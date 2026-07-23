import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clipboard,
  Download,
  ExternalLink,
  FileSearch,
  FileText,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
} from 'lucide-react'
import type {
  AuditControlAction,
  AuditDetail,
  ProposalDecision,
} from '../../../../packages/contracts/src/generated/api'
import {
  controlIdentityAudit,
  decideIdentityProposal,
  executeIdentityAuditBatch,
  getIdentityAudit,
} from '../app/identityDiscoveryBoundary'
import {
  buildIdentityAuditPackage,
  type IdentityAuditPackage,
  type IdentityAuditPackageFormat,
} from '../app/identityAuditPackage'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Badge, Button, Metric, PageHeader, Panel, Progress } from '../components/Primitives'

type AuditView = 'RESULTS' | 'ANALYSIS' | 'LEADS' | 'REVIEW' | 'TASKS' | 'RECEIPTS'
const RUNNING_STATES = new Set(['READY', 'RUNNING'])
const TERMINAL_GOOD = new Set(['COMPLETED', 'PARTIAL'])

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function stateTone(state: string): 'green' | 'amber' | 'rose' | 'cyan' | 'neutral' {
  if (state === 'COMPLETED' || state === 'SUCCEEDED_RESULTS' || state === 'SAVED') return 'green'
  if (state === 'PARTIAL' || state === 'REVIEW_REQUIRED' || state === 'AUTH_REQUIRED') return 'amber'
  if (state === 'FAILED' || state === 'FAILED_TERMINAL' || state === 'BLOCKED') return 'rose'
  if (state === 'READY' || state === 'RUNNING') return 'cyan'
  return 'neutral'
}

function formatTime(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Not yet'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeStyle: 'medium',
  }).format(new Date(value / 1_000))
}

