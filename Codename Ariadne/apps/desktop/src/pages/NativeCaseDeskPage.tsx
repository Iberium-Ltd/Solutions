/** Case Desk projection backed by review proposals and cited AI insights from the newest audit. */
import { Link } from 'react-router-dom'
import { BriefcaseBusiness } from 'lucide-react'
import { Badge, PageHeader, Panel } from '../components/Primitives'
import { useIdentityOverview } from '../app/useIdentityOverview'

export function NativeCaseDeskPage() {
  const overview = useIdentityOverview()
  if (overview.status !== 'READY') {
    const detail = overview.status === 'ERROR' ? overview.error : 'Complete or resume an audit to create reviewable cases.'
    return <div className="page controls-page impersonation-page" data-testid="route-ready"><PageHeader eyebrow="Audit review workspace" title="Case Desk" description="Cases appear only when the active audit produces review proposals or cited connections." /><div className="empty-state"><span className="empty-state__icon"><BriefcaseBusiness size={22} /></span><h2>No audit cases yet</h2><p>{detail}</p><Link className="button button--primary" to="/audits/new">Start an audit</Link></div></div>
  }
  const { audit } = overview
  const connections = audit.aiAnalysis?.insights.filter((insight) => insight.kind === 'CONNECTION') ?? []
  return <div className="page controls-page impersonation-page" data-testid="route-ready">
    <PageHeader eyebrow="Audit review workspace" title="Case Desk" description="Review possible identity links without turning similarity into fact. Every AI suggestion remains a hypothesis and retains its exact citations." meta={<><Badge tone="violet">{audit.proposals.length} proposals</Badge><Badge tone="cyan">{connections.length} cited connections</Badge></>} actions={<Link className="button button--primary" to={`/identity/audits/${audit.audit.auditId}`}>Review audit</Link>} />
    <div className="page-grid">
      <Panel className="span-6" eyebrow="Human review" title="Knowledge proposals">{audit.proposals.length ? audit.proposals.slice(0, 12).map((proposal) => <div className="attention-row" key={proposal.proposalId}><div className="attention-row__copy"><strong>{proposal.entityType.replaceAll('_', ' ')}</strong><span>{proposal.displayValue}</span></div><Badge tone={proposal.reviewState === 'ACCEPTED' ? 'green' : 'amber'}>{proposal.reviewState.toLowerCase()}</Badge></div>) : <div className="panel__body"><p>No proposals were generated.</p></div>}</Panel>
      <Panel className="span-6" eyebrow="Cited model analysis" title="Connection hypotheses">{connections.length ? connections.slice(0, 12).map((insight, index) => <div className="attention-row" key={`${insight.statement}-${index}`}><div className="attention-row__copy"><strong>{insight.statement}</strong><span>{insight.rationale}</span></div><Badge tone="violet">{insight.evidenceRefs.length} sources</Badge></div>) : <div className="panel__body"><p>No cited connection hypotheses are available for this run.</p></div>}</Panel>
    </div>
  </div>
}
