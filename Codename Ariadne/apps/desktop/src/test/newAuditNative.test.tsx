/** Proves a saved pre-intake model is actually preloaded before it is labelled ready. */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { NewAuditPage } from '../pages/NewAuditPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const model = 'qwen-synthetic:7b'
const response = (data: unknown) => ({ requestId, data })

describe('native pre-intake local AI readiness', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
    usePhase3WorkflowStore.getState().reset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_list_profiles') {
        return response({ profiles: [], hasMore: false })
      }
      if (command === 'core_get_local_ai_settings') {
        return response({
          enabled: true,
          provider: 'OLLAMA',
          endpoint: 'http://127.0.0.1:11434',
          selectedModel: model,
          revision: 2,
        })
      }
      if (command === 'core_discover_local_ai_models') {
        return response({ models: [{ provider: 'OLLAMA', modelId: model }] })
      }
      if (command === 'core_test_local_ai_connection') {
        return response({
          status: 'AVAILABLE',
          reachable: true,
          modelCount: 1,
          selectedModelAvailable: true,
        })
      }
      throw new Error(`Unexpected native command ${command}`)
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('runs the content-free preload before showing the saved model as ready', async () => {
    render(
      <MemoryRouter initialEntries={['/new-audit']}>
        <NewAuditPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith(
      'core_test_local_ai_connection',
      { request: {
        provider: 'OLLAMA',
        endpoint: 'http://127.0.0.1:11434',
        selectedModel: model,
      } },
    ))
    expect(await screen.findByRole('status')).toHaveTextContent(
      `${model} is loaded and will be used during intake and the later audit.`,
    )
  })
})
