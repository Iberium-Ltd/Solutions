/** Ensures workspace AI output remains bounded, review-only, and source-cited. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  analyzeLocalAIWorkspace,
  localAiWorkspaceBoundaryParsers,
} from '../app/localAiWorkspaceBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const sourceRef = 'evidence:33333333-3333-4333-8333-333333333333'
const counts = {
  entities: 0,
  graphNodes: 0,
  graphEdges: 0,
  findings: 1,
  remediationCases: 0,
  auditRuns: 0,
  documentSegments: 0,
}

const result = () => ({
  profileId,
  task: 'SUMMARY',
  selectedScopes: ['FINDINGS'],
  requestedExecution: 'DETERMINISTIC',
  executionMode: 'DETERMINISTIC',
  fallbackReason: null,
  provider: null,
  modelId: null,
  engineVersion: '1',
  title: 'Synthetic local summary',
  summary: 'One synthetic record is available for review.',
  sections: [{
    heading: 'Evidence',
    items: [{ text: 'One cited synthetic source.', evidenceRefs: [sourceRef] }],
  }],
  facts: [{
    statement: 'The selected synthetic finding has a FOUND outcome.',
    evidenceRefs: [sourceRef],
    confidence: 'HIGH',
  }],
  connections: [],
  nextSteps: [],
  sources: [{
    ref: sourceRef,
    kind: 'EVIDENCE_METADATA',
    label: 'Synthetic evidence',
    locator: `${sourceRef} · provider provider-synthetic-local`,
    sourceUrl: 'https://synthetic-source.example.invalid/profile',
    contentSha256: 'b'.repeat(64),
    providerId: 'provider-synthetic-local',
    sourceId: null,
    sourceDisplayName: null,
    artifactId: '33333333-3333-4333-8333-333333333333',
    segmentId: null,
    segmentIndex: null,
    segmentLocator: null,
    sourceSpanStart: null,
    sourceSpanEnd: null,
    extractionRunId: null,
    extractorKind: null,
    extractorName: null,
    extractorVersion: null,
    runId: 'run-synthetic-local',
    originKind: null,
    originType: null,
    observedAtUs: 1_783_900_000_000_000,
    confidenceMicros: null,
    disposition: null,
    sourceUrlSha256: 'c'.repeat(64),
    captureMethod: 'HTTP_FETCH',
    httpStatus: 200,
    redirectCount: 0,
  }],
  unanswered: null,
  limitations: ['Human review remains required.'],
  includedCounts: counts,
  availableCounts: counts,
  projectionTruncated: false,
  inputSha256: 'a'.repeat(64),
  restrictedValuesRedacted: 0,
  localOnly: true,
  externalNetworkUsed: false,
  rawEvidenceIncluded: false,
  reviewOnly: true,
  humanReviewRequired: true,
})

describe('local AI workspace native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts an exact cited source catalog and invokes only the workspace command', async () => {
    invokeMock.mockResolvedValue({ requestId, data: result() })
    const request = {
      profileId,
      task: 'SUMMARY' as const,
      question: null,
      scopes: ['FINDINGS' as const],
      includeSensitiveEntities: false,
      execution: 'DETERMINISTIC' as const,
      modelId: null,
      document: null,
    }

    const parsed = await analyzeLocalAIWorkspace(request)

    expect(parsed.sources[0]?.sourceUrl).toBe(
      'https://synthetic-source.example.invalid/profile',
    )
    expect(invokeMock).toHaveBeenCalledWith(
      'core_analyze_local_ai_workspace',
      { request },
    )
  })

  it('rejects facts whose exact source metadata is missing', () => {
    const invalid = result()
    invalid.sources = []
    expect(() =>
      localAiWorkspaceBoundaryParsers.result({ requestId, data: invalid }),
    ).toThrow('workspace response is invalid')

    const incomplete = result()
    const incompleteSource = incomplete.sources[0] as unknown as {
      artifactId: string | null
    }
    incompleteSource.artifactId = null
    expect(() =>
      localAiWorkspaceBoundaryParsers.result({ requestId, data: incomplete }),
    ).toThrow('workspace response is invalid')
  })

  it('rejects open output and inconsistent deterministic model identity', () => {
    expect(() =>
      localAiWorkspaceBoundaryParsers.result({
        requestId,
        data: { ...result(), actionExecuted: true },
      }),
    ).toThrow('workspace response is invalid')
    expect(() =>
      localAiWorkspaceBoundaryParsers.result({
        requestId,
        data: { ...result(), provider: 'OLLAMA', modelId: 'synthetic-model' },
      }),
    ).toThrow('workspace response is invalid')
  })

  it('accepts only an explicitly external OpenAI result and preserves exact sources', async () => {
    const external = {
      ...result(),
      requestedExecution: 'OPENAI_RESPONSES',
      executionMode: 'OPENAI_RESPONSES',
      provider: 'OPENAI_RESPONSES',
      modelId: 'gpt-synthetic',
      localOnly: false,
      externalNetworkUsed: true,
    }
    invokeMock.mockResolvedValue({ requestId, data: external })
    const request = {
      profileId,
      task: 'SUMMARY' as const,
      question: null,
      scopes: ['FINDINGS' as const],
      includeSensitiveEntities: false,
      execution: 'OPENAI_RESPONSES' as const,
      modelId: 'gpt-synthetic',
      openaiApiKey: 'sk-synthetic-one-request-key',
      document: null,
    }

    await expect(analyzeLocalAIWorkspace(request)).resolves.toEqual(external)
    expect(invokeMock).toHaveBeenCalledWith(
      'core_analyze_local_ai_workspace',
      { request },
    )
    expect(() => localAiWorkspaceBoundaryParsers.result({
      requestId,
      data: { ...external, localOnly: true },
    })).toThrow('workspace response is invalid')
  })
})
