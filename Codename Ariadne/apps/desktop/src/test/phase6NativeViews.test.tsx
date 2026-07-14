import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import type { Phase6RemediationCase } from '../app/phase6Boundary'
import { ComparePage } from '../pages/ComparePage'
import { RemediationPage } from '../pages/RemediationPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const baselineRunId = '33333333-3333-4333-8333-333333333333'
const currentRunId = '44444444-4444-4444-8444-444444444444'
const stableId = '55555555-5555-4555-8555-555555555555'
const providerId = 'local-provider.phase6'
const caseId = '77777777-7777-4777-8777-777777777777'
const findingId = '88888888-8888-4888-8888-888888888888'
const evidenceId = '99999999-9999-4999-8999-999999999999'
const createdAtUs = 1_783_900_000_000_000
const updatedAtUs = createdAtUs + 2_000

const response = (data: unknown) => ({ requestId, data })

const runs = [
  {
    runId: currentRunId,
    sequence: 2,
    capturedAtUs: createdAtUs - 1_000,
    runState: 'COMPLETED',
    findingCount: 1,
    providerCount: 1,
  },
  {
    runId: baselineRunId,
    sequence: 1,
    capturedAtUs: createdAtUs - 2_000,
    runState: 'COMPLETED',
    findingCount: 0,
    providerCount: 1,
  },
] as const

const comparison = {
  profileId,
  baselineRunId,
  currentRunId,
  diffs: [
    {
      stableId,
      providerId,
      state: 'NEW',
      previousFingerprint: null,
      currentFingerprint: 'a'.repeat(64),
    },
  ],
  unresolvedAbsences: [],
  coverage: [{ providerId, baselineState: 'COMPLETE', currentState: 'COMPLETE' }],
  lifecycles: [
    {
      stableId,
      providerId,
      events: [
        {
          runId: currentRunId,
          sequence: 2,
          runState: 'COMPLETED',
          providerCoverage: 'COMPLETE',
          observed: true,
          contentFingerprint: 'a'.repeat(64),
        },
      ],
    },
  ],
  incompleteComparison: false,
  incompleteReasons: [],
} as const

const caseSummary = {
  caseId,
  findingIds: [findingId],
  action: 'REQUEST_CORRECTION',
  actionDisposition: 'DRAFT',
  status: 'IN_PROGRESS',
  deadlineAtUs: updatedAtUs + 1_000,
  reappearanceCount: 0,
  revision: 2,
  updatedAtUs,
} as const

const caseDetail = {
  profileId,
  case: {
    ...caseSummary,
    draftText: 'A persisted synthetic correction draft.',
    evidenceReferences: [evidenceId],
    providerResponses: [
      {
        providerId,
        responseCode: 'RECEIVED',
        summary: 'A persisted synthetic provider response.',
        receivedAtUs: createdAtUs + 1_000,
        evidenceReferences: [evidenceId],
      },
    ],
    lastReappearanceAtUs: null,
    createdAtUs,
    history: [
      {
        revision: 1,
        eventType: 'CASE_CREATED',
        actorLabel: 'Local user',
        occurredAtUs: createdAtUs,
        previousStatus: null,
        currentStatus: 'OPEN',
        detailCode: 'CASE_CREATED',
        subjectId: findingId,
        evidenceReferences: [evidenceId],
        note: null,
      },
      {
        revision: 2,
        eventType: 'STATUS_CHANGED',
        actorLabel: 'Local user',
        occurredAtUs: updatedAtUs,
        previousStatus: 'OPEN',
        currentStatus: 'IN_PROGRESS',
        detailCode: 'REVIEW_STARTED',
        subjectId: providerId,
        evidenceReferences: [],
        note: 'Synthetic local review started.',
      },
    ],
  },
} as const

