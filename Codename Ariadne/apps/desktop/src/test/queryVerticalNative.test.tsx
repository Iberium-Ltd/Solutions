import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { TransmissionPage } from '../pages/TransmissionPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const runId = '33333333-3333-4333-8333-333333333333'
const checkId = '44444444-4444-4444-8444-444444444444'
const entityId = '55555555-5555-4555-8555-555555555555'
const privateValue = 'private-synthetic-alias-7f4d8a'

const response = (data: unknown) => ({ requestId, data })

const provider = {
  providerId: 'local-dry-run',
  displayName: 'Local dry-run evaluator',
  operator: 'Codename Ariadne on this Mac',
  adapterMode: 'DRY_RUN',
  accessBasis: 'LOCAL_ONLY',
  processingRegions: [],
  networkAccess: false,
  sendsIdentifiers: false,
  enabled: true,
  retentionKnown: true,
}

const approvalCell = {
  checkId,
  entityId,
  providerId: provider.providerId,
  maskedValue: 'p•••••••••••••••••••••••••••',
  entityType: 'USERNAME',
  queryClass: 'EXACT',
  state: 'APPROVAL_REQUIRED',
  outcome: 'NOT_CHECKED',
  reasonCode: 'ONE_TIME_APPROVAL_REQUIRED',
  requiresApproval: true,
  revision: 1,
}

describe('native query-policy preflight', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_query_providers') {
        return response({
          profileId,
          providers: [provider],
          externalProviderCount: 0,
        })
      }
      if (command === 'core_create_query_plan') {
        return response({
          runId,
          profileId,
          policyMode: 'LOCAL_ONLY',
          cells: [approvalCell],
          plannedCount: 0,
          approvalRequiredCount: 1,
          notCheckedCount: 0,
          blockedCount: 0,
        })
      }
      if (command === 'core_execute_query_dry_run') {
        return response({
          ...approvalCell,
          state: 'SUCCEEDED',
          outcome: 'SUCCEEDED',
          reasonCode: 'DRY_RUN_NO_NETWORK',
          requiresApproval: false,
          revision: 3,
        })
      }
      throw new Error(`Unexpected command: ${command}`)
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('creates a masked server-side plan and consumes approval only for dry-run', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <TransmissionPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Local dry-run evaluator · DRY RUN')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Create local preflight' }))
    expect(await screen.findByText(approvalCell.maskedValue)).toBeVisible()

    const planCall = invokeMock.mock.calls.find(
      ([command]) => command === 'core_create_query_plan',
    )
    expect(planCall?.[1]).toEqual({
      request: {
        profileId,
        purposeCode: 'AUTHORIZED_LOCAL_IDENTITY_REVIEW',
        providerIds: ['local-dry-run'],
        policyMode: 'LOCAL_ONLY',
        allowedProviderIds: [],
        allowedRegions: [],
        maximumChecks: 12,
        maximumChecksPerProvider: 6,
      },
    })
    expect(JSON.stringify(planCall)).not.toContain(privateValue)

    await user.click(
      screen.getByRole('button', { name: 'Approve once & dry-run' }),
    )
    await waitFor(() =>
      expect(screen.getAllByText('SUCCEEDED').length).toBeGreaterThan(0),
    )
    expect(invokeMock).toHaveBeenCalledWith('core_execute_query_dry_run', {
      request: {
        profileId,
        runId,
        checkId,
        expectedRevision: 1,
        approveOnce: true,
      },
    })
  })
})
