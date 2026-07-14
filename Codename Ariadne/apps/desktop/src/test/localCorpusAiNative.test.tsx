import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { CorpusAIPage } from '../pages/CorpusAIPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const documentHash = 'a'.repeat(64)
const documentId = `corpus-document:0000:${documentHash}`
const segmentId = `${documentId}:segment:0`
const response = (data: unknown) => ({ requestId, data })
const counts = { documents: 1, segments: 1, entities: 0, sharedEntities: 0 }

const corpusResult = {
  profileId,
  corpusId: `corpus:${'b'.repeat(64)}`,
  inputManifestSha256: 'c'.repeat(64),
  inputSha256: 'd'.repeat(64),
  task: 'SUMMARY',
  requestedExecution: 'DETERMINISTIC',
  executionMode: 'DETERMINISTIC',
  fallbackReason: null,
  provider: null,
  modelId: null,
  engineVersion: '1',
  title: 'Synthetic corpus review',
  draftSummary: 'The selected source contains one synthetic review note.',
  narrativeLabel: 'DRAFT_SUMMARY_NOT_A_FACT',
  sections: [{
    heading: 'Review notes',
    items: [{
      text: 'A possible interpretation still requires review.',
      label: 'HYPOTHESIS',
      origin: 'DETERMINISTIC',
      evidenceRefs: [],
    }],
  }],
  facts: [{
    statement: 'One source segment is present in the local corpus.',
    evidenceRefs: [segmentId],
    confidence: 'HIGH',
    origin: 'DETERMINISTIC',
  }],
  connections: [],
  nextSteps: [{
    priority: 1,
    suggestion: 'Review the exact source segment.',
    rationale: 'Direct inspection can verify the cited statement.',
    supportingRefs: [segmentId],
    origin: 'DETERMINISTIC',
  }],
  unanswered: null,
  uncertainties: [],
  sourceCatalog: [{
    referenceId: segmentId,
    referenceKind: 'SEGMENT',
    sources: [{
      documentId,
      documentName: 'synthetic-corpus.md',
      segmentId,
      segmentIndex: 0,
      locator: 'synthetic-corpus.md · paragraph 1',
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
}

describe('native Corpus AI page', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', { configurable: true, value: true })
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_local_ai_settings') return response({
        enabled: false,
        provider: 'OLLAMA',
        endpoint: 'http://127.0.0.1:11434',
        selectedModel: null,
        revision: 1,
      })
      if (command === 'core_discover_local_ai_models') return response({ models: [] })
      if (command === 'core_analyze_local_ai_corpus') return response(corpusResult)
      throw new Error(`Unexpected command ${command}`)
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('uploads a hash-bound file and renders hypothesis labels plus exact citations', async () => {
    const user = userEvent.setup()
    render(<CorpusAIPage />)
    const content = 'Synthetic local corpus source'
    const file = new File([content], 'synthetic-corpus.md', { type: 'text/markdown' })
    if (typeof file.arrayBuffer !== 'function') {
      Object.defineProperty(file, 'arrayBuffer', {
        value: async () => new TextEncoder().encode(content).buffer,
      })
    }

    await user.upload(screen.getByLabelText(/add local documents/i), file)
    expect(await screen.findByText('synthetic-corpus.md')).toBeVisible()
    const run = screen.getByRole('button', { name: /run ephemeral corpus analysis/i })
    await waitFor(() => expect(run).toBeEnabled())
    await user.click(run)

    expect(await screen.findByText('Synthetic corpus review')).toBeVisible()
    expect(screen.getByText('DRAFT SUMMARY · NOT A FACT')).toBeVisible()
    expect(screen.getByText('Uncited hypothesis · do not treat as a fact')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Cited facts' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Exact source catalog' })).toBeVisible()
    expect(screen.getAllByText(segmentId).length).toBeGreaterThan(0)
    expect(screen.getAllByText('synthetic-corpus.md · paragraph 1').length).toBeGreaterThan(0)
    expect(invokeMock).toHaveBeenCalledWith('core_analyze_local_ai_corpus', {
      request: expect.objectContaining({
        profileId,
        task: 'SUMMARY',
        execution: 'DETERMINISTIC',
        documents: [expect.objectContaining({
          displayName: 'synthetic-corpus.md',
          expectedSha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        })],
      }),
    })
  })

  it('keeps all five reasoning tasks visible and does not run without files', async () => {
    render(<CorpusAIPage />)

    for (const task of ['Summarize', 'Organize', 'Ask', 'Connections', 'Evidence gaps']) {
      expect(screen.getByRole('radio', { name: new RegExp(task, 'i') })).toBeVisible()
    }
    expect(screen.getByRole('button', { name: /run ephemeral corpus analysis/i })).toBeDisabled()
    expect(invokeMock.mock.calls.some(([command]) => command === 'core_analyze_local_ai_corpus')).toBe(false)
  })
})
