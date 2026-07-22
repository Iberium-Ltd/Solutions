/**
 * Strict decoder for optional AI workspace results. Model-derived content must
 * remain bounded, typed, review-only, and linked to validated source references.
 */
import type {
  LocalAIWorkspaceRequest,
  LocalAIWorkspaceResult,
} from '../../../../packages/contracts/src/generated/api'

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256 = /^[0-9a-f]{64}$/
const TASKS = new Set([
  'SUMMARY',
  'ORGANIZE',
  'QUESTION',
  'CONNECTIONS',
  'GAP_ANALYSIS',
])
const SCOPES = new Set([
  'ENTITIES',
  'GRAPH',
  'FINDINGS',
  'REMEDIATION',
  'AUDIT_COVERAGE',
  'DOCUMENT',
])
const EXECUTIONS = new Set([
  'LOCAL_MODEL',
  'DETERMINISTIC',
  'OPENAI_RESPONSES',
])
const LOCAL_PROVIDERS = new Set(['OLLAMA', 'OPENAI_COMPATIBLE'])
const FALLBACKS = new Set([
  'REQUEST_LIMIT',
  'TIMEOUT',
  'UNAVAILABLE',
  'UPSTREAM_REJECTED',
  'INVALID_RESPONSE',
  'RESPONSE_LIMIT',
])
const CONFIDENCES = new Set(['HIGH', 'MEDIUM', 'LOW'])
const MAX_DOCUMENT_BYTES = 64 * 1024

type RecordValue = Record<string, unknown>

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: RecordValue, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  )
}

function safeText(
  value: unknown,
  maximum: number,
  multiline = true,
): value is string {
  if (
    typeof value !== 'string' ||
    value.length < 1 ||
    Array.from(value).length > maximum ||
    value.trim() !== value
  ) {
    return false
  }
  return !Array.from(value).some((character) => {
    const point = character.codePointAt(0) ?? 0
    return (
      (point < 32 && (!multiline || !['\n', '\r', '\t'].includes(character))) ||
      point === 127
    )
  })
}

function safeReference(value: unknown): value is string {
  return safeText(value, 160, false) && !/\s/.test(value)
}

function uniqueStrings(
  value: unknown,
  minimum: number,
  maximum: number,
  predicate: (item: unknown) => item is string,
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.every(predicate) &&
    new Set(value).size === value.length
  )
}

function parseCommandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !exact(value, ['requestId', 'data']) ||
    typeof value.requestId !== 'string' ||
    !UUID.test(value.requestId)
  ) {
    throw new Error('Local AI workspace command response is invalid')
  }
  return value.data
}

function isCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= 1_000_000
}

function parseCounts(value: unknown): RecordValue | null {
  if (
    !isRecord(value) ||
    !exact(value, [
      'entities',
      'graphNodes',
      'graphEdges',
      'findings',
      'remediationCases',
      'auditRuns',
      'documentSegments',
    ]) ||
    !Object.values(value).every(isCount)
  ) {
    return null
  }
  return value
}

function validSection(value: unknown): boolean {
  return (
    isRecord(value) &&
    exact(value, ['heading', 'items']) &&
    safeText(value.heading, 96, false) &&
    Array.isArray(value.items) &&
    value.items.length >= 1 &&
    value.items.length <= 12 &&
    value.items.every(
      (item) =>
        isRecord(item) &&
        exact(item, ['text', 'evidenceRefs']) &&
        safeText(item.text, 600) &&
        uniqueStrings(item.evidenceRefs, 1, 8, safeReference),
    ) &&
    new Set(value.items.map((item) => (isRecord(item) ? item.text : '')))
      .size === value.items.length
  )
}

function validFact(value: unknown): boolean {
  return (
    isRecord(value) &&
    exact(value, ['statement', 'evidenceRefs', 'confidence']) &&
    safeText(value.statement, 600) &&
    uniqueStrings(value.evidenceRefs, 1, 8, safeReference) &&
    CONFIDENCES.has(String(value.confidence))
  )
}

