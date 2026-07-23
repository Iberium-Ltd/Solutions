/**
 * Phase 3 renderer-to-core boundary. Every native reply is parsed against a
 * closed contract before profile, intake, entity, or graph state reaches UI.
 */
import type {
  EntityDecisionRequest,
  EntityReviewRequest,
  EntityReviewResult,
  EntitySummary,
  FileIntakeRequest,
  GraphEdge,
  GraphEdgeEvidence,
  GraphNode,
  GraphSnapshot,
  GraphSnapshotRequest,
  IntakeReceipt,
  PasteIntakeRequest,
  ProfileCreateRequest,
  ProfileDeleteRequest,
  ProfileDeleteResult,
  ProfileListResult,
  ProfileSummary,
} from '../../../../packages/contracts/src/generated/api'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const TOKEN_PATTERN = /^[A-Z][A-Z0-9_]*$/
const SENSITIVITIES = new Set(['PUBLIC', 'SENSITIVE', 'HIGHLY_SENSITIVE'])
const REVIEW_STATES = new Set([
  'UNREVIEWED',
  'CONFIRMED',
  'PROBABLE',
  'POSSIBLE',
  'FALSE_POSITIVE',
  'EXCLUDED',
])
const TEMPORAL_STATES = new Set(['CURRENT', 'HISTORICAL', 'UNKNOWN'])
const SEARCH_POLICIES = new Set([
  'ALLOW',
  'REQUIRE_APPROVAL',
  'STORE_ONLY',
  'DENY',
])
const TRANSMISSION_POLICIES = new Set([
  'LOCAL_ONLY',
  'POLICY_CONTROLLED',
  'REQUIRE_EACH_APPROVAL',
  'NEVER',
])
const GRAPH_VISIBILITIES = new Set([
  'PUBLICLY_ATTRIBUTABLE',
  'PUBLIC_PSEUDONYMOUS',
  'PRIVATELY_LINKABLE',
  'HISTORICAL_RESIDUE',
  'PRIVATE_ONLY',
  'UNKNOWN',
])
const GRAPH_EVIDENCE_DISPOSITIONS = new Set(['SUPPORTS', 'CONTRADICTS'])
const LOCAL_AI_INTAKE_STATUSES = new Set([
  'NOT_REQUESTED',
  'DISABLED',
  'SUCCEEDED',
  'TIMEOUT',
  'UNAVAILABLE',
  'INVALID_RESPONSE',
])
const LOCAL_AI_PROVIDERS = new Set(['OLLAMA', 'OPENAI_COMPATIBLE'])
const ENTITY_ORIGIN_KINDS = new Set([
  'USER_INPUT',
  'DETERMINISTIC',
  'LOCAL_MODEL',
  'MANUAL',
])
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const MAX_ENTITY_ORIGINS = 32
const MAX_ENTITY_ORIGIN_PAGE_SIZE = 12
let nativeCoreModule: Promise<typeof import('@tauri-apps/api/core')> | null = null

export interface EntityOriginProjection {
  readonly sourceId: string
  readonly sourceDisplayName: string
  readonly sourceSha256: string
  readonly segmentId: string
  readonly segmentIndex: number
  readonly segmentLocator: string
  readonly sourceSpanStart: number | null
  readonly sourceSpanEnd: number | null
  readonly extractionRunId: string | null
  readonly extractorKind: string | null
  readonly extractorName: string | null
  readonly extractorVersion: string | null
  readonly originKind: string
  readonly observedAtUs: number
  readonly confidenceMicros: number
  readonly explanation: string
}

export interface EntityOriginPageRequest {
  readonly profileId: string
  readonly entityId: string
  readonly offset: number
  readonly limit: number
}

export interface EntityOriginPage {
  readonly profileId: string
  readonly entityId: string
  readonly offset: number
  readonly limit: number
  readonly origins: ReadonlyArray<EntityOriginProjection>
  readonly total: number
  readonly hasMore: boolean
}

export type EntitySummaryWithOrigins = Omit<
  EntitySummary,
  'origins' | 'originsTruncated'
> & {
  readonly origins: ReadonlyArray<EntityOriginProjection>
  readonly originsTruncated: boolean
}

export type EntityReviewWithOrigins = Omit<EntityReviewResult, 'entities'> & {
  readonly entities: ReadonlyArray<EntitySummaryWithOrigins>
}

