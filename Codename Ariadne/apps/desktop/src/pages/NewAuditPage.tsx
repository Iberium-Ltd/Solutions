/** Entry surface for selecting or naming a persistent profile before a new run. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  Check,
  Crosshair,
  FileClock,
  Files,
  LockKeyhole,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  UserRoundPlus,
} from 'lucide-react'
import type { ProfileSummary } from '../../../../packages/contracts/src/generated/api'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { createProfile, listProfiles } from '../app/phase3Boundary'
import {
  loadPhase6AuditRuns,
  type Phase6AuditRunSummary,
} from '../app/phase6Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import { Toggle } from '../components/Toggle'

const modes = [
  {
    id: 'full',
    icon: Files,
    title: 'Complete exposure audit',
    description: 'Review a synthetic identity set, compile a bounded plan, and compare broad source coverage.',
    estimate: '186 checks · 28 min',
    tone: 'cyan',
  },
  {
    id: 'targeted',
    icon: Crosshair,
    title: 'Targeted trace',
    description: 'Investigate one email, username, phone, name, domain, URL, address, or image.',
    estimate: '12–34 checks · 6 min',
    tone: 'violet',
  },
  {
    id: 'reaudit',
    icon: FileClock,
    title: 'Re-audit a prior run',
    description: 'Repeat selected checks and isolate new, changed, removed, or reappeared evidence.',
    estimate: '142 checks · 19 min',
    tone: 'green',
  },
] as const

type NativeProfileMode = 'CREATE' | 'CONTINUE'

function formatRunTime(timestampUs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(Math.floor(timestampUs / 1_000)))
}

function NativeRunHistory({ profileId }: { readonly profileId: string | null }) {
  const [runs, setRuns] = useState<ReadonlyArray<Phase6AuditRunSummary> | null>(
    null,
  )
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (profileId === null) {
      setRuns(null)
      setFailed(false)
      return
    }
    let cancelled = false
    setRuns(null)
    setFailed(false)
    void loadPhase6AuditRuns({ profileId, limit: 8 })
      .then((result) => {
        if (!cancelled) setRuns(result.runs)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [profileId])

  if (profileId === null) {
    return (
      <div className="empty-inline">
        <FileClock size={18} aria-hidden="true" />
        <span>A new profile has no retained audit runs yet.</span>
      </div>
    )
  }
  if (failed) {
    return (
      <div className="callout callout--danger" role="alert">
        Existing run history could not be loaded. The selected profile was not
        changed.
      </div>
    )
  }
  if (runs === null) {
    return <p className="text-muted">Loading encrypted run history…</p>
  }
  if (runs.length === 0) {
    return (
      <div className="empty-inline">
        <FileClock size={18} aria-hidden="true" />
        <span>No saved checkpoints for this profile yet.</span>
      </div>
    )
  }
  return (
    <ol className="audit-profile-runs" aria-label="Recent saved audit runs">
      {runs.slice(0, 5).map((run) => (
        <li key={run.runId}>
          <div>
            <strong>Run {run.sequence}</strong>
            <small>{formatRunTime(run.capturedAtUs)}</small>
          </div>
          <span>
            {run.findingCount} findings · {run.providerCount} providers ·{' '}
            {run.runState.toLocaleLowerCase()}
          </span>
        </li>
      ))}
    </ol>
  )
}

function NativeNewAuditPage() {
  const navigate = useNavigate()
  const activeProfileId = usePhase3WorkflowStore((state) => state.profileId)
  const setProfileId = usePhase3WorkflowStore((state) => state.setProfileId)
  const clearSource = usePhase3WorkflowStore((state) => state.clearSource)
  const [profiles, setProfiles] = useState<ReadonlyArray<ProfileSummary>>([])
  const [profilesLoading, setProfilesLoading] = useState(true)
  const [mode, setMode] = useState<NativeProfileMode>(
    activeProfileId === null ? 'CREATE' : 'CONTINUE',
  )
  const [selectedProfileId, setSelectedProfileId] = useState(
    activeProfileId ?? '',
  )
  const [profileName, setProfileName] = useState('')
  const [purpose, setPurpose] = useState('Authorised self-audit')
  const [pending, setPending] = useState(false)
  const [safeError, setSafeError] = useState<string | null>(null)
  const createIdempotencyKey = useRef(crypto.randomUUID())

  useEffect(() => {
    let cancelled = false
    setProfilesLoading(true)
    void listProfiles()
      .then((result) => {
        if (cancelled) return
        const resumable = result.profiles.filter((profile) =>
          ['ACTIVE', 'DRAFT'].includes(profile.status),
        )
        setProfiles(result.profiles)
        setSelectedProfileId((current) => {
          if (resumable.some((profile) => profile.profileId === current)) {
            return current
          }
          return resumable[0]?.profileId ?? ''
        })
        if (activeProfileId !== null || resumable.length > 0) {
          setMode((current) =>
            activeProfileId !== null ? 'CONTINUE' : current,
          )
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSafeError('Local profiles could not be loaded. Confirm the vault is unlocked.')
        }
      })
      .finally(() => {
        if (!cancelled) setProfilesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeProfileId])

  const resumableProfiles = useMemo(
    () =>
      profiles.filter((profile) => ['ACTIVE', 'DRAFT'].includes(profile.status)),
    [profiles],
  )
  const selectedProfile = resumableProfiles.find(
    (profile) => profile.profileId === selectedProfileId,
  )
  const normalizedName = profileName.trim().toLocaleLowerCase()
  const duplicate =
    normalizedName.length > 0 &&
    profiles.find(
      (profile) => profile.displayLabel.trim().toLocaleLowerCase() === normalizedName,
    )
  const createValid =
    profileName.trim().length >= 1 &&
    profileName.trim().length <= 80 &&
    purpose.trim().length >= 1 &&
    purpose.trim().length <= 240
  const canContinue =
    !pending &&
    !profilesLoading &&
    (mode === 'CREATE' ? createValid : selectedProfile !== undefined)
  const historyProfileId = mode === 'CONTINUE' ? selectedProfileId || null : null

  async function continueToIntake() {
    if (!canContinue) return
    setPending(true)
    setSafeError(null)
    try {
      if (mode === 'CREATE') {
        const profile = await createProfile({
          idempotencyKey: createIdempotencyKey.current,
          displayLabel: profileName.trim(),
          purpose: purpose.trim(),
        })
        setProfileId(profile.profileId)
        createIdempotencyKey.current = crypto.randomUUID()
      } else if (selectedProfile !== undefined) {
        setProfileId(selectedProfile.profileId)
        clearSource()
      } else {
        throw new Error('No profile selected')
      }
      navigate('/audits/new/intake')
    } catch {
      setSafeError(
        mode === 'CREATE'
          ? 'The named profile could not be created. Confirm the vault is unlocked and try again.'
          : 'The selected profile could not be resumed.',
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="page new-audit-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · profile and run scope"
        title="Start a profile-scoped audit"
        description="Create a named long-lived profile or continue one with its retained identifiers, findings, sources, and checkpoint history."
        meta={
          <>
            <Badge tone="green" dot>Encrypted local profile</Badge>
            <Badge tone="cyan">History retained by default</Badge>
          </>
        }
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Profile', 'Intake', 'Entities', 'Discovery', 'AI review', 'Checkpoint', 'Report'].map((step, index) => (
          <li className={index === 0 ? 'is-active' : ''} key={step}>
            <span>{index === 0 ? <Check size={11} /> : index + 1}</span>
            <strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="page-grid audit-builder-grid">
        <Panel className="span-8 panel--signal" eyebrow="Profile assignment" title="Where should this audit be retained?">
          <div className="panel__body stack">
            <div className="audit-profile-mode" role="radiogroup" aria-label="Profile assignment mode">
              <button type="button" className={mode === 'CREATE' ? 'is-selected' : ''} role="radio" aria-checked={mode === 'CREATE'} onClick={() => { setMode('CREATE'); setSafeError(null) }}>
                <UserRoundPlus size={17} aria-hidden="true" />
                <span><strong>Create a named profile</strong><small>Start a separate durable subject history.</small></span>
              </button>
              <button type="button" className={mode === 'CONTINUE' ? 'is-selected' : ''} role="radio" aria-checked={mode === 'CONTINUE'} disabled={resumableProfiles.length === 0} onClick={() => { setMode('CONTINUE'); setSafeError(null) }}>
                <FileClock size={17} aria-hidden="true" />
                <span><strong>Continue an existing profile</strong><small>Reuse reviewed identifiers and retained results.</small></span>
              </button>
            </div>

            {mode === 'CREATE' ? (
              <div className="audit-scope-form">
                <label className="field" htmlFor="native-profile-name">
                  <span>Profile name</span>
                  <input id="native-profile-name" className="input" value={profileName} maxLength={80} autoComplete="off" placeholder="e.g. Personal self-audit" disabled={pending} onChange={(event) => { setProfileName(event.target.value); setSafeError(null) }} />
                  <small>A local label. It is never used as the immutable profile ID.</small>
                </label>
                <label className="field" htmlFor="native-profile-purpose">
                  <span>Purpose</span>
                  <input id="native-profile-purpose" className="input" value={purpose} maxLength={240} autoComplete="off" disabled={pending} onChange={(event) => { setPurpose(event.target.value); setSafeError(null) }} />
                  <small>Stored only in the encrypted local vault.</small>
                </label>
              </div>
            ) : (
              <label className="field" htmlFor="native-existing-profile">
                <span>Existing profile</span>
                <select id="native-existing-profile" className="select" value={selectedProfileId} disabled={pending || profilesLoading || resumableProfiles.length === 0} onChange={(event) => { setSelectedProfileId(event.target.value); setSafeError(null) }}>
                  {resumableProfiles.map((profile) => (
                    <option value={profile.profileId} key={profile.profileId}>{profile.displayLabel}</option>
                  ))}
                </select>
                <small>{selectedProfile?.purpose ?? 'Select the profile that should receive this audit.'}</small>
              </label>
            )}

            {duplicate ? (
              <div className="callout callout--warning" role="status">
                A profile named “{duplicate.displayLabel}” already exists. Continue it instead unless deliberate separation is required.
              </div>
            ) : null}
            {safeError ? <div className="callout callout--danger" role="alert">{safeError}</div> : null}
          </div>
        </Panel>

        <div className="span-4 stack">
          <Panel eyebrow="Profile vs run" title="One profile, many audits">
            <div className="panel__body stack">
              <p className="text-muted">The profile retains reviewed identifiers and evidence. Saved checkpoints are the immutable run snapshots shown in Compare Runs.</p>
              <div className="privacy-guarantee">
                <LockKeyhole size={16} aria-hidden="true" />
                <div><strong>No hidden generic profile</strong><span>Intake cannot begin until you explicitly create or select one.</span></div>
              </div>
            </div>
          </Panel>
          <Panel eyebrow="Retained history" title={mode === 'CONTINUE' ? selectedProfile?.displayLabel ?? 'Selected profile' : 'New profile'}>
            <div className="panel__body">
              <NativeRunHistory profileId={historyProfileId} />
            </div>
          </Panel>
        </div>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <ShieldCheck size={16} aria-hidden="true" />
            <div><strong>{mode === 'CREATE' ? 'A new durable profile will be created.' : 'New intake will join the selected profile history.'}</strong><span>No search or external request starts from this step.</span></div>
          </div>
          <Button variant="primary" disabled={!canContinue} onClick={() => void continueToIntake()}>
            {pending ? 'Preparing…' : mode === 'CREATE' ? 'Create profile and continue' : 'Continue to intake'} <ArrowRight size={14} />
          </Button>
        </div>
      </div>
    </div>
  )
}

export function NewAuditPage() {
  return nativeRuntimeAvailable() ? <NativeNewAuditPage /> : <SimulatedNewAuditPage />
}

function SimulatedNewAuditPage() {
  const [selectedMode, setSelectedMode] = useState<(typeof modes)[number]['id']>('full')
  const [localOnly, setLocalOnly] = useState(true)
  const [saveDraft, setSaveDraft] = useState(true)

  return (
    <div className="page new-audit-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · step 1 of 7"
        title="Create a reviewed audit"
        description="Choose the investigation shape first. Intake, entity approval, transmission, plan, and budget remain separate gates."
        meta={<Badge tone="green" dot>Local-only default</Badge>}
        actions={<Button variant="ghost">Save draft</Button>}
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Audit type', 'Intake', 'Entities', 'Transmission', 'Plan', 'Budget', 'Review'].map((step, index) => (
          <li className={index === 0 ? 'is-active' : ''} key={step}>
            <span>{index === 0 ? <Check size={11} /> : index + 1}</span>
            <strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="compact-workflow-action compact-workflow-action--audit" role="region" aria-label="Audit step action">
        <div>
          <strong>Audit shape ready</strong>
          <span>Local-only · nothing runs yet</span>
        </div>
        <Link className="button button--primary" to="/audits/new/intake">
          Continue to intake <ArrowRight size={14} />
        </Link>
      </div>

      <div className="page-grid audit-builder-grid">
        <Panel className="span-8 panel--signal" eyebrow="Investigation shape" title="What do you want to run?">
          <div className="audit-mode-grid">
            {modes.map((mode) => {
              const Icon = mode.icon
              const selected = selectedMode === mode.id
              return (
                <button
                  type="button"
                  className={`audit-mode-card is-${mode.tone} ${selected ? 'is-selected' : ''}`}
                  onClick={() => setSelectedMode(mode.id)}
                  aria-pressed={selected}
                  key={mode.id}
                >
                  <span className="audit-mode-card__icon"><Icon size={19} /></span>
                  <span className="audit-mode-card__check">{selected && <Check size={12} />}</span>
                  <strong>{mode.title}</strong>
                  <p>{mode.description}</p>
                  <small>{mode.estimate}</small>
                </button>
              )
            })}
          </div>

          <div className="audit-scope-form">
            <div className="field">
              <label htmlFor="audit-name">Audit name</label>
              <input id="audit-name" className="input" defaultValue="Greyhaven exposure baseline" />
              <small>A local label; it is never sent to a provider.</small>
            </div>
            <div className="field">
              <label htmlFor="profile">Synthetic profile</label>
              <select id="profile" className="select" defaultValue="morgan">
                <option value="morgan">Morgan Vale · synthetic</option>
                <option value="isolated">Keep trace isolated</option>
              </select>
              <small>Profile assignment prevents cross-subject contamination.</small>
            </div>
          </div>
        </Panel>

        <div className="span-4 stack">
          <Panel eyebrow="Privacy posture" title="Start with a closed boundary">
            <div className="panel__body audit-privacy-list">
              <Toggle
                checked={localOnly}
                onCheckedChange={setLocalOnly}
                label="Local-only mode"
                description="No identifier can leave this Mac until a later explicit preflight."
              />
              <Toggle
                checked={saveDraft}
                onCheckedChange={setSaveDraft}
                label="Keep encrypted draft"
                description="Preserve reviewed progress in the synthetic local workspace."
              />
              <div className="privacy-guarantee">
                <LockKeyhole size={16} />
                <div><strong>Zero external requests</strong><span>Phase 1 uses deterministic in-memory fixtures only.</span></div>
              </div>
            </div>
          </Panel>

          <Panel eyebrow="Estimated envelope" title="Before entity review">
            <div className="panel__body audit-estimate">
              <div><span>Initial queries</span><strong className="mono">186 max</strong></div>
              <div><span>External providers</span><strong className="mono">0 approved</strong></div>
              <div><span>Estimated cost</span><strong className="mono">€0.00</strong></div>
              <div><span>Sensitive values</span><strong className="mono">Ask first</strong></div>
            </div>
          </Panel>
        </div>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <ShieldCheck size={16} />
            <div>
              <strong>Nothing runs from this step.</strong>
              <span>Every extracted entity must be approved, excluded, or marked store-only before a search plan exists.</span>
            </div>
          </div>
          <Link className="button button--primary" to="/audits/new/intake">
            Continue to intake <ArrowRight size={14} />
          </Link>
        </div>
      </div>

      <div className="audit-principles">
        <span><Sparkles size={13} /> Deterministic extraction first</span>
        <span><SearchCheck size={13} /> Query budget required</span>
        <span><ShieldCheck size={13} /> Human approval before transmission</span>
      </div>
    </div>
  )
}
