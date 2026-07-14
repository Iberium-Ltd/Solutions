import type {
  ProviderCatalogRequest,
  ProviderCatalogResult,
  QueryDryRunRequest,
  QueryPlanCell,
  QueryPlanRequest,
  QueryPlanResult,
  QueryProviderSummary,
} from '../../../../packages/contracts/src/generated/api'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const PROVIDER_PATTERN = /^[a-z][a-z0-9_-]{2,63}$/
const TOKEN_PATTERN = /^[A-Z][A-Z0-9_]{0,95}$/
const POLICY_MODES = new Set(['LOCAL_ONLY', 'EU_ONLY', 'CUSTOM'])
const CHECK_STATES = new Set([
  'PLANNED',
  'APPROVAL_REQUIRED',
  'NOT_CHECKED',
  'BLOCKED',
  'DISPATCHED',
  'SUCCEEDED',
  'CHECK_FAILED',
])
const COVERAGE_OUTCOMES = new Set([
  'NOT_CHECKED',
  'ACCESS_BLOCKED',
  'DISPATCHED',
  'SUCCEEDED',
  'CHECK_FAILED',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  )
}

function isBoundedString(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string {
  return (
    typeof value === 'string' &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.trim() === value &&
    !Array.from(value).some((character) => {
      const codePoint = character.codePointAt(0) ?? 0
      return codePoint < 32 || codePoint === 127
    })
  )
}

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !UUID_PATTERN.test(String(value.requestId))
  ) {
    throw new Error('Query-policy command response is invalid')
  }
  return value.data
}

function isProvider(value: unknown): value is QueryProviderSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'providerId',
      'displayName',
      'operator',
      'adapterMode',
      'accessBasis',
      'processingRegions',
      'networkAccess',
      'sendsIdentifiers',
      'enabled',
      'retentionKnown',
    ]) &&
    typeof value.providerId === 'string' &&
    PROVIDER_PATTERN.test(value.providerId) &&
    isBoundedString(value.displayName, 1, 96) &&
    isBoundedString(value.operator, 1, 128) &&
    ['DRY_RUN', 'MANUAL_LOCAL'].includes(String(value.adapterMode)) &&
    value.accessBasis === 'LOCAL_ONLY' &&
    Array.isArray(value.processingRegions) &&
    value.processingRegions.length === 0 &&
    value.networkAccess === false &&
    value.sendsIdentifiers === false &&
    value.enabled === true &&
    value.retentionKnown === true
  )
}

function parseProviderCatalog(value: unknown): ProviderCatalogResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'providers',
      'externalProviderCount',
    ]) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !Array.isArray(data.providers) ||
    data.providers.length < 1 ||
    data.providers.length > 8 ||
    !data.providers.every(isProvider) ||
    new Set(data.providers.map((provider) => provider.providerId)).size !==
      data.providers.length ||
    data.externalProviderCount !== 0
  ) {
    throw new Error('Query-policy provider catalog is invalid')
  }
  return data as unknown as ProviderCatalogResult
}

function isQueryCell(value: unknown): value is QueryPlanCell {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'checkId',
      'entityId',
      'providerId',
      'maskedValue',
      'entityType',
      'queryClass',
      'state',
      'outcome',
      'reasonCode',
      'requiresApproval',
      'revision',
    ]) ||
    !UUID_PATTERN.test(String(value.checkId)) ||
    !UUID_PATTERN.test(String(value.entityId)) ||
    typeof value.providerId !== 'string' ||
    !PROVIDER_PATTERN.test(value.providerId) ||
    !isBoundedString(value.maskedValue, 1, 512) ||
    !isBoundedString(value.entityType, 1, 32) ||
    value.queryClass !== 'EXACT' ||
    !CHECK_STATES.has(String(value.state)) ||
    !COVERAGE_OUTCOMES.has(String(value.outcome)) ||
    !isBoundedString(value.reasonCode, 1, 96) ||
    !TOKEN_PATTERN.test(value.reasonCode) ||
    typeof value.requiresApproval !== 'boolean' ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 1
  ) {
    return false
  }
  const outcomeByState: Record<string, string> = {
    PLANNED: 'NOT_CHECKED',
    APPROVAL_REQUIRED: 'NOT_CHECKED',
    NOT_CHECKED: 'NOT_CHECKED',
    BLOCKED: 'ACCESS_BLOCKED',
    DISPATCHED: 'DISPATCHED',
    SUCCEEDED: 'SUCCEEDED',
    CHECK_FAILED: 'CHECK_FAILED',
  }
  return (
    outcomeByState[String(value.state)] === value.outcome &&
    value.requiresApproval === (value.state === 'APPROVAL_REQUIRED')
  )
}

