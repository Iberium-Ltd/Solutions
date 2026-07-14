import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '../components/AppShell'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const vaultId = '22222222-2222-4222-8222-222222222222'
const response = (data: unknown) => ({ requestId, data })
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

const session = (
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

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/audits/new/intake']}>
      <AppShell>
        <div data-testid="native-workspace" />
      </AppShell>
    </MemoryRouter>,
  )
}

describe('native vault setup controls', () => {
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

  it('offers explicit generic vault creation, then refreshes to unlocked', async () => {
    let currentSession = session('NO_VAULT', 'LOCKED')
    invokeMock.mockImplementation(
      async (command: string, arguments_?: Record<string, unknown>) => {
        if (command === 'core_capabilities') return capabilities
        if (command === 'core_session') return currentSession
        if (command === 'core_create_vault') {
          expect(arguments_).toEqual({ displayName: 'Local Ariadne vault' })
          currentSession = session('UNLOCKED', 'UNLOCKED')
          return response({
            vaultId,
            lockState: 'UNLOCKED',
            vaultState: 'UNLOCKED',
          })
        }
        throw new Error('Unexpected command')
      },
    )
    const user = userEvent.setup()
    renderShell()

    expect(
      await screen.findByRole('heading', { name: 'Create your local vault' }),
    ).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Create vault and open Intake' }),
    ).toBeVisible()
    expect(
      screen.getByRole('link', { name: 'View getting-started guide' }),
    ).toHaveAttribute('href', '/help/getting-started')
    expect(screen.queryByText('SYN-0741')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()

    await user.click(
      await screen.findByRole('button', { name: 'Create local vault' }),
    )

    expect(
      await screen.findByRole('button', { name: 'Lock local vault' }),
    ).toBeVisible()
    expect(invokeMock).toHaveBeenCalledWith('core_create_vault', {
      displayName: 'Local Ariadne vault',
    })
  })

  it('offers explicit unlock and renders only a fixed safe failure', async () => {
    const unsafeNativeMessage = 'native error with private material'
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_capabilities') return capabilities
      if (command === 'core_session') return session('LOCKED', 'LOCKED')
      if (command === 'core_unlock_current_vault') {
        throw new Error(unsafeNativeMessage)
      }
      throw new Error('Unexpected command')
    })
    const user = userEvent.setup()
    renderShell()

    expect(
      await screen.findByRole('heading', { name: 'Unlock your local vault' }),
    ).toBeVisible()
    expect(screen.queryByText('SYN-0741')).not.toBeInTheDocument()

    await user.click(
      await screen.findByRole('button', { name: 'Unlock local vault' }),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(
      'The local vault could not be unlocked. Check system access and try again.',
    )
    expect(alert).not.toHaveTextContent(unsafeNativeMessage)
  })

  it('does not expose setup actions in browser simulation', () => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    renderShell()

    expect(
      screen.queryByRole('button', { name: 'Create local vault' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Unlock local vault' }),
    ).not.toBeInTheDocument()
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('keeps the getting-started route available while the vault is locked', async () => {
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_capabilities') return capabilities
      if (command === 'core_session') return session('LOCKED', 'LOCKED')
      throw new Error('Unexpected command')
    })

    render(
      <MemoryRouter initialEntries={['/help/getting-started']}>
        <AppShell>
          <div data-testid="locked-guide">
            <h1 id="page-title" data-testid="route-ready" tabIndex={-1}>
              Getting started
            </h1>
          </div>
        </AppShell>
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('locked-guide')).toBeVisible()
    expect(screen.queryByTestId('vault-workspace-guard')).not.toBeInTheDocument()
    expect(screen.queryByText('SYN-0741')).not.toBeInTheDocument()
  })
})
