/**
 * Network-free investigation-plan boundary. Compilation describes ordered,
 * policy-gated work but never grants approval or performs provider requests.
 */
export type InvestigationIdentifierKind =
  | 'EMAIL'
  | 'USERNAME'
  | 'DOMAIN'
  | 'NAME'
  | 'URL'
export type InvestigationProvider =
  | 'DUCKDUCKGO_HTML'
  | 'GITHUB_USERS'
  | 'HAVE_I_BEEN_PWNED_V3'

export interface InvestigationIdentifier {
  readonly identifierRef: string
  readonly kind: InvestigationIdentifierKind
  readonly value: string
}

export interface InvestigationPlanRequest {
  readonly identifiers: ReadonlyArray<InvestigationIdentifier>
  readonly enabledProviders: ReadonlyArray<InvestigationProvider>
  readonly authorizedSelfAudit: boolean
  readonly hibpApiKeyAvailable: boolean
  readonly hibpKAnonymityAvailable: boolean
  readonly authorizedDirectEmailTransmission: boolean
}

export interface InvestigationPlanStep {
  readonly stepId: string
  readonly identifierRef: string
  readonly identifierKind: InvestigationIdentifierKind
  readonly identifierSha256: string
  readonly provider: InvestigationProvider
  readonly operation:
    | 'PUBLIC_WEB_SEARCH'
    | 'GITHUB_USER_SEARCH'
    | 'HIBP_EMAIL_K_ANONYMITY'
    | 'HIBP_EMAIL_DIRECT'
    | 'HIBP_VERIFIED_DOMAIN_ENUMERATION'
  readonly executionRoute:
    | '/v1/discovery/public/search'
    | '/v1/discovery/hibp/account'
    | '/v1/discovery/hibp/domain'
  readonly transmission:
    | 'DIRECT_PUBLIC_QUERY'
    | 'PARTIAL_SHA1_PREFIX'
    | 'DIRECT_EMAIL'
    | 'PROVIDER_VERIFIED_DOMAIN'
  readonly prerequisites: ReadonlyArray<
    | 'EXPLICIT_SELF_AUDIT_AUTHORIZATION'
    | 'HIBP_API_KEY'
    | 'HIBP_K_ANONYMITY_SUBSCRIPTION'
    | 'DIRECT_IDENTIFIER_TRANSMISSION_AUTHORIZATION'
    | 'PROVIDER_VERIFIED_DOMAIN'
  >
  readonly sequence: number
  readonly executesDuringCompilation: false
  readonly humanReviewRequired: true
}

export interface InvestigationPlan {
  readonly planId: string
  readonly steps: ReadonlyArray<InvestigationPlanStep>
  readonly notices: ReadonlyArray<
    | 'SELF_AUDIT_AUTHORIZATION_REQUIRED'
    | 'HIBP_API_KEY_REQUIRED'
    | 'HIBP_EMAIL_MODE_NOT_AUTHORIZED'
  >
  readonly authorizationConfirmed: boolean
  readonly deterministic: true
  readonly executed: false
}

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const IDENTIFIER_REF = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
const SHA256 = /^[0-9a-f]{64}$/
const PLAN_ID = /^plan-[0-9a-f]{24}$/
const STEP_ID = /^step-[0-9]{3}$/
const KINDS = new Set<InvestigationIdentifierKind>([
  'EMAIL', 'USERNAME', 'DOMAIN', 'NAME', 'URL',
])
const PROVIDERS = new Set<InvestigationProvider>([
  'DUCKDUCKGO_HTML', 'GITHUB_USERS', 'HAVE_I_BEEN_PWNED_V3',
])
const OPERATIONS = new Set([
  'PUBLIC_WEB_SEARCH', 'GITHUB_USER_SEARCH', 'HIBP_EMAIL_K_ANONYMITY',
  'HIBP_EMAIL_DIRECT', 'HIBP_VERIFIED_DOMAIN_ENUMERATION',
])
const ROUTES = new Set([
  '/v1/discovery/public/search', '/v1/discovery/hibp/account',
  '/v1/discovery/hibp/domain',
])
const TRANSMISSIONS = new Set([
  'DIRECT_PUBLIC_QUERY', 'PARTIAL_SHA1_PREFIX', 'DIRECT_EMAIL',
  'PROVIDER_VERIFIED_DOMAIN',
])
const PREREQUISITES = new Set([
  'EXPLICIT_SELF_AUDIT_AUTHORIZATION', 'HIBP_API_KEY',
  'HIBP_K_ANONYMITY_SUBSCRIPTION',
  'DIRECT_IDENTIFIER_TRANSMISSION_AUTHORIZATION', 'PROVIDER_VERIFIED_DOMAIN',
])
const NOTICES = new Set([
  'SELF_AUDIT_AUTHORIZATION_REQUIRED', 'HIBP_API_KEY_REQUIRED',
  'HIBP_EMAIL_MODE_NOT_AUTHORIZED',
])

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

