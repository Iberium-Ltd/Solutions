import { useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  ClipboardCopy,
  EyeOff,
  FileSearch,
  FileWarning,
  Gauge,
  Import,
  Keyboard,
  LoaderCircle,
  MonitorCog,
  MousePointer2,
  Network,
  RefreshCw,
  SearchX,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  WifiOff,
} from 'lucide-react'
import { stateVariants } from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel, Progress } from '../components/Primitives'
import '../styles/pages-controls.css'

const stateCases = [
  { id: 'overview', label: 'Overview', icon: SlidersHorizontal, tone: 'cyan' as const, detail: 'State semantics and controls' },
  { id: 'empty', label: 'Empty', icon: SearchX, tone: 'blue' as const, detail: 'Scoped absence, safe next action' },
  { id: 'loading', label: 'Loading', icon: LoaderCircle, tone: 'cyan' as const, detail: 'Stable skeleton and busy label' },
  { id: 'failure', label: 'Failure', icon: FileWarning, tone: 'rose' as const, detail: 'Distinct provider outcomes' },
  { id: 'blocked', label: 'Blocked/manual', icon: ShieldAlert, tone: 'amber' as const, detail: 'Lawful fallback path' },
  { id: 'reduced-motion', label: 'Reduced motion', icon: Gauge, tone: 'violet' as const, detail: 'Static, complete rendering' },
  { id: 'long-identifier', label: 'Long identifiers', icon: Network, tone: 'green' as const, detail: 'Contained stress content' },
] as const

type StateCase = typeof stateCases[number]['id']

const isStateCase = (value: string | null): value is StateCase =>
  stateCases.some((item) => item.id === value)

function StateFrame({
  eyebrow,
  title,
  body,
  tone,
  icon,
  children,
}: {
  eyebrow: string
  title: string
  body: string
  tone: 'cyan' | 'blue' | 'rose' | 'amber' | 'violet' | 'green'
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <Panel className={`controls-state-specimen panel--raised controls-state-specimen--${tone}`}>
      <header className="controls-state-heading">
        <span className={`status-icon status-icon--${tone}`}>{icon}</span>
        <div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{body}</p></div>
      </header>
      {children}
    </Panel>
  )
}

function EmptySpecimen() {
  const copy = stateVariants.empty
  return (
    <StateFrame eyebrow={copy.eyebrow} title={copy.title} body={copy.body} tone="blue" icon={<SearchX size={20} aria-hidden="true" />}>
      <div className="controls-empty-layout">
        <div className="controls-empty-diagram" aria-hidden="true">
          <span><FileSearch size={18} /></span><i /><span><SlidersHorizontal size={18} /></span><i className="is-dashed" /><span><SearchX size={18} /></span>
        </div>
        <dl className="controls-empty-scope">
          <div><dt>Scope</dt><dd>Needs-review queue</dd></div>
          <div><dt>Filter</dt><dd>High confidence · unresolved</dd></div>
          <div><dt>Completed checks</dt><dd>142 of 186</dd></div>
          <div><dt>Coverage gaps</dt><dd>44 not checked, failed, or blocked</dd></div>
        </dl>
        <div className="controls-state-actions">
          <Button variant="primary">Start a synthetic trace</Button>
          <Button>Clear queue filters</Button>
        </div>
        <div className="controls-callout controls-callout--info">
          <CircleHelp size={16} aria-hidden="true" />
          <span>Empty means no rows match this review scope. It does not claim that no exposure exists.</span>
        </div>
      </div>
    </StateFrame>
  )
}

