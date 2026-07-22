/** Durable finding review: immutable evidence, attribution history, and remediation handoff. */
import {
  type ChangeEvent,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  Check,
  CheckCircle2,
  Copy,
  EyeOff,
  FileArchive,
  FileCheck2,
  Fingerprint,
  GitBranch,
  LockKeyhole,
  Plus,
  Scissors,
  ShieldCheck,
  TriangleAlert,
  UploadCloud,
  UserCheck,
  XCircle,
} from 'lucide-react'
import {
  appendPhase5AttributionDecision,
  createPhase5RedactedDerivative,
  importPhase5Evidence,
  loadPhase5Finding,
  type Phase5AttributionState,
  type Phase5EvidenceArtifact,
  type Phase5FindingDetail,
  type Phase5IntegrityStatus,
  type Phase5ManualArtifactKind,
} from '../app/phase5Boundary'
import {
  createPhase6RemediationCase,
  type Phase6RemediationAction,
} from '../app/phase6Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import {
  preparePhase5EvidenceFile,
  selectedPhase5EvidenceFileLimits,
} from '../app/selectedPhase5EvidenceFile'
import { Phase5StatePanel } from '../components/Phase5StatePanel'
import {
  Badge,
  Button,
  DefinitionList,
  PageHeader,
  Panel,
  type Tone,
} from '../components/Primitives'

const integrityTone: Record<Phase5IntegrityStatus, Tone> = {
  VERIFIED: 'green',
  NOT_VERIFIED: 'amber',
  FAILED: 'rose',
}

const manualArtifactKinds: ReadonlyArray<Phase5ManualArtifactKind> = [
  'SCREENSHOT',
  'HTML',
  'PDF',
  'RAW_JSON',
]

const attributionStates: ReadonlyArray<Phase5AttributionState> = [
  'CONFIRMED_MATCH',
  'CONFIRMED_NON_MATCH',
  'PROBABLE',
  'POSSIBLE',
  'UNRESOLVED',
  'NEEDS_MORE_EVIDENCE',
]

const remediationActions: ReadonlyArray<Phase6RemediationAction> = [
  'MONITOR',
  'PRESERVE_EVIDENCE',
  'DELETE_OWNED_ACCOUNT',
  'REQUEST_CORRECTION',
  'DRAFT_ERASURE_OR_DEINDEX',
  'DRAFT_IMPERSONATION_REPORT',
  'CONTACT',
  'ESCALATE',
  'MARK_LEGALLY_PERSISTENT',
]

const localRemediationActions = new Set<Phase6RemediationAction>([
  'MONITOR',
  'PRESERVE_EVIDENCE',
])

type WriteStatus = {
  readonly tone: 'success' | 'danger' | 'warning'
  readonly message: string
}

function WriteOperationStatus({ status }: { readonly status: WriteStatus | null }) {
  if (status === null) return null
  return (
    <div
      className={`phase5-write-status callout callout--${status.tone}`}
      role={status.tone === 'danger' ? 'alert' : 'status'}
    >
      {status.tone === 'success' ? (
        <CheckCircle2 size={14} aria-hidden="true" />
      ) : (
        <AlertTriangle size={14} aria-hidden="true" />
      )}
      <span>{status.message}</span>
    </div>
  )
}

function selectedFileCopy(file: File | null): string {
  if (file === null) return 'No file selected'
  const kibibytes = Math.max(1, Math.ceil(file.size / 1_024))
  return `One local file selected · ${kibibytes.toLocaleString()} KiB`
}

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
    second: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(new Date(Math.floor(timestampUs / 1_000)))
}

function artifactIntegrityCopy(status: Phase5IntegrityStatus): {
  readonly title: string
  readonly detail: string
} {
  if (status === 'VERIFIED') {
    return {
      title: 'Stored bytes match the recorded SHA-256.',
      detail: 'Integrity after capture is verified; the source claim and identity attribution are not.',
    }
  }
  if (status === 'FAILED') {
    return {
      title: 'Artifact integrity check failed.',
      detail: 'Do not rely on this artifact until the original is recovered or recaptured.',
    }
  }
  return {
    title: 'Artifact integrity has not been verified.',
    detail: 'The hash is recorded, but the current bytes have not passed a local verification check.',
  }
}

