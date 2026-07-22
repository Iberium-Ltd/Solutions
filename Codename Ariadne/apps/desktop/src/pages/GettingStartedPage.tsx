/** Short operational guide that separates the primary audit flow from optional tools. */
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  FileCheck2,
  FileInput,
  FileSearch,
  FlaskConical,
  HardDrive,
  ListChecks,
  Settings2,
} from 'lucide-react'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import { Badge, PageHeader, Panel } from '../components/Primitives'
import '../styles/pages-help.css'

const workflowSteps = [
  {
    number: '01',
    title: 'Create or unlock the vault',
    detail:
      'Use the Local vault card in the lower-left sidebar. First launch creates encrypted local storage; later launches unlock it.',
    icon: HardDrive,
  },
  {
    number: '02',
    title: 'Add source material in Intake',
    detail:
      'Paste text or choose a supported local file. Intake creates or resumes a local profile and extracts candidates for review.',
    icon: FileInput,
    to: '/audits/new/intake',
  },
  {
    number: '03',
    title: 'Review extracted entities',
    detail:
      'Confirm, reject, or edit the extracted identifiers before treating them as part of the profile.',
    icon: ListChecks,
    to: '/audits/new/entities',
  },
  {
    number: '04',
    title: 'Review findings and evidence',
    detail:
      'Findings is the persisted review queue. Open a finding to add local evidence and record your attribution decision.',
    icon: FileSearch,
    to: '/findings',
  },
  {
    number: '05',
    title: 'Compare, organise, and report',
    detail:
      'Create checkpoints in Compare Runs, organise follow-up in Removal Tracker, then generate a local JSON or Markdown report.',
    icon: FileCheck2,
    links: [
      ['/compare', 'Compare Runs'],
      ['/remediation', 'Removal Tracker'],
      ['/reports', 'Reports'],
    ] as const,
  },
] as const

const nativeScreens = [
  'Intake and Entity Review',
  'Link Map',
  'Findings and finding detail',
  'Compare Runs and Removal Tracker',
  'Reports',
  'Discovery Console',
  'AI Workspace with exact citations',
  'Corpus AI for cited multi-file analysis',
  'Local AI and privacy settings',
  'Transmission planning',
] as const

const syntheticScreens = [
  'Mission Control',
  'New Audit planner',
  'Operations console',
  'Geographic Map',
  'Case Desk',
  'Source Radar',
] as const

export function GettingStartedPage() {
  const native = nativeRuntimeAvailable()

  return (
    <div className="page getting-started-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Help · five-step workflow"
        title="Getting started"
        description="Follow the vault-backed path below for your own local records. Ariadne also contains clearly labelled synthetic demonstration screens that do not represent a live audit."
        meta={
          <Badge tone={native ? 'green' : 'amber'} dot>
            {native ? 'Native app' : 'Browser preview'}
          </Badge>
        }
      />

      {!native ? (
        <div className="getting-started__notice" role="note">
          <FlaskConical size={17} aria-hidden="true" />
          <div>
            <strong>You are viewing the browser prototype</strong>
            <span>
              It uses invented fixtures and cannot open the encrypted vault. Run
              the native macOS app for persisted Intake, Findings, Compare, and
              Reports.
            </span>
          </div>
        </div>
      ) : null}

      <section
        className="getting-started__workflow"
        aria-labelledby="workflow-title"
      >
        <div className="getting-started__section-heading">
          <span className="eyebrow">Recommended path</span>
          <h2 id="workflow-title">From source material to local report</h2>
        </div>
        <ol
          className="getting-started__steps"
          aria-label="Recommended Ariadne workflow"
        >
          {workflowSteps.map((step) => {
            const Icon = step.icon
            return (
              <li key={step.number}>
                <span className="getting-started__number">{step.number}</span>
                <span className="getting-started__icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.detail}</p>
                  {'to' in step ? (
                    <Link to={step.to}>
                      Open {step.title.replace(/^Add source material in |^Review extracted /, '')}
                      <ArrowRight size={14} aria-hidden="true" />
                    </Link>
                  ) : 'links' in step ? (
                    <span className="getting-started__links">
                      {step.links.map(([to, label]) => (
                        <Link to={to} key={to}>
                          {label}
                        </Link>
                      ))}
                    </span>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ol>
      </section>

      <div className="getting-started__screen-map">
        <Panel
          className="getting-started__screen-panel getting-started__screen-panel--native"
          eyebrow="Reads your encrypted workspace"
          title="Native vault-backed screens"
          action={<HardDrive size={17} aria-hidden="true" />}
        >
          <ul>
            {nativeScreens.map((screen) => (
              <li key={screen}>
                <FileCheck2 size={13} aria-hidden="true" />
                {screen}
              </li>
            ))}
          </ul>
        </Panel>
        <Panel
          className="getting-started__screen-panel getting-started__screen-panel--synthetic"
          eyebrow="Exploration only"
          title="Synthetic demonstration screens"
          action={<FlaskConical size={17} aria-hidden="true" />}
        >
          <ul>
            {syntheticScreens.map((screen) => (
              <li key={screen}>
                <FlaskConical size={13} aria-hidden="true" />
                {screen}
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <section className="getting-started__next" aria-labelledby="next-title">
        <Settings2 size={20} aria-hidden="true" />
        <div>
          <h2 id="next-title">Want local AI summaries?</h2>
          <p>
            After unlocking the vault, open Privacy &amp; Settings to select a
            local provider and model. Ariadne only enables models reported by
            the configured loopback service.
          </p>
        </div>
        <Link className="button button--secondary" to="/ai/workspace">
          Open AI Workspace
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </section>
    </div>
  )
}