describe('native Phase 6 views', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
    usePhase3WorkflowStore.getState().reset()
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('requires an active profile without invoking native commands or showing demo data', () => {
    const { unmount } = render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getByText('No active profile')).toBeVisible()
    expect(screen.queryByText('Directory snapshot')).not.toBeInTheDocument()
    expect(invokeMock).not.toHaveBeenCalled()
    unmount()

    render(
      <MemoryRouter>
        <RemediationPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('No active profile')).toBeVisible()
    expect(screen.queryByText('Legacy community profile')).not.toBeInTheDocument()
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('renders a persisted comparison and never substitutes synthetic rows', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_audit_runs') {
        return Promise.resolve(response({ profileId, runs, hasMore: false }))
      }
      if (command === 'core_compare_phase6_runs') {
        return Promise.resolve(response(comparison))
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`))
    })

    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '1 comparison rows' })).toBeVisible()
    expect(screen.getByText('Retained lifecycle')).toBeVisible()
    expect(screen.getByText(/Observed · Completed/i)).toBeVisible()
    expect(screen.queryByText('Directory snapshot')).not.toBeInTheDocument()
    expect(
      screen.getAllByRole('button', { name: 'Evidence view pending' }),
    ).toSatisfy((buttons: HTMLButtonElement[]) =>
      buttons.length > 0 && buttons.every((button) => button.disabled),
    )
    expect(invokeMock).toHaveBeenCalledWith('core_list_phase6_audit_runs', {
      request: { profileId, limit: 32 },
    })
    expect(invokeMock).toHaveBeenCalledWith('core_compare_phase6_runs', {
      request: { profileId, baselineRunId, currentRunId },
    })
  })

  it('shows an honest insufficient-history state without comparing one run', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({ profileId, runs: [runs[0]], hasMore: false }),
    )

    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Two persisted runs are required')).toBeVisible()
    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Directory snapshot')).not.toBeInTheDocument()
  })

  it('creates a network-free checkpoint and refreshes persisted run metadata', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_audit_runs') {
        return Promise.resolve(
          response({ profileId, runs: [runs[0]], hasMore: false }),
        )
      }
      if (command === 'core_create_phase6_local_checkpoint') {
        return Promise.resolve(
          response({
            profileId,
            runId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            sequence: 3,
            capturedAtUs: createdAtUs + 10_000,
            runState: 'COMPLETED',
            findingCount: 1,
            providerCount: 1,
            localOnly: true,
          }),
        )
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`))
    })

    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )

    await screen.findByText('Two persisted runs are required')
    await user.clear(screen.getByLabelText(/Provider IDs/i))
    await user.type(screen.getByLabelText(/Provider IDs/i), providerId)
    await user.click(screen.getByRole('button', { name: 'Save checkpoint' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_create_phase6_local_checkpoint',
        {
          request: {
            profileId,
            runState: 'COMPLETED',
            providerCoverage: [{ providerId, state: 'COMPLETE' }],
          },
        },
      )
    })
    expect(
      await screen.findByText(/Local checkpoint 3 saved with 1 finding fingerprint/i),
    ).toBeVisible()
    expect(
      invokeMock.mock.calls.filter(
        ([command]) => command === 'core_list_phase6_audit_runs',
      ).length,
    ).toBeGreaterThanOrEqual(2)
  })

  it('renders persisted remediation detail with local-only mutation controls', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_remediation_cases') {
        return Promise.resolve(
          response({ profileId, cases: [caseSummary], hasMore: false }),
        )
      }
      if (command === 'core_get_phase6_remediation_case') {
        return Promise.resolve(response(caseDetail))
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`))
    })

    render(
      <MemoryRouter>
        <RemediationPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Reveal persisted local draft')).toBeVisible()
    expect(screen.getByText('A persisted synthetic provider response.')).toBeVisible()
    expect(screen.getByText(/2 immutable events/i)).toBeVisible()
    expect(screen.getByRole('link', { name: /Create from finding/i })).toHaveAttribute('href', '/findings')
    expect(screen.getByText('Edit local draft')).toBeVisible()
    expect(screen.getByRole('button', { name: /Save local draft/i })).toBeEnabled()
    expect(screen.getByText(/nothing is sent or executed/i)).toBeVisible()
    expect(screen.queryByText('Legacy community profile')).not.toBeInTheDocument()

    await user.click(screen.getByText('Reveal persisted local draft'))
    expect(screen.getAllByText('A persisted synthetic correction draft.')).toHaveLength(2)
    expect(invokeMock).toHaveBeenCalledWith('core_list_phase6_remediation_cases', {
      request: { profileId, limit: 100 },
    })
    expect(invokeMock).toHaveBeenCalledWith('core_get_phase6_remediation_case', {
      request: { profileId, caseId },
    })
  })

  it('saves a draft against the displayed revision and refreshes local state', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    const nextDraft = 'A revised synthetic draft that remains local.'
    let currentCase: Phase6RemediationCase = caseDetail.case
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_remediation_cases') {
        const {
          draftText: _draftText,
          evidenceReferences: _evidenceReferences,
          providerResponses: _providerResponses,
          lastReappearanceAtUs: _lastReappearanceAtUs,
          createdAtUs: _createdAtUs,
          history: _history,
          ...summary
        } = currentCase
        return Promise.resolve(
          response({ profileId, cases: [summary], hasMore: false }),
        )
      }
      if (command === 'core_get_phase6_remediation_case') {
        return Promise.resolve(response({ profileId, case: currentCase }))
      }
      if (command === 'core_update_phase6_remediation_draft') {
        currentCase = {
          ...currentCase,
          draftText: nextDraft,
          revision: 3,
          updatedAtUs: updatedAtUs + 1_000,
          history: [
            ...currentCase.history,
            {
              revision: 3,
              eventType: 'DRAFT_UPDATED',
              actorLabel: 'Local user',
              occurredAtUs: updatedAtUs + 1_000,
              previousStatus: 'IN_PROGRESS',
              currentStatus: 'IN_PROGRESS',
              detailCode: 'DRAFT_UPDATED',
              subjectId: null,
              evidenceReferences: [],
              note: null,
            },
          ],
        }
        return Promise.resolve(response({ profileId, case: currentCase }))
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`))
    })

    render(
      <MemoryRouter>
        <RemediationPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByText('Edit local draft'))
    const draft = screen.getByLabelText('Reviewable draft · local only')
    await user.clear(draft)
    await user.type(draft, nextDraft)
    await user.click(screen.getByRole('button', { name: 'Save local draft' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_update_phase6_remediation_draft',
        {
          request: {
            profileId,
            caseId,
            expectedRevision: 2,
            draftText: nextDraft,
          },
        },
      )
    })
    await waitFor(() => {
      expect(
        invokeMock.mock.calls.filter(
          ([command]) => command === 'core_list_phase6_remediation_cases',
        ).length,
      ).toBeGreaterThan(1)
    })
    expect(await screen.findByText(/3 immutable events/i)).toBeVisible()
    expect(screen.getByDisplayValue(nextDraft)).toBeVisible()
  })

  it('fails closed when a remediation detail response is malformed', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_remediation_cases') {
        return Promise.resolve(
          response({ profileId, cases: [caseSummary], hasMore: false }),
        )
      }
      return Promise.resolve(
        response({
          ...caseDetail,
          case: {
            ...caseDetail.case,
            history: [
              caseDetail.case.history[0],
              { ...caseDetail.case.history[1], actorLabel: 'Remote actor' },
            ],
          },
        }),
      )
    })

    render(
      <MemoryRouter>
        <RemediationPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Case detail is unavailable')).toBeVisible()
    await waitFor(() =>
      expect(
        screen.queryByText('A persisted synthetic correction draft.'),
      ).not.toBeInTheDocument(),
    )
  })
})
