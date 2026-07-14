const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const CODE_PATTERN = /^[A-Z][A-Z0-9_]{1,63}$/
const OPAQUE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

const SNAPSHOT_RUN_STATES = new Set([
  'COMPLETED',
  'PARTIAL',
  'CANCELLED',
  'FAILED',
] as const)
const PROVIDER_COVERAGE_STATES = new Set([
  'COMPLETE',
  'NOT_CHECKED',
  'BLOCKED',
  'CHECK_FAILED',
] as const)
const FINDING_DIFF_STATES = new Set([
  'NEW',
  'CHANGED',
  'REMOVED',
  'UNCHANGED',
  'REAPPEARED',
] as const)
const INCOMPLETE_REASONS = new Set([
  'BASELINE_RUN_INCOMPLETE',
  'CURRENT_RUN_INCOMPLETE',
  'BASELINE_COVERAGE_INCOMPLETE',
  'CURRENT_COVERAGE_INCOMPLETE',
  'UNRESOLVED_ABSENCE',
  'HISTORY_GAP',
] as const)
const REMEDIATION_ACTIONS = new Set([
  'MONITOR',
  'PRESERVE_EVIDENCE',
  'DELETE_OWNED_ACCOUNT',
  'REQUEST_CORRECTION',
  'DRAFT_ERASURE_OR_DEINDEX',
  'DRAFT_IMPERSONATION_REPORT',
  'CONTACT',
  'ESCALATE',
  'MARK_LEGALLY_PERSISTENT',
] as const)
const ACTION_DISPOSITIONS = new Set([
  'LOCAL_ONLY',
  'DRAFT',
  'REQUIRE_EXPLICIT_APPROVAL',
] as const)
const REMEDIATION_STATUSES = new Set([
  'OPEN',
  'IN_PROGRESS',
  'AWAITING_EXPLICIT_APPROVAL',
  'MONITORING',
  'RESOLVED',
  'CLOSED',
] as const)
const REMEDIATION_EVENT_TYPES = new Set([
  'CASE_CREATED',
  'DRAFT_UPDATED',
  'APPROVAL_REQUIRED',
  'STATUS_CHANGED',
  'DEADLINE_CHANGED',
  'EVIDENCE_LINKED',
  'PROVIDER_RESPONSE_RECORDED',
  'REAPPEARANCE_RECORDED',
] as const)

const LOCAL_ACTIONS = new Set<Phase6RemediationAction>([
  'MONITOR',
  'PRESERVE_EVIDENCE',
])

export type Phase6SnapshotRunState =
  | 'COMPLETED'
  | 'PARTIAL'
  | 'CANCELLED'
  | 'FAILED'
export type Phase6ProviderCoverageState =
  | 'COMPLETE'
  | 'NOT_CHECKED'
  | 'BLOCKED'
  | 'CHECK_FAILED'
export type Phase6FindingDiffState =
  | 'NEW'
  | 'CHANGED'
  | 'REMOVED'
  | 'UNCHANGED'
  | 'REAPPEARED'
export type Phase6IncompleteReason =
  | 'BASELINE_RUN_INCOMPLETE'
  | 'CURRENT_RUN_INCOMPLETE'
  | 'BASELINE_COVERAGE_INCOMPLETE'
  | 'CURRENT_COVERAGE_INCOMPLETE'
  | 'UNRESOLVED_ABSENCE'
  | 'HISTORY_GAP'

export interface Phase6AuditRunSummary {
  readonly runId: string
  readonly sequence: number
  readonly capturedAtUs: number
  readonly runState: Phase6SnapshotRunState
  readonly findingCount: number
  readonly providerCount: number
}

export interface Phase6AuditRunList {
  readonly profileId: string
  readonly runs: ReadonlyArray<Phase6AuditRunSummary>
  readonly hasMore: boolean
}

export interface Phase6LocalCheckpointCoverage {
  readonly providerId: string
  readonly state: Phase6ProviderCoverageState
}

export interface Phase6LocalCheckpointRequest {
  readonly profileId: string
  readonly runState: Phase6SnapshotRunState
  readonly providerCoverage: ReadonlyArray<Phase6LocalCheckpointCoverage>
}

export interface Phase6LocalCheckpointResult extends Phase6AuditRunSummary {
  readonly profileId: string
  readonly localOnly: true
}

export interface Phase6FindingDiff {
  readonly stableId: string
  readonly providerId: string
  readonly state: Phase6FindingDiffState
  readonly previousFingerprint: string | null
  readonly currentFingerprint: string | null
}

export interface Phase6UnresolvedAbsence {
  readonly stableId: string
  readonly providerId: string
  readonly previousFingerprint: string
  readonly currentCoverage: Phase6ProviderCoverageState | null
}

export interface Phase6CoverageComparison {
  readonly providerId: string
  readonly baselineState: Phase6ProviderCoverageState | null
  readonly currentState: Phase6ProviderCoverageState | null
}

export interface Phase6LifecycleEvent {
  readonly runId: string
  readonly sequence: number
  readonly runState: Phase6SnapshotRunState
  readonly providerCoverage: Phase6ProviderCoverageState | null
  readonly observed: boolean
  readonly contentFingerprint: string | null
}

