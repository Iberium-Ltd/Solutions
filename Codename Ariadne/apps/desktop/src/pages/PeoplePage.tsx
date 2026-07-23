/**
 * Acts as the persistent home for a named identity profile.
 *
 * It joins reviewed identifiers, exact sources, history, and one-command audit
 * setup so users do not repeatedly re-enter the same identity clues.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowRight,
  BrainCircuit,
  FileSearch,
  Globe2,
  History,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  UserRound,
} from 'lucide-react'
import type {
  AuditMode,
  PersonWorkspace,
} from '../../../../packages/contracts/src/generated/api'
import {
  createIdentityAudit,
  createIdentitySource,
  getIdentityWorkspace,
  updateIdentityPerson,
} from '../app/identityDiscoveryBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Badge, Button, Metric, PageHeader, Panel, Progress } from '../components/Primitives'

const ACTIVE_AUDIT_STATES = new Set(['READY', 'RUNNING', 'PAUSED'])
const AUTOMATIC_PROVIDER_IDS = [
  'DUCKDUCKGO_HTML',
  'GITHUB_USERS',
  'GITLAB_USERS',
  'NPM_REGISTRY',
  'RDAP_DOMAIN',
  'WAYBACK_CDX',
  'CERTIFICATE_TRANSPARENCY',
]

function formatDate(value: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value / 1_000))
}

function safeMessage(error: unknown): string {
  if (error instanceof Error && /revision/iu.test(error.message)) {
    return 'This profile changed in another view. Reload it and try again.'
  }
  return 'The local operation could not be completed. Confirm the vault is unlocked and retry.'
}

export function PeoplePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [workspace, setWorkspace] = useState<PersonWorkspace | null>(null)
  const [loading, setLoading] = useState(profileId !== null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [personForm, setPersonForm] = useState({
    displayName: '', purpose: '', notes: '', tags: '',
  })
  const [sourceForm, setSourceForm] = useState({ url: '', title: '', notes: '' })
  const [auditForm, setAuditForm] = useState({
    name: `Full identity audit ${new Date().toLocaleDateString()}`,
    mode: 'MAXIMUM_COVERAGE' as AuditMode,
    maxDepth: 3,
    requestBudget: 160,
    useLocalAi: true,
    includeHibp: false,
  })

  useEffect(() => {
    if (profileId === null) {
      setWorkspace(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void getIdentityWorkspace({ profileId })
      .then((next) => {
        if (cancelled) return
        setWorkspace(next)
        setPersonForm({
          displayName: next.person.displayName,
          purpose: next.person.purpose,
          notes: next.person.notes,
          tags: next.person.tags.join(', '),
        })
      })
      .catch((cause) => {
        if (!cancelled) setError(safeMessage(cause))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [profileId])

  const activeAudit = useMemo(
    () => workspace?.audits.find((audit) => ACTIVE_AUDIT_STATES.has(audit.state)),
    [workspace],
  )

  useEffect(() => {
    if (workspace !== null && searchParams.get('start') === '1') {
      window.requestAnimationFrame(() => {
        document.querySelector('#run-full-audit')?.scrollIntoView({ behavior: 'smooth' })
      })
    }
  }, [searchParams, workspace])

  async function reload() {
    if (profileId === null) return
    setPending('reload')
    setError(null)
    try {
      setWorkspace(await getIdentityWorkspace({ profileId }))
    } catch (cause) {
      setError(safeMessage(cause))
    } finally {
      setPending(null)
    }
  }

  async function savePerson() {
    if (workspace === null) return
    const tags = personForm.tags.split(',').map((tag) => tag.trim()).filter(Boolean)
    setPending('person')
    setError(null)
    try {
      const next = await updateIdentityPerson({
        profileId: workspace.person.profileId,
        expectedProfileRevision: workspace.person.profileRevision,
        expectedDetailsRevision: workspace.person.detailsRevision,
        displayName: personForm.displayName.trim(),
        purpose: personForm.purpose.trim(),
        notes: personForm.notes.trim(),
        tags: [...new Set(tags)],
      })
      setWorkspace(next)
      setEditMode(false)
    } catch (cause) {
      setError(safeMessage(cause))
    } finally {
      setPending(null)
    }
  }

  async function addSource() {
    if (workspace === null || !sourceForm.url.trim()) return
    setPending('source')
    setError(null)
    try {
      const next = await createIdentitySource({
        profileId: workspace.person.profileId,
        url: sourceForm.url.trim(),
        sourceType: 'MANUAL_URL',
        title: sourceForm.title.trim() || null,
        notes: sourceForm.notes.trim(),
        authorizedSelfAudit: true,
      })
      setWorkspace(next)
      setSourceForm({ url: '', title: '', notes: '' })
    } catch (cause) {
      setError(safeMessage(cause))
    } finally {
      setPending(null)
    }
  }

  async function startAudit() {
    if (workspace === null) return
    setPending('audit')
    setError(null)
    try {
      const providerIds = [...AUTOMATIC_PROVIDER_IDS]
      if (auditForm.includeHibp) providerIds.push('HAVE_I_BEEN_PWNED_V3')
      const detail = await createIdentityAudit({
        profileId: workspace.person.profileId,
        name: auditForm.name.trim(),
        mode: auditForm.mode,
        providerIds,
        maxDepth: auditForm.maxDepth,
        requestBudget: auditForm.requestBudget,
        timeBudgetSeconds: 1_800,
        costBudgetMicros: 0,
        useLocalAi: auditForm.useLocalAi,
        authorizedSelfAudit: true,
      })
      navigate(`/identity/audits/${detail.audit.auditId}`)
    } catch (cause) {
      setError(safeMessage(cause))
    } finally {
      setPending(null)
    }
  }

  if (profileId === null) {
    return (
      <div className="page identity-page" data-testid="route-ready">
        <PageHeader eyebrow="People · persistent workspace" title="Select or create a profile" description="A profile is the durable root for identifiers, sources, runs, findings, and review history." />
        <Panel className="panel--signal">
          <div className="empty-state">
            <div className="empty-state__icon"><UserRound size={24} /></div>
            <h2>No active person profile</h2>
            <p>Create a named profile, then import and review the identifiers Ariadne should audit.</p>
            <Button variant="primary" onClick={() => navigate('/audits/new')}>Create or select profile <ArrowRight size={14} /></Button>
          </div>
        </Panel>
      </div>
    )
  }

  if (loading || workspace === null) {
    return (
      <div className="page identity-page" data-testid="route-ready" aria-busy="true">
        <PageHeader eyebrow="People · persistent workspace" title="Opening person profile" description="Loading durable identifiers, sources, and previous audit runs from the local vault." />
        <Panel><div className="empty-state"><LoaderCircle className="spin" size={28} /><h2>Loading local profile</h2></div></Panel>
        {error ? <div className="callout callout--danger" role="alert">{error}</div> : null}
      </div>
    )
  }

  return (
    <div className="page identity-page" data-testid="route-ready">
      <PageHeader
        eyebrow="People · persistent identity workspace"
        title={workspace.person.displayName}
        description={workspace.person.purpose}
        actions={<><Button variant="secondary" onClick={() => void reload()} disabled={pending !== null}><RefreshCw size={14} />Refresh</Button><Button variant="primary" onClick={() => document.querySelector('#run-full-audit')?.scrollIntoView({ behavior: 'smooth' })}><FileSearch size={14} />Run full audit</Button></>}
        meta={<><Badge tone="green" dot>{workspace.person.status.toLocaleLowerCase()}</Badge><Badge tone="cyan">{workspace.person.identityCount} reviewed identifiers</Badge><Badge tone="violet">{workspace.person.auditCount} retained runs</Badge></>}
      />

      {error ? <div className="callout callout--danger" role="alert">{error}</div> : null}
      {activeAudit ? (
        <button className="identity-active-run" type="button" onClick={() => navigate(`/identity/audits/${activeAudit.auditId}`)}>
          <span><History size={16} /><strong>Continue {activeAudit.name}</strong><small>{activeAudit.stage.replaceAll('_', ' ').toLocaleLowerCase()} · {Math.round(activeAudit.progressMicros / 10_000)}%</small></span>
          <Progress value={activeAudit.progressMicros / 10_000} label={`${activeAudit.name} progress`} />
          <ArrowRight size={16} />
        </button>
      ) : null}

      <div className="grid-4 identity-metrics">
        <Metric label="Identifiers" value={String(workspace.person.identityCount)} detail="confirmed or probable" />
        <Metric label="Exact sources" value={String(workspace.person.sourceCount)} detail="retained source URLs" tone="green" />
        <Metric label="Audit history" value={String(workspace.person.auditCount)} detail="durable runs" tone="violet" />
        <Metric label="Needs review" value={String(workspace.person.unresolvedProposalCount)} detail="knowledge proposals" tone="amber" />
      </div>

      <div className="page-grid">
        <Panel className="span-7" eyebrow="Person knowledge" title="Profile details" action={<Button size="compact" variant="ghost" onClick={() => setEditMode((value) => !value)}>{editMode ? 'Cancel' : 'Edit'}</Button>}>
          {editMode ? (
            <div className="panel__body stack identity-form">
              <label className="field"><span>Profile name</span><input className="input" maxLength={80} value={personForm.displayName} onChange={(event) => setPersonForm((current) => ({ ...current, displayName: event.target.value }))} /></label>
              <label className="field"><span>Audit purpose</span><input className="input" maxLength={240} value={personForm.purpose} onChange={(event) => setPersonForm((current) => ({ ...current, purpose: event.target.value }))} /></label>
              <label className="field"><span>Notes</span><textarea className="textarea" maxLength={20_000} value={personForm.notes} onChange={(event) => setPersonForm((current) => ({ ...current, notes: event.target.value }))} /></label>
              <label className="field"><span>Tags · comma separated</span><input className="input" value={personForm.tags} onChange={(event) => setPersonForm((current) => ({ ...current, tags: event.target.value }))} /></label>
              <div><Button variant="primary" disabled={pending !== null || !personForm.displayName.trim() || !personForm.purpose.trim()} onClick={() => void savePerson()}><Save size={14} />{pending === 'person' ? 'Saving…' : 'Save person'}</Button></div>
            </div>
          ) : (
            <div className="panel__body stack">
              <dl className="definition-list"><div><dt>Purpose</dt><dd>{workspace.person.purpose}</dd></div><div><dt>Notes</dt><dd>{workspace.person.notes || 'No notes yet'}</dd></div><div><dt>Tags</dt><dd>{workspace.person.tags.join(', ') || 'No tags yet'}</dd></div><div><dt>Profile revision</dt><dd>{workspace.person.profileRevision}</dd></div></dl>
              <Button variant="secondary" onClick={() => navigate('/audits/new/intake')}><Plus size={14} />Import or review identifiers</Button>
            </div>
          )}
        </Panel>

        <Panel className="span-5" eyebrow="Known origins" title="Add an exact source URL">
          <div className="panel__body stack identity-form">
            <label className="field"><span>Public HTTPS URL</span><input className="input" type="url" placeholder="https://example.org/profile" value={sourceForm.url} onChange={(event) => setSourceForm((current) => ({ ...current, url: event.target.value }))} /></label>
            <label className="field"><span>Title · optional</span><input className="input" maxLength={240} value={sourceForm.title} onChange={(event) => setSourceForm((current) => ({ ...current, title: event.target.value }))} /></label>
            <label className="field"><span>Why this source matters · optional</span><textarea className="textarea identity-source-notes" maxLength={4_000} value={sourceForm.notes} onChange={(event) => setSourceForm((current) => ({ ...current, notes: event.target.value }))} /></label>
            <Button variant="secondary" disabled={pending !== null || !sourceForm.url.trim()} onClick={() => void addSource()}><Plus size={14} />{pending === 'source' ? 'Saving…' : 'Retain source'}</Button>
          </div>
        </Panel>

        <Panel className="span-12" eyebrow="Exact-source memory" title={`${workspace.sources.length} retained sources`}>
          <div className="identity-source-list">
            {workspace.sources.length === 0 ? <div className="identity-empty-row">No exact source URLs retained yet. Crawled and manually supplied URLs will appear here.</div> : workspace.sources.map((source) => (
              <article className="identity-source-row" key={source.sourceId}>
                <Globe2 size={15} /><div><strong>{source.title || source.url}</strong><code>{source.url}</code></div><Badge tone={source.relationshipState === 'RELATED' ? 'green' : 'neutral'}>{source.sourceType.replaceAll('_', ' ').toLocaleLowerCase()}</Badge>
              </article>
            ))}
          </div>
        </Panel>

        <Panel id="run-full-audit" className="span-7 panel--signal" eyebrow="One-command workflow" title="Run the complete identity audit">
          <div className="panel__body stack identity-form">
            <label className="field"><span>Run name</span><input className="input" maxLength={120} value={auditForm.name} onChange={(event) => setAuditForm((current) => ({ ...current, name: event.target.value }))} /></label>
            <div className="grid-3">
              <label className="field"><span>Mode</span><select className="select" value={auditForm.mode} onChange={(event) => setAuditForm((current) => ({ ...current, mode: event.target.value as AuditMode }))}><option value="MAXIMUM_COVERAGE">Maximum coverage</option><option value="FULL_RESCAN">Full rescan</option><option value="INCREMENTAL">Incremental</option><option value="FAILED_AND_BLOCKED_RETRY">Retry blocked</option></select></label>
              <label className="field"><span>Recursive depth</span><input className="input" type="number" min={1} max={8} value={auditForm.maxDepth} onChange={(event) => setAuditForm((current) => ({ ...current, maxDepth: Number(event.target.value) }))} /></label>
              <label className="field"><span>Request budget</span><input className="input" type="number" min={1} max={2_000} value={auditForm.requestBudget} onChange={(event) => setAuditForm((current) => ({ ...current, requestBudget: Number(event.target.value) }))} /></label>
            </div>
            <label className="identity-check"><input type="checkbox" checked={auditForm.useLocalAi} onChange={(event) => setAuditForm((current) => ({ ...current, useLocalAi: event.target.checked }))} /><BrainCircuit size={15} /><span><strong>Use the selected local model when available</strong><small>The model choice is snapshotted with this run; deterministic discovery remains available.</small></span></label>
            <label className="identity-check"><input type="checkbox" checked={auditForm.includeHibp} onChange={(event) => setAuditForm((current) => ({ ...current, includeHibp: event.target.checked }))} /><FileSearch size={15} /><span><strong>Include Have I Been Pwned checks</strong><small>Tasks will report “authentication required” until an API key is configured.</small></span></label>
            <div className="callout"><div><strong>Seven automatic public surfaces</strong><p>DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback Machine, and certificate-transparency records run from every compatible reviewed identifier. Progress is persisted after every task and survives navigation or restart.</p></div></div>
            <Button variant="primary" disabled={pending !== null || !auditForm.name.trim()} onClick={() => void startAudit()}>{pending === 'audit' ? <LoaderCircle className="spin" size={14} /> : <FileSearch size={14} />}{pending === 'audit' ? 'Creating durable run…' : 'Start full audit'} <ArrowRight size={14} /></Button>
          </div>
        </Panel>

        <Panel className="span-5" eyebrow="Run history" title={`${workspace.audits.length} retained audits`}>
          <div className="identity-run-list">
            {workspace.audits.length === 0 ? <div className="identity-empty-row">No audits yet. Start the first full run.</div> : workspace.audits.map((audit) => (
              <button type="button" className="identity-run-row" key={audit.auditId} onClick={() => navigate(`/identity/audits/${audit.auditId}`)}>
                <span><strong>{audit.name}</strong><small>{formatDate(audit.createdAtUs)} · {audit.resultCount} results · {audit.leadCount} leads</small></span><Badge tone={audit.state === 'COMPLETED' ? 'green' : audit.state === 'PARTIAL' ? 'amber' : 'cyan'}>{audit.state.toLocaleLowerCase()}</Badge><ArrowRight size={14} />
              </button>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  )
}

export default PeoplePage
