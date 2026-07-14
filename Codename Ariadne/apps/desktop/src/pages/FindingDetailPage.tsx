import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Archive,
  ArrowLeft,
  Check,
  CheckCircle2,
  Copy,
  Download,
  Eye,
  EyeOff,
  Fingerprint,
  GitBranch,
  History,
  Link2,
  LockKeyhole,
  Scale,
  ShieldCheck,
  TriangleAlert,
  UserCheck,
  XCircle,
} from 'lucide-react'
import {
  attributionSignals,
  evidenceRecord,
  findings,
} from '@ariadne/synthetic-data'
import {
  Badge,
  Button,
  DefinitionList,
  PageHeader,
  Panel,
  type Tone,
} from '../components/Primitives'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { NativeFindingDetailPage } from './Phase5FindingDetail'
import '../styles/pages-results.css'

type Finding = (typeof findings)[number]

const outcomeTone: Record<Finding['outcome'], Tone> = {
  FOUND: 'green',
  AMBIGUOUS: 'violet',
  MANUAL_REVIEW_REQUIRED: 'amber',
}

function confidenceBand(score: number) {
  if (!score) return 'Unresolved'
  if (score >= 85) return 'High confidence'
  if (score >= 60) return 'Moderate confidence'
  return 'Low confidence'
}

