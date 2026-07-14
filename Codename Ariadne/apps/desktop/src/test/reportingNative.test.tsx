import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { ReportsPage } from '../pages/ReportsPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '11111111-1111-4111-8111-111111111111'
const profileId = '22222222-2222-4222-8222-222222222222'
const baselineRunId = '33333333-3333-4333-8333-333333333333'
const currentRunId = '44444444-4444-4444-8444-444444444444'
const generatedAtUs = 1_783_900_000_000_000
const jsonContent = '{"schema":"synthetic"}'
const jsonHash = '06c9132b3fe7d5b38e6df5944ea52d26e49a63ae1abdf9e505f216baccb60efc'
const markdownHash = '4b16b59922291491357555c499f0f021c54310928afbe524528b30f01a1d73bb'

const response = (data: unknown) => ({ requestId, data })
const runs = [
  {
    runId: currentRunId,
    sequence: 2,
    capturedAtUs: generatedAtUs - 1_000,
    runState: 'COMPLETED',
    findingCount: 1,
    providerCount: 1,
  },
  {
    runId: baselineRunId,
    sequence: 1,
    capturedAtUs: generatedAtUs - 2_000,
    runState: 'COMPLETED',
    findingCount: 0,
    providerCount: 1,
  },
] as const

describe('native local reporting UI', () => {
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

  it('generates a redacted canonical artifact for a selected persisted pair', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockImplementation((command: string) => {
      if (command === 'core_list_phase6_audit_runs') {
        return Promise.resolve(response({ profileId, runs, hasMore: false }))
      }
      if (command === 'core_generate_local_report') {
        return Promise.resolve(
          response({
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
              mode: 'REDACTED',
              content: jsonContent,
            },
            manifest: {
              schema: 'ariadne.local-report',
              version: 1,
              mode: 'REDACTED',
              generatedAtUs,
              fullExportApprovalId: null,
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
          }),
        )
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`))
    })

    render(
      <MemoryRouter>
        <ReportsPage />
      </MemoryRouter>,
    )

    await screen.findByRole('heading', { name: 'Choose scope and privacy mode' })
    await user.selectOptions(screen.getByLabelText('Artifact'), 'JSON')
    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    expect(await screen.findByRole('heading', { name: 'report.json' })).toBeVisible()
    expect(screen.getByText(jsonContent)).toBeVisible()
    expect(screen.getAllByText('Redacted')).toSatisfy(
      (items: HTMLElement[]) => items.some((item) => item.classList.contains('badge')),
    )
    expect(screen.getByRole('button', { name: 'Save local file' })).toBeEnabled()
    await waitFor(() => {
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
  })

  it('requires an explicit checkbox before full report generation', async () => {
    const user = userEvent.setup()
    usePhase3WorkflowStore.getState().setProfileId(profileId)
    invokeMock.mockResolvedValue(response({ profileId, runs, hasMore: false }))

    render(
      <MemoryRouter>
        <ReportsPage />
      </MemoryRouter>,
    )

    await screen.findByRole('heading', { name: 'Choose scope and privacy mode' })
    await user.selectOptions(screen.getByLabelText('Privacy mode'), 'FULL_EXPLICIT')
    expect(screen.getByRole('button', { name: 'Generate report' })).toBeDisabled()
    await user.click(screen.getByText('Include sensitive local text'))
    expect(screen.getByRole('button', { name: 'Generate report' })).toBeEnabled()
  })
})
