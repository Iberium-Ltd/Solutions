export type PublicDiscoveryProvider =
  | 'DUCKDUCKGO_HTML'
  | 'GITHUB_USERS'

export type PublicDiscoveryState =
  | 'NOT_CHECKED'
  | 'SUCCEEDED'
  | 'RATE_LIMITED'
  | 'ACCESS_BLOCKED'
  | 'FAILED'

export type PublicDiscoveryReason =
  | 'COMPLETE'
  | 'NO_RESULTS'
  | 'PARTIAL_RESULTS'
  | 'SELF_AUDIT_AUTHORIZATION_REQUIRED'
  | 'RESTRICTED_VALUE'
  | 'UPSTREAM_RATE_LIMITED'
  | 'CAPTCHA_OR_CHALLENGE'
  | 'UPSTREAM_ACCESS_BLOCKED'
  | 'REDIRECT_REFUSED'
  | 'TIMEOUT'
  | 'RESPONSE_LIMIT'
  | 'NETWORK_UNAVAILABLE'
  | 'UPSTREAM_UNAVAILABLE'
  | 'UPSTREAM_REJECTED'
  | 'INVALID_RESPONSE'

export interface PublicDiscoverySearchRequest {
  readonly provider: PublicDiscoveryProvider
  readonly query: string
  readonly authorizedSelfAudit: boolean
  readonly maxResults: number
}

export interface PublicDiscoveryResultItem {
  readonly provider: PublicDiscoveryProvider
  readonly rank: number
  readonly title: string
  readonly url: string
  readonly snippet: string | null
  readonly sourceId: string | null
}

export interface PublicDiscoverySearchResult {
  readonly provider: PublicDiscoveryProvider
  readonly state: PublicDiscoveryState
  readonly reason: PublicDiscoveryReason
  readonly results: ReadonlyArray<PublicDiscoveryResultItem>
  readonly totalEstimate: number | null
  readonly rateLimitRemaining: number | null
  readonly truncated: boolean
  readonly externalRequestMade: boolean
  readonly authorizationConfirmed: boolean
  readonly humanReviewRequired: true
}

export interface PublicDiscoveryCaptureRequest {
  readonly profileId: string
  readonly provider: PublicDiscoveryProvider
  readonly query: string
  readonly rank: number
  readonly title: string
  readonly url: string
  readonly snippet: string | null
  readonly sourceId: string | null
  readonly capturedAtUs: number
  readonly authorizedSelfAudit: true
}

export interface PublicDiscoveryCaptureResult {
  readonly profileId: string
  readonly findingId: string
  readonly artifactId: string
  readonly provider: PublicDiscoveryProvider
  readonly rank: number
  readonly sourceId: string | null
  readonly url: string
  readonly urlSha256: string
  readonly queryReference: string
  readonly capturedAtUs: number
  readonly evidenceKind: 'URL_REFERENCE'
  readonly encryptedAtRest: true
  readonly localOnly: true
  readonly deduplicated: boolean
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const QUERY_REFERENCE_PATTERN = /^mq_[0-9a-f]{64}$/
const PROVIDERS = new Set<PublicDiscoveryProvider>([
  'DUCKDUCKGO_HTML',
  'GITHUB_USERS',
])
const STATES = new Set<PublicDiscoveryState>([
  'NOT_CHECKED',
  'SUCCEEDED',
  'RATE_LIMITED',
  'ACCESS_BLOCKED',
  'FAILED',
])
const REASONS = new Set<PublicDiscoveryReason>([
  'COMPLETE',
  'NO_RESULTS',
  'PARTIAL_RESULTS',
  'SELF_AUDIT_AUTHORIZATION_REQUIRED',
  'RESTRICTED_VALUE',
  'UPSTREAM_RATE_LIMITED',
  'CAPTCHA_OR_CHALLENGE',
  'UPSTREAM_ACCESS_BLOCKED',
  'REDIRECT_REFUSED',
  'TIMEOUT',
  'RESPONSE_LIMIT',
  'NETWORK_UNAVAILABLE',
  'UPSTREAM_UNAVAILABLE',
  'UPSTREAM_REJECTED',
  'INVALID_RESPONSE',
])
const SUCCESS_REASONS = new Set<PublicDiscoveryReason>([
  'COMPLETE',
  'NO_RESULTS',
  'PARTIAL_RESULTS',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...expectedKeys].sort()
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  )
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number) {
  return (
    Number.isSafeInteger(value) &&
    Number(value) >= minimum &&
    Number(value) <= maximum
  )
}