function loadNativeCore() {
  nativeCoreModule ??= import('@tauri-apps/api/core')
  return nativeCoreModule
}

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
    !Array.from(value).some((character) => {
      const codePoint = character.codePointAt(0) ?? 0
      return (
        codePoint <= 8 ||
        codePoint === 11 ||
        codePoint === 12 ||
        (codePoint >= 14 && codePoint <= 31) ||
        codePoint === 127
      )
    })
  )
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !UUID_PATTERN.test(String(value.requestId))
  ) {
    throw new Error('Phase 3 command response is invalid')
  }
  return value.data
}

function isProfileSummary(value: unknown): value is ProfileSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'profileId',
      'displayLabel',
      'purpose',
      'status',
      'revision',
    ]) &&
    UUID_PATTERN.test(String(value.profileId)) &&
    isBoundedString(value.displayLabel, 1, 80) &&
    isBoundedString(value.purpose, 1, 240) &&
    typeof value.status === 'string' &&
    ['DRAFT', 'ACTIVE', 'ARCHIVED', 'PURGE_PENDING'].includes(value.status) &&
    Number.isSafeInteger(value.revision) &&
    Number(value.revision) >= 1
  )
}

function parseProfileSummary(value: unknown): ProfileSummary {
  const data = commandData(value)
  if (!isProfileSummary(data)) {
    throw new Error('Phase 3 profile response is invalid')
  }
  return data
}

function parseProfileList(value: unknown): ProfileListResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profiles', 'hasMore']) ||
    !Array.isArray(data.profiles) ||
    data.profiles.length > 100 ||
    !data.profiles.every(isProfileSummary) ||
    new Set(data.profiles.map((profile) => profile.profileId)).size !==
      data.profiles.length ||
    typeof data.hasMore !== 'boolean'
  ) {
    throw new Error('Phase 3 profile list response is invalid')
  }
  return data as unknown as ProfileListResult
}

function parseProfileDeleteResult(value: unknown): ProfileDeleteResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'deletedRows']) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !Number.isSafeInteger(data.deletedRows) ||
    Number(data.deletedRows) < 1
  ) {
    throw new Error('Phase 3 profile deletion response is invalid')
  }
  return data as unknown as ProfileDeleteResult
}

function parseIntakeReceipt(value: unknown): IntakeReceipt {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'sourceId',
      'profileId',
      'state',
      'sourceKind',
      'segmentCount',
      'candidateCount',
      'duplicateCount',
      'quarantineCount',
      'revision',
      'localAiStatus',
      'localAiProvider',
      'localAiModel',
      'localAiEngineVersion',
      'localAiSuggestionCount',
    ]) ||
    !UUID_PATTERN.test(String(data.sourceId)) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    typeof data.state !== 'string' ||
    !TOKEN_PATTERN.test(data.state) ||
    typeof data.sourceKind !== 'string' ||
    !TOKEN_PATTERN.test(data.sourceKind) ||
    !isNonNegativeInteger(data.segmentCount) ||
    !isNonNegativeInteger(data.candidateCount) ||
    !isNonNegativeInteger(data.duplicateCount) ||
    !isNonNegativeInteger(data.quarantineCount) ||
    !Number.isSafeInteger(data.revision) ||
    Number(data.revision) < 1 ||
    typeof data.localAiStatus !== 'string' ||
    !LOCAL_AI_INTAKE_STATUSES.has(data.localAiStatus) ||
    !isNonNegativeInteger(data.localAiSuggestionCount) ||
    Number(data.localAiSuggestionCount) > 64 ||
    (data.localAiStatus !== 'SUCCEEDED' &&
      Number(data.localAiSuggestionCount) !== 0)
  ) {
    throw new Error('Phase 3 intake response is invalid')
  }
  const enrichmentAttempted = !['NOT_REQUESTED', 'DISABLED'].includes(
    data.localAiStatus,
  )
  const identityPresent =
    typeof data.localAiProvider === 'string' &&
    LOCAL_AI_PROVIDERS.has(data.localAiProvider) &&
    isBoundedString(data.localAiModel, 1, 256) &&
    isBoundedString(data.localAiEngineVersion, 1, 48)
  const identityAbsent =
    data.localAiProvider === null &&
    data.localAiModel === null &&
    data.localAiEngineVersion === null
  if (
    (enrichmentAttempted && !identityPresent) ||
    (!enrichmentAttempted && !identityAbsent)
  ) {
    throw new Error('Phase 3 intake response is invalid')
  }
  return data as unknown as IntakeReceipt
}