function validConnection(value: unknown): boolean {
  return (
    isRecord(value) &&
    exact(value, [
      'fromRef',
      'toRef',
      'relationship',
      'supportingRefs',
      'contradictionRefs',
      'confidence',
      'rationale',
      'verificationSuggestion',
    ]) &&
    safeReference(value.fromRef) &&
    safeReference(value.toRef) &&
    value.fromRef !== value.toRef &&
    safeText(value.relationship, 96) &&
    uniqueStrings(value.supportingRefs, 1, 8, safeReference) &&
    uniqueStrings(value.contradictionRefs, 0, 8, safeReference) &&
    CONFIDENCES.has(String(value.confidence)) &&
    safeText(value.rationale, 600) &&
    safeText(value.verificationSuggestion, 600)
  )
}

function validNextStep(value: unknown): boolean {
  return (
    isRecord(value) &&
    exact(value, ['priority', 'suggestion', 'rationale', 'supportingRefs']) &&
    Number.isSafeInteger(value.priority) &&
    Number(value.priority) >= 1 &&
    Number(value.priority) <= 5 &&
    safeText(value.suggestion, 600) &&
    safeText(value.rationale, 600) &&
    uniqueStrings(value.supportingRefs, 1, 8, safeReference)
  )
}

function validSource(value: unknown): boolean {
  let sourceUrlValid = value === null
  let provenanceBindingValid = false
  if (isRecord(value)) {
    sourceUrlValid = value.sourceUrl === null
    if (typeof value.sourceUrl === 'string' && value.sourceUrl.length <= 2_048) {
      try {
        const url = new URL(value.sourceUrl)
        sourceUrlValid =
          ['http:', 'https:'].includes(url.protocol) &&
          url.hostname.length > 0 &&
          url.username === '' &&
          url.password === ''
      } catch {
        sourceUrlValid = false
      }
    }
    const completeSourceSegment =
      typeof value.sourceId === 'string' &&
      typeof value.sourceDisplayName === 'string' &&
      typeof value.contentSha256 === 'string' &&
      typeof value.segmentId === 'string' &&
      typeof value.segmentIndex === 'number' &&
      typeof value.segmentLocator === 'string'
    provenanceBindingValid =
      !['ENTITY_ORIGIN', 'GRAPH_EDGE_ORIGIN', 'DOCUMENT_SEGMENT'].includes(
        String(value.kind),
      ) || completeSourceSegment
    if (value.kind === 'ENTITY_ORIGIN') {
      provenanceBindingValid =
        provenanceBindingValid &&
        typeof value.observedAtUs === 'number' &&
        typeof value.confidenceMicros === 'number' &&
        typeof value.originKind === 'string'
    }
    if (value.kind === 'GRAPH_EDGE_ORIGIN') {
      provenanceBindingValid =
        provenanceBindingValid &&
        typeof value.extractionRunId === 'string' &&
        typeof value.extractorKind === 'string' &&
        typeof value.extractorName === 'string' &&
        typeof value.extractorVersion === 'string' &&
        typeof value.observedAtUs === 'number' &&
        typeof value.confidenceMicros === 'number' &&
        typeof value.originType === 'string' &&
        typeof value.disposition === 'string'
    }
    if (value.kind === 'EVIDENCE_METADATA') {
      provenanceBindingValid =
        typeof value.artifactId === 'string' &&
        typeof value.contentSha256 === 'string' &&
        typeof value.providerId === 'string' &&
        typeof value.runId === 'string' &&
        typeof value.observedAtUs === 'number' &&
        typeof value.captureMethod === 'string'
    }
  }
  return (
    isRecord(value) &&
    exact(value, [
      'ref',
      'kind',
      'label',
      'locator',
      'sourceUrl',
      'contentSha256',
      'providerId',
      'sourceId',
      'sourceDisplayName',
      'artifactId',
      'segmentId',
      'segmentIndex',
      'segmentLocator',
      'sourceSpanStart',
      'sourceSpanEnd',
      'extractionRunId',
      'extractorKind',
      'extractorName',
      'extractorVersion',
      'runId',
      'originKind',
      'originType',
      'observedAtUs',
      'confidenceMicros',
      'disposition',
      'sourceUrlSha256',
      'captureMethod',
      'httpStatus',
      'redirectCount',
    ]) &&
    safeReference(value.ref) &&
    safeText(value.kind, 64, false) &&
    safeText(value.label, 240, false) &&
    safeText(value.locator, 600, false) &&
    provenanceBindingValid &&
    sourceUrlValid &&
    (value.contentSha256 === null ||
      SHA256.test(String(value.contentSha256))) &&
    (value.providerId === null || safeText(value.providerId, 128, false)) &&
    (value.sourceId === null || safeReference(value.sourceId)) &&
    (value.sourceDisplayName === null ||
      safeText(value.sourceDisplayName, 255, false)) &&
    (value.artifactId === null || safeReference(value.artifactId)) &&
    (value.segmentId === null || safeReference(value.segmentId)) &&
    (value.segmentIndex === null ||
      (Number.isSafeInteger(value.segmentIndex) && Number(value.segmentIndex) >= 0)) &&
    (value.segmentLocator === null || safeText(value.segmentLocator, 600, false)) &&
    (value.sourceSpanStart === null ||
      (Number.isSafeInteger(value.sourceSpanStart) && Number(value.sourceSpanStart) >= 0)) &&
    (value.sourceSpanEnd === null ||
      (Number.isSafeInteger(value.sourceSpanEnd) && Number(value.sourceSpanEnd) > 0)) &&
    ((value.sourceSpanStart === null && value.sourceSpanEnd === null) ||
      (Number(value.sourceSpanEnd) > Number(value.sourceSpanStart))) &&
    (value.extractionRunId === null || safeReference(value.extractionRunId)) &&
    (value.extractorKind === null || safeText(value.extractorKind, 64, false)) &&
    (value.extractorName === null || safeText(value.extractorName, 96, false)) &&
    (value.extractorVersion === null || safeText(value.extractorVersion, 48, false)) &&
    (value.runId === null || safeReference(value.runId)) &&
    (value.originKind === null || safeText(value.originKind, 64, false)) &&
    (value.originType === null || safeText(value.originType, 64, false)) &&
    (value.observedAtUs === null ||
      (Number.isSafeInteger(value.observedAtUs) && Number(value.observedAtUs) >= 0)) &&
    (value.confidenceMicros === null ||
      (Number.isSafeInteger(value.confidenceMicros) &&
        Number(value.confidenceMicros) >= 0 &&
        Number(value.confidenceMicros) <= 1_000_000)) &&
    (value.disposition === null || safeText(value.disposition, 32, false)) &&
    (value.sourceUrlSha256 === null || SHA256.test(String(value.sourceUrlSha256))) &&
    ((value.sourceUrl === null && value.sourceUrlSha256 === null) ||
      (typeof value.sourceUrl === 'string' &&
        typeof value.sourceUrlSha256 === 'string')) &&
    (value.captureMethod === null || safeText(value.captureMethod, 64, false)) &&
    (value.httpStatus === null ||
      (Number.isSafeInteger(value.httpStatus) &&
        Number(value.httpStatus) >= 100 &&
        Number(value.httpStatus) <= 599)) &&
    (value.redirectCount === null ||
      (Number.isSafeInteger(value.redirectCount) &&
        Number(value.redirectCount) >= 0 &&
        Number(value.redirectCount) <= 20)) &&
    ((value.segmentId === null &&
      value.segmentIndex === null &&
      value.segmentLocator === null) ||
      (typeof value.segmentId === 'string' &&
        typeof value.segmentIndex === 'number' &&
        typeof value.segmentLocator === 'string'))
  )
}

