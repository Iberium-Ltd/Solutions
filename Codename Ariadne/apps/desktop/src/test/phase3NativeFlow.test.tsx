import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { EntitiesPage } from '../pages/EntitiesPage'
import { GraphPage } from '../pages/GraphPage'
import { IntakePage } from '../pages/IntakePage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))
vi.mock('cytoscape', () => ({
  default: vi.fn(() => {
    const element = {
      empty: () => false,
      select: vi.fn(),
    }
    const instance = {
      batch: (callback: () => void) => callback(),
      center: vi.fn(),
      destroy: vi.fn(),
      elements: () => ({ unselect: vi.fn() }),
      fit: vi.fn(),
      getElementById: () => element,
      nodes: () => ({ forEach: vi.fn() }),
      on: vi.fn(),
      ready: (callback: () => void) => callback(),
      zoom: vi.fn(() => 1),
    }
    return instance
  }),
}))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const sourceId = '33333333-3333-4333-8333-333333333333'
const entityId = '44444444-4444-4444-8444-444444444444'
const secondEntityId = '55555555-5555-4555-8555-555555555555'
const edgeId = '66666666-6666-4666-8666-666666666666'
const segmentId = '77777777-7777-4777-8777-777777777777'
const extractionRunId = '88888888-8888-4888-8888-888888888888'
const secondSegmentId = '99999999-9999-4999-8999-999999999999'

const response = (data: unknown) => ({ requestId, data })

const receipt = {
  sourceId,
  profileId,
  state: 'READY_FOR_REVIEW',
  sourceKind: 'PASTED_TEXT',
  segmentCount: 1,
  candidateCount: 1,
  localAiStatus: 'DISABLED',
  localAiProvider: null,
  localAiModel: null,
  localAiEngineVersion: null,
  localAiSuggestionCount: 0,
  duplicateCount: 0,
  quarantineCount: 1,
  revision: 1,
}

const entityOrigins = [
  {
    sourceId,
    sourceDisplayName: 'Synthetic local note',
    sourceSha256: 'a'.repeat(64),
    segmentId,
    segmentIndex: 0,
    segmentLocator: '{"kind":"paragraph","index":0}',
    sourceSpanStart: 5,
    sourceSpanEnd: 31,
    extractionRunId,
    extractorKind: 'DETERMINISTIC',
    extractorName: 'synthetic-entity-compiler',
    extractorVersion: '1.0.0',
    originKind: 'DETERMINISTIC',
    observedAtUs: 1_750_000_000_123_456,
    confidenceMicros: 980_000,
    explanation: 'Synthetic deterministic observation from the exact segment.',
  },
  {
    sourceId,
    sourceDisplayName: 'Synthetic local note',
    sourceSha256: 'a'.repeat(64),
    segmentId: secondSegmentId,
    segmentIndex: 1,
    segmentLocator: '{"kind":"paragraph","index":1}',
    sourceSpanStart: null,
    sourceSpanEnd: null,
    extractionRunId: null,
    extractorKind: null,
    extractorName: null,
    extractorVersion: null,
    originKind: 'USER_INPUT',
    observedAtUs: 1_750_000_000_223_456,
    confidenceMicros: 1_000_000,
    explanation: 'Synthetic direct user-input origin for the whole segment.',
  },
] as const

const entity = {
  entityId,
  entityType: 'EMAIL',
  displayValue: 'l•••@example.invalid',
  sensitivity: 'SENSITIVE',
  reviewState: 'UNREVIEWED',
  temporalState: 'UNKNOWN',
  searchPolicy: 'REQUIRE_APPROVAL',
  transmissionPolicy: 'REQUIRE_EACH_APPROVAL',
  confidenceMicros: 980_000,
  provenanceLabel: 'Local source · segment 1',
  origins: entityOrigins,
  originsTruncated: false,
  revision: 1,
} as const

function storageValues(storage: Storage): string[] {
  return Array.from({ length: storage.length }, (_, index) =>
    storage.getItem(storage.key(index) ?? '') ?? '',
  )
}

