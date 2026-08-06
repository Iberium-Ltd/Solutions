/** Mission Control projection backed only by the active profile's newest persisted audit. */
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, BrainCircuit, FileSearch, Plus } from 'lucide-react'
import { Badge, Metric, PageHeader, Panel } from '../components/Primitives'
import { useIdentityOverview } from '../app/useIdentityOverview'

function EmptyDashboard({ message }: { message: string }) {
  return (
    <div className="page dashboard-page" data-testid="route-ready">
      <PageHeader eyebrow="Audit-backed overview" title="Mission Control" description="This screen is populated only by a real audit in the selected local profile." />
      <div className="empty-state">
        <span className="empty-state__icon"><FileSearch size={22} /></span>
        <h2>No audit data yet</h2>
        <p>{message}</p>
        <Link className="button button--primary" to="/audits/new"><Plus size={14} /> Start an audit</Link>
      </div>
    </div>
  )
}

export function NativeDashboardPage() {
  const overview = useIdentityOverview()
  if (overview.status === 'NO_PROFILE') return <EmptyDashboard message="Create or select a profile, then import identifiers." />
  if (overview.status === 'EMPTY') return <EmptyDashboard message="The selected profile exists, but it has no audit run." />
  if (overview.status === 'LOADING') return <div className="page dashboard-page" data-testid="route-ready"><div className="empty-state"><h2>Loading latest audit…</h2></div></div>
  if (overview.status === 'ERROR') return <EmptyDashboard message={overview.error} />

  const { audit, workspace } = overview
  const summary = audit.audit
  const unresolved = audit.proposals.filter((proposal) => !['ACCEPTED', 'REJECTED'].includes(proposal.reviewState))
  const failed = summary.taskStates.filter((entry) => entry.state.includes('FAILED')).reduce((total, entry) => total + entry.count, 0)
  const blocked = summary.taskStates.filter((entry) => ['BLOCKED', 'AUTH_REQUIRED', 'RATE_LIMITED'].includes(entry.state)).reduce((total, entry) => total + entry.count, 0)
  const progress = Math.round(summary.progressMicros / 10_000)
  const providers = [...new Set(audit.tasks.map((task) => task.providerId))]

  return (
    <div className="page dashboard-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit-backed overview"
        title="Mission Control"
        description={`Latest persisted run for ${workspace.person.displayName}. Every count below comes from this local audit.`}
        meta={<><Badge tone={summary.state === 'COMPLETED' ? 'green' : 'amber'} dot>{summary.state.toLowerCase()}</Badge><Badge tone="cyan">{summary.stage.toLowerCase().replaceAll('_', ' ')}</Badge><Badge tone="violet">{unresolved.length} reviews pending</Badge></>}
        actions={<><Link className="button button--secondary" to={`/identity/audits/${summary.auditId}`}>Open audit <ArrowRight size={14} /></Link><Link className="button button--primary" to="/audits/new"><Plus size={14} /> New audit</Link></>}
      />
      <div className="metric-grid">
        <Metric label="Progress" value={`${progress}%`} detail={`${summary.terminalTasks} of ${summary.totalTasks} tasks terminal`} tone="cyan" />
        <Metric label="Exact results" value={String(audit.results.length)} detail={`${summary.resultCount} recorded by the run`} tone="green" />
        <Metric label="Connected leads" value={String(audit.leads.length)} detail={`${providers.length} providers observed`} tone="violet" />
        <Metric label="Needs attention" value={String(unresolved.length + failed + blocked)} detail={`${failed} failed · ${blocked} blocked`} tone="amber" />
      </div>
      <div className="page-grid dashboard-grid">
        <Panel className="span-7 panel--signal" eyebrow="Latest audit" title={summary.name} action={<Badge tone="cyan">{progress}%</Badge>}>
          <div className="panel__body">
            <p>{summary.stopReason ?? `${summary.terminalTasks} of ${summary.totalTasks} tasks reached a terminal state.`}</p>
            <p className="mono">Mode {summary.mode} · depth {summary.maxDepth} · budget {summary.requestBudget}</p>
            <Link className="text-link" to={`/identity/audits/${summary.auditId}`}>Review sources, trace, and results <ArrowRight size={13} /></Link>
          </div>
        </Panel>
        <Panel className="span-5" eyebrow="AI analysis" title={audit.aiAnalysis?.title ?? 'No analysis produced'} action={<BrainCircuit size={16} />}>
          <div className="panel__body"><p>{audit.aiAnalysis?.summary ?? 'This run has not produced a cited AI analysis. Open the audit or AI Workspace to retry.'}</p>{audit.aiAnalysis && <Badge tone={audit.aiAnalysis.status === 'SUCCEEDED' ? 'green' : 'amber'}>{audit.aiAnalysis.status.toLowerCase()}</Badge>}</div>
        </Panel>
        <Panel className="span-12" eyebrow="Human review" title="Audit attention queue" action={<Link className="text-link" to={`/identity/audits/${summary.auditId}`}>Open full review</Link>}>
          {unresolved.length === 0 ? <div className="panel__body"><p>No unresolved proposals in this audit.</p></div> : unresolved.slice(0, 5).map((proposal) => <div className="attention-row" key={proposal.proposalId}><span className="status-icon status-icon--amber"><AlertTriangle size={14} /></span><div className="attention-row__copy"><strong>{proposal.entityType.replaceAll('_', ' ')}</strong><span>{proposal.displayValue}</span></div><Badge tone="amber">{Math.round(proposal.confidenceMicros / 10_000)}%</Badge></div>)}
        </Panel>
      </div>
    </div>
  )
}
