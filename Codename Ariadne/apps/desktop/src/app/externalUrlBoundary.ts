import { nativeRuntimeAvailable } from './coreBoundary'

const FIXED_PORTALS = new Set([
  'https://dehashed.com/',
  'https://www.spokeo.com/',
  'https://www.intelius.com/',
  'https://web.archive.org/',
  'https://lookup.icann.org/',
  'https://find-and-update.company-information.service.gov.uk/',
  'https://github.com/search?type=users',
  'https://myactivity.google.com/results-about-you',
  'https://haveibeenpwned.com/',
  'https://haveibeenpwned.com/API/v3',
])

const SEARCH_TARGETS: Readonly<Record<string, { readonly path: string; readonly key: string; readonly extra?: readonly [string, string] }>> = {
  'www.google.com': { path: '/search', key: 'q' },
  'www.bing.com': { path: '/search', key: 'q' },
  'duckduckgo.com': { path: '/', key: 'q' },
  'search.brave.com': { path: '/search', key: 'q', extra: ['source', 'web'] },
  'www.ecosia.org': { path: '/search', key: 'q' },
  'www.startpage.com': { path: '/sp/search', key: 'query' },
  'www.mojeek.com': { path: '/search', key: 'q' },
}

export function isApprovedExternalUrl(value: string): boolean {
  if (!value || new TextEncoder().encode(value).byteLength > 8_192) return false
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return false
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash || url.href !== value) return false
  if (FIXED_PORTALS.has(value)) return true
  if (url.hostname === 'haveibeenpwned.com' && !url.search && /^\/api\/v3\/breach\/[^/]{1,256}$/u.test(url.pathname)) return true

  const target = SEARCH_TARGETS[url.hostname]
  if (!target || url.pathname !== target.path) return false
  const pairs = [...url.searchParams.entries()]
  const expectedLength = target.extra ? 2 : 1
  if (pairs.length !== expectedLength || pairs[0]?.[0] !== target.key) return false
  const query = pairs[0]?.[1] ?? ''
  if (!query || new TextEncoder().encode(query).byteLength > 1_024) return false
  return target.extra === undefined ||
    (pairs[1]?.[0] === target.extra[0] && pairs[1]?.[1] === target.extra[1])
}

export async function openApprovedExternalUrl(value: string): Promise<void> {
  if (!isApprovedExternalUrl(value)) throw new Error('External URL refused')
  if (nativeRuntimeAvailable()) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_external_url', { url: value })
    return
  }
  const opened = window.open(value, '_blank', 'noopener,noreferrer')
  if (opened === null) throw new Error('The browser blocked the external link')
  opened.opener = null
}
