import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  hibpBoundaryParsers,
  searchHibpAccount,
} from '../app/hibpBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const metadata = {
  sequence: 1,
  operation: 'EMAIL_K_ANONYMITY',
  method: 'GET',
  requestUrl: 'https://haveibeenpwned.com/api/v3/breachedaccountrange/ABCDEF',
  endpointHost: 'haveibeenpwned.com',
  identifierDisclosure: 'PARTIAL_SHA1_PREFIX',
  requestSha256: 'a'.repeat(64),
  httpStatus: 200,
  responseBytes: 128,
  observedAt: '2026-07-14T10:00:00Z',
  retryAfterSeconds: null,
  apiKeySent: true,
  redirectsFollowed: false,
}
const success = {
  provider: 'HAVE_I_BEEN_PWNED_V3',
  providerHomeUrl: 'https://haveibeenpwned.com/',
  apiDocumentationUrl: 'https://haveibeenpwned.com/API/v3',
  attribution: 'Have I Been Pwned',
  license: 'CC BY 4.0',
  mode: 'K_ANONYMITY',
  state: 'SUCCEEDED',
  reason: 'COMPLETE',
  breaches: [{
    name: 'SyntheticBreach',
    sourceUrl: 'https://haveibeenpwned.com/api/v3/breach/SyntheticBreach',
  }],
  requests: [metadata],
  retryAfterSeconds: null,
  externalRequestMade: true,
  authorizationConfirmed: true,
  directTransmissionAuthorized: false,
  humanReviewRequired: true,
}

describe('HIBP native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts exact attribution, breach sources, and request metadata', () => {
    expect(hibpBoundaryParsers.account({ requestId, data: success })).toEqual(success)
  })

  it('rejects credential reflection and contradictory disclosure state', () => {
    expect(() => hibpBoundaryParsers.account({
      requestId,
      data: { ...success, apiKey: '0'.repeat(32) },
    })).toThrow('account response is invalid')
    expect(() => hibpBoundaryParsers.account({
      requestId,
      data: { ...success, directTransmissionAuthorized: true },
    })).toThrow('account response is invalid')
  })

  it('dispatches a one-request key without persisting or returning it', async () => {
    invokeMock.mockResolvedValueOnce({ requestId, data: success })
    const request = {
      email: 'person@example.invalid',
      apiKey: '0'.repeat(32),
      mode: 'K_ANONYMITY' as const,
      authorizedSelfAudit: true,
      authorizedDirectIdentifierTransmission: false,
    }
    await expect(searchHibpAccount(request)).resolves.toEqual(success)
    expect(invokeMock).toHaveBeenCalledWith('core_search_hibp_account', { request })
    expect(JSON.stringify(success)).not.toContain(request.apiKey)
  })
})