function EvidenceArtifactPanel({
  artifacts,
}: {
  readonly artifacts: ReadonlyArray<Phase5EvidenceArtifact>
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [copiedHash, setCopiedHash] = useState<string | null>(null)
  const selected = useMemo(
    () =>
      artifacts.find((artifact) => artifact.artifactId === selectedId) ??
      artifacts[0] ??
      null,
    [artifacts, selectedId],
  )

  if (selected === null) {
    return (
      <Panel
        className="evidence-panel panel--raised"
        eyebrow="Immutable evidence"
        title="No artifact attached"
      >
        <div className="phase5-evidence-empty" role="status">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>This finding has no persisted evidence artifact.</strong>
            <span>Attribution remains incomplete; no preview or synthetic artifact is substituted.</span>
          </div>
        </div>
      </Panel>
    )
  }

  const integrity = artifactIntegrityCopy(selected.integrityStatus)
  const viewport = selected.viewport
    ? `${selected.viewport.width} × ${selected.viewport.height} · ${(selected.viewport.deviceScaleMicros / 1_000_000).toFixed(2)}×`
    : 'Not applicable'
  const http = selected.httpStatus === null
    ? `${selected.redirectCount} redirects · no HTTP status retained`
    : `${selected.httpStatus} · ${selected.redirectCount} redirects`

  const copyHash = () => {
    void navigator.clipboard?.writeText(selected.contentSha256)
    setCopiedHash(selected.contentSha256)
  }

  return (
    <Panel
      className="evidence-panel panel--raised"
      eyebrow="Immutable evidence"
      title={`${words(selected.kind)} original`}
      action={
        <Badge tone={integrityTone[selected.integrityStatus]}>
          <ShieldCheck size={11} /> {words(selected.integrityStatus)}
        </Badge>
      }
    >
      {artifacts.length > 1 ? (
        <div className="phase5-artifact-index" aria-label="Evidence artifacts">
          {artifacts.map((artifact, index) => (
            <button
              type="button"
              key={artifact.artifactId}
              aria-pressed={artifact.artifactId === selected.artifactId}
              onClick={() => setSelectedId(artifact.artifactId)}
            >
              <FileArchive size={13} aria-hidden="true" />
              <span>Artifact {index + 1}</span>
              <Badge tone={integrityTone[artifact.integrityStatus]}>{words(artifact.kind)}</Badge>
            </button>
          ))}
        </div>
      ) : null}

      <div className="phase5-sealed-preview" role="img" aria-label="Encrypted original content remains sealed">
        <LockKeyhole size={24} aria-hidden="true" />
        <strong>Original content remains sealed</strong>
        <span>This view exposes integrity and provenance metadata only.</span>
        <Badge tone="green">Encrypted at rest</Badge>
      </div>

      <div
        className={`evidence-integrity callout ${
          selected.integrityStatus === 'VERIFIED'
            ? 'callout--success'
            : 'callout--warning'
        }`}
        role={selected.integrityStatus === 'FAILED' ? 'alert' : 'status'}
      >
        <Fingerprint size={15} aria-hidden="true" />
        <span><strong>{integrity.title}</strong> {integrity.detail}</span>
      </div>

      <DefinitionList
        items={[
          ['Artifact ID', <span className="mono wrap-anywhere" key="id">{selected.artifactId}</span>],
          ['Artifact type', words(selected.kind)],
          ['Captured (UTC)', <span className="mono" key="captured">{displayTime(selected.capturedAtUs)}</span>],
          ['Exact source URL', <span className="mono wrap-anywhere" key="source">{selected.sourceUrl ?? 'No source URL retained'}</span>],
          ['HTTP / redirects', http],
          ['Viewport', <span className="mono" key="viewport">{viewport}</span>],
          ['Capture method', words(selected.captureMethod)],
          ['Provider', <span className="mono wrap-anywhere" key="provider">{selected.providerId}</span>],
          ['Audit run', <span className="mono wrap-anywhere" key="run">{selected.runId}</span>],
          ['Redacted derivatives', String(selected.derivativeCount)],
          ['Encryption', 'Required and active'],
          ['Integrity state', words(selected.integrityStatus)],
        ]}
      />

      <div className="evidence-hash">
        <div><span>SHA-256</span><Badge tone={integrityTone[selected.integrityStatus]}>{words(selected.integrityStatus)}</Badge></div>
        <code role="region" aria-label="Complete SHA-256 evidence hash" tabIndex={0}>
          {selected.contentSha256}
        </code>
        <Button variant="ghost" size="compact" onClick={copyHash}>
          {copiedHash === selected.contentSha256 ? <Check size={12} /> : <Copy size={12} />}
          {copiedHash === selected.contentSha256 ? 'Copied' : 'Copy full hash'}
        </Button>
      </div>
    </Panel>
  )
}

function AttributionPanel({ detail }: { readonly detail: Phase5FindingDetail }) {
  const { assessment, humanDecision } = detail
  return (
    <Panel
      className="attribution-panel panel--raised"
      eyebrow="Explainable attribution"
      title="Why this may be connected"
      action={<Badge tone="violet">Weights · {assessment.weightProfileVersion}</Badge>}
    >
      <div className="attribution-summary">
        <span className="status-icon status-icon--violet"><UserCheck size={16} /></span>
        <div>
          <strong>Automated assessment only · human review required</strong>
          <p>The score combines recorded support and contradictions. It does not assign identity ownership or replace a human decision.</p>
        </div>
        <span className="attribution-summary__score mono">{assessment.score >= 0 ? '+' : ''}{assessment.score}<small>/ 1000</small></span>
      </div>

      <div className="phase5-signal-groups">
        <section aria-labelledby="phase5-supporting-signals">
          <h3 id="phase5-supporting-signals">Contributing signals</h3>
          <div className="signal-list">
            {assessment.contributingSignals.length > 0 ? (
              assessment.contributingSignals.map((signal) => (
                <article className="signal-row signal-row--positive" key={signal.signal}>
                  <span className="signal-row__icon"><CheckCircle2 size={14} /></span>
                  <div>
                    <strong>{words(signal.signal)}</strong>
                    <small>{signal.evidenceArtifactIds.length} linked artifact{signal.evidenceArtifactIds.length === 1 ? '' : 's'}</small>
                    <span className="signal-row__sources">
                      {signal.evidenceArtifactIds.map((artifactId) => <code key={artifactId}>{artifactId}</code>)}
                    </span>
                  </div>
                  <b className="mono">+{signal.weight}</b>
                </article>
              ))
            ) : (
              <div className="phase5-signal-empty">No contributing signal is recorded.</div>
            )}
          </div>
        </section>

        <section aria-labelledby="phase5-contradicting-signals">
          <h3 id="phase5-contradicting-signals">Contradictions</h3>
          <div className="signal-list">
            {assessment.contradictions.length > 0 ? (
              assessment.contradictions.map((signal) => (
                <article className="signal-row signal-row--negative" key={signal.signal}>
                  <span className="signal-row__icon"><XCircle size={14} /></span>
                  <div>
                    <strong>{words(signal.signal)}</strong>
                    <small>{signal.evidenceArtifactIds.length} linked artifact{signal.evidenceArtifactIds.length === 1 ? '' : 's'}</small>
                    <span className="signal-row__sources">
                      {signal.evidenceArtifactIds.map((artifactId) => <code key={artifactId}>{artifactId}</code>)}
                    </span>
                  </div>
                  <b className="mono">−{signal.penalty}</b>
                </article>
              ))
            ) : (
              <div className="phase5-signal-empty">No contradiction is recorded. This is not proof that none exists.</div>
            )}
          </div>
        </section>

        <section aria-labelledby="phase5-missing-signals">
          <h3 id="phase5-missing-signals">Missing evidence</h3>
          <div className="signal-list">
            {assessment.missingEvidence.length > 0 ? (
              assessment.missingEvidence.map((signal) => (
                <article className="signal-row signal-row--missing" key={signal.signal}>
                  <span className="signal-row__icon"><TriangleAlert size={14} /></span>
                  <div>
                    <strong>{words(signal.signal)}</strong>
                    <small>{assessment.recommendedNextEvidence.includes(signal.signal) ? 'Recommended next evidence' : 'Not observed in this assessment'}</small>
                  </div>
                  <b className="mono">up to +{signal.potentialWeight}</b>
                </article>
              ))
            ) : (
              <div className="phase5-signal-empty">No missing-evidence item is recorded.</div>
            )}
          </div>
        </section>
      </div>

      <div className="attribution-decision">
        <div>
          <strong>{humanDecision === null ? 'No human attribution decision recorded' : `Human decision: ${words(humanDecision.state)}`}</strong>
          <span>
            {humanDecision === null
              ? 'Review remains required; this screen does not create an in-memory substitute.'
              : `${humanDecision.actorLabel} · ${displayTime(humanDecision.decidedAtUs)}`}
          </span>
        </div>
        <Badge tone={humanDecision === null ? 'amber' : 'green'}>
          {humanDecision === null ? 'Review required' : 'Human decision'}
        </Badge>
      </div>
    </Panel>
  )
}

function ManualEvidenceImportPanel({
  detail,
  onChanged,
}: {
  readonly detail: Phase5FindingDetail
  readonly onChanged: () => void
}) {
  const [kind, setKind] = useState<Phase5ManualArtifactKind>('SCREENSHOT')
  const [file, setFile] = useState<File | null>(null)
  const [viewportWidth, setViewportWidth] = useState('1440')
  const [viewportHeight, setViewportHeight] = useState('900')
  const [deviceScaleMicros, setDeviceScaleMicros] = useState('1000000')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<WriteStatus | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.currentTarget.files
    setFile(selected?.length === 1 ? selected[0] : null)
    setStatus(null)
  }

  function clearSelectedFile() {
    setFile(null)
    if (fileInput.current !== null) fileInput.current.value = ''
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || file === null) return
    setBusy(true)
    setStatus(null)
    let contentBase64: string | null = null
    try {
      const width = Number(viewportWidth)
      const height = Number(viewportHeight)
      const scale = Number(deviceScaleMicros)
      const viewport = kind === 'SCREENSHOT'
        ? { width, height, deviceScaleMicros: scale }
        : null
      contentBase64 = await preparePhase5EvidenceFile(file, kind)
      const result = await importPhase5Evidence({
        profileId: detail.profileId,
        findingId: detail.finding.findingId,
        kind,
        contentBase64,
        viewport,
        metadata: [],
      })
      setStatus({
        tone: 'success',
        message: result.deduplicated
          ? 'The existing immutable artifact was linked locally. Refreshing evidence metadata.'
          : 'The immutable artifact was imported into the encrypted local vault. Refreshing evidence metadata.',
      })
      onChanged()
    } catch {
      setStatus({
        tone: 'danger',
        message: 'The local import was rejected. Check the selected kind, file size, screenshot viewport, unlocked vault, and possible provenance conflict.',
      })
    } finally {
      contentBase64 = null
      clearSelectedFile()
      setBusy(false)
    }
  }

  const viewportValid = kind !== 'SCREENSHOT' || (
    Number.isInteger(Number(viewportWidth)) &&
    Number(viewportWidth) >= 1 &&
    Number(viewportWidth) <= 16_384 &&
    Number.isInteger(Number(viewportHeight)) &&
    Number(viewportHeight) >= 1 &&
    Number(viewportHeight) <= 16_384 &&
    Number.isInteger(Number(deviceScaleMicros)) &&
    Number(deviceScaleMicros) >= 100_000 &&
    Number(deviceScaleMicros) <= 8_000_000
  )

  return (
    <Panel
      className="phase5-write-panel"
      eyebrow="Manual local evidence"
      title="Import an immutable artifact"
      action={<Badge tone="green">Local only</Badge>}
    >
      <form className="phase5-write-form" onSubmit={(event) => void submit(event)}>
        <p className="phase5-write-note">
          Select one authorised local file. Its content is encoded only for the native command, encrypted at rest, and never rendered in this view.
        </p>
        <div className="phase5-write-fields phase5-write-fields--two">
          <label className="field">
            <span>Artifact kind</span>
            <select
              className="select"
              value={kind}
              disabled={busy}
              onChange={(event) => {
                setKind(event.target.value as Phase5ManualArtifactKind)
                clearSelectedFile()
                setStatus(null)
              }}
            >
              {manualArtifactKinds.map((value) => (
                <option key={value} value={value}>{words(value)}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Local file · maximum 10 MiB</span>
            <input
              ref={fileInput}
              className="input"
              type="file"
              aria-label="Choose manual evidence file"
              accept={selectedPhase5EvidenceFileLimits.acceptedImportSuffixes[kind]}
              disabled={busy}
              onChange={selectFile}
            />
            <small aria-live="polite">{selectedFileCopy(file)}</small>
          </label>
        </div>
        {kind === 'SCREENSHOT' ? (
          <fieldset className="phase5-viewport-fields">
            <legend>Screenshot viewport</legend>
            <label className="field">
              <span>Width (px)</span>
              <input className="input" type="number" min={1} max={16_384} value={viewportWidth} disabled={busy} onChange={(event) => setViewportWidth(event.target.value)} />
            </label>
            <label className="field">
              <span>Height (px)</span>
              <input className="input" type="number" min={1} max={16_384} value={viewportHeight} disabled={busy} onChange={(event) => setViewportHeight(event.target.value)} />
            </label>
            <label className="field">
              <span>Device scale (micros)</span>
              <input className="input" type="number" min={100_000} max={8_000_000} step={100_000} value={deviceScaleMicros} disabled={busy} onChange={(event) => setDeviceScaleMicros(event.target.value)} />
            </label>
          </fieldset>
        ) : null}
        <WriteOperationStatus status={status} />
        <div className="phase5-write-actions">
          <span><LockKeyhole size={12} aria-hidden="true" /> No network request is made</span>
          <Button type="submit" variant="secondary" size="compact" disabled={busy || file === null || !viewportValid}>
            <UploadCloud size={13} aria-hidden="true" /> {busy ? 'Importing locally…' : 'Import selected file'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function RedactedDerivativePanel({
  detail,
  onChanged,
}: {
  readonly detail: Phase5FindingDetail
  readonly onChanged: () => void
}) {
  const [originalArtifactId, setOriginalArtifactId] = useState(
    detail.artifacts[0]?.artifactId ?? '',
  )
  const [file, setFile] = useState<File | null>(null)
  const [policyVersion, setPolicyVersion] = useState('manual-redaction-v1')
  const [summaryCode, setSummaryCode] = useState('USER_REVIEWED_REDACTION')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<WriteStatus | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  function clearSelectedFile() {
    setFile(null)
    if (fileInput.current !== null) fileInput.current.value = ''
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || file === null || !confirmed || originalArtifactId === '') return
    setBusy(true)
    setStatus(null)
    let contentBase64: string | null = null
    try {
      contentBase64 = await preparePhase5EvidenceFile(file)
      const result = await createPhase5RedactedDerivative({
        profileId: detail.profileId,
        originalArtifactId,
        redactedContentBase64: contentBase64,
        alreadyRedacted: true,
        redactionPolicyVersion: policyVersion,
        redactionSummaryCode: summaryCode,
      })
      setStatus({
        tone: 'success',
        message: result.deduplicated
          ? 'The existing caller-supplied derivative was retained. Refreshing evidence metadata.'
          : 'The caller-supplied redacted derivative was stored locally. Refreshing evidence metadata.',
      })
      setConfirmed(false)
      onChanged()
    } catch {
      setStatus({
        tone: 'danger',
        message: 'The derivative was rejected. Confirm the file is already redacted, metadata is valid, the vault is unlocked, and no incompatible derivative exists.',
      })
    } finally {
      contentBase64 = null
      clearSelectedFile()
      setBusy(false)
    }
  }

  const policyValid = /^[a-z0-9][a-z0-9._-]{0,63}$/.test(policyVersion)
  const summaryValid = /^[A-Z][A-Z0-9_]{1,63}$/.test(summaryCode)

  return (
    <Panel
      className="phase5-write-panel"
      eyebrow="Caller-supplied redaction"
      title="Store a redacted derivative"
      action={<Badge tone="amber">Manual confirmation</Badge>}
    >
      <form className="phase5-write-form" onSubmit={(event) => void submit(event)}>
        <p className="phase5-write-note">
          Ariadne does not redact this file. Prepare and inspect it first, then explicitly attest that the selected content is already redacted.
        </p>
        {detail.artifacts.length === 0 ? (
          <div className="phase5-evidence-empty" role="status">
            <AlertTriangle size={16} aria-hidden="true" />
            <div><strong>No original artifact is available.</strong><span>Import or attach an immutable original before storing a derivative.</span></div>
          </div>
        ) : (
          <>
            <label className="field">
              <span>Original artifact</span>
              <select className="select mono" value={originalArtifactId} disabled={busy} onChange={(event) => setOriginalArtifactId(event.target.value)}>
                {detail.artifacts.map((artifact, index) => (
                  <option key={artifact.artifactId} value={artifact.artifactId}>Artifact {index + 1} · {words(artifact.kind)}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Already-redacted local file · maximum 10 MiB</span>
              <input
                ref={fileInput}
                className="input"
                type="file"
                aria-label="Choose already-redacted derivative file"
                disabled={busy}
                onChange={(event) => {
                  const selected = event.currentTarget.files
                  setFile(selected?.length === 1 ? selected[0] : null)
                  setStatus(null)
                }}
              />
              <small aria-live="polite">{selectedFileCopy(file)}</small>
            </label>
            <div className="phase5-write-fields phase5-write-fields--two">
              <label className="field">
                <span>Redaction policy version</span>
                <input className="input mono" value={policyVersion} maxLength={64} disabled={busy} onChange={(event) => setPolicyVersion(event.target.value)} />
              </label>
              <label className="field">
                <span>Summary code</span>
                <select className="select mono" value={summaryCode} disabled={busy} onChange={(event) => setSummaryCode(event.target.value)}>
                  <option value="USER_REVIEWED_REDACTION">USER_REVIEWED_REDACTION</option>
                  <option value="PERSONAL_IDENTIFIERS_REMOVED">PERSONAL_IDENTIFIERS_REMOVED</option>
                  <option value="VISUAL_IDENTIFIERS_MASKED">VISUAL_IDENTIFIERS_MASKED</option>
                </select>
              </label>
            </div>
            <label className="phase5-confirmation">
              <input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />
              <span>I confirm the selected file is already redacted and safe to store as a derivative.</span>
            </label>
          </>
        )}
        <WriteOperationStatus status={status} />
        <div className="phase5-write-actions">
          <span><Scissors size={12} aria-hidden="true" /> Original bytes are never overwritten</span>
          <Button type="submit" variant="secondary" size="compact" disabled={busy || detail.artifacts.length === 0 || file === null || !confirmed || !policyValid || !summaryValid}>
            <FileCheck2 size={13} aria-hidden="true" /> {busy ? 'Storing locally…' : 'Store redacted derivative'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function AttributionDecisionPanel({
  detail,
  onChanged,
}: {
  readonly detail: Phase5FindingDetail
  readonly onChanged: () => void
}) {
  const [state, setState] = useState<Phase5AttributionState>(
    detail.humanDecision?.state ?? 'UNRESOLVED',
  )
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<WriteStatus | null>(null)
  const previous = detail.humanDecision

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setStatus(null)
    try {
      const result = await appendPhase5AttributionDecision({
        profileId: detail.profileId,
        findingId: detail.finding.findingId,
        assessmentId: detail.assessment.assessmentId,
        state,
        expectedPreviousDecisionId: previous?.decisionId ?? null,
        expectedPreviousRevision: previous?.revision ?? 0,
      })
      setStatus({
        tone: 'success',
        message: `Human decision revision ${result.revision.toLocaleString()} was appended locally. Refreshing the finding.`,
      })
      onChanged()
    } catch {
      setStatus({
        tone: 'danger',
        message: 'The decision was not recorded. The assessment or prior decision may have changed; reload the finding and review the latest revision before retrying.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      className="phase5-write-panel"
      eyebrow="Human attribution"
      title={previous === null ? 'Record a decision' : 'Supersede the latest decision'}
      action={<Badge tone="violet">Append only</Badge>}
    >
      <form className="phase5-write-form" onSubmit={(event) => void submit(event)}>
        <p className="phase5-write-note">
          This decision is bound to the displayed assessment and appended as a new immutable revision. It does not alter the automated score.
        </p>
        <div className="phase5-decision-binding">
          <span>Assessment <code>{detail.assessment.assessmentId}</code></span>
          <span>Expected prior revision <strong>{previous?.revision ?? 0}</strong></span>
        </div>
        <label className="field">
          <span>Human attribution decision</span>
          <select className="select" value={state} disabled={busy} onChange={(event) => setState(event.target.value as Phase5AttributionState)}>
            {attributionStates.map((value) => (
              <option key={value} value={value}>{words(value)}</option>
            ))}
          </select>
        </label>
        <WriteOperationStatus status={status} />
        <div className="phase5-write-actions">
          <span><UserCheck size={12} aria-hidden="true" /> Actor: Local user</span>
          <Button type="submit" variant="primary" size="compact" disabled={busy}>
            <Check size={13} aria-hidden="true" /> {busy ? 'Recording…' : previous === null ? 'Record decision' : 'Append superseding decision'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function RemediationCaseCreatePanel({
  detail,
}: {
  readonly detail: Phase5FindingDetail
}) {
  const [action, setAction] = useState<Phase6RemediationAction>('MONITOR')
  const [deadline, setDeadline] = useState('')
  const [draftText, setDraftText] = useState('')
  const [selectedEvidence, setSelectedEvidence] = useState<ReadonlySet<string>>(
    () => new Set(detail.artifacts.map((artifact) => artifact.artifactId)),
  )
  const [busy, setBusy] = useState(false)
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null)
  const [status, setStatus] = useState<WriteStatus | null>(null)
  const localOnly = localRemediationActions.has(action)
  const deadlineMs = deadline === '' ? null : new Date(deadline).getTime()
  const deadlineValid =
    deadline === '' ||
    (Number.isFinite(deadlineMs) && (deadlineMs ?? 0) > Date.now())
  const draftValid =
    localOnly ||
    draftText === '' ||
    (draftText.length <= 10_000 && draftText === draftText.trim())

  function toggleEvidence(artifactId: string, checked: boolean) {
    setSelectedEvidence((current) => {
      const next = new Set(current)
      if (checked) next.add(artifactId)
      else next.delete(artifactId)
      return next
    })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !deadlineValid || !draftValid) return
    setBusy(true)
    setStatus(null)
    setCreatedCaseId(null)
    try {
      const result = await createPhase6RemediationCase({
        profileId: detail.profileId,
        findingIds: [detail.finding.findingId],
        action,
        deadlineAtUs:
          deadlineMs === null ? null : Math.floor(deadlineMs * 1_000),
        evidenceReferences: [...selectedEvidence],
        draftText: localOnly || draftText === '' ? null : draftText,
      })
      setCreatedCaseId(result.case.caseId)
      setStatus({
        tone: 'success',
        message: `Local remediation case revision ${result.case.revision.toLocaleString()} was created. No request or message was sent.`,
      })
    } catch {
      setStatus({
        tone: 'danger',
        message: 'The local case was not created. Reload this finding before retrying if its evidence changed, and confirm the optional deadline is still in the future.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      className="phase5-write-panel"
      eyebrow="Local remediation tracking"
      title="Create a reviewed case"
      action={<Badge tone="cyan">Never sent automatically</Badge>}
    >
      <form className="phase5-write-form" onSubmit={(event) => void submit(event)}>
        <p className="phase5-write-note">
          This creates an encrypted local planning record only. Draft actions are text for your review; Ariadne does not contact a provider or execute a request.
        </p>
        <label className="field">
          <span>Tracked action</span>
          <select
            className="select"
            value={action}
            disabled={busy}
            onChange={(event) => {
              const next = event.target.value as Phase6RemediationAction
              setAction(next)
              if (localRemediationActions.has(next)) setDraftText('')
              setStatus(null)
              setCreatedCaseId(null)
            }}
          >
            {remediationActions.map((value) => (
              <option key={value} value={value}>{words(value)}</option>
            ))}
          </select>
          <small>{localOnly ? 'Local-only observation; outbound draft text is disabled.' : 'Planning/draft state only; no external action is available.'}</small>
        </label>
        <label className="field">
          <span>Optional future deadline</span>
          <input
            className="input"
            type="datetime-local"
            value={deadline}
            disabled={busy}
            onChange={(event) => {
              setDeadline(event.target.value)
              setStatus(null)
            }}
          />
          {!deadlineValid ? <small className="field-error">Choose a future date and time.</small> : null}
        </label>
        {localOnly ? null : (
          <label className="field">
            <span>Optional local draft</span>
            <textarea
              className="input phase6-draft-input"
              value={draftText}
              maxLength={10_000}
              disabled={busy}
              onChange={(event) => {
                setDraftText(event.target.value)
                setStatus(null)
              }}
              placeholder="Write reviewable draft text. Nothing is sent."
            />
            {!draftValid ? <small className="field-error">Remove surrounding whitespace before saving.</small> : null}
          </label>
        )}
        <fieldset className="phase6-evidence-picker">
          <legend>Evidence references to link</legend>
          {detail.artifacts.length === 0 ? (
            <small>No evidence artifact is available; the case can still be created for local tracking.</small>
          ) : (
            detail.artifacts.map((artifact, index) => (
              <label key={artifact.artifactId}>
                <input
                  type="checkbox"
                  checked={selectedEvidence.has(artifact.artifactId)}
                  disabled={busy}
                  onChange={(event) => toggleEvidence(artifact.artifactId, event.target.checked)}
                />
                <span>Artifact {index + 1} · {words(artifact.kind)}</span>
              </label>
            ))
          )}
        </fieldset>
        <WriteOperationStatus status={status} />
        <div className="phase5-write-actions">
          <span><CalendarClock size={12} aria-hidden="true" /> Finding and selected evidence are bound locally</span>
          {createdCaseId === null ? (
            <Button type="submit" variant="primary" size="compact" disabled={busy || !deadlineValid || !draftValid}>
              <Plus size={13} aria-hidden="true" /> {busy ? 'Creating locally…' : 'Create local case'}
            </Button>
          ) : (
            <Link className="button button--secondary button--compact" to="/remediation">
              Open Removal Tracker
            </Link>
          )}
        </div>
      </form>
    </Panel>
  )
}

function LoadedFindingDetail({
  detail,
  onChanged,
}: {
  readonly detail: Phase5FindingDetail
  readonly onChanged: () => void
}) {
  const { finding, assessment } = detail
  return (
    <>
      <PageHeader
        eyebrow={`Persisted finding · ${finding.findingId.slice(0, 8)}`}
        title={finding.title}
        description={finding.summary}
        meta={
          <>
            <Badge tone="green" dot>{words(finding.outcome)}</Badge>
            <Badge tone="blue">{words(finding.visibility)}</Badge>
            <Badge tone={finding.attributionState === null ? 'amber' : 'violet'}>
              {finding.attributionState === null ? 'No human decision' : words(finding.attributionState)}
            </Badge>
            <Badge>{words(finding.confidenceBand)} assessment</Badge>
          </>
        }
        actions={
          <Link className="button button--secondary" to="/graph">
            <GitBranch size={14} /> Open in Link Map
          </Link>
        }
      />

      <section className="finding-dimensions" aria-label="Independent finding dimensions">
        <div><span>Check outcome</span><strong>{words(finding.outcome)}</strong><small>One defined persisted check</small></div>
        <div><span>Visibility</span><strong>{words(finding.visibility)}</strong><small>Independent from ownership</small></div>
        <div><span>Human decision</span><strong>{finding.attributionState === null ? 'Not recorded' : words(finding.attributionState)}</strong><small>Automation never assigns this state</small></div>
        <div><span>Assessment</span><strong>{words(assessment.confidenceBand)}</strong><small className="mono">{assessment.score >= 0 ? '+' : ''}{assessment.score} / 1000</small></div>
        <div><span>Evidence</span><strong>{finding.artifactCount} sealed artifact{finding.artifactCount === 1 ? '' : 's'}</strong><small>Metadata visible; content sealed</small></div>
        <div><span>Provenance</span><strong>{finding.providerLabel}</strong><small className="mono">{displayTime(finding.updatedAtUs)}</small></div>
      </section>

      <div className="finding-detail-grid">
        <div className="finding-detail-grid__analysis">
          <AttributionPanel detail={detail} />
          <AttributionDecisionPanel detail={detail} onChanged={onChanged} />
          <Panel
            className="finding-actions-panel"
            eyebrow="Review boundary"
            title="Human judgment remains separate"
          >
            <div className="finding-actions-panel__body">
              <span className="status-icon status-icon--amber"><EyeOff size={15} /></span>
              <div>
                <strong>No attribution decision is inferred from the score</strong>
                <p>Evidence integrity, check outcome, visibility, confidence, and ownership remain separate dimensions.</p>
              </div>
            </div>
          </Panel>
          <RemediationCaseCreatePanel detail={detail} />
        </div>
        <div className="finding-detail-grid__evidence">
          <EvidenceArtifactPanel artifacts={detail.artifacts} />
          <ManualEvidenceImportPanel detail={detail} onChanged={onChanged} />
          <RedactedDerivativePanel detail={detail} onChanged={onChanged} />
        </div>
      </div>
    </>
  )
}

export function NativeFindingDetailPage() {
  const { findingId } = useParams()
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [result, setResult] = useState<{
    readonly profileId: string
    readonly findingId: string
    readonly detail: Phase5FindingDetail
  } | null>(null)
  const [errorKey, setErrorKey] = useState<string | null>(null)
  const [loadRevision, setLoadRevision] = useState(0)
  const activeKey = profileId === null || findingId === undefined
    ? null
    : `${profileId}:${findingId}`

  useEffect(() => {
    document.title = 'Finding detail · Codename Ariadne'
    if (profileId === null || findingId === undefined) return
    let cancelled = false
    setErrorKey(null)
    void loadPhase5Finding({ profileId, findingId })
      .then((detail) => {
        if (!cancelled) setResult({ profileId, findingId, detail })
      })
      .catch(() => {
        if (!cancelled) setErrorKey(`${profileId}:${findingId}`)
      })
    return () => {
      cancelled = true
    }
  }, [findingId, loadRevision, profileId])

  const activeResult =
    result?.profileId === profileId && result.findingId === findingId
      ? result.detail
      : null

  return (
    <div className="page finding-detail-page" data-testid="route-ready">
      <Link className="finding-detail__back" to="/findings">
        <ArrowLeft size={13} /> Back to findings
      </Link>

      {profileId === null ? (
        <>
          <PageHeader
            eyebrow="Persisted finding"
            title="Finding detail"
            description="A local audit profile is required before persisted evidence can be loaded."
          />
          <Phase5StatePanel
            state="no-profile"
            title="No active profile"
            detail="Create or resume a local audit profile. Native mode does not substitute a synthetic finding."
          />
        </>
      ) : findingId === undefined ? (
        <>
          <PageHeader
            eyebrow="Persisted finding"
            title="Finding detail"
            description="The requested finding identifier is missing."
          />
          <Phase5StatePanel
            state="not-found"
            title="Finding identifier is unavailable"
            detail="Return to the persisted findings inbox and select an available record."
          />
        </>
      ) : errorKey === activeKey ? (
        <>
          <PageHeader
            eyebrow="Persisted finding"
            title="Finding detail"
            description="The local core did not return a valid profile-bound finding."
          />
          <Phase5StatePanel
            state="error"
            title="Finding could not be loaded"
            detail="No partial record, synthetic fixture, evidence preview, or attribution score is being shown."
            onRetry={() => setLoadRevision((current) => current + 1)}
          />
        </>
      ) : activeResult === null ? (
        <>
          <PageHeader
            eyebrow="Persisted finding"
            title="Loading finding"
            description="Reading evidence and attribution metadata from the encrypted local vault."
          />
          <Phase5StatePanel
            state="loading"
            title="Loading persisted finding"
            detail="The native boundary is validating the complete response before rendering it."
          />
        </>
      ) : (
        <LoadedFindingDetail
          detail={activeResult}
          onChanged={() => setLoadRevision((current) => current + 1)}
        />
      )}
    </div>
  )
}
