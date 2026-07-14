import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCoreBoundary } from '../app/coreBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const response = (data: unknown) => ({
  requestId: '11111111-1111-4111-8111-111111111111',
  data,
})

const capabilities = response({
  versions: { contract: 1, schema: 'ariadne-v1', events: 1, core: '0.1.0' },
  transport: 'UNIX_SOCKET',
  cipher: {
    required: 'SQLCIPHER',
    available: true,
    sqliteVersion: '3.53.3',
    cipherVersion: '4.17.0 community',
  },
  features: [],
})

const session = response({
  lockState: 'LOCKED',
  vaultState: 'LOCKED',
  compatibility: 'COMPATIBLE',
  authenticatedTransport: true,
  sessionExpiresAt: null,
  activeRevealCapabilities: 0,
})

const sessionResponse = (
  vaultState: 'NO_VAULT' | 'LOCKED' | 'UNLOCKED',
  lockState: 'LOCKED' | 'UNLOCKED',
) =>
  response({
    lockState,
    vaultState,
    compatibility: 'COMPATIBLE',
    authenticatedTransport: true,
    sessionExpiresAt: null,
    activeRevealCapabilities: 0,
  })

describe('native core startup', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
  })

  it('retries while a cold sidecar is still starting', async () => {
    let coreReady = false
    invokeMock.mockImplementation(async (command: string) => {
      if (!coreReady) throw new Error('Core is still starting')
      return command === 'core_capabilities' ? capabilities : session
    })

    const { result } = renderHook(() => useCoreBoundary())
    expect(result.current.state.mode).toBe('CONNECTING')
    await waitFor(() => expect(invokeMock.mock.calls.length).toBeGreaterThan(0), {
      timeout: 5_000,
    })

    const coldCallCount = invokeMock.mock.calls.length
    coreReady = true
    await waitFor(
      () => expect(invokeMock.mock.calls.length).toBeGreaterThan(coldCallCount),
      { timeout: 5_000 },
    )
    await waitFor(() => expect(result.current.state.mode).toBe('AVAILABLE'), {
      timeout: 5_000,
    })
    expect(invokeMock).toHaveBeenCalledWith('core_capabilities')
    expect(invokeMock).toHaveBeenCalledWith('core_session')
  }, 10_000)

  it('creates a generic local vault explicitly and refreshes the session', async () => {
    let currentSession = sessionResponse('NO_VAULT', 'LOCKED')
    let releaseCreate:
      | ((value: ReturnType<typeof response>) => void)
      | undefined
    invokeMock.mockImplementation(
      async (command: string, arguments_?: Record<string, unknown>) => {
        if (command === 'core_capabilities') return capabilities
        if (command === 'core_session') return currentSession
        if (command === 'core_create_vault') {
          expect(arguments_).toEqual({ displayName: 'Local Ariadne vault' })
          return new Promise((resolve) => {
            releaseCreate = resolve
          })
        }
        throw new Error('Unexpected command')
      },
    )

    const { result } = renderHook(() => useCoreBoundary())
    await waitFor(() => expect(result.current.state.mode).toBe('AVAILABLE'))

    let action: Promise<void> | undefined
    act(() => {
      action = result.current.createVault()
    })
    await waitFor(() => expect(result.current.vaultActionPending).toBe(true))
    currentSession = sessionResponse('UNLOCKED', 'UNLOCKED')
    releaseCreate?.(
      response({
        vaultId: '22222222-2222-4222-8222-222222222222',
        lockState: 'UNLOCKED',
        vaultState: 'UNLOCKED',
      }),
    )
    await act(async () => action)

    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        mode: 'AVAILABLE',
        session: { vaultState: 'UNLOCKED', lockState: 'UNLOCKED' },
      })
    })
    expect(result.current.vaultActionPending).toBe(false)
    expect(result.current.vaultActionError).toBeNull()
  })

  it('unlocks explicitly and never exposes a native error message', async () => {
    const unsafeNativeMessage = 'native failure included private material'
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_capabilities') return capabilities
      if (command === 'core_session') return sessionResponse('LOCKED', 'LOCKED')
      if (command === 'core_unlock_current_vault') {
        throw new Error(unsafeNativeMessage)
      }
      throw new Error('Unexpected command')
    })

    const { result } = renderHook(() => useCoreBoundary())
    await waitFor(() => expect(result.current.state.mode).toBe('AVAILABLE'))
    await act(async () => result.current.unlockVault())

    expect(invokeMock).toHaveBeenCalledWith('core_unlock_current_vault')
    expect(result.current.vaultActionPending).toBe(false)
    expect(result.current.vaultActionError).toBe(
      'The local vault could not be unlocked. Check system access and try again.',
    )
    expect(result.current.vaultActionError).not.toContain(unsafeNativeMessage)
  })
})
