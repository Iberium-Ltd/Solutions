/** Ensures corpus AI cannot escape its selected documents or citation catalog. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  analyzeLocalCorpusAI,
  localCorpusAiBoundaryParsers,
  prepareLocalCorpusDocument,
  type LocalCorpusAIRequest,
} from '../app/localCorpusAiBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const digestA = 'a'.repeat(64)
const documentId = `corpus-document:0000:${digestA}`
const segmentId = `${documentId}:segment:0`
const corpusId = `corpus:${'c'.repeat(64)}`

const counts = {
  documents: 1,
  segments: 1,
  entities: 0,
  sharedEntities: 0,
}

const result = () => ({
  profileId,
  corpusId,
  inputManifestSha256: 'd'.repeat(64),
  inputSha256: 'e'.repeat(64),
  task: 'SUMMARY',
  requestedExecution: 'DETERMINISTIC',
  executionMode: 'DETERMINISTIC',
  fallbackReason: null,
  provider: null,
  modelId: null,
  engineVersion: '1',
  title: 'Synthetic corpus summary',
  draftSummary: 'One local document is available for review.',
  narrativeLabel: 'DRAFT_SUMMARY_NOT_A_FACT',
  sections: [{
    heading: 'Document coverage',
    items: [{
      text: 'One document segment was selected.',
      label: 'CITED_SUMMARY',
      origin: 'DETERMINISTIC',
      evidenceRefs: [segmentId],
    }],
  }],
  facts: [{
    statement: 'The selected segment contains a synthetic project note.',
    evidenceRefs: [segmentId],
    confidence: 'HIGH',
    origin: 'DETERMINISTIC',
  }],
  connections: [],
  nextSteps: [{
    priority: 2,
    suggestion: 'Review the selected source segment.',
    rationale: 'The source is available for direct verification.',
    supportingRefs: [segmentId],
    origin: 'DETERMINISTIC',
  }],
  unanswered: null,
  uncertainties: [{
    text: 'No cross-document conclusion is possible from one file.',
    label: 'LIMITATION',
    origin: 'DETERMINISTIC',
    evidenceRefs: [],
  }],
  sourceCatalog: [{
    referenceId: segmentId,
    referenceKind: 'SEGMENT',
    sources: [{
      documentId,
      documentName: 'synthetic-notes.md',
      segmentId,
      segmentIndex: 0,
      locator: 'synthetic-notes.md · paragraph 1',
    }],
  }],
  includedCounts: counts,
  availableCounts: counts,
  projectionTruncated: false,
  restrictedValuesRedacted: 0,
  localOnly: true,
  externalNetworkUsed: false,
  rawSourcesRetained: false,
  persisted: false,
  reviewOnly: true,
  humanReviewRequired: true,
})

async function request(): Promise<LocalCorpusAIRequest> {
  const content = new TextEncoder().encode('Synthetic corpus note')
  const sha = Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', content)),
    (byte) => byte.toString(16).padStart(2, '0'),
  ).join('')
  return {
    documents: [{
      displayName: 'synthetic-notes.md',
      declaredMediaType: 'text/markdown',
      contentBase64: btoa(String.fromCharCode(...content)),
      expectedSizeBytes: content.byteLength,
      expectedSha256: sha,
    }],
    semanticEnrichmentEnabled: true,
    profileId,
    task: 'SUMMARY',
    question: null,
    execution: 'DETERMINISTIC',
    modelId: null,
    maxSegments: 200,
  }
}

describe('local corpus AI native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('hash-binds every document and invokes only the placeholder corpus command', async () => {
    const prepared = await request()
    invokeMock.mockResolvedValue({ requestId, data: result() })

    const parsed = await analyzeLocalCorpusAI(prepared)

    expect(parsed.sourceCatalog[0]?.sources[0]?.locator).toContain('paragraph 1')
    expect(invokeMock).toHaveBeenCalledWith('core_analyze_local_ai_corpus', {
      request: prepared,
    })
  })

  it('rejects a cited item when the exact source catalog entry is absent', () => {
    const invalid = result()
    invalid.sourceCatalog = []
    expect(() =>
      localCorpusAiBoundaryParsers.result({ requestId, data: invalid }),
    ).toThrow('corpus AI response is invalid')
  })

  it('prepares supported UTF-8 files with canonical base64 and Web Crypto hashes', async () => {
    const content = 'Synthetic Markdown corpus file'
    const file = new File([content], 'source.md', { type: 'text/markdown' })
    if (typeof file.arrayBuffer !== 'function') {
      Object.defineProperty(file, 'arrayBuffer', {
        value: async () => new TextEncoder().encode(content).buffer,
      })
    }

    const prepared = await prepareLocalCorpusDocument(file)

    expect(prepared.displayName).toBe('source.md')
    expect(prepared.declaredMediaType).toBe('text/markdown')
    expect(atob(prepared.contentBase64)).toBe(content)
    expect(prepared.expectedSha256).toMatch(/^[0-9a-f]{64}$/)
  })

  it('rejects open output and deterministic model identity', () => {
    expect(() => localCorpusAiBoundaryParsers.result({
      requestId,
      data: { ...result(), actionExecuted: true },
    })).toThrow('corpus AI response is invalid')
    expect(() => localCorpusAiBoundaryParsers.result({
      requestId,
      data: { ...result(), provider: 'OLLAMA', modelId: 'synthetic-model' },
    })).toThrow('corpus AI response is invalid')
  })

  it('accepts an explicit OpenAI corpus result with model-produced origins', async () => {
    const external = {
      ...result(),
      requestedExecution: 'OPENAI_RESPONSES',
      executionMode: 'OPENAI_RESPONSES',
      provider: 'OPENAI_RESPONSES',
      modelId: 'gpt-synthetic',
      sections: result().sections.map((section) => ({
        ...section,
        items: section.items.map((item) => ({ ...item, origin: 'OPENAI_RESPONSES' })),
      })),
      facts: result().facts.map((fact) => ({ ...fact, origin: 'OPENAI_RESPONSES' })),
      nextSteps: result().nextSteps.map((step) => ({ ...step, origin: 'OPENAI_RESPONSES' })),
      uncertainties: result().uncertainties.map((note) => ({
        ...note,
        origin: 'OPENAI_RESPONSES',
      })),
      localOnly: false,
      externalNetworkUsed: true,
    }
    const prepared = {
      ...await request(),
      execution: 'OPENAI_RESPONSES' as const,
      modelId: 'gpt-synthetic',
      openaiApiKey: 'sk-synthetic-one-request-key',
    }
    invokeMock.mockResolvedValue({ requestId, data: external })

    await expect(analyzeLocalCorpusAI(prepared)).resolves.toEqual(external)
    expect(() => localCorpusAiBoundaryParsers.result({
      requestId,
      data: { ...external, externalNetworkUsed: false },
    })).toThrow('corpus AI response is invalid')
  })
})