function safeValue(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 &&
    new TextEncoder().encode(value).byteLength <= 1_024 && value.trim() === value &&
    !Array.from(value).some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point < 32 || point === 127
    })
}

function parseCommandData(value: unknown): unknown {
  if (!isRecord(value) || !exact(value, ['requestId', 'data']) ||
      typeof value.requestId !== 'string' || !UUID.test(value.requestId)) {
    throw new Error('Investigation plan command response is invalid')
  }
  return value.data
}

function validStep(value: unknown, index: number): value is InvestigationPlanStep {
  return isRecord(value) && exact(value, [
    'stepId', 'identifierRef', 'identifierKind', 'identifierSha256', 'provider',
    'operation', 'executionRoute', 'transmission', 'prerequisites', 'sequence',
    'executesDuringCompilation', 'humanReviewRequired',
  ]) && typeof value.stepId === 'string' && STEP_ID.test(value.stepId) &&
    value.stepId === `step-${String(index + 1).padStart(3, '0')}` &&
    typeof value.identifierRef === 'string' && IDENTIFIER_REF.test(value.identifierRef) &&
    KINDS.has(value.identifierKind as InvestigationIdentifierKind) &&
    typeof value.identifierSha256 === 'string' && SHA256.test(value.identifierSha256) &&
    PROVIDERS.has(value.provider as InvestigationProvider) &&
    OPERATIONS.has(String(value.operation)) && ROUTES.has(String(value.executionRoute)) &&
    TRANSMISSIONS.has(String(value.transmission)) && Array.isArray(value.prerequisites) &&
    value.prerequisites.length >= 1 && value.prerequisites.length <= 5 &&
    value.prerequisites.every((item) => PREREQUISITES.has(String(item))) &&
    new Set(value.prerequisites).size === value.prerequisites.length &&
    value.sequence === index + 1 && value.executesDuringCompilation === false &&
    value.humanReviewRequired === true
}

export function parseInvestigationPlan(value: unknown): InvestigationPlan {
  const data = parseCommandData(value)
  if (!isRecord(data) || !exact(data, [
    'planId', 'steps', 'notices', 'authorizationConfirmed', 'deterministic',
    'executed',
  ]) || typeof data.planId !== 'string' || !PLAN_ID.test(data.planId) ||
      !Array.isArray(data.steps) || data.steps.length > 128 ||
      !data.steps.every(validStep) || !Array.isArray(data.notices) ||
      data.notices.length > 3 || !data.notices.every((item) => NOTICES.has(String(item))) ||
      new Set(data.notices).size !== data.notices.length ||
      typeof data.authorizationConfirmed !== 'boolean' ||
      (!data.authorizationConfirmed && data.steps.length !== 0) ||
      data.deterministic !== true || data.executed !== false) {
    throw new Error('Investigation plan response is invalid')
  }
  return data as unknown as InvestigationPlan
}

function requestIsValid(request: InvestigationPlanRequest): boolean {
  return request.identifiers.length >= 1 && request.identifiers.length <= 32 &&
    request.identifiers.every((identifier) =>
      IDENTIFIER_REF.test(identifier.identifierRef) && KINDS.has(identifier.kind) &&
      safeValue(identifier.value)) &&
    new Set(request.identifiers.map((identifier) => identifier.identifierRef)).size ===
      request.identifiers.length && request.enabledProviders.length >= 1 &&
    request.enabledProviders.length <= 3 &&
    request.enabledProviders.every((provider) => PROVIDERS.has(provider)) &&
    new Set(request.enabledProviders).size === request.enabledProviders.length &&
    [request.authorizedSelfAudit, request.hibpApiKeyAvailable,
      request.hibpKAnonymityAvailable, request.authorizedDirectEmailTransmission]
      .every((value) => typeof value === 'boolean')
}

export async function compileInvestigationPlan(
  request: InvestigationPlanRequest,
): Promise<InvestigationPlan> {
  if (!requestIsValid(request)) {
    throw new Error('Investigation plan request is invalid')
  }
  const { invoke } = await import('@tauri-apps/api/core')
  return parseInvestigationPlan(
    await invoke('core_compile_investigation_plan', { request }),
  )
}

export const investigationPlanBoundaryParsers = { plan: parseInvestigationPlan }
