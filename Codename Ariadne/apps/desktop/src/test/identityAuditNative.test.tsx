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
})
