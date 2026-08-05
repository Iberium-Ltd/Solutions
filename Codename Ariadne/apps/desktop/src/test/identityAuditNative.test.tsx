/** Exercises terminal audit review and export using a complete synthetic result. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { IdentityAuditPage } from '../pages/IdentityAuditPage'
import { completedAuditDetail } from './identityAuditFixture'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const requestId = '99999999-9999-4999-8999-999999999999'

describe('terminal native identity audit workflow', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:synthetic-audit-package'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    invokeMock.mockResolvedValue({ requestId, data: completedAuditDetail })
    usePhase3WorkflowStore.getState().setProfileId(completedAuditDetail.profileId)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(globalThis, 'isTauri')
    usePhase3WorkflowStore.getState().reset()
  })

  it('opens committed results and downloads the final cited package', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={[`/identity/audits/${completedAuditDetail.audit.auditId}`]}>
        <Routes>
          <Route path="/identity/audits/:auditId" element={<IdentityAuditPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', {
      name: completedAuditDetail.audit.name,
    })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Finish this audit' })).toBeVisible()
    expect(screen.getByText('Ready to export')).toBeVisible()

    await user.click(screen.getByRole('button', {
      name: 'Generate and download',
    }))

    expect(await screen.findByText(
      `ariadne-audit-${completedAuditDetail.audit.auditId}.md`,
    )).toBeVisible()
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith(
      'core_get_identity_audit',
      { request: {
        profileId: completedAuditDetail.profileId,
        auditId: completedAuditDetail.audit.auditId,
        maximumTasks: 4,
      } },
    ))
  })

  it('offers recovery instead of an endless loader when a retained run is rejected', async () => {
    const user = userEvent.setup()
    invokeMock
      .mockRejectedValueOnce(new Error('invalid retained projection'))
      .mockResolvedValue({ requestId, data: completedAuditDetail })

    render(
      <MemoryRouter initialEntries={[`/identity/audits/${completedAuditDetail.audit.auditId}`]}>
        <Routes>
          <Route path="/identity/audits/:auditId" element={<IdentityAuditPage />} />
          <Route path="/people" element={<h1>People recovery route</h1>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Audit could not be opened' })).toBeVisible()
    expect(screen.queryByText('Loading committed progress')).not.toBeInTheDocument()
    expect(screen.getByText('Committed progress is still safe')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry opening' }))
    expect(await screen.findByRole('heading', {
      name: completedAuditDetail.audit.name,
    })).toBeVisible()
    expect(invokeMock).toHaveBeenCalledTimes(2)
  })

  it('recovers missing local AI analysis from a reopened partial run', async () => {
    const partialWithoutAnalysis = {
      ...completedAuditDetail,
      audit: {
        ...completedAuditDetail.audit,
        state: 'PARTIAL' as const,
        stage: 'COMPLETE' as const,
        stopReason: 'REQUEST_BUDGET_EXHAUSTED' as const,
      },
      aiAnalysis: null,
    }
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_identity_audit') {
        return { requestId, data: partialWithoutAnalysis }
      }
      if (command === 'core_get_local_ai_settings') {
        return {
          requestId,
          data: {
            enabled: true,
            provider: 'OLLAMA',
            endpoint: 'http://127.0.0.1:11434',
            selectedModel: completedAuditDetail.audit.selectedModel,
            revision: 2,
          },
        }
      }
      if (command === 'core_test_local_ai_connection') {
        return {
          requestId,
          data: {
            status: 'AVAILABLE',
            reachable: true,
            modelCount: 1,
            selectedModelAvailable: true,
          },
        }
      }
      if (command === 'core_execute_identity_audit_batch') {
        return { requestId, data: completedAuditDetail }
      }
      throw new Error(`Unexpected command ${command}`)
    })

    render(
      <MemoryRouter initialEntries={[`/identity/audits/${completedAuditDetail.audit.auditId}`]}>
        <Routes>
          <Route path="/identity/audits/:auditId" element={<IdentityAuditPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', {
      name: completedAuditDetail.audit.name,
    })).toBeVisible()
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith(
      'core_execute_identity_audit_batch',
      { request: {
        profileId: completedAuditDetail.profileId,
        auditId: completedAuditDetail.audit.auditId,
        maximumTasks: 1,
      } },
    ))
    expect(await screen.findByText('Ready to export')).toBeVisible()
  })

  it('does not analyse with a merely reachable but unavailable selected model', async () => {
    const partialWithoutAnalysis = {
      ...completedAuditDetail,
      audit: {
        ...completedAuditDetail.audit,
        state: 'PARTIAL' as const,
        stage: 'COMPLETE' as const,
        stopReason: 'REQUEST_BUDGET_EXHAUSTED' as const,
      },
      aiAnalysis: null,
    }
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'core_get_identity_audit') {
        return { requestId, data: partialWithoutAnalysis }
      }
      if (command === 'core_get_local_ai_settings') {
        return {
          requestId,
          data: {
            enabled: true,
            provider: 'OLLAMA',
            endpoint: 'http://127.0.0.1:11434',
            selectedModel: completedAuditDetail.audit.selectedModel,
            revision: 2,
          },
        }
      }
      if (command === 'core_test_local_ai_connection') {
        return {
          requestId,
          data: {
            status: 'AVAILABLE',
            reachable: true,
            modelCount: 1,
            selectedModelAvailable: false,
          },
        }
      }
      throw new Error(`Unexpected command ${command}`)
    })

    render(
      <MemoryRouter initialEntries={[`/identity/audits/${completedAuditDetail.audit.auditId}`]}>
        <Routes>
          <Route path="/identity/audits/:auditId" element={<IdentityAuditPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The audit stopped safely before its next commit.',
    )
    expect(invokeMock).not.toHaveBeenCalledWith(
      'core_execute_identity_audit_batch',
      expect.anything(),
    )
  })
})
