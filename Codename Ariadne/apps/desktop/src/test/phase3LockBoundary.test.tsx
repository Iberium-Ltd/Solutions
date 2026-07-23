/** Ensures locking immediately removes intake and entity material from the DOM. */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { AppShell } from '../components/AppShell'
import { EntitiesPage } from '../pages/EntitiesPage'
import { IntakePage } from '../pages/IntakePage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const sourceId = '33333333-3333-4333-8333-333333333333'
const entityId = '44444444-4444-4444-8444-444444444444'
const segmentId = '66666666-6666-4666-8666-666666666666'
const extractionRunId = '77777777-7777-4777-8777-777777777777'
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

const session = (lockState: 'LOCKED' | 'UNLOCKED') =>
  response({
    lockState,
    vaultState: lockState,
    compatibility: 'COMPATIBLE',
    authenticatedTransport: true,
    sessionExpiresAt: null,
    activeRevealCapabilities: 0,
  })

const maskedEntity = {
  entityId,
  entityType: 'EMAIL',
  displayValue: 's••••••••@example.invalid',
  sensitivity: 'SENSITIVE',
  reviewState: 'UNREVIEWED',
  temporalState: 'UNKNOWN',
  searchPolicy: 'REQUIRE_APPROVAL',
  transmissionPolicy: 'REQUIRE_EACH_APPROVAL',
  confidenceMicros: 980_000,
  provenanceLabel: 'Local source · segment 1',
  origins: [
    {
      sourceId,
      sourceDisplayName: 'Synthetic protected source',
      sourceSha256: 'b'.repeat(64),
      segmentId,
      segmentIndex: 0,
      segmentLocator: '{"kind":"paragraph","index":0}',
      sourceSpanStart: 3,
      sourceSpanEnd: 24,
      extractionRunId,
      extractorKind: 'DETERMINISTIC',
      extractorName: 'synthetic-entity-compiler',
      extractorVersion: '1.0.0',
      originKind: 'DETERMINISTIC',
      observedAtUs: 1_750_000_000_123_456,
      confidenceMicros: 980_000,
      explanation: 'Synthetic protected-source observation.',
    },
  ],
  originsTruncated: false,
  revision: 1,
} as const

function seedWorkflow() {
  usePhase3WorkflowStore.getState().setProfileId(profileId)
  usePhase3WorkflowStore.getState().setSourceId(sourceId)
}

function renderProtectedRoute(route: string, child: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AppShell>{child}</AppShell>
    </MemoryRouter>,
  )
}

describe('Phase 3 lock memory boundary', () => {
  let currentLockState: 'LOCKED' | 'UNLOCKED'

  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    currentLockState = 'UNLOCKED'
    invokeMock.mockReset()
    usePhase3WorkflowStore.getState().reset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_capabilities') return capabilities
      if (command === 'core_session') return session(currentLockState)
      if (command === 'core_list_profiles') {
        return response({
          profiles: [
            {
              profileId,
              displayLabel: 'Synthetic protected profile',
              purpose: 'Synthetic lock-boundary review',
              status: 'ACTIVE',
              revision: 1,
            },
          ],
          hasMore: false,
        })
      }
      if (command === 'core_review_entities') {
        return response({
          profileId,
          entities: [maskedEntity],
          quarantineCount: 0,
          hasMore: false,
        })
      }
      if (command === 'core_lock_current_vault') {
        currentLockState = 'LOCKED'
        return response({
          vaultId: '55555555-5555-4555-8555-555555555555',
          lockState: 'LOCKED',
          vaultState: 'LOCKED',
        })
      }
      throw new Error('Unexpected native command')
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('purges identifiers and removes unsaved intake from the DOM on manual lock', async () => {
    const privateInput = 'Ephemeral authorised clue 91c5f8'
    seedWorkflow()
    const user = userEvent.setup()
    renderProtectedRoute('/audits/new/intake', <IntakePage />)

    const input = await screen.findByRole('textbox', {
      name: 'Local source text',
    })
    await user.type(input, privateInput)
    expect(input).toHaveValue(privateInput)

    await user.click(screen.getByRole('button', { name: 'Lock local vault' }))

    expect(
      await screen.findByTestId('vault-workspace-guard'),
    ).toBeVisible()
    expect(
      screen.queryByRole('textbox', { name: 'Local source text' }),
    ).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(privateInput)
    expect(usePhase3WorkflowStore.getState()).toMatchObject({
      profileId: null,
      sourceId: null,
    })
  })

  it('polls for auto-lock and removes entity results before retaining stale scope', async () => {
    seedWorkflow()
    renderProtectedRoute('/audits/new/entities', <EntitiesPage />)
    expect(await screen.findByText(maskedEntity.displayValue)).toBeVisible()

    currentLockState = 'LOCKED'

    await waitFor(
      () => {
        expect(screen.queryByText(maskedEntity.displayValue)).not.toBeInTheDocument()
        expect(usePhase3WorkflowStore.getState()).toMatchObject({
          profileId: null,
          sourceId: null,
        })
      },
      { timeout: 2_500 },
    )
    expect(screen.getByTestId('vault-workspace-guard')).toBeVisible()
  })

  it('fails closed during system-lock focus revalidation and purges locked scope', async () => {
    seedWorkflow()
    renderProtectedRoute('/audits/new/entities', <EntitiesPage />)
    expect(await screen.findByText(maskedEntity.displayValue)).toBeVisible()

    currentLockState = 'LOCKED'
    act(() => window.dispatchEvent(new Event('focus')))

    await waitFor(() => {
      expect(screen.getByTestId('vault-workspace-guard')).toBeVisible()
      expect(screen.queryByText(maskedEntity.displayValue)).not.toBeInTheDocument()
      expect(usePhase3WorkflowStore.getState()).toMatchObject({
        profileId: null,
        sourceId: null,
      })
    })
  })
})
