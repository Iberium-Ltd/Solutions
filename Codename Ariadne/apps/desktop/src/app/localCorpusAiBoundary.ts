/**
 * Browser-side boundary for ephemeral corpus reasoning. Documents and results
 * are size-bounded and shape-checked; citations reference the supplied corpus.
 */
export type LocalCorpusMediaType =
  | 'text/plain'
  | 'text/markdown'
  | 'text/x-markdown'
  | 'text/csv'
  | 'application/json'
  | 'text/vcard'
  | 'text/x-vcard'

export type LocalCorpusAITask =
  | 'SUMMARY'
  | 'ORGANIZE'
  | 'QUESTION'
  | 'CONNECTIONS'
  | 'GAP_ANALYSIS'
export type LocalCorpusAIExecution =
  | 'LOCAL_MODEL'
  | 'DETERMINISTIC'
  | 'OPENAI_RESPONSES'
export type LocalCorpusAIConfidence = 'HIGH' | 'MEDIUM' | 'LOW'
export type LocalCorpusAIContentOrigin =
  | 'DETERMINISTIC'
  | 'LOCAL_MODEL'
  | 'OPENAI_RESPONSES'
export type LocalCorpusAITextLabel =
  | 'ORGANIZATION'
  | 'CITED_SUMMARY'
  | 'HYPOTHESIS'
  | 'LIMITATION'
export type LocalCorpusAIReferenceKind = 'SEGMENT' | 'ENTITY'
export type LocalCorpusAIFallbackReason =
  | 'REQUEST_LIMIT'
  | 'RESPONSE_LIMIT'
  | 'TIMEOUT'
  | 'UNAVAILABLE'
  | 'UPSTREAM_REJECTED'
  | 'INVALID_RESPONSE'
  | 'CONFIGURATION'

export interface LocalCorpusDocumentRequest {
  readonly displayName: string
  readonly declaredMediaType: LocalCorpusMediaType
  readonly contentBase64: string
  readonly expectedSizeBytes: number
  readonly expectedSha256: string
}

export interface LocalCorpusAIRequest {
  readonly documents: ReadonlyArray<LocalCorpusDocumentRequest>
  readonly semanticEnrichmentEnabled: boolean
  readonly profileId: string
  readonly task: LocalCorpusAITask
  readonly question: string | null
  readonly execution: LocalCorpusAIExecution
  readonly modelId: string | null
  readonly openaiApiKey?: string | null
  readonly maxSegments: number
}

export interface LocalCorpusAISourcePointer {
  readonly documentId: string
  readonly documentName: string
  readonly segmentId: string
  readonly segmentIndex: number
  readonly locator: string
}

export interface LocalCorpusAISourceCatalogEntry {
  readonly referenceId: string
  readonly referenceKind: LocalCorpusAIReferenceKind
  readonly sources: ReadonlyArray<LocalCorpusAISourcePointer>
}

export interface LocalCorpusAIReviewNote {
  readonly text: string
  readonly label: LocalCorpusAITextLabel
  readonly origin: LocalCorpusAIContentOrigin
  readonly evidenceRefs: ReadonlyArray<string>
}

export interface LocalCorpusAISection {
  readonly heading: string
  readonly items: ReadonlyArray<LocalCorpusAIReviewNote>
}

export interface LocalCorpusAIFact {
  readonly statement: string
  readonly evidenceRefs: ReadonlyArray<string>
  readonly confidence: LocalCorpusAIConfidence
  readonly origin: LocalCorpusAIContentOrigin
}

export interface LocalCorpusAIConnection {
  readonly fromRef: string
  readonly toRef: string
  readonly sharedEntityRefs: ReadonlyArray<string>
  readonly relationship: string
  readonly supportingRefs: ReadonlyArray<string>
  readonly contradictionRefs: ReadonlyArray<string>
  readonly confidence: LocalCorpusAIConfidence
  readonly origin: LocalCorpusAIContentOrigin
  readonly rationale: string
  readonly verificationSuggestion: string
}

export interface LocalCorpusAINextStep {
  readonly priority: number
  readonly suggestion: string
  readonly rationale: string
  readonly supportingRefs: ReadonlyArray<string>
  readonly origin: LocalCorpusAIContentOrigin
}

export interface LocalCorpusAICounts {
  readonly documents: number
  readonly segments: number
  readonly entities: number
  readonly sharedEntities: number
}

