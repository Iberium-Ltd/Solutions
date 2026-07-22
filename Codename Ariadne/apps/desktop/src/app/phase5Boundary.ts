/**
 * Runtime parser for immutable evidence and append-only attribution contracts.
 *
 * The boundary keeps originals, redacted derivatives, assessments, and human
 * decisions distinct; treating one as another would erase provenance in the UI.
 */
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const TOKEN_PATTERN = /^[A-Z][A-Z0-9_]{0,95}$/
const OPAQUE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const POLICY_VERSION_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/
const SUMMARY_CODE_PATTERN = /^[A-Z][A-Z0-9_]{1,63}$/
const METADATA_KEY_PATTERN = /^[a-z][a-z0-9_.-]{0,47}$/
const BASE64_PATTERN = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/
const MAX_ARTIFACT_BYTES = 10 * 1_024 * 1_024
const MAX_BASE64_CHARACTERS = 4 * Math.ceil(MAX_ARTIFACT_BYTES / 3)

const CHECK_OUTCOMES = new Set([
  'FOUND',
  'NOT_FOUND',
  'NOT_CHECKED',
  'CHECK_FAILED',
  'ACCESS_BLOCKED',
  'AUTH_REQUIRED',
  'RATE_LIMITED',
  'PROVIDER_UNAVAILABLE',
  'AMBIGUOUS',
  'MANUAL_REVIEW_REQUIRED',
  'AUTHORITATIVE_ABSENCE',
] as const)
const SEVERITIES = new Set(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const)
const VISIBILITIES = new Set([
  'PUBLICLY_ATTRIBUTABLE',
  'PUBLIC_PSEUDONYMOUS',
  'PRIVATELY_LINKABLE',
  'HISTORICAL_RESIDUE',
  'PRIVATE_ONLY',
  'UNKNOWN',
] as const)
const ATTRIBUTION_STATES = new Set([
  'CONFIRMED_MATCH',
  'CONFIRMED_NON_MATCH',
  'PROBABLE',
  'POSSIBLE',
  'UNRESOLVED',
  'NEEDS_MORE_EVIDENCE',
] as const)
const CONFIDENCE_BANDS = new Set([
  'VERY_LOW',
  'LOW',
  'MEDIUM',
  'HIGH',
  'VERY_HIGH',
] as const)
const POSITIVE_SIGNALS = new Set([
  'EXACT_EMAIL',
  'RECOVERY_RELATIONSHIP',
  'EXACT_LEGAL_NAME',
  'SAME_UNCOMMON_USERNAME',
  'SAME_PHOTOGRAPH',
  'SAME_ORGANISATION',
  'SAME_EDUCATION',
  'SAME_LOCATION',
  'SAME_PROJECT',
  'SAME_LINKED_DOMAIN',
  'SAME_WRITING_PROFILE_LINKS',
  'CHRONOLOGICAL_COMPATIBILITY',
  'USER_CONFIRMATION',
  'IMMUTABLE_PLATFORM_ID_CONTINUITY',
] as const)
const NEGATIVE_SIGNALS = new Set([
  'CONFLICTING_AGE',
  'CONFLICTING_PHOTOGRAPH',
  'INCOMPATIBLE_GEOGRAPHY',
  'ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP',
  'DIFFERENT_IMMUTABLE_ACCOUNT_ID',
  'CONTRADICTORY_BIOGRAPHY',
  'EXPLICIT_USER_EXCLUSION',
  'USERNAME_RECYCLING_EVIDENCE',
] as const)
const ARTIFACT_KINDS = new Set([
  'SCREENSHOT',
  'HTML',
  'PDF',
  'RAW_JSON',
  'URL_REFERENCE',
] as const)
const MANUAL_ARTIFACT_KINDS = new Set([
  'SCREENSHOT',
  'HTML',
  'PDF',
  'RAW_JSON',
] as const)
const CAPTURE_METHODS = new Set([
  'BROWSER_CAPTURE',
  'HTTP_FETCH',
  'PROVIDER_API',
  'MANUAL_LOCAL_IMPORT',
] as const)
const INTEGRITY_STATUSES = new Set([
  'VERIFIED',
  'NOT_VERIFIED',
  'FAILED',
] as const)

export type Phase5CheckOutcome =
  | 'FOUND'
  | 'NOT_FOUND'
  | 'NOT_CHECKED'
  | 'CHECK_FAILED'
  | 'ACCESS_BLOCKED'
  | 'AUTH_REQUIRED'
  | 'RATE_LIMITED'
  | 'PROVIDER_UNAVAILABLE'
  | 'AMBIGUOUS'
  | 'MANUAL_REVIEW_REQUIRED'
  | 'AUTHORITATIVE_ABSENCE'