function LoadingSpecimen() {
  const copy = stateVariants.loading
  return (
    <StateFrame eyebrow={copy.eyebrow} title={copy.title} body={copy.body} tone="cyan" icon={<LoaderCircle className="controls-loading-icon" size={20} aria-hidden="true" />}>
      <div className="controls-loading-layout" aria-busy="true" aria-label="Loading reviewed identity graph locally">
        <div className="controls-loading-status" role="status">
          <span className="controls-static-spinner" aria-hidden="true" />
          <div><strong>Extracting reviewed nodes</strong><small>Step 2 of 4 · processing local fixture segments</small></div>
          <Badge tone="cyan">Local only</Badge>
        </div>
        <div className="controls-loading-structure">
          <div className="controls-skeleton-list">
            {[72, 88, 63, 81].map((width, index) => (
              <div key={width}>
                <span className="skeleton controls-skeleton-icon" />
                <span><i className="skeleton" style={{ inlineSize: `${width}%` }} /><i className="skeleton" style={{ inlineSize: `${45 + index * 6}%` }} /></span>
                <span className="skeleton controls-skeleton-badge" />
              </div>
            ))}
          </div>
          <div className="controls-skeleton-inspector">
            <span className="skeleton" />
            <span className="skeleton" />
            <span className="skeleton" />
            <div><span className="skeleton" /><span className="skeleton" /></div>
          </div>
        </div>
        <div className="controls-callout controls-callout--info">
          <MonitorCog size={16} aria-hidden="true" />
          <span>Final layout space is reserved. Skeletons contain no plausible identity values.</span>
        </div>
      </div>
    </StateFrame>
  )
}

function FailureSpecimen() {
  const copy = stateVariants.failure
  const failures = [
    { outcome: 'CHECK_FAILED', title: 'Archive lookup failed', cause: 'The response could not be normalised.', code: 'ARI-PROV-204', retained: '3 earlier results retained', tone: 'rose' as const, icon: FileWarning },
    { outcome: 'RATE_LIMITED', title: 'Search quota paused', cause: 'Provider retry window begins in 14 minutes.', code: 'ARI-PROV-429', retained: '8 completed checks retained', tone: 'amber' as const, icon: Gauge },
    { outcome: 'PROVIDER_UNAVAILABLE', title: 'Registry source unavailable', cause: 'Health check timed out within the bounded limit.', code: 'ARI-PROV-503', retained: 'Provider marked not checked', tone: 'blue' as const, icon: WifiOff },
  ]
  return (
    <StateFrame eyebrow={copy.eyebrow} title={copy.title} body={copy.body} tone="rose" icon={<FileWarning size={20} aria-hidden="true" />}>
      <div className="controls-failure-progress">
        <div><span>Retained run progress</span><strong>142 / 186 checks</strong></div>
        <Progress value={76} tone="rose" label="142 of 186 checks retained" />
        <small>Successful and reviewed work remains available while failed regions are retried.</small>
      </div>
      <div className="controls-failure-grid">
        {failures.map((failure) => {
          const Icon = failure.icon
          return (
            <article key={failure.outcome}>
              <div className="controls-failure-card__top">
                <span className={`status-icon status-icon--${failure.tone}`}><Icon size={16} /></span>
                <Badge tone={failure.tone}>{failure.outcome}</Badge>
              </div>
              <h3>{failure.title}</h3>
              <p>{failure.cause}</p>
              <dl><div><dt>Error code</dt><dd className="mono">{failure.code}</dd></div><div><dt>Prior work</dt><dd>{failure.retained}</dd></div></dl>
              <div><Button size="compact"><RefreshCw size={12} /> Retry safely</Button><Button size="compact" variant="ghost">Details</Button></div>
            </article>
          )
        })}
      </div>
      <div className="controls-callout controls-callout--danger">
        <AlertTriangle size={16} aria-hidden="true" />
        <span>Failed, rate-limited, and unavailable are distinct outcomes. None is evidence of absence.</span>
      </div>
    </StateFrame>
  )
}