export interface LocalCorpusAIResult {
  readonly profileId: string
  readonly corpusId: string
  readonly inputManifestSha256: string
  readonly inputSha256: string
  readonly task: LocalCorpusAITask
  readonly requestedExecution: LocalCorpusAIExecution
  readonly executionMode: LocalCorpusAIExecution
  readonly fallbackReason: LocalCorpusAIFallbackReason | null
  readonly provider: 'OLLAMA' | 'OPENAI_COMPATIBLE' | 'OPENAI_RESPONSES' | null
  readonly modelId: string | null
  readonly engineVersion: '1'
  readonly title: string
  readonly draftSummary: string
  readonly narrativeLabel: 'DRAFT_SUMMARY_NOT_A_FACT'
  readonly sections: ReadonlyArray<LocalCorpusAISection>
  readonly facts: ReadonlyArray<LocalCorpusAIFact>
  readonly connections: ReadonlyArray<LocalCorpusAIConnection>
  readonly nextSteps: ReadonlyArray<LocalCorpusAINextStep>
  readonly unanswered: string | null
  readonly uncertainties: ReadonlyArray<LocalCorpusAIReviewNote>
  readonly sourceCatalog: ReadonlyArray<LocalCorpusAISourceCatalogEntry>
  readonly includedCounts: LocalCorpusAICounts
  readonly availableCounts: LocalCorpusAICounts
  readonly projectionTruncated: boolean
  readonly restrictedValuesRedacted: number
  readonly localOnly: boolean
  readonly externalNetworkUsed: boolean
  readonly rawSourcesRetained: false
  readonly persisted: false
  readonly reviewOnly: true
  readonly humanReviewRequired: true
}

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256 = /^[0-9a-f]{64}$/
const CORPUS_ID = /^corpus:[0-9a-f]{64}$/
const DOCUMENT_ID = /^corpus-document:[0-9]{4}:[0-9a-f]{64}$/
const SEGMENT_ID = /^corpus-document:[0-9]{4}:[0-9a-f]{64}:segment:[0-9]{1,5}$/
const ENTITY_ID = /^corpus-entity:[0-9a-f]{64}$/
const TASKS = new Set<LocalCorpusAITask>([
  'SUMMARY', 'ORGANIZE', 'QUESTION', 'CONNECTIONS', 'GAP_ANALYSIS',
])
const EXECUTIONS = new Set<LocalCorpusAIExecution>([
  'LOCAL_MODEL', 'DETERMINISTIC', 'OPENAI_RESPONSES',
])
const CONFIDENCES = new Set<LocalCorpusAIConfidence>(['HIGH', 'MEDIUM', 'LOW'])
const ORIGINS = new Set<LocalCorpusAIContentOrigin>([
  'DETERMINISTIC', 'LOCAL_MODEL', 'OPENAI_RESPONSES',
])
const LABELS = new Set<LocalCorpusAITextLabel>([
  'ORGANIZATION', 'CITED_SUMMARY', 'HYPOTHESIS', 'LIMITATION',
])
const FALLBACKS = new Set<LocalCorpusAIFallbackReason>([
  'REQUEST_LIMIT', 'RESPONSE_LIMIT', 'TIMEOUT', 'UNAVAILABLE',
  'UPSTREAM_REJECTED', 'INVALID_RESPONSE', 'CONFIGURATION',
])
const LOCAL_PROVIDERS = new Set(['OLLAMA', 'OPENAI_COMPATIBLE'])
const MEDIA_BY_SUFFIX: Record<string, ReadonlySet<LocalCorpusMediaType>> = {
  txt: new Set(['text/plain']),
  md: new Set(['text/markdown', 'text/x-markdown']),
  csv: new Set(['text/csv']),
  json: new Set(['application/json']),
  vcf: new Set(['text/vcard', 'text/x-vcard']),
}
const DEFAULT_MEDIA: Record<string, LocalCorpusMediaType> = {
  txt: 'text/plain', md: 'text/markdown', csv: 'text/csv',
  json: 'application/json', vcf: 'text/vcard',
}
const MAX_DOCUMENT_BYTES = 1_048_576
const MAX_TOTAL_BYTES = 4 * 1_048_576

