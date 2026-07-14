import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  ArrowUpRight,
  CheckCircle2,
  Download,
  Filter,
  ListFilter,
  Network,
  Plus,
  Search,
  ShieldAlert,
} from 'lucide-react'
import { findings } from '@ariadne/synthetic-data'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  createPhase5ManualFinding,
  loadPhase5Findings,
  type Phase5CheckOutcome,
  type Phase5FindingList,
  type Phase5FindingSummary,
  type Phase5Severity,
  type Phase5Visibility,
} from '../app/phase5Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Phase5StatePanel } from '../components/Phase5StatePanel'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  type Tone,
} from '../components/Primitives'
import '../styles/pages-results.css'

type Finding = (typeof findings)[number]
type Queue = 'review' | 'new' | 'all'

const outcomeTone: Record<Finding['outcome'], Tone> = {
  FOUND: 'green',
  AMBIGUOUS: 'violet',
  MANUAL_REVIEW_REQUIRED: 'amber',
}

const severityTone: Record<Finding['severity'], Tone> = {
  critical: 'rose',
  high: 'rose',
  medium: 'amber',
  low: 'blue',
  info: 'neutral',
}

function confidenceBand(score: number) {
  if (score === 0) return 'Unresolved'
  if (score >= 85) return 'High'
  if (score >= 60) return 'Moderate'
  return 'Low'
}

function sensitivityFor(finding: Finding) {
  if (finding.id === 'finding_syn_blocked') return 'Highly sensitive'
  if (finding.visibility === 'Publicly attributable') return 'Public'
  return 'Sensitive'
}

