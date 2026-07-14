const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const REPORT_SCHEMA = 'ariadne.local-report'
const MAX_ARTIFACT_BYTES = 1_000_000

export type LocalReportFormat = 'JSON' | 'MARKDOWN'
export type LocalReportMode = 'REDACTED' | 'FULL_EXPLICIT'

export interface LocalReportRequest {
  readonly profileId: string
  readonly baselineRunId: string
  readonly currentRunId: string
  readonly artifactFormat: LocalReportFormat
  readonly mode: LocalReportMode
  readonly fullExportApprovalId: string | null
}

export interface LocalReportArtifactDescriptor {
  readonly filename: 'report.json' | 'report.md'
  readonly mediaType: 'application/json' | 'text/markdown; charset=utf-8'
  readonly byteCount: number
  readonly sha256: string
}

export interface LocalReportManifest {
  readonly schema: typeof REPORT_SCHEMA
  readonly version: 1
  readonly mode: LocalReportMode
  readonly generatedAtUs: number
  readonly fullExportApprovalId: string | null
  readonly artifacts: ReadonlyArray<LocalReportArtifactDescriptor>
}

export interface LocalReportArtifact extends LocalReportArtifactDescriptor {
  readonly schema: typeof REPORT_SCHEMA
  readonly version: 1
  readonly mode: LocalReportMode
  readonly content: string
}

export interface LocalReportResult {
  readonly profileId: string
  readonly baselineRunId: string
  readonly currentRunId: string
  readonly localOnly: true
  readonly artifact: LocalReportArtifact
  readonly manifest: LocalReportManifest
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

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

function isSafeInteger(value: unknown, minimum: number, maximum: number) {
  return (
    typeof value === 'number' &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  )
}

function isMode(value: unknown): value is LocalReportMode {
  return value === 'REDACTED' || value === 'FULL_EXPLICIT'
}

function isDescriptor(
  value: unknown,
): value is LocalReportArtifactDescriptor {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['filename', 'mediaType', 'byteCount', 'sha256']) ||
    !isSafeInteger(value.byteCount, 1, MAX_ARTIFACT_BYTES) ||
    typeof value.sha256 !== 'string' ||
    !SHA256_PATTERN.test(value.sha256)
  ) {
    return false
  }
  return (
    (value.filename === 'report.json' &&
      value.mediaType === 'application/json') ||
    (value.filename === 'report.md' &&
      value.mediaType === 'text/markdown; charset=utf-8')
  )
}

function parseReportResult(value: unknown): LocalReportResult {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !isUuid(value.requestId) ||
    !isRecord(value.data)
  ) {
    throw new Error('Local report command response is invalid')
  }
  const data = value.data
  if (
    !hasExactKeys(data, [
      'profileId',
      'baselineRunId',
      'currentRunId',
      'localOnly',
      'artifact',
      'manifest',
    ]) ||
    !isUuid(data.profileId) ||
    !isUuid(data.baselineRunId) ||
    !isUuid(data.currentRunId) ||
    data.baselineRunId === data.currentRunId ||
    data.localOnly !== true ||
    !isRecord(data.artifact) ||
    !hasExactKeys(data.artifact, [
      'filename',
      'mediaType',
      'byteCount',
      'sha256',
      'schema',
      'version',
      'mode',
      'content',
    ]) ||
    !isDescriptor({
      filename: data.artifact.filename,
      mediaType: data.artifact.mediaType,
      byteCount: data.artifact.byteCount,
      sha256: data.artifact.sha256,
    }) ||
    data.artifact.schema !== REPORT_SCHEMA ||
    data.artifact.version !== 1 ||
    !isMode(data.artifact.mode) ||
    typeof data.artifact.content !== 'string' ||
    data.artifact.content.length < 1 ||
    !isRecord(data.manifest) ||
    !hasExactKeys(data.manifest, [
      'schema',
      'version',
      'mode',
      'generatedAtUs',
      'fullExportApprovalId',
      'artifacts',
    ]) ||
    data.manifest.schema !== REPORT_SCHEMA ||
    data.manifest.version !== 1 ||
    !isMode(data.manifest.mode) ||
    !isSafeInteger(data.manifest.generatedAtUs, 1, Number.MAX_SAFE_INTEGER) ||
    (data.manifest.fullExportApprovalId !== null &&
      !isUuid(data.manifest.fullExportApprovalId)) ||
    !Array.isArray(data.manifest.artifacts) ||
    data.manifest.artifacts.length !== 2 ||
    !data.manifest.artifacts.every(isDescriptor)
  ) {
    throw new Error('Local report result is invalid')
  }

  const artifact = data.artifact as unknown as LocalReportArtifact
  const manifest = data.manifest as unknown as LocalReportManifest
  const filenames = manifest.artifacts.map((item) => item.filename)
  const selected = manifest.artifacts.find(
    (item) => item.filename === artifact.filename,
  )
  if (
    new Set(filenames).size !== 2 ||
    !filenames.includes('report.json') ||
    !filenames.includes('report.md') ||
    artifact.mode !== manifest.mode ||
    selected?.mediaType !== artifact.mediaType ||
    selected.byteCount !== artifact.byteCount ||
    selected.sha256 !== artifact.sha256 ||
    (artifact.mode === 'FULL_EXPLICIT') !==
      (manifest.fullExportApprovalId !== null)
  ) {
    throw new Error('Local report result bindings are invalid')
  }
  return data as unknown as LocalReportResult
}

function validateRequest(request: LocalReportRequest): void {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      'profileId',
      'baselineRunId',
      'currentRunId',
      'artifactFormat',
      'mode',
      'fullExportApprovalId',
    ]) ||
    !isUuid(request.profileId) ||
    !isUuid(request.baselineRunId) ||
    !isUuid(request.currentRunId) ||
    request.baselineRunId === request.currentRunId ||
    (request.artifactFormat !== 'JSON' &&
      request.artifactFormat !== 'MARKDOWN') ||
    !isMode(request.mode) ||
    (request.fullExportApprovalId !== null &&
      !isUuid(request.fullExportApprovalId)) ||
    (request.mode === 'FULL_EXPLICIT') !==
      (request.fullExportApprovalId !== null)
  ) {
    throw new Error('Local report request is invalid')
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

export async function generateLocalReport(
  request: LocalReportRequest,
): Promise<LocalReportResult> {
  validateRequest(request)
  const { invoke } = await import('@tauri-apps/api/core')
  const result = parseReportResult(
    await invoke<unknown>('core_generate_local_report', { request }),
  )
  const expectedFilename =
    request.artifactFormat === 'JSON' ? 'report.json' : 'report.md'
  const byteCount = new TextEncoder().encode(result.artifact.content).byteLength
  if (
    result.profileId !== request.profileId ||
    result.baselineRunId !== request.baselineRunId ||
    result.currentRunId !== request.currentRunId ||
    result.artifact.filename !== expectedFilename ||
    result.artifact.mode !== request.mode ||
    result.manifest.fullExportApprovalId !== request.fullExportApprovalId ||
    result.artifact.byteCount !== byteCount ||
    result.artifact.sha256 !== (await sha256(result.artifact.content))
  ) {
    throw new Error('Local report response binding is invalid')
  }
  return result
}

export const reportingBoundaryParsers = {
  result: parseReportResult,
}
