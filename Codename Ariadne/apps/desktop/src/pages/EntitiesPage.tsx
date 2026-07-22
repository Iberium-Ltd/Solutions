/** Human-review gate for extracted entities, policy, temporal state, and provenance. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  Eye,
  Filter,
  LockKeyhole,
  PencilLine,
  ShieldCheck,
  SlidersHorizontal,
  Split,
} from 'lucide-react'
import { entities } from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel, Progress } from '../components/Primitives'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  decideEntity,
  loadEntityOrigins,
  reviewEntities as loadEntityReview,
  type EntityOriginProjection,
  type EntitySummaryWithOrigins,
} from '../app/phase3Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import type {
  EntityDecisionType,
  ReviewState,
  SearchPolicy,
  Sensitivity,
  TemporalState,
  TransmissionPolicy,
} from '../../../../packages/contracts/src/generated/api'

const sensitivityTone = {
  Public: 'green',
  Sensitive: 'violet',
  Restricted: 'rose',
} as const

export function EntitiesPage() {
  return nativeRuntimeAvailable() ? (
    <NativeEntitiesPage />
  ) : (
    <SimulatedEntitiesPage />
  )
}

interface DecisionDraft {
  readonly reviewState: Exclude<ReviewState, 'UNREVIEWED'>
  readonly sensitivity: Sensitivity
  readonly temporalState: TemporalState
  readonly searchPolicy: SearchPolicy
  readonly transmissionPolicy: TransmissionPolicy
}

type BulkDecisionDraft = Omit<DecisionDraft, 'sensitivity'>

interface EntityOriginView {
  readonly entityId: string
  readonly origins: ReadonlyArray<EntityOriginProjection>
  readonly total: number | null
  readonly hasMore: boolean
  readonly fullProfileScope: boolean
}

const nativeSensitivity = {
  PUBLIC: { label: 'Public', tone: 'green' },
  SENSITIVE: { label: 'Sensitive', tone: 'violet' },
  HIGHLY_SENSITIVE: { label: 'Highly sensitive', tone: 'rose' },
} as const

function words(value: string): string {
  return value
    .toLocaleLowerCase('en-US')
    .split('_')
    .map((part) => `${part.slice(0, 1).toLocaleUpperCase('en-US')}${part.slice(1)}`)
    .join(' ')
}

function draftFor(entity: EntitySummaryWithOrigins): DecisionDraft {
  return normaliseDraft({
    reviewState:
      entity.reviewState === 'UNREVIEWED' ? 'CONFIRMED' : entity.reviewState,
    sensitivity: entity.sensitivity,
    temporalState: entity.temporalState,
    searchPolicy: entity.searchPolicy,
    transmissionPolicy: entity.transmissionPolicy,
  })
}

function normaliseDraft(draft: DecisionDraft): DecisionDraft {
  if (
    draft.reviewState === 'EXCLUDED' ||
    draft.reviewState === 'FALSE_POSITIVE'
  ) {
    return {
      ...draft,
      searchPolicy: 'DENY',
      transmissionPolicy: 'NEVER',
    }
  }
  if (draft.sensitivity === 'HIGHLY_SENSITIVE') {
    return {
      ...draft,
      searchPolicy:
        draft.searchPolicy === 'ALLOW'
          ? 'REQUIRE_APPROVAL'
          : draft.searchPolicy,
      transmissionPolicy:
        draft.transmissionPolicy === 'POLICY_CONTROLLED'
          ? 'REQUIRE_EACH_APPROVAL'
          : draft.transmissionPolicy,
    }
  }
  return draft
}

function decisionType(
  entity: EntitySummaryWithOrigins,
  draft: DecisionDraft,
): EntityDecisionType {
  if (entity.reviewState === draft.reviewState) {
    const policyChanged =
      entity.sensitivity !== draft.sensitivity ||
      entity.temporalState !== draft.temporalState ||
      entity.searchPolicy !== draft.searchPolicy ||
      entity.transmissionPolicy !== draft.transmissionPolicy
    if (policyChanged) return 'POLICY_CHANGE'
  }
  if (draft.reviewState === 'CONFIRMED') return 'CONFIRM'
  if (draft.reviewState === 'FALSE_POSITIVE') return 'REJECT'
  if (draft.reviewState === 'EXCLUDED') return 'EXCLUDE'
  return 'CLASSIFY'
}

function decisionChanged(
  entity: EntitySummaryWithOrigins,
  draft: DecisionDraft,
): boolean {
  return (
    entity.reviewState !== draft.reviewState ||
    entity.sensitivity !== draft.sensitivity ||
    entity.temporalState !== draft.temporalState ||
    entity.searchPolicy !== draft.searchPolicy ||
    entity.transmissionPolicy !== draft.transmissionPolicy
  )
}

function originSpan(origin: EntitySummaryWithOrigins['origins'][number]): string {
  if (origin.sourceSpanStart === null || origin.sourceSpanEnd === null) {
    return 'Whole segment / no character span'
  }
  return `${origin.sourceSpanStart}–${origin.sourceSpanEnd}`
}

function observedTime(observedAtUs: number): {
  readonly iso: string
  readonly label: string
} {
  const iso = new Date(Math.trunc(observedAtUs / 1_000)).toISOString()
  return { iso, label: `${iso} · ${observedAtUs} µs` }
}

function NativeEntitiesPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const sourceId = usePhase3WorkflowStore((state) => state.sourceId)
  const [entityRows, setEntityRows] = useState<
    ReadonlyArray<EntitySummaryWithOrigins>
  >([])
  const [quarantineCount, setQuarantineCount] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [filter, setFilter] = useState<'ALL' | Sensitivity>('ALL')
  const [loadState, setLoadState] = useState<
    'NO_SOURCE' | 'LOADING' | 'READY' | 'ERROR'
  >('LOADING')
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null)
  const [draft, setDraft] = useState<DecisionDraft | null>(null)
  const [decisionPending, setDecisionPending] = useState(false)
  const [bulkDraft, setBulkDraft] = useState<BulkDecisionDraft>({
    reviewState: 'CONFIRMED',
    temporalState: 'CURRENT',
    searchPolicy: 'ALLOW',
    transmissionPolicy: 'POLICY_CONTROLLED',
  })
  const [originView, setOriginView] = useState<EntityOriginView | null>(null)
  const [originLoadPending, setOriginLoadPending] = useState(false)
  const [originLoadError, setOriginLoadError] = useState<string | null>(null)
  const [safeError, setSafeError] = useState<string | null>(null)
  const [refreshRevision, setRefreshRevision] = useState(0)
  const decisionIdempotencyKey = useRef(crypto.randomUUID())

  useEffect(() => {
    if (profileId === null) {
      setLoadState('NO_SOURCE')
      setEntityRows([])
      setSelectedEntityId(null)
      return
    }
    let cancelled = false
    setLoadState('LOADING')
    setSafeError(null)
    void loadEntityReview({ profileId, sourceId, limit: 100 })
      .then((result) => {
        if (cancelled) return
        if (result.profileId !== profileId) {
          throw new Error('Entity review response scope mismatch')
        }
        setEntityRows(result.entities)
        setQuarantineCount(result.quarantineCount)
        setHasMore(result.hasMore)
        setSelectedEntityId((current) =>
          result.entities.some((entity) => entity.entityId === current)
            ? current
            : (result.entities[0]?.entityId ?? null),
        )
        setLoadState('READY')
      })
      .catch(() => {
        if (cancelled) return
        setLoadState('ERROR')
        setSafeError(
          'Entity review could not load. Confirm the vault is unlocked and try again.',
        )
      })
    return () => {
      cancelled = true
    }
  }, [profileId, refreshRevision, sourceId])

  const selectedEntity = useMemo(
    () => entityRows.find((entity) => entity.entityId === selectedEntityId) ?? null,
    [entityRows, selectedEntityId],
  )

  useEffect(() => {
    setDraft(selectedEntity === null ? null : draftFor(selectedEntity))
    setOriginView(
      selectedEntity === null
        ? null
        : {
            entityId: selectedEntity.entityId,
            origins: selectedEntity.origins,
            total: null,
            hasMore: selectedEntity.originsTruncated,
            fullProfileScope: false,
          },
    )
    setOriginLoadPending(false)
    setOriginLoadError(null)
    decisionIdempotencyKey.current = crypto.randomUUID()
  }, [selectedEntity])

  const displayedOrigins =
    selectedEntity !== null && originView?.entityId === selectedEntity.entityId
      ? originView.origins
      : (selectedEntity?.origins ?? [])
  const displayedOriginTotal =
    selectedEntity !== null && originView?.entityId === selectedEntity.entityId
      ? originView.total
      : selectedEntity?.origins.length
  const displayedOriginsHaveMore =
    selectedEntity !== null && originView?.entityId === selectedEntity.entityId
      ? originView.hasMore
      : (selectedEntity?.originsTruncated ?? false)
  const fullProfileOriginsLoaded =
    selectedEntity !== null &&
    originView?.entityId === selectedEntity.entityId &&
    originView.fullProfileScope

  const visibleEntities = useMemo(
    () =>
      entityRows.filter(
        (entity) => filter === 'ALL' || entity.sensitivity === filter,
      ),
    [entityRows, filter],
  )
  const resolvedCount = entityRows.filter(
    (entity) => entity.reviewState !== 'UNREVIEWED',
  ).length
  const confirmedCount = entityRows.filter(
    (entity) => entity.reviewState === 'CONFIRMED',
  ).length
  const excludedCount = entityRows.filter((entity) =>
    ['FALSE_POSITIVE', 'EXCLUDED'].includes(entity.reviewState),
  ).length
  const needsReviewCount = entityRows.length - resolvedCount
  const bulkTargets = entityRows.filter(
    (entity) => entity.reviewState === 'UNREVIEWED',
  )
  const reviewPercent =
    entityRows.length === 0
      ? 0
      : Math.round((resolvedCount / entityRows.length) * 100)
  const readyForNext = entityRows.length > 0 && needsReviewCount === 0

  function updateDraft(patch: Partial<DecisionDraft>) {
    setDraft((current) =>
      current === null ? null : normaliseDraft({ ...current, ...patch }),
    )
    decisionIdempotencyKey.current = crypto.randomUUID()
  }

  async function loadMoreExactOrigins() {
    if (
      profileId === null ||
      selectedEntity === null ||
      originLoadPending ||
      (fullProfileOriginsLoaded && !displayedOriginsHaveMore)
    ) {
      return
    }
    const entityId = selectedEntity.entityId
    const offset = fullProfileOriginsLoaded ? displayedOrigins.length : 0
    setOriginLoadPending(true)
    setOriginLoadError(null)
    try {
      const result = await loadEntityOrigins({
        profileId,
        entityId,
        offset,
        limit: 12,
      })
      setOriginView((current) => {
        if (current === null || current.entityId !== entityId) return current
        return {
          entityId,
          origins: current.fullProfileScope
            ? [...current.origins, ...result.origins]
            : result.origins,
          total: result.total,
          hasMore: result.hasMore,
          fullProfileScope: true,
        }
      })
    } catch {
      setOriginLoadError(
        'Additional source origins could not load. Confirm the vault is unlocked and try again.',
      )
    } finally {
      setOriginLoadPending(false)
    }
  }

  async function submitDecision(
    entity: EntitySummaryWithOrigins,
    nextDraft: DecisionDraft,
  ) {
    if (
      profileId === null ||
      decisionPending ||
      !decisionChanged(entity, nextDraft)
    ) {
      return
    }
    setDecisionPending(true)
    setSafeError(null)
    try {
      const updated = await decideEntity({
        idempotencyKey: decisionIdempotencyKey.current,
        profileId,
        entityId: entity.entityId,
        expectedRevision: entity.revision,
        decisionType: decisionType(entity, nextDraft),
        ...nextDraft,
      })
      if (
        updated.entityId !== entity.entityId ||
        updated.revision <= entity.revision
      ) {
        throw new Error('Entity decision response scope mismatch')
      }
      setEntityRows((current) =>
        current.map((item) =>
          item.entityId === updated.entityId ? updated : item,
        ),
      )
      setSelectedEntityId(updated.entityId)
      setDraft(draftFor(updated))
      decisionIdempotencyKey.current = crypto.randomUUID()
    } catch {
      setSafeError(
        'The decision could not be saved. The review will be refreshed before another attempt.',
      )
      setRefreshRevision((current) => current + 1)
    } finally {
      setDecisionPending(false)
    }
  }

  function quickToggle(entity: EntitySummaryWithOrigins) {
    setSelectedEntityId(entity.entityId)
    const nextDraft = draftFor(entity)
    void submitDecision(
      entity,
      normaliseDraft({
        ...nextDraft,
        reviewState:
          entity.reviewState === 'CONFIRMED' ? 'EXCLUDED' : 'CONFIRMED',
      }),
    )
  }

  async function applyBulkDecision() {
    if (profileId === null || decisionPending || bulkTargets.length === 0) return
    setDecisionPending(true)
    setSafeError(null)
    const updatedById = new Map<string, EntitySummaryWithOrigins>()
    try {
      for (const entity of bulkTargets) {
        const nextDraft = normaliseDraft({
          ...draftFor(entity),
          ...bulkDraft,
        })
        const updated = await decideEntity({
          idempotencyKey: crypto.randomUUID(),
          profileId,
          entityId: entity.entityId,
          expectedRevision: entity.revision,
          decisionType: decisionType(entity, nextDraft),
          ...nextDraft,
        })
        if (
          updated.entityId !== entity.entityId ||
          updated.revision <= entity.revision
        ) {
          throw new Error('Bulk entity decision response scope mismatch')
        }
        updatedById.set(updated.entityId, updated)
      }
      setEntityRows((current) =>
        current.map((entity) => updatedById.get(entity.entityId) ?? entity),
      )
      const firstUpdated = updatedById.values().next().value
      if (firstUpdated !== undefined) setSelectedEntityId(firstUpdated.entityId)
    } catch {
      setSafeError(
        'Bulk review stopped before every decision was saved. The review will refresh to show the exact saved state.',
      )
      setRefreshRevision((current) => current + 1)
    } finally {
      setDecisionPending(false)
    }
  }

  return (
    <div className="page entities-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · step 3 of 7"
        title="Review extracted entities"
        description="Confirm, classify, exclude, and assign local policy before an entity can enter a search plan."
        meta={
          <>
            <Badge tone="cyan">{entityRows.length} candidates</Badge>
            <Badge tone="green">{resolvedCount} resolved</Badge>
            <Badge tone={quarantineCount > 0 ? 'rose' : 'green'}>{quarantineCount} quarantined</Badge>
          </>
        }
        actions={
          <Link className="button button--ghost" to="/audits/new/intake">
            <ArrowLeft size={14} /> Back
          </Link>
        }
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Audit type', 'Intake', 'Entities', 'Transmission', 'Plan', 'Budget', 'Review'].map((step, index) => (
          <li className={index < 2 ? 'is-complete' : index === 2 ? 'is-active' : ''} key={step}>
            <span>{index < 2 ? <Check size={11} /> : index + 1}</span><strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="entity-toolbar">
        <div className="entity-review-progress">
          <span>Review progress</span><Progress value={reviewPercent} tone="green" /><strong className="mono">{resolvedCount} / {entityRows.length}</strong>
        </div>
        <div className="segmented-control" aria-label="Filter entities">
          {([
            ['ALL', 'All'],
            ['PUBLIC', 'Public'],
            ['SENSITIVE', 'Sensitive'],
            ['HIGHLY_SENSITIVE', 'Highly sensitive'],
          ] as const).map(([value, label]) => (
            <button key={value} className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
        <Button variant="secondary" size="compact" onClick={() => setRefreshRevision((current) => current + 1)} disabled={loadState === 'LOADING'}><Filter size={13} /> Refresh</Button>
      </div>

      {safeError && <div className="callout callout--danger" role="alert"><CircleAlert size={14} /><span>{safeError}</span></div>}

      <div className="page-grid entity-grid">
        <Panel className="span-12" eyebrow="Bulk review" title="Apply shared settings to every unresolved candidate" action={<Badge tone={bulkTargets.length > 0 ? 'amber' : 'green'}>{bulkTargets.length} unresolved</Badge>}>
          <div className="panel__body entity-bulk-controls">
            <label className="field"><span>Decision</span><select className="select" aria-label="Bulk decision" value={bulkDraft.reviewState} onChange={(event) => setBulkDraft((current) => ({ ...current, reviewState: event.target.value as BulkDecisionDraft['reviewState'] }))} disabled={decisionPending}>
              <option value="CONFIRMED">Confirmed</option>
              <option value="PROBABLE">Probable</option>
              <option value="POSSIBLE">Possible</option>
              <option value="FALSE_POSITIVE">False positive</option>
              <option value="EXCLUDED">Excluded</option>
            </select></label>
            <label className="field"><span>Temporal state</span><select className="select" aria-label="Bulk temporal state" value={bulkDraft.temporalState} onChange={(event) => setBulkDraft((current) => ({ ...current, temporalState: event.target.value as TemporalState }))} disabled={decisionPending}>
              <option value="CURRENT">Current</option>
              <option value="HISTORICAL">Historical</option>
              <option value="UNKNOWN">Unknown</option>
            </select></label>
            <label className="field"><span>Search policy</span><select className="select" aria-label="Bulk search policy" value={bulkDraft.searchPolicy} onChange={(event) => setBulkDraft((current) => ({ ...current, searchPolicy: event.target.value as SearchPolicy }))} disabled={decisionPending || bulkDraft.reviewState === 'EXCLUDED' || bulkDraft.reviewState === 'FALSE_POSITIVE'}>
              <option value="ALLOW">Allow</option>
              <option value="REQUIRE_APPROVAL">Require approval</option>
              <option value="STORE_ONLY">Store only</option>
              <option value="DENY">Deny</option>
            </select></label>
            <label className="field"><span>Transmission</span><select className="select" aria-label="Bulk transmission policy" value={bulkDraft.transmissionPolicy} onChange={(event) => setBulkDraft((current) => ({ ...current, transmissionPolicy: event.target.value as TransmissionPolicy }))} disabled={decisionPending || bulkDraft.reviewState === 'EXCLUDED' || bulkDraft.reviewState === 'FALSE_POSITIVE'}>
              <option value="LOCAL_ONLY">Local only</option>
              <option value="POLICY_CONTROLLED">Policy controlled</option>
              <option value="REQUIRE_EACH_APPROVAL">Approve each disclosure</option>
              <option value="NEVER">Never</option>
            </select></label>
            <Button variant="primary" size="compact" onClick={() => void applyBulkDecision()} disabled={decisionPending || bulkTargets.length === 0}>{decisionPending ? 'Saving…' : `Apply to ${bulkTargets.length} unresolved`}</Button>
            <p className="entity-bulk-note">Sensitivity remains specific to each entity. Previously reviewed candidates are not changed.</p>
          </div>
        </Panel>
        <Panel className="span-9 panel--signal entity-table-panel" eyebrow="Identity compiler" title={`${visibleEntities.length} entity candidates`} action={<Badge tone="violet">Human review required</Badge>}>
          <div className="entity-table-wrap">
            <table className="data-table entity-table">
              <thead><tr><th>Use</th><th>Entity</th><th>Decision</th><th>Sensitivity</th><th>Transmission</th><th>Provenance</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {visibleEntities.map((entity) => {
                  const sensitivity = nativeSensitivity[entity.sensitivity]
                  const confirmed = entity.reviewState === 'CONFIRMED'
                  const localAiSuggestion = entity.provenanceLabel.startsWith('local-ai:')
                  return (
                    <tr key={entity.entityId} className={selectedEntityId === entity.entityId ? 'is-selected' : ''}>
                      <td>
                        <button
                          className={`entity-check ${confirmed ? 'is-checked' : ''}`}
                          onClick={() => quickToggle(entity)}
                          disabled={decisionPending}
                          aria-label={`${confirmed ? 'Exclude' : 'Confirm'} ${words(entity.entityType)} candidate`}
                        >{confirmed && <Check size={11} />}</button>
                      </td>
                      <td><div className="entity-value"><span>{words(entity.entityType)}</span><strong className={['EMAIL', 'USERNAME'].includes(entity.entityType.toLocaleUpperCase('en-US')) ? 'mono' : ''}>{entity.displayValue}</strong><small>{Math.round(entity.confidenceMicros / 10_000)}% extraction confidence</small></div></td>
                      <td><Badge tone={entity.reviewState === 'EXCLUDED' || entity.reviewState === 'FALSE_POSITIVE' ? 'rose' : entity.reviewState === 'PROBABLE' || entity.reviewState === 'POSSIBLE' ? 'amber' : 'cyan'}>{words(entity.reviewState)}</Badge></td>
                      <td><Badge tone={sensitivity.tone}>{sensitivity.label}</Badge></td>
                      <td><span className={`permission-label ${entity.transmissionPolicy === 'NEVER' ? 'is-denied' : ''}`}>{words(entity.transmissionPolicy)}</span></td>
                      <td><span className="provenance-cell"><Eye size={12} /><span>{localAiSuggestion ? 'Local AI suggestion · probable · review required' : entity.provenanceLabel}<small>{entity.origins.length} exact source {entity.origins.length === 1 ? 'origin' : 'origins'}{entity.originsTruncated ? ' · more omitted' : ''}</small></span></span></td>
                      <td><button className="icon-button" aria-label={`Edit ${words(entity.entityType)} candidate`} onClick={() => setSelectedEntityId(entity.entityId)}><PencilLine size={13} /></button></td>
                    </tr>
                  )
                })}
                {visibleEntities.length === 0 && (
                  <tr><td colSpan={7}><span className="entity-empty-row">{loadState === 'LOADING' ? 'Loading encrypted profile…' : loadState === 'NO_SOURCE' ? 'Complete local intake before reviewing entities.' : 'No entities match this filter.'}</span></td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="span-3 stack">
          <Panel eyebrow="Human review" title="Decision controls">
            <div className="panel__body entity-decision-form">
              {selectedEntity !== null && draft !== null ? (
                <>
                  <div className="entity-decision-target"><span>{words(selectedEntity.entityType)}</span><strong>{selectedEntity.displayValue}</strong></div>
                  <label className="field"><span>Decision</span><select className="select" aria-label="Decision" value={draft.reviewState} onChange={(event) => updateDraft({ reviewState: event.target.value as DecisionDraft['reviewState'] })} disabled={decisionPending}>
                    <option value="CONFIRMED">Confirmed</option>
                    <option value="PROBABLE">Probable</option>
                    <option value="POSSIBLE">Possible</option>
                    <option value="FALSE_POSITIVE">False positive</option>
                    <option value="EXCLUDED">Excluded</option>
                  </select></label>
                  <label className="field"><span>Sensitivity</span><select className="select" aria-label="Sensitivity" value={draft.sensitivity} onChange={(event) => updateDraft({ sensitivity: event.target.value as Sensitivity })} disabled={decisionPending}>
                    <option value="PUBLIC">Public</option>
                    <option value="SENSITIVE">Sensitive</option>
                    <option value="HIGHLY_SENSITIVE">Highly sensitive</option>
                  </select></label>
                  <label className="field"><span>Temporal state</span><select className="select" aria-label="Temporal state" value={draft.temporalState} onChange={(event) => updateDraft({ temporalState: event.target.value as TemporalState })} disabled={decisionPending}>
                    <option value="CURRENT">Current</option>
                    <option value="HISTORICAL">Historical</option>
                    <option value="UNKNOWN">Unknown</option>
                  </select></label>
                  <label className="field"><span>Search policy</span><select className="select" aria-label="Search policy" value={draft.searchPolicy} onChange={(event) => updateDraft({ searchPolicy: event.target.value as SearchPolicy })} disabled={decisionPending || draft.reviewState === 'EXCLUDED' || draft.reviewState === 'FALSE_POSITIVE'}>
                    <option value="ALLOW">Allow</option>
                    <option value="REQUIRE_APPROVAL">Require approval</option>
                    <option value="STORE_ONLY">Store only</option>
                    <option value="DENY">Deny</option>
                  </select></label>
                  <label className="field"><span>Transmission</span><select className="select" aria-label="Transmission policy" value={draft.transmissionPolicy} onChange={(event) => updateDraft({ transmissionPolicy: event.target.value as TransmissionPolicy })} disabled={decisionPending || draft.reviewState === 'EXCLUDED' || draft.reviewState === 'FALSE_POSITIVE'}>
                    <option value="LOCAL_ONLY">Local only</option>
                    <option value="POLICY_CONTROLLED">Policy controlled</option>
                    <option value="REQUIRE_EACH_APPROVAL">Approve each disclosure</option>
                    <option value="NEVER">Never</option>
                  </select></label>
                  <Button variant="primary" size="compact" onClick={() => void submitDecision(selectedEntity, draft)} disabled={decisionPending || !decisionChanged(selectedEntity, draft)}>{decisionPending ? 'Saving…' : 'Apply decision'}</Button>
                </>
              ) : (
                <div className="callout"><PencilLine size={14} /><span>Select an entity to review its classification and policies.</span></div>
              )}
            </div>
          </Panel>
          <Panel
            eyebrow="Exact provenance"
            title="Source origins"
            action={
              selectedEntity === null ? undefined : (
                <Badge tone={displayedOriginsHaveMore ? 'amber' : 'cyan'}>
                  {!fullProfileOriginsLoaded || displayedOriginTotal === null
                    ? `${displayedOrigins.length} shown`
                    : `${displayedOrigins.length} / ${displayedOriginTotal}`}
                </Badge>
              )
            }
          >
            <div className="panel__body entity-origin-list">
              {selectedEntity === null ? (
                <div className="callout"><Eye size={14} /><span>Select an entity to inspect its exact source origins.</span></div>
              ) : (
                <>
                  {displayedOrigins.map((origin, index) => {
                    const observed = observedTime(origin.observedAtUs)
                    return (
                      <article
                        className="entity-origin-card"
                        data-testid="entity-origin-card"
                        key={`${origin.sourceId}:${origin.segmentId}:${origin.sourceSpanStart ?? 'segment'}:${origin.extractionRunId ?? origin.originKind}:${index}`}
                      >
                        <header>
                          <strong>{origin.sourceDisplayName}</strong>
                          <Badge tone={origin.originKind === 'LOCAL_MODEL' ? 'violet' : 'green'}>{words(origin.originKind)}</Badge>
                        </header>
                        <dl>
                          <div><dt>Source ID</dt><dd className="mono">{origin.sourceId}</dd></div>
                          <div><dt>SHA-256</dt><dd className="mono">{origin.sourceSha256}</dd></div>
                          <div><dt>Segment</dt><dd><span className="mono">{origin.segmentId}</span><small>Index {origin.segmentIndex} · span {originSpan(origin)}</small></dd></div>
                          <div><dt>Locator</dt><dd className="mono">{origin.segmentLocator}</dd></div>
                          <div><dt>Extractor</dt><dd>{origin.extractorName === null ? 'None · direct origin' : `${origin.extractorKind} · ${origin.extractorName} v${origin.extractorVersion}`}</dd></div>
                          <div><dt>Run ID</dt><dd className="mono">{origin.extractionRunId ?? 'None · direct origin'}</dd></div>
                          <div><dt>Observed</dt><dd><time dateTime={observed.iso}>{observed.label}</time></dd></div>
                          <div><dt>Confidence</dt><dd>{Math.round(origin.confidenceMicros / 10_000)}% · <span className="mono">{origin.confidenceMicros} µ</span></dd></div>
                        </dl>
                        <p>{origin.explanation}</p>
                      </article>
                    )
                  })}
                  {!fullProfileOriginsLoaded && (
                    <div className="entity-origin-pagination">
                      <div className={selectedEntity.originsTruncated ? 'callout callout--warning' : 'callout'} role="status">
                        <Eye size={14} />
                        <span>{selectedEntity.originsTruncated ? `The bounded summary shows ${displayedOrigins.length} exact origins.` : `The current review shows ${displayedOrigins.length} exact ${displayedOrigins.length === 1 ? 'origin' : 'origins'}.`} Load the full-profile provenance pages to inspect every stored origin for this entity.</span>
                      </div>
                      <Button
                        variant="secondary"
                        size="compact"
                        onClick={() => void loadMoreExactOrigins()}
                        disabled={originLoadPending}
                      >
                        <Eye size={13} />
                        {originLoadPending ? 'Loading exact origins…' : 'Inspect all stored origins'}
                      </Button>
                    </div>
                  )}
                  {fullProfileOriginsLoaded && displayedOriginsHaveMore && (
                    <div className="entity-origin-pagination">
                      <div className="callout callout--warning" role="status">
                        <CircleAlert size={14} />
                        <span>Showing {displayedOrigins.length} of {displayedOriginTotal} full-profile exact origins.</span>
                      </div>
                      <Button
                        variant="secondary"
                        size="compact"
                        onClick={() => void loadMoreExactOrigins()}
                        disabled={originLoadPending}
                      >
                        <Eye size={13} />
                        {originLoadPending ? 'Loading exact origins…' : 'Load next exact origins'}
                      </Button>
                    </div>
                  )}
                  {fullProfileOriginsLoaded && !displayedOriginsHaveMore && displayedOriginTotal !== null && (
                    <div className="callout" role="status">
                      <ShieldCheck size={14} />
                      <span>All {displayedOriginTotal} stored exact origins are loaded.</span>
                    </div>
                  )}
                  {originLoadError !== null && (
                    <div className="callout callout--danger" role="alert">
                      <CircleAlert size={14} />
                      <span>{originLoadError}</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </Panel>
          <Panel eyebrow="Profile boundary" title="Decision summary">
            <div className="panel__body entity-summary">
              <div><span>Confirmed</span><strong className="mono">{confirmedCount}</strong></div>
              <div><span>Excluded</span><strong className="mono">{excludedCount}</strong></div>
              <div><span>Needs review</span><strong className="mono">{needsReviewCount}</strong></div>
              <div><span>More available</span><strong>{hasMore ? 'Yes' : 'No'}</strong></div>
            </div>
          </Panel>
          <Panel eyebrow="Safety control" title="Restricted quarantine">
            <div className="panel__body stack">
              <div className="quarantine-mini"><LockKeyhole size={15} /><div><strong>{quarantineCount} values suppressed</strong><span>Never returned to the review interface or query planning.</span></div></div>
              <div className="callout"><ShieldCheck size={13} /><span>Every saved decision is revision checked and audit recorded.</span></div>
            </div>
          </Panel>
        </div>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <SlidersHorizontal size={16} />
            <div><strong>{readyForNext ? 'Next: run the complete audit.' : 'Resolve every candidate before starting discovery.'}</strong><span>The persistent Person workspace automatically seeds discovery from these reviewed identifiers.</span></div>
          </div>
          <Link className={`button button--primary ${!readyForNext ? 'is-disabled' : ''}`} aria-disabled={!readyForNext} to={readyForNext ? '/people?start=1' : '#'}>
            Continue to full audit <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </div>
  )
}

function SimulatedEntitiesPage() {
  const [filter, setFilter] = useState('All')
  const [approved, setApproved] = useState<Set<string>>(
    () => new Set(entities.slice(0, 5).map((entity) => entity.id)),
  )
  const visibleEntities = useMemo(
    () => entities.filter((entity) => filter === 'All' || entity.sensitivity === filter),
    [filter],
  )

  function toggleApproval(id: string) {
    setApproved((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="page entities-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · step 3 of 7"
        title="Review extracted entities"
        description="Correct, classify, approve, exclude, and assign transmission rules before an entity can enter a search plan."
        meta={
          <>
            <Badge tone="cyan">6 candidates</Badge>
            <Badge tone="green">5 resolved</Badge>
            <Badge tone="rose">1 quarantined</Badge>
          </>
        }
        actions={
          <Link className="button button--ghost" to="/audits/new/intake">
            <ArrowLeft size={14} /> Back
          </Link>
        }
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Audit type', 'Intake', 'Entities', 'Transmission', 'Plan', 'Budget', 'Review'].map((step, index) => (
          <li className={index < 2 ? 'is-complete' : index === 2 ? 'is-active' : ''} key={step}>
            <span>{index < 2 ? <Check size={11} /> : index + 1}</span><strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="entity-toolbar">
        <div className="entity-review-progress">
          <span>Review progress</span><Progress value={83} tone="green" /><strong className="mono">5 / 6</strong>
        </div>
        <div className="segmented-control" aria-label="Filter entities">
          {['All', 'Public', 'Sensitive', 'Restricted'].map((option) => (
            <button key={option} className={filter === option ? 'is-active' : ''} onClick={() => setFilter(option)}>{option}</button>
          ))}
        </div>
        <Button variant="secondary" size="compact"><Filter size={13} /> More filters</Button>
      </div>

      <div className="page-grid entity-grid">
        <Panel className="span-9 panel--signal entity-table-panel" eyebrow="Identity compiler" title={`${visibleEntities.length} entity candidates`} action={<Badge tone="violet">Human review required</Badge>}>
          <div className="entity-table-wrap">
            <table className="data-table entity-table">
              <thead><tr><th>Use</th><th>Entity</th><th>Decision</th><th>Sensitivity</th><th>Transmission</th><th>Provenance</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {visibleEntities.map((entity) => (
                  <tr key={entity.id} className={entity.sensitivity === 'Restricted' ? 'is-quarantined' : ''}>
                    <td>
                      <button
                        className={`entity-check ${approved.has(entity.id) ? 'is-checked' : ''}`}
                        onClick={() => toggleApproval(entity.id)}
                        disabled={entity.sensitivity === 'Restricted'}
                        aria-label={`${approved.has(entity.id) ? 'Remove' : 'Add'} ${entity.value} from approved profile`}
                      >{approved.has(entity.id) && <Check size={11} />}</button>
                    </td>
                    <td><div className="entity-value"><span>{entity.type}</span><strong className={entity.type === 'Email' || entity.type === 'Username' ? 'mono' : ''}>{entity.value}</strong><small>{entity.confidence}% extraction confidence</small></div></td>
                    <td><Badge tone={entity.decision === 'Excluded' ? 'rose' : entity.decision === 'Probable' ? 'amber' : 'cyan'}>{entity.decision}</Badge></td>
                    <td><Badge tone={sensitivityTone[entity.sensitivity]}>{entity.sensitivity}</Badge></td>
                    <td><span className={`permission-label ${entity.permission === 'Never transmit' ? 'is-denied' : ''}`}>{entity.permission}</span></td>
                    <td><span className="provenance-cell"><Eye size={12} /> {entity.provenance}</span></td>
                    <td><button className="icon-button" aria-label={`Edit ${entity.value}`}><PencilLine size={13} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="span-3 stack">
          <Panel eyebrow="Profile boundary" title="Decision summary">
            <div className="panel__body entity-summary">
              <div><span>Approved</span><strong className="mono">{approved.size}</strong></div>
              <div><span>Store only</span><strong className="mono">1</strong></div>
              <div><span>Excluded</span><strong className="mono">1</strong></div>
              <div><span>Needs review</span><strong className="mono">1</strong></div>
            </div>
          </Panel>
          <Panel eyebrow="Safety control" title="Restricted quarantine">
            <div className="panel__body stack">
              <div className="quarantine-mini"><LockKeyhole size={15} /><div><strong>Value suppressed</strong><span>Never part of a query or export.</span></div></div>
              <Button variant="ghost" size="compact"><ShieldCheck size={13} /> Review locally</Button>
            </div>
          </Panel>
          <Panel eyebrow="Ariadne Core" title="Merge safeguards">
            <div className="panel__body stack">
              <div className="callout"><Split size={14} /><span>Same-name and same-handle entities stay separate until corroborated.</span></div>
              <div className="callout callout--warning"><CircleAlert size={14} /><span>One chronology conflict remains visible.</span></div>
            </div>
          </Panel>
        </div>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <SlidersHorizontal size={16} />
            <div><strong>Next: transmission preflight.</strong><span>Provider, jurisdiction, exact payload, purpose, retention, and cost will be shown before approval.</span></div>
          </div>
          <Link className="button button--primary" to="/privacy/transmission?from=audit-builder">
            Review transmission <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </div>
  )
}
