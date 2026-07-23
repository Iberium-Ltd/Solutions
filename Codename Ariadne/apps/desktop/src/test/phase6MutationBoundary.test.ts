/** Locks revision and authorization requirements on monitoring-era mutations. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createPhase6RemediationCase,
  linkPhase6RemediationEvidence,
  recordPhase6ProviderResponse,
  recordPhase6Reappearance,
  requirePhase6RemediationApproval,
  setPhase6RemediationDeadline,
  transitionPhase6RemediationStatus,
  updatePhase6RemediationDraft,
  type Phase6RemediationCase,
  type Phase6RemediationEventType,
} from '../app/phase6Boundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const caseId = '33333333-3333-4333-8333-333333333333'
const findingId = '44444444-4444-4444-8444-444444444444'
const evidenceId = '55555555-5555-4555-8555-555555555555'
const addedEvidenceId = '66666666-6666-4666-8666-666666666666'
const providerId = 'local-provider.phase6'
const createdAtUs = 1_783_900_000_000_000
const updatedAtUs = createdAtUs + 1_000

const envelope = (case_: Phase6RemediationCase) => ({
  requestId,
  data: { profileId, case: case_ },
})

function createdCase(
  overrides: Partial<Phase6RemediationCase> = {},
): Phase6RemediationCase {
  return {
    caseId,
    findingIds: [findingId],
    action: 'REQUEST_CORRECTION',
    actionDisposition: 'DRAFT',
    status: 'OPEN',
    deadlineAtUs: null,
    reappearanceCount: 0,
    revision: 1,
    updatedAtUs: createdAtUs,
    draftText: null,
    evidenceReferences: [evidenceId],
    providerResponses: [],
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
        subjectId: null,
        evidenceReferences: [evidenceId],
        note: null,
      },
    ],
    ...overrides,
  }
}

function mutatedCase(
  eventType: Phase6RemediationEventType,
  overrides: Partial<Phase6RemediationCase> = {},
  eventOverrides: Partial<Phase6RemediationCase['history'][number]> = {},
): Phase6RemediationCase {
  const status = overrides.status ?? 'OPEN'
  return createdCase({
    revision: 2,
    updatedAtUs,
    history: [
      createdCase().history[0],
      {
        revision: 2,
        eventType,
        actorLabel: 'Local user',
        occurredAtUs: updatedAtUs,
        previousStatus: 'OPEN',
        currentStatus: status,
        detailCode: eventType,
        subjectId: null,
        evidenceReferences: [],
        note: null,
        ...eventOverrides,
      },
    ],
    ...overrides,
  })
}

describe('Phase 6 native remediation mutation boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('creates a profile-bound local case and binds its complete first revision', async () => {
    const draftText = 'A synthetic local correction draft.'
    invokeMock.mockResolvedValue(envelope(createdCase({ draftText })))
    const request = {
      profileId,
      findingIds: [findingId],
      action: 'REQUEST_CORRECTION',
      deadlineAtUs: null,
      evidenceReferences: [evidenceId],
      draftText,
    } as const

    await expect(createPhase6RemediationCase(request)).resolves.toMatchObject({
      profileId,
      case: { caseId, revision: 1 },
    })
    expect(invokeMock).toHaveBeenCalledWith(
      'core_create_phase6_remediation_case',
      { request },
    )
  })

  it('binds draft, approval, status, and deadline mutations to CAS revision two', async () => {
    const base = { profileId, caseId, expectedRevision: 1 } as const
    const draftText = 'Updated synthetic local draft.'
    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase('DRAFT_UPDATED', { draftText, status: 'IN_PROGRESS' })),
    )
    await expect(
      updatePhase6RemediationDraft({ ...base, draftText }),
    ).resolves.toMatchObject({ case: { revision: 2, draftText } })

    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase('APPROVAL_REQUIRED', {
        actionDisposition: 'REQUIRE_EXPLICIT_APPROVAL',
        status: 'AWAITING_EXPLICIT_APPROVAL',
      })),
    )
    await expect(requirePhase6RemediationApproval(base)).resolves.toMatchObject({
      case: { revision: 2, status: 'AWAITING_EXPLICIT_APPROVAL' },
    })

    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase('STATUS_CHANGED', { status: 'MONITORING' }, {
        note: 'Synthetic local monitoring note.',
      })),
    )
    await expect(
      transitionPhase6RemediationStatus({
        ...base,
        targetStatus: 'MONITORING',
        note: 'Synthetic local monitoring note.',
      }),
    ).resolves.toMatchObject({ case: { revision: 2, status: 'MONITORING' } })

    const deadlineAtUs = updatedAtUs + 10_000
    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase('DEADLINE_CHANGED', { deadlineAtUs })),
    )
    await expect(
      setPhase6RemediationDeadline({ ...base, deadlineAtUs }),
    ).resolves.toMatchObject({ case: { revision: 2, deadlineAtUs } })

    expect(invokeMock.mock.calls.map(([command]) => command)).toEqual([
      'core_update_phase6_remediation_draft',
      'core_require_phase6_remediation_approval',
      'core_transition_phase6_remediation_status',
      'core_set_phase6_remediation_deadline',
    ])
  })

  it('binds evidence, received response, and reappearance mutations', async () => {
    const base = { profileId, caseId, expectedRevision: 1 } as const
    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase(
        'EVIDENCE_LINKED',
        { evidenceReferences: [evidenceId, addedEvidenceId] },
        { evidenceReferences: [addedEvidenceId] },
      )),
    )
    await expect(
      linkPhase6RemediationEvidence({
        ...base,
        evidenceReferences: [addedEvidenceId],
      }),
    ).resolves.toMatchObject({ case: { revision: 2 } })

    const summary = 'Synthetic response already received outside Ariadne.'
    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase(
        'PROVIDER_RESPONSE_RECORDED',
        {
          providerResponses: [{
            providerId,
            responseCode: 'RECEIVED',
            summary,
            receivedAtUs: updatedAtUs,
            evidenceReferences: [evidenceId],
          }],
        },
        { subjectId: providerId, evidenceReferences: [evidenceId] },
      )),
    )
    await expect(
      recordPhase6ProviderResponse({
        ...base,
        providerId,
        responseCode: 'RECEIVED',
        summary,
        evidenceReferences: [evidenceId],
      }),
    ).resolves.toMatchObject({ case: { revision: 2 } })

    invokeMock.mockResolvedValueOnce(
      envelope(mutatedCase(
        'REAPPEARANCE_RECORDED',
        {
          status: 'IN_PROGRESS',
          reappearanceCount: 1,
          lastReappearanceAtUs: updatedAtUs,
        },
        {
          currentStatus: 'IN_PROGRESS',
          subjectId: findingId,
          evidenceReferences: [evidenceId],
        },
      )),
    )
    await expect(
      recordPhase6Reappearance({
        ...base,
        findingId,
        evidenceReferences: [evidenceId],
      }),
    ).resolves.toMatchObject({ case: { revision: 2, reappearanceCount: 1 } })

    expect(invokeMock.mock.calls.map(([command]) => command)).toEqual([
      'core_link_phase6_remediation_evidence',
      'core_record_phase6_provider_response',
      'core_record_phase6_reappearance',
    ])
  })

  it('rejects malformed requests and mismatched result revisions before exposure', async () => {
    await expect(
      createPhase6RemediationCase({
        profileId: profileId.toUpperCase(),
        findingIds: [findingId],
        action: 'MONITOR',
        deadlineAtUs: null,
        evidenceReferences: [],
        draftText: 'Outbound text is invalid for a local action.',
      }),
    ).rejects.toThrow('create request is invalid')
    expect(invokeMock).not.toHaveBeenCalled()

    invokeMock.mockResolvedValue(
      envelope(mutatedCase('DRAFT_UPDATED', {
        revision: 3,
        draftText: 'Synthetic local draft.',
      })),
    )
    await expect(
      updatePhase6RemediationDraft({
        profileId,
        caseId,
        expectedRevision: 1,
        draftText: 'Synthetic local draft.',
      }),
    ).rejects.toThrow()
  })
})