describe('native Phase 3 UI flow', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
    usePhase3WorkflowStore.getState().reset()
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('submits pasted text locally, then releases it without browser persistence', async () => {
    const privateInput = 'Authorised ephemeral source 7f4d8a'
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_intake_paste') return response(receipt)
      throw new Error('Unexpected native command')
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <IntakePage />
      </MemoryRouter>,
    )

    const input = screen.getByRole('textbox', { name: 'Local source text' })
    await user.type(input, privateInput)
    await user.click(screen.getByRole('button', { name: 'Extract locally' }))

    await waitFor(() => expect(input).toHaveValue(''))
    expect(
      screen.getAllByRole('link', { name: /Review candidates/ })[0],
    ).toHaveAttribute('href', '/audits/new/entities')
    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('core_intake_paste', {
      request: expect.objectContaining({
        profileId,
        content: privateInput,
        consentConfirmed: true,
        retainRawSource: false,
        semanticEnrichmentEnabled: true,
      }),
    })
    expect(storageValues(localStorage).join(' ')).not.toContain(privateInput)
    expect(storageValues(sessionStorage).join(' ')).not.toContain(privateInput)
    expect(usePhase3WorkflowStore.getState()).toMatchObject({
      profileId,
      sourceId,
    })
  })

  it('requires an explicitly named profile before intake', () => {
    render(
      <MemoryRouter>
        <IntakePage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', {
      name: 'Choose where this audit belongs',
    })).toBeVisible()
    expect(screen.getByRole('link', {
      name: /Create or select profile/,
    })).toHaveAttribute('href', '/audits/new')
    expect(screen.queryByRole('textbox', {
      name: 'Local source text',
    })).not.toBeInTheDocument()
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('sends one allowed browser-selected file with exact integrity metadata and no path', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({ ...receipt, sourceKind: 'FILE', quarantineCount: 0 }),
    )
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <IntakePage />
      </MemoryRouter>,
    )
    const input = screen.getByLabelText(
      'Choose one local intake file',
    ) as HTMLInputElement

    await user.upload(
      input,
      new File(['synthetic file note'], 'local_note.txt', {
        type: 'text/plain',
      }),
    )

    expect(await screen.findByText('Accepted')).toBeVisible()
    const call = invokeMock.mock.calls.find(
      ([command]) => command === 'core_intake_file',
    )
    expect(call).toBeDefined()
    expect(call?.[1]).toEqual({
      request: expect.objectContaining({
        profileId,
        displayName: 'local_note.txt',
        declaredMediaType: 'text/plain',
        expectedSizeBytes: 19,
        expectedSha256:
          'b1e681df3c7efa764891e037d07d02160c0f47567f9ea8d1d4278e9bf4dc9029',
        contentBase64: 'c3ludGhldGljIGZpbGUgbm90ZQ==',
        consentConfirmed: true,
        retainRawSource: false,
        semanticEnrichmentEnabled: true,
      }),
    })
    expect(call?.[1].request).not.toHaveProperty('path')
    expect(input).toHaveValue('')
  })

  it('reuses a file request key after response loss and rotates it for new work', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    let fileCalls = 0
    invokeMock.mockImplementation(async (command: string) => {
      if (command !== 'core_intake_file') throw new Error('Unexpected command')
      fileCalls += 1
      if (fileCalls === 1) {
        throw new Error('Simulated transport loss after local commit')
      }
      return response({ ...receipt, sourceKind: 'FILE', quarantineCount: 0 })
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <IntakePage />
      </MemoryRouter>,
    )
    const input = screen.getByLabelText(
      'Choose one local intake file',
    ) as HTMLInputElement
    const firstFile = () =>
      new File(['first synthetic note'], 'first_note.txt', {
        type: 'text/plain',
      })
    const secondFile = () =>
      new File(['second synthetic note'], 'second_note.txt', {
        type: 'text/plain',
      })

    await user.upload(input, firstFile())
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The selected file could not be accepted or parsed.',
    )
    await user.upload(input, firstFile())
    await waitFor(() => expect(fileCalls).toBe(2))
    await user.upload(input, secondFile())
    await waitFor(() => expect(fileCalls).toBe(3))
    await user.upload(input, secondFile())
    await waitFor(() => expect(fileCalls).toBe(4))

    const keys = invokeMock.mock.calls
      .filter(([command]) => command === 'core_intake_file')
      .map(([, arguments_]) => arguments_.request.idempotencyKey as string)
    expect(keys[1]).toBe(keys[0])
    expect(keys[2]).not.toBe(keys[1])
    expect(keys[3]).not.toBe(keys[2])
  })

  it('loads masked entities and applies invariant-safe review policies', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_review_entities') {
        return response({
          profileId,
          entities: [entity],
          quarantineCount: 1,
          hasMore: false,
        })
      }
      if (command === 'core_decide_entity') {
        return response({
          ...entity,
          sensitivity: 'HIGHLY_SENSITIVE',
          reviewState: 'CONFIRMED',
          revision: 2,
        })
      }
      throw new Error('Unexpected native command')
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <EntitiesPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(entity.displayValue)).toBeVisible()
    const originsPanel = screen
      .getByRole('heading', { level: 2, name: 'Source origins' })
      .closest('section')
    expect(originsPanel).not.toBeNull()
    const exactOrigins = within(originsPanel as HTMLElement)
    expect(exactOrigins.getAllByTestId('entity-origin-card')).toHaveLength(2)
    expect(exactOrigins.getAllByText('Synthetic local note')).toHaveLength(2)
    expect(exactOrigins.getAllByText(sourceId)).toHaveLength(2)
    expect(exactOrigins.getAllByText('a'.repeat(64))).toHaveLength(2)
    expect(exactOrigins.getByText(segmentId)).toBeVisible()
    expect(exactOrigins.getByText(secondSegmentId)).toBeVisible()
    expect(
      exactOrigins.getByText('DETERMINISTIC · synthetic-entity-compiler v1.0.0'),
    ).toBeVisible()
    expect(exactOrigins.getAllByText('None · direct origin')).toHaveLength(2)
    expect(exactOrigins.getByText(/1750000000123456 µs/)).toBeVisible()
    const editor = screen.getByRole('heading', {
      level: 2,
      name: 'Decision controls',
    }).closest('section')
    expect(editor).not.toBeNull()
    const scoped = within(editor as HTMLElement)
    await user.selectOptions(
      await scoped.findByRole('combobox', { name: 'Sensitivity' }),
      'HIGHLY_SENSITIVE',
    )
    expect(scoped.getByRole('combobox', { name: 'Search policy' })).toHaveValue(
      'REQUIRE_APPROVAL',
    )
    expect(
      scoped.getByRole('combobox', { name: 'Transmission policy' }),
    ).toHaveValue('REQUIRE_EACH_APPROVAL')
    await user.click(scoped.getByRole('button', { name: 'Apply decision' }))

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('core_decide_entity', {
        request: expect.objectContaining({
          profileId,
          entityId,
          expectedRevision: 1,
          decisionType: 'CONFIRM',
          reviewState: 'CONFIRMED',
          sensitivity: 'HIGHLY_SENSITIVE',
          searchPolicy: 'REQUIRE_APPROVAL',
          transmissionPolicy: 'REQUIRE_EACH_APPROVAL',
        }),
      }),
    )
    expect(await screen.findAllByText('Highly sensitive')).not.toHaveLength(0)
  })

  it('bulk-applies shared policy while preserving each unresolved sensitivity', async () => {
    const usernameEntity = {
      ...entity,
      entityId: secondEntityId,
      entityType: 'USERNAME',
      displayValue: 'synthetic_handle',
      sensitivity: 'PUBLIC',
    } as const
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)
    invokeMock.mockImplementation(
      async (command: string, arguments_: { request: Record<string, unknown> }) => {
        if (command === 'core_review_entities') {
          return response({
            profileId,
            entities: [entity, usernameEntity],
            quarantineCount: 0,
            hasMore: false,
          })
        }
        if (command === 'core_decide_entity') {
          const source =
            arguments_.request.entityId === entityId ? entity : usernameEntity
          return response({
            ...source,
            reviewState: arguments_.request.reviewState,
            temporalState: arguments_.request.temporalState,
            searchPolicy: arguments_.request.searchPolicy,
            transmissionPolicy: arguments_.request.transmissionPolicy,
            sensitivity: arguments_.request.sensitivity,
            revision: 2,
          })
        }
        throw new Error('Unexpected native command')
      },
    )
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <EntitiesPage />
      </MemoryRouter>,
    )

    await user.click(
      await screen.findByRole('button', { name: 'Apply to 2 unresolved' }),
    )

    await waitFor(() =>
      expect(
        invokeMock.mock.calls.filter(([command]) => command === 'core_decide_entity'),
      ).toHaveLength(2),
    )
    const requests = invokeMock.mock.calls
      .filter(([command]) => command === 'core_decide_entity')
      .map(([, arguments_]) => arguments_.request)
    expect(requests).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          entityId,
          reviewState: 'CONFIRMED',
          sensitivity: 'SENSITIVE',
          temporalState: 'CURRENT',
          searchPolicy: 'ALLOW',
          transmissionPolicy: 'POLICY_CONTROLLED',
        }),
        expect.objectContaining({
          entityId: secondEntityId,
          reviewState: 'CONFIRMED',
          sensitivity: 'PUBLIC',
          temporalState: 'CURRENT',
          searchPolicy: 'ALLOW',
          transmissionPolicy: 'POLICY_CONTROLLED',
        }),
      ]),
    )
    expect(
      await screen.findByRole('button', { name: 'Apply to 0 unresolved' }),
    ).toBeDisabled()
  })

  it('loads every stored exact origin beyond the bounded entity summary', async () => {
    const initialOrigins = Array.from({ length: 32 }, (_, index) => ({
      ...entityOrigins[0],
      explanation: `Synthetic bounded origin ${index + 1}.`,
    }))
    const finalOrigin = {
      ...entityOrigins[1],
      explanation: 'Synthetic final paginated origin.',
    }
    const allOrigins = [...initialOrigins, finalOrigin]
    const truncatedEntity = {
      ...entity,
      origins: initialOrigins,
      originsTruncated: true,
    }
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)
    invokeMock.mockImplementation(async (command: string, arguments_) => {
      if (command === 'core_review_entities') {
        return response({
          profileId,
          entities: [truncatedEntity],
          quarantineCount: 0,
          hasMore: false,
        })
      }
      if (command === 'core_list_entity_origins') {
        const offset = Number(arguments_.request.offset)
        const page = allOrigins.slice(offset, offset + 12)
        return response({
          profileId,
          entityId,
          offset,
          limit: 12,
          origins: page,
          total: 33,
          hasMore: offset + page.length < 33,
        })
      }
      throw new Error('Unexpected native command')
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <EntitiesPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(truncatedEntity.displayValue)).toBeVisible()
    const originsPanel = screen
      .getByRole('heading', { level: 2, name: 'Source origins' })
      .closest('section')
    expect(originsPanel).not.toBeNull()
    const exactOrigins = within(originsPanel as HTMLElement)
    expect(exactOrigins.getAllByTestId('entity-origin-card')).toHaveLength(32)

    await user.click(
      exactOrigins.getByRole('button', { name: 'Inspect all stored origins' }),
    )

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('core_list_entity_origins', {
        request: { profileId, entityId, offset: 0, limit: 12 },
      }),
    )
    expect(exactOrigins.getAllByTestId('entity-origin-card')).toHaveLength(12)
    await user.click(
      exactOrigins.getByRole('button', { name: 'Load next exact origins' }),
    )
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('core_list_entity_origins', {
        request: { profileId, entityId, offset: 12, limit: 12 },
      }),
    )
    expect(exactOrigins.getAllByTestId('entity-origin-card')).toHaveLength(24)
    await user.click(
      exactOrigins.getByRole('button', { name: 'Load next exact origins' }),
    )
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('core_list_entity_origins', {
        request: { profileId, entityId, offset: 24, limit: 12 },
      }),
    )
    expect(
      await exactOrigins.findByText('Synthetic final paginated origin.'),
    ).toBeVisible()
    expect(exactOrigins.getAllByTestId('entity-origin-card')).toHaveLength(33)
    expect(exactOrigins.getByText('All 33 stored exact origins are loaded.')).toBeVisible()
  })

  it('records policy-only edits without falsely reconfirming an entity', async () => {
    const confirmedEntity = {
      ...entity,
      reviewState: 'CONFIRMED',
    } as const
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_review_entities') {
        return response({
          profileId,
          entities: [confirmedEntity],
          quarantineCount: 0,
          hasMore: false,
        })
      }
      if (command === 'core_decide_entity') {
        return response({
          ...confirmedEntity,
          temporalState: 'HISTORICAL',
          revision: 2,
        })
      }
      throw new Error('Unexpected native command')
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <EntitiesPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(confirmedEntity.displayValue)).toBeVisible()
    const editor = (await screen.findByRole('heading', {
      level: 2,
      name: 'Decision controls',
    })).closest('section')
    expect(editor).not.toBeNull()
    const scoped = within(editor as HTMLElement)
    const applyDecision = scoped.getByRole('button', {
      name: 'Apply decision',
    })
    expect(applyDecision).toBeDisabled()
    await user.click(applyDecision)
    expect(invokeMock).not.toHaveBeenCalledWith(
      'core_decide_entity',
      expect.anything(),
    )
    await user.selectOptions(
      scoped.getByRole('combobox', { name: 'Temporal state' }),
      'HISTORICAL',
    )
    expect(applyDecision).toBeEnabled()
    await user.click(applyDecision)

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('core_decide_entity', {
        request: expect.objectContaining({
          entityId,
          reviewState: 'CONFIRMED',
          temporalState: 'HISTORICAL',
          decisionType: 'POLICY_CHANGE',
        }),
      }),
    )
  })

  it('renders the persisted native graph with source-linked evidence', async () => {
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(
      response({
        profileId,
        nodes: [
          {
            nodeId: entityId,
            nodeType: 'PERSON',
            displayLabel: 'Synthetic Person',
            sensitivity: 'PUBLIC',
            entityId,
          },
          {
            nodeId: secondEntityId,
            nodeType: 'USERNAME',
            displayLabel: '@synthetic_handle',
            sensitivity: 'SENSITIVE',
            entityId: secondEntityId,
          },
        ],
        edges: [
          {
            edgeId,
            fromNodeId: entityId,
            toNodeId: secondEntityId,
            edgeType: 'USED',
            confidenceMicros: 900_000,
            originType: 'DETERMINISTIC_RULE',
            explanation: 'Synthetic relationship extracted locally.',
            supportCount: 1,
            contradictionCount: 0,
            evidence: [
              {
                sourceId,
                segmentOrdinal: 0,
                sourceSpanStart: 0,
                sourceSpanEnd: 9,
                disposition: 'SUPPORTS',
                confidenceMicros: 900_000,
                visibility: 'PUBLIC_PSEUDONYMOUS',
                observedAtUs: 1_750_000_000_000_000,
                originType: 'DETERMINISTIC_RULE',
                explanation: 'Synthetic source observation.',
              },
            ],
            evidenceTruncated: false,
          },
        ],
        truncated: false,
      }),
    )

    render(
      <MemoryRouter>
        <GraphPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Native encrypted graph')).toBeVisible()
    expect(screen.getByText('Synthetic Person')).toBeInTheDocument()
    expect(screen.getByText('Synthetic relationship extracted locally.')).toBeVisible()
    expect(screen.getByText('1 supporting · 0 contradicting')).toBeVisible()
    expect(invokeMock).toHaveBeenCalledWith('core_graph_snapshot', {
      request: { profileId, maxNodes: 200, includeSensitive: true },
    })

    act(() => usePhase3WorkflowStore.getState().reset())
    expect(screen.getByText('No active profile')).toBeVisible()
    expect(
      screen.queryByText('Synthetic relationship extracted locally.'),
    ).not.toBeInTheDocument()
  })
})