export type Phase5Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
export type Phase5Visibility =
  | 'PUBLICLY_ATTRIBUTABLE'
  | 'PUBLIC_PSEUDONYMOUS'
  | 'PRIVATELY_LINKABLE'
  | 'HISTORICAL_RESIDUE'
  | 'PRIVATE_ONLY'
  | 'UNKNOWN'
export type Phase5AttributionState =
  | 'CONFIRMED_MATCH'
  | 'CONFIRMED_NON_MATCH'
  | 'PROBABLE'
  | 'POSSIBLE'
  | 'UNRESOLVED'
  | 'NEEDS_MORE_EVIDENCE'
export type Phase5ConfidenceBand =
  | 'VERY_LOW'
  | 'LOW'
  | 'MEDIUM'
  | 'HIGH'
  | 'VERY_HIGH'
export type Phase5PositiveSignal =
  | 'EXACT_EMAIL'
  | 'RECOVERY_RELATIONSHIP'
  | 'EXACT_LEGAL_NAME'
  | 'SAME_UNCOMMON_USERNAME'
  | 'SAME_PHOTOGRAPH'
  | 'SAME_ORGANISATION'
  | 'SAME_EDUCATION'
  | 'SAME_LOCATION'
  | 'SAME_PROJECT'
  | 'SAME_LINKED_DOMAIN'
  | 'SAME_WRITING_PROFILE_LINKS'
  | 'CHRONOLOGICAL_COMPATIBILITY'
  | 'USER_CONFIRMATION'
  | 'IMMUTABLE_PLATFORM_ID_CONTINUITY'
export type Phase5NegativeSignal =
  | 'CONFLICTING_AGE'
  | 'CONFLICTING_PHOTOGRAPH'
  | 'INCOMPATIBLE_GEOGRAPHY'
  | 'ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP'
  | 'DIFFERENT_IMMUTABLE_ACCOUNT_ID'
  | 'CONTRADICTORY_BIOGRAPHY'
  | 'EXPLICIT_USER_EXCLUSION'
  | 'USERNAME_RECYCLING_EVIDENCE'
export type Phase5ArtifactKind =
  | 'SCREENSHOT'
  | 'HTML'
  | 'PDF'
  | 'RAW_JSON'
  | 'URL_REFERENCE'
export type Phase5CaptureMethod =
  | 'BROWSER_CAPTURE'
  | 'HTTP_FETCH'
  | 'PROVIDER_API'
  | 'MANUAL_LOCAL_IMPORT'
export type Phase5IntegrityStatus = 'VERIFIED' | 'NOT_VERIFIED' | 'FAILED'
export type Phase5ManualArtifactKind = Exclude<
  Phase5ArtifactKind,
  'URL_REFERENCE'
>

export interface Phase5FindingSummary {
  readonly findingId: string
  readonly title: string
  readonly summary: string
  readonly outcome: Phase5CheckOutcome
  readonly severity: Phase5Severity
  readonly visibility: Phase5Visibility
  readonly attributionState: Phase5AttributionState | null
  readonly confidenceBand: Phase5ConfidenceBand
  readonly score: number
  readonly humanReviewRequired: true
  readonly providerLabel: string
  readonly artifactCount: number
  readonly updatedAtUs: number
}

export interface Phase5FindingList {
  readonly profileId: string
  readonly findings: ReadonlyArray<Phase5FindingSummary>
  readonly hasMore: boolean
}

export interface Phase5PositiveContribution {
  readonly signal: Phase5PositiveSignal
  readonly weight: number
  readonly evidenceArtifactIds: ReadonlyArray<string>
}

export interface Phase5NegativeContribution {
  readonly signal: Phase5NegativeSignal
  readonly penalty: number
  readonly evidenceArtifactIds: ReadonlyArray<string>
}

export interface Phase5MissingEvidence {
  readonly signal: Phase5PositiveSignal
  readonly potentialWeight: number
}

export interface Phase5AttributionAssessment {
  readonly assessmentId: string
  readonly caseId: string
  readonly weightProfileVersion: string
  readonly score: number
  readonly confidenceBand: Phase5ConfidenceBand
  readonly contributingSignals: ReadonlyArray<Phase5PositiveContribution>
  readonly contradictions: ReadonlyArray<Phase5NegativeContribution>
  readonly missingEvidence: ReadonlyArray<Phase5MissingEvidence>
  readonly recommendedNextEvidence: ReadonlyArray<Phase5PositiveSignal>
  readonly humanReviewRequired: true
}

export interface Phase5EvidenceViewport {
  readonly width: number
  readonly height: number
  readonly deviceScaleMicros: number
}