function isEntityOrigin(value: unknown): value is EntityOriginProjection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'sourceId',
      'sourceDisplayName',
      'sourceSha256',
      'segmentId',
      'segmentIndex',
      'segmentLocator',
      'sourceSpanStart',
      'sourceSpanEnd',
      'extractionRunId',
      'extractorKind',
      'extractorName',
      'extractorVersion',
      'originKind',
      'observedAtUs',
      'confidenceMicros',
      'explanation',
    ]) ||
    !UUID_PATTERN.test(String(value.sourceId)) ||
    !isBoundedString(value.sourceDisplayName, 1, 255) ||
    typeof value.sourceSha256 !== 'string' ||
    !SHA256_PATTERN.test(value.sourceSha256) ||
    !UUID_PATTERN.test(String(value.segmentId)) ||
    !isNonNegativeInteger(value.segmentIndex) ||
    Number(value.segmentIndex) > 1_000_000 ||
    !isBoundedString(value.segmentLocator, 1, 16_384) ||
    typeof value.originKind !== 'string' ||
    !ENTITY_ORIGIN_KINDS.has(value.originKind) ||
    !Number.isSafeInteger(value.observedAtUs) ||
    Number(value.observedAtUs) < 1 ||
    !isNonNegativeInteger(value.confidenceMicros) ||
    Number(value.confidenceMicros) > 1_000_000 ||
    !isBoundedString(value.explanation, 1, 2_048)
  ) {
    return false
  }

  const spanStart = value.sourceSpanStart
  const spanEnd = value.sourceSpanEnd
  const spanAbsent = spanStart === null && spanEnd === null
  const spanPresent =
    isNonNegativeInteger(spanStart) &&
    isNonNegativeInteger(spanEnd) &&
    Number(spanStart) <= 1_048_576 &&
    Number(spanEnd) <= 1_048_576 &&
    Number(spanEnd) > Number(spanStart)
  if (!spanAbsent && !spanPresent) return false

  const extractorValues = [
    value.extractionRunId,
    value.extractorKind,
    value.extractorName,
    value.extractorVersion,
  ]
  const extractorAbsent = extractorValues.every((item) => item === null)
  const extractorPresent =
    UUID_PATTERN.test(String(value.extractionRunId)) &&
    isBoundedString(value.extractorKind, 1, 24) &&
    isBoundedString(value.extractorName, 1, 96) &&
    isBoundedString(value.extractorVersion, 1, 48)
  return extractorAbsent || extractorPresent
}

function isEntitySummary(value: unknown): value is EntitySummaryWithOrigins {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'entityId',
      'entityType',
      'displayValue',
      'sensitivity',
      'reviewState',
      'temporalState',
      'searchPolicy',
      'transmissionPolicy',
      'confidenceMicros',
      'provenanceLabel',
      'origins',
      'originsTruncated',
      'revision',
    ]) &&
    UUID_PATTERN.test(String(value.entityId)) &&
    isBoundedString(value.entityType, 1, 96) &&
    isBoundedString(value.displayValue, 1, 512) &&
    SENSITIVITIES.has(String(value.sensitivity)) &&
    REVIEW_STATES.has(String(value.reviewState)) &&
    TEMPORAL_STATES.has(String(value.temporalState)) &&
    SEARCH_POLICIES.has(String(value.searchPolicy)) &&
    TRANSMISSION_POLICIES.has(String(value.transmissionPolicy)) &&
    Number.isSafeInteger(value.confidenceMicros) &&
    Number(value.confidenceMicros) >= 0 &&
    Number(value.confidenceMicros) <= 1_000_000 &&
    isBoundedString(value.provenanceLabel, 1, 160) &&
    Array.isArray(value.origins) &&
    value.origins.length >= 1 &&
    value.origins.length <= MAX_ENTITY_ORIGINS &&
    value.origins.every(isEntityOrigin) &&
    typeof value.originsTruncated === 'boolean' &&
    (!value.originsTruncated || value.origins.length === MAX_ENTITY_ORIGINS) &&
    Number.isSafeInteger(value.revision) &&
    Number(value.revision) >= 1
  )
}

function parseEntitySummary(value: unknown): EntitySummaryWithOrigins {
  const data = commandData(value)
  if (!isEntitySummary(data)) {
    throw new Error('Phase 3 entity response is invalid')
  }
  return data
}

