/** Typed renderer boundary for persistent people and restart-safe identity audits. */
import type {
  AuditControlRequest,
  AuditCreateRequest,
  AuditDetail,
  AuditExecuteRequest,
  AuditSummary,
  PersonSourceCreateRequest,
  PersonUpdateRequest,
  PersonWorkspace,
  PersonWorkspaceRequest,
  ProposalDecisionRequest,
} from '../../../../packages/contracts/src/generated/api'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu
const AUDIT_STATES = new Set([
  'DRAFT', 'READY', 'RUNNING', 'PAUSED', 'COMPLETED', 'PARTIAL',
  'CANCELLED', 'FAILED',
])
const AUDIT_STAGES = new Set([
  'KNOWLEDGE', 'PLANNING', 'SEARCHING', 'EXTRACTING', 'CORRELATING',
  'AI_ANALYSIS', 'REVIEW', 'CHECKPOINT', 'COMPLETE',
])
const AUDIT_MODES = new Set([
  'FULL_RESCAN', 'INCREMENTAL', 'NEW_IDENTIFIERS_ONLY',
  'FAILED_AND_BLOCKED_RETRY', 'SELECTED_IDENTITIES', 'SELECTED_PROVIDERS',
  'CHANGE_MONITORING', 'MAXIMUM_COVERAGE',
])
const TASK_STATES = new Set([
  'PLANNED', 'READY', 'QUEUED', 'RUNNING', 'SUCCEEDED_EMPTY',
  'SUCCEEDED_RESULTS', 'BLOCKED', 'RATE_LIMITED', 'AUTH_REQUIRED',
  'FAILED_RETRYABLE', 'FAILED_TERMINAL', 'SKIPPED', 'CANCELLED',
  'REVIEW_REQUIRED', 'REVIEWED', 'SAVED',
])
const AI_ANALYSIS_STATES = new Set(['SUCCEEDED', 'FALLBACK', 'FAILED', 'EMPTY'])
const AI_INSIGHT_KINDS = new Set(['FACT', 'CONNECTION', 'NEXT_STEP'])

interface CommandResponse<T> {
  readonly requestId: string
  readonly data: T
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown, maximum: number): value is string[] {
  return Array.isArray(value) && value.length <= maximum &&
    value.every((item) => typeof item === 'string')
}

function isSafeInteger(value: unknown, minimum = 0): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum
}

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === 'string'
}

function isNullableUuid(value: unknown): boolean {
  return value === null || UUID_PATTERN.test(String(value))
}

function isNullableSafeInteger(value: unknown): boolean {
  return value === null || isSafeInteger(value, 1)
}

function commandData(value: unknown): unknown {
  if (!isRecord(value) || !UUID_PATTERN.test(String(value.requestId))) {
    throw new Error('Identity command response is invalid')
  }
  return value.data
}

function validAuditSummary(value: unknown): value is AuditSummary {
  if (!isRecord(value) || !UUID_PATTERN.test(String(value.auditId)) ||
      typeof value.name !== 'string' || !AUDIT_MODES.has(String(value.mode)) ||
      !AUDIT_STATES.has(String(value.state)) || !AUDIT_STAGES.has(String(value.stage)) ||
      !isStringArray(value.providerIds, 8) || typeof value.useLocalAi !== 'boolean' ||
      !isNullableString(value.selectedModel) || !isSafeInteger(value.maxDepth) ||
      !isSafeInteger(value.requestBudget, 1) || !isSafeInteger(value.totalTasks) ||
      !isSafeInteger(value.terminalTasks) || !isSafeInteger(value.resultCount) ||
      !isSafeInteger(value.leadCount) || !isSafeInteger(value.proposalCount) ||
      !isSafeInteger(value.progressMicros) || Number(value.progressMicros) > 1_000_000 ||
      !isNullableString(value.stopReason) || !Array.isArray(value.taskStates) ||
      value.taskStates.length > 17 || !isNullableSafeInteger(value.startedAtUs) ||
      !isNullableSafeInteger(value.finishedAtUs) || !isSafeInteger(value.createdAtUs, 1) ||
      !isSafeInteger(value.updatedAtUs, 1) || !isSafeInteger(value.revision, 1)) {
    return false
  }
  return value.taskStates.every((item) =>
    isRecord(item) && TASK_STATES.has(String(item.state)) && isSafeInteger(item.count),
  )
}