export interface Phase6FindingLifecycle {
  readonly stableId: string
  readonly providerId: string
  readonly events: ReadonlyArray<Phase6LifecycleEvent>
}

export interface Phase6AuditComparison {
  readonly profileId: string
  readonly baselineRunId: string
  readonly currentRunId: string
  readonly diffs: ReadonlyArray<Phase6FindingDiff>
  readonly unresolvedAbsences: ReadonlyArray<Phase6UnresolvedAbsence>
  readonly coverage: ReadonlyArray<Phase6CoverageComparison>
  readonly lifecycles: ReadonlyArray<Phase6FindingLifecycle>
  readonly incompleteComparison: boolean
  readonly incompleteReasons: ReadonlyArray<Phase6IncompleteReason>
}

export type Phase6RemediationAction =
  | 'MONITOR'
  | 'PRESERVE_EVIDENCE'
  | 'DELETE_OWNED_ACCOUNT'
  | 'REQUEST_CORRECTION'
  | 'DRAFT_ERASURE_OR_DEINDEX'
  | 'DRAFT_IMPERSONATION_REPORT'
  | 'CONTACT'
  | 'ESCALATE'
  | 'MARK_LEGALLY_PERSISTENT'
export type Phase6ActionDisposition =
  | 'LOCAL_ONLY'
  | 'DRAFT'
  | 'REQUIRE_EXPLICIT_APPROVAL'
export type Phase6RemediationStatus =
  | 'OPEN'
  | 'IN_PROGRESS'
  | 'AWAITING_EXPLICIT_APPROVAL'
  | 'MONITORING'
  | 'RESOLVED'
  | 'CLOSED'
export type Phase6RemediationEventType =
  | 'CASE_CREATED'
  | 'DRAFT_UPDATED'
  | 'APPROVAL_REQUIRED'
  | 'STATUS_CHANGED'
  | 'DEADLINE_CHANGED'
  | 'EVIDENCE_LINKED'
  | 'PROVIDER_RESPONSE_RECORDED'
  | 'REAPPEARANCE_RECORDED'

export interface Phase6RemediationCaseSummary {
  readonly caseId: string
  readonly findingIds: ReadonlyArray<string>
  readonly action: Phase6RemediationAction
  readonly actionDisposition: Phase6ActionDisposition
  readonly status: Phase6RemediationStatus
  readonly deadlineAtUs: number | null
  readonly reappearanceCount: number
  readonly revision: number
  readonly updatedAtUs: number
}

export interface Phase6RemediationCaseList {
  readonly profileId: string
  readonly cases: ReadonlyArray<Phase6RemediationCaseSummary>
  readonly hasMore: boolean
}

export interface Phase6ProviderResponse {
  readonly providerId: string
  readonly responseCode: string
  readonly summary: string
  readonly receivedAtUs: number
  readonly evidenceReferences: ReadonlyArray<string>
}

export interface Phase6RemediationHistoryEntry {
  readonly revision: number
  readonly eventType: Phase6RemediationEventType
  readonly actorLabel: 'Local user'
  readonly occurredAtUs: number
  readonly previousStatus: Phase6RemediationStatus | null
  readonly currentStatus: Phase6RemediationStatus
  readonly detailCode: string
  readonly subjectId: string | null
  readonly evidenceReferences: ReadonlyArray<string>
  readonly note: string | null
}

export interface Phase6RemediationCase extends Phase6RemediationCaseSummary {
  readonly draftText: string | null
  readonly evidenceReferences: ReadonlyArray<string>
  readonly providerResponses: ReadonlyArray<Phase6ProviderResponse>
  readonly lastReappearanceAtUs: number | null
  readonly createdAtUs: number
  readonly history: ReadonlyArray<Phase6RemediationHistoryEntry>
}

export interface Phase6RemediationCaseDetail {
  readonly profileId: string
  readonly case: Phase6RemediationCase
}

export interface Phase6RemediationCreateRequest {
  readonly profileId: string
  readonly findingIds: ReadonlyArray<string>
  readonly action: Phase6RemediationAction
  readonly deadlineAtUs: number | null
  readonly evidenceReferences: ReadonlyArray<string>
  readonly draftText: string | null
}

export interface Phase6RemediationMutationRequest {
  readonly profileId: string
  readonly caseId: string
  readonly expectedRevision: number
}

export interface Phase6RemediationDraftUpdateRequest
  extends Phase6RemediationMutationRequest {
  readonly draftText: string
}

export type Phase6RemediationRequireApprovalRequest =
  Phase6RemediationMutationRequest

export interface Phase6RemediationStatusTransitionRequest
  extends Phase6RemediationMutationRequest {
  readonly targetStatus: Phase6RemediationStatus
  readonly note: string | null
}

export interface Phase6RemediationDeadlineUpdateRequest
  extends Phase6RemediationMutationRequest {
  readonly deadlineAtUs: number | null
}

export interface Phase6RemediationEvidenceLinkRequest
  extends Phase6RemediationMutationRequest {
  readonly evidenceReferences: ReadonlyArray<string>
}

