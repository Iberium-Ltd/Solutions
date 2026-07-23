/**
 * Provides a fast browser-level sanity check for routing, accessibility, and
 * shell rendering before the more expensive screenshot matrix is attempted.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { majorVisualCases, type VisualCase } from './visual-manifest'

const BASE_URL = 'http://127.0.0.1:1420'

async function installRuntimeGuards(page: Page) {
  const runtimeErrors: string[] = []

  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => runtimeErrors.push(`page: ${error.message}`))
  page.on('requestfailed', (request) => {
    runtimeErrors.push(
      `request: ${request.method()} ${request.url()} · ${request.failure()?.errorText ?? 'failed'}`,
    )
  })
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (
      url.origin !== BASE_URL &&
      url.protocol !== 'data:' &&
      url.protocol !== 'blob:'
    ) {
      runtimeErrors.push(`external-request: ${route.request().method()} ${url.href}`)
      await route.abort('blockedbyclient')
      return
    }
    await route.continue()
  })

  return runtimeErrors
}

async function expectRoute(page: Page, visualCase: VisualCase) {
  const runtimeErrors = await installRuntimeGuards(page)
  await page.goto(visualCase.path, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => document.fonts.ready)

  await expect(page.locator('h1:visible')).toHaveCount(1)
  await expect(
    page.getByRole('heading', { level: 1, name: visualCase.heading, exact: true }),
  ).toBeVisible()
  await expect(page).toHaveTitle(visualCase.documentTitle)
  await expect(page.getByTestId('route-ready')).toBeVisible()
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.captureReady),
    )
    .toBe('true')

  await expect(page.locator('main#main-content')).toHaveAttribute(
    'aria-labelledby',
    'page-title',
  )
  await expect(page.locator('aside[aria-label="Primary navigation"]')).toBeVisible()
  if (visualCase.activeNavigation) {
    await expect(
      page
        .locator('nav.nav-groups')
        .getByRole('link', { name: visualCase.activeNavigation, exact: true }),
    ).toHaveAttribute('aria-current', 'page')
  }

  if (visualCase.layoutSignal) {
    await expect(page.getByTestId('route-ready')).toHaveAttribute(
      'data-layout-ready',
      'true',
    )
  }

  const axeResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const blockingViolations = axeResults.violations.filter(
    (violation) =>
      violation.impact === 'critical' || violation.impact === 'serious',
  )
  expect(
    blockingViolations,
    blockingViolations
      .map(
        (violation) =>
          `${violation.id}: ${violation.help} (${violation.nodes.length} nodes)`,
      )
      .join('\n'),
  ).toEqual([])
  expect(runtimeErrors, runtimeErrors.join('\n')).toEqual([])
}

test.describe('route and accessibility smoke', () => {
  for (const visualCase of majorVisualCases) {
    test(`${visualCase.id} ${visualCase.slug} @smoke`, async ({ page }) => {
      await expectRoute(page, visualCase)
    })
  }

  test('root redirects to the dashboard @smoke', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/dashboard$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
      'Mission Control',
    )
  })

  test('unknown routes fail closed to the dashboard @smoke', async ({ page }) => {
    await page.goto('/this-route-does-not-exist')
    await expect(page).toHaveURL(/\/dashboard$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
      'Mission Control',
    )
  })

  test('compact shell links and buttons keep accessible names @smoke', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1100, height: 800 })
    await page.goto('/dashboard?fixture=standard')
    await expect(page.getByTestId('route-ready')).toBeVisible()

    const controls = page.locator('a:visible, button:visible')
    const controlCount = await controls.count()
    expect(controlCount).toBeGreaterThan(0)
    for (let index = 0; index < controlCount; index += 1) {
      const control = controls.nth(index)
      const markup = await control.evaluate((element) =>
        element.outerHTML.replace(/\s+/g, ' ').slice(0, 180),
      )
      await expect(
        control,
        `Compact control must have an accessible name: ${markup}`,
      ).toHaveAccessibleName(/\S/)
    }

    await expect(page.locator('.new-audit-button')).toHaveAccessibleName(
      'New audit',
    )
  })

  test('system and in-app reduced-motion paths remain effective @smoke', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/settings/privacy?fixture=standard')
    await expect
      .poll(() =>
        page.locator('.activity-dot').evaluate((element) => {
          const duration = getComputedStyle(element).animationDuration
          return duration.endsWith('ms')
            ? Number.parseFloat(duration)
            : Number.parseFloat(duration) * 1000
        }),
      )
      .toBeLessThanOrEqual(0.001)

    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.getByRole('button', { name: 'Reduced', exact: true }).click()
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.dataset.motion),
      )
      .toBe('reduced')
    await expect(page.getByText('No nonessential movement')).toBeVisible()

    await page.getByRole('button', { name: 'Follow system', exact: true }).click()
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.dataset.motion),
      )
      .toBe('full')
  })
})