type RecordValue = Record<string, unknown>

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: RecordValue, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function safeText(value: unknown, maximum: number, multiline = true): value is string {
  if (
    typeof value !== 'string' || value.length === 0 ||
    Array.from(value).length > maximum || value.trim() !== value
  ) return false
  return !Array.from(value).some((character) => {
    const point = character.codePointAt(0) ?? 0
    return (point < 32 && (!multiline || !['\n', '\r', '\t'].includes(character))) ||
      point === 127 || (point >= 0xd800 && point <= 0xdfff)
  })
}

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum
}

function uniqueArray<T extends string>(
  value: unknown,
  minimum: number,
  maximum: number,
  predicate: (item: unknown) => item is T,
): value is T[] {
  return Array.isArray(value) && value.length >= minimum && value.length <= maximum &&
    value.every(predicate) && new Set(value).size === value.length
}

function isReference(value: unknown): value is string {
  return typeof value === 'string' && (SEGMENT_ID.test(value) || ENTITY_ID.test(value))
}

function validPointer(value: unknown): value is LocalCorpusAISourcePointer {
  return isRecord(value) && exact(value, [
    'documentId', 'documentName', 'segmentId', 'segmentIndex', 'locator',
  ]) && typeof value.documentId === 'string' && DOCUMENT_ID.test(value.documentId) &&
    safeText(value.documentName, 255, false) &&
    typeof value.segmentId === 'string' && SEGMENT_ID.test(value.segmentId) &&
    integer(value.segmentIndex, 0, 99_999) && safeText(value.locator, 4_096) &&
    value.segmentId.startsWith(`${value.documentId}:segment:`) &&
    value.segmentId.endsWith(`:${value.segmentIndex}`)
}

function validCatalogEntry(value: unknown): value is LocalCorpusAISourceCatalogEntry {
  if (!isRecord(value) || !exact(value, ['referenceId', 'referenceKind', 'sources']) ||
      !isReference(value.referenceId) ||
      !['SEGMENT', 'ENTITY'].includes(String(value.referenceKind)) ||
      !Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 32 ||
      !value.sources.every(validPointer) ||
      new Set(value.sources.map((source) => source.segmentId)).size !== value.sources.length) return false
  const isSegment = value.referenceKind === 'SEGMENT'
  return isSegment === SEGMENT_ID.test(value.referenceId) &&
    (!isSegment || (value.sources.length === 1 && value.sources[0]?.segmentId === value.referenceId))
}

function validReviewNote(value: unknown): value is LocalCorpusAIReviewNote {
  if (!isRecord(value) || !exact(value, ['text', 'label', 'origin', 'evidenceRefs']) ||
      !safeText(value.text, 600) || !LABELS.has(value.label as LocalCorpusAITextLabel) ||
      !ORIGINS.has(value.origin as LocalCorpusAIContentOrigin) ||
      !uniqueArray(value.evidenceRefs, 0, 8, isReference)) return false
  return !(['ORGANIZATION', 'CITED_SUMMARY'].includes(String(value.label)) &&
    value.evidenceRefs.length === 0)
}

function validSection(value: unknown): value is LocalCorpusAISection {
  return isRecord(value) && exact(value, ['heading', 'items']) &&
    safeText(value.heading, 96, false) && Array.isArray(value.items) &&
    value.items.length >= 1 && value.items.length <= 12 && value.items.every(validReviewNote)
}

function validFact(value: unknown): value is LocalCorpusAIFact {
  return isRecord(value) && exact(value, ['statement', 'evidenceRefs', 'confidence', 'origin']) &&
    safeText(value.statement, 600) && uniqueArray(value.evidenceRefs, 1, 8, isReference) &&
    CONFIDENCES.has(value.confidence as LocalCorpusAIConfidence) &&
    ORIGINS.has(value.origin as LocalCorpusAIContentOrigin)
}

