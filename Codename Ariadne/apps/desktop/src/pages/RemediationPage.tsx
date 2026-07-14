import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Columns3,
  FilePenLine,
  List,
  MessageSquareText,
  Paperclip,
  Plus,
  RotateCcw,
  Scale,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { remediationColumns } from '@ariadne/synthetic-data'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { loadPhase5Finding } from '../app/phase5Boundary'
import {
  linkPhase6RemediationEvidence,
  loadPhase6RemediationCase,
  loadPhase6RemediationCases,
  recordPhase6ProviderResponse,
  recordPhase6Reappearance,
  requirePhase6RemediationApproval,
  setPhase6RemediationDeadline,
  transitionPhase6RemediationStatus,
  updatePhase6RemediationDraft,
  type Phase6RemediationCase,
  type Phase6RemediationCaseList,
  type Phase6RemediationCaseSummary,
  type Phase6RemediationStatus,
} from '../app/phase6Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Phase6StatePanel } from '../components/Phase6StatePanel'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  type Tone,
} from '../components/Primitives'
import '../styles/pages-controls.css'

type ViewMode = 'board' | 'list'

type CaseDetails = {
  owner: string
  jurisdiction: string
  evidence: string
  response: string
  nextCheck: string
  reappearance: string
  legalBasis: string
  reference: string
}

const detailByTitle: Record<string, CaseDetails> = {
  'Legacy community profile': {
    owner: 'You', jurisdiction: 'EU · synthetic', evidence: '2 artifacts', response: 'Not contacted',
    nextCheck: 'After evidence review', reappearance: 'First observation', legalBasis: 'Account correction', reference: 'REM-SYN-014',
  },
  'Archived biography': {
    owner: 'Review queue', jurisdiction: 'NL · synthetic', evidence: '1 artifact', response: 'Not contacted',
    nextCheck: '14 Aug 2026', reappearance: 'Archive remains', legalBasis: 'Assess persistence', reference: 'REM-SYN-018',
  },
  'Directory correction': {
    owner: 'You', jurisdiction: 'DE · synthetic', evidence: '3 artifacts', response: 'Draft only',
    nextCheck: '16 Jul 2026', reappearance: 'No prior removal', legalBasis: 'Source correction', reference: 'REM-SYN-021',
  },
  'Search result cache': {
    owner: 'You', jurisdiction: 'EU · synthetic', evidence: '2 artifacts', response: 'Draft only',
    nextCheck: '18 Jul 2026', reappearance: 'Cache observed', legalBasis: 'Deindexing request', reference: 'REM-SYN-023',
  },
  'Profile removal': {
    owner: 'You', jurisdiction: 'FI · synthetic', evidence: '4 artifacts', response: 'Acknowledged · simulated',
    nextCheck: '26 Jul 2026', reappearance: 'Not yet checked', legalBasis: 'Owned-account deletion', reference: 'REM-SYN-025',
  },
  'Archive reappearance': {
    owner: 'Monitor', jurisdiction: 'NL · synthetic', evidence: '5 artifacts', response: 'Previously removed',
    nextCheck: '11 Aug 2026', reappearance: 'Reappeared 11 Jul', legalBasis: 'Monitoring', reference: 'REM-SYN-031',
  },
  'Confirmed non-match': {
    owner: 'Monitor', jurisdiction: 'Local', evidence: '1 decision', response: 'No action',
    nextCheck: '11 Oct 2026', reappearance: 'Exclusion watch', legalBasis: 'False-positive exclusion', reference: 'REM-SYN-034',
  },
}

const priorityTone = (priority: string) => {
  if (priority === 'High') return 'rose' as const
  if (priority === 'Medium') return 'amber' as const
  return 'blue' as const
}