function BlockedSpecimen() {
  const copy = stateVariants.blocked
  return (
    <StateFrame eyebrow={copy.eyebrow} title={copy.title} body={copy.body} tone="amber" icon={<ShieldAlert size={20} aria-hidden="true" />}>
      <div className="controls-blocked-layout">
        <section className="controls-blocked-summary">
          <div className="controls-boundary-visual" aria-hidden="true"><span>ARIADNE</span><i><Ban size={19} /></i><span>PROVIDER</span></div>
          <div>
            <Badge tone="amber">ACCESS_BLOCKED</Badge>
            <h3>Ordinary automated access stopped</h3>
            <p>The provider presented an interactive access boundary. No bypass, credential testing, or circumvention was attempted.</p>
          </div>
          <dl>
            <div><dt>Checked</dt><dd>Public landing response only</dd></div>
            <div><dt>Not checked</dt><dd>Profile content and image results</dd></div>
            <div><dt>Task state</dt><dd>MANUAL_REVIEW_REQUIRED</dd></div>
            <div><dt>Evidence</dt><dd>Boundary metadata retained</dd></div>
          </dl>
        </section>
        <section className="controls-manual-options" aria-labelledby="manual-options-heading">
          <h3 id="manual-options-heading">Lawful ways to continue</h3>
          <button type="button"><span className="status-icon status-icon--cyan"><MousePointer2 size={16} /></span><span><strong>Guided browser capture</strong><small>Open an ordinary browser and import only what you are authorised to view.</small></span><ChevronRight size={15} /></button>
          <button type="button"><span className="status-icon status-icon--violet"><Import size={16} /></span><span><strong>Import a local capture</strong><small>Add a user-provided screenshot or export with provenance.</small></span><ChevronRight size={15} /></button>
          <button type="button"><span className="status-icon"><Ban size={16} /></span><span><strong>Skip this provider</strong><small>Keep the task as ACCESS_BLOCKED in coverage.</small></span><ChevronRight size={15} /></button>
        </section>
      </div>
      <div className="controls-callout controls-callout--amber">
        <ShieldAlert size={16} aria-hidden="true" />
        <span>Manual capture is a transparent hand-off, not a method for evading a provider boundary.</span>
      </div>
    </StateFrame>
  )
}

function ReducedMotionSpecimen() {
  return (
    <StateFrame eyebrow="Reduced motion active" title="Every state remains understandable" body="Ambient pulses, scan sweeps, and edge flow are stopped. Progress, hierarchy, focus, and selection remain visible." tone="violet" icon={<Gauge size={20} aria-hidden="true" />}>
      <div className="controls-reduced-layout">
        <div className="controls-reduced-preview">
          <div className="controls-reduced-toolbar"><Badge tone="violet">STATIC LAYOUT</Badge><span>Graph specimen · 5 nodes · 4 edges</span><Badge tone="green">68% complete</Badge></div>
          <svg viewBox="0 0 680 250" role="img" aria-label="Static identity graph with five labelled nodes and four connections">
            <path d="M120 122 L280 65 L420 122 L565 60" />
            <path d="M280 65 L360 205 L420 122" />
            <g transform="translate(120 122)"><circle r="27" /><text y="4">Person</text></g>
            <g transform="translate(280 65)"><rect x="-38" y="-19" width="76" height="38" rx="7" /><text y="4">Handle</text></g>
            <g transform="translate(420 122)" className="is-selected"><rect x="-42" y="-20" width="84" height="40" rx="7" /><text y="4">Finding</text></g>
            <g transform="translate(565 60)"><rect x="-42" y="-19" width="84" height="38" rx="7" /><text y="4">Evidence</text></g>
            <g transform="translate(360 205)"><rect x="-38" y="-19" width="76" height="38" rx="7" /><text y="4">Source</text></g>
          </svg>
          <div className="controls-reduced-progress"><span>Correlation progress · 34 of 50 deterministic steps</span><Progress value={68} tone="violet" /></div>
        </div>
        <aside className="controls-reduced-checklist">
          <h3>Reduced behavior</h3>
          <ul>
            <li><CheckCircle2 size={14} /> Graph uses deterministic static positions</li>
            <li><CheckCircle2 size={14} /> Progress uses value and label, not animation</li>
            <li><CheckCircle2 size={14} /> Selection keeps a stable outline</li>
            <li><CheckCircle2 size={14} /> Keyboard and screen-reader alternatives remain</li>
          </ul>
          <Button><Keyboard size={13} /> Open graph table</Button>
        </aside>
      </div>
    </StateFrame>
  )
}

