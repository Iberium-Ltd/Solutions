/** Proves findings expose retained evidence and attribution without fabricated sources. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { FindingDetailPage } from '../pages/FindingDetailPage'
import { FindingsPage } from '../pages/FindingsPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const findingId = '33333333-3333-4333-8333-333333333333'
const assessmentId = '44444444-4444-4444-8444-444444444444'
const artifactId = '55555555-5555-4555-8555-555555555555'
const runId = '66666666-6666-4666-8666-666666666666'
const decisionId = '77777777-7777-4777-8777-777777777777'
const derivativeId = '88888888-8888-4888-8888-888888888888'
const nextDecisionId = '99999999-9999-4999-8999-999999999999'
const remediationCaseId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const persistedTitle = 'Persisted synthetic profile result'
const syntheticFallbackTitle = 'Legacy community profile'

const response = (data: unknown) => ({ requestId, data })

const finding = {
  findingId,
  title: persistedTitle,
  summary: 'A bounded synthetic record used only to test the native Phase 5 screen.',
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
}

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
}

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
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={[`/findings/${findingId}`]}>
      <Routes>
        <Route path="/findings/:findingId" element={<FindingDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('native Phase 5 findings UI', () => {
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

  it('requires an active profile without invoking the core or showing demo records', () => {
    render(
      <MemoryRouter>
        <FindingsPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('No active profile')).toBeVisible()
    expect(screen.queryByText(syntheticFallbackTitle)).not.toBeInTheDocument()
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('renders an honest empty native queue without a synthetic fallback', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({ profileId, findings: [], hasMore: false }),
    )

    render(
      <MemoryRouter>
        <FindingsPage />
      </MemoryRouter>,
    )

    expect(
      await screen.findByText('No persisted findings for this profile'),
    ).toBeVisible()
    expect(screen.getByText(/not evidence of absence/i)).toBeVisible()
    expect(screen.queryByText(syntheticFallbackTitle)).not.toBeInTheDocument()
    expect(invokeMock).toHaveBeenCalledWith('core_list_phase5_findings', {
      request: { profileId, limit: 100 },
    })
  })

  it('creates the first unresolved local finding from an empty native profile', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    const createdFinding = {
      ...finding,
      title: 'Synthetic manual finding',
      summary: 'A synthetic observation entered through the local-only form.',
      outcome: 'MANUAL_REVIEW_REQUIRED',
      visibility: 'UNKNOWN',
      providerLabel: 'Synthetic manual provider',
      artifactCount: 0,
      score: 0,
    }
    const createdAssessment = {
      ...assessment,
      score: 0,
      contributingSignals: [],
      contradictions: [],
      missingEvidence: [
        { signal: 'EXACT_EMAIL', potentialWeight: 180 },
        { signal: 'USER_CONFIRMATION', potentialWeight: 200 },
      ],
      recommendedNextEvidence: ['USER_CONFIRMATION', 'EXACT_EMAIL'],
    }
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_list_phase5_findings') {
        return response({ profileId, findings: [], hasMore: false })
      }
      if (command === 'core_create_phase5_manual_finding') {
        return response({
          profileId,
          finding: createdFinding,
          assessment: createdAssessment,
          artifacts: [],
          humanDecision: null,
        })
      }
      throw new Error('Unexpected command')
    })

    render(
      <MemoryRouter>
        <FindingsPage />
      </MemoryRouter>,
    )

    await screen.findByText('No persisted findings for this profile')
    await user.type(screen.getByLabelText('Finding title'), 'Synthetic manual finding')
    await user.type(
      screen.getByLabelText('Review summary'),
      'A synthetic observation entered through the local-only form.',
    )
    await user.clear(screen.getByLabelText('Provider label'))
    await user.type(screen.getByLabelText('Provider label'), 'Synthetic manual provider')
    await user.clear(screen.getByLabelText('Provider ID'))
    await user.type(screen.getByLabelText('Provider ID'), 'synthetic.manual')
    await user.click(screen.getByRole('button', { name: 'Create local finding' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_create_phase5_manual_finding',
        {
          request: {
            profileId,
            title: 'Synthetic manual finding',
            summary:
              'A synthetic observation entered through the local-only form.',
            outcome: 'MANUAL_REVIEW_REQUIRED',
            severity: 'MEDIUM',
            visibility: 'UNKNOWN',
            providerId: 'synthetic.manual',
            providerLabel: 'Synthetic manual provider',
          },
        },
      )
    })
    expect(screen.queryByText(syntheticFallbackTitle)).not.toBeInTheDocument()
  })

  it('renders persisted finding summaries and keeps dimensions separate', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({ profileId, findings: [finding], hasMore: false }),
    )

    render(
      <MemoryRouter>
        <FindingsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(persistedTitle)).toBeVisible()
    expect(screen.getByText('No human decision')).toBeVisible()
    expect(screen.getByText('+20 / 1000')).toBeVisible()
    expect(screen.getByText('1 sealed')).toBeVisible()
    expect(screen.queryByText(syntheticFallbackTitle)).not.toBeInTheDocument()
  })

  it('shows explainable scoring and sealed evidence integrity metadata', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({
        profileId,
        finding,
        assessment,
        artifacts: [artifact],
        humanDecision: null,
      }),
    )

    renderDetail()

    expect(await screen.findByRole('heading', { name: persistedTitle })).toBeVisible()
    expect(screen.getByText('Same uncommon username')).toBeVisible()
    expect(screen.getByText('Conflicting age')).toBeVisible()
    expect(screen.getByText('Same photograph')).toBeVisible()
    expect(screen.getByText('Original content remains sealed')).toBeVisible()
    expect(screen.getByText(/stored bytes match the recorded SHA-256/i)).toBeVisible()
    expect(screen.getByText('No human attribution decision recorded')).toBeVisible()
    expect(screen.queryByText(syntheticFallbackTitle)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Copy full hash' }))
    expect(screen.getByRole('button', { name: 'Copied' })).toBeVisible()
    expect(invokeMock).toHaveBeenCalledWith('core_get_phase5_finding', {
      request: { profileId, findingId },
    })
  })

  it('imports a bounded local file and refreshes without rendering encoded bytes', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_phase5_finding') {
        return response({
          profileId,
          finding,
          assessment,
          artifacts: [artifact],
          humanDecision: null,
        })
      }
      if (command === 'core_import_phase5_evidence') {
        return response({
          profileId,
          findingId,
          artifactId,
          kind: 'SCREENSHOT',
          contentSha256: 'b'.repeat(64),
          capturedAtUs: 1_783_900_300_000_000,
          captureMethod: 'MANUAL_LOCAL_IMPORT',
          encryptedAtRest: true,
          localOnly: true,
          deduplicated: false,
        })
      }
      throw new Error('Unexpected command')
    })
    renderDetail()

    await screen.findByRole('heading', { name: 'Import an immutable artifact' })
    await user.upload(
      screen.getByLabelText('Choose manual evidence file'),
      new File(['synthetic evidence'], 'synthetic_capture.png', {
        type: 'image/png',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Import selected file' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('core_import_phase5_evidence', {
        request: {
          profileId,
          findingId,
          kind: 'SCREENSHOT',
          contentBase64: 'c3ludGhldGljIGV2aWRlbmNl',
          viewport: {
            width: 1440,
            height: 900,
            deviceScaleMicros: 1_000_000,
          },
          metadata: [],
        },
      })
    })
    expect(await screen.findByText(/immutable artifact was imported/i)).toBeVisible()
    expect(screen.getAllByText('No file selected')).toHaveLength(2)
    expect(document.body).not.toHaveTextContent('c3ludGhldGljIGV2aWRlbmNl')
    await waitFor(() => {
      expect(
        invokeMock.mock.calls.filter(([command]) => command === 'core_get_phase5_finding'),
      ).toHaveLength(2)
    })
  })

  it('requires explicit already-redacted confirmation before storing a derivative', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_phase5_finding') {
        return response({
          profileId,
          finding,
          assessment,
          artifacts: [artifact],
          humanDecision: null,
        })
      }
      if (command === 'core_create_phase5_redacted_derivative') {
        return response({
          profileId,
          originalArtifactId: artifactId,
          derivativeId,
          contentSha256: 'c'.repeat(64),
          createdAtUs: 1_783_900_400_000_000,
          redactionPolicyVersion: 'manual-redaction-v1',
          redactionSummaryCode: 'USER_REVIEWED_REDACTION',
          redactionMode: 'CALLER_SUPPLIED',
          encryptedAtRest: true,
          localOnly: true,
          deduplicated: false,
        })
      }
      throw new Error('Unexpected command')
    })
    renderDetail()

    const storeButton = await screen.findByRole('button', {
      name: 'Store redacted derivative',
    })
    await user.upload(
      screen.getByLabelText('Choose already-redacted derivative file'),
      new File(['synthetic redacted'], 'synthetic_redacted.png', {
        type: 'image/png',
      }),
    )
    expect(storeButton).toBeDisabled()
    await user.click(
      screen.getByRole('checkbox', { name: /selected file is already redacted/i }),
    )
    expect(storeButton).toBeEnabled()
    await user.click(storeButton)

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_create_phase5_redacted_derivative',
        {
          request: expect.objectContaining({
            profileId,
            originalArtifactId: artifactId,
            alreadyRedacted: true,
            redactionPolicyVersion: 'manual-redaction-v1',
            redactionSummaryCode: 'USER_REVIEWED_REDACTION',
          }),
        },
      )
    })
    expect(await screen.findByText(/redacted derivative was stored locally/i)).toBeVisible()
    expect(screen.getByRole('checkbox', { name: /selected file is already redacted/i })).not.toBeChecked()
  })

  it('appends a human decision against the displayed assessment revision', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_phase5_finding') {
        return response({
          profileId,
          finding,
          assessment,
          artifacts: [artifact],
          humanDecision: null,
        })
      }
      if (command === 'core_append_phase5_attribution_decision') {
        return response({
          profileId,
          findingId,
          assessmentId,
          decisionId,
          state: 'PROBABLE',
          actorLabel: 'Local user',
          decidedAtUs: 1_783_900_500_000_000,
          weightProfileVersion: assessment.weightProfileVersion,
          supersedesDecisionId: null,
          revision: 1,
        })
      }
      throw new Error('Unexpected command')
    })
    renderDetail()

    await user.selectOptions(
      await screen.findByLabelText('Human attribution decision'),
      'PROBABLE',
    )
    await user.click(screen.getByRole('button', { name: 'Record decision' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_append_phase5_attribution_decision',
        {
          request: {
            profileId,
            findingId,
            assessmentId,
            state: 'PROBABLE',
            expectedPreviousDecisionId: null,
            expectedPreviousRevision: 0,
          },
        },
      )
    })
    expect(await screen.findByText(/decision revision 1 was appended locally/i)).toBeVisible()
  })

  it('creates a local remediation case from selected finding evidence', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    const draftText = 'A synthetic correction draft for local review only.'
    const createdAtUs = 1_783_900_700_000_000
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_phase5_finding') {
        return response({
          profileId,
          finding,
          assessment,
          artifacts: [artifact],
          humanDecision: null,
        })
      }
      if (command === 'core_create_phase6_remediation_case') {
        return response({
          profileId,
          case: {
            caseId: remediationCaseId,
            findingIds: [findingId],
            action: 'REQUEST_CORRECTION',
            actionDisposition: 'DRAFT',
            status: 'OPEN',
            deadlineAtUs: null,
            reappearanceCount: 0,
            revision: 1,
            updatedAtUs: createdAtUs,
            draftText,
            evidenceReferences: [artifactId],
            providerResponses: [],
            lastReappearanceAtUs: null,
            createdAtUs,
            history: [{
              revision: 1,
              eventType: 'CASE_CREATED',
              actorLabel: 'Local user',
              occurredAtUs: createdAtUs,
              previousStatus: null,
              currentStatus: 'OPEN',
              detailCode: 'CASE_CREATED',
              subjectId: findingId,
              evidenceReferences: [artifactId],
              note: null,
            }],
          },
        })
      }
      throw new Error('Unexpected command')
    })
    renderDetail()

    await screen.findByRole('heading', { name: 'Create a reviewed case' })
    expect(
      screen.getByRole('checkbox', { name: 'Artifact 1 · Screenshot' }),
    ).toBeChecked()
    await user.selectOptions(
      screen.getByLabelText(/^Tracked action/),
      'REQUEST_CORRECTION',
    )
    await user.type(screen.getByLabelText(/^Optional local draft/), draftText)
    await user.click(screen.getByRole('button', { name: 'Create local case' }))

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_create_phase6_remediation_case',
        {
          request: {
            profileId,
            findingIds: [findingId],
            action: 'REQUEST_CORRECTION',
            deadlineAtUs: null,
            evidenceReferences: [artifactId],
            draftText,
          },
        },
      )
    })
    expect(await screen.findByText(/local remediation case revision 1/i)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open Removal Tracker' })).toHaveAttribute(
      'href',
      '/remediation',
    )
  })

  it('supersedes exactly the displayed prior human decision revision', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    const decidedFinding = { ...finding, attributionState: 'POSSIBLE' }
    const humanDecision = {
      decisionId,
      assessmentId,
      state: 'POSSIBLE',
      actorLabel: 'Local user',
      decidedAtUs: 1_783_900_500_000_000,
      weightProfileVersion: assessment.weightProfileVersion,
      supersedesDecisionId: null,
      revision: 1,
    }
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_phase5_finding') {
        return response({
          profileId,
          finding: decidedFinding,
          assessment,
          artifacts: [artifact],
          humanDecision,
        })
      }
      if (command === 'core_append_phase5_attribution_decision') {
        return response({
          profileId,
          findingId,
          assessmentId,
          decisionId: nextDecisionId,
          state: 'CONFIRMED_NON_MATCH',
          actorLabel: 'Local user',
          decidedAtUs: 1_783_900_600_000_000,
          weightProfileVersion: assessment.weightProfileVersion,
          supersedesDecisionId: decisionId,
          revision: 2,
        })
      }
      throw new Error('Unexpected command')
    })
    renderDetail()

    await user.selectOptions(
      await screen.findByLabelText('Human attribution decision'),
      'CONFIRMED_NON_MATCH',
    )
    await user.click(
      screen.getByRole('button', { name: 'Append superseding decision' }),
    )

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'core_append_phase5_attribution_decision',
        {
          request: {
            profileId,
            findingId,
            assessmentId,
            state: 'CONFIRMED_NON_MATCH',
            expectedPreviousDecisionId: decisionId,
            expectedPreviousRevision: 1,
          },
        },
      )
    })
    expect(await screen.findByText(/decision revision 2 was appended locally/i)).toBeVisible()
  })

  it('rejects malformed native detail responses without leaking partial data', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({
        profileId,
        finding,
        assessment,
        artifacts: [{ ...artifact, encryptedAtRest: false }],
        humanDecision: null,
      }),
    )

    renderDetail()

    expect(await screen.findByText('Finding could not be loaded')).toBeVisible()
    await waitFor(() => expect(screen.queryByText(persistedTitle)).not.toBeInTheDocument())
    expect(document.body).not.toHaveTextContent(artifact.contentSha256)
  })
})