function SimulatedRemediationPage() {
  const [view, setView] = useState<ViewMode>('board')
  const [selectedTitle, setSelectedTitle] = useState('Legacy community profile')
  const [draftReady, setDraftReady] = useState(false)
  const [historyAdded, setHistoryAdded] = useState(false)

  const selected = detailByTitle[selectedTitle]
  const allItems = useMemo(
    () => remediationColumns.flatMap((column) =>
      column.items.map((item) => ({ ...item, column: column.title })),
    ),
    [],
  )

  useEffect(() => {
    document.title = 'Removal Tracker · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  return (
    <div className="page controls-page remediation-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Removal Tracker · 7 active cases"
        title="Remediation stays reviewed"
        description="Track evidence, deadlines, provider responses, rechecks, and reappearance without automatically sending a legal, deletion, or impersonation request."
        meta={
          <>
            <Badge tone="rose" dot>2 need attention</Badge>
            <Badge tone="amber">1 awaiting response</Badge>
            <Badge tone="cyan">All external actions are drafts</Badge>
          </>
        }
        actions={
          <>
            <div className="segmented-control" aria-label="Remediation layout">
              <button type="button" className={view === 'board' ? 'is-active' : ''} onClick={() => setView('board')} aria-pressed={view === 'board'}>
                <Columns3 size={13} aria-hidden="true" /> Board
              </button>
              <button type="button" className={view === 'list' ? 'is-active' : ''} onClick={() => setView('list')} aria-pressed={view === 'list'}>
                <List size={13} aria-hidden="true" /> List
              </button>
            </div>
            <Button variant="primary"><Plus size={15} aria-hidden="true" /> New case</Button>
          </>
        }
      />

      <div className="controls-remediation-summary" aria-label="Remediation attention summary">
        <article>
          <span className="status-icon status-icon--rose"><CalendarClock size={16} /></span>
          <div><strong>2 due within 48 hours</strong><small>Evidence preservation leads; no external send is scheduled.</small></div>
          <Badge tone="rose">Attention</Badge>
        </article>
        <article>
          <span className="status-icon status-icon--amber"><MessageSquareText size={16} /></span>
          <div><strong>1 simulated response</strong><small>Profile removal acknowledgement awaits a bounded recheck.</small></div>
          <Badge tone="amber">Waiting</Badge>
        </article>
        <article>
          <span className="status-icon status-icon--violet"><RotateCcw size={16} /></span>
          <div><strong>1 item reappeared</strong><small>Archived content remains distinct from a live source.</small></div>
          <Badge tone="violet">Review</Badge>
        </article>
      </div>

      <div className={`controls-remediation-workspace is-${view}`}>
        <Panel
          className="controls-remediation-board panel--raised"
          eyebrow="Active work"
          title={view === 'board' ? 'Status board' : 'Grouped case list'}
          action={<Badge>{allItems.length} synthetic cases</Badge>}
        >
          {view === 'board' ? (
            <div className="controls-board-scroll" role="region" aria-label="Remediation status board" tabIndex={0}>
              <div className="controls-board">
                {remediationColumns.map((column) => (
                  <section className="controls-board-column" key={column.id} aria-labelledby={`column-${column.id}`}>
                    <header>
                      <h3 id={`column-${column.id}`}>{column.title}</h3>
                      <span>{column.items.length}</span>
                    </header>
                    <div className="controls-board-column__items">
                      {column.items.map((item) => {
                        const detail = detailByTitle[item.title]
                        return (
                          <button
                            type="button"
                            className={`controls-remediation-card ${selectedTitle === item.title ? 'is-selected' : ''}`}
                            key={item.title}
                            onClick={() => setSelectedTitle(item.title)}
                          >
                            <div className="controls-remediation-card__top">
                              <Badge tone={priorityTone(item.priority)}>{item.priority}</Badge>
                              <span className="mono">{detail.reference}</span>
                            </div>
                            <strong>{item.title}</strong>
                            <small>{item.action}</small>
                            <div className="controls-remediation-card__meta">
                              <span><UserRound size={11} /> {detail.owner}</span>
                              <span><CalendarClock size={11} /> {item.due}</span>
                            </div>
                            <div className="controls-remediation-card__footer">
                              <span><Paperclip size={11} /> {detail.evidence}</span>
                              <span>{detail.jurisdiction}</span>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          ) : (
            <div className="controls-remediation-list">
              {allItems.map((item) => {
                const detail = detailByTitle[item.title]
                return (
                  <button type="button" key={item.title} onClick={() => setSelectedTitle(item.title)} className={selectedTitle === item.title ? 'is-selected' : ''}>
                    <span><Badge tone={priorityTone(item.priority)}>{item.priority}</Badge></span>
                    <span><strong>{item.title}</strong><small>{item.action} · {detail.reference}</small></span>
                    <span>{item.column}</span>
                    <span>{detail.owner}</span>
                    <span>{item.due}</span>
                  </button>
                )
              })}
            </div>
          )}
        </Panel>

        <Panel
          className="controls-remediation-inspector panel--raised"
          eyebrow="Selected case"
          title={selectedTitle}
          action={<Badge tone="cyan">{selected.reference}</Badge>}
        >
          <div className="controls-draft-boundary">
            <ShieldCheck size={16} aria-hidden="true" />
            <span>Nothing is sent without explicit review and approval.</span>
          </div>
          <dl className="controls-compact-dl">
            <div><dt>Owner</dt><dd>{selected.owner}</dd></div>
            <div><dt>Jurisdiction</dt><dd>{selected.jurisdiction}</dd></div>
            <div><dt>Request basis</dt><dd>{selected.legalBasis}</dd></div>
            <div><dt>Evidence</dt><dd>{selected.evidence}</dd></div>
            <div><dt>Provider response</dt><dd>{selected.response}</dd></div>
            <div><dt>Next recheck</dt><dd>{selected.nextCheck}</dd></div>
            <div><dt>Reappearance</dt><dd>{selected.reappearance}</dd></div>
          </dl>

          <div className="controls-case-history">
            <h3>Case history</h3>
            <ol>
              <li><span>11 Jul · 14:42</span><strong>Evidence attached</strong><small>Synthetic artifact EV-SYN-04</small></li>
              <li><span>11 Jul · 14:38</span><strong>Case created</strong><small>Human decision from finding review</small></li>
              {historyAdded && <li><span>11 Jul · 14:48</span><strong>Local note saved</strong><small>No external action performed</small></li>}
            </ol>
          </div>

          {draftReady && (
            <div className="controls-callout controls-callout--success" role="status">
              <CheckCircle2 size={16} aria-hidden="true" />
              <span>Draft prepared locally with evidence list and uncertainty language.</span>
            </div>
          )}

          <div className="controls-inspector-actions controls-inspector-actions--stack">
            <Button variant="primary" onClick={() => setDraftReady(true)}>
              <FilePenLine size={14} aria-hidden="true" /> Prepare reviewed draft
            </Button>
            <Button onClick={() => setHistoryAdded(true)} disabled={historyAdded}>
              <MessageSquareText size={14} aria-hidden="true" /> Add local note
            </Button>
          </div>
          <div className="controls-legal-note">
            <Scale size={14} aria-hidden="true" />
            <span>Templates organise user-provided facts; they are not legal advice.</span>
          </div>
        </Panel>
      </div>

      <div className="controls-callout controls-callout--amber">
        <AlertTriangle size={16} aria-hidden="true" />
        <span>
          A source marked removed may remain in search caches, mirrors, or archives.
          Rechecks record each surface independently.
        </span>
      </div>
    </div>
  )
}

const nativeStatusTone: Record<Phase6RemediationStatus, Tone> = {
  OPEN: 'cyan',
  IN_PROGRESS: 'violet',
  AWAITING_EXPLICIT_APPROVAL: 'amber',
  MONITORING: 'blue',
  RESOLVED: 'green',
  CLOSED: 'neutral',
}

const localRemediationActions = new Set([
  'MONITOR',
  'PRESERVE_EVIDENCE',
] as const)

const allowedStatusTransitions: Record<
  Phase6RemediationStatus,
  ReadonlyArray<Phase6RemediationStatus>
> = {
  OPEN: ['IN_PROGRESS', 'AWAITING_EXPLICIT_APPROVAL', 'MONITORING', 'RESOLVED', 'CLOSED'],
  IN_PROGRESS: ['AWAITING_EXPLICIT_APPROVAL', 'MONITORING', 'RESOLVED', 'CLOSED'],
  AWAITING_EXPLICIT_APPROVAL: ['IN_PROGRESS', 'MONITORING', 'CLOSED'],
  MONITORING: ['IN_PROGRESS', 'AWAITING_EXPLICIT_APPROVAL', 'RESOLVED', 'CLOSED'],
  RESOLVED: ['IN_PROGRESS', 'MONITORING', 'CLOSED'],
  CLOSED: [],
}

type Phase6MutationStatus = {
  readonly tone: 'success' | 'danger'
  readonly message: string
}

type AvailableEvidence = {
  readonly artifactId: string
  readonly findingId: string
  readonly providerId: string
  readonly label: string
}

const nativeCaseGroups: ReadonlyArray<{
  readonly id: string
  readonly title: string
  readonly statuses: ReadonlySet<Phase6RemediationStatus>
}> = [
  { id: 'open', title: 'Open', statuses: new Set(['OPEN']) },
  {
    id: 'active',
    title: 'Active review',
    statuses: new Set(['IN_PROGRESS', 'AWAITING_EXPLICIT_APPROVAL']),
  },
  { id: 'monitoring', title: 'Monitoring', statuses: new Set(['MONITORING']) },
  {
    id: 'closed',
    title: 'Resolved / closed',
    statuses: new Set(['RESOLVED', 'CLOSED']),
  },
]

function words(value: string): string {
  return value
    .toLocaleLowerCase()
    .replaceAll('_', ' ')
    .replace(/^./, (character) => character.toLocaleUpperCase())
}

function displayTime(timestampUs: number | null): string {
  if (timestampUs === null) return 'Not set'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(new Date(Math.floor(timestampUs / 1_000)))
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`
}

function deadlineInputValue(timestampUs: number | null): string {
  if (timestampUs === null) return ''
  const date = new Date(Math.floor(timestampUs / 1_000))
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function MutationStatus({ status }: { readonly status: Phase6MutationStatus | null }) {
  if (status === null) return null
  return (
    <div
      className={`phase6-mutation-status callout callout--${status.tone}`}
      role={status.tone === 'danger' ? 'alert' : 'status'}
    >
      {status.tone === 'success' ? (
        <CheckCircle2 size={14} aria-hidden="true" />
      ) : (
        <AlertTriangle size={14} aria-hidden="true" />
      )}
      <span>{status.message}</span>
    </div>
  )
}

function EvidenceChoices({
  evidence,
  selected,
  onChange,
  disabled,
  emptyCopy,
}: {
  readonly evidence: ReadonlyArray<AvailableEvidence>
  readonly selected: ReadonlySet<string>
  readonly onChange: (artifactId: string, checked: boolean) => void
  readonly disabled: boolean
  readonly emptyCopy: string
}) {
  if (evidence.length === 0) return <small>{emptyCopy}</small>
  return (
    <div className="phase6-evidence-options">
      {evidence.map((artifact) => (
        <label key={artifact.artifactId}>
          <input
            type="checkbox"
            checked={selected.has(artifact.artifactId)}
            disabled={disabled}
            onChange={(event) => onChange(artifact.artifactId, event.target.checked)}
          />
          <span>{artifact.label}</span>
        </label>
      ))}
    </div>
  )
}

function NativeCaseCard({
  item,
  selected,
  onSelect,
}: {
  readonly item: Phase6RemediationCaseSummary
  readonly selected: boolean
  readonly onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`controls-remediation-card ${selected ? 'is-selected' : ''}`}
      onClick={onSelect}
    >
      <div className="controls-remediation-card__top">
        <Badge tone={nativeStatusTone[item.status]}>{words(item.status)}</Badge>
        <span className="mono">{shortId(item.caseId)}</span>
      </div>
      <strong>{words(item.action)}</strong>
      <small>{words(item.actionDisposition)}</small>
      <div className="controls-remediation-card__meta">
        <span><UserRound size={11} /> {item.findingIds.length} finding{item.findingIds.length === 1 ? '' : 's'}</span>
        <span><CalendarClock size={11} /> {item.deadlineAtUs === null ? 'No deadline' : displayTime(item.deadlineAtUs)}</span>
      </div>
      <div className="controls-remediation-card__footer">
        <span><Paperclip size={11} /> Revision {item.revision}</span>
        <span>{item.reappearanceCount} reappearance{item.reappearanceCount === 1 ? '' : 's'}</span>
      </div>
    </button>
  )
}

function NativeCaseInspector({
  profileId,
  case_,
  onMutated,
  onReload,
}: {
  readonly profileId: string
  readonly case_: Phase6RemediationCase
  readonly onMutated: (case_: Phase6RemediationCase) => void
  readonly onReload: () => void
}) {
  const [draftText, setDraftText] = useState(case_.draftText ?? '')
  const [deadline, setDeadline] = useState(deadlineInputValue(case_.deadlineAtUs))
  const [targetStatus, setTargetStatus] = useState<Phase6RemediationStatus | ''>('')
  const [statusNote, setStatusNote] = useState('')
  const [providerId, setProviderId] = useState('')
  const [responseCode, setResponseCode] = useState('RECEIVED')
  const [responseSummary, setResponseSummary] = useState('')
  const [reappearanceFindingId, setReappearanceFindingId] = useState(case_.findingIds[0] ?? '')
  const [linkSelection, setLinkSelection] = useState<ReadonlySet<string>>(new Set())
  const [responseEvidence, setResponseEvidence] = useState<ReadonlySet<string>>(new Set())
  const [reappearanceEvidence, setReappearanceEvidence] = useState<ReadonlySet<string>>(new Set())
  const [busyOperation, setBusyOperation] = useState<string | null>(null)
  const [mutationStatus, setMutationStatus] = useState<Phase6MutationStatus | null>(null)
  const evidenceKey = `${profileId}:${case_.findingIds.join(':')}`
  const [evidenceResult, setEvidenceResult] = useState<{
    readonly key: string
    readonly evidence: ReadonlyArray<AvailableEvidence>
  } | null>(null)
  const [evidenceErrorKey, setEvidenceErrorKey] = useState<string | null>(null)
  const [evidenceRevision, setEvidenceRevision] = useState(0)

  const transitions = useMemo(
    () => allowedStatusTransitions[case_.status].filter(
      (value) =>
        value !== 'AWAITING_EXPLICIT_APPROVAL' ||
        case_.actionDisposition === 'REQUIRE_EXPLICIT_APPROVAL',
    ),
    [case_.actionDisposition, case_.status],
  )
  const isLocalAction = localRemediationActions.has(
    case_.action as 'MONITOR' | 'PRESERVE_EVIDENCE',
  )

  useEffect(() => {
    setDraftText(case_.draftText ?? '')
    setDeadline(deadlineInputValue(case_.deadlineAtUs))
    setTargetStatus(transitions[0] ?? '')
    setStatusNote('')
    setReappearanceFindingId(case_.findingIds[0] ?? '')
    setLinkSelection(new Set())
    setResponseEvidence(new Set())
    setReappearanceEvidence(new Set())
  }, [
    case_.caseId,
    case_.deadlineAtUs,
    case_.draftText,
    case_.findingIds,
    case_.revision,
    transitions,
  ])

  useEffect(() => {
    let cancelled = false
    setEvidenceErrorKey(null)
    void Promise.all(
      case_.findingIds.map((findingId) =>
        loadPhase5Finding({ profileId, findingId }),
      ),
    )
      .then((details) => {
        if (cancelled) return
        const byId = new Map<string, AvailableEvidence>()
        for (const detail of details) {
          detail.artifacts.forEach((artifact, index) => {
            byId.set(artifact.artifactId, {
              artifactId: artifact.artifactId,
              findingId: detail.finding.findingId,
              providerId: artifact.providerId,
              label: `${shortId(detail.finding.findingId)} · Artifact ${index + 1} · ${words(artifact.kind)}`,
            })
          })
        }
        setEvidenceResult({ key: evidenceKey, evidence: [...byId.values()] })
      })
      .catch(() => {
        if (!cancelled) setEvidenceErrorKey(evidenceKey)
      })
    return () => {
      cancelled = true
    }
  }, [case_.findingIds, evidenceKey, evidenceRevision, profileId])

  const loadedEvidence = evidenceResult?.key === evidenceKey
    ? evidenceResult.evidence
    : []
  const knownEvidenceById = new Map(
    loadedEvidence.map((artifact) => [artifact.artifactId, artifact]),
  )
  const selectableEvidence = [
    ...loadedEvidence,
    ...case_.evidenceReferences
      .filter((artifactId) => !knownEvidenceById.has(artifactId))
      .map((artifactId) => ({
        artifactId,
        findingId: case_.findingIds[0],
        providerId: '',
        label: `Linked evidence · ${shortId(artifactId)}`,
      })),
  ]
  const unlinkedEvidence = loadedEvidence.filter(
    (artifact) => !case_.evidenceReferences.includes(artifact.artifactId),
  )
  const providerOptions = [...new Set([
    ...loadedEvidence.map((artifact) => artifact.providerId),
    ...case_.providerResponses.map((response) => response.providerId),
  ].filter((value) => value !== ''))]
  const selectedProviderId = providerOptions.length > 0
    ? (providerOptions.includes(providerId) ? providerId : providerOptions[0])
    : providerId
  const recentHistory = case_.history.slice(-20).reverse()
  const deadlineMs = deadline === '' ? null : new Date(deadline).getTime()
  const deadlineValid =
    deadline === '' ||
    (Number.isFinite(deadlineMs) && (deadlineMs ?? 0) > Date.now())
  const deadlineAtUs = deadlineMs === null ? null : Math.floor(deadlineMs * 1_000)
  const deadlineChanged = deadlineAtUs !== case_.deadlineAtUs
  const providerIdValid = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(selectedProviderId)
  const responseSummaryValid =
    responseSummary.length >= 1 &&
    responseSummary.length <= 2_048 &&
    responseSummary === responseSummary.trim() &&
    !/[\n\r]/.test(responseSummary)

  function updateSelection(
    setter: (value: ReadonlySet<string>) => void,
    current: ReadonlySet<string>,
    artifactId: string,
    checked: boolean,
  ) {
    const next = new Set(current)
    if (checked) next.add(artifactId)
    else next.delete(artifactId)
    setter(next)
  }

  async function executeMutation(
    operation: string,
    action: () => Promise<{ readonly case: Phase6RemediationCase }>,
    success: string,
  ) {
    if (busyOperation !== null) return
    setBusyOperation(operation)
    setMutationStatus(null)
    try {
      const result = await action()
      setMutationStatus({ tone: 'success', message: success })
      onMutated(result.case)
    } catch {
      setMutationStatus({
        tone: 'danger',
        message: `The local change was not saved. Case revision ${case_.revision.toLocaleString()} may be stale or the requested transition may no longer apply; the latest case is being reloaded.`,
      })
      onReload()
    } finally {
      setBusyOperation(null)
    }
  }

  return (
    <Panel
      className="controls-remediation-inspector panel--raised"
      eyebrow="Persisted local case"
      title={words(case_.action)}
      action={<Badge tone={nativeStatusTone[case_.status]}>{words(case_.status)}</Badge>}
    >
      <div className="controls-draft-boundary">
        <ShieldCheck size={16} aria-hidden="true" />
        <span>{words(case_.actionDisposition)} tracking boundary. Controls below update this local record only; nothing is sent or executed.</span>
      </div>
      <dl className="controls-compact-dl">
        <div><dt>Case ID</dt><dd className="mono">{shortId(case_.caseId)}</dd></div>
        <div><dt>Action</dt><dd>{words(case_.action)}</dd></div>
        <div><dt>Disposition</dt><dd>{words(case_.actionDisposition)}</dd></div>
        <div><dt>Status</dt><dd>{words(case_.status)}</dd></div>
        <div><dt>Deadline</dt><dd>{displayTime(case_.deadlineAtUs)}</dd></div>
        <div><dt>Findings</dt><dd>{case_.findingIds.length} linked</dd></div>
        <div><dt>Evidence</dt><dd>{case_.evidenceReferences.length} sealed reference{case_.evidenceReferences.length === 1 ? '' : 's'}</dd></div>
        <div><dt>Provider responses</dt><dd>{case_.providerResponses.length}</dd></div>
        <div><dt>Reappearance</dt><dd>{case_.reappearanceCount === 0 ? 'None recorded' : `${case_.reappearanceCount} · last ${displayTime(case_.lastReappearanceAtUs)}`}</dd></div>
        <div><dt>Revision</dt><dd>{case_.revision}</dd></div>
        <div><dt>Updated</dt><dd>{displayTime(case_.updatedAtUs)}</dd></div>
      </dl>

      {case_.draftText !== null ? (
        <details className="controls-readonly-draft">
          <summary>Reveal persisted local draft</summary>
          <p>This content remains local and has not been sent.</p>
          <pre>{case_.draftText}</pre>
        </details>
      ) : (
        <div className="controls-readonly-draft controls-readonly-draft--empty">
          <FilePenLine size={14} aria-hidden="true" />
          <span>No persisted draft is attached to this revision.</span>
        </div>
      )}

      <MutationStatus status={mutationStatus} />
      <div className="phase6-case-controls" aria-label="Local remediation case controls">
        {!isLocalAction && case_.status !== 'CLOSED' ? (
          <details>
            <summary>Edit local draft</summary>
            <form onSubmit={(event: FormEvent<HTMLFormElement>) => {
              event.preventDefault()
              void executeMutation(
                'draft',
                () => updatePhase6RemediationDraft({
                  profileId,
                  caseId: case_.caseId,
                  expectedRevision: case_.revision,
                  draftText,
                }),
                'The reviewed draft was saved locally. No provider contact occurred.',
              )
            }}>
              <label className="field">
                <span>Reviewable draft · local only</span>
                <textarea className="input phase6-draft-input" value={draftText} maxLength={10_000} disabled={busyOperation !== null} onChange={(event) => setDraftText(event.target.value)} />
              </label>
              <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || draftText.length < 1 || draftText !== draftText.trim()}>
                <FilePenLine size={13} /> Save local draft
              </Button>
            </form>
          </details>
        ) : null}

        {!isLocalAction &&
        case_.actionDisposition === 'DRAFT' &&
        ['OPEN', 'IN_PROGRESS', 'MONITORING'].includes(case_.status) ? (
          <details>
            <summary>Require explicit approval</summary>
            <p>Marks this local plan as approval-required. It does not approve, send, or execute it.</p>
            <Button
              variant="secondary"
              size="compact"
              disabled={busyOperation !== null}
              onClick={() => void executeMutation(
                'approval',
                () => requirePhase6RemediationApproval({
                  profileId,
                  caseId: case_.caseId,
                  expectedRevision: case_.revision,
                }),
                'The case now requires explicit approval. Nothing was approved or sent.',
              )}
            >
              <ShieldCheck size={13} /> Require approval locally
            </Button>
          </details>
        ) : null}

        {transitions.length > 0 ? (
          <details>
            <summary>Update local status</summary>
            <form onSubmit={(event) => {
              event.preventDefault()
              if (targetStatus === '') return
              void executeMutation(
                'status',
                () => transitionPhase6RemediationStatus({
                  profileId,
                  caseId: case_.caseId,
                  expectedRevision: case_.revision,
                  targetStatus,
                  note: statusNote === '' ? null : statusNote,
                }),
                `The local case status changed to ${words(targetStatus)}. No external action occurred.`,
              )
            }}>
              <label className="field">
                <span>Target status</span>
                <select className="select" value={targetStatus} disabled={busyOperation !== null} onChange={(event) => setTargetStatus(event.target.value as Phase6RemediationStatus)}>
                  {transitions.map((value) => <option key={value} value={value}>{words(value)}</option>)}
                </select>
              </label>
              <label className="field">
                <span>Optional local note</span>
                <textarea className="input" value={statusNote} maxLength={1_000} disabled={busyOperation !== null} onChange={(event) => setStatusNote(event.target.value)} />
              </label>
              <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || targetStatus === '' || (statusNote !== '' && statusNote !== statusNote.trim())}>Save local status</Button>
            </form>
          </details>
        ) : null}

        <details>
          <summary>Set local deadline</summary>
          <form onSubmit={(event) => {
            event.preventDefault()
            if (!deadlineValid || !deadlineChanged) return
            void executeMutation(
              'deadline',
              () => setPhase6RemediationDeadline({
                profileId,
                caseId: case_.caseId,
                expectedRevision: case_.revision,
                deadlineAtUs,
              }),
              deadlineAtUs === null ? 'The local deadline was cleared.' : 'The future local deadline was saved.',
            )
          }}>
            <label className="field">
              <span>Future deadline · clear the field to remove</span>
              <input className="input" type="datetime-local" value={deadline} disabled={busyOperation !== null} onChange={(event) => setDeadline(event.target.value)} />
              {!deadlineValid ? <small className="field-error">Choose a future date and time.</small> : null}
            </label>
            <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || !deadlineValid || !deadlineChanged}>Save local deadline</Button>
          </form>
        </details>

        <details>
          <summary>Link finding evidence</summary>
          {evidenceErrorKey === evidenceKey ? (
            <div className="phase6-inline-error">
              <small>Available artifacts could not be validated, so no evidence ID input is exposed.</small>
              <Button size="compact" variant="ghost" onClick={() => setEvidenceRevision((value) => value + 1)}>Retry</Button>
            </div>
          ) : evidenceResult?.key !== evidenceKey ? (
            <small>Loading eligible evidence from linked findings…</small>
          ) : (
            <form onSubmit={(event) => {
              event.preventDefault()
              if (linkSelection.size === 0) return
              void executeMutation(
                'evidence',
                () => linkPhase6RemediationEvidence({
                  profileId,
                  caseId: case_.caseId,
                  expectedRevision: case_.revision,
                  evidenceReferences: [...linkSelection],
                }),
                'Selected evidence references were linked to the local case.',
              )
            }}>
              <EvidenceChoices evidence={unlinkedEvidence} selected={linkSelection} disabled={busyOperation !== null} emptyCopy="All validated artifacts for linked findings are already attached." onChange={(id, checked) => updateSelection(setLinkSelection, linkSelection, id, checked)} />
              <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || linkSelection.size === 0}>Link selected evidence</Button>
            </form>
          )}
        </details>

        {!isLocalAction && case_.providerResponses.length < 32 ? (
          <details>
            <summary>Record a provider response</summary>
            <p>Records a response you already received; Ariadne does not contact the provider.</p>
            <form onSubmit={(event) => {
              event.preventDefault()
              if (!providerIdValid || !responseSummaryValid) return
              void executeMutation(
                'response',
                () => recordPhase6ProviderResponse({
                  profileId,
                  caseId: case_.caseId,
                  expectedRevision: case_.revision,
                  providerId: selectedProviderId,
                  responseCode,
                  summary: responseSummary,
                  evidenceReferences: [...responseEvidence],
                }),
                'The already-received provider response was recorded locally. No message was sent.',
              )
            }}>
              <label className="field">
                <span>Provider</span>
                {providerOptions.length > 0 ? (
                  <select className="select mono" value={selectedProviderId} disabled={busyOperation !== null} onChange={(event) => setProviderId(event.target.value)}>
                    {providerOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                ) : (
                  <input className="input mono" value={providerId} maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,127}" disabled={busyOperation !== null} onChange={(event) => setProviderId(event.target.value)} placeholder="Validated provider identifier" />
                )}
              </label>
              <label className="field">
                <span>Response state</span>
                <select className="select" value={responseCode} disabled={busyOperation !== null} onChange={(event) => setResponseCode(event.target.value)}>
                  {['RECEIVED', 'ACKNOWLEDGED', 'COMPLETED', 'REJECTED', 'MORE_INFORMATION_REQUIRED'].map((value) => <option key={value} value={value}>{words(value)}</option>)}
                </select>
              </label>
              <label className="field">
                <span>Response summary</span>
                <textarea className="input" value={responseSummary} maxLength={2_048} disabled={busyOperation !== null} onChange={(event) => setResponseSummary(event.target.value)} />
              </label>
              <EvidenceChoices evidence={selectableEvidence} selected={responseEvidence} disabled={busyOperation !== null} emptyCopy="No validated evidence reference is available; a response may be recorded without one." onChange={(id, checked) => updateSelection(setResponseEvidence, responseEvidence, id, checked)} />
              <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || !providerIdValid || !responseSummaryValid}>Record received response</Button>
            </form>
          </details>
        ) : null}

        <details>
          <summary>Record a reappearance</summary>
          <p>Records a new observation locally and reopens tracking. At least one validated evidence reference is required.</p>
          <form onSubmit={(event) => {
            event.preventDefault()
            if (reappearanceFindingId === '' || reappearanceEvidence.size === 0) return
            void executeMutation(
              'reappearance',
              () => recordPhase6Reappearance({
                profileId,
                caseId: case_.caseId,
                expectedRevision: case_.revision,
                findingId: reappearanceFindingId,
                evidenceReferences: [...reappearanceEvidence],
              }),
              'The evidenced reappearance was recorded locally and tracking was reopened.',
            )
          }}>
            <label className="field">
              <span>Linked finding</span>
              <select className="select mono" value={reappearanceFindingId} disabled={busyOperation !== null} onChange={(event) => setReappearanceFindingId(event.target.value)}>
                {case_.findingIds.map((value) => <option key={value} value={value}>{shortId(value)}</option>)}
              </select>
            </label>
            <EvidenceChoices evidence={selectableEvidence.filter((artifact) => artifact.findingId === reappearanceFindingId || case_.evidenceReferences.includes(artifact.artifactId))} selected={reappearanceEvidence} disabled={busyOperation !== null} emptyCopy="No validated evidence is available. Import evidence on the finding before recording reappearance." onChange={(id, checked) => updateSelection(setReappearanceEvidence, reappearanceEvidence, id, checked)} />
            <Button type="submit" variant="secondary" size="compact" disabled={busyOperation !== null || reappearanceEvidence.size === 0}>Record evidenced reappearance</Button>
          </form>
        </details>
      </div>

      {case_.providerResponses.length > 0 ? (
        <div className="controls-provider-responses">
          <h3>Provider responses</h3>
          {case_.providerResponses.map((response) => (
            <article key={`${response.providerId}:${response.receivedAtUs}`}>
              <div>
                <Badge tone="blue">{words(response.responseCode)}</Badge>
                <span className="mono">{response.providerId}</span>
              </div>
              <p>{response.summary}</p>
              <small>{displayTime(response.receivedAtUs)} · {response.evidenceReferences.length} evidence reference{response.evidenceReferences.length === 1 ? '' : 's'}</small>
            </article>
          ))}
        </div>
      ) : null}

      <div className="controls-case-history">
        <h3>Case history · {case_.history.length} immutable event{case_.history.length === 1 ? '' : 's'}</h3>
        <ol>
          {recentHistory.map((entry) => (
            <li key={entry.revision}>
              <span>Rev {entry.revision}</span>
              <strong>{words(entry.eventType)} · {words(entry.currentStatus)}</strong>
              <small>{displayTime(entry.occurredAtUs)} · {entry.actorLabel}{entry.note === null ? '' : ` · ${entry.note}`}</small>
            </li>
          ))}
        </ol>
        {case_.history.length > recentHistory.length ? (
          <small className="controls-history-limit">Showing the 20 most recent events.</small>
        ) : null}
      </div>

      <div className="controls-legal-note">
        <Scale size={14} aria-hidden="true" />
        <span>These controls maintain local plans and records only. They do not send requests, approve legal action, or provide legal advice.</span>
      </div>
    </Panel>
  )
}

function NativeRemediationWorkspace({
  profileId,
  cases,
  selectedCaseId,
  selectCase,
  view,
  detail,
  detailLoading,
  detailError,
  retryDetail,
  onMutated,
}: {
  readonly profileId: string
  readonly cases: ReadonlyArray<Phase6RemediationCaseSummary>
  readonly selectedCaseId: string
  readonly selectCase: (caseId: string) => void
  readonly view: ViewMode
  readonly detail: Phase6RemediationCase | null
  readonly detailLoading: boolean
  readonly detailError: boolean
  readonly retryDetail: () => void
  readonly onMutated: (case_: Phase6RemediationCase) => void
}) {
  return (
    <div className={`controls-remediation-workspace is-${view}`}>
      <Panel
        className="controls-remediation-board panel--raised"
        eyebrow="Persisted local work"
        title={view === 'board' ? 'Status board' : 'Case list'}
        action={<Badge>{cases.length} local case{cases.length === 1 ? '' : 's'}</Badge>}
      >
        {view === 'board' ? (
          <div className="controls-board-scroll" role="region" aria-label="Persisted remediation status board" tabIndex={0}>
            <div className="controls-board">
              {nativeCaseGroups.map((group) => {
                const items = cases.filter((item) => group.statuses.has(item.status))
                return (
                  <section className="controls-board-column" key={group.id} aria-labelledby={`native-column-${group.id}`}>
                    <header>
                      <h3 id={`native-column-${group.id}`}>{group.title}</h3>
                      <span>{items.length}</span>
                    </header>
                    <div className="controls-board-column__items">
                      {items.length === 0 ? (
                        <div className="controls-board-column__empty">No persisted cases</div>
                      ) : items.map((item) => (
                        <NativeCaseCard
                          key={item.caseId}
                          item={item}
                          selected={selectedCaseId === item.caseId}
                          onSelect={() => selectCase(item.caseId)}
                        />
                      ))}
                    </div>
                  </section>
                )
              })}
            </div>
          </div>
        ) : (
          <div className="controls-remediation-list">
            {cases.map((item) => (
              <button type="button" key={item.caseId} onClick={() => selectCase(item.caseId)} className={selectedCaseId === item.caseId ? 'is-selected' : ''}>
                <span><Badge tone={nativeStatusTone[item.status]}>{words(item.status)}</Badge></span>
                <span><strong>{words(item.action)}</strong><small className="mono">{shortId(item.caseId)}</small></span>
                <span>{words(item.actionDisposition)}</span>
                <span>Rev {item.revision}</span>
                <span>{item.deadlineAtUs === null ? 'No deadline' : displayTime(item.deadlineAtUs)}</span>
              </button>
            ))}
          </div>
        )}
      </Panel>

      {detailError ? (
        <Phase6StatePanel
          state="error"
          compact
          title="Case detail is unavailable"
          detail="The selected case failed strict validation. No partial draft, response, or history is shown."
          onRetry={retryDetail}
        />
      ) : detailLoading || detail === null ? (
        <Phase6StatePanel
          state="loading"
          compact
          title="Loading persisted case"
          detail="Validating the complete immutable revision before rendering it."
        />
      ) : (
        <NativeCaseInspector
          profileId={profileId}
          case_={detail}
          onMutated={onMutated}
          onReload={retryDetail}
        />
      )}
    </div>
  )
}

function NativeRemediationPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [view, setView] = useState<ViewMode>('board')
  const [listResult, setListResult] = useState<{
    readonly profileId: string
    readonly data: Phase6RemediationCaseList
  } | null>(null)
  const [listErrorProfileId, setListErrorProfileId] = useState<string | null>(null)
  const [listRevision, setListRevision] = useState(0)
  const [selection, setSelection] = useState<{
    readonly profileId: string
    readonly caseId: string
  } | null>(null)
  const [detailResult, setDetailResult] = useState<{
    readonly key: string
    readonly data: Phase6RemediationCase
  } | null>(null)
  const [detailErrorKey, setDetailErrorKey] = useState<string | null>(null)
  const [detailRevision, setDetailRevision] = useState(0)

  useEffect(() => {
    document.title = 'Removal Tracker · Codename Ariadne'
  }, [])

  useEffect(() => {
    if (profileId === null) return
    let cancelled = false
    setListErrorProfileId(null)
    void loadPhase6RemediationCases({ profileId, limit: 100 })
      .then((data) => {
        if (!cancelled) setListResult({ profileId, data })
      })
      .catch(() => {
        if (!cancelled) setListErrorProfileId(profileId)
      })
    return () => {
      cancelled = true
    }
  }, [listRevision, profileId])

  const activeList = listResult?.profileId === profileId ? listResult.data : null
  const sortedCases = useMemo(
    () => [...(activeList?.cases ?? [])].sort((left, right) => right.updatedAtUs - left.updatedAtUs),
    [activeList],
  )

  useEffect(() => {
    if (profileId === null || sortedCases.length === 0) return
    setSelection((current) =>
      current?.profileId === profileId &&
      sortedCases.some((item) => item.caseId === current.caseId)
        ? current
        : { profileId, caseId: sortedCases[0].caseId },
    )
  }, [profileId, sortedCases])

  const activeSelection =
    selection?.profileId === profileId &&
    sortedCases.some((item) => item.caseId === selection.caseId)
      ? selection
      : null
  const detailKey = activeSelection === null
    ? null
    : `${activeSelection.profileId}:${activeSelection.caseId}`

  useEffect(() => {
    if (activeSelection === null || detailKey === null) return
    let cancelled = false
    setDetailErrorKey(null)
    void loadPhase6RemediationCase(activeSelection)
      .then((result) => {
        if (!cancelled) setDetailResult({ key: detailKey, data: result.case })
      })
      .catch(() => {
        if (!cancelled) setDetailErrorKey(detailKey)
      })
    return () => {
      cancelled = true
    }
  }, [activeSelection, detailKey, detailRevision])

  const activeDetail = detailResult?.key === detailKey ? detailResult.data : null
  const openCount = sortedCases.filter((item) => item.status === 'OPEN' || item.status === 'IN_PROGRESS').length
  const approvalCount = sortedCases.filter((item) => item.status === 'AWAITING_EXPLICIT_APPROVAL').length
  const reappearanceCount = sortedCases.reduce((total, item) => total + item.reappearanceCount, 0)

  return (
    <div className="page controls-page remediation-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Removal Tracker · Encrypted local cases"
        title="Remediation stays reviewed"
        description="Create and update local drafts, statuses, deadlines, evidence links, received responses, and reappearance history. Ariadne never sends or executes provider actions."
        meta={
          <>
            <Badge tone="green" dot>Native vault</Badge>
            <Badge tone="cyan">No automatic sends</Badge>
            {activeList?.hasMore ? <Badge tone="amber">More cases available</Badge> : null}
          </>
        }
        actions={
          <>
            <div className="segmented-control" aria-label="Remediation layout">
              <button type="button" className={view === 'board' ? 'is-active' : ''} onClick={() => setView('board')} aria-pressed={view === 'board'}>
                <Columns3 size={13} aria-hidden="true" /> Board
              </button>
              <button type="button" className={view === 'list' ? 'is-active' : ''} onClick={() => setView('list')} aria-pressed={view === 'list'}>
                <List size={13} aria-hidden="true" /> List
              </button>
            </div>
            <Link className="button button--primary" to="/findings"><Plus size={15} aria-hidden="true" /> Create from finding</Link>
          </>
        }
      />

      {profileId === null ? (
        <Phase6StatePanel
          state="no-profile"
          title="No active profile"
          detail="Create or resume a local audit profile before loading persisted remediation cases. Native mode never substitutes synthetic cases."
        />
      ) : listErrorProfileId === profileId ? (
        <Phase6StatePanel
          state="error"
          title="Persisted remediation cases are unavailable"
          detail="The local core did not return a valid profile-bound response. No partial drafts, histories, or demo records are shown."
          onRetry={() => setListRevision((current) => current + 1)}
        />
      ) : activeList === null ? (
        <Phase6StatePanel
          state="loading"
          title="Loading persisted remediation cases"
          detail="Reading bounded case summaries from the active encrypted profile."
        />
      ) : sortedCases.length === 0 ? (
        <Phase6StatePanel
          state="empty"
          title="No persisted remediation cases"
          detail="The active profile has no local cases. Open a persisted finding to create one; this does not imply all findings are resolved, and no synthetic fallback is shown."
        />
      ) : activeSelection === null ? (
        <Phase6StatePanel
          state="loading"
          title="Selecting a persisted case"
          detail="Binding the most recently updated case to the active profile."
        />
      ) : (
        <>
          <div className="controls-remediation-summary" aria-label="Persisted remediation summary">
            <article>
              <span className="status-icon status-icon--cyan"><CalendarClock size={16} /></span>
              <div><strong>{openCount} open or in progress</strong><small>Every change is local, revision-bound, and recorded in case history.</small></div>
              <Badge tone="cyan">Local</Badge>
            </article>
            <article>
              <span className="status-icon status-icon--amber"><MessageSquareText size={16} /></span>
              <div><strong>{approvalCount} awaiting explicit approval</strong><small>No approval, request, or provider message is sent automatically.</small></div>
              <Badge tone="amber">Review</Badge>
            </article>
            <article>
              <span className="status-icon status-icon--violet"><RotateCcw size={16} /></span>
              <div><strong>{reappearanceCount} recorded reappearance{reappearanceCount === 1 ? '' : 's'}</strong><small>Each event remains attached to immutable case history.</small></div>
              <Badge tone="violet">History</Badge>
            </article>
          </div>

          <NativeRemediationWorkspace
            profileId={profileId}
            cases={sortedCases}
            selectedCaseId={activeSelection.caseId}
            selectCase={(caseId) => setSelection({ profileId, caseId })}
            view={view}
            detail={activeDetail}
            detailLoading={activeDetail === null && detailErrorKey !== detailKey}
            detailError={detailErrorKey === detailKey}
            retryDetail={() => setDetailRevision((current) => current + 1)}
            onMutated={(case_) => {
              if (detailKey !== null) setDetailResult({ key: detailKey, data: case_ })
              setListRevision((current) => current + 1)
            }}
          />

          <div className="controls-callout controls-callout--amber">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>A finding classified as removed may remain in caches, mirrors, or archives. Persisted rechecks record each surface independently.</span>
          </div>
        </>
      )}
    </div>
  )
}

export function RemediationPage() {
  return nativeRuntimeAvailable() ? (
    <NativeRemediationPage />
  ) : (
    <SimulatedRemediationPage />
  )
}

export default RemediationPage
