import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import { usePrototypeStore } from '../app/prototypeStore'

describe('application accessibility smoke', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/dashboard?fixture=standard')
    usePrototypeStore.setState({
      sidebarCollapsed: false,
      simulationPaused: false,
      reducedMotion: false,
      selectedTool: 'Username Sweep',
      transmissionMode: 'local',
    })
  })

  it('exposes one labelled main landmark and a working skip target', async () => {
    render(<App />)
    const heading = await screen.findByRole('heading', {
      level: 1,
      name: 'Mission Control',
    }, { timeout: 5_000 })
    const main = screen.getByRole('main')

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(main).toHaveAttribute('id', 'main-content')
    expect(main).toHaveAttribute('aria-labelledby', heading.id)
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main-content',
    )
    await waitFor(() => expect(heading).toHaveFocus())
  })

  it('provides accessible names for every rendered button', async () => {
    render(<App />)
    await screen.findByRole(
      'heading',
      { level: 1, name: 'Mission Control' },
      { timeout: 5_000 },
    )

    for (const button of screen.getAllByRole('button')) {
      expect(button).toHaveAccessibleName()
    }
  })

  it('marks the active route and restores heading focus after navigation', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole(
      'heading',
      { level: 1, name: 'Mission Control' },
      { timeout: 5_000 },
    )
    const sidebar = screen.getByRole('complementary', {
      name: 'Primary navigation',
    })

    const toolLink = within(sidebar).getByRole('link', {
      name: 'Discovery Console',
    })
    await user.click(toolLink)

    const toolHeading = await screen.findByRole('heading', {
      level: 1,
      name: 'Tool Console',
    }, { timeout: 5_000 })
    expect(toolLink).toHaveAttribute('aria-current', 'page')
    await waitFor(() => expect(toolHeading).toHaveFocus())
  })
})