function parseQueryPlan(value: unknown): QueryPlanResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'runId',
      'profileId',
      'policyMode',
      'cells',
      'plannedCount',
      'approvalRequiredCount',
      'notCheckedCount',
      'blockedCount',
    ]) ||
    !UUID_PATTERN.test(String(data.runId)) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !POLICY_MODES.has(String(data.policyMode)) ||
    !Array.isArray(data.cells) ||
    data.cells.length > 200 ||
    !data.cells.every(isQueryCell) ||
    new Set(data.cells.map((cell) => cell.checkId)).size !== data.cells.length
  ) {
    throw new Error('Query-policy plan is invalid')
  }
  const counts = {
    plannedCount: data.cells.filter((cell) => cell.state === 'PLANNED').length,
    approvalRequiredCount: data.cells.filter(
      (cell) => cell.state === 'APPROVAL_REQUIRED',
    ).length,
    notCheckedCount: data.cells.filter((cell) => cell.state === 'NOT_CHECKED')
      .length,
    blockedCount: data.cells.filter((cell) => cell.state === 'BLOCKED').length,
  }
  if (
    data.cells.some((cell) =>
      ['DISPATCHED', 'SUCCEEDED', 'CHECK_FAILED'].includes(cell.state),
    ) ||
    Object.entries(counts).some(([key, count]) => data[key] !== count)
  ) {
    throw new Error('Query-policy plan counts are invalid')
  }
  return data as unknown as QueryPlanResult
}

function parseQueryCell(value: unknown): QueryPlanCell {
  const data = commandData(value)
  if (!isQueryCell(data)) {
    throw new Error('Query-policy check response is invalid')
  }
  return data
}

async function invokeQuery(command: string, request: object): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<unknown>(command, { request })
}

export async function loadQueryProviders(
  request: ProviderCatalogRequest,
): Promise<ProviderCatalogResult> {
  const result = parseProviderCatalog(
    await invokeQuery('core_query_providers', request),
  )
  if (result.profileId !== request.profileId) {
    throw new Error('Query-policy profile binding is invalid')
  }
  return result
}

export async function createQueryPlan(
  request: QueryPlanRequest,
): Promise<QueryPlanResult> {
  const result = parseQueryPlan(
    await invokeQuery('core_create_query_plan', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.policyMode !== request.policyMode ||
    result.cells.some((cell) => !request.providerIds.includes(cell.providerId))
  ) {
    throw new Error('Query-policy plan binding is invalid')
  }
  return result
}

export async function executeQueryDryRun(
  request: QueryDryRunRequest,
): Promise<QueryPlanCell> {
  const result = parseQueryCell(
    await invokeQuery('core_execute_query_dry_run', request),
  )
  if (
    result.checkId !== request.checkId ||
    result.revision < request.expectedRevision ||
    result.revision > request.expectedRevision + 3
  ) {
    throw new Error('Query-policy check binding is invalid')
  }
  return result
}

export const queryBoundaryParsers = {
  catalog: parseProviderCatalog,
  plan: parseQueryPlan,
  cell: parseQueryCell,
}