export interface Phase6RemediationProviderResponseRequest
  extends Phase6RemediationMutationRequest {
  readonly providerId: string
  readonly responseCode: string
  readonly summary: string
  readonly evidenceReferences: ReadonlyArray<string>
}

export interface Phase6RemediationReappearanceRequest
  extends Phase6RemediationMutationRequest {
  readonly findingId: string
  readonly evidenceReferences: ReadonlyArray<string>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: ReadonlyArray<string>,
): boolean {
  const actual = Object.keys(value)
  return (
    actual.length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
  )
}

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !isUuid(value.requestId)
  ) {
    throw new Error('Phase 6 command response is invalid')
  }
  return value.data
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

function isCanonicalUuid(value: unknown): value is string {
  return isUuid(value) && value === value.toLocaleLowerCase()
}

function isSha256(value: unknown): value is string {
  return typeof value === 'string' && SHA256_PATTERN.test(value)
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === 'string' && OPAQUE_ID_PATTERN.test(value)
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number) {
  return (
    typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  )
}

function isTimestamp(value: unknown): value is number {
  return isIntegerBetween(value, 1, Number.MAX_SAFE_INTEGER)
}

function isBoundedText(
  value: unknown,
  maximum: number,
  multiline = false,
): value is string {
  return (
    typeof value === 'string' &&
    value.length >= 1 &&
    value.length <= maximum &&
    value === value.trim() &&
    value.trim().length >= 1 &&
    [...value].every((character) => {
      const code = character.codePointAt(0) ?? 0
      return code >= 32 || (multiline && (character === '\n' || character === '\t'))
    })
  )
}

function setsEqual(
  left: ReadonlyArray<string>,
  right: ReadonlyArray<string>,
): boolean {
  return (
    left.length === right.length &&
    left.every((value) => right.includes(value))
  )
}

function isUuidArray(
  value: unknown,
  minimum: number,
  maximum: number,
): value is ReadonlyArray<string> {
  return (
    Array.isArray(value) &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.every(isUuid) &&
    new Set(value).size === value.length
  )
}

function isRunSummary(value: unknown): value is Phase6AuditRunSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'runId',
      'sequence',
      'capturedAtUs',
      'runState',
      'findingCount',
      'providerCount',
    ]) &&
    isUuid(value.runId) &&
    isIntegerBetween(value.sequence, 1, Number.MAX_SAFE_INTEGER) &&
    isTimestamp(value.capturedAtUs) &&
    SNAPSHOT_RUN_STATES.has(value.runState as never) &&
    isIntegerBetween(value.findingCount, 0, 2_000) &&
    isIntegerBetween(value.providerCount, 1, 256)
  )
}

function parseAuditRunList(value: unknown): Phase6AuditRunList {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'runs', 'hasMore']) ||
    !isUuid(data.profileId) ||
    !Array.isArray(data.runs) ||
    data.runs.length > 32 ||
    !data.runs.every(isRunSummary) ||
    typeof data.hasMore !== 'boolean'
  ) {
    throw new Error('Phase 6 audit run list is invalid')
  }
  const runs = data.runs as ReadonlyArray<Phase6AuditRunSummary>
  if (
    new Set(runs.map((run) => run.runId)).size !== runs.length ||
    new Set(runs.map((run) => run.sequence)).size !== runs.length ||
    new Set(runs.map((run) => run.capturedAtUs)).size !== runs.length
  ) {
    throw new Error('Phase 6 audit run list identities are invalid')
  }
  return data as unknown as Phase6AuditRunList
}

function isLocalCheckpointCoverage(
  value: unknown,
): value is Phase6LocalCheckpointCoverage {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['providerId', 'state']) &&
    isOpaqueId(value.providerId) &&
    PROVIDER_COVERAGE_STATES.has(value.state as never)
  )
}

function parseLocalCheckpoint(value: unknown): Phase6LocalCheckpointResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'runId',
      'sequence',
      'capturedAtUs',
      'runState',
      'findingCount',
      'providerCount',
      'localOnly',
    ]) ||
    !isCanonicalUuid(data.profileId) ||
    !isRunSummary({
      runId: data.runId,
      sequence: data.sequence,
      capturedAtUs: data.capturedAtUs,
      runState: data.runState,
      findingCount: data.findingCount,
      providerCount: data.providerCount,
    }) ||
    data.localOnly !== true
  ) {
    throw new Error('Phase 6 local checkpoint response is invalid')
  }
  return data as unknown as Phase6LocalCheckpointResult
}

function isDiff(value: unknown): value is Phase6FindingDiff {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'stableId',
      'providerId',
      'state',
      'previousFingerprint',
      'currentFingerprint',
    ]) ||
    !isUuid(value.stableId) ||
    !isOpaqueId(value.providerId) ||
    !FINDING_DIFF_STATES.has(value.state as never)
  ) {
    return false
  }
  const previous = value.previousFingerprint
  const current = value.currentFingerprint
  switch (value.state) {
    case 'NEW':
      return previous === null && isSha256(current)
    case 'CHANGED':
      return isSha256(previous) && isSha256(current) && previous !== current
    case 'REMOVED':
      return isSha256(previous) && current === null
    case 'UNCHANGED':
      return isSha256(previous) && previous === current
    case 'REAPPEARED':
      return isSha256(previous) && isSha256(current)
    default:
      return false
  }
}

