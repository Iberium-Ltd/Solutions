/** Verifies compiled plans expose exact steps without executing network work. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  compileInvestigationPlan,
  investigationPlanBoundaryParsers,
} from '../app/investigationPlanBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const plan = {
  planId: `plan-${'a'.repeat(24)}`,
  steps: [{
    stepId: 'step-001',
    identifierRef: 'identifier-1',
    identifierKind: 'USERNAME',
    identifierSha256: 'b'.repeat(64),
    provider: 'GITHUB_USERS',
    operation: 'GITHUB_USER_SEARCH',
    executionRoute: '/v1/discovery/public/search',
    transmission: 'DIRECT_PUBLIC_QUERY',
    prerequisites: ['EXPLICIT_SELF_AUDIT_AUTHORIZATION'],
    sequence: 1,
    executesDuringCompilation: false,
    humanReviewRequired: true,
  }],
  notices: [],
  authorizationConfirmed: true,
  deterministic: true,
  executed: false,
}

describe('investigation-plan native boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts a non-executing, digest-only plan', () => {
    expect(investigationPlanBoundaryParsers.plan({ requestId, data: plan })).toEqual(plan)
    expect(JSON.stringify(plan)).not.toContain('synthetic_handle')
  })

  it('rejects execution claims and raw identifier reflection', () => {
    expect(() => investigationPlanBoundaryParsers.plan({
      requestId,
      data: { ...plan, executed: true },
    })).toThrow('plan response is invalid')
    expect(() => investigationPlanBoundaryParsers.plan({
      requestId,
      data: { ...plan, rawIdentifier: 'synthetic_handle' },
    })).toThrow('plan response is invalid')
  })

  it('dispatches a deterministic plan request to its narrow command', async () => {
    invokeMock.mockResolvedValueOnce({ requestId, data: plan })
    const request = {
      identifiers: [{
        identifierRef: 'identifier-1',
        kind: 'USERNAME' as const,
        value: 'synthetic_handle',
      }],
      enabledProviders: ['GITHUB_USERS' as const],
      authorizedSelfAudit: true,
      hibpApiKeyAvailable: false,
      hibpKAnonymityAvailable: false,
      authorizedDirectEmailTransmission: false,
    }
    await expect(compileInvestigationPlan(request)).resolves.toEqual(plan)
    expect(invokeMock).toHaveBeenCalledWith(
      'core_compile_investigation_plan',
      { request },
    )
  })
})