function parseEntityReview(value: unknown): EntityReviewWithOrigins {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'entities',
      'quarantineCount',
      'hasMore',
    ]) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !Array.isArray(data.entities) ||
    data.entities.length > 100 ||
    !data.entities.every(isEntitySummary) ||
    new Set(data.entities.map((entity) => entity.entityId)).size !==
      data.entities.length ||
    !isNonNegativeInteger(data.quarantineCount) ||
    typeof data.hasMore !== 'boolean'
  ) {
    throw new Error('Phase 3 entity review response is invalid')
  }
  return data as unknown as EntityReviewWithOrigins
}

function parseEntityOriginPage(value: unknown): EntityOriginPage {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'entityId',
      'offset',
      'limit',
      'origins',
      'total',
      'hasMore',
    ]) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !UUID_PATTERN.test(String(data.entityId)) ||
    !isNonNegativeInteger(data.offset) ||
    Number(data.offset) > 100_000_000 ||
    !Number.isSafeInteger(data.limit) ||
    Number(data.limit) < 1 ||
    Number(data.limit) > MAX_ENTITY_ORIGIN_PAGE_SIZE ||
    !Array.isArray(data.origins) ||
    data.origins.length > Number(data.limit) ||
    !data.origins.every(isEntityOrigin) ||
    !isNonNegativeInteger(data.total) ||
    typeof data.hasMore !== 'boolean' ||
    (data.origins.length > 0 &&
      Number(data.offset) + data.origins.length > Number(data.total)) ||
    (Number(data.offset) < Number(data.total) && data.origins.length === 0) ||
    data.hasMore !==
      (Number(data.offset) + data.origins.length < Number(data.total))
  ) {
    throw new Error('Phase 3 entity origin page response is invalid')
  }
  return data as unknown as EntityOriginPage
}

function isGraphNode(value: unknown): value is GraphNode {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'nodeId',
      'nodeType',
      'displayLabel',
      'sensitivity',
      'entityId',
    ]) &&
    UUID_PATTERN.test(String(value.nodeId)) &&
    isBoundedString(value.nodeType, 1, 96) &&
    isBoundedString(value.displayLabel, 1, 512) &&
    SENSITIVITIES.has(String(value.sensitivity)) &&
    (value.entityId === null || UUID_PATTERN.test(String(value.entityId)))
  )
}

function isGraphEvidence(value: unknown): value is GraphEdgeEvidence {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'sourceId',
      'segmentOrdinal',
      'sourceSpanStart',
      'sourceSpanEnd',
      'disposition',
      'confidenceMicros',
      'visibility',
      'observedAtUs',
      'originType',
      'explanation',
    ]) ||
    !UUID_PATTERN.test(String(value.sourceId)) ||
    !isNonNegativeInteger(value.segmentOrdinal) ||
    Number(value.segmentOrdinal) > 1_000_000 ||
    !GRAPH_EVIDENCE_DISPOSITIONS.has(String(value.disposition)) ||
    !isNonNegativeInteger(value.confidenceMicros) ||
    Number(value.confidenceMicros) > 1_000_000 ||
    !GRAPH_VISIBILITIES.has(String(value.visibility)) ||
    !Number.isSafeInteger(value.observedAtUs) ||
    Number(value.observedAtUs) < 1 ||
    !isBoundedString(value.originType, 1, 64) ||
    !isBoundedString(value.explanation, 1, 160)
  ) {
    return false
  }

  const start = value.sourceSpanStart
  const end = value.sourceSpanEnd
  if (start === null && end === null) return true
  return (
    isNonNegativeInteger(start) &&
    isNonNegativeInteger(end) &&
    Number(start) <= 1_048_576 &&
    Number(end) <= 1_048_576 &&
    Number(end) > Number(start)
  )
}

function isGraphEdge(value: unknown): value is GraphEdge {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'edgeId',
      'fromNodeId',
      'toNodeId',
      'edgeType',
      'confidenceMicros',
      'originType',
      'explanation',
      'supportCount',
      'contradictionCount',
      'evidence',
      'evidenceTruncated',
    ]) &&
    UUID_PATTERN.test(String(value.edgeId)) &&
    UUID_PATTERN.test(String(value.fromNodeId)) &&
    UUID_PATTERN.test(String(value.toNodeId)) &&
    value.fromNodeId !== value.toNodeId &&
    isBoundedString(value.edgeType, 1, 96) &&
    isNonNegativeInteger(value.confidenceMicros) &&
    Number(value.confidenceMicros) <= 1_000_000 &&
    isBoundedString(value.originType, 1, 64) &&
    isBoundedString(value.explanation, 1, 2_048) &&
    isNonNegativeInteger(value.supportCount) &&
    Number(value.supportCount) <= 100_000 &&
    isNonNegativeInteger(value.contradictionCount) &&
    Number(value.contradictionCount) <= 100_000 &&
    Array.isArray(value.evidence) &&
    value.evidence.length <= 8 &&
    value.evidence.every(isGraphEvidence) &&
    value.evidence.length <=
      Number(value.supportCount) + Number(value.contradictionCount) &&
    typeof value.evidenceTruncated === 'boolean'
  )
}

