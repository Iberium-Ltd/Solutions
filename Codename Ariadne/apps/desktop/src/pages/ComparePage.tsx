import { useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  ArrowRightLeft,
  CheckCircle2,
  CircleHelp,
  Eye,
  Filter,
  GitCompareArrows,
  RotateCcw,
  Save,
} from 'lucide-react'
import { comparisonRows } from '@ariadne/synthetic-data'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  createPhase6LocalCheckpoint,
  loadPhase6AuditComparison,
  loadPhase6AuditRuns,
  type Phase6AuditComparison,
  type Phase6AuditRunList,
  type Phase6AuditRunSummary,
  type Phase6FindingDiff,
  type Phase6FindingDiffState,
  type Phase6ProviderCoverageState,
  type Phase6SnapshotRunState,
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

type DiffState =
  | 'NEW'
  | 'CHANGED'
  | 'REMOVED'
  | 'REAPPEARED'
  | 'ARCHIVED'
  | 'FALSE_POSITIVE'
  | 'UNKNOWN'

type ComparisonItem = {
  item: string
  previous: string
  current: string
  state: DiffState
  impact: string
  source: string
  detail: string
}

const extraRows: ComparisonItem[] = [
  {
    item: 'Directory snapshot',
    previous: 'Live listing',
    current: 'Archive capture only',
    state: 'ARCHIVED',
    impact: 'Medium',
    source: 'Meridian Archive',
    detail: 'The source is no longer live, but a historical capture remains observable.',
  },
  {
    item: 'Provider-only record',
    previous: 'Provider returned metadata',
    current: 'Provider unavailable',
    state: 'UNKNOWN',
    impact: 'Unknown',
    source: 'Civic Ledger',
    detail: 'No conclusion is possible because equivalent coverage was unavailable in the current run.',
  },
]

const comparisonData: ComparisonItem[] = [
  ...comparisonRows.map((row) => ({
    ...row,
    state: row.state as DiffState,
    source: row.item.includes('Code') ? 'Code Atlas' : 'Boreal Search',
    detail:
      row.state === 'REMOVED'
        ? 'The prior URL returned a simulated 404. This does not prove deletion from mirrors, archives, or indexes.'
        : 'Content and source metadata were compared after removing known dynamic noise.',
  })),
  ...extraRows,
]

const summary = [
  ['NEW', '1', 'cyan'],
  ['CHANGED', '1', 'violet'],
  ['REMOVED', '1', 'green'],
  ['REAPPEARED', '1', 'amber'],
  ['ARCHIVED', '1', 'blue'],
  ['UNKNOWN', '1', 'rose'],
] as const

const stateTone = (state: DiffState) => {
  switch (state) {
    case 'NEW': return 'cyan' as const
    case 'CHANGED': return 'violet' as const
    case 'REMOVED': return 'green' as const
    case 'REAPPEARED': return 'amber' as const
    case 'ARCHIVED': return 'blue' as const
    case 'UNKNOWN': return 'rose' as const
    default: return 'neutral' as const
  }
}

