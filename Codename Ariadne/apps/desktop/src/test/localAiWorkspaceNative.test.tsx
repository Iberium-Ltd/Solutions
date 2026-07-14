import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { AIWorkspacePage } from '../pages/AIWorkspacePage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const leftRef = 'finding:33333333-3333-4333-8333-333333333333'
const rightRef = 'finding:44444444-4444-4444-8444-444444444444'
const evidenceRef = 'evidence:55555555-5555-4555-8555-555555555555'
const response = (data: unknown) => ({ requestId, data })

const counts = {
  entities: 0,
  graphNodes: 0,
  graphEdges: 0,
  findings: 2,
  remediationCases: 0,
  auditRuns: 0,
  documentSegments: 0,
}

const exactSourceFields = {
  sourceId: null,
  sourceDisplayName: null,
  artifactId: null,
  segmentId: null,
  segmentIndex: null,
  segmentLocator: null,
  sourceSpanStart: null,
  sourceSpanEnd: null,
  extractionRunId: null,
  extractorKind: null,
  extractorName: null,
  extractorVersion: null,
  runId: null,
  originKind: null,
  originType: null,
  observedAtUs: null,
  confidenceMicros: null,
  disposition: null,
  sourceUrlSha256: null,
  captureMethod: null,
  httpStatus: null,
  redirectCount: null,
}

const workspaceResult = {
  profileId,
  task: 'SUMMARY',
  selectedScopes: ['ENTITIES', 'GRAPH', 'FINDINGS', 'REMEDIATION', 'AUDIT_COVERAGE'],
  requestedExecution: 'DETERMINISTIC',
  executionMode: 'DETERMINISTIC',
  fallbackReason: null,
  provider: null,
  modelId: null,
  engineVersion: '1',
  title: 'Synthetic source-grounded review',
  summary: 'The model proposes one relationship for human review.',
  sections: [{
    heading: 'Hypotheses',
    items: [{
      text: 'A possible relationship needs verification.',
      evidenceRefs: [leftRef, rightRef, evidenceRef],
    }],
  }],
  facts: [{
    statement: 'The first synthetic finding is stored in the selected profile.',
    evidenceRefs: [leftRef],
    confidence: 'HIGH',
  }],
  connections: [{
    fromRef: leftRef,
    toRef: rightRef,
    relationship: 'POSSIBLY_RELATED',
    supportingRefs: [evidenceRef],
    contradictionRefs: [rightRef],
    confidence: 'LOW',
    rationale: 'One bounded synthetic signal overlaps while another record may contradict it.',
    verificationSuggestion: 'Compare the cited source records before confirmation.',
  }],
  nextSteps: [{
    priority: 1,
    suggestion: 'Review the exact evidence source.',
    rationale: 'The relationship remains unconfirmed.',
    supportingRefs: [evidenceRef],
  }],
  sources: [
    {
      ...exactSourceFields,
      ref: leftRef,
      kind: 'FINDING',
      label: 'Synthetic finding A',
      locator: `${leftRef} · provider provider-synthetic-local`,
      sourceUrl: null,
      contentSha256: null,
      providerId: 'provider-synthetic-local',
    },
    {
      ...exactSourceFields,
      ref: rightRef,
      kind: 'FINDING',
      label: 'Synthetic finding B',
      locator: `${rightRef} · provider provider-synthetic-local`,
      sourceUrl: null,
      contentSha256: null,
      providerId: 'provider-synthetic-local',
    },
    {
      ...exactSourceFields,
      ref: evidenceRef,
      kind: 'EVIDENCE_METADATA',
      label: 'Synthetic HTML evidence',
      locator: `${evidenceRef} · run run-synthetic-local · sha256 ${'a'.repeat(64)}`,
      sourceUrl: 'https://evidence.example.invalid/capture',
      contentSha256: 'a'.repeat(64),
      providerId: 'provider-synthetic-local',
      artifactId: '55555555-5555-4555-8555-555555555555',
      runId: 'run-synthetic-local',
      observedAtUs: 1_783_900_000_000_000,
      sourceUrlSha256: 'c'.repeat(64),
      captureMethod: 'HTTP_FETCH',
      httpStatus: 200,
      redirectCount: 0,
    },
  ],
  unanswered: null,
  limitations: ['Human review remains required.'],
  includedCounts: counts,
  availableCounts: counts,
  projectionTruncated: false,
  inputSha256: 'b'.repeat(64),
  restrictedValuesRedacted: 0,
  localOnly: true,
  externalNetworkUsed: false,
  rawEvidenceIncluded: false,
  reviewOnly: true,
  humanReviewRequired: true,
}

describe('native local AI workspace', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', { configurable: true, value: true })
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_local_ai_settings') {
        return response({
          enabled: false,
          provider: 'OLLAMA',
          endpoint: 'http://127.0.0.1:11434',
          selectedModel: null,
          revision: 1,
        })
      }
      if (command === 'core_discover_local_ai_models') {
        return response({ models: [] })
      }
      if (command === 'core_analyze_local_ai_workspace') {
        return response(workspaceResult)
      }
      throw new Error(`Unexpected command ${command}`)
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('renders every fact, endpoint, support, contradiction, and suggestion source explicitly', async () => {
    const user = userEvent.setup()
    render(<AIWorkspacePage />)

    const run = await screen.findByRole('button', { name: /run review-only analysis/i })
    await waitFor(() => expect(run).toBeEnabled())
    await user.click(run)

    expect(await screen.findByText('Synthetic source-grounded review')).toBeVisible()
    expect(screen.getByText(/model-generated summary/i)).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Cited facts' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Connection hypotheses' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Suggested next checks' })).toBeVisible()
    expect(screen.getByText('Endpoints')).toBeVisible()
    expect(screen.getByText('Supporting sources')).toBeVisible()
    expect(screen.getByText('Contradicting sources')).toBeVisible()
    expect(screen.getByText('Basis sources')).toBeVisible()
    expect(screen.getByText('Section sources')).toBeVisible()
    expect(screen.getAllByText('Synthetic finding A').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Synthetic finding B').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Synthetic HTML evidence').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Artifact ID/i).length).toBeGreaterThan(0)
    expect(
      screen.getAllByRole('link', { name: /evidence\.example\.invalid\/capture/i }).length,
    ).toBeGreaterThan(0)
    expect(invokeMock).toHaveBeenCalledWith('core_analyze_local_ai_workspace', {
      request: expect.objectContaining({
        profileId,
        execution: 'DETERMINISTIC',
        modelId: null,
      }),
    })
  })

  it('never invokes analysis without an active profile', async () => {
    usePhase3WorkflowStore.getState().reset()
    render(<AIWorkspacePage />)

    expect(screen.getByText(/no active profile/i)).toBeVisible()
    expect(screen.getByRole('button', { name: /run review-only analysis/i })).toBeDisabled()
    expect(
      invokeMock.mock.calls.some(([command]) => command === 'core_analyze_local_ai_workspace'),
    ).toBe(false)
  })
})