function parseGraphSnapshot(value: unknown): GraphSnapshot {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'nodes', 'edges', 'truncated']) ||
    !UUID_PATTERN.test(String(data.profileId)) ||
    !Array.isArray(data.nodes) ||
    data.nodes.length > 500 ||
    !data.nodes.every(isGraphNode) ||
    !Array.isArray(data.edges) ||
    data.edges.length > 250 ||
    !data.edges.every(isGraphEdge) ||
    typeof data.truncated !== 'boolean'
  ) {
    throw new Error('Phase 3 graph response is invalid')
  }

  const nodeIds = new Set(data.nodes.map((node) => node.nodeId))
  const edgeIds = new Set(data.edges.map((edge) => edge.edgeId))
  const evidenceCount = data.edges.reduce(
    (total, edge) => total + edge.evidence.length,
    0,
  )
  if (
    nodeIds.size !== data.nodes.length ||
    edgeIds.size !== data.edges.length ||
    evidenceCount > 500 ||
    data.edges.some(
      (edge) =>
        !nodeIds.has(edge.fromNodeId) || !nodeIds.has(edge.toNodeId),
    )
  ) {
    throw new Error('Phase 3 graph response is invalid')
  }
  return data as unknown as GraphSnapshot
}

async function invokePhase3(
  command:
    | 'core_create_profile'
    | 'core_delete_profile'
    | 'core_intake_paste'
    | 'core_intake_file'
    | 'core_review_entities'
    | 'core_list_entity_origins'
    | 'core_decide_entity'
    | 'core_graph_snapshot',
  request: object,
): Promise<unknown> {
  const { invoke } = await loadNativeCore()
  return invoke<unknown>(command, { request })
}

export async function createProfile(
  request: ProfileCreateRequest,
): Promise<ProfileSummary> {
  return parseProfileSummary(await invokePhase3('core_create_profile', request))
}

export async function listProfiles(): Promise<ProfileListResult> {
  const { invoke } = await loadNativeCore()
  return parseProfileList(await invoke<unknown>('core_list_profiles'))
}

export async function deleteProfile(
  request: ProfileDeleteRequest,
): Promise<ProfileDeleteResult> {
  const result = parseProfileDeleteResult(
    await invokePhase3('core_delete_profile', request),
  )
  if (result.profileId !== request.profileId) {
    throw new Error('Phase 3 profile deletion scope mismatch')
  }
  return result
}

export async function submitPastedIntake(
  request: PasteIntakeRequest,
): Promise<IntakeReceipt> {
  return parseIntakeReceipt(await invokePhase3('core_intake_paste', request))
}

export async function submitFileIntake(
  request: FileIntakeRequest,
): Promise<IntakeReceipt> {
  return parseIntakeReceipt(await invokePhase3('core_intake_file', request))
}

export async function reviewEntities(
  request: EntityReviewRequest,
): Promise<EntityReviewWithOrigins> {
  return parseEntityReview(await invokePhase3('core_review_entities', request))
}

export async function loadEntityOrigins(
  request: EntityOriginPageRequest,
): Promise<EntityOriginPage> {
  const result = parseEntityOriginPage(
    await invokePhase3('core_list_entity_origins', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.entityId !== request.entityId ||
    result.offset !== request.offset ||
    result.limit !== request.limit
  ) {
    throw new Error('Phase 3 entity origin page scope mismatch')
  }
  return result
}

export async function decideEntity(
  request: EntityDecisionRequest,
): Promise<EntitySummaryWithOrigins> {
  return parseEntitySummary(await invokePhase3('core_decide_entity', request))
}

export async function loadGraphSnapshot(
  request: GraphSnapshotRequest,
): Promise<GraphSnapshot> {
  return parseGraphSnapshot(await invokePhase3('core_graph_snapshot', request))
}

export const phase3BoundaryParsers = {
  profile: parseProfileSummary,
  profileDelete: parseProfileDeleteResult,
  profiles: parseProfileList,
  intake: parseIntakeReceipt,
  entity: parseEntitySummary,
  review: parseEntityReview,
  origins: parseEntityOriginPage,
  graph: parseGraphSnapshot,
}
