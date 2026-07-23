/** Proves public-search responses and exact source URLs are parsed defensively. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  capturePublicDiscovery,
  publicDiscoveryBoundaryParsers,
  searchPublicDiscovery,
} from '../app/publicDiscoveryBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const response = (data: unknown) => ({ requestId, data })
const successful = {
  provider: 'DUCKDUCKGO_HTML',
  state: 'SUCCEEDED',
  reason: 'COMPLETE',
  results: [
    {
      provider: 'DUCKDUCKGO_HTML',
      rank: 1,
      title: 'Synthetic public result',
      url: 'https://public.example.invalid/profile',
      snippet: 'Reserved-domain synthetic result.',
      sourceId: null,
    },
  ],
  totalEstimate: 1,
  rateLimitRemaining: null,
  truncated: false,
  externalRequestMade: true,
  authorizationConfirmed: true,
  humanReviewRequired: true,
}
const captured = {
  profileId: '22222222-2222-4222-8222-222222222222',
  findingId: '33333333-3333-4333-8333-333333333333',
  artifactId: '44444444-4444-4444-8444-444444444444',
  provider: 'DUCKDUCKGO_HTML',
  rank: 1,
  sourceId: null,
  url: 'https://public.example.invalid/profile/syn-9037',
  urlSha256: 'c39f925f2a181e06b71b88a5d86cd6814f732cf7ae4324ae661236729ae8f605',
  queryReference: `mq_${'a'.repeat(64)}`,
  capturedAtUs: 1_700_000_000_000_000,
  evidenceKind: 'URL_REFERENCE',
  encryptedAtRest: true,
  localOnly: true,
  deduplicated: false,
}

describe('public discovery native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts an exact cited success envelope', () => {
    expect(publicDiscoveryBoundaryParsers.result(response(successful))).toEqual(
      successful,
    )
  })

  it('rejects contradictory state, duplicate URLs, and credentials', () => {
    expect(() =>
      publicDiscoveryBoundaryParsers.result(
        response({ ...successful, state: 'FAILED' }),
      ),
    ).toThrow('search response is invalid')
    expect(() =>
      publicDiscoveryBoundaryParsers.result(
        response({
          ...successful,
          results: [successful.results[0], successful.results[0]],
        }),
      ),
    ).toThrow('search response is invalid')
    expect(() =>
      publicDiscoveryBoundaryParsers.result(
        response({
          ...successful,
          results: [
            {
              ...successful.results[0],
              url: 'https://user:key@public.example.invalid/profile',
            },
          ],
        }),
      ),
    ).toThrow('search response is invalid')
  })

  it('dispatches only the route-specific command and binds provider/consent', async () => {
    invokeMock.mockResolvedValueOnce(response(successful))
    const request = {
      provider: 'DUCKDUCKGO_HTML' as const,
      query: 'SYNTHETIC_DISCOVERY_QUERY_9037',
      authorizedSelfAudit: true,
      maxResults: 10,
    }

    await expect(searchPublicDiscovery(request)).resolves.toEqual(successful)
    expect(invokeMock).toHaveBeenCalledWith('core_search_public_discovery', {
      request,
    })
  })

  it('accepts and dispatches an exact, source-bound capture', async () => {
    expect(
      publicDiscoveryBoundaryParsers.captureResult(response(captured)),
    ).toEqual(captured)
    invokeMock.mockResolvedValueOnce(response(captured))
    const request = {
      profileId: captured.profileId,
      provider: captured.provider as 'DUCKDUCKGO_HTML',
      query: 'SYNTHETIC_CAPTURE_QUERY_9037',
      rank: captured.rank,
      title: 'Synthetic capture fixture 9037',
      url: captured.url,
      snippet: 'Reserved synthetic capture fixture.',
      sourceId: null,
      capturedAtUs: captured.capturedAtUs,
      authorizedSelfAudit: true as const,
    }

    await expect(capturePublicDiscovery(request)).resolves.toEqual(captured)
    expect(invokeMock).toHaveBeenCalledWith('core_capture_public_discovery', {
      request,
    })
  })

  it('rejects capture mutation, missing provenance, and an unbound URL hash', async () => {
    expect(() =>
      publicDiscoveryBoundaryParsers.captureResult(
        response({ ...captured, evidenceKind: 'HTML' }),
      ),
    ).toThrow('capture response is invalid')
    expect(() =>
      publicDiscoveryBoundaryParsers.captureResult(
        response({ ...captured, artifactId: undefined }),
      ),
    ).toThrow('capture response is invalid')

    invokeMock.mockResolvedValueOnce(
      response({ ...captured, urlSha256: 'b'.repeat(64) }),
    )
    await expect(
      capturePublicDiscovery({
        profileId: captured.profileId,
        provider: 'DUCKDUCKGO_HTML',
        query: 'SYNTHETIC_CAPTURE_QUERY_9037',
        rank: 1,
        title: 'Synthetic capture fixture 9037',
        url: captured.url,
        snippet: null,
        sourceId: null,
        capturedAtUs: captured.capturedAtUs,
        authorizedSelfAudit: true,
      }),
    ).rejects.toThrow('capture response binding is invalid')
  })

  it('refuses non-canonical, unbounded, or unconsented response bindings', async () => {
    await expect(
      searchPublicDiscovery({
        provider: 'GITHUB_USERS',
        query: '  padded query  ',
        authorizedSelfAudit: true,
        maxResults: 10,
      }),
    ).rejects.toThrow('search request is invalid')

    invokeMock.mockResolvedValueOnce(response(successful))
    await expect(
      searchPublicDiscovery({
        provider: 'DUCKDUCKGO_HTML',
        query: 'SYNTHETIC_DISCOVERY_QUERY_9037',
        authorizedSelfAudit: false,
        maxResults: 10,
      }),
    ).rejects.toThrow('response binding is invalid')
  })
})
