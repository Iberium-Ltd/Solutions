export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type Health = 'operational' | 'degraded' | 'blocked' | 'offline'

export const syntheticNotice =
  'Synthetic prototype · no external requests · no personal data'

export const syntheticProfile = {
  id: 'profile_syn_01',
  name: 'Morgan Vale',
  initials: 'MV',
  location: 'Greyhaven',
  email: 'morgan.vale@example.invalid',
  username: 'night_orbit',
  organisation: 'Northbridge Systems',
  description:
    'Fictional identity used only to validate review, attribution, and privacy controls.',
}

export const syntheticRun = {
  id: 'run-syn-0007',
  shortId: 'SYN-0741',
  title: 'Greyhaven exposure baseline',
  status: 'running',
  progress: 68,
  phase: 'Correlating findings',
  startedAt: '11 Jul 2026 · 14:32',
  eta: '08m 24s',
  mode: 'Local + approved EU',
}

export const dashboardMetrics = [
  { label: 'Coverage checks', value: '186', delta: '142 complete', tone: 'cyan' },
  { label: 'Findings', value: '27', delta: '6 need review', tone: 'violet' },
  { label: 'Evidence sealed', value: '14', delta: '14 hashes verified', tone: 'green' },
  { label: 'Coverage gaps', value: '5', delta: '2 manual actions', tone: 'amber' },
] as const

export const coverageSeries = [38, 44, 43, 55, 58, 62, 61, 71, 76, 79, 84, 88]

export const auditPhases = [
  { label: 'Identity review', status: 'complete', detail: '12 entities approved' },
  { label: 'Plan compiled', status: 'complete', detail: '186 bounded checks' },
  { label: 'Source discovery', status: 'complete', detail: '142 checks returned' },
  { label: 'Correlation', status: 'active', detail: '6 candidates need review' },
  { label: 'Evidence sealing', status: 'queued', detail: '4 captures queued' },
] as const

export const entities = [
  {
    id: 'ent_syn_person',
    type: 'Person',
    value: 'Morgan Vale',
    provenance: 'Pasted profile brief',
    confidence: 98,
    decision: 'Confirmed',
    sensitivity: 'Public',
    permission: 'Search allowed',
  },
  {
    id: 'ent_syn_email',
    type: 'Email',
    value: 'morgan.vale@example.invalid',
    provenance: 'Pasted profile brief',
    confidence: 100,
    decision: 'Confirmed',
    sensitivity: 'Sensitive',
    permission: 'Ask per provider',
  },
  {
    id: 'ent_syn_username',
    type: 'Username',
    value: '@night_orbit',
    provenance: 'Fictional portfolio note',
    confidence: 94,
    decision: 'Historical',
    sensitivity: 'Sensitive',
    permission: 'Search allowed',
  },
  {
    id: 'ent_syn_org',
    type: 'Organisation',
    value: 'Northbridge Systems',
    provenance: 'Fictional CV fragment',
    confidence: 91,
    decision: 'Probable',
    sensitivity: 'Public',
    permission: 'Search allowed',
  },
  {
    id: 'ent_syn_location',
    type: 'Location',
    value: 'Greyhaven',
    provenance: 'Fictional profile note',
    confidence: 86,
    decision: 'Historical',
    sensitivity: 'Sensitive',
    permission: 'Store only',
  },
  {
    id: 'ent_syn_restricted',
    type: 'Restricted value',
    value: '•••••••• · quarantined',
    provenance: 'Local restricted-value detector',
    confidence: 99,
    decision: 'Excluded',
    sensitivity: 'Restricted',
    permission: 'Never transmit',
  },
] as const

