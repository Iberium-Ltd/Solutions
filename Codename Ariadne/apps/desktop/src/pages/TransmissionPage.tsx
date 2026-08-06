/** Policy-bound provider planning and network-free preflight; compilation is not dispatch. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  EyeOff,
  Globe2,
  ListChecks,
  LockKeyhole,
  MapPinned,
  RotateCcw,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Timer,
} from 'lucide-react'
import { providers, transmissionLedger } from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import { usePrototypeStore } from '../app/prototypeStore'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  createQueryPlan,
  executeQueryDryRun,
  loadQueryProviders,
} from '../app/queryBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { useIdentityOverview } from '../app/useIdentityOverview'
import type {
  QueryPlanCell,
  QueryPlanResult,
  QueryPolicyMode,
  QueryProviderSummary,
} from '../../../../packages/contracts/src/generated/api'
import '../styles/pages-controls.css'

type ApprovalState = 'pending' | 'approved' | 'denied'

const modes = [
  {
    id: 'local' as const,
    title: 'Local only',
    detail: 'Identifiers never leave this Mac.',
    icon: LockKeyhole,
  },
  {
    id: 'eu' as const,
    title: 'EU only',
    detail: 'Allow reviewed providers hosted in the EU.',
    icon: MapPinned,
  },
  {
    id: 'worldwide' as const,
    title: 'Worldwide',
    detail: 'Require per-provider risk review.',
    icon: Globe2,
  },
  {
    id: 'custom' as const,
    title: 'Custom policy',
    detail: 'Use explicit allow and block lists.',
    icon: SlidersHorizontal,
  },
] as const

const policyRows = [
  { provider: 'Local Corpus Engine', operator: 'On device', hosting: 'Local', payload: 'Local index only', retention: 'None external', risk: 'Low', result: 'ALLOW' },
  { provider: 'Boreal Search', operator: 'FI', hosting: 'EU', payload: 'Masked username', retention: '30 days declared', risk: 'Medium', result: 'REVIEW' },
  { provider: 'Meridian Archive', operator: 'NL', hosting: 'EU', payload: 'Public alias', retention: 'Unknown', risk: 'Medium', result: 'REVIEW' },
  { provider: 'Image Observatory', operator: 'US', hosting: 'US', payload: 'Image fingerprint', retention: 'Unknown', risk: 'High', result: 'BLOCK' },
] as const

const maskLedgerValue = (value: string) => {
  if (value.startsWith('@')) return '@n•••••••••'
  if (value.includes('@')) return 'm•••••@example.invalid'
  if (value === 'Greyhaven') return 'Coarse location · G••••••••'
  return 'Image fingerprint · masked'
}

function SimulatedTransmissionPage() {
  const { transmissionMode, setTransmissionMode } = usePrototypeStore()
  const [approval, setApproval] = useState<ApprovalState>('pending')
  const [customEu, setCustomEu] = useState(true)
  const [customUs, setCustomUs] = useState(false)

  useEffect(() => {
    document.title = 'Transmission · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  const policyResult = transmissionMode === 'local'
    ? 'Outside current policy'
    : transmissionMode === 'eu' || (transmissionMode === 'custom' && customEu)
      ? 'Eligible for one-time approval'
      : transmissionMode === 'worldwide'
        ? 'High-attention approval'
        : 'Blocked by custom policy'

  return (
    <div className="page controls-page transmission-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Transmission control · Preflight"
        title="Know what leaves the device"
        description="Policy limits provider eligibility; every sensitive disclosure still shows its purpose, masking, jurisdiction, retention, cost, and risk before approval."
        meta={
          <>
            <Badge tone="green" dot>Local only by default</Badge>
            <Badge tone="amber">1 pending decision</Badge>
            <Badge tone="cyan">Ledger stays local</Badge>
          </>
        }
        actions={<Button><ListChecks size={15} aria-hidden="true" /> Export redacted ledger</Button>}
      />

      <section className="controls-transmission-modes" aria-labelledby="transmission-mode-heading">
        <div className="controls-section-heading">
          <div><span className="eyebrow">Policy mode</span><h2 id="transmission-mode-heading">Where may reviewed data go?</h2></div>
          <Badge tone="cyan">Current · {modes.find((mode) => mode.id === transmissionMode)?.title}</Badge>
        </div>
        <div className="controls-mode-grid" role="radiogroup" aria-label="Transmission policy mode">
          {modes.map((mode) => {
            const Icon = mode.icon
            return (
              <button
                type="button"
                role="radio"
                aria-checked={transmissionMode === mode.id}
                className={transmissionMode === mode.id ? 'is-selected' : ''}
                key={mode.id}
                onClick={() => setTransmissionMode(mode.id)}
              >
                <span className="controls-mode-icon"><Icon size={18} aria-hidden="true" /></span>
                <span><strong>{mode.title}</strong><small>{mode.detail}</small></span>
                <span className="controls-radio-dot" aria-hidden="true" />
              </button>
            )
          })}
        </div>
        {transmissionMode === 'worldwide' && (
          <div className="controls-callout controls-callout--amber" role="status">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>Worldwide mode broadens eligibility only. It does not approve any provider or disclosure.</span>
          </div>
        )}
        {transmissionMode === 'custom' && (
          <div className="controls-custom-policy" aria-label="Custom region rules">
            <label><input type="checkbox" checked={customEu} onChange={(event) => setCustomEu(event.target.checked)} /> EU hosting allowed</label>
            <label><input type="checkbox" checked={customUs} onChange={(event) => setCustomUs(event.target.checked)} /> US hosting allowed</label>
            <span>Unknown hosting remains blocked.</span>
          </div>
        )}
      </section>

      <Panel
        className={`controls-preflight panel--raised is-${approval}`}
        eyebrow="Pending disclosure · SYN-TX-004"
        title="Sensitive username search"
        action={
          approval === 'pending' ? <Badge tone="amber" dot>Decision required</Badge>
            : approval === 'approved' ? <Badge tone="green" dot>Approved once · simulated</Badge>
              : <Badge tone="rose" dot>Denied · not sent</Badge>
        }
      >
        <div className="controls-preflight-boundary">
          <div className="controls-preflight-payload">
            <span className="status-icon status-icon--amber"><Send size={18} /></span>
            <div>
              <span>Payload · masked</span>
              <strong className="mono">@n•••••••••</strong>
              <small>Category: historical username · 1 exact query variant</small>
            </div>
            <Badge tone="cyan"><EyeOff size={11} /> Masked in ledger</Badge>
          </div>
          <div className="controls-preflight-route" aria-label="Transmission route">
            <span>THIS MAC</span><i aria-hidden="true" /><span>BOREAL SEARCH</span><i aria-hidden="true" /><span>EU HOSTING</span>
          </div>
        </div>

        <div className="controls-preflight-grid">
          <dl>
            <div><dt>Provider</dt><dd>Boreal Search</dd></div>
            <div><dt>Access basis</dt><dd>Official public API</dd></div>
            <div><dt>Operator country</dt><dd>Finland · FI</dd></div>
            <div><dt>Hosting regions</dt><dd>European Union</dd></div>
          </dl>
          <dl>
            <div><dt>Purpose</dt><dd>Exact public profile search</dd></div>
            <div><dt>Retention</dt><dd>30 days declared</dd></div>
            <div><dt>Estimated cost</dt><dd><CircleDollarSign size={12} /> €0.02 · estimate</dd></div>
            <div><dt>Estimated duration</dt><dd><Timer size={12} /> 2–4 seconds</dd></div>
          </dl>
          <div className="controls-policy-verdict">
            <span>Current policy result</span>
            <strong>{policyResult}</strong>
            <Badge tone={policyResult.includes('Blocked') || policyResult.includes('Outside') ? 'rose' : 'amber'}>Medium risk</Badge>
            <small>Approval is scoped only to this synthetic run and creates a local ledger entry.</small>
          </div>
        </div>

        {approval === 'pending' ? (
          <div className="controls-preflight-actions">
            <Button variant="primary" onClick={() => setApproval('denied')}>
              <Ban size={14} aria-hidden="true" /> Deny and keep local
            </Button>
            <Button className="controls-approve-exception" onClick={() => setApproval('approved')}>
              <ShieldCheck size={14} aria-hidden="true" /> Approve once
            </Button>
            <Button variant="ghost">Return to edit</Button>
            <span>No approval is preselected.</span>
          </div>
        ) : (
          <div className={`controls-decision-result is-${approval}`} role="status">
            {approval === 'approved' ? <CheckCircle2 size={17} aria-hidden="true" /> : <Ban size={17} aria-hidden="true" />}
            <span>{approval === 'approved' ? 'Approval recorded in memory; Phase 1 sent no request.' : 'Provider remains NOT_CHECKED and is not interpreted as absence.'}</span>
            <Button size="compact" variant="ghost" onClick={() => setApproval('pending')}><RotateCcw size={13} /> Reset decision</Button>
          </div>
        )}
      </Panel>

      <div className="controls-transmission-lower">
        <Panel className="controls-policy-matrix panel--raised" eyebrow="Provider policy" title="Allow, review, and block results">
          <div className="controls-table-scroll" role="region" aria-label="Provider transmission policy table" tabIndex={0}>
            <table className="data-table">
              <caption className="sr-only">Provider transmission policy results</caption>
              <thead><tr><th scope="col">Provider</th><th scope="col">Operator / host</th><th scope="col">Payload</th><th scope="col">Retention</th><th scope="col">Risk</th><th scope="col">Result</th></tr></thead>
              <tbody>
                {policyRows.map((row) => (
                  <tr key={row.provider}>
                    <th scope="row">{row.provider}</th>
                    <td>{row.operator} / {row.hosting}</td>
                    <td>{row.payload}</td>
                    <td className={row.retention === 'Unknown' ? 'is-warning' : ''}>{row.retention}</td>
                    <td>{row.risk}</td>
                    <td><Badge tone={row.result === 'ALLOW' ? 'green' : row.result === 'REVIEW' ? 'amber' : 'rose'}>{row.result}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel className="controls-ledger panel--raised" eyebrow="Local audit trail" title="Transmission ledger" action={<Badge><LockKeyhole size={11} /> Masked</Badge>}>
          <ul>
            {transmissionLedger.map((entry) => (
              <li key={entry.time + entry.provider}>
                <time className="mono">{entry.time}</time>
                <div><strong>{entry.provider}</strong><small>{entry.purpose} · {entry.region}</small></div>
                <span className="mono">{maskLedgerValue(entry.value)}</span>
                <Badge tone={entry.result.includes('Blocked') ? 'rose' : entry.result.includes('Local') ? 'cyan' : 'green'}>{entry.result}</Badge>
              </li>
            ))}
          </ul>
          <div className="controls-ledger-footer"><Clock3 size={13} /><span>Ledger records decisions without duplicating unnecessary plaintext.</span></div>
        </Panel>
      </div>

      <div className="controls-callout controls-callout--success">
        <ShieldCheck size={16} aria-hidden="true" />
        <span>{providers.filter((provider) => !provider.sendsIdentifiers).length} enabled provider processes entirely on device; all prototype traffic remains simulated.</span>
      </div>
    </div>
  )
}

function NativeTransmissionPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const overview = useIdentityOverview()
  const [providers, setProviders] = useState<ReadonlyArray<QueryProviderSummary>>(
    [],
  )
  const [selected, setSelected] = useState<ReadonlyArray<string>>([])
  const [policyMode, setPolicyMode] =
    useState<QueryPolicyMode>('LOCAL_ONLY')
  const [maximumChecks, setMaximumChecks] = useState(12)
  const [maximumChecksPerProvider, setMaximumChecksPerProvider] = useState(6)
  const [plan, setPlan] = useState<QueryPlanResult | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Transmission · Codename Ariadne'
    if (profileId === null || overview.status !== 'READY') return
    let cancelled = false
    setError(null)
    void loadQueryProviders({ profileId })
      .then((catalog) => {
        if (cancelled) return
        setProviders(catalog.providers)
        setSelected(catalog.providers.map((provider) => provider.providerId))
      })
      .catch(() => {
        if (!cancelled) setError('Local provider catalog is unavailable.')
      })
    return () => {
      cancelled = true
    }
  }, [overview.status, profileId])

  const buildPlan = async () => {
    if (profileId === null || selected.length === 0) return
    setPending('plan')
    setError(null)
    try {
      setPlan(
        await createQueryPlan({
          profileId,
          purposeCode: 'AUTHORIZED_LOCAL_IDENTITY_REVIEW',
          providerIds: selected,
          policyMode,
          allowedProviderIds: policyMode === 'CUSTOM' ? selected : [],
          allowedRegions: policyMode === 'EU_ONLY' ? ['DE'] : [],
          maximumChecks,
          maximumChecksPerProvider,
        }),
      )
    } catch {
      setError('The local preflight could not be created.')
    } finally {
      setPending(null)
    }
  }

  const runDryCheck = async (cell: QueryPlanCell) => {
    if (profileId === null || plan === null) return
    setPending(cell.checkId)
    setError(null)
    try {
      const updated = await executeQueryDryRun({
        profileId,
        runId: plan.runId,
        checkId: cell.checkId,
        expectedRevision: cell.revision,
        approveOnce: cell.requiresApproval,
      })
      setPlan((current) =>
        current === null
          ? null
          : {
              ...current,
              cells: current.cells.map((item) =>
                item.checkId === updated.checkId ? updated : item,
              ),
            },
      )
    } catch {
      setError('The dry-run check could not be completed.')
    } finally {
      setPending(null)
    }
  }

  if (profileId === null || overview.status !== 'READY') {
    return (
      <div className="page controls-page transmission-page" data-testid="route-ready">
        <PageHeader
          eyebrow="Transmission control · Optional advanced preflight"
          title="No audit transmission record yet"
          description="The main audit workflow applies its selected provider and budget policy automatically. This advanced screen appears after a run and lets you inspect a local, network-free preflight."
          meta={<Badge tone="cyan">No identifiers transmitted</Badge>}
        />
        <div className="empty-state"><h2>No transmission data</h2><p>{overview.status === 'ERROR' ? overview.error : 'Start an audit first; no placeholder policy records are shown.'}</p><Link className="button button--primary" to="/audits/new">Start an audit</Link></div>
      </div>
    )
  }

  return (
    <div className="page controls-page transmission-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Transmission control · Native preflight"
        title="Plan checks without exposing identifiers"
        description="The core selects confirmed values. This screen receives masked cells only and never submits raw entity values."
        meta={
          <>
            <Badge tone="green" dot>Zero network access</Badge>
            <Badge tone="cyan">Local dry-run only</Badge>
          </>
        }
      />

      <Panel
        className="controls-policy-matrix panel--raised"
        eyebrow="Explicit policy"
        title="Select local providers and a bounded budget"
      >
        <div className="controls-custom-policy" aria-label="Query policy">
          <label>
            Policy
            <select
              className="select"
              aria-label="Query policy mode"
              value={policyMode}
              onChange={(event) =>
                setPolicyMode(event.target.value as QueryPolicyMode)
              }
            >
              <option value="LOCAL_ONLY">Local only</option>
              <option value="EU_ONLY">EU policy</option>
              <option value="CUSTOM">Custom allowlist</option>
            </select>
          </label>
          <label>
            Maximum checks
            <input
              className="input"
              aria-label="Maximum checks"
              type="number"
              min={1}
              max={200}
              value={maximumChecks}
              onChange={(event) => setMaximumChecks(Number(event.target.value))}
            />
          </label>
          <label>
            Per provider
            <input
              className="input"
              aria-label="Maximum checks per provider"
              type="number"
              min={1}
              max={100}
              value={maximumChecksPerProvider}
              onChange={(event) =>
                setMaximumChecksPerProvider(Number(event.target.value))
              }
            />
          </label>
        </div>
        <div className="controls-custom-policy" aria-label="Local providers">
          {providers.map((provider) => (
            <label key={provider.providerId}>
              <input
                type="checkbox"
                checked={selected.includes(provider.providerId)}
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, provider.providerId]
                      : current.filter((item) => item !== provider.providerId),
                  )
                }
              />
              {provider.displayName} · {provider.adapterMode.replaceAll('_', ' ')}
            </label>
          ))}
        </div>
        <div className="controls-preflight-actions">
          <Button
            variant="primary"
            disabled={
              pending !== null ||
              selected.length === 0 ||
              maximumChecksPerProvider > maximumChecks
            }
            onClick={() => void buildPlan()}
          >
            <ListChecks size={14} aria-hidden="true" />
            {pending === 'plan' ? 'Creating preflight…' : 'Create local preflight'}
          </Button>
          <span>A dry-run evaluates the dispatch boundary; it performs no search.</span>
        </div>
      </Panel>

      {error !== null && (
        <div className="controls-callout controls-callout--amber" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {plan !== null && (
        <Panel
          className="controls-policy-matrix panel--raised"
          eyebrow="Masked plan"
          title={`${plan.cells.length} explicit provider checks`}
          action={<Badge tone="cyan">Run · {plan.runId.slice(0, 8)}</Badge>}
        >
          <div
            className="controls-table-scroll"
            role="region"
            aria-label="Masked query plan"
            tabIndex={0}
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th>Masked entity</th>
                  <th>Provider</th>
                  <th>State</th>
                  <th>Coverage</th>
                  <th><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {plan.cells.map((cell) => (
                  <tr key={cell.checkId}>
                    <th scope="row" className="mono">{cell.maskedValue}</th>
                    <td>{cell.providerId}</td>
                    <td><Badge tone={cell.state === 'SUCCEEDED' ? 'green' : cell.state === 'BLOCKED' ? 'rose' : 'amber'}>{cell.state.replaceAll('_', ' ')}</Badge></td>
                    <td>{cell.outcome.replaceAll('_', ' ')}</td>
                    <td>
                      {cell.providerId === 'local-dry-run' &&
                        ['PLANNED', 'APPROVAL_REQUIRED'].includes(cell.state) && (
                          <Button
                            size="compact"
                            disabled={pending !== null}
                            onClick={() => void runDryCheck(cell)}
                          >
                            {pending === cell.checkId
                              ? 'Running…'
                              : cell.requiresApproval
                                ? 'Approve once & dry-run'
                                : 'Run dry-run'}
                          </Button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="controls-ledger-footer">
            <LockKeyhole size={13} />
            <span>NOT CHECKED is preserved as unknown coverage, never absence.</span>
          </div>
        </Panel>
      )}
    </div>
  )
}

export function TransmissionPage() {
  return nativeRuntimeAvailable() ? (
    <NativeTransmissionPage />
  ) : (
    <SimulatedTransmissionPage />
  )
}

export default TransmissionPage