function parseWorkspace(value: unknown): PersonWorkspace {
  const data = commandData(value)
  if (!isRecord(data) || !isRecord(data.person) ||
      !UUID_PATTERN.test(String(data.person.profileId)) ||
      typeof data.person.displayName !== 'string' || typeof data.person.purpose !== 'string' ||
      typeof data.person.status !== 'string' || typeof data.person.notes !== 'string' ||
      !isStringArray(data.person.tags, 32) || !isSafeInteger(data.person.profileRevision, 1) ||
      !isSafeInteger(data.person.detailsRevision) || !isSafeInteger(data.person.identityCount) ||
      !isSafeInteger(data.person.sourceCount) || !isSafeInteger(data.person.auditCount) ||
      !isSafeInteger(data.person.unresolvedProposalCount) || !Array.isArray(data.sources) ||
      data.sources.length > 200 || !Array.isArray(data.audits) || data.audits.length > 64 ||
      typeof data.hasMoreSources !== 'boolean' || typeof data.hasMoreAudits !== 'boolean') {
    throw new Error('Identity workspace is invalid')
  }
  const sourcesValid = data.sources.every((source) => isRecord(source) &&
    UUID_PATTERN.test(String(source.sourceId)) && typeof source.sourceType === 'string' &&
    typeof source.url === 'string' && isNullableString(source.title) &&
    typeof source.notes === 'string' && typeof source.relationshipState === 'string' &&
    isNullableUuid(source.parentSourceId) && isSafeInteger(source.firstSeenAtUs, 1) &&
    isNullableSafeInteger(source.lastCheckedAtUs) &&
    (source.httpStatus === null || isSafeInteger(source.httpStatus, 100)) &&
    isSafeInteger(source.revision, 1))
  if (!sourcesValid || !data.audits.every(validAuditSummary)) {
    throw new Error('Identity workspace collections are invalid')
  }
  return data as unknown as PersonWorkspace
}

function parseAuditDetail(value: unknown): AuditDetail {
  const data = commandData(value)
  if (!isRecord(data) || !UUID_PATTERN.test(String(data.profileId)) ||
      !validAuditSummary(data.audit) || !Array.isArray(data.tasks) || data.tasks.length > 500 ||
      !Array.isArray(data.results) || data.results.length > 500 ||
      !Array.isArray(data.leads) || data.leads.length > 500 ||
      !Array.isArray(data.proposals) || data.proposals.length > 250 ||
      !Array.isArray(data.receipts) || data.receipts.length > 500 ||
      !(data.aiAnalysis === null || isRecord(data.aiAnalysis)) ||
      typeof data.hasMoreTasks !== 'boolean' || typeof data.hasMoreResults !== 'boolean' ||
      typeof data.hasMoreLeads !== 'boolean' || typeof data.hasMoreProposals !== 'boolean' ||
      typeof data.hasMoreReceipts !== 'boolean') {
    throw new Error('Identity audit detail is invalid')
  }
  const tasksValid = data.tasks.every((task) => isRecord(task) &&
    UUID_PATTERN.test(String(task.taskId)) && isNullableUuid(task.leadId) &&
    isNullableUuid(task.parentTaskId) && typeof task.taskType === 'string' &&
    typeof task.providerId === 'string' && typeof task.maskedPayload === 'string' &&
    isSafeInteger(task.priority) && isSafeInteger(task.informationGainMicros) &&
    isSafeInteger(task.depth) && TASK_STATES.has(String(task.state)) &&
    isSafeInteger(task.attemptCount) && isSafeInteger(task.retryLimit) &&
    isSafeInteger(task.resultCount) && isNullableString(task.stopReason) &&
    isSafeInteger(task.revision, 1))
  const resultsValid = data.results.every((result) => isRecord(result) &&
    UUID_PATTERN.test(String(result.resultId)) && UUID_PATTERN.test(String(result.taskId)) &&
    typeof result.providerId === 'string' && isSafeInteger(result.rank, 1) &&
    typeof result.category === 'string' && typeof result.url === 'string' &&
    typeof result.title === 'string' && typeof result.snippet === 'string' &&
    isSafeInteger(result.observedAtUs, 1) && typeof result.reviewState === 'string')
  const leadsValid = data.leads.every((lead) => isRecord(lead) &&
    UUID_PATTERN.test(String(lead.leadId)) && isNullableUuid(lead.parentLeadId) &&
    isNullableUuid(lead.sourceId) && typeof lead.leadType === 'string' &&
    typeof lead.displayValue === 'string' && isNullableString(lead.sourceUrl) &&
    typeof lead.providerId === 'string' && isSafeInteger(lead.depth) &&
    isStringArray(lead.supportingSignals, 32) && isStringArray(lead.contradictions, 32) &&
    isSafeInteger(lead.confidenceMicros) && typeof lead.ownershipState === 'string' &&
    typeof lead.temporalState === 'string' && typeof lead.reviewState === 'string' &&
    typeof lead.expansionState === 'string')
  const proposalsValid = data.proposals.every((proposal) => isRecord(proposal) &&
    UUID_PATTERN.test(String(proposal.proposalId)) && UUID_PATTERN.test(String(proposal.leadId)) &&
    typeof proposal.entityType === 'string' && typeof proposal.displayValue === 'string' &&
    typeof proposal.sourceUrl === 'string' &&
    (proposal.sourceSpanStart === null || isSafeInteger(proposal.sourceSpanStart)) &&
    (proposal.sourceSpanEnd === null || isSafeInteger(proposal.sourceSpanEnd)) &&
    isStringArray(proposal.supportingSignals, 32) &&
    isStringArray(proposal.contradictions, 32) && isSafeInteger(proposal.confidenceMicros) &&
    typeof proposal.temporalState === 'string' && typeof proposal.reviewState === 'string' &&
    isStringArray(proposal.recommendedActions, 16) && isNullableString(proposal.modelProvider) &&
    isNullableString(proposal.modelId) && isSafeInteger(proposal.revision, 1))
  const receiptsValid = data.receipts.every((receipt) => isRecord(receipt) &&
    UUID_PATTERN.test(String(receipt.receiptId)) && isNullableUuid(receipt.taskId) &&
    typeof receipt.toolName === 'string' && typeof receipt.authorizationState === 'string' &&
    typeof receipt.executionState === 'string' && typeof receipt.resultCode === 'string' &&
    isSafeInteger(receipt.resultCount) && isNullableString(receipt.modelProvider) &&
    isNullableString(receipt.modelId) && isSafeInteger(receipt.startedAtUs, 1) &&
    isSafeInteger(receipt.finishedAtUs, 1))
  const analysisValid = data.aiAnalysis === null || validAiAnalysis(data.aiAnalysis)
  if (!tasksValid || !resultsValid || !leadsValid || !proposalsValid || !receiptsValid || !analysisValid) {
    throw new Error('Identity audit collections are invalid')
  }
  return data as unknown as AuditDetail
}

