import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url))

export default defineConfig({
  testDir: './e2e',
  outputDir: `${repositoryRoot}/test-results/playwright`,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 7_500,
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: `${repositoryRoot}/playwright-report`, open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:1420',
    locale: 'en-GB',
    timezoneId: 'UTC',
    colorScheme: 'dark',
    reducedMotion: 'no-preference',
    deviceScaleFactor: 1,
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: {
    command: 'corepack pnpm build && corepack pnpm preview',
    url: 'http://127.0.0.1:1420',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: /screenshots\.spec\.ts/,
      use: { browserName: 'chromium' },
    },
    {
      name: 'webkit',
      testMatch: /(?:smoke|display-preferences)\.spec\.ts/,
      use: { browserName: 'webkit' },
    },
    {
      name: 'screenshots',
      testMatch: /screenshots\.spec\.ts/,
      retries: 0,
      use: {
        browserName: 'chromium',
        launchOptions: {
          args: ['--disable-gpu'],
        },
        screenshot: 'off',
        trace: 'off',
      },
    },
  ],
})