function SimulatedComparePage() {
  const [previousRun, setPreviousRun] = useState('run-syn-0615')
  const [currentRun, setCurrentRun] = useState('run-syn-0711')
  const [filter, setFilter] = useState<'ALL' | DiffState>('ALL')
  const [selected, setSelected] = useState<ComparisonItem>(comparisonData[0])

  const incompatible = previousRun === 'run-syn-limited'
  const visibleRows = useMemo(
    () => comparisonData.filter((row) => filter === 'ALL' || row.state === filter),
    [filter],
  )

  useEffect(() => {
    document.title = 'Compare Runs · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  const swapRuns = () => {
    setPreviousRun(currentRun)
    setCurrentRun(previousRun)
  }

  return (
    <div className="page controls-page compare-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Compare Runs · Synthetic re-audit"
        title="What changed between snapshots?"
        description="Compare source state, content, attribution, and coverage independently. Removed, deindexed, and archived never collapse into one outcome."
        meta={
          <>
            <Badge tone="green" dot>Compatible scope</Badge>
            <Badge>7 material rows</Badge>
            <Badge tone="cyan">Local diff</Badge>
          </>
        }
        actions={
          <Button>
            <Eye size={15} aria-hidden="true" />
            Review evidence
          </Button>
        }
      />

      <Panel className="controls-run-pair panel--raised" eyebrow="Snapshot pair" title="Compatible run selection">
        <div className="controls-run-pair__grid">
          <label className="controls-run-select">
            <span>Baseline run</span>
            <select value={previousRun} onChange={(event) => setPreviousRun(event.target.value)}>
              <option value="run-syn-0615">15 Jun 2026 · SYN-0615</option>
              <option value="run-syn-0511">11 May 2026 · SYN-0511</option>
              <option value="run-syn-limited">02 Apr 2026 · SYN-0402 · limited</option>
            </select>
            <small>EU-approved · 181 checks · 5 unavailable</small>
          </label>

          <Button className="controls-swap-button" size="compact" onClick={swapRuns} aria-label="Swap baseline and current runs">
            <ArrowRightLeft size={15} aria-hidden="true" />
          </Button>

          <label className="controls-run-select">
            <span>Current run</span>
            <select value={currentRun} onChange={(event) => setCurrentRun(event.target.value)}>
              <option value="run-syn-0711">11 Jul 2026 · SYN-0711</option>
              <option value="run-syn-0628">28 Jun 2026 · SYN-0628</option>
            </select>
            <small>EU-approved · 186 checks · 4 unavailable</small>
          </label>

          <div className="controls-compatibility">
            {incompatible ? (
              <>
                <AlertTriangle size={17} aria-hidden="true" />
                <div>
                  <strong>Coverage differs</strong>
                  <small>23 checks have no equivalent baseline.</small>
                </div>
                <Badge tone="amber">Partial</Badge>
              </>
            ) : (
              <>
                <CheckCircle2 size={17} aria-hidden="true" />
                <div>
                  <strong>Scope aligned</strong>
                  <small>181 checks are directly comparable.</small>
                </div>
                <Badge tone="green">97%</Badge>
              </>
            )}
          </div>
        </div>
      </Panel>

      {incompatible && (
        <div className="controls-callout controls-callout--amber" role="status">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>
            The baseline used local-only policy. Provider-only rows remain UNKNOWN;
            comparable local results are still shown below.
          </span>
          <Button size="compact" onClick={() => setPreviousRun('run-syn-0615')}>Use compatible run</Button>
        </div>
      )}

      <section className="controls-diff-summary" aria-label="Change summary">
        {summary.map(([state, count, tone]) => (
          <button
            type="button"
            key={state}
            className={filter === state ? 'is-selected' : ''}
            onClick={() => setFilter(filter === state ? 'ALL' : state)}
            aria-pressed={filter === state}
          >
            <span className={`controls-diff-glyph controls-diff-glyph--${tone}`} aria-hidden="true" />
            <div>
              <small>{state}</small>
              <strong>{count}</strong>
            </div>
          </button>
        ))}
      </section>

      <div className="controls-comparison-layout">
        <Panel
          className="controls-comparison-list panel--raised"
          eyebrow="Material changes"
          title={`${visibleRows.length} comparison rows`}
          action={
            <Button size="compact" variant="ghost" onClick={() => setFilter('ALL')}>
              <Filter size={13} aria-hidden="true" />
              {filter === 'ALL' ? 'All states' : filter}
            </Button>
          }
        >
          <div className="controls-table-scroll" role="region" aria-label="Run comparison results table" tabIndex={0}>
            <table className="data-table controls-diff-table">
              <caption className="sr-only">Material differences between selected synthetic runs</caption>
              <thead>
                <tr>
                  <th scope="col">Finding</th>
                  <th scope="col">Baseline</th>
                  <th scope="col">Current</th>
                  <th scope="col">State</th>
                  <th scope="col">Impact</th>
                  <th scope="col"><span className="sr-only">Inspect</span></th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.item} className={selected.item === row.item ? 'is-selected' : ''}>
                    <th scope="row">
                      <button type="button" onClick={() => setSelected(row)}>{row.item}</button>
                      <small>{row.source}</small>
                    </th>
                    <td>{row.previous}</td>
                    <td>{row.current}</td>
                    <td><Badge tone={stateTone(row.state)}>{row.state}</Badge></td>
                    <td>{row.impact}</td>
                    <td>
                      <button type="button" className="controls-row-action" onClick={() => setSelected(row)} aria-label={`Inspect ${row.item}`}>
                        <ArrowRight size={14} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel
          className="controls-diff-inspector panel--raised"
          eyebrow="Before / after"
          title={selected.item}
          action={<Badge tone={stateTone(selected.state)}>{selected.state}</Badge>}
        >
          <div className="controls-version-pair">
            <article>
              <span>Baseline · 15 Jun</span>
              <strong>{selected.previous}</strong>
              <small>Evidence EV-SYN-0615-04</small>
            </article>
            <ArrowRight size={18} aria-hidden="true" />
            <article>
              <span>Current · 11 Jul</span>
              <strong>{selected.current}</strong>
              <small>Evidence EV-SYN-0711-09</small>
            </article>
          </div>
          <div className="controls-inspector-explanation">
            {selected.state === 'ARCHIVED' ? <Archive size={17} aria-hidden="true" /> :
              selected.state === 'UNKNOWN' ? <CircleHelp size={17} aria-hidden="true" /> :
                <GitCompareArrows size={17} aria-hidden="true" />}
            <p>{selected.detail}</p>
          </div>
          <dl className="controls-compact-dl">
            <div><dt>Source coverage</dt><dd>{selected.state === 'UNKNOWN' ? 'Not equivalent' : 'Equivalent'}</dd></div>
            <div><dt>Content hash</dt><dd className="mono">{selected.state === 'CHANGED' ? 'Changed' : 'Recorded separately'}</dd></div>
            <div><dt>Attribution</dt><dd>Probable · unchanged</dd></div>
            <div><dt>Review status</dt><dd>Human review pending</dd></div>
          </dl>
          <div className="controls-inspector-actions">
            <Button size="compact" variant="primary">Open current evidence</Button>
            <Button size="compact"><RotateCcw size={13} aria-hidden="true" /> Add to monitoring</Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}

const nativeStateTone: Record<Phase6FindingDiffState, Tone> = {
  NEW: 'cyan',
  CHANGED: 'violet',
  REMOVED: 'green',
  REAPPEARED: 'amber',
  UNCHANGED: 'neutral',
}

const nativeSummaryStates: ReadonlyArray<
  readonly [Phase6FindingDiffState, Tone]
> = [
  ['NEW', 'cyan'],
  ['CHANGED', 'violet'],
  ['REMOVED', 'green'],
  ['REAPPEARED', 'amber'],
  ['UNCHANGED', 'neutral'],
]

function words(value: string): string {
  return value
    .toLocaleLowerCase()
    .replaceAll('_', ' ')
    .replace(/^./, (character) => character.toLocaleUpperCase())
}

function displayTime(timestampUs: number): string {
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

function fingerprint(value: string | null): string {
  return value === null ? 'Not observed' : `${value.slice(0, 12)}…${value.slice(-8)}`
}

function runLabel(run: Phase6AuditRunSummary): string {
  return `${displayTime(run.capturedAtUs)} · Run ${run.sequence}`
}

function diffExplanation(diff: Phase6FindingDiff): string {
  switch (diff.state) {
    case 'NEW':
      return 'Observed in the current snapshot without a prior observation in the retained timeline.'
    case 'CHANGED':
      return 'The normalized content fingerprint changed. Review evidence before drawing a substantive conclusion.'
    case 'REMOVED':
      return 'Absent under complete equivalent coverage. This does not prove removal from caches, mirrors, or archives.'
    case 'REAPPEARED':
      return 'Observed again after a conclusive intervening absence in the retained audit timeline.'
    case 'UNCHANGED':
      return 'The normalized content fingerprint is unchanged across the selected snapshots.'
  }
}

function NativeLoadedComparison({
  comparison,
  runs,
  filter,
  setFilter,
}: {
  readonly comparison: Phase6AuditComparison
  readonly runs: ReadonlyArray<Phase6AuditRunSummary>
  readonly filter: 'ALL' | Phase6FindingDiffState
  readonly setFilter: (state: 'ALL' | Phase6FindingDiffState) => void
}) {
  const [selectedStableId, setSelectedStableId] = useState<string | null>(null)
  const visibleDiffs = useMemo(
    () =>
      comparison.diffs.filter(
        (diff) => filter === 'ALL' || diff.state === filter,
      ),
    [comparison.diffs, filter],
  )
  const selected =
    comparison.diffs.find((diff) => diff.stableId === selectedStableId) ??
    visibleDiffs[0] ??
    comparison.diffs[0] ??
    null
  const lifecycle = comparison.lifecycles.find(
    (item) => item.stableId === selected?.stableId,
  )
  const baseline = runs.find(
    (run) => run.runId === comparison.baselineRunId,
  )
  const current = runs.find((run) => run.runId === comparison.currentRunId)
  const coverageByProvider = new Map(
    comparison.coverage.map((item) => [item.providerId, item]),
  )
  const counts = new Map<Phase6FindingDiffState, number>()
  for (const diff of comparison.diffs) {
    counts.set(diff.state, (counts.get(diff.state) ?? 0) + 1)
  }

  return (
    <>
      {comparison.incompleteComparison ? (
        <div className="controls-callout controls-callout--amber" role="status">
          <AlertTriangle size={17} aria-hidden="true" />
          <span>
            This comparison is incomplete: {comparison.incompleteReasons.map(words).join('; ')}.
            Missing observations remain unresolved and are not classified as removals.
          </span>
        </div>
      ) : null}

      {comparison.unresolvedAbsences.length > 0 ? (
        <div className="controls-callout controls-callout--amber" role="status">
          <CircleHelp size={17} aria-hidden="true" />
          <span>
            {comparison.unresolvedAbsences.length} prior observation{comparison.unresolvedAbsences.length === 1 ? '' : 's'} could not be resolved because current provider coverage was incomplete.
          </span>
          <Badge tone="amber">Not removed</Badge>
        </div>
      ) : null}

      <section className="controls-diff-summary controls-diff-summary--phase6" aria-label="Persisted change summary">
        {nativeSummaryStates.map(([state, tone]) => (
          <button
            type="button"
            key={state}
            className={filter === state ? 'is-selected' : ''}
            onClick={() => setFilter(filter === state ? 'ALL' : state)}
            aria-pressed={filter === state}
          >
            <span className={`controls-diff-glyph controls-diff-glyph--${tone}`} aria-hidden="true" />
            <div>
              <small>{state}</small>
              <strong>{counts.get(state) ?? 0}</strong>
            </div>
          </button>
        ))}
      </section>

      {comparison.diffs.length === 0 ? (
        <Phase6StatePanel
          state="empty"
          title="No comparable findings in this pair"
          detail="The selected persisted snapshots produced no material or unchanged finding rows. Review provider coverage before treating this as an absence result."
        />
      ) : (
        <div className="controls-comparison-layout">
          <Panel
            className="controls-comparison-list panel--raised"
            eyebrow="Persisted lifecycle diff"
            title={`${visibleDiffs.length} comparison rows`}
            action={
              <Button size="compact" variant="ghost" onClick={() => setFilter('ALL')}>
                <Filter size={13} aria-hidden="true" />
                {filter === 'ALL' ? 'All states' : filter}
              </Button>
            }
          >
            <div className="controls-table-scroll" role="region" aria-label="Persisted run comparison results table" tabIndex={0}>
              <table className="data-table controls-diff-table">
                <caption className="sr-only">Finding lifecycle differences between selected persisted audit runs</caption>
                <thead>
                  <tr>
                    <th scope="col">Finding identity</th>
                    <th scope="col">Baseline</th>
                    <th scope="col">Current</th>
                    <th scope="col">State</th>
                    <th scope="col">Provider</th>
                    <th scope="col"><span className="sr-only">Inspect</span></th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDiffs.map((diff) => (
                    <tr key={diff.stableId} className={selected?.stableId === diff.stableId ? 'is-selected' : ''}>
                      <th scope="row">
                        <button type="button" onClick={() => setSelectedStableId(diff.stableId)}>{shortId(diff.stableId)}</button>
                        <small>Stable local identifier</small>
                      </th>
                      <td className="mono">{fingerprint(diff.previousFingerprint)}</td>
                      <td className="mono">{fingerprint(diff.currentFingerprint)}</td>
                      <td><Badge tone={nativeStateTone[diff.state]}>{diff.state}</Badge></td>
                      <td className="mono">{shortId(diff.providerId)}</td>
                      <td>
                        <button type="button" className="controls-row-action" onClick={() => setSelectedStableId(diff.stableId)} aria-label={`Inspect finding ${diff.stableId}`}>
                          <ArrowRight size={14} aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {selected ? (
            <Panel
              className="controls-diff-inspector panel--raised"
              eyebrow="Before / after"
              title={shortId(selected.stableId)}
              action={<Badge tone={nativeStateTone[selected.state]}>{selected.state}</Badge>}
            >
              <div className="controls-version-pair">
                <article>
                  <span>Baseline · {baseline ? `run ${baseline.sequence}` : 'persisted run'}</span>
                  <strong className="mono">{fingerprint(selected.previousFingerprint)}</strong>
                  <small>{baseline ? displayTime(baseline.capturedAtUs) : shortId(comparison.baselineRunId)}</small>
                </article>
                <ArrowRight size={18} aria-hidden="true" />
                <article>
                  <span>Current · {current ? `run ${current.sequence}` : 'persisted run'}</span>
                  <strong className="mono">{fingerprint(selected.currentFingerprint)}</strong>
                  <small>{current ? displayTime(current.capturedAtUs) : shortId(comparison.currentRunId)}</small>
                </article>
              </div>
              <div className="controls-inspector-explanation">
                <GitCompareArrows size={17} aria-hidden="true" />
                <p>{diffExplanation(selected)}</p>
              </div>
              <dl className="controls-compact-dl">
                <div><dt>Provider</dt><dd className="mono">{shortId(selected.providerId)}</dd></div>
                <div><dt>Baseline coverage</dt><dd>{words(coverageByProvider.get(selected.providerId)?.baselineState ?? 'NOT_AVAILABLE')}</dd></div>
                <div><dt>Current coverage</dt><dd>{words(coverageByProvider.get(selected.providerId)?.currentState ?? 'NOT_AVAILABLE')}</dd></div>
                <div><dt>Lifecycle events</dt><dd>{lifecycle?.events.length ?? 0} retained</dd></div>
              </dl>
              {lifecycle ? (
                <div className="controls-case-history controls-lifecycle-history">
                  <h3>Retained lifecycle</h3>
                  <ol>
                    {lifecycle.events.map((event) => (
                      <li key={event.runId}>
                        <span>Run {event.sequence}</span>
                        <strong>{event.observed ? 'Observed' : 'Not observed'} · {words(event.runState)}</strong>
                        <small>{event.providerCoverage === null ? 'Provider absent from run' : `${words(event.providerCoverage)} coverage`}</small>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
              <div className="controls-inspector-actions">
                <Button size="compact" variant="primary" disabled title="Evidence navigation is not part of the current read-only Phase 6 bridge">
                  Evidence view pending
                </Button>
                <Button size="compact" disabled title="Monitoring mutations are not implemented yet">
                  <RotateCcw size={13} aria-hidden="true" /> Monitoring write pending
                </Button>
              </div>
            </Panel>
          ) : null}
        </div>
      )}
    </>
  )
}

function NativeComparePage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [runResult, setRunResult] = useState<{
    readonly profileId: string
    readonly data: Phase6AuditRunList
  } | null>(null)
  const [runErrorProfileId, setRunErrorProfileId] = useState<string | null>(null)
  const [runRevision, setRunRevision] = useState(0)
  const [pair, setPair] = useState<{
    readonly profileId: string
    readonly baselineRunId: string
    readonly currentRunId: string
  } | null>(null)
  const [comparisonResult, setComparisonResult] = useState<{
    readonly key: string
    readonly data: Phase6AuditComparison
  } | null>(null)
  const [comparisonErrorKey, setComparisonErrorKey] = useState<string | null>(null)
  const [comparisonRevision, setComparisonRevision] = useState(0)
  const [filter, setFilter] = useState<'ALL' | Phase6FindingDiffState>('ALL')

  useEffect(() => {
    document.title = 'Compare Runs · Codename Ariadne'
  }, [])

  useEffect(() => {
    if (profileId === null) return
    let cancelled = false
    setRunErrorProfileId(null)
    void loadPhase6AuditRuns({ profileId, limit: 32 })
      .then((data) => {
        if (!cancelled) setRunResult({ profileId, data })
      })
      .catch(() => {
        if (!cancelled) setRunErrorProfileId(profileId)
      })
    return () => {
      cancelled = true
    }
  }, [profileId, runRevision])

  const activeRuns = runResult?.profileId === profileId ? runResult.data : null
  const sortedRuns = useMemo(
    () => [...(activeRuns?.runs ?? [])].sort((left, right) => right.sequence - left.sequence),
    [activeRuns],
  )

  useEffect(() => {
    if (profileId === null || sortedRuns.length < 2) return
    const runIds = new Set(sortedRuns.map((run) => run.runId))
    setPair((current) => {
      if (
        current?.profileId === profileId &&
        current.baselineRunId !== current.currentRunId &&
        runIds.has(current.baselineRunId) &&
        runIds.has(current.currentRunId)
      ) {
        return current
      }
      return {
        profileId,
        baselineRunId: sortedRuns[1].runId,
        currentRunId: sortedRuns[0].runId,
      }
    })
  }, [profileId, sortedRuns])

  const activePair =
    pair?.profileId === profileId &&
    sortedRuns.some((run) => run.runId === pair.baselineRunId) &&
    sortedRuns.some((run) => run.runId === pair.currentRunId)
      ? pair
      : null
  const comparisonKey = activePair === null
    ? null
    : `${activePair.profileId}:${activePair.baselineRunId}:${activePair.currentRunId}`

  useEffect(() => {
    if (activePair === null || comparisonKey === null) return
    let cancelled = false
    setComparisonErrorKey(null)
    void loadPhase6AuditComparison(activePair)
      .then((data) => {
        if (!cancelled) setComparisonResult({ key: comparisonKey, data })
      })
      .catch(() => {
        if (!cancelled) setComparisonErrorKey(comparisonKey)
      })
    return () => {
      cancelled = true
    }
  }, [activePair, comparisonKey, comparisonRevision])

  const activeComparison =
    comparisonResult?.key === comparisonKey ? comparisonResult.data : null

  const updatePair = (next: Partial<Pick<NonNullable<typeof activePair>, 'baselineRunId' | 'currentRunId'>>) => {
    if (activePair === null) return
    setFilter('ALL')
    setPair({ ...activePair, ...next })
  }

  return (
    <div className="page controls-page compare-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Compare Runs · Encrypted local snapshots"
        title="What changed between snapshots?"
        description="Compare persisted finding fingerprints and provider coverage without turning incomplete observations into false removal claims."
        meta={
          <>
            <Badge tone="green" dot>Native vault</Badge>
            <Badge tone="cyan">Deterministic local diff</Badge>
            {activeComparison?.incompleteComparison ? <Badge tone="amber">Incomplete comparison</Badge> : null}
          </>
        }
        actions={
          <Button disabled title="Evidence navigation is not part of the current read-only Phase 6 bridge">
            <Eye size={15} aria-hidden="true" /> Evidence view pending
          </Button>
        }
      />

      {profileId === null ? null : (
        <NativeCheckpointForm
          profileId={profileId}
          onCreated={() => setRunRevision((current) => current + 1)}
        />
      )}

      {profileId === null ? (
        <Phase6StatePanel
          state="no-profile"
          title="No active profile"
          detail="Create or resume a local audit profile before comparing persisted runs. Native mode never substitutes synthetic snapshots."
        />
      ) : runErrorProfileId === profileId ? (
        <Phase6StatePanel
          state="error"
          title="Persisted audit runs are unavailable"
          detail="The local core did not return a valid profile-bound run list. No partial or demo comparison is shown."
          onRetry={() => setRunRevision((current) => current + 1)}
        />
      ) : activeRuns === null ? (
        <Phase6StatePanel
          state="loading"
          title="Loading persisted audit runs"
          detail="Reading bounded snapshot metadata from the active encrypted profile."
        />
      ) : sortedRuns.length < 2 ? (
        <Phase6StatePanel
          state="insufficient"
          title="Two persisted runs are required"
          detail={`${sortedRuns.length} audit run${sortedRuns.length === 1 ? ' is' : 's are'} available. A comparison is not inferred and synthetic history is not added.`}
        />
      ) : activePair === null ? (
        <Phase6StatePanel
          state="loading"
          title="Preparing run selection"
          detail="Binding two distinct persisted snapshots to the active profile."
        />
      ) : (
        <>
          <Panel className="controls-run-pair panel--raised" eyebrow="Snapshot pair" title="Persisted run selection">
            <div className="controls-run-pair__grid">
              <label className="controls-run-select">
                <span>Baseline run</span>
                <select value={activePair.baselineRunId} onChange={(event) => updatePair({ baselineRunId: event.target.value })}>
                  {sortedRuns.filter((run) => run.runId !== activePair.currentRunId).map((run) => (
                    <option key={run.runId} value={run.runId}>{runLabel(run)}</option>
                  ))}
                </select>
                {(() => {
                  const run = sortedRuns.find((item) => item.runId === activePair.baselineRunId)
                  return <small>{run ? `${words(run.runState)} · ${run.findingCount} findings · ${run.providerCount} providers` : 'Persisted run'}</small>
                })()}
              </label>

              <Button className="controls-swap-button" size="compact" onClick={() => updatePair({ baselineRunId: activePair.currentRunId, currentRunId: activePair.baselineRunId })} aria-label="Swap baseline and current runs">
                <ArrowRightLeft size={15} aria-hidden="true" />
              </Button>

              <label className="controls-run-select">
                <span>Current run</span>
                <select value={activePair.currentRunId} onChange={(event) => updatePair({ currentRunId: event.target.value })}>
                  {sortedRuns.filter((run) => run.runId !== activePair.baselineRunId).map((run) => (
                    <option key={run.runId} value={run.runId}>{runLabel(run)}</option>
                  ))}
                </select>
                {(() => {
                  const run = sortedRuns.find((item) => item.runId === activePair.currentRunId)
                  return <small>{run ? `${words(run.runState)} · ${run.findingCount} findings · ${run.providerCount} providers` : 'Persisted run'}</small>
                })()}
              </label>

              <div className="controls-compatibility">
                {activeComparison?.incompleteComparison ? <AlertTriangle size={17} aria-hidden="true" /> : <CheckCircle2 size={17} aria-hidden="true" />}
                <div>
                  <strong>{activeComparison === null ? 'Validating coverage' : activeComparison.incompleteComparison ? 'Coverage differs' : 'Coverage resolved'}</strong>
                  <small>{activeComparison === null ? 'Waiting for the local comparison.' : `${activeComparison.coverage.length} provider coverage records compared.`}</small>
                </div>
                <Badge tone={activeComparison?.incompleteComparison ? 'amber' : 'green'}>{activeComparison?.incompleteComparison ? 'Partial' : 'Local'}</Badge>
              </div>
            </div>
          </Panel>

          {comparisonErrorKey === comparisonKey ? (
            <Phase6StatePanel
              state="error"
              title="The selected runs could not be compared"
              detail="The local response failed validation or no longer matched the active profile and snapshot pair. No partial lifecycle is shown."
              onRetry={() => setComparisonRevision((current) => current + 1)}
            />
          ) : activeComparison === null ? (
            <Phase6StatePanel
              state="loading"
              title="Comparing persisted snapshots"
              detail="Validating finding lifecycles, fingerprints, and provider coverage before rendering any result."
            />
          ) : (
            <NativeLoadedComparison
              comparison={activeComparison}
              runs={sortedRuns}
              filter={filter}
              setFilter={setFilter}
            />
          )}
        </>
      )}
    </div>
  )
}

function NativeCheckpointForm({
  profileId,
  onCreated,
}: {
  readonly profileId: string
  readonly onCreated: () => void
}) {
  const [providerText, setProviderText] = useState('manual.local')
  const [coverageState, setCoverageState] =
    useState<Phase6ProviderCoverageState>('COMPLETE')
  const [runState, setRunState] =
    useState<Phase6SnapshotRunState>('COMPLETED')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<
    | { readonly tone: 'success' | 'danger'; readonly message: string }
    | null
  >(null)
  const providerIds = providerText
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
  const uniqueProviderIds = [...new Set(providerIds)]
  const providersValid =
    uniqueProviderIds.length >= 1 &&
    uniqueProviderIds.length <= 256 &&
    uniqueProviderIds.length === providerIds.length &&
    uniqueProviderIds.every((value) =>
      /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value),
    )

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !providersValid) return
    setBusy(true)
    setStatus(null)
    try {
      const checkpoint = await createPhase6LocalCheckpoint({
        profileId,
        runState,
        providerCoverage: uniqueProviderIds.map((providerId) => ({
          providerId,
          state: coverageState,
        })),
      })
      setStatus({
        tone: 'success',
        message: `Local checkpoint ${checkpoint.sequence.toLocaleString()} saved with ${checkpoint.findingCount.toLocaleString()} finding fingerprints.`,
      })
      onCreated()
    } catch {
      setStatus({
        tone: 'danger',
        message:
          'The checkpoint was not created. Confirm provider IDs match the findings being captured and the vault is unlocked.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      className="phase6-checkpoint-panel panel--raised"
      eyebrow="Network-free monitoring"
      title="Create a local checkpoint"
      action={<Badge tone="cyan">Fingerprints only</Badge>}
    >
      <form className="phase6-checkpoint-form" onSubmit={(event) => void submit(event)}>
        <p>
          Snapshot current persisted findings for the listed providers. Evidence bytes are never copied and no provider is contacted.
        </p>
        <label className="field phase6-checkpoint-providers">
          <span>Provider IDs · comma separated</span>
          <input className="input mono" value={providerText} maxLength={32_767} disabled={busy} required onChange={(event) => { setProviderText(event.target.value); setStatus(null) }} />
          {!providersValid ? <small className="field-error">Use 1–256 unique opaque IDs with letters, digits, dots, underscores, colons, or hyphens.</small> : null}
        </label>
        <label className="field">
          <span>Coverage</span>
          <select className="select" value={coverageState} disabled={busy} onChange={(event) => { setCoverageState(event.target.value as Phase6ProviderCoverageState); setStatus(null) }}>
            {(['COMPLETE', 'NOT_CHECKED', 'BLOCKED', 'CHECK_FAILED'] as const).map((value) => <option key={value} value={value}>{words(value)}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Run state</span>
          <select className="select" value={runState} disabled={busy} onChange={(event) => { setRunState(event.target.value as Phase6SnapshotRunState); setStatus(null) }}>
            {(['COMPLETED', 'PARTIAL', 'CANCELLED', 'FAILED'] as const).map((value) => <option key={value} value={value}>{words(value)}</option>)}
          </select>
        </label>
        <Button type="submit" disabled={busy || !providersValid}>
          <Save size={14} aria-hidden="true" /> {busy ? 'Saving…' : 'Save checkpoint'}
        </Button>
      </form>
      {status ? <div className={`callout callout--${status.tone}`} role={status.tone === 'danger' ? 'alert' : 'status'}>{status.message}</div> : null}
    </Panel>
  )
}

export function ComparePage() {
  return nativeRuntimeAvailable() ? <NativeComparePage /> : <SimulatedComparePage />
}

export default ComparePage
