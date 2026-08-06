/** Audit-derived provider coverage; this is observability, not a fictional global registry. */
import { Link } from 'react-router-dom'
import { ArrowRight, Radar } from 'lucide-react'
import { Badge, PageHeader, Panel } from '../components/Primitives'
import { useIdentityOverview } from '../app/useIdentityOverview'

export function NativeProvidersPage() {
  const overview = useIdentityOverview()
  if (overview.status !== 'READY') {
    const detail = overview.status === 'ERROR' ? overview.error : 'Run an audit first. Provider coverage will then show which engines were attempted and what each returned.'
    return <div className="page controls-page providers-page" data-testid="route-ready"><PageHeader eyebrow="Provider coverage" title="Source coverage" description="A factual view of providers used by the active audit." /><div className="empty-state"><span className="empty-state__icon"><Radar size={22} /></span><h2>No provider observations yet</h2><p>{detail}</p><Link className="button button--primary" to="/audits/new">Start an audit</Link></div></div>
  }
  const { audit } = overview
  const rows = audit.audit.providerIds.map((providerId) => {
    const tasks = audit.tasks.filter((task) => task.providerId === providerId)
    const receipts = audit.receipts.filter((receipt) => receipt.toolName === providerId || tasks.some((task) => task.taskId === receipt.taskId))
    return { providerId, tasks, receipts, results: audit.results.filter((result) => result.providerId === providerId) }
  })
  return <div className="page controls-page providers-page" data-testid="route-ready">
    <PageHeader eyebrow="Audit-derived provider coverage" title="Source coverage" description="Use this screen to understand which search providers the current audit attempted, which were blocked, and how many exact-source results were retained. It does not claim complete internet coverage." meta={<><Badge tone="green" dot>{rows.length} configured</Badge><Badge tone="cyan">{audit.results.length} retained results</Badge></>} />
    <Panel eyebrow="Current audit" title={audit.audit.name} action={<Link className="text-link" to={`/identity/audits/${audit.audit.auditId}`}>Open audit <ArrowRight size={12} /></Link>}>
      <div className="controls-table-scroll"><table className="data-table"><thead><tr><th>Provider</th><th>Tasks</th><th>Results</th><th>Receipts</th><th>Observed state</th></tr></thead><tbody>{rows.map((row) => {
        const blocked = row.tasks.filter((task) => ['BLOCKED', 'AUTH_REQUIRED', 'RATE_LIMITED'].includes(task.state)).length
        const failed = row.tasks.filter((task) => task.state.includes('FAILED')).length
        const state = blocked ? 'blocked / auth' : failed ? 'failed' : row.results.length ? 'returned results' : 'no retained result'
        return <tr key={row.providerId}><th>{row.providerId.replaceAll('_', ' ')}</th><td>{row.tasks.length}</td><td>{row.results.length}</td><td>{row.receipts.length}</td><td><Badge tone={blocked || failed ? 'amber' : row.results.length ? 'green' : 'neutral'}>{state}</Badge></td></tr>
      })}</tbody></table></div>
    </Panel>
  </div>
}
