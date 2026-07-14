import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  appendPhase5AttributionDecision,
  createPhase5RedactedDerivative,
  importPhase5Evidence,
} from '../app/phase5Boundary'
import {
  preparePhase5EvidenceFile,
  selectedPhase5EvidenceFileLimits,
} from '../app/selectedPhase5EvidenceFile'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const findingId = '33333333-3333-4333-8333-333333333333'
const assessmentId = '44444444-4444-4444-8444-444444444444'
const artifactId = '55555555-5555-4555-8555-555555555555'
const decisionId = '66666666-6666-4666-8666-666666666666'
const derivativeId = '77777777-7777-4777-8777-777777777777'
const contentBase64 = 'c3ludGhldGljIGV2aWRlbmNl'

const response = (data: unknown) => ({ requestId, data })

describe('Phase 5 native write boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('imports canonical bounded evidence and binds the complete response', async () => {
    invokeMock.mockResolvedValue(
      response({
        profileId,
        findingId,
        artifactId,
        kind: 'SCREENSHOT',
        contentSha256: 'a'.repeat(64),
        capturedAtUs: 1_783_900_000_000_000,
        captureMethod: 'MANUAL_LOCAL_IMPORT',
        encryptedAtRest: true,
        localOnly: true,
        deduplicated: false,
      }),
    )
    const request = {
      profileId,
      findingId,
      kind: 'SCREENSHOT',
      contentBase64,
      viewport: { width: 1440, height: 900, deviceScaleMicros: 2_000_000 },
      metadata: [],
    } as const

    await expect(importPhase5Evidence(request)).resolves.toMatchObject({
      artifactId,
      localOnly: true,
    })
    expect(invokeMock).toHaveBeenCalledWith('core_import_phase5_evidence', {
      request,
    })
  })

  it('rejects invalid import cross-fields before exposing content to the command', async () => {
    await expect(
      importPhase5Evidence({
        profileId,
        findingId,
        kind: 'PDF',
        contentBase64,
        viewport: { width: 1440, height: 900, deviceScaleMicros: 2_000_000 },
        metadata: [],
      }),
    ).rejects.toThrow('request is invalid')
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('requires caller attestation and binds derivative policy metadata', async () => {
    invokeMock.mockResolvedValue(
      response({
        profileId,
        originalArtifactId: artifactId,
        derivativeId,
        contentSha256: 'b'.repeat(64),
        createdAtUs: 1_783_900_100_000_000,
        redactionPolicyVersion: 'manual-redaction-v1',
        redactionSummaryCode: 'USER_REVIEWED_REDACTION',
        redactionMode: 'CALLER_SUPPLIED',
        encryptedAtRest: true,
        localOnly: true,
        deduplicated: false,
      }),
    )

    await expect(
      createPhase5RedactedDerivative({
        profileId,
        originalArtifactId: artifactId,
        redactedContentBase64: contentBase64,
        alreadyRedacted: true,
        redactionPolicyVersion: 'manual-redaction-v1',
        redactionSummaryCode: 'USER_REVIEWED_REDACTION',
      }),
    ).resolves.toMatchObject({ derivativeId, redactionMode: 'CALLER_SUPPLIED' })
  })

  it('binds a decision to the expected assessment and prior revision', async () => {
    invokeMock.mockResolvedValue(
      response({
        profileId,
        findingId,
        assessmentId,
        decisionId,
        state: 'PROBABLE',
        actorLabel: 'Local user',
        decidedAtUs: 1_783_900_200_000_000,
        weightProfileVersion: 'ariadne-attribution-v1',
        supersedesDecisionId: null,
        revision: 1,
      }),
    )

    await expect(
      appendPhase5AttributionDecision({
        profileId,
        findingId,
        assessmentId,
        state: 'PROBABLE',
        expectedPreviousDecisionId: null,
        expectedPreviousRevision: 0,
      }),
    ).resolves.toMatchObject({ decisionId, revision: 1 })

    invokeMock.mockResolvedValue(
      response({
        profileId,
        findingId,
        assessmentId,
        decisionId,
        state: 'PROBABLE',
        actorLabel: 'Local user',
        decidedAtUs: 1_783_900_200_000_000,
        weightProfileVersion: 'ariadne-attribution-v1',
        supersedesDecisionId: decisionId,
        revision: 1,
      }),
    )
    await expect(
      appendPhase5AttributionDecision({
        profileId,
        findingId,
        assessmentId,
        state: 'PROBABLE',
        expectedPreviousDecisionId: null,
        expectedPreviousRevision: 0,
      }),
    ).rejects.toThrow('response is invalid')
  })
})

describe('Phase 5 selected evidence file', () => {
  it('encodes one matching local file without returning its name or path', async () => {
    const prepared = await preparePhase5EvidenceFile(
      new File(['synthetic evidence'], 'synthetic_capture.json', {
        type: 'application/json',
      }),
      'RAW_JSON',
    )
    expect(prepared).toBe('c3ludGhldGljIGV2aWRlbmNl')
  })

  it('rejects mismatched, empty, and oversized files before encoding', async () => {
    await expect(
      preparePhase5EvidenceFile(
        new File(['{}'], 'synthetic_capture.pdf', { type: 'application/pdf' }),
        'RAW_JSON',
      ),
    ).rejects.toThrow('does not match')
    await expect(
      preparePhase5EvidenceFile(new File([], 'synthetic_capture.pdf'), 'PDF'),
    ).rejects.toThrow('non-empty')
    await expect(
      preparePhase5EvidenceFile(
        new File([
          new Uint8Array(selectedPhase5EvidenceFileLimits.maximumBytes + 1),
        ], 'synthetic_capture.pdf'),
        'PDF',
      ),
    ).rejects.toThrow('10 MiB')
  })
})