function SimulatedFindingDetailPage() {
  const { findingId } = useParams()
  const finding =
    findings.find((candidate) => candidate.id === findingId) ?? findings[0]
  const [previewRevealed, setPreviewRevealed] = useState(false)
  const [hashCopied, setHashCopied] = useState(false)
  const [decision, setDecision] = useState<'probable' | 'non-match' | null>(null)

  const host = new URL(finding.url).host
  const positiveSignals = attributionSignals.filter((signal) => signal.tone === 'positive').length
  const contradictingSignals = attributionSignals.filter((signal) => signal.tone === 'negative').length
  const missingSignals = attributionSignals.filter((signal) => signal.tone === 'missing').length

  const copyHash = () => {
    void navigator.clipboard?.writeText(evidenceRecord.hash)
    setHashCopied(true)
  }

  return (
    <div className="page finding-detail-page" data-testid="route-ready">
      <Link className="finding-detail__back" to="/findings">
        <ArrowLeft size={13} /> Back to findings
      </Link>

      <PageHeader
        eyebrow={`Finding detail · ${findingId ?? finding.id}`}
        title={finding.title}
        description={finding.summary}
        meta={
          <>
            <Badge tone={outcomeTone[finding.outcome]} dot>{finding.outcome}</Badge>
            <Badge tone="blue">{finding.visibility}</Badge>
            <Badge tone="violet">{decision === 'non-match' ? 'Non-match · human decision' : finding.ownership}</Badge>
            <Badge>{confidenceBand(finding.confidence)}</Badge>
          </>
        }
        actions={
          <>
            <Button variant="secondary"><Archive size={14} /> Preserve evidence</Button>
            <Button variant="primary"><GitBranch size={14} /> Open in Link Map</Button>
          </>
        }
      />

      <section className="finding-dimensions" aria-label="Independent finding dimensions">
        <div><span>Check outcome</span><strong>{finding.outcome}</strong><small>One defined synthetic check</small></div>
        <div><span>Exposure</span><strong>{finding.visibility}</strong><small>Observed at capture time</small></div>
        <div><span>Attribution</span><strong>{decision === 'non-match' ? 'Non-match' : finding.ownership}</strong><small>Human review remains decisive</small></div>
        <div><span>Confidence</span><strong>{confidenceBand(finding.confidence)}</strong><small>{positiveSignals} support · {contradictingSignals} contradict · {missingSignals} missing</small></div>
        <div><span>Sensitivity</span><strong>Sensitive</strong><small>Redacted by default</small></div>
        <div><span>Provenance</span><strong>{finding.source}</strong><small className="mono">11 Jul 2026 · 14:36 UTC</small></div>
      </section>

      <div className="finding-detail-grid">
        <div className="finding-detail-grid__analysis">
          <Panel
            className="attribution-panel panel--raised"
            eyebrow="Attribution assessment"
            title="Why this may be connected"
            action={<Badge tone="violet">Model v1 · explainable</Badge>}
          >
            <div className="attribution-summary">
              <span className="status-icon status-icon--violet"><UserCheck size={16} /></span>
              <div>
                <strong>{decision ? `Decision recorded: ${decision === 'probable' ? 'probable match' : 'non-match'}` : 'Probable match · unresolved by automation'}</strong>
                <p>The uncommon synthetic handle and project reference support a connection. An incomplete chronology and missing authorised image comparison prevent a confirmed attribution.</p>
              </div>
              <span className="attribution-summary__score mono">{finding.confidence}<small>/ 100</small></span>
            </div>
            <div className="signal-list" aria-label="Attribution signals">
              {attributionSignals.map((signal) => {
                const tone = signal.tone === 'positive'
                  ? 'positive'
                  : signal.tone === 'negative'
                    ? 'negative'
                    : 'missing'
                return (
                  <article className={`signal-row signal-row--${tone}`} key={signal.label}>
                    <span className="signal-row__icon">
                      {tone === 'positive' ? <CheckCircle2 size={14} /> : tone === 'negative' ? <XCircle size={14} /> : <TriangleAlert size={14} />}
                    </span>
                    <div><strong>{signal.label}</strong><small>{signal.detail}</small></div>
                    <b className="mono">{signal.weight}</b>
                  </article>
                )
              })}
            </div>
            <div className="attribution-decision">
              <div>
                <strong>Human attribution decision</strong>
                <span>Automation never makes an identity accusation.</span>
              </div>
              <div>
                <Button
                  variant={decision === 'probable' ? 'primary' : 'secondary'}
                  size="compact"
                  onClick={() => setDecision('probable')}
                >
                  Probable match
                </Button>
                <Button
                  variant={decision === 'non-match' ? 'primary' : 'ghost'}
                  size="compact"
                  onClick={() => setDecision('non-match')}
                >
                  Mark non-match
                </Button>
              </div>
            </div>
          </Panel>

          <Panel
            className="provenance-panel"
            eyebrow="Normalised provenance"
            title="Source and capture chain"
          >
            <ol className="provenance-chain">
              <li>
                <span><Link2 size={14} /></span>
                <div><strong>Provider result normalised</strong><small>{finding.source} · simulated response</small></div>
                <time className="mono">14:35:58</time>
              </li>
              <li>
                <span><Archive size={14} /></span>
                <div><strong>Immutable artifact created</strong><small>Original synthetic capture retained</small></div>
                <time className="mono">14:36:22</time>
              </li>
              <li>
                <span><Fingerprint size={14} /></span>
                <div><strong>Content hash verified</strong><small>Integrity checked locally; claim not verified</small></div>
                <time className="mono">14:36:23</time>
              </li>
            </ol>
          </Panel>
        </div>

        <div className="finding-detail-grid__evidence">
          <Panel
            className="evidence-panel panel--raised"
            eyebrow="Immutable evidence"
            title="Captured source preview"
            action={<Badge tone="green"><ShieldCheck size={11} /> Hash verified</Badge>}
          >
            <div className="evidence-preview">
              <div className="evidence-preview__bar">
                <span aria-hidden="true"><i /><i /><i /></span>
                <div><LockKeyhole size={11} /> {host}</div>
                <Badge tone="blue">Synthetic capture</Badge>
              </div>
              <div className={previewRevealed ? 'evidence-preview__content is-revealed' : 'evidence-preview__content'}>
                <div className="evidence-preview__avatar" aria-hidden="true" />
                <div className="evidence-preview__lines" aria-hidden="true">
                  <i /><i /><i /><i />
                </div>
                {previewRevealed ? (
                  <div className="evidence-preview__reveal">
                    <strong>{finding.title}</strong>
                    <span>{finding.summary}</span>
                    <small>{finding.url}</small>
                  </div>
                ) : (
                  <div className="evidence-preview__redaction">
                    <EyeOff size={22} />
                    <strong>Sensitive preview redacted</strong>
                    <span>Reveal applies only to this local session.</span>
                  </div>
                )}
              </div>
              <div className="evidence-preview__actions">
                <Button
                  variant={previewRevealed ? 'ghost' : 'secondary'}
                  size="compact"
                  onClick={() => setPreviewRevealed((current) => !current)}
                >
                  {previewRevealed ? <EyeOff size={12} /> : <Eye size={12} />}
                  {previewRevealed ? 'Hide preview' : 'Reveal locally'}
                </Button>
                <Button variant="ghost" size="compact"><Download size={12} /> Redacted copy</Button>
              </div>
            </div>

            <div className="evidence-integrity callout callout--success">
              <Fingerprint size={15} />
              <span><strong>Artifact integrity verified.</strong> This confirms the local artifact has not changed; it does not prove the source claim or identity attribution.</span>
            </div>

            <DefinitionList
              items={[
                ['Evidence ID', <span className="mono" key="id">{evidenceRecord.id}</span>],
                ['Source URL', <span className="mono wrap-anywhere" key="url">{finding.url}</span>],
                ['Captured (UTC)', <span className="mono" key="captured">{evidenceRecord.capturedAt}</span>],
                ['HTTP / redirects', `${evidenceRecord.httpStatus} · ${evidenceRecord.redirectCount} redirect`],
                ['Viewport', <span className="mono" key="viewport">{evidenceRecord.viewport}</span>],
                ['Method', evidenceRecord.method],
                ['Encryption', evidenceRecord.encryption],
              ]}
            />

            <div className="evidence-hash">
              <div><span>SHA-256</span><Badge tone="green">Verified locally</Badge></div>
              <code
                role="region"
                aria-label="Complete SHA-256 evidence hash"
                tabIndex={0}
              >
                {evidenceRecord.hash}
              </code>
              <Button variant="ghost" size="compact" onClick={copyHash}>
                {hashCopied ? <Check size={12} /> : <Copy size={12} />}
                {hashCopied ? 'Copied' : 'Copy full hash'}
              </Button>
            </div>
          </Panel>

          <Panel
            className="finding-actions-panel"
            eyebrow="Next safe action"
            title="Review and remediation"
          >
            <div className="finding-actions-panel__body">
              <span className="status-icon status-icon--amber"><Scale size={15} /></span>
              <div>
                <strong>No request will be sent automatically</strong>
                <p>Preserve the evidence, resolve attribution, then prepare a reviewable correction or removal draft.</p>
              </div>
            </div>
            <div className="finding-actions-panel__buttons">
              <Button variant="secondary" size="compact"><History size={12} /> Add to monitor</Button>
              <Button variant="ghost" size="compact">Prepare draft</Button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

export function FindingDetailPage() {
  return nativeRuntimeAvailable() ? (
    <NativeFindingDetailPage />
  ) : (
    <SimulatedFindingDetailPage />
  )
}
