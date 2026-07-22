/** User-mediated portal metadata; entries are navigation aids, not automations. */
export type ManualResearchPortalCategory =
  | 'BREACH_AWARENESS'
  | 'PEOPLE_SEARCH'
  | 'ARCHIVE'
  | 'PUBLIC_RECORD'
  | 'CODE'
  | 'REMOVAL'

export interface ManualResearchPortal {
  readonly id: string
  readonly name: string
  readonly category: ManualResearchPortalCategory
  readonly url: string
  readonly operator: string
  readonly description: string
  readonly accessNote: string
  readonly importNote: string
}

/**
 * Portals without a reviewed, stable API remain user-mediated. Ariadne does not
 * prefill an identifier, automate a login, or work around an access challenge.
 */
export const manualResearchPortals: ReadonlyArray<ManualResearchPortal> = [
  {
    id: 'dehashed',
    name: 'DeHashed',
    category: 'BREACH_AWARENESS',
    url: 'https://dehashed.com/',
    operator: 'DeHashed',
    description: 'Review exposure records through your own authorised account.',
    accessNote: 'Manual account access; subscription and provider terms apply.',
    importNote: 'Import source metadata only. Never import exposed passwords or secrets.',
  },
  {
    id: 'spokeo',
    name: 'Spokeo',
    category: 'PEOPLE_SEARCH',
    url: 'https://www.spokeo.com/',
    operator: 'Spokeo',
    description: 'Review a broker listing for your own identity or an authorised subject.',
    accessNote: 'Manual portal; no documented integration is assumed.',
    importNote: 'Save only a reviewed URL or a user-supplied local export.',
  },
  {
    id: 'intelius',
    name: 'Intelius',
    category: 'PEOPLE_SEARCH',
    url: 'https://www.intelius.com/',
    operator: 'Intelius',
    description: 'Review a broker listing for your own identity or an authorised subject.',
    accessNote: 'Manual portal; subscription and provider terms apply.',
    importNote: 'Save only a reviewed URL or a user-supplied local export.',
  },
  {
    id: 'wayback-machine',
    name: 'Wayback Machine',
    category: 'ARCHIVE',
    url: 'https://web.archive.org/',
    operator: 'Internet Archive',
    description: 'Inspect historical captures of a URL you are authorised to research.',
    accessNote: 'Public manual search; availability varies by archived URL.',
    importNote: 'Retain the exact snapshot URL and capture time as provenance.',
  },
  {
    id: 'icann-lookup',
    name: 'ICANN Lookup',
    category: 'PUBLIC_RECORD',
    url: 'https://lookup.icann.org/',
    operator: 'ICANN',
    description: 'Inspect public registration data for a domain.',
    accessNote: 'Public manual lookup; redacted fields are expected.',
    importNote: 'Retain the exact lookup URL and observation time.',
  },
  {
    id: 'companies-house',
    name: 'Companies House',
    category: 'PUBLIC_RECORD',
    url: 'https://find-and-update.company-information.service.gov.uk/',
    operator: 'UK Companies House',
    description: 'Search the official UK company register.',
    accessNote: 'Public official register; jurisdiction is the United Kingdom.',
    importNote: 'Retain the exact company or filing URL as the source.',
  },
  {
    id: 'github-search',
    name: 'GitHub Search',
    category: 'CODE',
    url: 'https://github.com/search?type=users',
    operator: 'GitHub',
    description: 'Continue a public account or code search in GitHub.',
    accessNote: 'Manual browser search; account access may change available results.',
    importNote: 'Retain exact public profile, repository, commit, or issue URLs.',
  },
  {
    id: 'google-results-about-you',
    name: 'Results about you',
    category: 'REMOVAL',
    url: 'https://myactivity.google.com/results-about-you',
    operator: 'Google',
    description: 'Review and manage eligible personal-result removal requests.',
    accessNote: 'Manual signed-in workflow; availability varies by account and region.',
    importNote: 'Track only the request status and provider response you choose to record.',
  },
]

export function isApprovedManualPortalUrl(value: string): boolean {
  return manualResearchPortals.some((portal) => portal.url === value)
}