function SimulatedFindingsPage() {
  const [queue, setQueue] = useState<Queue>('review')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [severity, setSeverity] = useState<'all' | Finding['severity']>('all')

  const filteredFindings = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return findings.filter((finding) => {
      const matchesQuery =
        !normalized ||
        `${finding.title} ${finding.source} ${finding.summary}`
          .toLocaleLowerCase()
          .includes(normalized)
      const matchesSeverity = severity === 'all' || finding.severity === severity
      const matchesQueue =
        queue === 'all' ||
        (queue === 'new' && finding.changed === 'New') ||
        (queue === 'review' && finding.ownership !== 'Confirmed match')
      return matchesQuery && matchesSeverity && matchesQueue
    })
  }, [query, queue, severity])

  const toggleFinding = (id: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    const visibleIds = filteredFindings.map((finding) => finding.id)
    const allSelected = visibleIds.every((id) => selected.has(id))
    setSelected((current) => {
      const next = new Set(current)
      visibleIds.forEach((id) => {
        if (allSelected) next.delete(id)
        else next.add(id)
      })
      return next
    })
  }

  return (
    <div className="page findings-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Review queue · synthetic evidence"
        title="Findings"
        description="Triage normalised results without conflating a source outcome, visibility, or confidence score with identity ownership."
        meta={
          <>
            <Badge tone="violet" dot>6 need review</Badge>
            <Badge tone="amber">2 coverage limitations</Badge>
            <span className="findings-page__updated mono">Snapshot 11 Jul 2026 · 14:38</span>
          </>
        }
        actions={
          <>
            <Link className="button button--secondary" to="/graph">
              <Network size={14} /> Open Link Map
            </Link>
            <Button variant="secondary"><Download size={14} /> Export review</Button>
          </>
        }
      />

      <section className="findings-queues" aria-label="Saved review queues">
        <button
          type="button"
          className={queue === 'review' ? 'is-active' : undefined}
          aria-pressed={queue === 'review'}
          onClick={() => setQueue('review')}
        >
          <span className="status-icon status-icon--violet"><ListFilter size={15} /></span>
          <span><strong>Needs review</strong><small>Unresolved or probable attribution</small></span>
          <b className="mono">4</b>
        </button>
        <button
          type="button"
          className={queue === 'new' ? 'is-active' : undefined}
          aria-pressed={queue === 'new'}
          onClick={() => setQueue('new')}
        >
          <span className="status-icon status-icon--cyan"><AlertCircle size={15} /></span>
          <span><strong>New this run</strong><small>Not observed in the previous audit</small></span>
          <b className="mono">1</b>
        </button>
        <button
          type="button"
          className={queue === 'all' ? 'is-active' : undefined}
          aria-pressed={queue === 'all'}
          onClick={() => setQueue('all')}
        >
          <span className="status-icon status-icon--green"><CheckCircle2 size={15} /></span>
          <span><strong>All results</strong><small>Includes blocked and non-match checks</small></span>
          <b className="mono">5</b>
        </button>
      </section>

      <div className="findings-limitation callout callout--warning">
        <ShieldAlert size={15} aria-hidden="true" />
        <div>
          <strong>Coverage is partial, not an all-clear.</strong>
          <span> Image similarity remains unexecuted and one archive adapter returned degraded coverage. Available findings are retained below.</span>
        </div>
        <Link to="/providers">Inspect coverage <ArrowUpRight size={12} /></Link>
      </div>

      <Panel className="findings-inbox panel--raised">
        <div className="findings-toolbar">
          <label className="findings-search">
            <span className="sr-only">Search findings</span>
            <Search size={14} aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search title, source, or signal"
              type="search"
            />
            <kbd>/</kbd>
          </label>
          <label className="findings-filter">
            <Filter size={13} aria-hidden="true" />
            <span>Severity</span>
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as typeof severity)}
              aria-label="Filter by severity"
            >
              <option value="all">All</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="info">Info</option>
            </select>
          </label>
          <Button variant="ghost" size="compact"><Filter size={12} /> More filters</Button>
          <span className="findings-toolbar__count mono">{filteredFindings.length} visible</span>
          {selected.size > 0 ? (
            <div className="findings-bulk" role="status">
              <strong>{selected.size} selected</strong>
              <Button variant="secondary" size="compact">Mark reviewed</Button>
              <Button variant="ghost" size="compact">Add label</Button>
            </div>
          ) : null}
        </div>

        {filteredFindings.length ? (
          <div className="findings-table-wrap">
            <table className="data-table findings-table">
              <thead>
                <tr>
                  <th scope="col" className="findings-table__check">
                    <input
                      type="checkbox"
                      checked={
                        filteredFindings.length > 0 &&
                        filteredFindings.every((finding) => selected.has(finding.id))
                      }
                      onChange={toggleAll}
                      aria-label="Select all visible findings"
                    />
                  </th>
                  <th scope="col">Finding</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Visibility</th>
                  <th scope="col">Attribution</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Sensitivity</th>
                  <th scope="col">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {filteredFindings.map((finding) => (
                  <tr key={finding.id} className={selected.has(finding.id) ? 'is-selected' : undefined}>
                    <td className="findings-table__check">
                      <input
                        type="checkbox"
                        checked={selected.has(finding.id)}
                        onChange={() => toggleFinding(finding.id)}
                        aria-label={`Select ${finding.title}`}
                      />
                    </td>
                    <td>
                      <div className="finding-title-cell">
                        <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
                        <span>{finding.summary}</span>
                        <span className="finding-title-cell__compact">
                          Exposure: {finding.visibility} · Sensitivity: {sensitivityFor(finding)}
                        </span>
                        <div>
                          <Badge tone={severityTone[finding.severity]}>{finding.severity}</Badge>
                          <Badge>{finding.changed}</Badge>
                        </div>
                      </div>
                    </td>
                    <td><Badge tone={outcomeTone[finding.outcome]} dot>{finding.outcome}</Badge></td>
                    <td><span className="finding-dimension">{finding.visibility}</span></td>
                    <td><span className="finding-dimension">{finding.ownership}</span></td>
                    <td>
                      <div className="finding-confidence">
                        <strong>{confidenceBand(finding.confidence)}</strong>
                        <span className="mono">{finding.confidence || '—'}</span>
                      </div>
                    </td>
                    <td><span className="finding-dimension">{sensitivityFor(finding)}</span></td>
                    <td>
                      <div className="finding-provenance">
                        <strong>{finding.source}</strong>
                        <span className="mono">11 Jul · 14:36</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state findings-empty">
            <span className="empty-state__icon"><Search size={20} /></span>
            <h2>No findings match this review view</h2>
            <p>The current filters hide all available synthetic results. This does not mean no exposure exists.</p>
            <Button variant="secondary" onClick={() => { setQuery(''); setSeverity('all'); setQueue('all') }}>
              Clear filters
            </Button>
          </div>
        )}
      </Panel>
    </div>
  )
}

type NativeQueue = 'review' | 'all'

const nativeOutcomeTone: Record<Phase5CheckOutcome, Tone> = {
  FOUND: 'green',
  NOT_FOUND: 'blue',
  NOT_CHECKED: 'neutral',
  CHECK_FAILED: 'rose',
  ACCESS_BLOCKED: 'rose',
  AUTH_REQUIRED: 'amber',
  RATE_LIMITED: 'amber',
  PROVIDER_UNAVAILABLE: 'amber',
  AMBIGUOUS: 'violet',
  MANUAL_REVIEW_REQUIRED: 'amber',
  AUTHORITATIVE_ABSENCE: 'blue',
}

const nativeSeverityTone: Record<Phase5Severity, Tone> = {
  CRITICAL: 'rose',
  HIGH: 'rose',
  MEDIUM: 'amber',
  LOW: 'blue',
  INFO: 'neutral',
}

function words(value: string): string {
  return value
    .toLocaleLowerCase()
    .replaceAll('_', ' ')
    .replace(/^./, (character) => character.toLocaleUpperCase())
}

function displayTime(timestampUs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(Math.floor(timestampUs / 1_000)))
}