function LongIdentifierSpecimen() {
  const longUrl = 'https://profile.example.invalid/synthetic-segment-0001/synthetic-segment-0002/synthetic-segment-0003/synthetic-segment-0004'
  const longId = 'finding_syn_0000000000000000000000000000000000000000000000000000000000000000000000000000000000000001'
  const longHash = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  const longProvider = 'Synthetic Provider With A Deliberately Long Descriptive Display Name For Layout Testing'
  return (
    <StateFrame eyebrow="Overflow stress test" title="Long identifiers stay contained" body="URLs, hashes, provider names, and opaque IDs wrap or disclose within their component. Page actions remain reachable." tone="green" icon={<Network size={20} aria-hidden="true" />}>
      <div className="controls-long-layout">
        <section className="controls-long-record">
          <div className="controls-long-record__header"><Badge tone="green">FOUND</Badge><Badge tone="violet">Needs review</Badge><span className="mono">SYNTHETIC</span></div>
          <h3>{longProvider}</h3>
          <p>Stress fixture using a reserved host and opaque synthetic identifiers only.</p>
          <dl>
            <div><dt>Source URL</dt><dd><code>{longUrl}</code><Button size="compact" variant="ghost" aria-label="Copy synthetic source URL"><ClipboardCopy size={12} /></Button></dd></div>
            <div><dt>Finding ID</dt><dd><code>{longId}</code><Button size="compact" variant="ghost" aria-label="Copy synthetic finding ID"><ClipboardCopy size={12} /></Button></dd></div>
            <div><dt>SHA-256</dt><dd><code>{longHash}</code><Button size="compact" variant="ghost" aria-label="Copy synthetic evidence hash"><ClipboardCopy size={12} /></Button></dd></div>
          </dl>
          <details>
            <summary>Inspect complete identifiers</summary>
            <div><strong>Complete provider label</strong><code>{longProvider}</code><strong>Complete opaque reference</strong><code>{longId}</code></div>
          </details>
          <div className="controls-state-actions"><Button variant="primary">Open evidence</Button><Button>Add to review</Button><Button variant="ghost">More actions</Button></div>
        </section>
        <aside className="controls-overflow-audit">
          <h3>Containment audit</h3>
          <ul>
            <li><CheckCircle2 size={14} /><span><strong>URL</strong> wraps within record</span></li>
            <li><CheckCircle2 size={14} /><span><strong>Hash</strong> uses safe character wrapping</span></li>
            <li><CheckCircle2 size={14} /><span><strong>Provider</strong> remains fully inspectable</span></li>
            <li><CheckCircle2 size={14} /><span><strong>Actions</strong> stay in keyboard order</span></li>
          </ul>
          <div className="controls-callout controls-callout--success"><EyeOff size={15} /><span>No real host or personal identifier is present.</span></div>
        </aside>
      </div>
    </StateFrame>
  )
}

function OverviewSpecimen({ selectCase }: { selectCase: (value: StateCase) => void }) {
  return (
    <Panel className="controls-state-overview panel--raised" eyebrow="Component contract" title="Representative route states" action={<Badge tone="cyan">7 deterministic fixtures</Badge>}>
      <div className="controls-state-card-grid">
        {stateCases.filter((item) => item.id !== 'overview').map((item) => {
          const Icon = item.icon
          return (
            <button type="button" key={item.id} onClick={() => selectCase(item.id)}>
              <span className={`status-icon status-icon--${item.tone}`}><Icon size={17} /></span>
              <span><strong>{item.label}</strong><small>{item.detail}</small></span>
              <ChevronRight size={15} aria-hidden="true" />
            </button>
          )
        })}
      </div>
      <div className="controls-state-annotations">
        <article><Keyboard size={17} /><div><strong>Keyboard complete</strong><small>Native controls, logical order, visible focus, one route heading.</small></div></article>
        <article><EyeOff size={17} /><div><strong>Privacy safe</strong><small>Reserved hosts, synthetic IDs, masked values, no remote traffic.</small></div></article>
        <article><Sparkles size={17} /><div><strong>Motion optional</strong><small>Status and meaning never depend on animation or color alone.</small></div></article>
      </div>
    </Panel>
  )
}