function isUnresolvedAbsence(
  value: unknown,
): value is Phase6UnresolvedAbsence {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'stableId',
      'providerId',
      'previousFingerprint',
      'currentCoverage',
    ]) &&
    isUuid(value.stableId) &&
    isOpaqueId(value.providerId) &&
    isSha256(value.previousFingerprint) &&
    (value.currentCoverage === null ||
      PROVIDER_COVERAGE_STATES.has(value.currentCoverage as never))
  )
}

function isCoverage(value: unknown): value is Phase6CoverageComparison {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['providerId', 'baselineState', 'currentState']) &&
    isOpaqueId(value.providerId) &&
    (value.baselineState === null ||
      PROVIDER_COVERAGE_STATES.has(value.baselineState as never)) &&
    (value.currentState === null ||
      PROVIDER_COVERAGE_STATES.has(value.currentState as never))
  )
}

function isLifecycleEvent(value: unknown): value is Phase6LifecycleEvent {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'runId',
      'sequence',
      'runState',
      'providerCoverage',
      'observed',
      'contentFingerprint',
    ]) &&
    isUuid(value.runId) &&
    isIntegerBetween(value.sequence, 1, Number.MAX_SAFE_INTEGER) &&
    SNAPSHOT_RUN_STATES.has(value.runState as never) &&
    (value.providerCoverage === null ||
      PROVIDER_COVERAGE_STATES.has(value.providerCoverage as never)) &&
    typeof value.observed === 'boolean' &&
    (value.observed
      ? isSha256(value.contentFingerprint)
      : value.contentFingerprint === null)
  )
}

function isLifecycle(value: unknown): value is Phase6FindingLifecycle {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['stableId', 'providerId', 'events']) ||
    !isUuid(value.stableId) ||
    !isOpaqueId(value.providerId) ||
    !Array.isArray(value.events) ||
    value.events.length < 1 ||
    value.events.length > 32 ||
    !value.events.every(isLifecycleEvent)
  ) {
    return false
  }
  const events = value.events as ReadonlyArray<Phase6LifecycleEvent>
  return (
    new Set(events.map((event) => event.runId)).size === events.length &&
    events.every(
      (event, index) => index === 0 || event.sequence > events[index - 1].sequence,
    )
  )
}

function parseAuditComparison(value: unknown): Phase6AuditComparison {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'baselineRunId',
      'currentRunId',
      'diffs',
      'unresolvedAbsences',
      'coverage',
      'lifecycles',
      'incompleteComparison',
      'incompleteReasons',
    ]) ||
    !isUuid(data.profileId) ||
    !isUuid(data.baselineRunId) ||
    !isUuid(data.currentRunId) ||
    data.baselineRunId === data.currentRunId ||
    !Array.isArray(data.diffs) ||
    data.diffs.length > 4_000 ||
    !data.diffs.every(isDiff) ||
    !Array.isArray(data.unresolvedAbsences) ||
    data.unresolvedAbsences.length > 4_000 ||
    !data.unresolvedAbsences.every(isUnresolvedAbsence) ||
    !Array.isArray(data.coverage) ||
    data.coverage.length > 256 ||
    !data.coverage.every(isCoverage) ||
    !Array.isArray(data.lifecycles) ||
    data.lifecycles.length > 5_000 ||
    !data.lifecycles.every(isLifecycle) ||
    typeof data.incompleteComparison !== 'boolean' ||
    !Array.isArray(data.incompleteReasons) ||
    data.incompleteReasons.length > 6 ||
    !data.incompleteReasons.every((reason) =>
      INCOMPLETE_REASONS.has(reason as never),
    )
  ) {
    throw new Error('Phase 6 audit comparison is invalid')
  }

  const diffs = data.diffs as ReadonlyArray<Phase6FindingDiff>
  const unresolved =
    data.unresolvedAbsences as ReadonlyArray<Phase6UnresolvedAbsence>
  const coverage = data.coverage as ReadonlyArray<Phase6CoverageComparison>
  const lifecycles = data.lifecycles as ReadonlyArray<Phase6FindingLifecycle>
  const reasons = data.incompleteReasons as ReadonlyArray<Phase6IncompleteReason>
  const outputs = [...diffs, ...unresolved]
  const lifecycleById = new Map(
    lifecycles.map((lifecycle) => [lifecycle.stableId, lifecycle]),
  )
  const coverageIds = new Set(coverage.map((item) => item.providerId))
  const totalEvents = lifecycles.reduce(
    (total, lifecycle) => total + lifecycle.events.length,
    0,
  )
  if (
    new Set(outputs.map((item) => item.stableId)).size !== outputs.length ||
    new Set(coverageIds).size !== coverage.length ||
    new Set(lifecycles.map((item) => item.stableId)).size !== lifecycles.length ||
    outputs.length !== lifecycles.length ||
    outputs.some((item) => {
      const lifecycle = lifecycleById.get(item.stableId)
      return (
        lifecycle?.providerId !== item.providerId ||
        lifecycle.events.at(-1)?.runId !== data.currentRunId ||
        !coverageIds.has(item.providerId)
      )
    }) ||
    totalEvents > 128_000 ||
    new Set(reasons).size !== reasons.length ||
    data.incompleteComparison !== (reasons.length > 0) ||
    (unresolved.length > 0) !== reasons.includes('UNRESOLVED_ABSENCE')
  ) {
    throw new Error('Phase 6 audit comparison bindings are invalid')
  }
  return data as unknown as Phase6AuditComparison
}

