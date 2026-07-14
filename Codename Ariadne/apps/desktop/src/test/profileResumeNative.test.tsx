import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { AppShell } from '../components/AppShell'
import { IntakePage } from '../pages/IntakePage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const firstProfileId = '22222222-2222-4222-8222-222222222222'
const secondProfileId = '33333333-3333-4333-8333-333333333333'
const sourceId = '44444444-4444-4444-8444-444444444444'
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

const session = response({
  lockState: 'UNLOCKED',
  vaultState: 'UNLOCKED',
  compatibility: 'COMPATIBLE',
  authenticatedTransport: true,
  sessionExpiresAt: null,
  activeRevealCapabilities: 0,
})

const profiles = response({
  profiles: [
    {
      profileId: firstProfileId,
      displayLabel: 'Synthetic primary profile',
      purpose: 'Synthetic local review',
      status: 'ACTIVE',
      revision: 1,
    },
    {
      profileId: secondProfileId,
      displayLabel: 'Synthetic secondary profile',
      purpose: 'Synthetic local review',
      status: 'ACTIVE',
      revision: 1,
    },
  ],
  hasMore: false,
})

describe('native profile resume boundary', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
    usePhase3WorkflowStore.getState().reset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_capabilities') return capabilities
      if (command === 'core_session') return session
      if (command === 'core_list_profiles') return profiles
      throw new Error('Unexpected native command')
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('requires explicit resume and purges the prior route state on profile switch', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/audits/new/intake']}>
        <AppShell>
          <IntakePage />
        </AppShell>
      </MemoryRouter>,
    )

    const selector = await screen.findByRole('combobox', {
      name: 'Active local profile',
    })
    await waitFor(() => expect(selector).toBeEnabled())
    expect(selector).toHaveValue('')
    expect(usePhase3WorkflowStore.getState().profileId).toBeNull()
    expect(
      screen.getByRole('option', { name: 'Synthetic primary profile' }),
    ).toBeInTheDocument()

    await user.selectOptions(selector, firstProfileId)
    await waitFor(() =>
      expect(usePhase3WorkflowStore.getState().profileId).toBe(firstProfileId),
    )

    const privateInput = 'Ephemeral synthetic clue for profile switching'
    const input = await screen.findByRole('textbox', {
      name: 'Local source text',
    })
    await user.type(input, privateInput)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)

    await user.selectOptions(selector, secondProfileId)

    await waitFor(() =>
      expect(usePhase3WorkflowStore.getState()).toMatchObject({
        profileId: secondProfileId,
        sourceId: null,
      }),
    )
    expect(
      await screen.findByRole('textbox', { name: 'Local source text' }),
    ).toHaveValue('')
    expect(document.body).not.toHaveTextContent(privateInput)
  })
})
