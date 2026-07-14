import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToolsPage } from '../pages/ToolsPage'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

describe('native discovery console', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    invokeMock.mockReset()
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
  })

  it('exposes public, advanced-query, breach, composed-plan, and manual-portal surfaces', async () => {
    const user = userEvent.setup()
    render(<ToolsPage />)

    expect(screen.getByRole('heading', { level: 1, name: 'Discovery Console' })).toBeVisible()
    expect(screen.getByText('Search one public provider')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: /query composer/i }))
    expect(screen.getByText('Advanced search composer')).toBeVisible()
    await user.type(screen.getByLabelText('Core query'), 'synthetic alias')
    await user.type(screen.getByLabelText('Only site or domain'), 'example.invalid')
    await user.click(screen.getByLabelText(/I authorise this browser search/i))
    expect(screen.getByText('synthetic alias site:example.invalid')).toBeVisible()
    expect(screen.getAllByRole('link', { name: /^Open$/i })[0]).toHaveAttribute('href', expect.stringContaining('https://'))

    await user.click(screen.getByRole('tab', { name: /breach exposure/i }))
    expect(screen.getByText('Have I Been Pwned v3')).toBeVisible()
    expect(screen.getByLabelText(/HIBP API key/i)).toHaveAttribute('type', 'password')

    await user.click(screen.getByRole('tab', { name: /plan & combine/i }))
    expect(screen.getByText('Compose an investigation')).toBeVisible()
    expect(screen.getByRole('button', { name: /compile without executing/i })).toBeVisible()
    await user.type(screen.getByLabelText('Identifier 1 value'), 'synthetic_handle')

    await user.click(screen.getByRole('tab', { name: /public search/i }))
    await user.click(screen.getByRole('tab', { name: /plan & combine/i }))
    expect(screen.getByLabelText('Identifier 1 value')).toHaveValue('synthetic_handle')

    await user.click(screen.getByRole('tab', { name: /manual portals/i }))
    expect(screen.getByRole('heading', { name: 'DeHashed' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Spokeo' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Intelius' })).toBeVisible()
    expect(screen.getAllByRole('link', { name: /open official portal/i }).length).toBeGreaterThan(4)
    expect(invokeMock).not.toHaveBeenCalled()
  })
})