function isBoundedText(value: unknown, minimum: number, maximum: number) {
  return (
    typeof value === 'string' &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.trim() === value &&
    !Array.from(value).some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point < 32 || point === 127
    })
  )
}

function isPublicUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length < 1 || value.length > 2_048) {
    return false
  }
  try {
    const url = new URL(value)
    return (
      ['http:', 'https:'].includes(url.protocol) &&
      url.hostname.includes('.') &&
      url.username === '' &&
      url.password === '' &&
      url.hash === ''
    )
  } catch {
    return false
  }
}

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !UUID_PATTERN.test(String(value.requestId))
  ) {
    throw new Error('Public discovery command response is invalid')
  }
  return value.data
}

function isResultItem(value: unknown): value is PublicDiscoveryResultItem {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'provider',
      'rank',
      'title',
      'url',
      'snippet',
      'sourceId',
    ]) &&
    PROVIDERS.has(value.provider as PublicDiscoveryProvider) &&
    isIntegerBetween(value.rank, 1, 25) &&
    isBoundedText(value.title, 1, 240) &&
    isPublicUrl(value.url) &&
    (value.snippet === null || isBoundedText(value.snippet, 1, 600)) &&
    (value.sourceId === null || isBoundedText(value.sourceId, 1, 160))
  )
}

function parseResult(value: unknown): PublicDiscoverySearchResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'provider',
      'state',
      'reason',
      'results',
      'totalEstimate',
      'rateLimitRemaining',
      'truncated',
      'externalRequestMade',
      'authorizationConfirmed',
      'humanReviewRequired',
    ]) ||
    !PROVIDERS.has(data.provider as PublicDiscoveryProvider) ||
    !STATES.has(data.state as PublicDiscoveryState) ||
    !REASONS.has(data.reason as PublicDiscoveryReason) ||
    !Array.isArray(data.results) ||
    data.results.length > 25 ||
    !data.results.every(isResultItem) ||
    !data.results.every((item) => item.provider === data.provider) ||
    new Set(data.results.map((item) => item.url)).size !== data.results.length ||
    !data.results.every((item, index) => item.rank === index + 1) ||
    !(
      data.totalEstimate === null ||
      isIntegerBetween(data.totalEstimate, 0, 1_000_000_000)
    ) ||
    !(
      data.rateLimitRemaining === null ||
      isIntegerBetween(data.rateLimitRemaining, 0, 1_000_000_000)
    ) ||
    typeof data.truncated !== 'boolean' ||
    typeof data.externalRequestMade !== 'boolean' ||
    typeof data.authorizationConfirmed !== 'boolean' ||
    data.humanReviewRequired !== true ||
    ((data.state === 'SUCCEEDED') !==
      SUCCESS_REASONS.has(data.reason as PublicDiscoveryReason)) ||
    (data.state !== 'SUCCEEDED' && data.results.length !== 0) ||
    (data.state === 'SUCCEEDED' && !data.externalRequestMade) ||
    (data.externalRequestMade && !data.authorizationConfirmed) ||
    (data.reason === 'NO_RESULTS' && data.results.length !== 0) ||
    (data.reason !== 'NO_RESULTS' &&
      data.state === 'SUCCEEDED' &&
      data.results.length === 0)
  ) {
    throw new Error('Public discovery search response is invalid')
  }
  return data as unknown as PublicDiscoverySearchResult
}

function validateRequest(request: PublicDiscoverySearchRequest): void {
  const queryBytes = new TextEncoder().encode(request.query).length
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'provider',
      'query',
      'authorizedSelfAudit',
      'maxResults',
    ]) ||
    !PROVIDERS.has(request.provider) ||
    !isBoundedText(request.query, 1, 1_024) ||
    queryBytes > 1_024 ||
    typeof request.authorizedSelfAudit !== 'boolean' ||
    !isIntegerBetween(request.maxResults, 1, 25)
  ) {
    throw new Error('Public discovery search request is invalid')
  }
}

