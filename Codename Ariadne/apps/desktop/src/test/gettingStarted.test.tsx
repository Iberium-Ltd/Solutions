/** Keeps first-run guidance aligned with the actual local workflow and controls. */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { GettingStartedPage } from '../pages/GettingStartedPage'

function renderGuide() {
  return render(
    <MemoryRouter>
      <GettingStartedPage />
    </MemoryRouter>,
  )
}

describe('getting-started guide', () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
  })

  it('explains the complete native workflow and separates demo screens', () => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    renderGuide()

    expect(
      screen.getByRole('heading', { level: 1, name: 'Getting started' }),
    ).toBeVisible()
    const firstSteps = screen.getByRole('list', {
      name: 'Recommended Ariadne workflow',
    })
    expect(within(firstSteps).getByText('Create or unlock the vault')).toBeVisible()
    expect(within(firstSteps).getByText('Add source material in Intake')).toBeVisible()
    expect(within(firstSteps).getByText('Review extracted entities')).toBeVisible()
    expect(within(firstSteps).getByText('Review findings and evidence')).toBeVisible()
    expect(within(firstSteps).getByText('Compare, organise, and report')).toBeVisible()
    expect(
      screen.getByRole('heading', { name: 'Native vault-backed screens' }),
    ).toBeVisible()
    expect(
      screen.getByRole('heading', { name: 'Synthetic demonstration screens' }),
    ).toBeVisible()
    expect(screen.getByRole('link', { name: 'Reports' })).toHaveAttribute(
      'href',
      '/reports',
    )
  })

  it('warns that browser preview cannot open persisted records', () => {
    renderGuide()

    expect(screen.getByText('Browser preview')).toBeVisible()
    expect(
      screen.getByText('You are viewing the browser prototype'),
    ).toBeVisible()
    expect(screen.getByText(/cannot open the encrypted vault/)).toBeVisible()
  })
})
