/**
 * Runtime contract for explicit HIBP self-audit calls. Requests are validated
 * before invocation and native responses are treated as untrusted data.
 */
export type HibpAccountMode = 'K_ANONYMITY' | 'DIRECT'
export type HibpState =
  | 'NOT_CHECKED'
  | 'SUCCEEDED'
  | 'RATE_LIMITED'
  | 'ACCESS_BLOCKED'
  | 'FAILED'
export type HibpReason =
  | 'COMPLETE'
  | 'NO_RESULTS'
  | 'PARTIAL_RESULTS'
  | 'SELF_AUDIT_AUTHORIZATION_REQUIRED'
  | 'DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED'
  | 'DOMAIN_NOT_PROVIDER_VERIFIED'
  | 'INVALID_API_KEY'
  | 'UPSTREAM_RATE_LIMITED'
  | 'REDIRECT_REFUSED'
  | 'UPSTREAM_ACCESS_BLOCKED'
  | 'TIMEOUT'
  | 'RESPONSE_LIMIT'
  | 'NETWORK_UNAVAILABLE'
  | 'UPSTREAM_UNAVAILABLE'
  | 'UPSTREAM_REJECTED'
  | 'INVALID_RESPONSE'

export interface HibpAccountSearchRequest {
  readonly email: string
  readonly apiKey: string
  readonly mode: HibpAccountMode
  readonly authorizedSelfAudit: boolean
  readonly authorizedDirectIdentifierTransmission: boolean
}

export interface HibpDomainSearchRequest {
  readonly domain: string
  readonly apiKey: string
  readonly authorizedSelfAudit: boolean
}

export interface HibpBreachReference {
  readonly name: string
  readonly sourceUrl: string
}

export interface HibpRequestMetadata {
  readonly sequence: number
  readonly operation:
    | 'EMAIL_K_ANONYMITY'
    | 'EMAIL_DIRECT'
    | 'VERIFY_SUBSCRIBED_DOMAIN'
    | 'DOMAIN_ENUMERATION'
  readonly method: 'GET'
  readonly requestUrl: string
  readonly endpointHost: 'haveibeenpwned.com'
  readonly identifierDisclosure:
    | 'PARTIAL_SHA1_PREFIX'
    | 'DIRECT_EMAIL'
    | 'DIRECT_DOMAIN'
    | 'NONE'
  readonly requestSha256: string
  readonly httpStatus: number | null
  readonly responseBytes: number
  readonly observedAt: string
  readonly retryAfterSeconds: number | null
  readonly apiKeySent: true
  readonly redirectsFollowed: false
}

interface HibpProviderIdentity {
  readonly provider: 'HAVE_I_BEEN_PWNED_V3'
  readonly providerHomeUrl: 'https://haveibeenpwned.com/'
  readonly apiDocumentationUrl: 'https://haveibeenpwned.com/API/v3'
  readonly attribution: 'Have I Been Pwned'
  readonly license: 'CC BY 4.0'
}

export interface HibpAccountSearchResult extends HibpProviderIdentity {
  readonly mode: HibpAccountMode
  readonly state: HibpState
  readonly reason: HibpReason
  readonly breaches: ReadonlyArray<HibpBreachReference>
  readonly requests: ReadonlyArray<HibpRequestMetadata>
  readonly retryAfterSeconds: number | null
  readonly externalRequestMade: boolean
  readonly authorizationConfirmed: boolean
  readonly directTransmissionAuthorized: boolean
  readonly humanReviewRequired: true
}

export interface HibpDomainAccount {
  readonly alias: string
  readonly breaches: ReadonlyArray<HibpBreachReference>
}

export interface HibpDomainSearchResult extends HibpProviderIdentity {
  readonly state: HibpState
  readonly reason: HibpReason
  readonly accounts: ReadonlyArray<HibpDomainAccount>
  readonly requests: ReadonlyArray<HibpRequestMetadata>
  readonly retryAfterSeconds: number | null
  readonly providerVerifiedDomain: boolean
  readonly truncated: boolean
  readonly externalRequestMade: boolean
  readonly authorizationConfirmed: boolean
  readonly humanReviewRequired: true
}

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256 = /^[0-9a-f]{64}$/
const API_KEY = /^[0-9a-f]{32}$/i
const STATES = new Set<HibpState>([
  'NOT_CHECKED', 'SUCCEEDED', 'RATE_LIMITED', 'ACCESS_BLOCKED', 'FAILED',
])
const REASONS = new Set<HibpReason>([
  'COMPLETE', 'NO_RESULTS', 'PARTIAL_RESULTS', 'SELF_AUDIT_AUTHORIZATION_REQUIRED',
  'DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED', 'DOMAIN_NOT_PROVIDER_VERIFIED',
  'INVALID_API_KEY', 'UPSTREAM_RATE_LIMITED', 'REDIRECT_REFUSED',
  'UPSTREAM_ACCESS_BLOCKED', 'TIMEOUT', 'RESPONSE_LIMIT', 'NETWORK_UNAVAILABLE',
  'UPSTREAM_UNAVAILABLE', 'UPSTREAM_REJECTED', 'INVALID_RESPONSE',
])
const OPERATIONS = new Set([
  'EMAIL_K_ANONYMITY', 'EMAIL_DIRECT', 'VERIFY_SUBSCRIBED_DOMAIN',
  'DOMAIN_ENUMERATION',
])
const DISCLOSURES = new Set([
  'PARTIAL_SHA1_PREFIX', 'DIRECT_EMAIL', 'DIRECT_DOMAIN', 'NONE',
])
const SUCCESS_REASONS = new Set<HibpReason>(['COMPLETE', 'NO_RESULTS', 'PARTIAL_RESULTS'])

