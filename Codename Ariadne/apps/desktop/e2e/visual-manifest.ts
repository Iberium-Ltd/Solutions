/**
 * Defines the canonical route, state, and viewport matrix used by screenshot
 * tests; keeping it declarative makes missing visual coverage detectable.
 */
export const VISUAL_CLOCK = '2034-06-15T12:00:00.000Z'
export const VISUAL_FIXTURE_VERSION = 'ariadne-visual-v1'
export const VISUAL_RANDOM_SEED = 'ariadne-visual-v1'

export const visualViewports = [
  { key: 'desktop', width: 1440, height: 900 },
  { key: 'wide', width: 1728, height: 1117 },
  { key: 'narrow', width: 1100, height: 800 },
] as const

export type VisualViewport = (typeof visualViewports)[number]

export type VisualCase = {
  id: string
  kind: 'major' | 'states'
  slug: string
  path: string
  heading: string
  documentTitle: string
  activeNavigation: string | null
  proof: string
  layoutSignal?: 'graph' | 'map'
  reducedMotion?: boolean
}

export const majorVisualCases = [
  {
    id: 'M01',
    kind: 'major',
    slug: 'dashboard',
    path: '/dashboard?fixture=standard&capture=1',
    heading: 'Mission Control',
    documentTitle: 'Mission Control · Codename Ariadne',
    activeNavigation: 'Mission Control',
    proof: 'Mission control, synthetic run, limitations, alerts, and next actions',
  },
  {
    id: 'M02',
    kind: 'major',
    slug: 'new-audit',
    path: '/audits/new?fixture=full-audit-draft&capture=1',
    heading: 'Create a reviewed audit',
    documentTitle: 'New Audit · Codename Ariadne',
    activeNavigation: 'New Audit',
    proof: 'New-audit stepper, scope, profile, permissions, and budget summary',
  },
  {
    id: 'M03',
    kind: 'major',
    slug: 'intake',
    path: '/audits/new/intake?fixture=pasted-source&capture=1',
    heading: 'Add source material',
    documentTitle: 'Intake · Codename Ariadne',
    activeNavigation: 'New Audit',
    proof: 'Paste and file intake, local processing, validation, and quarantine feedback',
  },
  {
    id: 'M04',
    kind: 'major',
    slug: 'entity-review',
    path: '/audits/new/entities?fixture=review-mixed&capture=1',
    heading: 'Review extracted entities',
    documentTitle: 'Entity Review · Codename Ariadne',
    activeNavigation: 'New Audit',
    proof: 'Entity review, sensitivity, history, approval, exclusion, and transmission decisions',
  },
  {
    id: 'M05',
    kind: 'major',
    slug: 'tool-launcher',
    path: '/tools?fixture=standard&capture=1',
    heading: 'Tool Console',
    documentTitle: 'Tool Console · Codename Ariadne',
    activeNavigation: 'Tool Console',
    proof: 'Tool launcher, search, filtering, capabilities, jurisdiction, and transmission cues',
  },
  {
    id: 'M06',
    kind: 'major',
    slug: 'live-operations',
    path: '/operations/run-syn-0007?fixture=active&capture=1',
    heading: 'Greyhaven exposure baseline',
    documentTitle: 'Live Operations · Codename Ariadne',
    activeNavigation: 'Operations',
    proof: 'Phase 1 simulation, progress, queue, provider state, cost, findings, and safe controls',
  },
  {
    id: 'M07',
    kind: 'major',
    slug: 'findings',
    path: '/findings?fixture=review-queue&capture=1',
    heading: 'Findings',
    documentTitle: 'Findings · Codename Ariadne',
    activeNavigation: 'Findings',
    proof: 'Independent result, visibility, attribution, confidence, sensitivity, provenance, and review state',
  },
  {
    id: 'M08',
    kind: 'major',
    slug: 'identity-graph',
    path: '/graph?fixture=identity-standard&capture=1',
    heading: 'Link Map',
    documentTitle: 'Link Map · Codename Ariadne',
    activeNavigation: 'Link Map',
    proof: 'Identity and provenance graph, filters, private-node controls, edge explanation, and evidence',
    layoutSignal: 'graph',
  },
  {
    id: 'M09',
    kind: 'major',
    slug: 'geographic-map',
    path: '/map?fixture=coarse-locations&capture=1',
    heading: 'Geographic Map',
    documentTitle: 'Geographic Map · Codename Ariadne',
    activeNavigation: 'Geographic Map',
    proof: 'Coarse locations, temporal context, confidence, source, time, and jurisdiction controls',
    layoutSignal: 'map',
  },
  {
    id: 'M10',
    kind: 'major',
    slug: 'result-evidence',
    path: '/findings/finding-syn-0014?fixture=evidence-rich&capture=1',
    heading: 'Legacy community profile',
    documentTitle: 'Finding Detail · Codename Ariadne',
    activeNavigation: 'Findings',
    proof: 'Result detail, capture metadata, hash, immutable evidence, signals, and missing evidence',
  },
  {
    id: 'M11',
    kind: 'major',
    slug: 'impersonation-case',
    path: '/cases/impersonation/case-syn-0003?fixture=unresolved&capture=1',
    heading: 'Unresolved identity claim',
    documentTitle: 'Case Desk · Codename Ariadne',
    activeNavigation: 'Case Desk',
    proof: 'Careful classification, timeline, ownership periods, contradictions, gaps, and draft-only reporting',
  },
  {
    id: 'M12',
    kind: 'major',
    slug: 'compare-runs',
    path: '/compare?fixture=two-runs&capture=1',
    heading: 'What changed between snapshots?',
    documentTitle: 'Compare Runs · Codename Ariadne',
    activeNavigation: 'Compare Runs',
    proof: 'Run selectors and distinct new, changed, removed, reappeared, archived, and unknown states',
  },
  {
    id: 'M13',
    kind: 'major',
    slug: 'remediation',
    path: '/remediation?fixture=active-cases&capture=1',
    heading: 'Remediation stays reviewed',
    documentTitle: 'Removal Tracker · Codename Ariadne',
    activeNavigation: 'Removal Tracker',
    proof: 'Removal tracker status, owner, due date, evidence, response, recheck, and reappearance',
  },
  {
    id: 'M14',
    kind: 'major',
    slug: 'provider-registry',
    path: '/providers?fixture=global-registry&capture=1',
    heading: 'Provider coverage has boundaries',
    documentTitle: 'Source Radar · Codename Ariadne',
    activeNavigation: 'Source Radar',
    proof: 'Provider health, jurisdictions, access basis, retention, terms, risk, and enable state',
  },
  {
    id: 'M15',
    kind: 'major',
    slug: 'transmission-controls',
    path: '/privacy/transmission?fixture=preflight&capture=1',
    heading: 'Know what leaves the device',
    documentTitle: 'Transmission · Codename Ariadne',
    activeNavigation: 'Transmission',
    proof: 'Boundary modes and preflight provider, purpose, masked payload, retention, cost, risk, and approval',
  },
  {
    id: 'M16',
    kind: 'major',
    slug: 'settings-privacy',
    path: '/settings/privacy?fixture=standard&capture=1',
    heading: 'Private by default, explicit by design',
    documentTitle: 'Privacy & Settings · Codename Ariadne',
    activeNavigation: 'Privacy & Settings',
    proof: 'Manual vault session, retention, redaction, local AI, connectors, telemetry off, and motion controls',
  },
  {
    id: 'M17',
    kind: 'major',
    slug: 'state-lab',
    path: '/states?case=overview&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'State semantics, status labels, actions, and accessibility annotations',
  },
] as const satisfies readonly VisualCase[]

