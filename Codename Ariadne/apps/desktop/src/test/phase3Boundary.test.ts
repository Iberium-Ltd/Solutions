import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  loadEntityOrigins,
  loadGraphSnapshot,
  listProfiles,
  phase3BoundaryParsers,
  submitPastedIntake,
} from '../app/phase3Boundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const sourceId = '33333333-3333-4333-8333-333333333333'
const entityId = '44444444-4444-4444-8444-444444444444'
const secondEntityId = '55555555-5555-4555-8555-555555555555'
const edgeId = '66666666-6666-4666-8666-666666666666'
const segmentId = '77777777-7777-4777-8777-777777777777'
const extractionRunId = '88888888-8888-4888-8888-888888888888'

const commandResponse = (data: unknown) => ({ requestId, data })

const intakeReceipt = {
  sourceId,
  profileId,
  state: 'READY_FOR_REVIEW',
  sourceKind: 'PASTED_TEXT',
  segmentCount: 1,
  candidateCount: 2,
  localAiStatus: 'DISABLED',
  localAiProvider: null,
  localAiModel: null,
  localAiEngineVersion: null,
  localAiSuggestionCount: 0,
  duplicateCount: 0,
  quarantineCount: 1,
  revision: 1,
}

const entityOrigin = {
  sourceId,
  sourceDisplayName: 'Synthetic intake note',
  sourceSha256: 'a'.repeat(64),
  segmentId,
  segmentIndex: 0,
  segmentLocator: '{"kind":"paragraph","index":0}',
  sourceSpanStart: 4,
  sourceSpanEnd: 28,
  extractionRunId,
  extractorKind: 'DETERMINISTIC',
  extractorName: 'synthetic-entity-compiler',
  extractorVersion: '1.0.0',
  originKind: 'DETERMINISTIC',
  observedAtUs: 1_750_000_000_123_456,
  confidenceMicros: 950_000,
  explanation: 'Synthetic entity extracted from the exact local segment.',
}

const entitySummary = {
  entityId,
  entityType: 'EMAIL',
  displayValue: 'm•••@example.invalid',
  sensitivity: 'SENSITIVE',
  reviewState: 'UNREVIEWED',
  temporalState: 'UNKNOWN',
  searchPolicy: 'REQUIRE_APPROVAL',
  transmissionPolicy: 'REQUIRE_EACH_APPROVAL',
  confidenceMicros: 950_000,
  provenanceLabel: 'Pasted source · segment 1',
  origins: [entityOrigin],
  originsTruncated: false,
  revision: 1,
}

