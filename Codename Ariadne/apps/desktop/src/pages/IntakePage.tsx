/** Local intake UI for bounded paste/file preparation before entity review. */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Braces,
  Check,
  FileCheck2,
  FileText,
  Files,
  LockKeyhole,
  ScanSearch,
  ShieldAlert,
  UploadCloud,
} from 'lucide-react'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { submitFileIntake, submitPastedIntake } from '../app/phase3Boundary'
import { prepareSelectedIntakeFile } from '../app/selectedIntakeFile'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { getLocalAISettings } from '../app/localAiBoundary'
import type {
  IntakeReceipt,
  LocalAISettings,
} from '../../../../packages/contracts/src/generated/api'

const syntheticText = `Morgan Vale uses the historical handle @night_orbit.
Contact: morgan.vale@example.invalid
Previously associated with Northbridge Systems in Greyhaven.
This fictional profile exists only for local interface testing.`

const pipeline = [
  ['MIME + encoding', 'complete'],
  ['Restricted scan', 'complete'],
  ['Deterministic extract', 'active'],
  ['Local enrichment', 'queued'],
  ['Human review', 'queued'],
] as const

export function IntakePage() {
  return nativeRuntimeAvailable() ? <NativeIntakePage /> : <SimulatedIntakePage />
}

type NativeIntakeStatus = 'IDLE' | 'PROCESSING' | 'READY' | 'ERROR'

interface FileIntakeRetryBinding {
  readonly fingerprint: string
  readonly idempotencyKey: string
}

function fileIntakeFingerprint(
  profileId: string,
  file: {
    readonly declaredMediaType: string
    readonly displayName: string
    readonly expectedSha256: string
    readonly expectedSizeBytes: number
  },
): string {
  return JSON.stringify([
    profileId,
    file.displayName,
    file.declaredMediaType,
    file.expectedSizeBytes,
    file.expectedSha256,
    true,
    false,
    true,
  ])
}