function validConnection(value: unknown): value is LocalCorpusAIConnection {
  if (!isRecord(value) || !exact(value, [
    'fromRef', 'toRef', 'sharedEntityRefs', 'relationship', 'supportingRefs',
    'contradictionRefs', 'confidence', 'origin', 'rationale', 'verificationSuggestion',
  ]) || typeof value.fromRef !== 'string' || !SEGMENT_ID.test(value.fromRef) ||
      typeof value.toRef !== 'string' || !SEGMENT_ID.test(value.toRef) ||
      value.fromRef === value.toRef ||
      !uniqueArray(value.sharedEntityRefs, 1, 4, (item): item is string =>
        typeof item === 'string' && ENTITY_ID.test(item)) ||
      !safeText(value.relationship, 96) ||
      !uniqueArray(value.supportingRefs, 3, 8, isReference) ||
      !uniqueArray(value.contradictionRefs, 0, 8, isReference) ||
      !CONFIDENCES.has(value.confidence as LocalCorpusAIConfidence) ||
      !ORIGINS.has(value.origin as LocalCorpusAIContentOrigin) ||
      !safeText(value.rationale, 600) || !safeText(value.verificationSuggestion, 600)) return false
  const support = new Set(value.supportingRefs)
  return [value.fromRef, value.toRef, ...value.sharedEntityRefs].every((item) => support.has(item))
}

function validNextStep(value: unknown): value is LocalCorpusAINextStep {
  return isRecord(value) && exact(value, [
    'priority', 'suggestion', 'rationale', 'supportingRefs', 'origin',
  ]) && integer(value.priority, 1, 5) && safeText(value.suggestion, 600) &&
    safeText(value.rationale, 600) && uniqueArray(value.supportingRefs, 1, 8, isReference) &&
    ORIGINS.has(value.origin as LocalCorpusAIContentOrigin)
}

function parseCounts(value: unknown): LocalCorpusAICounts | null {
  if (!isRecord(value) || !exact(value, ['documents', 'segments', 'entities', 'sharedEntities']) ||
      !integer(value.documents, 1, 20) || !integer(value.segments, 1, 5_000) ||
      !integer(value.entities, 0, 4_096) || !integer(value.sharedEntities, 0, 4_096)) return null
  return value as unknown as LocalCorpusAICounts
}

function commandData(value: unknown): unknown {
  if (!isRecord(value) || !exact(value, ['requestId', 'data']) ||
      typeof value.requestId !== 'string' || !UUID.test(value.requestId)) {
    throw new Error('Local corpus AI command response is invalid')
  }
  return value.data
}

