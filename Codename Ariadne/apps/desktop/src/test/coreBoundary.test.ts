/** Verifies hostile or incompatible core responses are rejected at the webview boundary. */
import { describe, expect, it } from 'vitest'
import { coreBoundaryParsers } from '../app/coreBoundary'

const response = (data: unknown) => ({
  requestId: '11111111-1111-4111-8111-111111111111',
  data,
})

describe('native core boundary parsing', () => {
  it('accepts only the generated capability contract', () => {
    const capabilities = coreBoundaryParsers.capabilities(
      response({
        versions: { contract: 1, schema: 'ariadne-v1', events: 1, core: '0.1.0' },
        transport: 'UNIX_SOCKET',
        cipher: {
          required: 'SQLCIPHER',
          available: true,
          sqliteVersion: '3.53.3',
          cipherVersion: '4.17.0 community',
        },
        features: [
          { key: 'intake', status: 'AVAILABLE' },
          { key: 'identity_compiler', status: 'AVAILABLE' },
          { key: 'entity_review', status: 'AVAILABLE' },
          { key: 'identity_graph', status: 'AVAILABLE' },
          { key: 'evidence', status: 'AVAILABLE' },
          { key: 'attribution', status: 'AVAILABLE' },
          { key: 'audit_comparison', status: 'AVAILABLE' },
          { key: 'remediation', status: 'AVAILABLE' },
        ],
      }),
    )
    expect(capabilities.transport).toBe('UNIX_SOCKET')
    expect(() =>
      coreBoundaryParsers.capabilities(response({ transport: 'REMOTE' })),
    ).toThrow('Core capabilities are invalid')
    expect(() =>
      coreBoundaryParsers.capabilities(
        response({
          ...capabilities,
          features: [{ key: 'unapproved_feature', status: 'AVAILABLE' }],
        }),
      ),
    ).toThrow('Core capabilities are invalid')
  })

  it('rejects impossible session and lifecycle states', () => {
    const session = coreBoundaryParsers.session(
      response({
        lockState: 'LOCKED',
        vaultState: 'LOCKED',
        compatibility: 'COMPATIBLE',
        authenticatedTransport: true,
        sessionExpiresAt: null,
        activeRevealCapabilities: 0,
      }),
    )
    expect(session.lockState).toBe('LOCKED')

    expect(() =>
      coreBoundaryParsers.lifecycle(
        response({
          vaultId: '22222222-2222-4222-8222-222222222222',
          lockState: 'LOCKED',
          vaultState: 'UNLOCKED',
        }),
      ),
    ).toThrow('Core lifecycle response is invalid')
  })
})