function hasValidActionDisposition(
  action: Phase6RemediationAction,
  disposition: Phase6ActionDisposition,
  status: Phase6RemediationStatus,
): boolean {
  if (LOCAL_ACTIONS.has(action)) return disposition === 'LOCAL_ONLY'
  if (disposition === 'LOCAL_ONLY') return false
  return (
    status !== 'AWAITING_EXPLICIT_APPROVAL' ||
    disposition === 'REQUIRE_EXPLICIT_APPROVAL'
  )
}

function isRemediationSummary(
  value: unknown,
): value is Phase6RemediationCaseSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'caseId',
      'findingIds',
      'action',
      'actionDisposition',
      'status',
      'deadlineAtUs',
      'reappearanceCount',
      'revision',
      'updatedAtUs',
    ]) &&
    isUuid(value.caseId) &&
    isUuidArray(value.findingIds, 1, 64) &&
    REMEDIATION_ACTIONS.has(value.action as never) &&
    ACTION_DISPOSITIONS.has(value.actionDisposition as never) &&
    REMEDIATION_STATUSES.has(value.status as never) &&
    (value.deadlineAtUs === null || isTimestamp(value.deadlineAtUs)) &&
    isIntegerBetween(value.reappearanceCount, 0, Number.MAX_SAFE_INTEGER) &&
    isIntegerBetween(value.revision, 1, 256) &&
    isTimestamp(value.updatedAtUs) &&
    hasValidActionDisposition(
      value.action as Phase6RemediationAction,
      value.actionDisposition as Phase6ActionDisposition,
      value.status as Phase6RemediationStatus,
    )
  )
}

function parseRemediationCaseList(value: unknown): Phase6RemediationCaseList {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'cases', 'hasMore']) ||
    !isUuid(data.profileId) ||
    !Array.isArray(data.cases) ||
    data.cases.length > 100 ||
    !data.cases.every(isRemediationSummary) ||
    typeof data.hasMore !== 'boolean'
  ) {
    throw new Error('Phase 6 remediation case list is invalid')
  }
  const cases = data.cases as ReadonlyArray<Phase6RemediationCaseSummary>
  if (new Set(cases.map((item) => item.caseId)).size !== cases.length) {
    throw new Error('Phase 6 remediation case identities are invalid')
  }
  return data as unknown as Phase6RemediationCaseList
}

function isProviderResponse(value: unknown): value is Phase6ProviderResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'providerId',
      'responseCode',
      'summary',
      'receivedAtUs',
      'evidenceReferences',
    ]) &&
    isOpaqueId(value.providerId) &&
    typeof value.responseCode === 'string' &&
    CODE_PATTERN.test(value.responseCode) &&
    isBoundedText(value.summary, 2_048, true) &&
    isTimestamp(value.receivedAtUs) &&
    isUuidArray(value.evidenceReferences, 0, 64)
  )
}

function isHistoryEntry(
  value: unknown,
): value is Phase6RemediationHistoryEntry {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'revision',
      'eventType',
      'actorLabel',
      'occurredAtUs',
      'previousStatus',
      'currentStatus',
      'detailCode',
      'subjectId',
      'evidenceReferences',
      'note',
    ]) &&
    isIntegerBetween(value.revision, 1, 256) &&
    REMEDIATION_EVENT_TYPES.has(value.eventType as never) &&
    value.actorLabel === 'Local user' &&
    isTimestamp(value.occurredAtUs) &&
    (value.previousStatus === null ||
      REMEDIATION_STATUSES.has(value.previousStatus as never)) &&
    REMEDIATION_STATUSES.has(value.currentStatus as never) &&
    typeof value.detailCode === 'string' &&
    CODE_PATTERN.test(value.detailCode) &&
    (value.subjectId === null || isOpaqueId(value.subjectId)) &&
    isUuidArray(value.evidenceReferences, 0, 64) &&
    (value.note === null || isBoundedText(value.note, 1_000, true))
  )
}