export const toolCatalog = [
  ['Email Trace', 'email', 'Trace one email through public or authorised links.', 'Sensitive'],
  ['Username Sweep', 'at-sign', 'Check one handle and controlled variants across sources.', 'Sensitive'],
  ['Name Search', 'user-search', 'Search a legal name, nickname, or alias with context.', 'Public'],
  ['Phone Trace', 'phone', 'Inspect approved phone formats with strict controls.', 'High control'],
  ['Address Search', 'map-pin', 'Investigate a location without exposing exact coordinates.', 'High control'],
  ['Domain Scan', 'globe', 'Inspect a domain, public infrastructure, and mentions.', 'Public'],
  ['URL Inspector', 'link', 'Analyse redirects, metadata, archives, and evidence.', 'Public'],
  ['Company Search', 'building-2', 'Review public company records and linked identities.', 'Public'],
  ['Image Match', 'scan-face', 'Run authorised image similarity and reverse checks.', 'High control'],
  ['Repository Scan', 'git-branch', 'Inspect owned or authorised source history.', 'Local first'],
  ['Archive Search', 'archive', 'Look for historical captures and cached references.', 'Public'],
  ['Public Records Search', 'landmark', 'Query official registers with jurisdiction context.', 'Public'],
  ['Inbox Account Finder', 'mail-search', 'Extract account metadata from an authorised mailbox.', 'Private'],
  ['GitHub Exposure Review', 'github', 'Review an authorised account and repositories.', 'Authorised'],
  ['Local File Search', 'folder-search', 'Search an imported local corpus without transmission.', 'Local only'],
  ['Evidence Capture', 'camera', 'Preserve screenshots, source, metadata, and hashes.', 'Local only'],
  ['Compare Runs', 'git-compare', 'Compare two audits and isolate meaningful change.', 'Local only'],
  ['Removal Tracker', 'list-checks', 'Track correction, deletion, and deindexing work.', 'Local only'],
  ['Source Radar', 'radar', 'Inspect provider health, jurisdiction, and coverage.', 'Registry'],
  ['Link Map', 'share-2', 'Explore the identity and provenance graph.', 'Local only'],
  ['Case Desk', 'briefcase-business', 'Resolve ambiguous attribution and impersonation cases.', 'Human review'],
] as const

export const operationTasks = [
  { id: 'tsk_101', name: 'Exact username search', provider: 'Boreal Search', state: 'complete', duration: '1.8s', results: 8 },
  { id: 'tsk_102', name: 'Archive capture lookup', provider: 'Meridian Archive', state: 'complete', duration: '4.2s', results: 3 },
  { id: 'tsk_103', name: 'Profile correlation', provider: 'Ariadne Core', state: 'running', duration: '12.6s', results: 6 },
  { id: 'tsk_104', name: 'Code attribution check', provider: 'Code Atlas', state: 'running', duration: '7.1s', results: 2 },
  { id: 'tsk_105', name: 'Image similarity', provider: 'Image Observatory', state: 'blocked', duration: '—', results: 0 },
  { id: 'tsk_106', name: 'Evidence screenshot', provider: 'Local Capture', state: 'queued', duration: '—', results: 0 },
] as const

export const operationLogs = [
  ['14:37:18.092', 'INFO', 'Ariadne Core', 'Candidate edge created · explanation required'],
  ['14:37:18.840', 'PASS', 'Policy', 'EU provider preflight matched approved scope'],
  ['14:37:20.113', 'WARN', 'Image Observatory', 'Manual image approval required; task blocked'],
  ['14:37:22.405', 'FOUND', 'Boreal Search', 'Public profile candidate normalised'],
  ['14:37:24.889', 'INFO', 'Evidence', 'Capture queued with immutable source metadata'],
] as const

export const findings = [
  {
    id: 'finding_syn_profile',
    title: 'Legacy community profile',
    source: 'Boreal Search',
    url: 'https://community.example.invalid/u/night_orbit',
    outcome: 'FOUND',
    visibility: 'Public pseudonymous',
    ownership: 'Probable match',
    confidence: 86,
    severity: 'high' as Severity,
    changed: 'New',
    summary: 'Handle and project reference align; chronology remains incomplete.',
  },
  {
    id: 'finding_syn_archive',
    title: 'Archived portfolio biography',
    source: 'Meridian Archive',
    url: 'https://archive.example.invalid/snapshot/portfolio-042',
    outcome: 'FOUND',
    visibility: 'Historical residue',
    ownership: 'Probable match',
    confidence: 79,
    severity: 'medium' as Severity,
    changed: 'Reappeared',
    summary: 'Archived page repeats a fictional organisation and alias.',
  },
  {
    id: 'finding_syn_code',
    title: 'Public code author metadata',
    source: 'Code Atlas',
    url: 'https://code.example.invalid/northbridge/thread-index',
    outcome: 'FOUND',
    visibility: 'Publicly attributable',
    ownership: 'Confirmed match',
    confidence: 97,
    severity: 'medium' as Severity,
    changed: 'Changed',
    summary: 'Synthetic commit metadata connects the public name and organisation.',
  },
  {
    id: 'finding_syn_collision',
    title: 'Same-handle gaming account',
    source: 'Source Radar',
    url: 'https://games.example.invalid/night_orbit',
    outcome: 'AMBIGUOUS',
    visibility: 'Public pseudonymous',
    ownership: 'Unrelated collision',
    confidence: 34,
    severity: 'low' as Severity,
    changed: 'Unchanged',
    summary: 'Timeline and language contradict the synthetic subject profile.',
  },
  {
    id: 'finding_syn_blocked',
    title: 'Image result awaiting approval',
    source: 'Image Observatory',
    url: 'https://images.example.invalid/manual-review',
    outcome: 'MANUAL_REVIEW_REQUIRED',
    visibility: 'Unknown',
    ownership: 'Unresolved',
    confidence: 0,
    severity: 'info' as Severity,
    changed: 'Not checked',
    summary: 'No image was transmitted; explicit user approval is required.',
  },
] as const