function NativeIntakePage() {
  const [text, setText] = useState('')
  const [status, setStatus] = useState<NativeIntakeStatus>('IDLE')
  const [receipt, setReceipt] = useState<IntakeReceipt | null>(null)
  const [safeError, setSafeError] = useState<string | null>(null)
  const [localAiSettings, setLocalAiSettings] =
    useState<LocalAISettings | null>(null)
  const [fileState, setFileState] = useState<'NONE' | 'PROCESSING' | 'ACCEPTED'>(
    'NONE',
  )
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const setSourceId = usePhase3WorkflowStore((state) => state.setSourceId)
  const clearSource = usePhase3WorkflowStore((state) => state.clearSource)
  const pasteIdempotencyKey = useRef(crypto.randomUUID())
  const fileIntakeRetry = useRef<FileIntakeRetryBinding | null>(null)
  const pending = status === 'PROCESSING'
  const ready = status === 'READY' && receipt !== null
  const activeModel =
    localAiSettings?.enabled === true ? localAiSettings.selectedModel : null

  useEffect(() => {
    let cancelled = false
    void getLocalAISettings()
      .then((settings) => {
        if (!cancelled) setLocalAiSettings(settings)
      })
      .catch(() => {
        if (!cancelled) setLocalAiSettings(null)
      })
    return () => { cancelled = true }
  }, [])

  function acceptReceipt(nextReceipt: IntakeReceipt, expectedProfileId: string) {
    if (nextReceipt.profileId !== expectedProfileId) {
      throw new Error('Intake response scope mismatch')
    }
    setReceipt(nextReceipt)
    setSourceId(nextReceipt.sourceId)
    setStatus('READY')
  }

  async function extractPastedText() {
    if (pending || text.length === 0) return
    setSafeError(null)
    setStatus('PROCESSING')
    clearSource()
    try {
      if (profileId === null) throw new Error('A named profile is required')
      const activeProfileId = profileId
      const nextReceipt = await submitPastedIntake({
        idempotencyKey: pasteIdempotencyKey.current,
        profileId: activeProfileId,
        displayName: 'Pasted local source',
        content: text,
        consentConfirmed: true,
        retainRawSource: false,
        semanticEnrichmentEnabled: true,
      })
      acceptReceipt(nextReceipt, activeProfileId)
      setText('')
      pasteIdempotencyKey.current = crypto.randomUUID()
    } catch {
      setStatus('ERROR')
      setSafeError(
        'Local intake could not complete. Confirm the vault is unlocked and try again.',
      )
    }
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget
    const selectedFiles = input.files
    if (pending || selectedFiles === null || selectedFiles.length !== 1) {
      input.value = ''
      return
    }

    setSafeError(null)
    setStatus('PROCESSING')
    setFileState('PROCESSING')
    clearSource()
    try {
      const prepared = await prepareSelectedIntakeFile(selectedFiles[0])
      if (profileId === null) throw new Error('A named profile is required')
      const activeProfileId = profileId
      const fingerprint = fileIntakeFingerprint(activeProfileId, prepared)
      const idempotencyKey =
        fileIntakeRetry.current?.fingerprint === fingerprint
          ? fileIntakeRetry.current.idempotencyKey
          : crypto.randomUUID()
      fileIntakeRetry.current = { fingerprint, idempotencyKey }
      const nextReceipt = await submitFileIntake({
        idempotencyKey,
        profileId: activeProfileId,
        ...prepared,
        consentConfirmed: true,
        retainRawSource: false,
        semanticEnrichmentEnabled: true,
      })
      acceptReceipt(nextReceipt, activeProfileId)
      fileIntakeRetry.current = null
      setFileState('ACCEPTED')
    } catch {
      setStatus('ERROR')
      setFileState('NONE')
      setSafeError(
        'The selected file could not be accepted or parsed. Choose one allowed file up to 1 MiB.',
      )
    } finally {
      input.value = ''
    }
  }

  const candidateCount = receipt?.candidateCount ?? 0
  const quarantineCount = receipt?.quarantineCount ?? 0
  const localAiFailed =
    receipt !== null &&
    ['TIMEOUT', 'UNAVAILABLE', 'INVALID_RESPONSE'].includes(receipt.localAiStatus)
  const localAiSkipped =
    receipt !== null &&
    ['DISABLED', 'NOT_REQUESTED'].includes(receipt.localAiStatus)
  const localAiDetail =
    receipt?.localAiStatus === 'SUCCEEDED'
      ? `${receipt.localAiSuggestionCount} probable · ${receipt.localAiProvider ?? 'local'} model`
      : receipt?.localAiStatus === 'TIMEOUT'
        ? 'Timed out · deterministic result kept'
        : receipt?.localAiStatus === 'INVALID_RESPONSE'
          ? 'Invalid response · deterministic result kept'
          : receipt?.localAiStatus === 'UNAVAILABLE'
            ? 'Service unavailable · deterministic result kept'
        : localAiSkipped
          ? 'Deterministic only'
          : 'queued'
  const localAiOutcomeMessage = receipt?.localAiStatus === 'SUCCEEDED'
    ? `Local AI added ${receipt.localAiSuggestionCount} grounded suggestion${receipt.localAiSuggestionCount === 1 ? '' : 's'} for review.`
    : receipt?.localAiStatus === 'TIMEOUT'
      ? 'The selected local model did not finish within two minutes. Deterministic extraction was kept.'
      : receipt?.localAiStatus === 'INVALID_RESPONSE'
        ? 'The selected local model returned output that did not pass Ariadne’s grounding contract after one retry. Deterministic extraction was kept.'
        : receipt?.localAiStatus === 'UNAVAILABLE'
          ? 'The selected local model service could not be reached. Deterministic extraction was kept.'
          : activeModel === null
            ? 'Deterministic extraction · no model selected'
            : 'Deterministic extraction completed without local-model suggestions.'
  const pipelineState = ready
    ? (['complete', 'complete', 'complete', localAiFailed ? 'fallback' : localAiSkipped ? 'skipped' : 'complete', 'active'] as const)
    : pending
      ? (['complete', 'active', 'queued', 'queued', 'queued'] as const)
      : (['active', 'queued', 'queued', 'queued', 'queued'] as const)
  const pipelineLabels = [
    'MIME + encoding',
    'Restricted scan',
    'Deterministic extract',
    'Local enrichment',
    'Human review',
  ] as const

  if (profileId === null) {
    return (
      <div className="page intake-page" data-testid="route-ready">
        <PageHeader
          eyebrow="Audit builder · profile required"
          title="Choose where this audit belongs"
          description="Ariadne never creates an unnamed generic profile. Create or select a durable profile before importing identifiers."
        />
        <Panel className="panel--signal">
          <div className="empty-state">
            <LockKeyhole size={24} />
            <h2>No active profile</h2>
            <p>The selected profile will retain this intake, review decisions, sources, audit progress, and final package.</p>
            <Link className="button button--primary" to="/audits/new">
              Create or select profile <ArrowRight size={14} />
            </Link>
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div className="page intake-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · step 2 of 7"
        title="Add source material"
        description="Paste or select one file for local parsing. Restricted values are quarantined before extraction, logging, or model use."
        meta={
          <>
            <Badge tone="green" dot>Native local processing</Badge>
            <Badge tone={activeModel === null ? 'neutral' : 'violet'}>
              {activeModel === null ? 'AI off' : `AI · ${activeModel}`}
            </Badge>
          </>
        }
        actions={
          <Link className="button button--ghost" to="/audits/new">
            <ArrowLeft size={14} /> Back
          </Link>
        }
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Profile', 'Intake', 'Entities', 'Discovery', 'AI review', 'Results', 'Report'].map((step, index) => (
          <li className={index < 1 ? 'is-complete' : index === 1 ? 'is-active' : ''} key={step}>
            <span>{index < 1 ? <Check size={11} /> : index + 1}</span>
            <strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="compact-workflow-action compact-workflow-action--intake" role="region" aria-label="Intake step action">
        <div>
          <strong>{ready ? `${candidateCount} candidates ready` : pending ? activeModel === null ? 'Processing locally' : `Extracting with ${activeModel}` : 'Extraction required'}</strong>
          <span>{quarantineCount > 0 ? `${quarantineCount} restricted value${quarantineCount === 1 ? '' : 's'} quarantined` : ready ? localAiOutcomeMessage : activeModel === null ? 'Deterministic extraction · no model selected' : 'Natural-language clues will be enriched by the selected local model'}</span>
        </div>
        <Link className={`button button--primary ${!ready ? 'is-disabled' : ''}`} to={ready ? '/audits/new/entities' : '#'} aria-disabled={!ready}>
          Review candidates <ArrowRight size={14} />
        </Link>
      </div>

      <div className="page-grid intake-grid">
        <Panel className="span-7 panel--signal" eyebrow="Free-text intake" title="Paste authorised identity clues" action={<Badge tone="green">Nothing transmitted</Badge>}>
          <div className="panel__body intake-editor">
            <label className="sr-only" htmlFor="intake-text">Local source text</label>
            <textarea
              id="intake-text"
              className="textarea intake-textarea mono"
              value={text}
              maxLength={262_144}
              placeholder="Write naturally or paste structured identifiers—for example: “My name is…, I also use…, I study at…, and my username is…”."
              onChange={(event) => {
                setText(event.target.value)
                setReceipt(null)
                setStatus('IDLE')
                setSafeError(null)
                clearSource()
                pasteIdempotencyKey.current = crypto.randomUUID()
              }}
              spellCheck={false}
              disabled={pending}
            />
            <div className="intake-editor__footer">
              <span>{text.length} characters · UTF-8 · memory only</span>
              <Button size="compact" variant="secondary" onClick={() => void extractPastedText()} disabled={pending || text.length === 0}>
                <ScanSearch size={13} /> {pending ? 'Processing…' : 'Extract locally'}
              </Button>
            </div>
          </div>
        </Panel>

        <Panel className="span-5" eyebrow="File intake" title="Select one local file">
          <div className="panel__body">
            <label className="file-dropzone" htmlFor="file-input">
              <input id="file-input" type="file" accept=".txt,.md,.csv,.json,.vcf" aria-label="Choose one local intake file" onChange={(event) => void selectFile(event)} disabled={pending} />
              <span className="file-dropzone__icon"><UploadCloud size={21} /></span>
              <strong>Choose one file</strong>
              <p>The selected bytes are bounded, hashed, and parsed in a restricted local worker.</p>
              <span className="file-type-row">
                {['TXT', 'MD', 'CSV', 'JSON', 'VCF'].map((type) => <Badge key={type}>{type}</Badge>)}
              </span>
            </label>
            {fileState !== 'NONE' && (
              <div className="selected-file" aria-live="polite">
                <span className="status-icon status-icon--green"><FileCheck2 size={14} /></span>
                <div><strong>Selected local file</strong><small>{fileState === 'PROCESSING' ? 'Reading and parsing locally' : 'Accepted · content released from the picker'}</small></div>
                <Badge tone={fileState === 'PROCESSING' ? 'cyan' : 'green'}>{fileState === 'PROCESSING' ? 'Processing' : 'Accepted'}</Badge>
              </div>
            )}
          </div>
        </Panel>

        <Panel className="span-7" eyebrow="Local pipeline" title="Intake processing">
          <div className="pipeline-track">
            {pipelineLabels.map((label, index) => {
              const stepStatus = pipelineState[index]
              return (
                <div className={`pipeline-step is-${stepStatus}`} key={label}>
                  <span>{stepStatus === 'complete' ? <Check size={12} /> : index + 1}</span>
                  <div><strong>{label}</strong><small>{index === 3 && ready ? localAiDetail : stepStatus === 'active' && ready ? `${candidateCount} candidates` : stepStatus}</small></div>
                </div>
              )
            })}
          </div>
          <div className="intake-result-strip">
            <div><FileText size={14} /><span>{receipt?.segmentCount ?? 0} source segments</span></div>
            <div><Braces size={14} /><span>{candidateCount} candidates</span></div>
            <div><Files size={14} /><span>{receipt?.duplicateCount ?? 0} duplicates</span></div>
            <div><ShieldAlert size={14} /><span>{quarantineCount} quarantined</span></div>
          </div>
          {localAiFailed && (
            <div className="callout callout--warning" role="status">
              <ShieldAlert size={14} />
              <span>{localAiOutcomeMessage}</span>
            </div>
          )}
        </Panel>

        <Panel className="span-5" eyebrow="Restricted-value boundary" title="Quarantine summary" action={<Badge tone={quarantineCount > 0 ? 'amber' : 'green'}>{quarantineCount} detected</Badge>}>
          <div className="panel__body stack">
            <div className="quarantine-card">
              <span className={`status-icon ${quarantineCount > 0 ? 'status-icon--amber' : 'status-icon--green'}`}><LockKeyhole size={14} /></span>
              <div><strong>{quarantineCount > 0 ? 'Restricted values suppressed' : 'No restricted values reported'}</strong><span>Values are never returned to this screen, logged, indexed, prompted, or transmitted.</span></div>
            </div>
            {safeError && <div className="callout callout--danger" role="alert"><ShieldAlert size={15} /><span>{safeError}</span></div>}
          </div>
        </Panel>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <ScanSearch size={16} />
            <div><strong>{ready ? 'Local extraction ready for review.' : pending ? 'Local restricted worker is processing.' : 'Add source material to begin local extraction.'}</strong><span>No query or provider task has been created.</span></div>
          </div>
          <Link className={`button button--primary ${!ready ? 'is-disabled' : ''}`} to={ready ? '/audits/new/entities' : '#'} aria-disabled={!ready}>
            Review candidates <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </div>
  )
}

function SimulatedIntakePage() {
  const [text, setText] = useState(syntheticText)
  const [parsed, setParsed] = useState(true)

  return (
    <div className="page intake-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Audit builder · step 2 of 7"
        title="Add source material"
        description="Paste or select files for local parsing. Restricted values are quarantined before extraction, logging, or model use."
        meta={
          <>
            <Badge tone="green" dot>Local processing</Badge>
            <Badge tone="cyan">5 MVP file types</Badge>
          </>
        }
        actions={
          <Link className="button button--ghost" to="/audits/new">
            <ArrowLeft size={14} /> Back
          </Link>
        }
      />

      <ol className="wizard-steps" aria-label="Audit creation steps">
        {['Profile', 'Intake', 'Entities', 'Discovery', 'AI review', 'Results', 'Report'].map((step, index) => (
          <li className={index < 1 ? 'is-complete' : index === 1 ? 'is-active' : ''} key={step}>
            <span>{index < 1 ? <Check size={11} /> : index + 1}</span>
            <strong>{step}</strong>
          </li>
        ))}
      </ol>

      <div className="compact-workflow-action compact-workflow-action--intake" role="region" aria-label="Intake step action">
        <div>
          <strong>{parsed ? '6 candidates ready' : 'Extraction required'}</strong>
          <span>Restricted value remains quarantined</span>
        </div>
        <Link className={`button button--primary ${!parsed ? 'is-disabled' : ''}`} to={parsed ? '/audits/new/entities' : '#'} aria-disabled={!parsed}>
          Review 6 candidates <ArrowRight size={14} />
        </Link>
      </div>

      <div className="page-grid intake-grid">
        <Panel className="span-7 panel--signal" eyebrow="Free-text intake" title="Synthetic identity clues" action={<Badge tone="green">Nothing transmitted</Badge>}>
          <div className="panel__body intake-editor">
            <label className="sr-only" htmlFor="intake-text">Synthetic source text</label>
            <textarea
              id="intake-text"
              className="textarea intake-textarea mono"
              value={text}
              onChange={(event) => { setText(event.target.value); setParsed(false) }}
              spellCheck={false}
            />
            <div className="intake-editor__footer">
              <span>{text.length} characters · UTF-8</span>
              <Button size="compact" variant="secondary" onClick={() => setParsed(true)}>
                <ScanSearch size={13} /> Extract locally
              </Button>
            </div>
          </div>
        </Panel>

        <Panel className="span-5" eyebrow="File intake" title="Select local files">
          <div className="panel__body">
            <label className="file-dropzone" htmlFor="file-input">
              <input id="file-input" type="file" accept=".txt,.md,.csv,.json,.vcf" multiple />
              <span className="file-dropzone__icon"><UploadCloud size={21} /></span>
              <strong>Choose files or drop them here</strong>
              <p>Files remain on this Mac and are parsed in a restricted local worker.</p>
              <span className="file-type-row">
                {['TXT', 'MD', 'CSV', 'JSON', 'VCF'].map((type) => <Badge key={type}>{type}</Badge>)}
              </span>
            </label>
            <div className="selected-file">
              <span className="status-icon status-icon--green"><FileCheck2 size={14} /></span>
              <div><strong>fictional_profile_notes.md</strong><small>4.8 KB · safe text · synthetic</small></div>
              <Badge tone="green">Accepted</Badge>
            </div>
          </div>
        </Panel>

        <Panel className="span-7" eyebrow="Local pipeline" title="Intake processing">
          <div className="pipeline-track">
            {pipeline.map(([label, status], index) => (
              <div className={`pipeline-step is-${status}`} key={label}>
                <span>{status === 'complete' ? <Check size={12} /> : index + 1}</span>
                <div><strong>{label}</strong><small>{status === 'active' ? '6 entity candidates' : status}</small></div>
              </div>
            ))}
          </div>
          <div className="intake-result-strip">
            <div><FileText size={14} /><span>1 source segment</span></div>
            <div><Braces size={14} /><span>6 candidates</span></div>
            <div><Files size={14} /><span>0 duplicates</span></div>
            <div><ShieldAlert size={14} /><span>1 quarantined</span></div>
          </div>
        </Panel>

        <Panel className="span-5" eyebrow="Restricted-value boundary" title="Quarantine summary" action={<Badge tone="amber">1 detected</Badge>}>
          <div className="panel__body stack">
            <div className="quarantine-card">
              <span className="status-icon status-icon--amber"><LockKeyhole size={14} /></span>
              <div><strong>Possible authentication secret</strong><span>Value suppressed · never logged, indexed, prompted, or transmitted</span></div>
            </div>
            <div className="callout callout--warning">
              <ShieldAlert size={15} />
              <span>Quarantined content is excluded from the reviewed profile. Review it locally before deletion.</span>
            </div>
          </div>
        </Panel>

        <div className="span-12 audit-builder-footer">
          <div className="audit-builder-note">
            <ScanSearch size={16} />
            <div><strong>{parsed ? 'Local extraction ready for review.' : 'Source changed; run local extraction again.'}</strong><span>No query or provider task has been created.</span></div>
          </div>
          <Link className={`button button--primary ${!parsed ? 'is-disabled' : ''}`} to={parsed ? '/audits/new/entities' : '#'} aria-disabled={!parsed}>
            Review 6 candidates <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </div>
  )
}
