/** Verifies report requests and projections preserve their cited source scope. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  generateLocalReport,
  reportingBoundaryParsers,
} from '../app/reportingBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const baselineRunId = '33333333-3333-4333-8333-333333333333'
const currentRunId = '44444444-4444-4444-8444-444444444444'
const approvalId = '55555555-5555-4555-8555-555555555555'
const jsonContent = '{"schema":"synthetic"}'
const jsonHash = '06c9132b3fe7d5b38e6df5944ea52d26e49a63ae1abdf9e505f216baccb60efc'
const markdownHash = '4b16b59922291491357555c499f0f021c54310928afbe524528b30f01a1d73bb'

function envelope(mode: 'REDACTED' | 'FULL_EXPLICIT' = 'REDACTED') {
  return {
    requestId,
    data: {
      profileId,
      baselineRunId,
      currentRunId,
      localOnly: true,
      artifact: {
        filename: 'report.json',
        mediaType: 'application/json',
        byteCount: 22,
        sha256: jsonHash,
        schema: 'ariadne.local-report',
        version: 1,
        mode,
        content: jsonContent,
      },
      manifest: {
        schema: 'ariadne.local-report',
        version: 1,
        mode,
        generatedAtUs: 1_783_900_000_000_000,
        fullExportApprovalId: mode === 'FULL_EXPLICIT' ? approvalId : null,
        artifacts: [
          {
            filename: 'report.json',
            mediaType: 'application/json',
            byteCount: 22,
            sha256: jsonHash,
          },
          {
            filename: 'report.md',
            mediaType: 'text/markdown; charset=utf-8',
            byteCount: 18,
            sha256: markdownHash,
          },
        ],
      },
    },
  } as const
}

describe('local reporting desktop boundary', () => {
  beforeEach(() => invokeMock.mockReset())

  it('accepts an exact bounded local artifact and two-entry manifest', () => {
    expect(reportingBoundaryParsers.result(envelope())).toMatchObject({
      profileId,
      baselineRunId,
      currentRunId,
      localOnly: true,
      artifact: { filename: 'report.json', byteCount: 22 },
    })
  })

  it('rejects approval, descriptor, and active-field drift', () => {
    expect(() =>
      reportingBoundaryParsers.result({
        ...envelope(),
        data: {
          ...envelope().data,
          manifest: {
            ...envelope().data.manifest,
            fullExportApprovalId: approvalId,
          },
        },
      }),
    ).toThrow('bindings are invalid')

    expect(() =>
      reportingBoundaryParsers.result({
        ...envelope(),
        data: {
          ...envelope().data,
          artifact: { ...envelope().data.artifact, html: '<script />' },
        },
      }),
    ).toThrow('result is invalid')
  })

  it('binds request scope and recomputes the selected artifact hash', async () => {
    invokeMock.mockResolvedValue(envelope())
    await expect(
      generateLocalReport({
        profileId,
        baselineRunId,
        currentRunId,
        artifactFormat: 'JSON',
        mode: 'REDACTED',
        fullExportApprovalId: null,
      }),
    ).resolves.toMatchObject({ artifact: { sha256: jsonHash } })
    expect(invokeMock).toHaveBeenCalledWith('core_generate_local_report', {
      request: {
        profileId,
        baselineRunId,
        currentRunId,
        artifactFormat: 'JSON',
        mode: 'REDACTED',
        fullExportApprovalId: null,
      },
    })
  })

  it('rejects full export without a request-scoped explicit approval UUID', async () => {
    await expect(
      generateLocalReport({
        profileId,
        baselineRunId,
        currentRunId,
        artifactFormat: 'JSON',
        mode: 'FULL_EXPLICIT',
        fullExportApprovalId: null,
      }),
    ).rejects.toThrow('request is invalid')
    expect(invokeMock).not.toHaveBeenCalled()
  })
})
