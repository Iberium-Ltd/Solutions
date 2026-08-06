/** Persisted task and tool-receipt trace for the newest real audit. */
import { Link } from 'react-router-dom'
import { Activity, ArrowRight } from 'lucide-react'
import { Badge, PageHeader, Panel, Progress } from '../components/Primitives'
import { useIdentityOverview } from '../app/useIdentityOverview'

export function NativeOperationsPage() {
  const overview = useIdentityOverview()
  if (overview.status !== 'READY') {
    const detail = overview.status === 'ERROR' ? overview.error : 'Start an audit to populate its task frontier, provider actions, outcomes, and stop reasons.'
    return <div className="page operations-page" data-testid="route-ready"><PageHeader eyebrow="Persisted audit execution" title="Operations" description="This screen contains only real task and receipt records from the active profile." /><div className="empty-state"><span className="empty-state__icon"><Activity size={22} /></span><h2>No operation trace yet</h2><p>{detail}</p><Link className="button button--primary" to="/audits/new">Start an audit</Link></div></div>
  }
  const { audit } = overview
  const progress = Math.round(audit.audit.progressMicros / 10_000)
  return <div className="page operations-page" data-testid="route-ready">
    <PageHeader eyebrow="Persisted audit execution" title={audit.audit.name} description="A visible action trace of planned queries, provider calls, outcomes, and stop reasons. This is not hidden model chain-of-thought." meta={<><Badge tone={audit.audit.state === 'COMPLETED' ? 'green' : 'amber'} dot>{audit.audit.state.toLowerCase()}</Badge><Badge tone="cyan">{audit.audit.stage.toLowerCase().replaceAll('_', ' ')}</Badge></>} actions={<Link className="button button--primary" to={`/identity/audits/${audit.audit.auditId}`}>Open audit <ArrowRight size={14} /></Link>} />
    <Panel className="operations-status panel--signal">
      <div className="operations-status__lead"><div className="operations-status__progress"><div className="space-between"><span>{audit.audit.terminalTasks} of {audit.audit.totalTasks} tasks terminal</span><strong className="mono">{progress}%</strong></div><Progress value={progress} label={`${progress} percent complete`} /></div></div>
      <div className="operations-status__facts"><div><span>Results</span><strong>{audit.results.length}</strong></div><div><span>Leads</span><strong>{audit.leads.length}</strong></div><div><span>Review proposals</span><strong>{audit.proposals.length}</strong></div><div><span>Receipts</span><strong>{audit.receipts.length}</strong></div></div>
    </Panel>
    <Panel className="operations-tasks" eyebrow="Execution frontier" title="Provider tasks">
      <div className="operations-table-wrap"><table className="data-table operations-table"><thead><tr><th>Task</th><th>Provider</th><th>Depth</th><th>State</th><th>Results</th><th>Stop reason</th></tr></thead><tbody>{audit.tasks.map((task) => <tr key={task.taskId}><td>{task.taskType.replaceAll('_', ' ')}<small className="mono">{task.maskedPayload}</small></td><td>{task.providerId.replaceAll('_', ' ')}</td><td>{task.depth}</td><td><Badge tone={task.state === 'SUCCEEDED_RESULTS' ? 'green' : task.state.includes('FAILED') || ['BLOCKED', 'AUTH_REQUIRED'].includes(task.state) ? 'amber' : 'cyan'}>{task.state.toLowerCase().replaceAll('_', ' ')}</Badge></td><td>{task.resultCount}</td><td>{task.stopReason ?? '—'}</td></tr>)}</tbody></table></div>
    </Panel>
    <Panel className="operations-log" eyebrow="Evidence/action trace" title="Tool receipts">
      {audit.receipts.length ? <div className="operations-log__rows" role="log">{audit.receipts.map((receipt) => <div className="operations-log__row" key={receipt.receiptId}><time className="mono">{new Date(receipt.finishedAtUs / 1000).toLocaleTimeString()}</time><Badge tone={receipt.executionState === 'SUCCEEDED' ? 'green' : 'amber'}>{receipt.executionState}</Badge><strong>{receipt.toolName}</strong><span>{receipt.resultCode} · {receipt.resultCount} results{receipt.modelId ? ` · model ${receipt.modelId}` : ''}</span></div>)}</div> : <div className="panel__body"><p>No tool receipts have been recorded.</p></div>}
    </Panel>
  </div>
}
