/** Prototype presentation of impersonation signals and locally drafted actions. */
import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  CircleHelp,
  FilePenLine,
  Plus,
  Save,
  Scale,
  ShieldAlert,
} from 'lucide-react'
import {
  impersonationTimeline,
  syntheticProfile,
} from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import '../styles/pages-controls.css'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { NativeCaseDeskPage } from './NativeCaseDeskPage'

type Classification =
  | 'Unresolved'
  | 'Possible impersonation'
  | 'Coincidental collision'
  | 'Recycled username'

const identifierRows = [
  {
    field: 'Display name',
    reviewed: syntheticProfile.name,
    observed: 'M. Vale Studio',
    assessment: 'Partial overlap',
    tone: 'amber' as const,
  },
  {
    field: 'Username',
    reviewed: `@${syntheticProfile.username}`,
    observed: `@${syntheticProfile.username}`,
    assessment: 'Exact text · ownership unknown',
    tone: 'violet' as const,
  },
  {
    field: 'Contact',
    reviewed: 'm•••••@example.invalid',
    observed: 'Not published',
    assessment: 'Not comparable',
    tone: 'neutral' as const,
  },
  {
    field: 'Immutable account ID',
    reviewed: 'Not available',
    observed: 'Not captured',
    assessment: 'Evidence gap',
    tone: 'rose' as const,
  },
] as const

const evidenceGroups = [
  {
    title: 'Supporting signals',
    tone: 'green' as const,
    icon: CheckCircle2,
    items: [
      'Exact historical handle appears on the observed profile.',
      'A fictional project label overlaps with reviewed material.',
    ],
  },
  {
    title: 'Contradictions',
    tone: 'rose' as const,
    icon: AlertTriangle,
    items: [
      'Writing style and activity region do not align.',
      'Observed activity begins after the stated ownership period.',
    ],
  },
  {
    title: 'Missing evidence',
    tone: 'amber' as const,
    icon: CircleHelp,
    items: [
      'No immutable account identifier has been preserved.',
      'No authorised image comparison has been performed.',
    ],
  },
] as const