function parseRemediationCaseDetail(
  value: unknown,
): Phase6RemediationCaseDetail {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'case']) ||
    !isUuid(data.profileId) ||
    !isRecord(data.case) ||
    !hasExactKeys(data.case, [
      'caseId',
      'findingIds',
      'action',
      'actionDisposition',
      'status',
      'deadlineAtUs',
      'reappearanceCount',
      'revision',
      'updatedAtUs',
      'draftText',
      'evidenceReferences',
      'providerResponses',
      'lastReappearanceAtUs',
      'createdAtUs',
      'history',
    ]) ||
    !isRemediationSummary({
      caseId: data.case.caseId,
      findingIds: data.case.findingIds,
      action: data.case.action,
      actionDisposition: data.case.actionDisposition,
      status: data.case.status,
      deadlineAtUs: data.case.deadlineAtUs,
      reappearanceCount: data.case.reappearanceCount,
      revision: data.case.revision,
      updatedAtUs: data.case.updatedAtUs,
    }) ||
    (data.case.draftText !== null &&
      !isBoundedText(data.case.draftText, 10_000, true)) ||
    !isUuidArray(data.case.evidenceReferences, 0, 64) ||
    !Array.isArray(data.case.providerResponses) ||
    data.case.providerResponses.length > 32 ||
    !data.case.providerResponses.every(isProviderResponse) ||
    (data.case.lastReappearanceAtUs !== null &&
      !isTimestamp(data.case.lastReappearanceAtUs)) ||
    !isTimestamp(data.case.createdAtUs) ||
    !Array.isArray(data.case.history) ||
    !data.case.history.every(isHistoryEntry)
  ) {
    throw new Error('Phase 6 remediation case detail is invalid')
  }

  const case_ = data.case as unknown as Phase6RemediationCase
  const evidenceIds = new Set(case_.evidenceReferences)
  const history = case_.history
  if (
    case_.history.length !== case_.revision ||
    case_.createdAtUs > case_.updatedAtUs ||
    (case_.deadlineAtUs !== null && case_.deadlineAtUs <= case_.createdAtUs) ||
    ((case_.reappearanceCount === 0) !==
      (case_.lastReappearanceAtUs === null)) ||
    (case_.lastReappearanceAtUs !== null &&
      case_.lastReappearanceAtUs > case_.updatedAtUs) ||
    history.some(
      (entry, index) =>
        entry.revision !== index + 1 ||
        (index === 0
          ? entry.previousStatus !== null
          : entry.previousStatus !== history[index - 1].currentStatus) ||
        (index > 0 &&
          entry.occurredAtUs <= history[index - 1].occurredAtUs),
    ) ||
    history.at(-1)?.occurredAtUs !== case_.updatedAtUs ||
    history.at(-1)?.currentStatus !== case_.status ||
    case_.providerResponses.some(
      (response) =>
        response.receivedAtUs < case_.createdAtUs ||
        response.receivedAtUs > case_.updatedAtUs ||
        response.evidenceReferences.some((id) => !evidenceIds.has(id)),
    ) ||
    history.some((entry) =>
      entry.evidenceReferences.some((id) => !evidenceIds.has(id)),
    )
  ) {
    throw new Error('Phase 6 remediation case bindings are invalid')
  }
  return data as unknown as Phase6RemediationCaseDetail
}

async function invokePhase6(command: string, request: object): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<unknown>(command, { request })
}

function isCanonicalUuidArray(
  value: unknown,
  minimum: number,
  maximum: number,
): value is ReadonlyArray<string> {
  return (
    Array.isArray(value) &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.every(isCanonicalUuid) &&
    new Set(value).size === value.length
  )
}

function validateMutationBase(
  request: Phase6RemediationMutationRequest,
): void {
  if (
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuid(request.caseId) ||
    !isIntegerBetween(request.expectedRevision, 1, 255)
  ) {
    throw new Error('Phase 6 remediation mutation request is invalid')
  }
}

function validateCreateRequest(request: Phase6RemediationCreateRequest): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'findingIds',
      'action',
      'deadlineAtUs',
      'evidenceReferences',
      'draftText',
    ]) ||
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuidArray(request.findingIds, 1, 64) ||
    !REMEDIATION_ACTIONS.has(request.action as never) ||
    (request.deadlineAtUs !== null && !isTimestamp(request.deadlineAtUs)) ||
    !isCanonicalUuidArray(request.evidenceReferences, 0, 64) ||
    (request.draftText !== null &&
      !isBoundedText(request.draftText, 10_000, true)) ||
    (LOCAL_ACTIONS.has(request.action) && request.draftText !== null)
  ) {
    throw new Error('Phase 6 remediation create request is invalid')
  }
}

function validateExactMutation(
  request: Phase6RemediationMutationRequest,
  keys: ReadonlyArray<string>,
): void {
  if (!isRecord(request) || !hasExactKeys(request, keys)) {
    throw new Error('Phase 6 remediation mutation request is invalid')
  }
  validateMutationBase(request)
}

function bindMutationResult(
  value: unknown,
  request: Phase6RemediationMutationRequest,
  eventType: Phase6RemediationEventType,
): Phase6RemediationCaseDetail {
  const result = parseRemediationCaseDetail(value)
  const lastEvent = result.case.history.at(-1)
  if (
    result.profileId !== request.profileId ||
    result.case.caseId !== request.caseId ||
    result.case.revision !== request.expectedRevision + 1 ||
    lastEvent?.revision !== result.case.revision ||
    lastEvent.eventType !== eventType
  ) {
    throw new Error('Phase 6 remediation mutation response binding is invalid')
  }
  return result
}