function validAiAnalysis(value: Record<string, unknown>): boolean {
  if (!UUID_PATTERN.test(String(value.analysisId)) ||
      !AI_ANALYSIS_STATES.has(String(value.status)) || typeof value.resultCode !== 'string' ||
      !isNullableString(value.provider) || !isNullableString(value.modelId) ||
      !isNullableString(value.engineVersion) || typeof value.title !== 'string' ||
      typeof value.summary !== 'string' || !Array.isArray(value.insights) ||
      value.insights.length > 100 || !Array.isArray(value.citations) ||
      value.citations.length > 200 || !isStringArray(value.limitations, 32) ||
      !isSafeInteger(value.createdAtUs, 1)) return false
  const references = new Set<string>()
  if (!value.citations.every((citation) => {
    if (!isRecord(citation) || typeof citation.referenceId !== 'string' ||
        !UUID_PATTERN.test(String(citation.resultId)) || typeof citation.url !== 'string' ||
        typeof citation.title !== 'string') return false
    references.add(citation.referenceId)
    return true
  })) return false
  return value.insights.every((insight) => isRecord(insight) &&
    AI_INSIGHT_KINDS.has(String(insight.kind)) && typeof insight.statement === 'string' &&
    typeof insight.rationale === 'string' && isNullableString(insight.confidence) &&
    isStringArray(insight.evidenceRefs, 32) &&
    insight.evidenceRefs.every((reference) => references.has(reference)))
}

async function invokeIdentity(command: string, request: object): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<CommandResponse<unknown>>(command, { request })
}

export async function getIdentityWorkspace(request: PersonWorkspaceRequest): Promise<PersonWorkspace> {
  return parseWorkspace(await invokeIdentity('core_identity_workspace', request))
}

export async function updateIdentityPerson(request: PersonUpdateRequest): Promise<PersonWorkspace> {
  return parseWorkspace(await invokeIdentity('core_update_identity_person', request))
}

export async function createIdentitySource(request: PersonSourceCreateRequest): Promise<PersonWorkspace> {
  return parseWorkspace(await invokeIdentity('core_create_identity_source', request))
}

export async function createIdentityAudit(request: AuditCreateRequest): Promise<AuditDetail> {
  return parseAuditDetail(await invokeIdentity('core_create_identity_audit', request))
}

export async function getIdentityAudit(request: AuditExecuteRequest): Promise<AuditDetail> {
  return parseAuditDetail(await invokeIdentity('core_get_identity_audit', request))
}

export async function executeIdentityAuditBatch(request: AuditExecuteRequest): Promise<AuditDetail> {
  return parseAuditDetail(await invokeIdentity('core_execute_identity_audit_batch', request))
}

export async function controlIdentityAudit(request: AuditControlRequest): Promise<AuditDetail> {
  return parseAuditDetail(await invokeIdentity('core_control_identity_audit', request))
}

export async function decideIdentityProposal(request: ProposalDecisionRequest): Promise<AuditDetail> {
  return parseAuditDetail(await invokeIdentity('core_decide_identity_proposal', request))
}

export const identityDiscoveryParsers = {
  workspace: parseWorkspace,
  auditDetail: parseAuditDetail,
}
