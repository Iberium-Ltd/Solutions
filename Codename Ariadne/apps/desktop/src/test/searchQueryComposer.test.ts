/** Locks transparent provider-specific query composition and length bounds. */
import { describe, expect, it } from 'vitest'
import {
  buildSearchEngineUrl,
  composeAdvancedSearchQuery,
  searchEngines,
  type AdvancedSearchFields,
} from '../app/searchQueryComposer'

const fields = (patch: Partial<AdvancedSearchFields> = {}): AdvancedSearchFields => ({
  baseQuery: '',
  exactPhrase: '',
  anyTerms: '',
  site: '',
  excludedSite: '',
  fileType: '',
  titleContains: '',
  urlContains: '',
  excludedTerms: '',
  afterDate: '',
  beforeDate: '',
  additionalOperators: '',
  ...patch,
})

describe('advanced search query composition', () => {
  it('combines structured operators deterministically without transmitting anything', () => {
    expect(composeAdvancedSearchQuery(fields({
      baseQuery: '  synthetic alias  ',
      exactPhrase: 'example phrase',
      anyTerms: 'alpha, beta phrase',
      site: 'example.invalid',
      excludedSite: 'noise.invalid',
      fileType: '.pdf',
      titleContains: 'public profile',
      urlContains: 'directory',
      excludedTerms: 'wrong, false match',
      afterDate: '2025-01-01',
      beforeDate: '2026-01-01',
      additionalOperators: '  custom:value  ',
    }))).toBe('synthetic alias "example phrase" (alpha OR "beta phrase") site:example.invalid -site:noise.invalid filetype:pdf intitle:"public profile" inurl:"directory" -wrong -"false match" after:2025-01-01 before:2026-01-01 custom:value')
  })

  it('builds encoded HTTPS handoffs for every fixed engine', () => {
    expect(searchEngines).toHaveLength(7)
    for (const engine of searchEngines) {
      const url = new URL(buildSearchEngineUrl(engine.id, 'synthetic phrase site:example.invalid'))
      expect(url.protocol).toBe('https:')
      expect([...url.searchParams.values()]).toContain('synthetic phrase site:example.invalid')
    }
  })

  it('rejects empty handoff queries', () => {
    expect(() => buildSearchEngineUrl('BING', '   ')).toThrow('A search query is required')
  })
})