export function parseLocalCorpusAIResult(value: unknown): LocalCorpusAIResult {
  const data = commandData(value)
  const keys = [
    'profileId', 'corpusId', 'inputManifestSha256', 'inputSha256', 'task',
    'requestedExecution', 'executionMode', 'fallbackReason', 'provider', 'modelId',
    'engineVersion', 'title', 'draftSummary', 'narrativeLabel', 'sections', 'facts',
    'connections', 'nextSteps', 'unanswered', 'uncertainties', 'sourceCatalog',
    'includedCounts', 'availableCounts', 'projectionTruncated',
    'restrictedValuesRedacted', 'localOnly', 'externalNetworkUsed',
    'rawSourcesRetained', 'persisted', 'reviewOnly', 'humanReviewRequired',
  ]
  if (!isRecord(data) || !exact(data, keys)) throw new Error('Local corpus AI response is invalid')
  const included = parseCounts(data.includedCounts)
  const available = parseCounts(data.availableCounts)
  const sectionsValid = Array.isArray(data.sections) && data.sections.length <= 8 && data.sections.every(validSection)
  const factsValid = Array.isArray(data.facts) && data.facts.length <= 20 && data.facts.every(validFact)
  const connectionsValid = Array.isArray(data.connections) && data.connections.length <= 16 && data.connections.every(validConnection)
  const stepsValid = Array.isArray(data.nextSteps) && data.nextSteps.length <= 16 && data.nextSteps.every(validNextStep)
  const uncertaintiesValid = Array.isArray(data.uncertainties) && data.uncertainties.length <= 12 && data.uncertainties.every(validReviewNote)
  const catalogValid = Array.isArray(data.sourceCatalog) && data.sourceCatalog.length <= 512 &&
    data.sourceCatalog.every(validCatalogEntry) &&
    new Set(data.sourceCatalog.map((entry) => entry.referenceId)).size === data.sourceCatalog.length
  const catalog = new Set(
    Array.isArray(data.sourceCatalog)
      ? data.sourceCatalog.filter(isRecord).map((entry) => String(entry.referenceId))
      : [],
  )
  const sections = sectionsValid ? data.sections as LocalCorpusAISection[] : []
  const facts = factsValid ? data.facts as LocalCorpusAIFact[] : []
  const connections = connectionsValid ? data.connections as LocalCorpusAIConnection[] : []
  const steps = stepsValid ? data.nextSteps as LocalCorpusAINextStep[] : []
  const uncertainties = uncertaintiesValid
    ? data.uncertainties as LocalCorpusAIReviewNote[]
    : []
  const cited = new Set<string>()
  for (const section of sections) for (const item of section.items) for (const ref of item.evidenceRefs) cited.add(ref)
  for (const fact of facts) for (const ref of fact.evidenceRefs) cited.add(ref)
  for (const connection of connections) {
    for (const ref of [connection.fromRef, connection.toRef, ...connection.sharedEntityRefs, ...connection.supportingRefs, ...connection.contradictionRefs]) cited.add(ref)
  }
  for (const step of steps) for (const ref of step.supportingRefs) cited.add(ref)
  for (const note of uncertainties) for (const ref of note.evidenceRefs) cited.add(ref)
  const localIdentity = (() => {
    if (data.executionMode === 'LOCAL_MODEL') {
      return data.fallbackReason === null &&
        LOCAL_PROVIDERS.has(String(data.provider)) && safeText(data.modelId, 256, false)
    }
    if (data.executionMode === 'OPENAI_RESPONSES') {
      return data.requestedExecution === 'OPENAI_RESPONSES' &&
        data.fallbackReason === null && data.provider === 'OPENAI_RESPONSES' &&
        safeText(data.modelId, 256, false)
    }
    if (data.requestedExecution === 'OPENAI_RESPONSES') {
      return data.provider === 'OPENAI_RESPONSES' &&
        safeText(data.modelId, 256, false) && data.fallbackReason !== null
    }
    return data.provider === null && data.modelId === null
  })()
  const valid = typeof data.profileId === 'string' && UUID.test(data.profileId) &&
    typeof data.corpusId === 'string' && CORPUS_ID.test(data.corpusId) &&
    typeof data.inputManifestSha256 === 'string' && SHA256.test(data.inputManifestSha256) &&
    typeof data.inputSha256 === 'string' && SHA256.test(data.inputSha256) &&
    TASKS.has(data.task as LocalCorpusAITask) && EXECUTIONS.has(data.requestedExecution as LocalCorpusAIExecution) &&
    EXECUTIONS.has(data.executionMode as LocalCorpusAIExecution) &&
    (data.fallbackReason === null || FALLBACKS.has(data.fallbackReason as LocalCorpusAIFallbackReason)) &&
    localIdentity && !(data.requestedExecution === 'DETERMINISTIC' &&
      (data.executionMode !== 'DETERMINISTIC' || data.fallbackReason !== null)) &&
    !(data.requestedExecution === 'LOCAL_MODEL' && data.executionMode === 'DETERMINISTIC' && data.fallbackReason === null) &&
    data.engineVersion === '1' && safeText(data.title, 120, false) &&
    safeText(data.draftSummary, 2_000) && data.narrativeLabel === 'DRAFT_SUMMARY_NOT_A_FACT' &&
    sectionsValid && factsValid && connectionsValid && stepsValid &&
    (data.unanswered === null || safeText(data.unanswered, 1_000)) && uncertaintiesValid &&
    catalogValid && [...cited].every((reference) => catalog.has(reference)) &&
    included !== null && available !== null &&
    included.documents <= available.documents && included.segments <= available.segments &&
    included.entities <= available.entities && included.sharedEntities <= available.sharedEntities &&
    typeof data.projectionTruncated === 'boolean' && integer(data.restrictedValuesRedacted, 0, 20_000) &&
    typeof data.localOnly === 'boolean' && typeof data.externalNetworkUsed === 'boolean' &&
    (data.requestedExecution === 'OPENAI_RESPONSES'
      ? data.localOnly === false && data.externalNetworkUsed === true
      : data.localOnly === true && data.externalNetworkUsed === false) &&
    data.rawSourcesRetained === false && data.persisted === false &&
    data.reviewOnly === true && data.humanReviewRequired === true
  if (!valid) throw new Error('Local corpus AI response is invalid')
  return data as unknown as LocalCorpusAIResult
}

function documentExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase()
}

