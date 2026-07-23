/** Locks loopback-only model discovery, settings parsing, and safe failure handling. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  discoverLocalAIModels,
  isLoopbackLocalAIEndpoint,
  localAiBoundaryParsers,
  updateLocalAISettings,
} from '../app/localAiBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const response = (data: unknown) => ({ requestId, data })

describe('local AI native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts only HTTP loopback endpoints', () => {
    expect(isLoopbackLocalAIEndpoint('http://127.0.0.1:11434')).toBe(true)
    expect(isLoopbackLocalAIEndpoint('http://127.4.5.6:1234')).toBe(true)
    expect(isLoopbackLocalAIEndpoint('http://[::1]:1234')).toBe(true)
    expect(isLoopbackLocalAIEndpoint('http://localhost:11434')).toBe(true)
    expect(isLoopbackLocalAIEndpoint('https://127.0.0.1:11434')).toBe(false)
    expect(isLoopbackLocalAIEndpoint('http://192.0.2.10:11434')).toBe(false)
    expect(isLoopbackLocalAIEndpoint('http://example.invalid:11434')).toBe(
      false,
    )
    expect(isLoopbackLocalAIEndpoint('http://user:key@127.0.0.1')).toBe(false)
    expect(isLoopbackLocalAIEndpoint('http://127.0.0.1/api')).toBe(false)
  })

  it('parses disabled-by-default persisted settings exactly', () => {
    expect(
      localAiBoundaryParsers.settings(
        response({
          enabled: false,
          provider: 'OLLAMA',
          endpoint: 'http://127.0.0.1:11434',
          selectedModel: null,
          revision: 1,
        }),
      ),
    ).toMatchObject({ enabled: false, selectedModel: null, revision: 1 })

    expect(() =>
      localAiBoundaryParsers.settings(
        response({
          enabled: true,
          provider: 'OLLAMA',
          endpoint: 'http://127.0.0.1:11434',
          selectedModel: null,
          revision: 1,
        }),
      ),
    ).toThrow('settings response is invalid')
  })

  it('rejects duplicate, unbounded, and unexpected model data', () => {
    expect(() =>
      localAiBoundaryParsers.models(
        response({
          models: [
            { provider: 'OLLAMA', modelId: 'qwen-local:7b' },
            { provider: 'OLLAMA', modelId: 'qwen-local:7b' },
          ],
        }),
      ),
    ).toThrow('model response is invalid')

    expect(() =>
      localAiBoundaryParsers.models(
        response({ models: [], downloadAvailable: true }),
      ),
    ).toThrow('model response is invalid')
  })

  it('validates connection state consistency', () => {
    expect(
      localAiBoundaryParsers.connection(
        response({
          status: 'MODEL_UNAVAILABLE',
          reachable: true,
          modelCount: 1,
          selectedModelAvailable: false,
        }),
      ),
    ).toMatchObject({ status: 'MODEL_UNAVAILABLE', reachable: true })

    expect(() =>
      localAiBoundaryParsers.connection(
        response({
          status: 'TIMEOUT',
          reachable: true,
          modelCount: 1,
          selectedModelAvailable: null,
        }),
      ),
    ).toThrow('connection response is invalid')
  })

  it('uses only route-specific discovery and update commands', async () => {
    invokeMock
      .mockResolvedValueOnce(
        response({
          models: [{ provider: 'OLLAMA', modelId: 'qwen-local:7b' }],
        }),
      )
      .mockResolvedValueOnce(
        response({
          enabled: true,
          provider: 'OLLAMA',
          endpoint: 'http://127.0.0.1:11434',
          selectedModel: 'qwen-local:7b',
          revision: 2,
        }),
      )

    const endpoint = {
      provider: 'OLLAMA' as const,
      endpoint: 'http://127.0.0.1:11434',
      selectedModel: null,
    }
    await discoverLocalAIModels(endpoint)
    expect(invokeMock).toHaveBeenLastCalledWith(
      'core_discover_local_ai_models',
      { request: endpoint },
    )

    const update = {
      enabled: true,
      provider: 'OLLAMA' as const,
      endpoint: 'http://127.0.0.1:11434',
      selectedModel: 'qwen-local:7b',
      expectedRevision: 1,
    }
    await updateLocalAISettings(update)
    expect(invokeMock).toHaveBeenLastCalledWith(
      'core_update_local_ai_settings',
      { request: update },
    )
  })
})