function savePackage(artifact: IdentityAuditPackage) {
  const blob = new Blob([artifact.content], { type: artifact.mediaType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = artifact.filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export function IdentityAuditPage() {
  const { auditId } = useParams<{ auditId: string }>()
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AuditDetail | null>(null)
  const [view, setView] = useState<AuditView>('RESULTS')
  const [cycle, setCycle] = useState(0)
  const [batchPending, setBatchPending] = useState(false)
  const [actionPending, setActionPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [packageFormat, setPackageFormat] =
    useState<IdentityAuditPackageFormat>('MARKDOWN')
  const [packagePending, setPackagePending] = useState(false)
  const [auditPackage, setAuditPackage] = useState<IdentityAuditPackage | null>(null)

  useEffect(() => {
    if (profileId === null || auditId === undefined) return
    let cancelled = false
    async function loadAndRun() {
      setError(null)
      try {
        let current = await getIdentityAudit({ profileId: profileId!, auditId: auditId!, maximumTasks: 4 })
        if (cancelled) return
        setDetail(current)
        while (!cancelled && RUNNING_STATES.has(current.audit.state)) {
          const previousRevision = current.audit.revision
          setBatchPending(true)
          current = await executeIdentityAuditBatch({ profileId: profileId!, auditId: auditId!, maximumTasks: 4 })
          if (cancelled) return
          setDetail(current)
          setBatchPending(false)
          if (!RUNNING_STATES.has(current.audit.state)) break
          await wait(current.audit.revision === previousRevision ? 1_000 : 250)
        }
      } catch {
        if (!cancelled) setError('The durable audit could not be loaded or advanced. Its last committed state remains in the vault.')
      } finally {
        if (!cancelled) setBatchPending(false)
      }
    }
    void loadAndRun()
    return () => { cancelled = true }
  }, [auditId, cycle, profileId])

  const taskStateCounts = useMemo(
    () => detail?.audit.taskStates.filter((item) => item.count > 0) ?? [],
    [detail],
  )

  async function control(action: AuditControlAction) {
    if (detail === null || profileId === null || auditId === undefined) return
    setActionPending(true)
    setError(null)
    try {
      const next = await controlIdentityAudit({
        profileId, auditId, expectedRevision: detail.audit.revision, action,
      })
      setDetail(next)
      setCycle((value) => value + 1)
    } catch {
      setError('The audit changed while this action was being applied. Reload the latest state and retry.')
    } finally {
      setActionPending(false)
    }
  }

  async function decide(proposalId: string, revision: number, decision: ProposalDecision) {
    if (profileId === null || auditId === undefined) return
    setActionPending(true)
    setError(null)
    try {
      const next = await decideIdentityProposal({
        profileId, auditId, proposalId, expectedRevision: revision, decision,
      })
      setDetail(next)
      if (decision === 'SEARCH_DEEPER') setCycle((value) => value + 1)
    } catch {
      setError('That proposal changed before the decision was saved. Reload and review its latest revision.')
    } finally {
      setActionPending(false)
    }
  }

  async function copy(value: string, id: string) {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(id)
      window.setTimeout(() => setCopied((current) => current === id ? null : current), 1_500)
    } catch {
      setError('The system clipboard did not accept the URL. The exact source remains visible below.')
    }
  }

  async function finishAudit() {
    if (detail === null || packagePending) return
    setPackagePending(true)
    setError(null)
    try {
      const artifact = await buildIdentityAuditPackage(detail, packageFormat)
      setAuditPackage(artifact)
      savePackage(artifact)
    } catch {
      setError('The final audit package could not be generated. Reload the committed run and try again.')
    } finally {
      setPackagePending(false)
    }
  }

  if (profileId === null || auditId === undefined) {
    return (
      <div className="page identity-audit-page" data-testid="route-ready">
        <PageHeader eyebrow="Identity audit" title="Select the owning person profile" description="Audit IDs are scoped to a durable profile. Select it from the profile switcher, then reopen this run." />
        <Button variant="primary" onClick={() => navigate('/people')}>Open People</Button>
      </div>
    )
  }

  if (detail === null) {
    return (
      <div className="page identity-audit-page" data-testid="route-ready" aria-busy="true">
        <PageHeader eyebrow="Identity audit · durable execution" title="Opening audit run" description="Loading the persisted frontier and exact task state from the local vault." />
        <Panel><div className="empty-state"><LoaderCircle className="spin" size={30} /><h2>Loading committed progress</h2><p>No simulated percentage is used on this screen.</p></div></Panel>
        {error ? <div className="callout callout--danger" role="alert">{error}</div> : null}
      </div>
    )
  }

  const percentage = detail.audit.progressMicros / 10_000
  const running = RUNNING_STATES.has(detail.audit.state)
  const finalizable = TERMINAL_GOOD.has(detail.audit.state)
  const unresolvedProposals = detail.proposals.filter(
    (proposal) => proposal.reviewState === 'UNREVIEWED',
  ).length

  return (
    <div className="page identity-audit-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Identity discovery · durable recursive audit"
        title={detail.audit.name}
        description="Every search, fetch, result, lead, proposal, source URL, and stop reason below comes from the persisted local run."
        actions={<><Button variant="ghost" onClick={() => navigate('/people')}><ArrowLeft size={14} />People</Button><Button variant="secondary" disabled={running || actionPending} onClick={() => setCycle((value) => value + 1)}><RefreshCw size={14} />Reload</Button></>}
        meta={<><Badge tone={stateTone(detail.audit.state)} dot>{detail.audit.state.toLocaleLowerCase()}</Badge><Badge tone="cyan">{detail.audit.stage.replaceAll('_', ' ').toLocaleLowerCase()}</Badge><Badge tone={detail.audit.useLocalAi ? 'violet' : 'neutral'}>{detail.audit.selectedModel ? `AI · ${detail.audit.selectedModel}` : detail.audit.useLocalAi ? 'AI requested · no selected model' : 'deterministic'}</Badge></>}
      />

      {error ? <div className="callout callout--danger" role="alert"><AlertTriangle size={16} />{error}</div> : null}

      <section className="identity-progress-card" aria-live="polite">
        <div className="identity-progress-card__top"><div><span>{running ? 'Ariadne is working' : 'Durable run state'}</span><strong>{detail.audit.stage.replaceAll('_', ' ')}</strong><small>{detail.audit.terminalTasks} of {detail.audit.totalTasks} frontier tasks terminal{detail.audit.stopReason ? ` · ${detail.audit.stopReason.replaceAll('_', ' ').toLocaleLowerCase()}` : ''}</small></div><strong>{Math.round(percentage)}%</strong></div>
        <Progress value={percentage} label={`${detail.audit.name} durable progress`} tone={TERMINAL_GOOD.has(detail.audit.state) ? 'green' : 'cyan'} />
        <div className="identity-task-state-strip">{taskStateCounts.map((item) => <Badge key={item.state} tone={stateTone(item.state)}>{item.count} {item.state.replaceAll('_', ' ').toLocaleLowerCase()}</Badge>)}</div>
        <div className="identity-progress-card__controls">
          {running ? <Button variant="secondary" disabled={actionPending || batchPending} onClick={() => void control('PAUSE')}><Pause size={14} />Pause after current batch</Button> : null}
          {detail.audit.state === 'PAUSED' ? <Button variant="primary" disabled={actionPending} onClick={() => void control('RESUME')}><Play size={14} />Resume</Button> : null}
          {['READY', 'RUNNING', 'PAUSED'].includes(detail.audit.state) ? <Button variant="danger" disabled={actionPending || batchPending} onClick={() => void control('CANCEL')}><Square size={13} />Cancel run</Button> : null}
          <span>{batchPending ? <><LoaderCircle className="spin" size={14} />Executing the next bounded task batch…</> : `Last committed ${formatTime(detail.audit.updatedAtUs)}`}</span>
        </div>
      </section>

      <div className="grid-4 identity-metrics">
        <Metric label="Exact results" value={String(detail.audit.resultCount)} detail="URLs with provider origin" tone="green" />
        <Metric label="Connected leads" value={String(detail.audit.leadCount)} detail="recursive frontier knowledge" />
        <Metric label="Review proposals" value={String(detail.audit.proposalCount)} detail="never auto-promoted" tone="amber" />
        <Metric label="Tool receipts" value={String(detail.receipts.length)} detail="execution accountability" tone="violet" />
      </div>

      {finalizable ? (
        <Panel
          className="identity-finish panel--signal"
          eyebrow="Final step · cited local artifact"
          title="Finish this audit"
          action={<Badge tone={unresolvedProposals === 0 ? 'green' : 'amber'}>{unresolvedProposals === 0 ? 'Ready to export' : `${unresolvedProposals} reviews remaining`}</Badge>}
        >
          <div className="panel__body identity-finish__body">
            <div className="identity-finish__checks">
              <span><CheckCircle2 size={16} /><strong>Discovery terminal</strong><small>{detail.audit.terminalTasks}/{detail.audit.totalTasks} tasks terminal</small></span>
              <span><CheckCircle2 size={16} /><strong>Exact sources retained</strong><small>{detail.results.length} result URLs with provider origin</small></span>
              <span className={unresolvedProposals === 0 ? '' : 'is-pending'}>{unresolvedProposals === 0 ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}<strong>Human review</strong><small>{unresolvedProposals === 0 ? 'No unresolved proposals' : 'Review proposals before final export'}</small></span>
              <span><ShieldCheck size={16} /><strong>Analysis labelled</strong><small>{detail.aiAnalysis?.status.toLocaleLowerCase() ?? 'No analysis produced'}</small></span>
            </div>
            {unresolvedProposals > 0 ? (
              <Button variant="primary" onClick={() => setView('REVIEW')}>
                Review {unresolvedProposals} proposal{unresolvedProposals === 1 ? '' : 's'}
              </Button>
            ) : (
              <div className="identity-finish__export">
                <label className="field">
                  <span>Final package</span>
                  <select
                    className="select"
                    value={packageFormat}
                    disabled={packagePending}
                    onChange={(event) => {
                      setPackageFormat(event.target.value as IdentityAuditPackageFormat)
                      setAuditPackage(null)
                    }}
                  >
                    <option value="MARKDOWN">Cited Markdown</option>
                    <option value="JSON">Structured JSON</option>
                  </select>
                </label>
                <Button variant="primary" disabled={packagePending} onClick={() => void finishAudit()}>
                  {packagePending ? <LoaderCircle className="spin" size={14} /> : <Download size={14} />}
                  {packagePending ? 'Building package…' : 'Generate and download'}
                </Button>
              </div>
            )}
            {auditPackage ? (
              <div className="identity-finish__artifact" role="status">
                <FileText size={16} />
                <div><strong>{auditPackage.filename}</strong><small>{auditPackage.byteCount.toLocaleString()} bytes · SHA-256 {auditPackage.sha256}</small></div>
                <Button size="compact" variant="secondary" onClick={() => savePackage(auditPackage)}><Download size={13} />Download again</Button>
              </div>
            ) : null}
            <p className="text-muted">The package includes exact result URLs, provider coverage and failures, cited analysis, proposal decisions, and explicit uncertainty. Nothing is uploaded.</p>
          </div>
        </Panel>
      ) : null}

      <div className="identity-audit-tabs" role="tablist" aria-label="Audit evidence views">
        {([
          ['RESULTS', `Sources & results (${detail.results.length})`],
          ['ANALYSIS', `AI analysis (${detail.aiAnalysis?.insights.length ?? 0})`],
          ['LEADS', `Leads (${detail.leads.length})`],
          ['REVIEW', `Review (${detail.proposals.length})`],
          ['TASKS', `Task frontier (${detail.tasks.length})`],
          ['RECEIPTS', `Receipts (${detail.receipts.length})`],
        ] as const).map(([value, label]) => <button type="button" role="tab" aria-selected={view === value} className={view === value ? 'is-active' : ''} key={value} onClick={() => setView(value)}>{label}</button>)}
      </div>

      {view === 'RESULTS' ? (
        <Panel eyebrow="Exact-source review" title={`${detail.results.length} discovered results`} action={<Badge tone="green"><ExternalLink size={12} />URLs retained</Badge>}>
          <div className="identity-result-list">
            {detail.results.length === 0 ? <div className="empty-state"><Search size={26} /><h2>No result URLs yet</h2><p>Inspect Task frontier for exact provider outcomes and stop reasons.</p></div> : detail.results.map((result) => (
              <article className="identity-result-row" key={result.resultId}>
                <span className="identity-result-row__rank">{String(result.rank).padStart(2, '0')}</span>
                <div><div className="inline"><strong>{result.title || result.url}</strong><Badge>{result.category.toLocaleLowerCase()}</Badge></div><code>{result.url}</code><p>{result.snippet || 'No provider excerpt returned.'}</p><small>{result.providerId.replaceAll('_', ' ')} · observed {formatTime(result.observedAtUs)}</small></div>
                <Button size="compact" variant="secondary" onClick={() => void copy(result.url, result.resultId)}><Clipboard size={13} />{copied === result.resultId ? 'Copied' : 'Copy URL'}</Button>
              </article>
            ))}
          </div>
        </Panel>
      ) : null}

      {view === 'ANALYSIS' ? (
        <Panel eyebrow="Cited reasoning" title={detail.aiAnalysis?.title ?? 'No analysis produced'} action={detail.aiAnalysis ? <Badge tone={detail.aiAnalysis.status === 'SUCCEEDED' ? 'violet' : 'amber'}>{detail.aiAnalysis.status.toLocaleLowerCase()}</Badge> : undefined}>
          {detail.aiAnalysis === null ? <div className="empty-state"><Sparkles size={28} /><h2>No AI analysis for this run</h2><p>Enable a selected local model before starting an audit. Deterministic discovery remains fully available without it.</p></div> : <div className="identity-ai-analysis">
            <p className="identity-ai-analysis__summary">{detail.aiAnalysis.summary}</p>
            <div className="identity-card-grid">{detail.aiAnalysis.insights.map((insight, index) => <article className="identity-knowledge-card" key={`${insight.kind}-${index}`}><header><Badge tone="violet">{insight.kind.replaceAll('_', ' ').toLocaleLowerCase()}</Badge>{insight.confidence ? <span>{insight.confidence.toLocaleLowerCase()} confidence</span> : null}</header><strong>{insight.statement}</strong><p>{insight.rationale}</p><div className="chip-wrap">{insight.evidenceRefs.map((reference) => <Badge key={reference}>{reference}</Badge>)}</div></article>)}</div>
            <div className="identity-ai-citations">{detail.aiAnalysis.citations.map((citation) => <article className="identity-result-row" key={citation.referenceId}><Sparkles size={15} /><div><strong>{citation.title || citation.url}</strong><code>{citation.url}</code><small>{citation.referenceId}</small></div><Button size="compact" variant="secondary" onClick={() => void copy(citation.url, citation.referenceId)}><Clipboard size={13} />{copied === citation.referenceId ? 'Copied' : 'Copy URL'}</Button></article>)}</div>
            {detail.aiAnalysis.limitations.length ? <div className="callout callout--warning"><AlertTriangle size={16} /><div><strong>Analysis limits</strong><p>{detail.aiAnalysis.limitations.join(' · ')}</p></div></div> : null}
            <small>{detail.aiAnalysis.provider && detail.aiAnalysis.modelId ? `${detail.aiAnalysis.provider} · ${detail.aiAnalysis.modelId} · ` : 'Deterministic fallback · '}{detail.aiAnalysis.resultCode.replaceAll('_', ' ').toLocaleLowerCase()}</small>
          </div>}
        </Panel>
      ) : null}

      {view === 'LEADS' ? (
        <Panel eyebrow="Recursive correlation" title={`${detail.leads.length} durable leads`}>
          <div className="identity-card-grid">{detail.leads.length === 0 ? <div className="identity-empty-row">No leads have been retained.</div> : detail.leads.map((lead) => <article className="identity-knowledge-card" key={lead.leadId}><header><Badge tone={stateTone(lead.reviewState)}>{lead.leadType.toLocaleLowerCase()}</Badge><span>{Math.round(lead.confidenceMicros / 10_000)}%</span></header><strong>{lead.displayValue}</strong><small>{lead.providerId.replaceAll('_', ' ')} · depth {lead.depth}</small>{lead.sourceUrl ? <code>{lead.sourceUrl}</code> : null}<div className="chip-wrap">{lead.supportingSignals.map((signal) => <Badge tone="green" key={signal}>{signal}</Badge>)}{lead.contradictions.map((signal) => <Badge tone="rose" key={signal}>{signal}</Badge>)}</div></article>)}</div>
        </Panel>
      ) : null}

      {view === 'REVIEW' ? (
        <Panel eyebrow="Human review" title={`${detail.proposals.length} knowledge proposals`}>
          <div className="identity-proposal-list">{detail.proposals.length === 0 ? <div className="empty-state"><CheckCircle2 size={28} /><h2>No pending proposals</h2><p>Deterministic results remain visible without being silently promoted to profile knowledge.</p></div> : detail.proposals.map((proposal) => <article className="identity-proposal" key={proposal.proposalId}><div><header><Badge tone={stateTone(proposal.reviewState)}>{proposal.reviewState.toLocaleLowerCase()}</Badge><Badge>{proposal.entityType.toLocaleLowerCase()}</Badge><span>{Math.round(proposal.confidenceMicros / 10_000)}% confidence</span></header><strong>{proposal.displayValue}</strong><code>{proposal.sourceUrl}</code><small>{proposal.supportingSignals.join(' · ') || 'No supporting-signal label returned'}</small></div><div className="identity-proposal__actions"><Button size="compact" variant="primary" disabled={actionPending || proposal.reviewState !== 'UNREVIEWED'} onClick={() => void decide(proposal.proposalId, proposal.revision, 'CONFIRM')}>Confirm</Button><Button size="compact" variant="secondary" disabled={actionPending || proposal.reviewState !== 'UNREVIEWED'} onClick={() => void decide(proposal.proposalId, proposal.revision, 'SEARCH_DEEPER')}>Search deeper</Button><Button size="compact" variant="ghost" disabled={actionPending || proposal.reviewState !== 'UNREVIEWED'} onClick={() => void decide(proposal.proposalId, proposal.revision, 'UNRELATED')}>Unrelated</Button></div></article>)}</div>
        </Panel>
      ) : null}

      {view === 'TASKS' ? (
        <Panel eyebrow="Durable frontier" title={`${detail.tasks.length} scheduled tasks`}>
          <div className="identity-task-list">{detail.tasks.map((task) => <article className="identity-task-row" key={task.taskId}><div><Badge tone={stateTone(task.state)}>{task.state.replaceAll('_', ' ').toLocaleLowerCase()}</Badge><strong>{task.taskType.replaceAll('_', ' ')}</strong><span>{task.providerId.replaceAll('_', ' ')}</span></div><code>{task.maskedPayload}</code><small>depth {task.depth} · attempt {task.attemptCount}/{task.retryLimit + 1} · {task.resultCount} results{task.stopReason ? ` · ${task.stopReason.replaceAll('_', ' ').toLocaleLowerCase()}` : ''}</small></article>)}</div>
        </Panel>
      ) : null}

      {view === 'RECEIPTS' ? (
        <Panel eyebrow="Execution accountability" title={`${detail.receipts.length} tool receipts`}>
          <div className="identity-receipt-list">{detail.receipts.map((receipt) => <article className="identity-receipt-row" key={receipt.receiptId}><FileSearch size={15} /><div><strong>{receipt.toolName.replaceAll('_', ' ')}</strong><small>{receipt.resultCode.replaceAll('_', ' ').toLocaleLowerCase()} · {receipt.resultCount} results</small></div><Badge tone={stateTone(receipt.executionState)}>{receipt.executionState.toLocaleLowerCase()}</Badge><time>{formatTime(receipt.finishedAtUs)}</time></article>)}</div>
        </Panel>
      ) : null}
    </div>
  )
}

export default IdentityAuditPage