export interface Phase5EvidenceArtifact {
  readonly artifactId: string
  readonly kind: Phase5ArtifactKind
  readonly contentSha256: string
  readonly capturedAtUs: number
  readonly sourceUrl: string | null
  readonly httpStatus: number | null
  readonly redirectCount: number
  readonly providerId: string
  readonly runId: string
  readonly viewport: Phase5EvidenceViewport | null
  readonly captureMethod: Phase5CaptureMethod
  readonly encryptedAtRest: true
  readonly integrityStatus: Phase5IntegrityStatus
  readonly derivativeCount: number
}

export interface Phase5HumanDecision {
  readonly decisionId: string
  readonly assessmentId: string
  readonly state: Phase5AttributionState
  readonly actorLabel: 'Local user'
  readonly decidedAtUs: number
  readonly weightProfileVersion: string
  readonly supersedesDecisionId: string | null
  readonly revision: number
}

export interface Phase5FindingDetail {
  readonly profileId: string
  readonly finding: Phase5FindingSummary
  readonly assessment: Phase5AttributionAssessment
  readonly artifacts: ReadonlyArray<Phase5EvidenceArtifact>
  readonly humanDecision: Phase5HumanDecision | null
}

export interface Phase5ManualFindingRequest {
  readonly profileId: string
  readonly title: string
  readonly summary: string
  readonly outcome: Phase5CheckOutcome
  readonly severity: Phase5Severity
  readonly visibility: Phase5Visibility
  readonly providerId: string
  readonly providerLabel: string
}

export interface Phase5EvidenceMetadata {
  readonly key: string
  readonly value: string
}

export interface Phase5ManualEvidenceImportRequest {
  readonly profileId: string
  readonly findingId: string
  readonly kind: Phase5ManualArtifactKind
  readonly contentBase64: string
  readonly viewport: Phase5EvidenceViewport | null
  readonly metadata: ReadonlyArray<Phase5EvidenceMetadata>
}

export interface Phase5ManualEvidenceImportResult {
  readonly profileId: string
  readonly findingId: string
  readonly artifactId: string
  readonly kind: Phase5ManualArtifactKind
  readonly contentSha256: string
  readonly capturedAtUs: number
  readonly captureMethod: 'MANUAL_LOCAL_IMPORT'
  readonly encryptedAtRest: true
  readonly localOnly: true
  readonly deduplicated: boolean
}

export interface Phase5RedactedDerivativeRequest {
  readonly profileId: string
  readonly originalArtifactId: string
  readonly redactedContentBase64: string
  readonly alreadyRedacted: true
  readonly redactionPolicyVersion: string
  readonly redactionSummaryCode: string
}

export interface Phase5RedactedDerivativeResult {
  readonly profileId: string
  readonly originalArtifactId: string
  readonly derivativeId: string
  readonly contentSha256: string
  readonly createdAtUs: number
  readonly redactionPolicyVersion: string
  readonly redactionSummaryCode: string
  readonly redactionMode: 'CALLER_SUPPLIED'
  readonly encryptedAtRest: true
  readonly localOnly: true
  readonly deduplicated: boolean
}

export interface Phase5AttributionDecisionRequest {
  readonly profileId: string
  readonly findingId: string
  readonly assessmentId: string
  readonly state: Phase5AttributionState
  readonly expectedPreviousDecisionId: string | null
  readonly expectedPreviousRevision: number
}

export interface Phase5AttributionDecisionResult {
  readonly profileId: string
  readonly findingId: string
  readonly assessmentId: string
  readonly decisionId: string
  readonly state: Phase5AttributionState
  readonly actorLabel: 'Local user'
  readonly decidedAtUs: number
  readonly weightProfileVersion: string
  readonly supersedesDecisionId: string | null
  readonly revision: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: ReadonlyArray<string>,
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

function isIntegerBetween(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return (
    Number.isSafeInteger(value) &&
    Number(value) >= minimum &&
    Number(value) <= maximum
  )
}

function isCanonicalUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    UUID_PATTERN.test(value) &&
    value === value.toLocaleLowerCase('en-US')
  )
}

function isCanonicalBase64(value: unknown): value is string {
  if (
    typeof value !== 'string' ||
    value.length < 4 ||
    value.length > MAX_BASE64_CHARACTERS ||
    value.length % 4 !== 0 ||
    !BASE64_PATTERN.test(value)
  ) {
    return false
  }
  const padding = value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0
  const decodedBytes = (value.length / 4) * 3 - padding
  if (decodedBytes < 1 || decodedBytes > MAX_ARTIFACT_BYTES) return false

  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
  if (padding === 2) {
    return alphabet.indexOf(value.at(-3) ?? '') % 16 === 0
  }
  if (padding === 1) {
    return alphabet.indexOf(value.at(-2) ?? '') % 4 === 0
  }
  return true
}