describe('typed native Phase 3 boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('uses only the fixed paste command and one request wrapper', async () => {
    invokeMock.mockResolvedValue(commandResponse(intakeReceipt))
    const request = {
      idempotencyKey: '11111111-1111-4111-8111-111111111111',
      profileId,
      displayName: 'Pasted local source',
      content: 'synthetic local text',
      consentConfirmed: true,
      retainRawSource: false,
      semanticEnrichmentEnabled: true,
    }

    await expect(submitPastedIntake(request)).resolves.toEqual(intakeReceipt)
    expect(invokeMock).toHaveBeenCalledWith('core_intake_paste', { request })
  })

  it('loads a bounded unique profile list without a request payload', async () => {
    const profiles = [
      {
        profileId,
        displayLabel: 'Synthetic resumable profile',
        purpose: 'Synthetic local review',
        status: 'ACTIVE',
        revision: 1,
      },
    ]
    invokeMock.mockResolvedValue(commandResponse({ profiles, hasMore: false }))

    await expect(listProfiles()).resolves.toEqual({ profiles, hasMore: false })
    expect(invokeMock).toHaveBeenCalledWith('core_list_profiles')

    expect(() =>
      phase3BoundaryParsers.profiles(
        commandResponse({ profiles: [profiles[0], profiles[0]], hasMore: false }),
      ),
    ).toThrow('profile list response is invalid')
  })

  it('accepts only a complete bounded entity review response', () => {
    expect(
      phase3BoundaryParsers.review(
        commandResponse({
          profileId,
          entities: [entitySummary],
          quarantineCount: 1,
          hasMore: false,
        }),
      ),
    ).toMatchObject({ profileId, entities: [entitySummary] })

    expect(() =>
      phase3BoundaryParsers.review(
        commandResponse({
          profileId,
          entities: [entitySummary, entitySummary],
          quarantineCount: 0,
          hasMore: false,
        }),
      ),
    ).toThrow('entity review response is invalid')
  })

  it('rejects unknown response fields and invalid policy enums', () => {
    expect(() =>
      phase3BoundaryParsers.intake(
        commandResponse({ ...intakeReceipt, rawContent: 'must not cross back' }),
      ),
    ).toThrow('intake response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({ ...entitySummary, searchPolicy: 'SEARCH_EVERYWHERE' }),
      ),
    ).toThrow('entity response is invalid')
  })

  it('requires complete, exact, bounded entity origins', () => {
    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({ ...entitySummary, origins: [] }),
      ),
    ).toThrow('entity response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({
          ...entitySummary,
          origins: [
            {
              ...entityOrigin,
              sourceSpanEnd: null,
            },
          ],
        }),
      ),
    ).toThrow('entity response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({
          ...entitySummary,
          origins: [
            {
              ...entityOrigin,
              extractorVersion: null,
            },
          ],
        }),
      ),
    ).toThrow('entity response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({ ...entitySummary, originsTruncated: true }),
      ),
    ).toThrow('entity response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({
          ...entitySummary,
          origins: [{ ...entityOrigin, sourceSha256: 'A'.repeat(64) }],
        }),
      ),
    ).toThrow('entity response is invalid')

    expect(() =>
      phase3BoundaryParsers.entity(
        commandResponse({
          ...entitySummary,
          origins: [{ ...entityOrigin, untrustedContent: 'must not cross' }],
        }),
      ),
    ).toThrow('entity response is invalid')
  })

  it('loads a bounded scope-bound entity origin page', async () => {
    const request = { profileId, entityId, offset: 32, limit: 12 }
    const page = {
      ...request,
      origins: [entityOrigin],
      total: 33,
      hasMore: false,
    }
    invokeMock.mockResolvedValue(commandResponse(page))

    await expect(loadEntityOrigins(request)).resolves.toEqual(page)
    expect(invokeMock).toHaveBeenCalledWith('core_list_entity_origins', {
      request,
    })

    expect(() =>
      phase3BoundaryParsers.origins(
        commandResponse({ ...page, hasMore: true }),
      ),
    ).toThrow('entity origin page response is invalid')
    expect(() =>
      phase3BoundaryParsers.origins(
        commandResponse({
          ...page,
          origins: Array.from({ length: 101 }, () => entityOrigin),
        }),
      ),
    ).toThrow('entity origin page response is invalid')
    expect(() =>
      phase3BoundaryParsers.origins(
        commandResponse({
          ...page,
          origins: [{ ...entityOrigin, sourceContent: 'must not cross' }],
        }),
      ),
    ).toThrow('entity origin page response is invalid')

    invokeMock.mockResolvedValue(
      commandResponse({ ...page, entityId: secondEntityId }),
    )
    await expect(loadEntityOrigins(request)).rejects.toThrow(
      'entity origin page scope mismatch',
    )
  })

  it('rejects malformed command envelopes', () => {
    expect(() =>
      phase3BoundaryParsers.profile({
        requestId: 'not-a-uuid',
        data: {
          profileId,
          displayLabel: 'Local review profile',
          purpose: 'Authorised local identity review',
          status: 'ACTIVE',
          revision: 1,
        },
      }),
    ).toThrow('command response is invalid')
  })

  it('loads a bounded source-linked graph and rejects dangling edges', async () => {
    const graph = {
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
    }
    invokeMock.mockResolvedValue(commandResponse(graph))
    const request = { profileId, maxNodes: 200, includeSensitive: true }

    await expect(loadGraphSnapshot(request)).resolves.toEqual(graph)
    expect(invokeMock).toHaveBeenCalledWith('core_graph_snapshot', { request })

    expect(() =>
      phase3BoundaryParsers.graph(
        commandResponse({
          ...graph,
          edges: [
            {
              ...graph.edges[0],
              toNodeId: '77777777-7777-4777-8777-777777777777',
            },
          ],
        }),
      ),
    ).toThrow('graph response is invalid')
  })
})