export const attributionSignals = [
  { label: 'Exact uncommon handle', weight: '+28', detail: 'Present on two independent synthetic sources', tone: 'positive' },
  { label: 'Project reference', weight: '+22', detail: 'Matches the fictional Northbridge project', tone: 'positive' },
  { label: 'Chronology gap', weight: '−14', detail: 'No immutable account ID before the archive date', tone: 'negative' },
  { label: 'Photograph comparison', weight: '—', detail: 'Not checked; no authorised image supplied', tone: 'missing' },
] as const

export const evidenceRecord = {
  id: 'ev_syn_f4c2',
  capturedAt: '2026-07-11T14:36:22Z',
  viewport: '1440 × 900',
  method: 'Synthetic local capture',
  httpStatus: '200 · simulated',
  redirectCount: 1,
  encryption: 'Encrypted · local vault',
  hash: '7f4a2d81c6e90b3f45a81d5e7a0c4bf9c6d11a82e5b4f7d903c2a1184e6f20ab',
}

export const graphNodes = [
  { data: { id: 'person', label: 'Morgan Vale', type: 'person', confidence: 100 }, position: { x: 410, y: 230 } },
  { data: { id: 'username', label: '@night_orbit', type: 'username', confidence: 94 }, position: { x: 620, y: 130 } },
  { data: { id: 'email', label: 'm•••••@example.invalid', type: 'email', confidence: 100 }, position: { x: 615, y: 335 } },
  { data: { id: 'org', label: 'Northbridge Systems', type: 'organisation', confidence: 91 }, position: { x: 190, y: 130 } },
  { data: { id: 'place', label: 'Greyhaven', type: 'location', confidence: 86 }, position: { x: 185, y: 335 } },
  { data: { id: 'finding', label: 'Legacy profile', type: 'finding', confidence: 86 }, position: { x: 820, y: 225 } },
  { data: { id: 'evidence', label: 'Evidence 04', type: 'evidence', confidence: 100 }, position: { x: 845, y: 390 } },
] as const

export const graphEdges = [
  { data: { id: 'e1', source: 'person', target: 'username', label: 'USED', confidence: 94 } },
  { data: { id: 'e2', source: 'person', target: 'email', label: 'OWNS', confidence: 100 } },
  { data: { id: 'e3', source: 'person', target: 'org', label: 'EMPLOYED_BY', confidence: 91 } },
  { data: { id: 'e4', source: 'person', target: 'place', label: 'LIVED_AT', confidence: 86 } },
  { data: { id: 'e5', source: 'username', target: 'finding', label: 'FOUND_BY', confidence: 86 } },
  { data: { id: 'e6', source: 'finding', target: 'evidence', label: 'SUPPORTED_BY', confidence: 100 } },
] as const

export const mapPoints = [
  { id: 'greyhaven', label: 'Greyhaven', x: 47, y: 38, kind: 'historic', precision: 'Coarse region', confidence: 86 },
  { id: 'northbridge', label: 'Northbridge office', x: 56, y: 31, kind: 'public', precision: 'City level', confidence: 91 },
  { id: 'provider-eu', label: 'EU provider region', x: 50, y: 30, kind: 'provider', precision: 'Hosting region', confidence: 100 },
  { id: 'provider-us', label: 'US provider region', x: 23, y: 36, kind: 'provider', precision: 'Hosting region', confidence: 100 },
] as const

export const providers = [
  { id: 'local-corpus', name: 'Local Corpus Engine', country: 'On device', regions: ['Local'], type: 'local_index', health: 'operational' as Health, risk: 'Low', retention: 'No external retention', enabled: true, sendsIdentifiers: false, coverage: 100 },
  { id: 'boreal-search', name: 'Boreal Search', country: 'FI', regions: ['EU'], type: 'public_search_api', health: 'operational' as Health, risk: 'Medium', retention: '30 days declared', enabled: true, sendsIdentifiers: true, coverage: 92 },
  { id: 'meridian-archive', name: 'Meridian Archive', country: 'NL', regions: ['EU'], type: 'public_archive', health: 'degraded' as Health, risk: 'Medium', retention: 'Unknown', enabled: true, sendsIdentifiers: true, coverage: 71 },
  { id: 'code-atlas', name: 'Code Atlas', country: 'DE', regions: ['EU'], type: 'public_code_search', health: 'operational' as Health, risk: 'Low', retention: 'No query storage declared', enabled: true, sendsIdentifiers: true, coverage: 88 },
  { id: 'image-observatory', name: 'Image Observatory', country: 'US', regions: ['US'], type: 'reverse_image', health: 'blocked' as Health, risk: 'High', retention: 'Unknown', enabled: false, sendsIdentifiers: true, coverage: 0 },
  { id: 'civic-ledger', name: 'Civic Ledger', country: 'GB', regions: ['GB'], type: 'public_records', health: 'offline' as Health, risk: 'Medium', retention: 'Public query logs unknown', enabled: false, sendsIdentifiers: true, coverage: 0 },
] as const