function isPolicyVersion(value: unknown): value is string {
  return typeof value === 'string' && POLICY_VERSION_PATTERN.test(value)
}

function isMetadata(value: unknown): value is ReadonlyArray<Phase5EvidenceMetadata> {
  if (!Array.isArray(value) || value.length > 32) return false
  let totalCharacters = 0
  const keys = new Set<string>()
  for (const item of value) {
    if (
      !isRecord(item) ||
      !hasExactKeys(item, ['key', 'value']) ||
      typeof item.key !== 'string' ||
      !METADATA_KEY_PATTERN.test(item.key) ||
      typeof item.value !== 'string' ||
      item.value.length < 1 ||
      item.value.length > 256 ||
      item.value !== item.value.trim() ||
      /\p{C}/u.test(item.value) ||
      keys.has(item.key)
    ) {
      return false
    }
    keys.add(item.key)
    totalCharacters += item.key.length + item.value.length
  }
  return totalCharacters <= 4_096
}

function isSafeSourceUrl(value: unknown): value is string | null {
  if (value === null) return true
  if (!isBoundedString(value, 8, 2_048)) return false
  try {
    const parsed = new URL(value)
    return (
      ['http:', 'https:'].includes(parsed.protocol) &&
      parsed.username === '' &&
      parsed.password === '' &&
      parsed.search === '' &&
      parsed.hash === '' &&
      parsed.hostname.length > 0
    )
  } catch {
    return false
  }
}

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !isCanonicalUuid(value.requestId)
  ) {
    throw new Error('Phase 5 command response is invalid')
  }
  return value.data
}

function isFindingSummary(value: unknown): value is Phase5FindingSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'findingId',
      'title',
      'summary',
      'outcome',
      'severity',
      'visibility',
      'attributionState',
      'confidenceBand',
      'score',
      'humanReviewRequired',
      'providerLabel',
      'artifactCount',
      'updatedAtUs',
    ]) &&
    isCanonicalUuid(value.findingId) &&
    isBoundedString(value.title, 1, 256) &&
    isBoundedString(value.summary, 1, 2_048) &&
    CHECK_OUTCOMES.has(value.outcome as never) &&
    SEVERITIES.has(value.severity as never) &&
    VISIBILITIES.has(value.visibility as never) &&
    (value.attributionState === null ||
      ATTRIBUTION_STATES.has(value.attributionState as never)) &&
    CONFIDENCE_BANDS.has(value.confidenceBand as never) &&
    isIntegerBetween(value.score, -1_000, 1_000) &&
    value.humanReviewRequired === true &&
    isBoundedString(value.providerLabel, 1, 128) &&
    isIntegerBetween(value.artifactCount, 0, 1_000) &&
    isIntegerBetween(value.updatedAtUs, 1, Number.MAX_SAFE_INTEGER)
  )
}

function parseFindingList(value: unknown): Phase5FindingList {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['profileId', 'findings', 'hasMore']) ||
    !isCanonicalUuid(data.profileId) ||
    !Array.isArray(data.findings) ||
    data.findings.length > 100 ||
    !data.findings.every(isFindingSummary) ||
    new Set(data.findings.map((finding) => finding.findingId)).size !==
      data.findings.length ||
    typeof data.hasMore !== 'boolean'
  ) {
    throw new Error('Phase 5 finding list is invalid')
  }
  return data as unknown as Phase5FindingList
}

function isEvidenceIds(value: unknown): value is ReadonlyArray<string> {
  return (
    Array.isArray(value) &&
    value.length >= 1 &&
    value.length <= 16 &&
    value.every(isCanonicalUuid) &&
    new Set(value).size === value.length
  )
}

function isPositiveContribution(
  value: unknown,
): value is Phase5PositiveContribution {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['signal', 'weight', 'evidenceArtifactIds']) &&
    POSITIVE_SIGNALS.has(value.signal as never) &&
    isIntegerBetween(value.weight, 0, 1_000) &&
    isEvidenceIds(value.evidenceArtifactIds)
  )
}

function isNegativeContribution(
  value: unknown,
): value is Phase5NegativeContribution {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['signal', 'penalty', 'evidenceArtifactIds']) &&
    NEGATIVE_SIGNALS.has(value.signal as never) &&
    isIntegerBetween(value.penalty, 0, 1_000) &&
    isEvidenceIds(value.evidenceArtifactIds)
  )
}

function isMissingEvidence(value: unknown): value is Phase5MissingEvidence {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['signal', 'potentialWeight']) &&
    POSITIVE_SIGNALS.has(value.signal as never) &&
    isIntegerBetween(value.potentialWeight, 0, 1_000)
  )
}

