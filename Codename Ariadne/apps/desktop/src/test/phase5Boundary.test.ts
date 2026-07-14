import { describe, expect, it } from 'vitest'
import { phase5BoundaryParsers } from '../app/phase5Boundary'

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const findingId = '33333333-3333-4333-8333-333333333333'
const assessmentId = '44444444-4444-4444-8444-444444444444'
const artifactId = '55555555-5555-4555-8555-555555555555'
const runId = '66666666-6666-4666-8666-666666666666'
const decisionId = '77777777-7777-4777-8777-777777777777'

const finding = {
  findingId,
  title: 'Persisted synthetic profile result',
  summary: 'A bounded synthetic record used only to validate the native Phase 5 boundary.',
  outcome: 'FOUND',
  severity: 'MEDIUM',
  visibility: 'PUBLIC_PSEUDONYMOUS',
  attributionState: null,
  confidenceBand: 'LOW',
  score: 20,
  humanReviewRequired: true,
  providerLabel: 'Local synthetic provider',
  artifactCount: 1,
  updatedAtUs: 1_783_900_000_000_000,
} as const

const artifact = {
  artifactId,
  kind: 'SCREENSHOT',
  contentSha256: 'a'.repeat(64),
  capturedAtUs: 1_783_899_000_000_000,
  sourceUrl: 'https://phase5.example.invalid/profile',
  httpStatus: 200,
  redirectCount: 0,
  providerId: 'local-synthetic-provider',
  runId,
  viewport: { width: 1440, height: 900, deviceScaleMicros: 2_000_000 },
  captureMethod: 'BROWSER_CAPTURE',
  encryptedAtRest: true,
  integrityStatus: 'VERIFIED',
  derivativeCount: 1,
} as const

const assessment = {
  assessmentId,
  caseId: findingId,
  weightProfileVersion: 'ariadne-attribution-v1',
  score: 20,
  confidenceBand: 'LOW',
  contributingSignals: [
    {
      signal: 'SAME_UNCOMMON_USERNAME',
      weight: 120,
      evidenceArtifactIds: [artifactId],
    },
  ],
  contradictions: [
    {
      signal: 'CONFLICTING_AGE',
      penalty: 100,
      evidenceArtifactIds: [artifactId],
    },
  ],
  missingEvidence: [{ signal: 'SAME_PHOTOGRAPH', potentialWeight: 120 }],
  recommendedNextEvidence: ['SAME_PHOTOGRAPH'],
  humanReviewRequired: true,
} as const

const envelope = (data: unknown) => ({ requestId, data })

function validDetail() {
  return envelope({
    profileId,
    finding,
    assessment,
    artifacts: [artifact],
    humanDecision: null,
  })
}

describe('Phase 5 desktop response boundary', () => {
  it('accepts a completely bound evidence and attribution response', () => {
    expect(phase5BoundaryParsers.detail(validDetail())).toMatchObject({
      profileId,
      finding: { findingId, score: 20, attributionState: null },
      assessment: { assessmentId, caseId: findingId, humanReviewRequired: true },
      artifacts: [{ artifactId, integrityStatus: 'VERIFIED' }],
      humanDecision: null,
    })
  })

  it('rejects unknown fields, unencrypted artifacts, and unsafe source URLs', () => {
    expect(() =>
      phase5BoundaryParsers.list(
        envelope({ profileId, findings: [finding], hasMore: false, extra: true }),
      ),
    ).toThrow('finding list is invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          artifacts: [{ ...artifact, encryptedAtRest: false }],
        }),
      ),
    ).toThrow('finding detail is invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          artifacts: [
            { ...artifact, sourceUrl: 'https://phase5.example.invalid/profile?secret=value' },
          ],
        }),
      ),
    ).toThrow('finding detail is invalid')
  })

  it('rejects score, artifact-count, evidence-reference, and decision bindings that drift', () => {
    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          assessment: { ...assessment, score: 21 },
        }),
      ),
    ).toThrow('bindings are invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          finding: { ...finding, artifactCount: 2 },
        }),
      ),
    ).toThrow('bindings are invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          assessment: {
            ...assessment,
            contributingSignals: [
              {
                ...assessment.contributingSignals[0],
                evidenceArtifactIds: [
                  '77777777-7777-4777-8777-777777777777',
                ],
              },
            ],
          },
        }),
      ),
    ).toThrow('bindings are invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(validDetail().data as Record<string, unknown>),
          humanDecision: {
            decisionId,
            assessmentId,
            state: 'CONFIRMED_MATCH',
            actorLabel: 'Local user',
            decidedAtUs: 1_783_900_100_000_000,
            weightProfileVersion: assessment.weightProfileVersion,
            supersedesDecisionId: null,
            revision: 1,
          },
        }),
      ),
    ).toThrow('bindings are invalid')
  })

  it('accepts an exact human revision and rejects assessment or chain drift', () => {
    const decided = envelope({
      ...(validDetail().data as Record<string, unknown>),
      finding: { ...finding, attributionState: 'PROBABLE' },
      humanDecision: {
        decisionId,
        assessmentId,
        state: 'PROBABLE',
        actorLabel: 'Local user',
        decidedAtUs: 1_783_900_100_000_000,
        weightProfileVersion: assessment.weightProfileVersion,
        supersedesDecisionId: null,
        revision: 1,
      },
    })
    expect(phase5BoundaryParsers.detail(decided)).toMatchObject({
      humanDecision: { decisionId, assessmentId, revision: 1 },
    })

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(decided.data as Record<string, unknown>),
          humanDecision: {
            ...(decided.data as { humanDecision: Record<string, unknown> }).humanDecision,
            assessmentId: '88888888-8888-4888-8888-888888888888',
          },
        }),
      ),
    ).toThrow('bindings are invalid')

    expect(() =>
      phase5BoundaryParsers.detail(
        envelope({
          ...(decided.data as Record<string, unknown>),
          humanDecision: {
            ...(decided.data as { humanDecision: Record<string, unknown> }).humanDecision,
            revision: 2,
          },
        }),
      ),
    ).toThrow('finding detail is invalid')
  })
})