function validDocumentShape(document: LocalCorpusDocumentRequest): boolean {
  const extension = documentExtension(document.displayName)
  return safeText(document.displayName, 255, false) &&
    !document.displayName.includes('/') && !document.displayName.includes('\\') &&
    Boolean(MEDIA_BY_SUFFIX[extension]?.has(document.declaredMediaType)) &&
    integer(document.expectedSizeBytes, 1, MAX_DOCUMENT_BYTES) &&
    SHA256.test(document.expectedSha256) &&
    document.contentBase64.length >= 4 && document.contentBase64.length <= 1_398_104 &&
    /^[A-Za-z0-9+/]+={0,2}$/.test(document.contentBase64)
}

function decodeBase64(value: string): Uint8Array {
  const decoded = atob(value)
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0))
}

async function digestHex(bytes: Uint8Array): Promise<string> {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  const digest = await crypto.subtle.digest('SHA-256', copy.buffer)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function encodeBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 32_768
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk))
  }
  return btoa(binary)
}

export async function prepareLocalCorpusDocument(file: File): Promise<LocalCorpusDocumentRequest> {
  const extension = documentExtension(file.name)
  const supported = MEDIA_BY_SUFFIX[extension]
  if (!supported || file.size < 1 || file.size > MAX_DOCUMENT_BYTES ||
      !safeText(file.name, 255, false) || file.name.includes('/') || file.name.includes('\\')) {
    throw new Error('Select a supported UTF-8 file no larger than 1 MiB.')
  }
  const bytes = new Uint8Array(await file.arrayBuffer())
  try {
    new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new Error('Corpus documents must be valid UTF-8 text.')
  }
  const declared = supported.has(file.type as LocalCorpusMediaType)
    ? file.type as LocalCorpusMediaType
    : DEFAULT_MEDIA[extension]
  if (!declared) throw new Error('The selected document type is unsupported.')
  return {
    displayName: file.name,
    declaredMediaType: declared,
    contentBase64: encodeBase64(bytes),
    expectedSizeBytes: bytes.byteLength,
    expectedSha256: await digestHex(bytes),
  }
}

async function validateRequest(request: LocalCorpusAIRequest): Promise<void> {
  const total = request.documents.reduce((sum, document) => sum + document.expectedSizeBytes, 0)
  const shape = UUID.test(request.profileId) && TASKS.has(request.task) &&
    request.documents.length >= 1 && request.documents.length <= 20 && total <= MAX_TOTAL_BYTES &&
    request.documents.every(validDocumentShape) && typeof request.semanticEnrichmentEnabled === 'boolean' &&
    integer(request.maxSegments, 1, 200) &&
    (request.task === 'QUESTION' ? safeText(request.question, 2_000) &&
      new TextEncoder().encode(request.question).byteLength <= 2_048 : request.question === null) &&
    (request.execution === 'LOCAL_MODEL'
      ? safeText(request.modelId, 256, false) &&
        (request.openaiApiKey === null || request.openaiApiKey === undefined)
      : request.execution === 'OPENAI_RESPONSES'
        ? safeText(request.modelId, 256, false) &&
          typeof request.openaiApiKey === 'string' &&
          request.openaiApiKey.length > 0 &&
          new TextEncoder().encode(request.openaiApiKey).byteLength <= 512 &&
          request.openaiApiKey.trim() === request.openaiApiKey &&
          !Array.from(request.openaiApiKey).some((character) => {
            const point = character.codePointAt(0) ?? 0
            return point <= 32 || point === 127
          })
        : request.modelId === null &&
          (request.openaiApiKey === null || request.openaiApiKey === undefined))
  if (!shape) throw new Error('Local corpus AI request is invalid')
  for (const document of request.documents) {
    let bytes: Uint8Array
    try {
      bytes = decodeBase64(document.contentBase64)
    } catch {
      throw new Error('Local corpus AI request is invalid')
    }
    if (bytes.byteLength !== document.expectedSizeBytes ||
        await digestHex(bytes) !== document.expectedSha256 ||
        encodeBase64(bytes) !== document.contentBase64) {
      throw new Error('Local corpus AI document integrity check failed')
    }
  }
}

export async function analyzeLocalCorpusAI(request: LocalCorpusAIRequest): Promise<LocalCorpusAIResult> {
  await validateRequest(request)
  const { invoke } = await import('@tauri-apps/api/core')
  return parseLocalCorpusAIResult(
    await invoke('core_analyze_local_ai_corpus', { request }),
  )
}

export const localCorpusAiBoundaryParsers = { result: parseLocalCorpusAIResult }