function parseCaptureResult(value: unknown): PublicDiscoveryCaptureResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'findingId',
      'artifactId',
      'provider',
      'rank',
      'sourceId',
      'url',
      'urlSha256',
      'queryReference',
      'capturedAtUs',
      'evidenceKind',
      'encryptedAtRest',
      'localOnly',
      'deduplicated',
    ]) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !UUID_PATTERN.test(String(data.findingId)) ||
    !UUID_PATTERN.test(String(data.artifactId)) ||
    !PROVIDERS.has(data.provider as PublicDiscoveryProvider) ||
    !isIntegerBetween(data.rank, 1, 25) ||
    (data.sourceId !== null && !isBoundedText(data.sourceId, 1, 160)) ||
    !isPublicUrl(data.url) ||
    !SHA256_PATTERN.test(String(data.urlSha256)) ||
    !QUERY_REFERENCE_PATTERN.test(String(data.queryReference)) ||
    !isIntegerBetween(data.capturedAtUs, 1, Number.MAX_SAFE_INTEGER) ||
    data.evidenceKind !== 'URL_REFERENCE' ||
    data.encryptedAtRest !== true ||
    data.localOnly !== true ||
    typeof data.deduplicated !== 'boolean'
  ) {
    throw new Error('Public discovery capture response is invalid')
  }
  return data as unknown as PublicDiscoveryCaptureResult
}

function validateCaptureRequest(request: PublicDiscoveryCaptureRequest): void {
  const queryBytes = new TextEncoder().encode(request.query).length
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'provider',
      'query',
      'rank',
      'title',
      'url',
      'snippet',
      'sourceId',
      'capturedAtUs',
      'authorizedSelfAudit',
    ]) ||
    !UUID_PATTERN.test(request.profileId) ||
    !PROVIDERS.has(request.provider) ||
    !isBoundedText(request.query, 1, 1_024) ||
    queryBytes > 1_024 ||
    !isIntegerBetween(request.rank, 1, 25) ||
    !isBoundedText(request.title, 1, 240) ||
    !isPublicUrl(request.url) ||
    (request.snippet !== null && !isBoundedText(request.snippet, 1, 600)) ||
    (request.sourceId !== null && !isBoundedText(request.sourceId, 1, 160)) ||
    !isIntegerBetween(request.capturedAtUs, 1, Number.MAX_SAFE_INTEGER) ||
    request.authorizedSelfAudit !== true
  ) {
    throw new Error('Public discovery capture request is invalid')
  }
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(value),
  )
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

export async function searchPublicDiscovery(
  request: PublicDiscoverySearchRequest,
): Promise<PublicDiscoverySearchResult> {
  validateRequest(request)
  const { invoke } = await import('@tauri-apps/api/core')
  const result = parseResult(
    await invoke('core_search_public_discovery', { request }),
  )
  if (
    result.provider !== request.provider ||
    result.authorizationConfirmed !== request.authorizedSelfAudit
  ) {
    throw new Error('Public discovery response binding is invalid')
  }
  return result
}

export async function capturePublicDiscovery(
  request: PublicDiscoveryCaptureRequest,
): Promise<PublicDiscoveryCaptureResult> {
  validateCaptureRequest(request)
  const { invoke } = await import('@tauri-apps/api/core')
  const result = parseCaptureResult(
    await invoke('core_capture_public_discovery', { request }),
  )
  if (
    result.profileId !== request.profileId ||
    result.provider !== request.provider ||
    result.rank !== request.rank ||
    result.sourceId !== request.sourceId ||
    result.url !== request.url ||
    result.capturedAtUs !== request.capturedAtUs ||
    result.urlSha256 !== (await sha256(request.url))
  ) {
    throw new Error('Public discovery capture response binding is invalid')
  }
  return result
}

export const publicDiscoveryBoundaryParsers = {
  result: parseResult,
  captureResult: parseCaptureResult,
}