export function StatesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedCase = searchParams.get('case')
  const activeCase: StateCase = isStateCase(requestedCase) ? requestedCase : 'overview'
  const [density, setDensity] = useState('comfortable')
  const [contrast, setContrast] = useState('standard')
  const [viewport, setViewport] = useState('route')

  const selectCase = (value: StateCase) => {
    const next = new URLSearchParams(searchParams)
    next.set('case', value)
    setSearchParams(next)
  }

  useEffect(() => {
    document.title = 'State Laboratory · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  useEffect(() => {
    if (activeCase !== 'reduced-motion') return
    const previous = document.documentElement.dataset.motion
    document.documentElement.dataset.motion = 'reduced'
    return () => {
      if (previous) document.documentElement.dataset.motion = previous
      else delete document.documentElement.dataset.motion
    }
  }, [activeCase])

  const specimen = activeCase === 'empty' ? <EmptySpecimen />
    : activeCase === 'loading' ? <LoadingSpecimen />
      : activeCase === 'failure' ? <FailureSpecimen />
        : activeCase === 'blocked' ? <BlockedSpecimen />
          : activeCase === 'reduced-motion' ? <ReducedMotionSpecimen />
            : activeCase === 'long-identifier' ? <LongIdentifierSpecimen />
              : <OverviewSpecimen selectCase={selectCase} />

  return (
    <div className="page controls-page states-page" data-testid="route-ready" data-state-case={activeCase} data-density={density} data-contrast={contrast}>
      <PageHeader
        eyebrow="Development route · Synthetic fixtures only"
        title="State laboratory"
        description="Inspect honest loading, empty, failure, blocked, motion, and overflow behavior without waiting for a transient network condition."
        meta={<><Badge tone="cyan" dot>Deterministic</Badge><Badge>No production data</Badge><Badge tone="violet">WCAG annotations</Badge></>}
      />

      <Panel className="controls-state-toolbar panel--raised" aria-label="State laboratory controls">
        <div className="controls-state-toolbar__case">
          <span>Specimen</span>
          <strong>{stateCases.find((item) => item.id === activeCase)?.label}</strong>
        </div>
        <label><span>Density</span><select value={density} onChange={(event) => setDensity(event.target.value)}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
        <label><span>Contrast</span><select value={contrast} onChange={(event) => setContrast(event.target.value)}><option value="standard">Standard</option><option value="increased">Increased</option></select></label>
        <label><span>Frame</span><select value={viewport} onChange={(event) => setViewport(event.target.value)}><option value="route">Route viewport</option><option value="1440">1440 × 900</option><option value="1100">1100 × 800</option></select></label>
        <Badge tone={activeCase === 'reduced-motion' ? 'violet' : 'green'}>{activeCase === 'reduced-motion' ? 'Motion reduced' : 'System motion'}</Badge>
      </Panel>

      <div className="controls-state-layout">
        <nav className="controls-state-selector" aria-label="State specimens">
          {stateCases.map((item) => {
            const Icon = item.icon
            return (
              <button type="button" key={item.id} className={activeCase === item.id ? 'is-active' : ''} onClick={() => selectCase(item.id)} aria-current={activeCase === item.id ? 'page' : undefined}>
                <span className={`status-icon status-icon--${item.tone}`}><Icon size={15} /></span>
                <span><strong>{item.label}</strong><small>{item.detail}</small></span>
              </button>
            )
          })}
        </nav>
        <div className={`controls-state-canvas controls-state-canvas--${viewport}`}>
          <div className="controls-state-canvas__label"><span>SPECIMEN / {activeCase.toUpperCase()}</span><span>SYNTHETIC · FROZEN</span></div>
          {specimen}
        </div>
      </div>
    </div>
  )
}

export default StatesPage
