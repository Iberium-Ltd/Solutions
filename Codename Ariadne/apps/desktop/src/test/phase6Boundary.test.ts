/** Validates comparison, remediation, checkpoint, and report projections. */
import { describe, expect, it } from 'vitest'
import { phase6BoundaryParsers } from '../app/phase6Boundary'

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

const envelope = (data: unknown) => ({ requestId, data })

const baselineRun = {
  runId: baselineRunId,
  sequence: 1,
  capturedAtUs: createdAtUs - 10_000,
  runState: 'COMPLETED',
  findingCount: 0,
  providerCount: 1,
} as const

const currentRun = {
  runId: currentRunId,
  sequence: 2,
  capturedAtUs: createdAtUs - 5_000,
  runState: 'COMPLETED',
  findingCount: 1,
  providerCount: 1,
} as const

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
  coverage: [
    {
      providerId,
      baselineState: 'COMPLETE',
      currentState: 'COMPLETE',
    },
  ],
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

function remediationDetail() {
  return envelope({
    profileId,
    case: {
      ...caseSummary,
      draftText: 'A local synthetic correction draft.',
      evidenceReferences: [evidenceId],
      providerResponses: [
        {
          providerId,
          responseCode: 'RECEIVED',
          summary: 'A synthetic provider response retained for boundary testing.',
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
  })
}

describe('Phase 6 desktop response boundary', () => {
  it('accepts bounded profile-bound run and comparison responses', () => {
    const parsedRuns = phase6BoundaryParsers.auditRuns(
      envelope({ profileId, runs: [currentRun, baselineRun], hasMore: false }),
    )
    expect(parsedRuns.profileId).toBe(profileId)
    expect(parsedRuns.runs[0]).toMatchObject({ runId: currentRunId })

    expect(phase6BoundaryParsers.auditComparison(envelope(comparison))).toMatchObject({
      profileId,
      baselineRunId,
      currentRunId,
      diffs: [{ stableId, state: 'NEW' }],
    })
  })

  it('accepts an exact local-only checkpoint and rejects response drift', () => {
    const checkpoint = {
      profileId,
      ...currentRun,
      localOnly: true,
    }
    expect(
      phase6BoundaryParsers.localCheckpoint(envelope(checkpoint)),
    ).toMatchObject({
      profileId,
      runId: currentRunId,
      sequence: 2,
      localOnly: true,
    })

    expect(() =>
      phase6BoundaryParsers.localCheckpoint(
        envelope({ ...checkpoint, localOnly: false }),
      ),
    ).toThrow('local checkpoint response is invalid')
  })

  it('rejects impossible fingerprint and lifecycle bindings', () => {
    expect(() =>
      phase6BoundaryParsers.auditComparison(
        envelope({
          ...comparison,
          diffs: [
            {
              ...comparison.diffs[0],
              state: 'REMOVED',
              currentFingerprint: 'a'.repeat(64),
            },
          ],
        }),
      ),
    ).toThrow('audit comparison is invalid')

    expect(() =>
      phase6BoundaryParsers.auditComparison(
        envelope({
          ...comparison,
          lifecycles: [
            {
              ...comparison.lifecycles[0],
              events: [
                {
                  ...comparison.lifecycles[0].events[0],
                  runId: baselineRunId,
                },
              ],
            },
          ],
        }),
      ),
    ).toThrow('comparison bindings are invalid')
  })

  it('accepts complete remediation summaries and immutable case history', () => {
    expect(
      phase6BoundaryParsers.remediationCases(
        envelope({ profileId, cases: [caseSummary], hasMore: false }),
      ),
    ).toMatchObject({ profileId, cases: [{ caseId, revision: 2 }] })

    expect(phase6BoundaryParsers.remediationCase(remediationDetail())).toMatchObject({
      profileId,
      case: {
        caseId,
        providerResponses: [{ providerId, responseCode: 'RECEIVED' }],
        history: [{ revision: 1 }, { revision: 2 }],
      },
    })
  })

  it('rejects unknown fields, history gaps, and nested evidence drift', () => {
    expect(() =>
      phase6BoundaryParsers.remediationCases(
        envelope({ profileId, cases: [caseSummary], hasMore: false, extra: true }),
      ),
    ).toThrow('case list is invalid')

    const historyGap = remediationDetail()
    const historyGapCase = (historyGap.data as { case: Record<string, unknown> }).case
    const history = historyGapCase.history as Array<Record<string, unknown>>
    historyGapCase.history = [history[0], { ...history[1], revision: 3 }]
    expect(() => phase6BoundaryParsers.remediationCase(historyGap)).toThrow(
      'case bindings are invalid',
    )

    const evidenceDrift = remediationDetail()
    const evidenceCase = (evidenceDrift.data as { case: Record<string, unknown> }).case
    const responses = evidenceCase.providerResponses as Array<Record<string, unknown>>
    evidenceCase.providerResponses = [
      {
        ...responses[0],
        evidenceReferences: ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
      },
    ]
    expect(() => phase6BoundaryParsers.remediationCase(evidenceDrift)).toThrow(
      'case bindings are invalid',
    )
  })
})
