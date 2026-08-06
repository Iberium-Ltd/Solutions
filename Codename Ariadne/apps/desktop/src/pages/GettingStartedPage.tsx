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
    title: 'Create or select the person profile',
    detail:
      'Give the profile a clear name or resume an existing person. Choose and load an Ollama or LM Studio model here if AI should assist the run.',
    icon: FileInput,
    to: '/audits/new',
  },
  {
    number: '03',
    title: 'Import and review identifiers',
    detail:
      'Paste natural-language clues or choose a supported file. Deterministic extraction runs first; the selected local model can suggest additional identifiers before one review step.',
    icon: ListChecks,
    to: '/audits/new/intake',
  },
  {
    number: '04',
    title: 'Run the complete identity audit',
    detail:
      'People starts the bounded provider frontier with your depth and request budget. Progress, ETA, provider actions, exact URLs, and failures are persisted while you navigate.',
    icon: FileSearch,
    to: '/people',
  },
  {
    number: '05',
    title: 'Review cited AI analysis and export',
    detail:
      'Load the selected model if needed, review its source-cited facts and connections, resolve proposals, then generate the final local Markdown or JSON package.',
    icon: FileCheck2,
    links: [
      ['/ai/workspace', 'AI Workspace'],
      ['/graph', 'Link Map'],
      ['/reports', 'Reports'],
    ] as const,
  },
] as const

const nativeScreens = [
  'Mission Control and People',
  'Intake and entity review',
  'Operations and findings',
  'Link Map and Geographic Map',
  'Case Desk and reports',
  'Discovery Console',
  'AI Workspace with exact citations',
  'Corpus AI for cited multi-file analysis',
  'Source Coverage and Transmission Preflight',
  'Compare Runs and Removal Tracker',
] as const

const syntheticScreens = [
  'Browser-only fixture previews',
  'State laboratory',
] as const

export function GettingStartedPage() {
  const native = nativeRuntimeAvailable()

  return (
    <div className="page getting-started-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Help · five-step workflow"
        title="Getting started"
        description="Follow the vault-backed path below for your own local records. Native screens remain empty until your first audit supplies persisted data."
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
          eyebrow="Outside the native app"
          title="Browser-only demonstration surfaces"
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