type RecordValue = Record<string, unknown>

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: RecordValue, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
}

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum
}

function safeText(value: unknown, maximum: number): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= maximum &&
    value.trim() === value && !Array.from(value).some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point < 32 || point === 127
    })
}

function validHibpUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 2_048) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'haveibeenpwned.com' &&
      url.username === '' && url.password === '' && url.hash === '' &&
      url.pathname.startsWith('/api/v3/')
  } catch {
    return false
  }
}

function commandData(value: unknown): unknown {
  if (!isRecord(value) || !exact(value, ['requestId', 'data']) ||
      typeof value.requestId !== 'string' || !UUID.test(value.requestId)) {
    throw new Error('HIBP command response is invalid')
  }
  return value.data
}

function providerIdentityIsValid(value: RecordValue): boolean {
  return value.provider === 'HAVE_I_BEEN_PWNED_V3' &&
    value.providerHomeUrl === 'https://haveibeenpwned.com/' &&
    value.apiDocumentationUrl === 'https://haveibeenpwned.com/API/v3' &&
    value.attribution === 'Have I Been Pwned' && value.license === 'CC BY 4.0'
}

function validBreach(value: unknown): value is HibpBreachReference {
  return isRecord(value) && exact(value, ['name', 'sourceUrl']) &&
    safeText(value.name, 160) && validHibpUrl(value.sourceUrl) &&
    new URL(value.sourceUrl).pathname.startsWith('/api/v3/breach/')
}

function validMetadata(value: unknown, index: number): value is HibpRequestMetadata {
  return isRecord(value) && exact(value, [
    'sequence', 'operation', 'method', 'requestUrl', 'endpointHost',
    'identifierDisclosure', 'requestSha256', 'httpStatus', 'responseBytes',
    'observedAt', 'retryAfterSeconds', 'apiKeySent', 'redirectsFollowed',
  ]) && value.sequence === index + 1 && OPERATIONS.has(String(value.operation)) &&
    value.method === 'GET' && validHibpUrl(value.requestUrl) &&
    value.endpointHost === 'haveibeenpwned.com' &&
    DISCLOSURES.has(String(value.identifierDisclosure)) &&
    typeof value.requestSha256 === 'string' && SHA256.test(value.requestSha256) &&
    (value.httpStatus === null || integer(value.httpStatus, 100, 599)) &&
    integer(value.responseBytes, 0, 1_048_576) &&
    typeof value.observedAt === 'string' && Number.isFinite(Date.parse(value.observedAt)) &&
    (value.retryAfterSeconds === null || integer(value.retryAfterSeconds, 0, 86_400)) &&
    value.apiKeySent === true && value.redirectsFollowed === false
}

function commonResultIsValid(value: RecordValue): boolean {
  if (!providerIdentityIsValid(value) || !STATES.has(value.state as HibpState) ||
      !REASONS.has(value.reason as HibpReason) || !Array.isArray(value.requests) ||
      value.requests.length > 2 ||
      !value.requests.every((metadata, index) => validMetadata(metadata, index)) ||
      !(value.retryAfterSeconds === null || integer(value.retryAfterSeconds, 0, 86_400)) ||
      typeof value.externalRequestMade !== 'boolean' ||
      typeof value.authorizationConfirmed !== 'boolean' ||
      value.humanReviewRequired !== true) return false
  const state = value.state as HibpState
  const reason = value.reason as HibpReason
  return (state === 'SUCCEEDED') === SUCCESS_REASONS.has(reason) &&
    (!value.externalRequestMade || value.authorizationConfirmed) &&
    (value.externalRequestMade === (value.requests.length > 0)) &&
    ((state === 'RATE_LIMITED') === (reason === 'UPSTREAM_RATE_LIMITED')) &&
    (state !== 'RATE_LIMITED' || value.retryAfterSeconds !== null)
}