export const transmissionLedger = [
  { time: '14:32:08', value: '@night_orbit', provider: 'Boreal Search', region: 'EU', purpose: 'Exact public search', result: 'Approved · sent' },
  { time: '14:32:12', value: 'm•••••@example.invalid', provider: 'Local Corpus Engine', region: 'Local', purpose: 'Local correlation', result: 'Local only' },
  { time: '14:33:41', value: 'Greyhaven', provider: 'Meridian Archive', region: 'EU', purpose: 'Historic context', result: 'Approved · sent' },
  { time: '14:34:03', value: 'Image fingerprint', provider: 'Image Observatory', region: 'US', purpose: 'Similarity search', result: 'Blocked · approval needed' },
] as const

export const comparisonRows = [
  { item: 'Legacy community profile', previous: 'Not observed', current: 'Public page', state: 'NEW', impact: 'High' },
  { item: 'Portfolio biography', previous: 'Removed', current: 'Archived copy', state: 'REAPPEARED', impact: 'Medium' },
  { item: 'Code author metadata', previous: 'Old organisation', current: 'Northbridge Systems', state: 'CHANGED', impact: 'Medium' },
  { item: 'Old directory listing', previous: 'Public page', current: '404', state: 'REMOVED', impact: 'Low' },
  { item: 'Same-handle gaming profile', previous: 'Rejected', current: 'Rejected', state: 'FALSE_POSITIVE', impact: 'None' },
] as const

export const remediationColumns = [
  {
    id: 'triage',
    title: 'Triage',
    items: [
      { title: 'Legacy community profile', action: 'Preserve evidence', due: 'Today', priority: 'High' },
      { title: 'Archived biography', action: 'Assess persistence', due: '14 Jul', priority: 'Medium' },
    ],
  },
  {
    id: 'draft',
    title: 'Draft ready',
    items: [
      { title: 'Directory correction', action: 'Correction request', due: '16 Jul', priority: 'Medium' },
      { title: 'Search result cache', action: 'Deindexing draft', due: '18 Jul', priority: 'Low' },
    ],
  },
  {
    id: 'waiting',
    title: 'Waiting',
    items: [
      { title: 'Profile removal', action: 'Provider response', due: '26 Jul', priority: 'High' },
    ],
  },
  {
    id: 'monitor',
    title: 'Monitor',
    items: [
      { title: 'Archive reappearance', action: 'Monthly check', due: '11 Aug', priority: 'Medium' },
      { title: 'Confirmed non-match', action: 'Watch exclusion', due: '11 Oct', priority: 'Low' },
    ],
  },
] as const

export const impersonationTimeline = [
  { date: 'Mar 2022', title: 'Synthetic handle first used', detail: 'User-stated historical ownership; no public capture.' },
  { date: 'Nov 2024', title: 'Last verified ownership marker', detail: 'Fictional local export references the handle.' },
  { date: 'Jun 2026', title: 'Suspicious public result observed', detail: 'Profile claims overlap but immutable account ID is missing.' },
  { date: 'Jul 2026', title: 'Case opened', detail: 'Evidence preservation pending manual browser capture.' },
] as const

export const stateVariants = {
  empty: {
    eyebrow: 'Clean workspace',
    title: 'No findings match this view',
    body: 'Adjust the filters or start a synthetic trace. An empty view is not a claim that no exposure exists.',
  },
  loading: {
    eyebrow: 'Local processing',
    title: 'Building the reviewed identity graph',
    body: 'Deterministic extraction is running locally. Nothing has been transmitted.',
  },
  failure: {
    eyebrow: 'Check failed',
    title: 'The provider did not return a usable response',
    body: 'The check remains recorded as CHECK_FAILED and will not be interpreted as absence.',
  },
  blocked: {
    eyebrow: 'Manual action required',
    title: 'Automation stopped at the provider boundary',
    body: 'A guided capture can continue without bypassing access controls.',
  },
} as const