function isAssessment(value: unknown): value is Phase5AttributionAssessment {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'assessmentId',
      'caseId',
      'weightProfileVersion',
      'score',
      'confidenceBand',
      'contributingSignals',
      'contradictions',
      'missingEvidence',
      'recommendedNextEvidence',
      'humanReviewRequired',
    ]) ||
    !isCanonicalUuid(value.assessmentId) ||
    !isCanonicalUuid(value.caseId) ||
    !isPolicyVersion(value.weightProfileVersion) ||
    !TOKEN_PATTERN.test(String(value.confidenceBand)) ||
    !CONFIDENCE_BANDS.has(value.confidenceBand as never) ||
    !isIntegerBetween(value.score, -1_000, 1_000) ||
    !Array.isArray(value.contributingSignals) ||
    value.contributingSignals.length > 14 ||
    !value.contributingSignals.every(isPositiveContribution) ||
    !Array.isArray(value.contradictions) ||
    value.contradictions.length > 8 ||
    !value.contradictions.every(isNegativeContribution) ||
    !Array.isArray(value.missingEvidence) ||
    value.missingEvidence.length > 14 ||
    !value.missingEvidence.every(isMissingEvidence) ||
    !Array.isArray(value.recommendedNextEvidence) ||
    value.recommendedNextEvidence.length > 5 ||
    !value.recommendedNextEvidence.every((signal) =>
      POSITIVE_SIGNALS.has(signal as never),
    ) ||
    value.humanReviewRequired !== true
  ) {
    return false
  }
  const positive = value.contributingSignals.map((item) => item.signal)
  const negative = value.contradictions.map((item) => item.signal)
  const missing = value.missingEvidence.map((item) => item.signal)
  return (
    new Set(positive).size === positive.length &&
    new Set(negative).size === negative.length &&
    new Set(missing).size === missing.length &&
    positive.every((signal) => !missing.includes(signal)) &&
    new Set(value.recommendedNextEvidence).size ===
      value.recommendedNextEvidence.length &&
    value.recommendedNextEvidence.every((signal) => missing.includes(signal))
  )
}

function isViewport(value: unknown): value is Phase5EvidenceViewport {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['width', 'height', 'deviceScaleMicros']) &&
    isIntegerBetween(value.width, 1, 16_384) &&
    isIntegerBetween(value.height, 1, 16_384) &&
    isIntegerBetween(value.deviceScaleMicros, 100_000, 8_000_000)
  )
}

function isArtifact(value: unknown): value is Phase5EvidenceArtifact {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'artifactId',
      'kind',
      'contentSha256',
      'capturedAtUs',
      'sourceUrl',
      'httpStatus',
      'redirectCount',
      'providerId',
      'runId',
      'viewport',
      'captureMethod',
      'encryptedAtRest',
      'integrityStatus',
      'derivativeCount',
    ]) &&
    isCanonicalUuid(value.artifactId) &&
    ARTIFACT_KINDS.has(value.kind as never) &&
    typeof value.contentSha256 === 'string' &&
    SHA256_PATTERN.test(value.contentSha256) &&
    isIntegerBetween(value.capturedAtUs, 1, Number.MAX_SAFE_INTEGER) &&
    isSafeSourceUrl(value.sourceUrl) &&
    (value.httpStatus === null ||
      isIntegerBetween(value.httpStatus, 100, 599)) &&
    (value.httpStatus === null || value.sourceUrl !== null) &&
    isIntegerBetween(value.redirectCount, 0, 10) &&
    (value.redirectCount === 0 || value.sourceUrl !== null) &&
    typeof value.providerId === 'string' &&
    OPAQUE_ID_PATTERN.test(value.providerId) &&
    isCanonicalUuid(value.runId) &&
    (value.viewport === null || isViewport(value.viewport)) &&
    (value.kind !== 'SCREENSHOT' || value.viewport !== null) &&
    (value.kind !== 'URL_REFERENCE' ||
      (value.sourceUrl !== null && value.viewport === null)) &&
    CAPTURE_METHODS.has(value.captureMethod as never) &&
    (value.captureMethod !== 'MANUAL_LOCAL_IMPORT' ||
      (value.sourceUrl === null &&
        value.httpStatus === null &&
        value.redirectCount === 0)) &&
    value.encryptedAtRest === true &&
    INTEGRITY_STATUSES.has(value.integrityStatus as never) &&
    isIntegerBetween(value.derivativeCount, 0, 2_000)
  )
}