function NativeFindingsTable({
  findings: persistedFindings,
}: {
  readonly findings: ReadonlyArray<Phase5FindingSummary>
}) {
  const [queue, setQueue] = useState<NativeQueue>('review')
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState<'all' | Phase5Severity>('all')
  const filteredFindings = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return persistedFindings.filter((finding) => {
      const matchesQuery =
        !normalized ||
        `${finding.title} ${finding.summary} ${finding.providerLabel}`
          .toLocaleLowerCase()
          .includes(normalized)
      const matchesSeverity = severity === 'all' || finding.severity === severity
      const matchesQueue = queue === 'all' || finding.humanReviewRequired
      return matchesQuery && matchesSeverity && matchesQueue
    })
  }, [persistedFindings, query, queue, severity])
  const reviewCount = persistedFindings.filter(
    (finding) => finding.humanReviewRequired,
  ).length

  return (
    <>
      <section className="findings-queues findings-queues--native" aria-label="Persisted review queues">
        <button
          type="button"
          className={queue === 'review' ? 'is-active' : undefined}
          aria-pressed={queue === 'review'}
          onClick={() => setQueue('review')}
        >
          <span className="status-icon status-icon--violet"><ListFilter size={15} /></span>
          <span><strong>Needs human review</strong><small>Scoring never assigns identity ownership</small></span>
          <b className="mono">{reviewCount}</b>
        </button>
        <button
          type="button"
          className={queue === 'all' ? 'is-active' : undefined}
          aria-pressed={queue === 'all'}
          onClick={() => setQueue('all')}
        >
          <span className="status-icon status-icon--green"><CheckCircle2 size={15} /></span>
          <span><strong>All persisted findings</strong><small>No synthetic results are included</small></span>
          <b className="mono">{persistedFindings.length}</b>
        </button>
      </section>

      <div className="findings-limitation callout callout--warning">
        <ShieldAlert size={15} aria-hidden="true" />
        <div>
          <strong>Persisted results do not imply complete coverage.</strong>
          <span> Blocked, failed, and unexecuted checks remain unknown rather than becoming absence.</span>
        </div>
        <Link to="/privacy/transmission">Inspect policy <ArrowUpRight size={12} /></Link>
      </div>

      <Panel className="findings-inbox panel--raised">
        <div className="findings-toolbar">
          <label className="findings-search">
            <span className="sr-only">Search persisted findings</span>
            <Search size={14} aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search title, provider, or summary"
              type="search"
            />
          </label>
          <label className="findings-filter">
            <Filter size={13} aria-hidden="true" />
            <span>Severity</span>
            <select
              value={severity}
              onChange={(event) =>
                setSeverity(event.target.value as typeof severity)
              }
              aria-label="Filter persisted findings by severity"
            >
              <option value="all">All</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
              <option value="INFO">Info</option>
            </select>
          </label>
          <span className="findings-toolbar__count mono">{filteredFindings.length} visible</span>
        </div>

        {filteredFindings.length > 0 ? (
          <div className="findings-table-wrap">
            <table className="data-table findings-table findings-table--native">
              <thead>
                <tr>
                  <th scope="col">Finding</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Visibility</th>
                  <th scope="col">Human decision</th>
                  <th scope="col">Assessment</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {filteredFindings.map((finding) => (
                  <tr key={finding.findingId}>
                    <td>
                      <div className="finding-title-cell">
                        <Link to={`/findings/${finding.findingId}`}>{finding.title}</Link>
                        <span>{finding.summary}</span>
                        <div>
                          <Badge tone={nativeSeverityTone[finding.severity]}>{words(finding.severity)}</Badge>
                          {finding.humanReviewRequired ? <Badge tone="violet">Review required</Badge> : null}
                        </div>
                      </div>
                    </td>
                    <td><Badge tone={nativeOutcomeTone[finding.outcome]} dot>{words(finding.outcome)}</Badge></td>
                    <td><span className="finding-dimension">{words(finding.visibility)}</span></td>
                    <td>
                      <span className="finding-dimension">
                        {finding.attributionState === null
                          ? 'No human decision'
                          : words(finding.attributionState)}
                      </span>
                    </td>
                    <td>
                      <div className="finding-confidence">
                        <strong>{words(finding.confidenceBand)}</strong>
                        <span className="mono">{finding.score >= 0 ? '+' : ''}{finding.score} / 1000</span>
                      </div>
                    </td>
                    <td><span className="finding-dimension">{finding.artifactCount} sealed</span></td>
                    <td>
                      <div className="finding-provenance">
                        <strong>{finding.providerLabel}</strong>
                        <span className="mono">{displayTime(finding.updatedAtUs)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state findings-empty">
            <span className="empty-state__icon"><Search size={20} /></span>
            <h2>No persisted findings match this view</h2>
            <p>The active filters hide the available records. This is not an all-clear.</p>
            <Button variant="secondary" onClick={() => { setQuery(''); setSeverity('all'); setQueue('all') }}>
              Clear filters
            </Button>
          </div>
        )}
      </Panel>
    </>
  )
}

function NativeFindingsPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const navigate = useNavigate()
  const [result, setResult] = useState<{
    readonly profileId: string
    readonly data: Phase5FindingList
  } | null>(null)
  const [errorProfileId, setErrorProfileId] = useState<string | null>(null)
  const [loadRevision, setLoadRevision] = useState(0)

  useEffect(() => {
    document.title = 'Findings · Codename Ariadne'
    if (profileId === null) return
    let cancelled = false
    setErrorProfileId(null)
    void loadPhase5Findings({ profileId, limit: 100 })
      .then((data) => {
        if (!cancelled) setResult({ profileId, data })
      })
      .catch(() => {
        if (!cancelled) setErrorProfileId(profileId)
      })
    return () => {
      cancelled = true
    }
  }, [loadRevision, profileId])

  const activeResult = result?.profileId === profileId ? result.data : null

  return (
    <div className="page findings-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Review queue · Encrypted local evidence"
        title="Findings"
        description="Review persisted results and explainable attribution without treating a score as an identity decision."
        meta={
          <>
            <Badge tone="green" dot>Native vault</Badge>
            <Badge tone="violet">Human review required</Badge>
            {activeResult?.hasMore ? <Badge tone="amber">More records available</Badge> : null}
          </>
        }
        actions={
          <Link className="button button--secondary" to="/graph">
            <Network size={14} /> Open Link Map
          </Link>
        }
      />

      {profileId === null ? null : (
        <NativeManualFindingForm
          profileId={profileId}
          onCreated={(findingId) => {
            setLoadRevision((current) => current + 1)
            void navigate(`/findings/${findingId}`)
          }}
        />
      )}

      {profileId === null ? (
        <Phase5StatePanel
          state="no-profile"
          title="No active profile"
          detail="Create or resume a local audit profile before loading persisted findings. No synthetic findings are substituted in native mode."
        />
      ) : errorProfileId === profileId ? (
        <Phase5StatePanel
          state="error"
          title="Persisted findings are unavailable"
          detail="The local core did not return a valid profile-bound response. No partial or demo records are being shown."
          onRetry={() => setLoadRevision((current) => current + 1)}
        />
      ) : activeResult === null ? (
        <Phase5StatePanel
          state="loading"
          title="Loading persisted findings"
          detail="Reading the active profile from the encrypted local vault."
        />
      ) : activeResult.findings.length === 0 ? (
        <Phase5StatePanel
          state="empty"
          title="No persisted findings for this profile"
          detail="The native vault returned an empty review queue. This is not evidence of absence, and synthetic fixtures are not used as a fallback."
        />
      ) : (
        <NativeFindingsTable findings={activeResult.findings} />
      )}
    </div>
  )
}

function NativeManualFindingForm({
  profileId,
  onCreated,
}: {
  readonly profileId: string
  readonly onCreated: (findingId: string) => void
}) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [providerId, setProviderId] = useState('manual.local')
  const [providerLabel, setProviderLabel] = useState('Manual local source')
  const [outcome, setOutcome] =
    useState<Phase5CheckOutcome>('MANUAL_REVIEW_REQUIRED')
  const [severity, setSeverity] = useState<Phase5Severity>('MEDIUM')
  const [visibility, setVisibility] =
    useState<Phase5Visibility>('UNKNOWN')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setFailed(false)
    try {
      const detail = await createPhase5ManualFinding({
        profileId,
        title: title.trim(),
        summary: summary.trim(),
        outcome,
        severity,
        visibility,
        providerId: providerId.trim(),
        providerLabel: providerLabel.trim(),
      })
      onCreated(detail.finding.findingId)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      className="phase5-write-panel findings-manual-panel"
      eyebrow="Fresh profile intake"
      title="Add a local finding"
      action={<Badge tone="cyan">Encrypted · no network</Badge>}
    >
      <form className="phase5-write-form" onSubmit={(event) => void submit(event)}>
        <p className="phase5-write-note">
          Create the first review record manually, then attach evidence and make a human attribution decision from its detail page. The initial assessment stays unresolved.
        </p>
        <div className="phase5-write-fields phase5-write-fields--two">
          <label className="field">
            <span>Finding title</span>
            <input className="input" value={title} minLength={1} maxLength={256} required disabled={busy} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="field">
            <span>Provider label</span>
            <input className="input" value={providerLabel} minLength={1} maxLength={128} required disabled={busy} onChange={(event) => setProviderLabel(event.target.value)} />
          </label>
        </div>
        <label className="field">
          <span>Review summary</span>
          <textarea className="input findings-manual-summary" value={summary} minLength={1} maxLength={2_048} required disabled={busy} onChange={(event) => setSummary(event.target.value)} />
        </label>
        <div className="phase5-write-fields findings-manual-fields">
          <label className="field">
            <span>Provider ID</span>
            <input className="input mono" value={providerId} minLength={1} maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,127}" required disabled={busy} onChange={(event) => setProviderId(event.target.value)} />
          </label>
          <label className="field">
            <span>Outcome</span>
            <select className="select" value={outcome} disabled={busy} onChange={(event) => setOutcome(event.target.value as Phase5CheckOutcome)}>
              {Array.from(CHECK_OUTCOMES_FOR_FORM).map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Severity</span>
            <select className="select" value={severity} disabled={busy} onChange={(event) => setSeverity(event.target.value as Phase5Severity)}>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const).map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Visibility</span>
            <select className="select" value={visibility} disabled={busy} onChange={(event) => setVisibility(event.target.value as Phase5Visibility)}>
              {(['UNKNOWN', 'PUBLICLY_ATTRIBUTABLE', 'PUBLIC_PSEUDONYMOUS', 'PRIVATELY_LINKABLE', 'HISTORICAL_RESIDUE', 'PRIVATE_ONLY'] as const).map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
          </label>
        </div>
        {failed ? <div className="callout callout--danger" role="alert">The local finding was not created. Check the bounded fields and retry after confirming the vault is unlocked.</div> : null}
        <div className="phase5-write-actions">
          <span>Server-generated ID and timestamp · no automatic ownership decision</span>
          <Button type="submit" disabled={busy || title.trim() === '' || summary.trim() === '' || providerId.trim() === '' || providerLabel.trim() === ''}>
            <Plus size={14} /> {busy ? 'Creating…' : 'Create local finding'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

const CHECK_OUTCOMES_FOR_FORM: ReadonlyArray<Phase5CheckOutcome> = [
  'MANUAL_REVIEW_REQUIRED',
  'FOUND',
  'AMBIGUOUS',
  'NOT_FOUND',
  'NOT_CHECKED',
  'ACCESS_BLOCKED',
  'CHECK_FAILED',
  'AUTH_REQUIRED',
  'RATE_LIMITED',
  'PROVIDER_UNAVAILABLE',
  'AUTHORITATIVE_ABSENCE',
]

export function FindingsPage() {
  return nativeRuntimeAvailable() ? (
    <NativeFindingsPage />
  ) : (
    <SimulatedFindingsPage />
  )
}
