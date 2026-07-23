/** Ensures every canonical route renders its intended screen and recovery state. */
import { render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import { usePrototypeStore } from '../app/prototypeStore'

function renderRoute(path: string) {
  window.history.replaceState(null, '', path)
  return render(<App />)
}

const representativeRoutes = [
  ['/dashboard?fixture=standard', 'Mission Control', 'Mission Control'],
  ['/audits/new/intake?fixture=pasted-source', 'Add source material', 'Import identifiers'],
  ['/findings?fixture=review-queue', 'Findings', 'Findings'],
  ['/reports', 'Reports', 'Reports'],
  ['/ai/workspace', 'AI Workspace', 'AI Workspace'],
  ['/ai/corpus', 'Corpus AI', 'Corpus AI'],
  ['/help/getting-started', 'Getting started', 'Getting started'],
  [
    '/findings/finding-syn-0014?fixture=evidence-rich',
    'Legacy community profile',
    'Findings',
  ],
  [
    '/settings/privacy?fixture=standard',
    'Private by default, explicit by design',
    'Privacy & Settings',
  ],
  ['/states?case=overview', 'State laboratory', null],
] as const

const lazyRouteWait = { timeout: 5_000 }

describe('application route contract', () => {
  beforeEach(() => {
    usePrototypeStore.setState({
      sidebarCollapsed: false,
      simulationPaused: false,
      reducedMotion: false,
      selectedTool: 'Username Sweep',
      transmissionMode: 'local',
    })
    document.title = 'Codename Ariadne · Synthetic prototype'
  })

  it.each(representativeRoutes)(
    'renders %s as the intended screen',
    async (path, headingName, activeNavigation) => {
      renderRoute(path)

      const heading = await screen.findByRole(
        'heading',
        {
          level: 1,
          name: headingName,
        },
        lazyRouteWait,
      )
      expect(heading).toBeVisible()
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
      expect(await screen.findByTestId('route-ready')).toBeVisible()
      expect(document.title).toContain('Codename Ariadne')

      if (activeNavigation) {
        const sidebar = screen.getByRole('complementary', {
          name: 'Primary navigation',
        })
        expect(
          within(sidebar).getByRole('link', {
            name: activeNavigation,
          }),
        ).toHaveAttribute('aria-current', 'page')
      }

      await waitFor(() => expect(heading).toHaveFocus())
    },
  )

  it('redirects the root route to Mission Control', async () => {
    renderRoute('/')
    expect(
      await screen.findByRole(
        'heading',
        { level: 1, name: 'Mission Control' },
        lazyRouteWait,
      ),
    ).toBeVisible()
    await waitFor(() => expect(window.location.pathname).toBe('/dashboard'))
  })

  it('fails closed to Mission Control for unknown routes', async () => {
    renderRoute('/not-a-real-ariadne-route')
    expect(
      await screen.findByRole(
        'heading',
        { level: 1, name: 'Mission Control' },
        lazyRouteWait,
      ),
    ).toBeVisible()
    await waitFor(() => expect(window.location.pathname).toBe('/dashboard'))
  })
})