function resultShapeIsValid(data: RecordValue): boolean {
  const included = parseCounts(data.includedCounts)
  const available = parseCounts(data.availableCounts)
  const countsValid =
    included !== null &&
    available !== null &&
    Object.keys(included).every(
      (key) => Number(included[key]) <= Number(available[key]),
    )
  const modelIdentity = (() => {
    if (data.executionMode === 'LOCAL_MODEL') {
      return (
        data.fallbackReason === null &&
        LOCAL_PROVIDERS.has(String(data.provider)) &&
        safeText(data.modelId, 256, false)
      )
    }
    if (data.executionMode === 'OPENAI_RESPONSES') {
      return (
        data.requestedExecution === 'OPENAI_RESPONSES' &&
        data.fallbackReason === null &&
        data.provider === 'OPENAI_RESPONSES' &&
        safeText(data.modelId, 256, false)
      )
    }
    if (data.requestedExecution === 'OPENAI_RESPONSES') {
      return (
        data.provider === 'OPENAI_RESPONSES' &&
        safeText(data.modelId, 256, false) &&
        data.fallbackReason !== null
      )
    }
    return data.provider === null && data.modelId === null
  })()
  const cited = new Set<string>()
  if (Array.isArray(data.sections)) {
    for (const section of data.sections) {
      if (!isRecord(section) || !Array.isArray(section.items)) continue
      for (const item of section.items) {
        if (isRecord(item) && Array.isArray(item.evidenceRefs)) {
          for (const reference of item.evidenceRefs) cited.add(String(reference))
        }
      }
    }
  }
  if (Array.isArray(data.facts)) {
    for (const fact of data.facts) {
      if (isRecord(fact) && Array.isArray(fact.evidenceRefs)) {
        for (const reference of fact.evidenceRefs) cited.add(String(reference))
      }
    }
  }
  if (Array.isArray(data.connections)) {
    for (const connection of data.connections) {
      if (!isRecord(connection)) continue
      cited.add(String(connection.fromRef))
      cited.add(String(connection.toRef))
      for (const key of ['supportingRefs', 'contradictionRefs'] as const) {
        if (Array.isArray(connection[key])) {
          for (const reference of connection[key]) cited.add(String(reference))
        }
      }
    }
  }
  if (Array.isArray(data.nextSteps)) {
    for (const step of data.nextSteps) {
      if (isRecord(step) && Array.isArray(step.supportingRefs)) {
        for (const reference of step.supportingRefs) cited.add(String(reference))
      }
    }
  }
  const sourceRefs = Array.isArray(data.sources)
    ? data.sources.map((source) =>
        isRecord(source) ? String(source.ref) : '',
      )
    : []
  return (
    UUID.test(String(data.profileId)) &&
    TASKS.has(String(data.task)) &&
    uniqueStrings(data.selectedScopes, 1, 6, (scope): scope is string =>
      SCOPES.has(String(scope)),
    ) &&
    EXECUTIONS.has(String(data.requestedExecution)) &&
    EXECUTIONS.has(String(data.executionMode)) &&
    (data.fallbackReason === null ||
      FALLBACKS.has(String(data.fallbackReason))) &&
    modelIdentity &&
    !(
      data.requestedExecution === 'DETERMINISTIC' &&
      (data.executionMode !== 'DETERMINISTIC' || data.fallbackReason !== null)
    ) &&
    !(
      data.requestedExecution === 'LOCAL_MODEL' &&
      data.executionMode === 'DETERMINISTIC' &&
      data.fallbackReason === null
    ) &&
    data.engineVersion === '1' &&
    safeText(data.title, 120, false) &&
    safeText(data.summary, 2_000) &&
    Array.isArray(data.sections) &&
    data.sections.length <= 8 &&
    data.sections.every(validSection) &&
    Array.isArray(data.facts) &&
    data.facts.length <= 20 &&
    data.facts.every(validFact) &&
    Array.isArray(data.connections) &&
    data.connections.length <= 16 &&
    data.connections.every(validConnection) &&
    Array.isArray(data.nextSteps) &&
    data.nextSteps.length <= 16 &&
    data.nextSteps.every(validNextStep) &&
    Array.isArray(data.sources) &&
    data.sources.length <= 128 &&
    data.sources.every(validSource) &&
    new Set(sourceRefs).size === sourceRefs.length &&
    sourceRefs.length === cited.size &&
    sourceRefs.every((reference) => cited.has(reference)) &&
    (data.unanswered === null || safeText(data.unanswered, 1_000)) &&
    uniqueStrings(data.limitations, 0, 12, (item): item is string =>
      safeText(item, 600),
    ) &&
    countsValid &&
    typeof data.projectionTruncated === 'boolean' &&
    SHA256.test(String(data.inputSha256)) &&
    Number.isSafeInteger(data.restrictedValuesRedacted) &&
    Number(data.restrictedValuesRedacted) >= 0 &&
    Number(data.restrictedValuesRedacted) <= 10_000 &&
    typeof data.localOnly === 'boolean' &&
    typeof data.externalNetworkUsed === 'boolean' &&
    (data.requestedExecution === 'OPENAI_RESPONSES'
      ? data.localOnly === false && data.externalNetworkUsed === true
      : data.localOnly === true && data.externalNetworkUsed === false) &&
    data.rawEvidenceIncluded === false &&
    data.reviewOnly === true &&
    data.humanReviewRequired === true
  )
}