export function parseHibpAccountResult(value: unknown): HibpAccountSearchResult {
  const data = commandData(value)
  if (!isRecord(data) || !exact(data, [
    'provider', 'providerHomeUrl', 'apiDocumentationUrl', 'attribution', 'license',
    'mode', 'state', 'reason', 'breaches', 'requests', 'retryAfterSeconds',
    'externalRequestMade', 'authorizationConfirmed', 'directTransmissionAuthorized',
    'humanReviewRequired',
  ]) || !commonResultIsValid(data) || !['K_ANONYMITY', 'DIRECT'].includes(String(data.mode)) ||
      !Array.isArray(data.breaches) || data.breaches.length > 1_024 ||
      !data.breaches.every(validBreach) ||
      new Set(data.breaches.map((item) => item.name)).size !== data.breaches.length ||
      typeof data.directTransmissionAuthorized !== 'boolean' ||
      (data.state !== 'SUCCEEDED' && data.breaches.length !== 0) ||
      (data.reason === 'NO_RESULTS' && data.breaches.length !== 0) ||
      (data.mode === 'K_ANONYMITY' && data.directTransmissionAuthorized) ||
      (data.mode === 'DIRECT' && data.externalRequestMade && !data.directTransmissionAuthorized)) {
    throw new Error('HIBP account response is invalid')
  }
  return data as unknown as HibpAccountSearchResult
}

export function parseHibpDomainResult(value: unknown): HibpDomainSearchResult {
  const data = commandData(value)
  if (!isRecord(data) || !exact(data, [
    'provider', 'providerHomeUrl', 'apiDocumentationUrl', 'attribution', 'license',
    'state', 'reason', 'accounts', 'requests', 'retryAfterSeconds',
    'providerVerifiedDomain', 'truncated', 'externalRequestMade',
    'authorizationConfirmed', 'humanReviewRequired',
  ]) || !commonResultIsValid(data) || !Array.isArray(data.accounts) ||
      data.accounts.length > 2_000 || !data.accounts.every((account) =>
        isRecord(account) && exact(account, ['alias', 'breaches']) &&
        safeText(account.alias, 160) && Array.isArray(account.breaches) &&
        account.breaches.length <= 1_024 && account.breaches.every(validBreach)) ||
      new Set(data.accounts.map((account) => isRecord(account) ? account.alias : '')).size !== data.accounts.length ||
      typeof data.providerVerifiedDomain !== 'boolean' || typeof data.truncated !== 'boolean' ||
      (data.state !== 'SUCCEEDED' && data.accounts.length !== 0) ||
      (data.state === 'SUCCEEDED' && !data.providerVerifiedDomain) ||
      (data.accounts.length > 0 && !data.providerVerifiedDomain) ||
      (data.truncated && data.state !== 'SUCCEEDED')) {
    throw new Error('HIBP domain response is invalid')
  }
  return data as unknown as HibpDomainSearchResult
}

function validEmail(value: string): boolean {
  return value.length <= 254 && value.trim() === value && value.split('@').length === 2 &&
    !Array.from(value).some((character) => character <= ' ' || character === '\u007f')
}

function validDomain(value: string): boolean {
  return value.length >= 3 && value.length <= 253 && value.includes('.') &&
    value.trim() === value && /^[A-Za-z0-9.-]+$/.test(value)
}

export async function searchHibpAccount(
  request: HibpAccountSearchRequest,
): Promise<HibpAccountSearchResult> {
  if (!validEmail(request.email) || !API_KEY.test(request.apiKey) ||
      !['K_ANONYMITY', 'DIRECT'].includes(request.mode) ||
      typeof request.authorizedSelfAudit !== 'boolean' ||
      typeof request.authorizedDirectIdentifierTransmission !== 'boolean' ||
      (request.mode === 'DIRECT' && !request.authorizedDirectIdentifierTransmission)) {
    throw new Error('HIBP account request is invalid')
  }
  const { invoke } = await import('@tauri-apps/api/core')
  return parseHibpAccountResult(
    await invoke('core_search_hibp_account', { request }),
  )
}

export async function searchHibpDomain(
  request: HibpDomainSearchRequest,
): Promise<HibpDomainSearchResult> {
  if (!validDomain(request.domain) || !API_KEY.test(request.apiKey) ||
      typeof request.authorizedSelfAudit !== 'boolean') {
    throw new Error('HIBP domain request is invalid')
  }
  const { invoke } = await import('@tauri-apps/api/core')
  return parseHibpDomainResult(
    await invoke('core_search_hibp_domain', { request }),
  )
}

export const hibpBoundaryParsers = {
  account: parseHibpAccountResult,
  domain: parseHibpDomainResult,
}