function isHumanDecision(value: unknown): value is Phase5HumanDecision {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'decisionId',
      'assessmentId',
      'state',
      'actorLabel',
      'decidedAtUs',
      'weightProfileVersion',
      'supersedesDecisionId',
      'revision',
    ]) &&
    isCanonicalUuid(value.decisionId) &&
    isCanonicalUuid(value.assessmentId) &&
    ATTRIBUTION_STATES.has(value.state as never) &&
    value.actorLabel === 'Local user' &&
    isIntegerBetween(value.decidedAtUs, 1, Number.MAX_SAFE_INTEGER) &&
    isPolicyVersion(value.weightProfileVersion) &&
    (value.supersedesDecisionId === null ||
      isCanonicalUuid(value.supersedesDecisionId)) &&
    value.decisionId !== value.supersedesDecisionId &&
    isIntegerBetween(value.revision, 1, 2_147_483_647) &&
    ((value.supersedesDecisionId === null) === (value.revision === 1))
  )
}

function parseFindingDetail(value: unknown): Phase5FindingDetail {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'profileId',
      'finding',
      'assessment',
      'artifacts',
      'humanDecision',
    ]) ||
    !isCanonicalUuid(data.profileId) ||
    !isFindingSummary(data.finding) ||
    !isAssessment(data.assessment) ||
    !Array.isArray(data.artifacts) ||
    data.artifacts.length > 64 ||
    !data.artifacts.every(isArtifact) ||
    new Set(data.artifacts.map((artifact) => artifact.artifactId)).size !==
      data.artifacts.length ||
    (data.humanDecision !== null && !isHumanDecision(data.humanDecision))
  ) {
    throw new Error('Phase 5 finding detail is invalid')
  }
  const artifactIds = new Set(
    data.artifacts.map((artifact) => artifact.artifactId),
  )
  const referencedIds = [
    ...data.assessment.contributingSignals.flatMap(
      (item) => item.evidenceArtifactIds,
    ),
    ...data.assessment.contradictions.flatMap(
      (item) => item.evidenceArtifactIds,
    ),
  ]
  if (
    data.finding.findingId !== data.assessment.caseId ||
    data.finding.score !== data.assessment.score ||
    data.finding.confidenceBand !== data.assessment.confidenceBand ||
    data.finding.artifactCount !== data.artifacts.length ||
    referencedIds.some((artifactId) => !artifactIds.has(artifactId)) ||
    ((data.humanDecision === null) !==
      (data.finding.attributionState === null) ||
      (data.humanDecision !== null &&
        (data.finding.attributionState !== data.humanDecision.state ||
          data.humanDecision.assessmentId !== data.assessment.assessmentId ||
          data.humanDecision.weightProfileVersion !==
            data.assessment.weightProfileVersion)))
  ) {
    throw new Error('Phase 5 finding detail bindings are invalid')
  }
  return data as unknown as Phase5FindingDetail
}

function isManualImportResult(
  value: unknown,
): value is Phase5ManualEvidenceImportResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'profileId',
      'findingId',
      'artifactId',
      'kind',
      'contentSha256',
      'capturedAtUs',
      'captureMethod',
      'encryptedAtRest',
      'localOnly',
      'deduplicated',
    ]) &&
    isCanonicalUuid(value.profileId) &&
    isCanonicalUuid(value.findingId) &&
    isCanonicalUuid(value.artifactId) &&
    MANUAL_ARTIFACT_KINDS.has(value.kind as never) &&
    typeof value.contentSha256 === 'string' &&
    SHA256_PATTERN.test(value.contentSha256) &&
    isIntegerBetween(value.capturedAtUs, 1, Number.MAX_SAFE_INTEGER) &&
    value.captureMethod === 'MANUAL_LOCAL_IMPORT' &&
    value.encryptedAtRest === true &&
    value.localOnly === true &&
    typeof value.deduplicated === 'boolean'
  )
}

function parseManualImportResult(
  value: unknown,
): Phase5ManualEvidenceImportResult {
  const data = commandData(value)
  if (!isManualImportResult(data)) {
    throw new Error('Phase 5 manual evidence response is invalid')
  }
  return data
}

function isRedactedDerivativeResult(
  value: unknown,
): value is Phase5RedactedDerivativeResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'profileId',
      'originalArtifactId',
      'derivativeId',
      'contentSha256',
      'createdAtUs',
      'redactionPolicyVersion',
      'redactionSummaryCode',
      'redactionMode',
      'encryptedAtRest',
      'localOnly',
      'deduplicated',
    ]) &&
    isCanonicalUuid(value.profileId) &&
    isCanonicalUuid(value.originalArtifactId) &&
    isCanonicalUuid(value.derivativeId) &&
    value.derivativeId !== value.originalArtifactId &&
    typeof value.contentSha256 === 'string' &&
    SHA256_PATTERN.test(value.contentSha256) &&
    isIntegerBetween(value.createdAtUs, 1, Number.MAX_SAFE_INTEGER) &&
    isPolicyVersion(value.redactionPolicyVersion) &&
    typeof value.redactionSummaryCode === 'string' &&
    SUMMARY_CODE_PATTERN.test(value.redactionSummaryCode) &&
    value.redactionMode === 'CALLER_SUPPLIED' &&
    value.encryptedAtRest === true &&
    value.localOnly === true &&
    typeof value.deduplicated === 'boolean'
  )
}

