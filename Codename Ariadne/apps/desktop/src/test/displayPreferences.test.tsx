import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import {
  applyDisplayPreferences,
  DEFAULT_DISPLAY_PREFERENCES,
  DISPLAY_PREFERENCES_STORAGE_KEY,
  readDisplayPreferences,
  useDisplayPreferences,
} from '../app/displayPreferences'
import { usePrototypeStore } from '../app/prototypeStore'

const stylesheets = import.meta.glob('../styles/*.css', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>

describe('display preferences', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useDisplayPreferences.setState(DEFAULT_DISPLAY_PREFERENCES)
    usePrototypeStore.setState({
      sidebarCollapsed: false,
      simulationPaused: false,
      reducedMotion: false,
      selectedTool: 'Username Sweep',
      transmissionMode: 'local',
    })
    window.history.replaceState(null, '', '/settings/privacy?fixture=standard')
  })

  afterEach(() => {
    window.localStorage.clear()
    document.documentElement.style.removeProperty('--font-scale')
    delete document.documentElement.dataset.displayPreset
    delete document.documentElement.dataset.fontScale
    delete document.documentElement.dataset.theme
  })

  it('falls back safely when persisted data is missing, malformed, or unsupported', () => {
    expect(readDisplayPreferences({ getItem: () => null })).toEqual(
      DEFAULT_DISPLAY_PREFERENCES,
    )
    expect(readDisplayPreferences({ getItem: () => '{broken' })).toEqual(
      DEFAULT_DISPLAY_PREFERENCES,
    )
    expect(
      readDisplayPreferences({
        getItem: () => JSON.stringify({ fontScale: 900, displayPreset: 'wall' }),
      }),
    ).toEqual(DEFAULT_DISPLAY_PREFERENCES)
  })

  it('applies only non-sensitive display values to root CSS state', () => {
    applyDisplayPreferences(
      { fontScale: 125, displayPreset: 'ultrawide', theme: 'dark' },
      document.documentElement,
    )

    expect(document.documentElement).toHaveAttribute('data-font-scale', '125')
    expect(document.documentElement).toHaveAttribute(
      'data-display-preset',
      'ultrawide',
    )
    expect(
      document.documentElement.style.getPropertyValue('--font-scale'),
    ).toBe('1.25')
  })

  it('offers accessible live controls and persists changes locally', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', {
      level: 1,
      name: 'Private by default, explicit by design',
    }, { timeout: 5_000 })

    const sizeGroup = screen.getByRole('group', { name: 'Interface size' })
    const presetGroup = screen.getByRole('group', { name: 'Display preset' })
    await user.click(
      within(sizeGroup).getByRole('button', { name: '125% interface size' }),
    )
    await user.click(within(presetGroup).getByRole('button', { name: 'Ultrawide' }))

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute('data-font-scale', '125')
      expect(document.documentElement).toHaveAttribute(
        'data-display-preset',
        'ultrawide',
      )
    })
    expect(
      within(sizeGroup).getByRole('button', { name: '125% interface size' }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      within(presetGroup).getByRole('button', { name: 'Ultrawide' }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      JSON.parse(
        window.localStorage.getItem(DISPLAY_PREFERENCES_STORAGE_KEY) ?? '{}',
      ),
    ).toEqual({ fontScale: 125, displayPreset: 'ultrawide', theme: 'dark' })
  })

  it('switches the UI between dark and light themes from the shell', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', {
      level: 1,
      name: 'Private by default, explicit by design',
    }, { timeout: 5_000 })

    const toggle = screen.getByRole('button', {
      name: /switch to light mode/i,
    })
    await user.click(toggle)

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute('data-theme', 'light')
    })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(
      JSON.parse(
        window.localStorage.getItem(DISPLAY_PREFERENCES_STORAGE_KEY) ?? '{}',
      ),
    ).toMatchObject({ theme: 'light' })
  })

  it('routes every explicit stylesheet font size through the scale variable', () => {
    const combinedStyles = Object.values(stylesheets).join('\n')
    expect(combinedStyles).not.toMatch(/font-size:\s*\d+(?:\.\d+)?px/)
    expect(combinedStyles).not.toMatch(/font:\s*\d+(?:\.\d+)?px/)
    expect(combinedStyles).toContain('--font-scale')
  })
})