export const stateVisualCases = [
  {
    id: 'S01',
    kind: 'states',
    slug: 'empty',
    path: '/states?case=empty&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Honest empty findings and remediation states with safe next actions',
  },
  {
    id: 'S02',
    kind: 'states',
    slug: 'loading',
    path: '/states?case=loading&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Stable labelled loading representations with exposed busy state',
  },
  {
    id: 'S03',
    kind: 'states',
    slug: 'failure',
    path: '/states?case=failure&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Distinct failed, rate-limited, and unavailable states with bounded retries',
  },
  {
    id: 'S04',
    kind: 'states',
    slug: 'blocked-manual',
    path: '/states?case=blocked&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Explicit blocked access and guided manual capture without bypass claims',
  },
  {
    id: 'S05',
    kind: 'states',
    slug: 'reduced-motion',
    path: '/states?case=reduced-motion&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Understandable graph, scan, and progress content with nonessential motion removed',
    reducedMotion: true,
  },
  {
    id: 'S06',
    kind: 'states',
    slug: 'long-identifier',
    path: '/states?case=long-identifier&capture=1',
    heading: 'State laboratory',
    documentTitle: 'State Laboratory · Codename Ariadne',
    activeNavigation: null,
    proof: 'Inspectable long URL, hash, provider label, and identifier without document overflow',
  },
] as const satisfies readonly VisualCase[]

export const visualCases: readonly VisualCase[] = [
  ...majorVisualCases,
  ...stateVisualCases,
]

export const expectedScreenshotCount =
  visualCases.length * visualViewports.length

if (
  majorVisualCases.length !== 17 ||
  stateVisualCases.length !== 6 ||
  visualViewports.length !== 3 ||
  expectedScreenshotCount !== 69
) {
  throw new Error(
    'The Phase 1 visual manifest must contain 17 major routes and 6 state variants across 3 viewports (69 screenshots).',
  )
}

if (new Set(visualCases.map((visualCase) => visualCase.id)).size !== visualCases.length) {
  throw new Error('Every visual manifest case must have a unique ID.')
}

export function screenshotFileName(
  visualCase: VisualCase,
  viewport: VisualViewport,
) {
  return `${visualCase.id}-${visualCase.slug}__${viewport.width}x${viewport.height}.png`
}