export function parseLocalAIWorkspaceResult(
  value: unknown,
): LocalAIWorkspaceResult {
  const data = parseCommandData(value)
  const keys = [
    'profileId',
    'task',
    'selectedScopes',
    'requestedExecution',
    'executionMode',
    'fallbackReason',
    'provider',
    'modelId',
    'engineVersion',
    'title',
    'summary',
    'sections',
    'facts',
    'connections',
    'nextSteps',
    'sources',
    'unanswered',
    'limitations',
    'includedCounts',
    'availableCounts',
    'projectionTruncated',
    'inputSha256',
    'restrictedValuesRedacted',
    'localOnly',
    'externalNetworkUsed',
    'rawEvidenceIncluded',
    'reviewOnly',
    'humanReviewRequired',
  ]
  if (!isRecord(data) || !exact(data, keys) || !resultShapeIsValid(data)) {
    throw new Error('Local AI workspace response is invalid')
  }
  return data as unknown as LocalAIWorkspaceResult
}

function requestIsValid(request: LocalAIWorkspaceRequest): boolean {
  const scopes = [...request.scopes]
  const documentSelected = scopes.includes('DOCUMENT')
  const questionValid =
    request.task === 'QUESTION'
      ? safeText(request.question, 2_000)
      : request.question === null || request.question === undefined
  const apiKey = request.openaiApiKey
  const apiKeyValid =
    typeof apiKey === 'string' &&
    apiKey.length > 0 &&
    new TextEncoder().encode(apiKey).byteLength <= 512 &&
    apiKey.trim() === apiKey &&
    !Array.from(apiKey).some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point <= 32 || point === 127
    })
  const modelValid = (() => {
    if (request.execution === 'LOCAL_MODEL') {
      return (
        safeText(request.modelId, 256, false) &&
        (apiKey === null || apiKey === undefined)
      )
    }
    if (request.execution === 'OPENAI_RESPONSES') {
      return safeText(request.modelId, 256, false) && apiKeyValid
    }
    return (
      (request.modelId === null || request.modelId === undefined) &&
      (apiKey === null || apiKey === undefined)
    )
  })()
  const contentBytes = request.document
    ? new TextEncoder().encode(request.document.content).byteLength
    : 0
  return (
    UUID.test(request.profileId) &&
    TASKS.has(request.task) &&
    scopes.length >= 1 &&
    scopes.length <= 6 &&
    scopes.every((scope) => SCOPES.has(scope)) &&
    new Set(scopes).size === scopes.length &&
    questionValid &&
    modelValid &&
    documentSelected === Boolean(request.document) &&
    (request.document === null ||
      request.document === undefined ||
      (safeText(request.document.displayName, 255, false) &&
        safeText(request.document.content, MAX_DOCUMENT_BYTES) &&
        contentBytes <= MAX_DOCUMENT_BYTES &&
        SHA256.test(request.document.contentSha256)))
  )
}

export async function analyzeLocalAIWorkspace(
  request: LocalAIWorkspaceRequest,
): Promise<LocalAIWorkspaceResult> {
  if (!requestIsValid(request)) {
    throw new Error('Local AI workspace request is invalid')
  }
  const { invoke } = await import('@tauri-apps/api/core')
  return parseLocalAIWorkspaceResult(
    await invoke('core_analyze_local_ai_workspace', { request }),
  )
}

export const localAiWorkspaceBoundaryParsers = {
  result: parseLocalAIWorkspaceResult,
}