export async function loadPhase6AuditRuns(request: {
  readonly profileId: string
  readonly limit?: number
}): Promise<Phase6AuditRunList> {
  const limit = request.limit ?? 32
  if (!isUuid(request.profileId) || !isIntegerBetween(limit, 1, 32)) {
    throw new Error('Phase 6 audit run request is invalid')
  }
  const result = parseAuditRunList(
    await invokePhase6('core_list_phase6_audit_runs', {
      profileId: request.profileId,
      limit,
    }),
  )
  if (result.profileId !== request.profileId) {
    throw new Error('Phase 6 audit run profile binding is invalid')
  }
  return result
}

export async function loadPhase6AuditComparison(request: {
  readonly profileId: string
  readonly baselineRunId: string
  readonly currentRunId: string
}): Promise<Phase6AuditComparison> {
  if (
    !isUuid(request.profileId) ||
    !isUuid(request.baselineRunId) ||
    !isUuid(request.currentRunId) ||
    request.baselineRunId === request.currentRunId
  ) {
    throw new Error('Phase 6 audit comparison request is invalid')
  }
  const result = parseAuditComparison(
    await invokePhase6('core_compare_phase6_runs', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.baselineRunId !== request.baselineRunId ||
    result.currentRunId !== request.currentRunId
  ) {
    throw new Error('Phase 6 audit comparison request binding is invalid')
  }
  return result
}

export async function createPhase6LocalCheckpoint(
  request: Phase6LocalCheckpointRequest,
): Promise<Phase6LocalCheckpointResult> {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, ['profileId', 'runState', 'providerCoverage']) ||
    !isCanonicalUuid(request.profileId) ||
    !SNAPSHOT_RUN_STATES.has(request.runState as never) ||
    !Array.isArray(request.providerCoverage) ||
    request.providerCoverage.length < 1 ||
    request.providerCoverage.length > 256 ||
    !request.providerCoverage.every(isLocalCheckpointCoverage) ||
    new Set(request.providerCoverage.map((item) => item.providerId)).size !==
      request.providerCoverage.length
  ) {
    throw new Error('Phase 6 local checkpoint request is invalid')
  }
  const result = parseLocalCheckpoint(
    await invokePhase6('core_create_phase6_local_checkpoint', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.runState !== request.runState ||
    result.providerCount !== request.providerCoverage.length
  ) {
    throw new Error('Phase 6 local checkpoint response binding is invalid')
  }
  return result
}

export async function loadPhase6RemediationCases(request: {
  readonly profileId: string
  readonly limit?: number
}): Promise<Phase6RemediationCaseList> {
  const limit = request.limit ?? 100
  if (!isUuid(request.profileId) || !isIntegerBetween(limit, 1, 100)) {
    throw new Error('Phase 6 remediation list request is invalid')
  }
  const result = parseRemediationCaseList(
    await invokePhase6('core_list_phase6_remediation_cases', {
      profileId: request.profileId,
      limit,
    }),
  )
  if (result.profileId !== request.profileId) {
    throw new Error('Phase 6 remediation profile binding is invalid')
  }
  return result
}

export async function loadPhase6RemediationCase(request: {
  readonly profileId: string
  readonly caseId: string
}): Promise<Phase6RemediationCaseDetail> {
  if (!isUuid(request.profileId) || !isUuid(request.caseId)) {
    throw new Error('Phase 6 remediation detail request is invalid')
  }
  const result = parseRemediationCaseDetail(
    await invokePhase6('core_get_phase6_remediation_case', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.case.caseId !== request.caseId
  ) {
    throw new Error('Phase 6 remediation detail binding is invalid')
  }
  return result
}

export async function createPhase6RemediationCase(
  request: Phase6RemediationCreateRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateCreateRequest(request)
  const result = parseRemediationCaseDetail(
    await invokePhase6('core_create_phase6_remediation_case', request),
  )
  const case_ = result.case
  if (
    result.profileId !== request.profileId ||
    case_.revision !== 1 ||
    case_.action !== request.action ||
    case_.deadlineAtUs !== request.deadlineAtUs ||
    case_.draftText !== request.draftText ||
    !setsEqual(case_.findingIds, request.findingIds) ||
    !setsEqual(case_.evidenceReferences, request.evidenceReferences) ||
    case_.history[0]?.eventType !== 'CASE_CREATED'
  ) {
    throw new Error('Phase 6 remediation create response binding is invalid')
  }
  return result
}

export async function updatePhase6RemediationDraft(
  request: Phase6RemediationDraftUpdateRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'draftText',
  ])
  if (!isBoundedText(request.draftText, 10_000, true)) {
    throw new Error('Phase 6 remediation draft request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_update_phase6_remediation_draft', request),
    request,
    'DRAFT_UPDATED',
  )
  if (result.case.draftText !== request.draftText) {
    throw new Error('Phase 6 remediation draft response binding is invalid')
  }
  return result
}

