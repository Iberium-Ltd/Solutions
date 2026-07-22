/** Local report generation with redacted default and approval-gated full output. */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Clipboard, Download, FileText, ShieldAlert } from 'lucide-react'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { loadPhase6AuditRuns, type Phase6AuditRunSummary } from '../app/phase6Boundary'
import {
  generateLocalReport,
  type LocalReportFormat,
  type LocalReportMode,
  type LocalReportResult,
} from '../app/reportingBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Phase6StatePanel } from '../components/Phase6StatePanel'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import '../styles/pages-reporting.css'

function runLabel(run: Phase6AuditRunSummary) {
  const captured = new Date(Math.floor(run.capturedAtUs / 1_000))
  return `Checkpoint ${run.sequence} · ${captured.toLocaleString()} · ${run.findingCount} findings`
}

function saveArtifact(report: LocalReportResult) {
  const blob = new Blob([report.artifact.content], {
    type: report.artifact.mediaType,
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = report.artifact.filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

function NativeReportsPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [runs, setRuns] = useState<ReadonlyArray<Phase6AuditRunSummary> | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [loadRevision, setLoadRevision] = useState(0)
  const [baselineRunId, setBaselineRunId] = useState('')
  const [currentRunId, setCurrentRunId] = useState('')
  const [format, setFormat] = useState<LocalReportFormat>('MARKDOWN')
  const [mode, setMode] = useState<LocalReportMode>('REDACTED')
  const [fullApproved, setFullApproved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<LocalReportResult | null>(null)
  const [generationFailed, setGenerationFailed] = useState(false)

  useEffect(() => {
    if (profileId === null) return
    let cancelled = false
    setLoadFailed(false)
    setRuns(null)
    void loadPhase6AuditRuns({ profileId, limit: 32 })
      .then((result) => {
        if (!cancelled) setRuns(result.runs)
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [loadRevision, profileId])

  const sortedRuns = useMemo(
    () => [...(runs ?? [])].sort((left, right) => right.sequence - left.sequence),
    [runs],
  )

  useEffect(() => {
    if (sortedRuns.length < 2) return
    const ids = new Set(sortedRuns.map((run) => run.runId))
    if (!ids.has(currentRunId)) setCurrentRunId(sortedRuns[0].runId)
    if (!ids.has(baselineRunId) || baselineRunId === sortedRuns[0].runId) {
      setBaselineRunId(sortedRuns[1].runId)
    }
  }, [baselineRunId, currentRunId, sortedRuns])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      profileId === null ||
      baselineRunId === '' ||
      currentRunId === '' ||
      baselineRunId === currentRunId ||
      busy ||
      (mode === 'FULL_EXPLICIT' && !fullApproved)
    ) {
      return
    }
    setBusy(true)
    setGenerationFailed(false)
    setReport(null)
    try {
      setReport(
        await generateLocalReport({
          profileId,
          baselineRunId,
          currentRunId,
          artifactFormat: format,
          mode,
          fullExportApprovalId:
            mode === 'FULL_EXPLICIT' ? crypto.randomUUID() : null,
        }),
      )
    } catch {
      setGenerationFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page reports-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Local reporting · Selected snapshots"
        title="Reports"
        description="Generate deterministic JSON or Markdown from persisted findings, comparison coverage, and remediation history. Nothing is uploaded or sent."
        meta={
          <>
            <Badge tone="green" dot>Native vault</Badge>
            <Badge tone="cyan">1 MiB bounded artifact</Badge>
            <Badge tone="violet">Evidence content excluded</Badge>
          </>
        }
      />

      {profileId === null ? (
        <Phase6StatePanel state="no-profile" title="No active profile" detail="Create or resume a local profile before generating a report." />
      ) : loadFailed ? (
        <Phase6StatePanel state="error" title="Report inputs are unavailable" detail="The local core did not return a valid profile-bound snapshot list." onRetry={() => setLoadRevision((current) => current + 1)} />
      ) : runs === null ? (
        <Phase6StatePanel state="loading" title="Loading report inputs" detail="Reading bounded snapshot metadata from the encrypted local vault." />
      ) : sortedRuns.length < 2 ? (
        <Phase6StatePanel state="insufficient" title="Two checkpoints are required" detail="Create at least two local checkpoints on Compare Runs before generating a lifecycle report." />
      ) : (
        <>
          <Panel className="reports-builder panel--raised" eyebrow="Export builder" title="Choose scope and privacy mode" action={<Badge tone="cyan">Local only</Badge>}>
            <form className="reports-form" onSubmit={(event) => void submit(event)}>
              <label className="field">
                <span>Baseline checkpoint</span>
                <select className="select" value={baselineRunId} disabled={busy} onChange={(event) => { setBaselineRunId(event.target.value); setReport(null) }}>
                  {sortedRuns.filter((run) => run.runId !== currentRunId).map((run) => <option key={run.runId} value={run.runId}>{runLabel(run)}</option>)}
                </select>
              </label>
              <label className="field">
                <span>Current checkpoint</span>
                <select className="select" value={currentRunId} disabled={busy} onChange={(event) => { setCurrentRunId(event.target.value); setReport(null) }}>
                  {sortedRuns.filter((run) => run.runId !== baselineRunId).map((run) => <option key={run.runId} value={run.runId}>{runLabel(run)}</option>)}
                </select>
              </label>
              <div className="reports-form__options">
                <label className="field">
                  <span>Artifact</span>
                  <select className="select" value={format} disabled={busy} onChange={(event) => { setFormat(event.target.value as LocalReportFormat); setReport(null) }}>
                    <option value="MARKDOWN">Markdown</option>
                    <option value="JSON">Canonical JSON</option>
                  </select>
                </label>
                <label className="field">
                  <span>Privacy mode</span>
                  <select className="select" value={mode} disabled={busy} onChange={(event) => { const next = event.target.value as LocalReportMode; setMode(next); setFullApproved(false); setReport(null) }}>
                    <option value="REDACTED">Redacted</option>
                    <option value="FULL_EXPLICIT">Full · explicit approval</option>
                  </select>
                </label>
              </div>
              {mode === 'FULL_EXPLICIT' ? (
                <label className="reports-full-approval">
                  <input type="checkbox" checked={fullApproved} disabled={busy} onChange={(event) => setFullApproved(event.target.checked)} />
                  <ShieldAlert size={16} aria-hidden="true" />
                  <span><strong>Include sensitive local text</strong><small>I understand this artifact may reveal finding, provider, evidence-metadata, and remediation details.</small></span>
                </label>
              ) : (
                <div className="reports-redaction-note"><ShieldAlert size={15} aria-hidden="true" /><span>IDs and URLs are deterministically remapped; free text and metadata values are replaced.</span></div>
              )}
              {generationFailed ? <div className="callout callout--danger" role="alert">The report was not generated. Reload the snapshot pair if it changed, then retry.</div> : null}
              <div className="reports-form__actions">
                <span>No evidence bytes, network request, or active content.</span>
                <Button type="submit" disabled={busy || (mode === 'FULL_EXPLICIT' && !fullApproved)}><FileText size={14} /> {busy ? 'Generating…' : 'Generate report'}</Button>
              </div>
            </form>
          </Panel>

          {report ? <ReportPreview report={report} /> : null}
        </>
      )}
    </div>
  )
}

function ReportPreview({ report }: { readonly report: LocalReportResult }) {
  const previewLimit = 20_000
  const preview = report.artifact.content.slice(0, previewLimit)
  const truncated = preview.length < report.artifact.content.length
  const [copied, setCopied] = useState(false)
  return (
    <Panel className="reports-preview panel--raised" eyebrow="Generated artifact" title={report.artifact.filename} action={<Badge tone={report.artifact.mode === 'REDACTED' ? 'green' : 'amber'}>{report.artifact.mode === 'REDACTED' ? 'Redacted' : 'Full explicit'}</Badge>}>
      <div className="reports-preview__meta">
        <span className="mono">{report.artifact.byteCount.toLocaleString()} bytes</span>
        <span className="mono">SHA-256 {report.artifact.sha256}</span>
        <span>{new Date(Math.floor(report.manifest.generatedAtUs / 1_000)).toLocaleString()}</span>
      </div>
      <pre>{preview}{truncated ? '\n\n[Preview truncated; saved artifact remains complete.]' : ''}</pre>
      <div className="reports-preview__actions">
        <Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(report.artifact.content).then(() => setCopied(true)).catch(() => setCopied(false)) }}><Clipboard size={14} /> {copied ? 'Copied' : 'Copy full artifact'}</Button>
        <Button onClick={() => saveArtifact(report)}><Download size={14} /> Save local file</Button>
      </div>
    </Panel>
  )
}

function BrowserReportsPage() {
  return (
    <div className="page reports-page" data-testid="route-ready">
      <PageHeader eyebrow="Local reporting" title="Reports" description="Report generation reads the encrypted native vault and is unavailable in browser-only preview mode." meta={<Badge tone="amber">Native app required</Badge>} />
      <Phase6StatePanel state="insufficient" title="Open the native app to generate reports" detail="Browser preview does not fabricate export artifacts or substitute synthetic report content." />
    </div>
  )
}

export function ReportsPage() {
  return nativeRuntimeAvailable() ? <NativeReportsPage /> : <BrowserReportsPage />
}

export default ReportsPage
