/**
 * Runtime validation for local-model settings and discovery responses.
 *
 * Loopback checks here improve UI feedback; the Rust and Python boundaries must
 * independently enforce them because webview validation grants no authority.
 */
import type {
  LocalAIConnectionResult,
  LocalAIEndpointRequest,
  LocalAIModelDiscoveryResult,
  LocalAIProvider,
  LocalAISettings,
  LocalAISettingsUpdateRequest,
} from '../../../../packages/contracts/src/generated/api'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const PROVIDERS = new Set(['OLLAMA', 'OPENAI_COMPATIBLE'])
const CONNECTION_STATUSES = new Set([
  'AVAILABLE',
  'MODEL_UNAVAILABLE',
  'TIMEOUT',
  'UNAVAILABLE',
  'INVALID_RESPONSE',
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

function commandData(value: unknown): unknown {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['requestId', 'data']) ||
    !UUID_PATTERN.test(String(value.requestId))
  ) {
    throw new Error('Local AI command response is invalid')
  }
  return value.data
}

function isProvider(value: unknown): value is LocalAIProvider {
  return PROVIDERS.has(String(value))
}

function isModelId(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length >= 1 &&
    value.length <= 256 &&
    value.trim() === value &&
    !Array.from(value).some((character) => {
      const point = character.codePointAt(0) ?? 0
      return point < 32 || point === 127
    })
  )
}

export function isLoopbackLocalAIEndpoint(value: string): boolean {
  if (!value || value.length > 256 || value.trim() !== value) return false
  try {
    const endpoint = new URL(value)
    const host = endpoint.hostname.toLowerCase()
    const ipv4 = host.match(/^127\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
    const loopback =
      host === 'localhost' ||
      host === '[::1]' ||
      Boolean(
        ipv4 &&
          ipv4.slice(1).every((component) => Number(component) <= 255),
      )
    return (
      endpoint.protocol === 'http:' &&
      loopback &&
      endpoint.username === '' &&
      endpoint.password === '' &&
      endpoint.pathname === '/' &&
      endpoint.search === '' &&
      endpoint.hash === ''
    )
  } catch {
    return false
  }
}

function parseSettings(value: unknown): LocalAISettings {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'enabled',
      'provider',
      'endpoint',
      'selectedModel',
      'revision',
    ]) ||
    typeof data.enabled !== 'boolean' ||
    !isProvider(data.provider) ||
    typeof data.endpoint !== 'string' ||
    !isLoopbackLocalAIEndpoint(data.endpoint) ||
    !(data.selectedModel === null || isModelId(data.selectedModel)) ||
    (data.enabled && data.selectedModel === null) ||
    !Number.isSafeInteger(data.revision) ||
    Number(data.revision) < 1
  ) {
    throw new Error('Local AI settings response is invalid')
  }
  return data as unknown as LocalAISettings
}

function parseModels(value: unknown): LocalAIModelDiscoveryResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, ['models']) ||
    !Array.isArray(data.models) ||
    data.models.length > 512 ||
    !data.models.every(
      (model) =>
        isRecord(model) &&
        hasExactKeys(model, ['provider', 'modelId']) &&
        isProvider(model.provider) &&
        isModelId(model.modelId),
    ) ||
    new Set(data.models.map((model) => String(model.modelId))).size !==
      data.models.length
  ) {
    throw new Error('Local AI model response is invalid')
  }
  return data as unknown as LocalAIModelDiscoveryResult
}

function parseConnection(value: unknown): LocalAIConnectionResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !hasExactKeys(data, [
      'status',
      'reachable',
      'modelCount',
      'selectedModelAvailable',
    ]) ||
    !CONNECTION_STATUSES.has(String(data.status)) ||
    typeof data.reachable !== 'boolean' ||
    !Number.isSafeInteger(data.modelCount) ||
    Number(data.modelCount) < 0 ||
    Number(data.modelCount) > 512 ||
    !(
      data.selectedModelAvailable === null ||
      typeof data.selectedModelAvailable === 'boolean'
    ) ||
    (data.status === 'AVAILABLE' && !data.reachable) ||
    (data.status === 'AVAILABLE' && data.selectedModelAvailable === false) ||
    (data.status === 'MODEL_UNAVAILABLE' &&
      (!data.reachable || data.selectedModelAvailable !== false)) ||
    (['TIMEOUT', 'UNAVAILABLE', 'INVALID_RESPONSE'].includes(
      String(data.status),
    ) &&
      (data.reachable || data.modelCount !== 0))
  ) {
    throw new Error('Local AI connection response is invalid')
  }
  return data as unknown as LocalAIConnectionResult
}

async function invokeNative(command: string, request?: object): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core')
  return request === undefined
    ? invoke(command)
    : invoke(command, { request })
}

export async function getLocalAISettings(): Promise<LocalAISettings> {
  return parseSettings(await invokeNative('core_get_local_ai_settings'))
}

export async function updateLocalAISettings(
  request: LocalAISettingsUpdateRequest,
): Promise<LocalAISettings> {
  return parseSettings(
    await invokeNative('core_update_local_ai_settings', request),
  )
}

export async function discoverLocalAIModels(
  request: LocalAIEndpointRequest,
): Promise<LocalAIModelDiscoveryResult> {
  return parseModels(
    await invokeNative('core_discover_local_ai_models', request),
  )
}

export async function testLocalAIConnection(
  request: LocalAIEndpointRequest,
): Promise<LocalAIConnectionResult> {
  return parseConnection(
    await invokeNative('core_test_local_ai_connection', request),
  )
}

export const localAiBoundaryParsers = {
  settings: parseSettings,
  models: parseModels,
  connection: parseConnection,
}
