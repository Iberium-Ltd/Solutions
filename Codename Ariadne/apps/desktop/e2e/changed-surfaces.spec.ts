/**
 * Focused visual regression coverage for surfaces changed after the accepted
 * baseline, avoiding an expensive recapture of unrelated screens.
 */
import { expect, test, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const screenshotRoot = `${repositoryRoot}/artifacts/ui-screenshots/targeted-final`
const captureScreenshots = process.env.ARIADNE_TARGETED_SCREENSHOTS === '1'

async function blockExternalRequests(page: Page) {
  const failures: string[] = []
  page.on('pageerror', (error) => failures.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') failures.push(message.text())
  })
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (
      url.origin !== 'http://127.0.0.1:1420' &&
      url.protocol !== 'data:' &&
      url.protocol !== 'blob:'
    ) {
      failures.push(`Blocked external request: ${url.href}`)
      await route.abort('blockedbyclient')
      return
    }
    await route.continue()
  })
  return failures
}

async function expectNoPageOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual(
      await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.clientWidth,
      })),
    )
}

async function capture(page: Page, fileName: string) {
  if (!captureScreenshots) return
  await mkdir(screenshotRoot, { recursive: true })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    animations: 'disabled',
    fullPage: true,
    path: `${screenshotRoot}/${fileName}`,
  })
}

test('display controls and OpenAI selectors fit laptop and ultrawide layouts', async ({
  page,
}) => {
  const failures = await blockExternalRequests(page)

  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/settings/privacy?fixture=standard')
  await expect(page.getByTestId('route-ready')).toBeVisible()
  await page.getByRole('button', { name: '110% interface size' }).click()
  await page.getByRole('button', { name: 'Laptop', exact: true }).click()
  await expectNoPageOverflow(page)
  await capture(page, 'settings-laptop-1366x768.png')

  await page.setViewportSize({ width: 2560, height: 1080 })
  await page.getByRole('button', { name: 'Ultrawide', exact: true }).click()
  await expectNoPageOverflow(page)
  await capture(page, 'settings-ultrawide-2560x1080.png')

  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/ai/workspace?fixture=standard')
  await expect(page.getByTestId('route-ready')).toBeVisible()
  await page.getByText('OpenAI Responses', { exact: true }).click()
  await expect(page.getByText('OpenAI API key · used once')).toBeVisible()
  await expectNoPageOverflow(page)
  await capture(page, 'ai-workspace-openai-laptop-1366x768.png')

  await page.setViewportSize({ width: 2560, height: 1080 })
  await page.goto('/ai/corpus?fixture=standard')
  await expect(page.getByTestId('route-ready')).toBeVisible()
  await page.getByText('OpenAI Responses', { exact: true }).click()
  await expect(page.getByText('OpenAI API key · used once')).toBeVisible()
  await expectNoPageOverflow(page)
  await capture(page, 'corpus-ai-openai-ultrawide-2560x1080.png')

  expect(failures).toEqual([])
})

test('all Discovery Console tabs fit without invoking a provider', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, 'isTauri', {
      configurable: true,
      value: true,
    })
    const response = (data: unknown) => ({
      requestId: '11111111-1111-4111-8111-111111111111',
      data,
    })
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      configurable: true,
      value: {
        invoke: async (command: string) => {
          if (command === 'core_capabilities') {
            return response({
              versions: {
                contract: 1,
                schema: 'ariadne-v1',
                events: 1,
                core: '0.1.0',
              },
              transport: 'DEV_LOOPBACK',
              cipher: {
                required: 'SQLCIPHER',
                available: true,
                sqliteVersion: 'synthetic',
                cipherVersion: 'synthetic',
              },
              features: [],
            })
          }
          if (command === 'core_session') {
            return response({
              lockState: 'UNLOCKED',
              vaultState: 'UNLOCKED',
              authenticatedTransport: true,
              compatibility: 'COMPATIBLE',
              sessionExpiresAt: null,
              activeRevealCapabilities: 0,
            })
          }
          throw new Error(`Unexpected synthetic invoke: ${command}`)
        },
      },
    })
  })
  const failures = await blockExternalRequests(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/tools?fixture=standard')
  await expect(page.getByRole('heading', { level: 1, name: 'Discovery Console' })).toBeVisible()
  await expect(page.getByText('Search one public provider')).toBeVisible()
  await expectNoPageOverflow(page)
  await capture(page, 'discovery-public-1440x900.png')

  await page.getByRole('tab', { name: 'Query composer' }).click()
  await page.getByLabel('Core query').fill('synthetic alias')
  await page.getByLabel('Only site or domain').fill('example.invalid')
  await page.getByLabel(/I authorise this browser search/).check()
  await expect(page.getByText('synthetic alias site:example.invalid')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open' }).first()).toHaveAttribute('href', /google\.com\/search/)
  await expectNoPageOverflow(page)
  await capture(page, 'discovery-query-composer-1440x900.png')

  await page.getByRole('tab', { name: 'Breach exposure' }).click()
  await expect(page.getByRole('heading', { name: 'Have I Been Pwned v3' })).toBeVisible()
  await expect(page.getByLabel(/HIBP API key/)).toHaveAttribute('type', 'password')
  await expectNoPageOverflow(page)

  await page.getByRole('tab', { name: 'Plan & combine' }).click()
  await expect(page.getByText('Compose an investigation')).toBeVisible()
  await expectNoPageOverflow(page)
  await capture(page, 'discovery-plan-1440x900.png')

  await page.setViewportSize({ width: 2560, height: 1080 })
  await page.getByRole('tab', { name: 'Manual portals' }).click()
  await expect(page.getByRole('heading', { name: 'DeHashed' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Spokeo' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Intelius' })).toBeVisible()
  await expectNoPageOverflow(page)
  await capture(page, 'discovery-portals-ultrawide-2560x1080.png')

  expect(failures).toEqual([])
})
