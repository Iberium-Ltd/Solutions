export type SearchEngineId =
  | 'GOOGLE'
  | 'BING'
  | 'DUCKDUCKGO'
  | 'BRAVE'
  | 'ECOSIA'
  | 'STARTPAGE'
  | 'MOJEEK'

export interface SearchEngineDefinition {
  readonly id: SearchEngineId
  readonly label: string
  readonly operator: string
  readonly description: string
  readonly buildUrl: (query: string) => string
}

export interface AdvancedSearchFields {
  readonly baseQuery: string
  readonly exactPhrase: string
  readonly anyTerms: string
  readonly site: string
  readonly excludedSite: string
  readonly fileType: string
  readonly titleContains: string
  readonly urlContains: string
  readonly excludedTerms: string
  readonly afterDate: string
  readonly beforeDate: string
  readonly additionalOperators: string
}

const compact = (value: string) => value.normalize('NFKC').split(/\s+/u).filter(Boolean).join(' ')
const withoutQuotes = (value: string) => compact(value).replaceAll('"', '')
const operatorValue = (value: string) => withoutQuotes(value).replace(/\s/gu, '')
const quoted = (value: string) => {
  const clean = withoutQuotes(value)
  return clean.length === 0 ? '' : `"${clean}"`
}
const commaTerms = (value: string) => value
  .split(',')
  .map((term) => withoutQuotes(term))
  .filter(Boolean)

const queryUrl = (base: string, parameter: 'q' | 'query', query: string, extra = '') =>
  `${base}?${parameter}=${encodeURIComponent(query)}${extra}`

/** Browser handoffs only. Search results are not fetched or represented as Ariadne evidence. */
export const searchEngines: ReadonlyArray<SearchEngineDefinition> = [
  {
    id: 'GOOGLE',
    label: 'Google',
    operator: 'Google Search',
    description: 'Broad web index; operator support varies over time.',
    buildUrl: (query) => queryUrl('https://www.google.com/search', 'q', query),
  },
  {
    id: 'BING',
    label: 'Bing',
    operator: 'Microsoft Bing',
    description: 'Independent result ranking and Microsoft index coverage.',
    buildUrl: (query) => queryUrl('https://www.bing.com/search', 'q', query),
  },
  {
    id: 'DUCKDUCKGO',
    label: 'DuckDuckGo',
    operator: 'DuckDuckGo',
    description: 'Privacy-oriented browser search and Ariadne handoff option.',
    buildUrl: (query) => queryUrl('https://duckduckgo.com/', 'q', query),
  },
  {
    id: 'BRAVE',
    label: 'Brave',
    operator: 'Brave Search',
    description: 'Alternative web index with its own result ranking.',
    buildUrl: (query) => queryUrl('https://search.brave.com/search', 'q', query, '&source=web'),
  },
  {
    id: 'ECOSIA',
    label: 'Ecosia',
    operator: 'Ecosia',
    description: 'Browser handoff for an additional result presentation.',
    buildUrl: (query) => queryUrl('https://www.ecosia.org/search', 'q', query),
  },
  {
    id: 'STARTPAGE',
    label: 'Startpage',
    operator: 'Startpage',
    description: 'Privacy-oriented browser handoff; syntax support may differ.',
    buildUrl: (query) => queryUrl('https://www.startpage.com/sp/search', 'query', query),
  },
  {
    id: 'MOJEEK',
    label: 'Mojeek',
    operator: 'Mojeek',
    description: 'Independent crawler and index for supplementary coverage.',
    buildUrl: (query) => queryUrl('https://www.mojeek.com/search', 'q', query),
  },
]

export function composeAdvancedSearchQuery(fields: AdvancedSearchFields): string {
  const parts: string[] = []
  const baseQuery = compact(fields.baseQuery)
  if (baseQuery) parts.push(baseQuery)

  const exactPhrase = quoted(fields.exactPhrase)
  if (exactPhrase) parts.push(exactPhrase)

  const alternatives = commaTerms(fields.anyTerms)
  if (alternatives.length === 1) parts.push(alternatives[0] ?? '')
  if (alternatives.length > 1) {
    parts.push(`(${alternatives.map((term) => term.includes(' ') ? `"${term}"` : term).join(' OR ')})`)
  }

  const site = operatorValue(fields.site)
  if (site) parts.push(`site:${site}`)
  const excludedSite = operatorValue(fields.excludedSite)
  if (excludedSite) parts.push(`-site:${excludedSite}`)
  const fileType = operatorValue(fields.fileType).replace(/^\./u, '')
  if (fileType) parts.push(`filetype:${fileType}`)

  const titleContains = quoted(fields.titleContains)
  if (titleContains) parts.push(`intitle:${titleContains}`)
  const urlContains = quoted(fields.urlContains)
  if (urlContains) parts.push(`inurl:${urlContains}`)

  for (const term of commaTerms(fields.excludedTerms)) {
    parts.push(`-${term.includes(' ') ? `"${term}"` : term}`)
  }

  const afterDate = operatorValue(fields.afterDate)
  if (afterDate) parts.push(`after:${afterDate}`)
  const beforeDate = operatorValue(fields.beforeDate)
  if (beforeDate) parts.push(`before:${beforeDate}`)

  const additionalOperators = compact(fields.additionalOperators)
  if (additionalOperators) parts.push(additionalOperators)
  return parts.filter(Boolean).join(' ')
}

export function buildSearchEngineUrl(engineId: SearchEngineId, query: string): string {
  const engine = searchEngines.find((candidate) => candidate.id === engineId)
  if (!engine) throw new Error('Unsupported search engine')
  const normalizedQuery = compact(query)
  if (!normalizedQuery) throw new Error('A search query is required')
  return engine.buildUrl(normalizedQuery)
}