export async function requirePhase6RemediationApproval(
  request: Phase6RemediationRequireApprovalRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, ['profileId', 'caseId', 'expectedRevision'])
  const result = bindMutationResult(
    await invokePhase6('core_require_phase6_remediation_approval', request),
    request,
    'APPROVAL_REQUIRED',
  )
  if (
    result.case.actionDisposition !== 'REQUIRE_EXPLICIT_APPROVAL' ||
    result.case.status !== 'AWAITING_EXPLICIT_APPROVAL'
  ) {
    throw new Error('Phase 6 remediation approval response binding is invalid')
  }
  return result
}

export async function transitionPhase6RemediationStatus(
  request: Phase6RemediationStatusTransitionRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'targetStatus',
    'note',
  ])
  if (
    !REMEDIATION_STATUSES.has(request.targetStatus as never) ||
    (request.note !== null && !isBoundedText(request.note, 1_000, true))
  ) {
    throw new Error('Phase 6 remediation status request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_transition_phase6_remediation_status', request),
    request,
    'STATUS_CHANGED',
  )
  const lastEvent = result.case.history.at(-1)
  if (
    result.case.status !== request.targetStatus ||
    lastEvent?.note !== request.note
  ) {
    throw new Error('Phase 6 remediation status response binding is invalid')
  }
  return result
}

export async function setPhase6RemediationDeadline(
  request: Phase6RemediationDeadlineUpdateRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'deadlineAtUs',
  ])
  if (request.deadlineAtUs !== null && !isTimestamp(request.deadlineAtUs)) {
    throw new Error('Phase 6 remediation deadline request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_set_phase6_remediation_deadline', request),
    request,
    'DEADLINE_CHANGED',
  )
  if (result.case.deadlineAtUs !== request.deadlineAtUs) {
    throw new Error('Phase 6 remediation deadline response binding is invalid')
  }
  return result
}

export async function linkPhase6RemediationEvidence(
  request: Phase6RemediationEvidenceLinkRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'evidenceReferences',
  ])
  if (!isCanonicalUuidArray(request.evidenceReferences, 1, 64)) {
    throw new Error('Phase 6 remediation evidence request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_link_phase6_remediation_evidence', request),
    request,
    'EVIDENCE_LINKED',
  )
  const eventEvidence = result.case.history.at(-1)?.evidenceReferences ?? []
  if (
    request.evidenceReferences.some(
      (reference) => !result.case.evidenceReferences.includes(reference),
    ) ||
    eventEvidence.length < 1 ||
    eventEvidence.some(
      (reference) => !request.evidenceReferences.includes(reference),
    )
  ) {
    throw new Error('Phase 6 remediation evidence response binding is invalid')
  }
  return result
}

export async function recordPhase6ProviderResponse(
  request: Phase6RemediationProviderResponseRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'providerId',
    'responseCode',
    'summary',
    'evidenceReferences',
  ])
  if (
    !isOpaqueId(request.providerId) ||
    !CODE_PATTERN.test(request.responseCode) ||
    !isBoundedText(request.summary, 2_048, false) ||
    !isCanonicalUuidArray(request.evidenceReferences, 0, 64)
  ) {
    throw new Error('Phase 6 provider response request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_record_phase6_provider_response', request),
    request,
    'PROVIDER_RESPONSE_RECORDED',
  )
  const response = result.case.providerResponses.at(-1)
  const event = result.case.history.at(-1)
  if (
    response?.providerId !== request.providerId ||
    response.responseCode !== request.responseCode ||
    response.summary !== request.summary ||
    !setsEqual(response.evidenceReferences, request.evidenceReferences) ||
    response.receivedAtUs !== result.case.updatedAtUs ||
    event?.subjectId !== request.providerId ||
    !setsEqual(event.evidenceReferences, request.evidenceReferences)
  ) {
    throw new Error('Phase 6 provider response binding is invalid')
  }
  return result
}

export async function recordPhase6Reappearance(
  request: Phase6RemediationReappearanceRequest,
): Promise<Phase6RemediationCaseDetail> {
  validateExactMutation(request, [
    'profileId',
    'caseId',
    'expectedRevision',
    'findingId',
    'evidenceReferences',
  ])
  if (
    !isCanonicalUuid(request.findingId) ||
    !isCanonicalUuidArray(request.evidenceReferences, 1, 64)
  ) {
    throw new Error('Phase 6 reappearance request is invalid')
  }
  const result = bindMutationResult(
    await invokePhase6('core_record_phase6_reappearance', request),
    request,
    'REAPPEARANCE_RECORDED',
  )
  const event = result.case.history.at(-1)
  if (
    !result.case.findingIds.includes(request.findingId) ||
    request.evidenceReferences.some(
      (reference) => !result.case.evidenceReferences.includes(reference),
    ) ||
    result.case.reappearanceCount < 1 ||
    result.case.lastReappearanceAtUs !== result.case.updatedAtUs ||
    event?.subjectId !== request.findingId ||
    !setsEqual(event.evidenceReferences, request.evidenceReferences)
  ) {
    throw new Error('Phase 6 reappearance response binding is invalid')
  }
  return result
}

export const phase6BoundaryParsers = {
  auditRuns: parseAuditRunList,
  localCheckpoint: parseLocalCheckpoint,
  auditComparison: parseAuditComparison,
  remediationCases: parseRemediationCaseList,
  remediationCase: parseRemediationCaseDetail,
}