function parseRedactedDerivativeResult(
  value: unknown,
): Phase5RedactedDerivativeResult {
  const data = commandData(value)
  if (!isRedactedDerivativeResult(data)) {
    throw new Error('Phase 5 redacted derivative response is invalid')
  }
  return data
}

function isAttributionDecisionResult(
  value: unknown,
): value is Phase5AttributionDecisionResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'profileId',
      'findingId',
      'assessmentId',
      'decisionId',
      'state',
      'actorLabel',
      'decidedAtUs',
      'weightProfileVersion',
      'supersedesDecisionId',
      'revision',
    ]) &&
    isCanonicalUuid(value.profileId) &&
    isCanonicalUuid(value.findingId) &&
    isCanonicalUuid(value.assessmentId) &&
    isCanonicalUuid(value.decisionId) &&
    ATTRIBUTION_STATES.has(value.state as never) &&
    value.actorLabel === 'Local user' &&
    isIntegerBetween(value.decidedAtUs, 1, Number.MAX_SAFE_INTEGER) &&
    isPolicyVersion(value.weightProfileVersion) &&
    (value.supersedesDecisionId === null ||
      isCanonicalUuid(value.supersedesDecisionId)) &&
    value.decisionId !== value.supersedesDecisionId &&
    isIntegerBetween(value.revision, 1, 2_147_483_647) &&
    ((value.supersedesDecisionId === null) === (value.revision === 1))
  )
}

function parseAttributionDecisionResult(
  value: unknown,
): Phase5AttributionDecisionResult {
  const data = commandData(value)
  if (!isAttributionDecisionResult(data)) {
    throw new Error('Phase 5 attribution decision response is invalid')
  }
  return data
}

function validateManualImportRequest(
  request: Phase5ManualEvidenceImportRequest,
): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'findingId',
      'kind',
      'contentBase64',
      'viewport',
      'metadata',
    ]) ||
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuid(request.findingId) ||
    !MANUAL_ARTIFACT_KINDS.has(request.kind as never) ||
    !isCanonicalBase64(request.contentBase64) ||
    (request.viewport !== null && !isViewport(request.viewport)) ||
    (request.kind === 'SCREENSHOT') !== (request.viewport !== null) ||
    !isMetadata(request.metadata)
  ) {
    throw new Error('Phase 5 manual evidence request is invalid')
  }
}

function validateRedactedDerivativeRequest(
  request: Phase5RedactedDerivativeRequest,
): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'originalArtifactId',
      'redactedContentBase64',
      'alreadyRedacted',
      'redactionPolicyVersion',
      'redactionSummaryCode',
    ]) ||
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuid(request.originalArtifactId) ||
    !isCanonicalBase64(request.redactedContentBase64) ||
    request.alreadyRedacted !== true ||
    !isPolicyVersion(request.redactionPolicyVersion) ||
    !SUMMARY_CODE_PATTERN.test(request.redactionSummaryCode)
  ) {
    throw new Error('Phase 5 redacted derivative request is invalid')
  }
}

function validateAttributionDecisionRequest(
  request: Phase5AttributionDecisionRequest,
): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'findingId',
      'assessmentId',
      'state',
      'expectedPreviousDecisionId',
      'expectedPreviousRevision',
    ]) ||
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuid(request.findingId) ||
    !isCanonicalUuid(request.assessmentId) ||
    !ATTRIBUTION_STATES.has(request.state as never) ||
    (request.expectedPreviousDecisionId !== null &&
      !isCanonicalUuid(request.expectedPreviousDecisionId)) ||
    !isIntegerBetween(request.expectedPreviousRevision, 0, 2_147_483_647) ||
    ((request.expectedPreviousDecisionId === null) !==
      (request.expectedPreviousRevision === 0))
  ) {
    throw new Error('Phase 5 attribution decision request is invalid')
  }
}