function SimulatedImpersonationPage() {
  const [classification, setClassification] =
    useState<Classification>('Unresolved')
  const [rationale, setRationale] = useState('')
  const [periodAdded, setPeriodAdded] = useState(false)
  const [draftPrepared, setDraftPrepared] = useState(false)

  useEffect(() => {
    document.title = 'Case Desk · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  const saveDecision = () => {
    if (classification === 'Unresolved') return
    setDraftPrepared(false)
  }

  return (
    <div
      className="page controls-page impersonation-page"
      data-testid="route-ready"
    >
      <PageHeader
        eyebrow="Case Desk · CASE-SYN-0003"
        title="Unresolved identity claim"
        description="Compare ownership, activity, and evidence without turning overlap into an accusation. Classification remains a recorded human decision."
        meta={
          <>
            <Badge tone="violet" dot>{classification}</Badge>
            <Badge tone="amber">2 evidence gaps</Badge>
            <Badge>Opened 11 Jul 2026 · synthetic</Badge>
          </>
        }
        actions={
          <>
            <Button onClick={() => setDraftPrepared(true)}>
              <FilePenLine size={15} aria-hidden="true" />
              Prepare draft
            </Button>
            <Button
              variant="primary"
              onClick={saveDecision}
              disabled={classification === 'Unresolved' || !rationale.trim()}
            >
              <Save size={15} aria-hidden="true" />
              Save decision
            </Button>
          </>
        }
      />

      <div className="controls-safety-band" role="note">
        <ShieldAlert size={18} aria-hidden="true" />
        <div>
          <strong>No automatic accusation</strong>
          <span>
            Similar identifiers can indicate prior ownership, recycling, a mirror,
            or coincidence. This prototype never submits a report.
          </span>
        </div>
        <Badge tone="cyan">Draft only</Badge>
      </div>

      {draftPrepared && (
        <div className="controls-inline-notice" role="status">
          <FilePenLine size={16} aria-hidden="true" />
          <span>
            Draft workspace prepared locally. It contains uncertainty and coverage
            limitations; no external action is available in Phase 1.
          </span>
          <Button size="compact" variant="ghost" onClick={() => setDraftPrepared(false)}>
            Dismiss
          </Button>
        </div>
      )}

      <div className="controls-case-grid">
        <Panel
          className="controls-case-timeline panel--raised"
          eyebrow="Ownership & activity"
          title="Timeline"
          action={<Badge tone="cyan"><CalendarRange size={12} /> 4 events</Badge>}
        >
          <ol className="controls-timeline">
            {impersonationTimeline.map((event, index) => (
              <li key={event.date + event.title}>
                <div className="controls-timeline__rail" aria-hidden="true">
                  <span className={index === 3 ? 'is-current' : ''} />
                </div>
                <time>{event.date}</time>
                <div>
                  <strong>{event.title}</strong>
                  <p>{event.detail}</p>
                  <small>
                    {index < 2 ? 'User-stated ownership period' : 'Observed account activity'}
                  </small>
                </div>
              </li>
            ))}
            {periodAdded && (
              <li className="is-added">
                <div className="controls-timeline__rail" aria-hidden="true"><span /></div>
                <time>2023–24</time>
                <div>
                  <strong>Added ownership period</strong>
                  <p>Synthetic interval saved as user-stated, pending corroboration.</p>
                  <small>User decision · not independent evidence</small>
                </div>
              </li>
            )}
          </ol>
          <div className="controls-panel-footer">
            <Button size="compact" onClick={() => setPeriodAdded((value) => !value)}>
              <Plus size={13} aria-hidden="true" />
              {periodAdded ? 'Remove added period' : 'Add ownership period'}
            </Button>
            <span>Dates may be approximate and are labelled by origin.</span>
          </div>
        </Panel>

        <Panel
          className="controls-case-compare panel--raised"
          eyebrow="Identity claim"
          title="Identifier comparison"
          action={<Badge tone="amber">Needs corroboration</Badge>}
        >
          <div className="controls-identity-summary">
            <div>
              <span>Reviewed synthetic profile</span>
              <strong>{syntheticProfile.name}</strong>
              <small>{syntheticProfile.organisation} · {syntheticProfile.location}</small>
            </div>
            <Scale size={20} aria-hidden="true" />
            <div>
              <span>Observed claim</span>
              <strong>M. Vale Studio</strong>
              <small>Public profile · source.example.invalid</small>
            </div>
          </div>
          <div className="controls-table-scroll" role="region" aria-label="Identifier comparison table" tabIndex={0}>
            <table className="data-table controls-compare-table">
              <caption className="sr-only">
                Reviewed and observed identifiers with independent assessments
              </caption>
              <thead>
                <tr>
                  <th scope="col">Identifier</th>
                  <th scope="col">Reviewed</th>
                  <th scope="col">Observed</th>
                  <th scope="col">Assessment</th>
                </tr>
              </thead>
              <tbody>
                {identifierRows.map((row) => (
                  <tr key={row.field}>
                    <th scope="row">{row.field}</th>
                    <td className="mono">{row.reviewed}</td>
                    <td className="mono">{row.observed}</td>
                    <td><Badge tone={row.tone}>{row.assessment}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="controls-callout controls-callout--amber">
            <CircleHelp size={16} aria-hidden="true" />
            <span>
              A matching username is not sufficient attribution. Preserve an
              immutable account ID or historical account export before deciding.
            </span>
          </div>
        </Panel>
      </div>

      <div className="controls-evidence-grid">
        {evidenceGroups.map((group) => {
          const Icon = group.icon
          return (
            <Panel key={group.title} className="controls-evidence-panel">
              <div className="controls-evidence-panel__heading">
                <span className={`status-icon status-icon--${group.tone}`}>
                  <Icon size={15} aria-hidden="true" />
                </span>
                <div>
                  <h2>{group.title}</h2>
                  <small>{group.items.length} recorded observations</small>
                </div>
              </div>
              <ul>
                {group.items.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </Panel>
          )
        })}
      </div>

      <Panel
        className="controls-decision-panel"
        eyebrow="Human classification"
        title="Record a careful conclusion"
        action={<Badge tone={classification === 'Unresolved' ? 'violet' : 'cyan'}>{classification}</Badge>}
      >
        <div className="controls-decision-layout">
          <div className="field">
            <label htmlFor="case-classification">Classification</label>
            <select
              id="case-classification"
              className="select"
              value={classification}
              onChange={(event) => setClassification(event.target.value as Classification)}
            >
              <option>Unresolved</option>
              <option>Possible impersonation</option>
              <option>Coincidental collision</option>
              <option>Recycled username</option>
            </select>
            <small>“Confirmed impersonation” is unavailable until required evidence is present.</small>
          </div>
          <div className="field controls-rationale-field">
            <label htmlFor="case-rationale">Decision rationale</label>
            <textarea
              id="case-rationale"
              className="textarea"
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              placeholder="Explain supporting evidence, contradictions, and remaining uncertainty…"
            />
          </div>
        </div>
      </Panel>
    </div>
  )
}

export function ImpersonationPage() {
  return nativeRuntimeAvailable() ? <NativeCaseDeskPage /> : <SimulatedImpersonationPage />
}

export default ImpersonationPage