function validateManualFindingRequest(
  request: Phase5ManualFindingRequest,
): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'title',
      'summary',
      'outcome',
      'severity',
      'visibility',
      'providerId',
      'providerLabel',
    ]) ||
    !isCanonicalUuid(request.profileId) ||
    !isBoundedString(request.title, 1, 256) ||
    !isBoundedString(request.summary, 1, 2_048) ||
    !CHECK_OUTCOMES.has(request.outcome as never) ||
    !SEVERITIES.has(request.severity as never) ||
    !VISIBILITIES.has(request.visibility as never) ||
    !OPAQUE_ID_PATTERN.test(request.providerId) ||
    !isBoundedString(request.providerLabel, 1, 128)
  ) {
    throw new Error('Phase 5 manual finding request is invalid')
  }
}

async function invokePhase5(command: string, request: object): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<unknown>(command, { request })
}

export async function loadPhase5Findings(request: {
  readonly profileId: string
  readonly limit?: number
}): Promise<Phase5FindingList> {
  if (
    !isCanonicalUuid(request.profileId) ||
    !isIntegerBetween(request.limit ?? 100, 1, 100)
  ) {
    throw new Error('Phase 5 finding request is invalid')
  }
  const result = parseFindingList(
    await invokePhase5('core_list_phase5_findings', {
      profileId: request.profileId,
      limit: request.limit ?? 100,
    }),
  )
  if (result.profileId !== request.profileId) {
    throw new Error('Phase 5 finding profile binding is invalid')
  }
  return result
}

export async function loadPhase5Finding(request: {
  readonly profileId: string
  readonly findingId: string
}): Promise<Phase5FindingDetail> {
  if (
    !isCanonicalUuid(request.profileId) ||
    !isCanonicalUuid(request.findingId)
  ) {
    throw new Error('Phase 5 finding detail request is invalid')
  }
  const result = parseFindingDetail(
    await invokePhase5('core_get_phase5_finding', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.finding.findingId !== request.findingId
  ) {
    throw new Error('Phase 5 finding detail binding is invalid')
  }
  return result
}

export async function createPhase5ManualFinding(
  request: Phase5ManualFindingRequest,
): Promise<Phase5FindingDetail> {
  validateManualFindingRequest(request)
  const result = parseFindingDetail(
    await invokePhase5('core_create_phase5_manual_finding', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.finding.title !== request.title ||
    result.finding.summary !== request.summary ||
    result.finding.outcome !== request.outcome ||
    result.finding.severity !== request.severity ||
    result.finding.visibility !== request.visibility ||
    result.finding.providerLabel !== request.providerLabel ||
    result.finding.artifactCount !== 0 ||
    result.humanDecision !== null
  ) {
    throw new Error('Phase 5 manual finding response binding is invalid')
  }
  return result
}

export async function importPhase5Evidence(
  request: Phase5ManualEvidenceImportRequest,
): Promise<Phase5ManualEvidenceImportResult> {
  validateManualImportRequest(request)
  const result = parseManualImportResult(
    await invokePhase5('core_import_phase5_evidence', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.findingId !== request.findingId ||
    result.kind !== request.kind
  ) {
    throw new Error('Phase 5 manual evidence response binding is invalid')
  }
  return result
}

export async function createPhase5RedactedDerivative(
  request: Phase5RedactedDerivativeRequest,
): Promise<Phase5RedactedDerivativeResult> {
  validateRedactedDerivativeRequest(request)
  const result = parseRedactedDerivativeResult(
    await invokePhase5('core_create_phase5_redacted_derivative', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.originalArtifactId !== request.originalArtifactId ||
    result.redactionPolicyVersion !== request.redactionPolicyVersion ||
    result.redactionSummaryCode !== request.redactionSummaryCode
  ) {
    throw new Error('Phase 5 redacted derivative response binding is invalid')
  }
  return result
}

export async function appendPhase5AttributionDecision(
  request: Phase5AttributionDecisionRequest,
): Promise<Phase5AttributionDecisionResult> {
  validateAttributionDecisionRequest(request)
  const result = parseAttributionDecisionResult(
    await invokePhase5('core_append_phase5_attribution_decision', request),
  )
  if (
    result.profileId !== request.profileId ||
    result.findingId !== request.findingId ||
    result.assessmentId !== request.assessmentId ||
    result.state !== request.state ||
    result.supersedesDecisionId !== request.expectedPreviousDecisionId ||
    result.revision !== request.expectedPreviousRevision + 1
  ) {
    throw new Error('Phase 5 attribution decision response binding is invalid')
  }
  return result
}

export const phase5BoundaryParsers = {
  list: parseFindingList,
  detail: parseFindingDetail,
  manualImport: parseManualImportResult,
  redactedDerivative: parseRedactedDerivativeResult,
  attributionDecision: parseAttributionDecisionResult,
}

export const phase5EvidenceLimits = {
  maximumBytes: MAX_ARTIFACT_BYTES,
  maximumBase64Characters: MAX_BASE64_CHARACTERS,
} as const
