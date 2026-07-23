/**
 * Captures the deterministic visual contract declared by visual-manifest.ts.
 * Network blocking and fixed fixtures make each image reproducible evidence.
 */
import { chromium, expect, test, type Locator, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import {
  expectedScreenshotCount,
  screenshotFileName,
  VISUAL_CLOCK,
  VISUAL_FIXTURE_VERSION,
  VISUAL_RANDOM_SEED,
  visualCases,
  visualViewports,
  type VisualCase,
  type VisualViewport,
} from './visual-manifest'

const BASE_URL = 'http://127.0.0.1:1420'
const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const screenshotPass = process.env.SCREENSHOT_PASS?.trim() || 'pass-01'

if (!/^[a-z0-9][a-z0-9-]*$/i.test(screenshotPass)) {
  throw new Error(
    'SCREENSHOT_PASS must contain only letters, numbers, and hyphens.',
  )
}

const artifactRoot = `${repositoryRoot}/artifacts/ui-screenshots/${screenshotPass}`
const metadataPath = `${artifactRoot}/manifest.json`
const allowOverwrite = process.env.ARIADNE_OVERWRITE_SCREENSHOTS === '1'

const longIdentifierFixture = {
  id: 'finding_syn_0000000000000000000000000000000000000000000000000000000000000000000000000000000000000001',
  url: 'https://profile.example.invalid/synthetic-segment-0001/synthetic-segment-0002/synthetic-segment-0003/synthetic-segment-0004',
  hash: 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  provider:
    'Synthetic Provider With A Deliberately Long Descriptive Display Name For Layout Testing',
} as const

type PageProblem = {
  kind: 'console' | 'page' | 'request' | 'external-request'
  message: string
}

function worktreeIdentifier() {
  try {
    const revision = execFileSync(
      'git',
      ['rev-parse', '--short=12', 'HEAD'],
      { cwd: repositoryRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
    ).trim()
    const dirty = execFileSync('git', ['status', '--porcelain'], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    return dirty ? `${revision}-dirty` : revision
  } catch {
    return 'uncommitted-worktree'
  }
}

async function existingPngCount() {
  let count = 0
  for (const directory of ['major', 'states']) {
    try {
      const entries = await readdir(`${artifactRoot}/${directory}`)
      count += entries.filter((entry) => entry.endsWith('.png')).length
    } catch {
      // A new pass has no artifact directories yet.
    }
  }
  return count
}

async function installDeterministicRuntime(page: Page) {
  const frozenTime = Date.parse(VISUAL_CLOCK)
  const script = `
    (() => {
      const NativeDate = Date;
      const frozenTime = ${JSON.stringify(frozenTime)};
      class FrozenDate extends NativeDate {
        constructor(...args) {
          if (args.length === 0) super(frozenTime);
          else super(...args);
        }
        static now() { return frozenTime; }
      }
      Object.defineProperty(window, 'Date', {
        configurable: true,
        value: FrozenDate,
      });

      let state = 2166136261;
      for (const character of ${JSON.stringify(VISUAL_RANDOM_SEED)}) {
        state ^= character.charCodeAt(0);
        state = Math.imul(state, 16777619);
      }
      Math.random = () => {
        state += 0x6D2B79F5;
        let value = state;
        value = Math.imul(value ^ (value >>> 15), value | 1);
        value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
        return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
      };

      const markFixtureSeed = () => {
        if (document.documentElement) {
          document.documentElement.dataset.fixtureSeed = ${JSON.stringify(VISUAL_RANDOM_SEED)};
        }
      };
      markFixtureSeed();
      if (!document.documentElement) {
        document.addEventListener('DOMContentLoaded', markFixtureSeed, { once: true });
      }
      try {
        localStorage.setItem('ariadne:visual-seed', ${JSON.stringify(VISUAL_RANDOM_SEED)});
      } catch {
        // Storage can be unavailable on the initial about:blank document.
      }
    })();
  `
  await page.addInitScript(script)
}

async function guardLocalRuntime(page: Page) {
  const problems: PageProblem[] = []

  page.on('console', (message) => {
    if (message.type() === 'error') {
      problems.push({ kind: 'console', message: message.text() })
    }
  })
  page.on('pageerror', (error) => {
    problems.push({ kind: 'page', message: error.message })
  })
  page.on('requestfailed', (request) => {
    problems.push({
      kind: 'request',
      message: `${request.method()} ${request.url()} · ${request.failure()?.errorText ?? 'failed'}`,
    })
  })

  await page.route('**/*', async (route) => {
    const requestUrl = new URL(route.request().url())
    if (
      requestUrl.origin !== BASE_URL &&
      requestUrl.protocol !== 'data:' &&
      requestUrl.protocol !== 'blob:'
    ) {
      problems.push({
        kind: 'external-request',
        message: `${route.request().method()} ${requestUrl.href}`,
      })
      await route.abort('blockedbyclient')
      return
    }
    await route.continue()
  })

  return problems
}

async function expectProofInViewport(
  locator: Locator,
  viewport: VisualViewport,
  label: string,
  options: { all?: boolean } = {},
) {
  const rectangles = await locator.evaluateAll(
    (elements, dimensions) =>
      elements.map((element) => {
        const rectangle = element.getBoundingClientRect()
        const visibleWidth = Math.max(
          0,
          Math.min(rectangle.right, dimensions.width) -
            Math.max(rectangle.left, 0),
        )
        const visibleHeight = Math.max(
          0,
          Math.min(rectangle.bottom, dimensions.height) -
            Math.max(rectangle.top, 0),
        )
        const area = rectangle.width * rectangle.height
        return {
          ratio: area > 0 ? (visibleWidth * visibleHeight) / area : 0,
          x: rectangle.x,
          y: rectangle.y,
          width: rectangle.width,
          height: rectangle.height,
        }
      }),
    { width: viewport.width, height: viewport.height },
  )

  expect(rectangles.length, `${label} must exist`).toBeGreaterThan(0)
  const indexed = rectangles.map((rectangle, index) => ({ rectangle, index }))
  const candidates = options.all
    ? indexed
    : [
        indexed.reduce((best, candidate) =>
          candidate.rectangle.ratio > best.rectangle.ratio ? candidate : best,
        ),
      ]

  for (const candidate of candidates) {
    const detail = JSON.stringify(candidate.rectangle)
    await expect(locator.nth(candidate.index), `${label} must be visible`).toBeVisible()
    expect(
      candidate.rectangle.ratio,
      `${label} must be at least 80% inside ${viewport.width}x${viewport.height}; geometry=${detail}`,
    ).toBeGreaterThanOrEqual(0.8)
  }
}

async function assertRouteProof(
  page: Page,
  visualCase: VisualCase,
  viewport: VisualViewport,
) {
  if (visualCase.id === 'M02' && viewport.width === 1100) {
    await expectProofInViewport(
      page.getByRole('link', { name: /continue to intake/i }),
      viewport,
      'M02 Continue to intake action',
    )
  }
  if (
    visualCase.id === 'M03' &&
    (viewport.width === 1100 || viewport.width === 1440)
  ) {
    await expectProofInViewport(
      page.getByRole('link', { name: /review 6 candidates/i }),
      viewport,
      'M03 Review 6 candidates action',
    )
  }
  if (
    visualCase.id === 'M05' &&
    (viewport.width === 1100 || viewport.width === 1440)
  ) {
    await expectProofInViewport(
      page.getByRole('button', { name: /review & simulate trace/i }),
      viewport,
      'M05 Review and simulate trace action',
    )
  }
  if (
    visualCase.id === 'M06' &&
    (viewport.width === 1100 || viewport.width === 1440)
  ) {
    const recovery = page.getByRole('region', { name: /blocked task recovery/i })
    await expectProofInViewport(recovery, viewport, 'M06 blocked task recovery')
    await expectProofInViewport(
      recovery.getByRole('button', { name: /review boundary/i }),
      viewport,
      'M06 Review boundary recovery action',
    )
    await expectProofInViewport(
      recovery.getByRole('button', { name: /skip provider/i }),
      viewport,
      'M06 Skip provider recovery action',
    )
  }
  if (
    visualCase.id === 'M10' &&
    (viewport.width === 1100 || viewport.width === 1440)
  ) {
    await expectProofInViewport(
      page.locator('.evidence-hash'),
      viewport,
      'M10 SHA-256 evidence region',
    )
    await expectProofInViewport(
      page.getByRole('button', { name: /copy full hash/i }),
      viewport,
      'M10 Copy full hash action',
    )
  }
}

async function assertStateContract(
  page: Page,
  visualCase: VisualCase,
  viewport: VisualViewport,
) {
  if (visualCase.id === 'S01') {
    await expect(page.getByText(/does not claim that no exposure exists/i)).toBeVisible()
    if (viewport.width === 1100) {
      await expectProofInViewport(
        page.getByRole('button', { name: /start a synthetic trace/i }),
        viewport,
        'S01 safe next action',
      )
      await expectProofInViewport(
        page.locator('.controls-callout').filter({
          hasText: /does not claim that no exposure exists/i,
        }),
        viewport,
        'S01 honest empty-state callout',
      )
    }
  }
  if (visualCase.id === 'S02') {
    await expect(page.locator('[aria-busy="true"]')).toBeVisible()
    await expect(
      page.locator('[aria-busy="true"] [role="status"]'),
    ).toContainText(/extracting|loading/i)
    if (viewport.width === 1100) {
      await expectProofInViewport(
        page.locator('.controls-callout').filter({
          hasText: /final layout space is reserved/i,
        }),
        viewport,
        'S02 loading assurance callout',
      )
    }
  }
  if (visualCase.id === 'S03') {
    for (const outcome of [
      'CHECK_FAILED',
      'RATE_LIMITED',
      'PROVIDER_UNAVAILABLE',
    ]) {
      await expect(page.getByText(outcome, { exact: true })).toBeVisible()
    }
    if (viewport.width === 1100) {
      await expect(
        page.getByRole('button', { name: /retry safely/i }),
      ).toHaveCount(3)
      await expectProofInViewport(
        page.getByRole('button', { name: /retry safely/i }),
        viewport,
        'S03 Retry safely actions',
        { all: true },
      )
    }
  }
  if (visualCase.id === 'S04') {
    await expect(page.getByText('ACCESS_BLOCKED', { exact: true })).toBeVisible()
    await expect(page.getByText(/guided browser capture/i)).toBeVisible()
    await expect(page.getByText(/import a local capture/i)).toBeVisible()
    if (viewport.width === 1100) {
      await expectProofInViewport(
        page.locator('.controls-callout').filter({
          hasText: /transparent hand-off/i,
        }),
        viewport,
        'S04 manual-capture caution',
      )
    }
  }
  if (visualCase.id === 'S05') {
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.motion))
      .toBe('reduced')
    await expect(page.getByText(/every state remains understandable/i)).toBeVisible()
    if (viewport.width === 1100) {
      await expectProofInViewport(
        page.getByRole('button', { name: /open graph table/i }),
        viewport,
        'S05 Open graph table action',
      )
    }
  }
  if (visualCase.id === 'S06') {
    for (const value of Object.values(longIdentifierFixture)) {
      await expect(page.getByText(value, { exact: true }).first()).toBeAttached()
    }
    if (viewport.width === 1100) {
      await expectProofInViewport(
        page.getByText(longIdentifierFixture.hash, { exact: true }),
        viewport,
        'S06 SHA-256 value',
      )
      await expectProofInViewport(
        page.getByRole('button', { name: /open evidence/i }),
        viewport,
        'S06 Open evidence action',
      )
    }
  }
}

async function assertPrivacySafety(page: Page, visualCase: VisualCase) {
  const rendered = await page.evaluate(() => ({
    text: document.body.innerText,
    resourceUrls: Array.from(
      document.querySelectorAll<HTMLElement>('[href], [src]'),
    ).flatMap((element) => {
      const value = element.getAttribute('href') ?? element.getAttribute('src')
      return value ? [value] : []
    }),
  }))

  const emailMatches = rendered.text.match(
    /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi,
  ) ?? []
  for (const email of emailMatches) {
    expect(email.toLocaleLowerCase()).toMatch(/@(?:[a-z0-9-]+\.)*example\.invalid$/)
  }

  const visibleUrls = rendered.text.match(/https?:\/\/[^\s<>"']+/gi) ?? []
  for (const value of [...rendered.resourceUrls, ...visibleUrls]) {
    const resolved = new URL(value.replace(/[),.;]+$/, ''), BASE_URL)
    if (resolved.origin === BASE_URL || ['data:', 'blob:'].includes(resolved.protocol)) {
      continue
    }
    expect(resolved.hostname).toMatch(/(?:^|\.)example\.invalid$/)
  }

  expect(rendered.text).not.toMatch(
    /[-+]?\d{1,3}\.\d{4,}\s*[,°]\s*[-+]?\d{1,3}\.\d{4,}/,
  )
  await expect(page.getByText(/synthetic prototype/i).first()).toBeVisible()

  const unsafeEnabledActions = page
    .locator('button:not([disabled]), a[href]')
    .filter({
      hasText:
        /\b(?:send externally|submit report|transmit now|publish publicly|file report|contact provider)\b/i,
    })
  await expect(unsafeEnabledActions).toHaveCount(0)

  if (visualCase.id === 'M06') {
    await expect(page.getByText(/phase 1/i).first()).toBeVisible()
  }
}

async function assertViewportIntegrity(page: Page, viewport: VisualViewport) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)

  const primaryAction = page
    .locator('.page-header__actions :is(button, a):visible')
    .first()
  if (await primaryAction.count()) {
    const box = await primaryAction.boundingBox()
    expect(box, 'Primary action must have a rendered bounding box').not.toBeNull()
    if (box) {
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.y).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
    }
  }

  const emptyBadges = await page.locator('.badge:visible').evaluateAll((badges) =>
    badges.filter((badge) => !badge.textContent?.trim()).length,
  )
  expect(emptyBadges, 'Status badges must have visible text, not colour alone').toBe(0)
}

async function preparePage(
  page: Page,
  visualCase: VisualCase,
  viewport: VisualViewport,
) {
  await installDeterministicRuntime(page)
  const problems = await guardLocalRuntime(page)

  await page.goto(visualCase.path, { waitUntil: 'networkidle' })
  await page.evaluate(() => document.fonts.ready)

  const headings = page.locator('h1:visible')
  await expect(headings).toHaveCount(1)
  await expect(
    page.getByRole('heading', { level: 1, name: visualCase.heading, exact: true }),
  ).toBeVisible()
  await expect(page).toHaveTitle(visualCase.documentTitle)
  await expect(page.locator('main#main-content')).toBeVisible()
  await expect(page.locator('aside[aria-label="Primary navigation"]')).toBeVisible()

  const routeRoot = page.getByTestId('route-ready')
  await expect(routeRoot).toBeVisible()
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.captureReady),
    )
    .toBe('true')

  if (visualCase.layoutSignal) {
    await expect(routeRoot).toHaveAttribute('data-layout-ready', 'true')
  }
  if (visualCase.layoutSignal === 'graph') {
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.dataset.graphLayout),
      )
      .toBe('settled')
  }

  const navigation = page.locator('nav.nav-groups')
  if (visualCase.activeNavigation) {
    const activeLink = navigation.getByRole('link', {
      name: visualCase.activeNavigation,
      exact: true,
    })
    await expect(activeLink).toHaveAttribute('aria-current', 'page')
  } else {
    await expect(navigation.locator('[aria-current="page"]')).toHaveCount(0)
  }

  await assertRouteProof(page, visualCase, viewport)
  await assertStateContract(page, visualCase, viewport)
  await assertPrivacySafety(page, visualCase)
  await assertViewportIntegrity(page, viewport)

  // Let lazy route CSS, local font glyphs, and the software compositor reach a
  // quiet frame. Playwright's screenshot-level animation control is used below
  // so this wait does not trigger a global style invalidation of the document.
  await page.waitForTimeout(1000)

  expect(problems, problems.map((problem) => `${problem.kind}: ${problem.message}`).join('\n')).toEqual([])
}

test.describe('Phase 1 screenshot contract @visual', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async ({ browser }) => {
    const existing = await existingPngCount()
    if (existing > 0 && !allowOverwrite) {
      throw new Error(
        `${artifactRoot} already contains ${existing} PNG files. Choose a new SCREENSHOT_PASS or set ARIADNE_OVERWRITE_SCREENSHOTS=1 for an explicitly disposable pass.`,
      )
    }

    await mkdir(`${artifactRoot}/major`, { recursive: true })
    await mkdir(`${artifactRoot}/states`, { recursive: true })
    await writeFile(
      metadataPath,
      `${JSON.stringify(
        {
          schemaVersion: 1,
          reviewStatus: 'unreviewed',
          pass: screenshotPass,
          startedAt: new Date().toISOString(),
          appClock: VISUAL_CLOCK,
          fixtureVersion: VISUAL_FIXTURE_VERSION,
          randomSeed: VISUAL_RANDOM_SEED,
          browser: {
            name: 'chromium',
            version: browser.version(),
            gpuCompositing: 'disabled for deterministic raster capture',
          },
          worktree: worktreeIdentifier(),
          captureCommand: `SCREENSHOT_PASS=${screenshotPass} pnpm screenshots`,
          expectedScreenshotCount,
          viewports: visualViewports,
          artifacts: visualCases.flatMap((visualCase) =>
            visualViewports.map((viewport) => ({
              id: visualCase.id,
              kind: visualCase.kind,
              route: visualCase.path,
              proof: visualCase.proof,
              viewport,
              file: `${visualCase.kind}/${screenshotFileName(visualCase, viewport)}`,
            })),
          ),
        },
        null,
        2,
      )}\n`,
      'utf8',
    )
  })

  test.afterAll(async () => {
    const metadata = JSON.parse(await readFile(metadataPath, 'utf8')) as Record<
      string,
      unknown
    >
    const capturedScreenshotCount = await existingPngCount()
    await writeFile(
      metadataPath,
      `${JSON.stringify(
        {
          ...metadata,
          finishedAt: new Date().toISOString(),
          capturedScreenshotCount,
          captureSetComplete:
            capturedScreenshotCount === expectedScreenshotCount,
        },
        null,
        2,
      )}\n`,
      'utf8',
    )
  })

  for (const visualCase of visualCases) {
    for (const viewport of visualViewports) {
      test(`${visualCase.id} ${visualCase.slug} ${viewport.key}`, async () => {
        // A fresh software-rendered browser per artifact prevents Chromium's
        // compositor cache from leaking incomplete tiles between rapid serial
        // captures on macOS. The production app remains hardware accelerated.
        const captureBrowser = await chromium.launch({
          headless: true,
          args: ['--disable-gpu'],
        })
        const context = await captureBrowser.newContext({
          colorScheme: 'dark',
          deviceScaleFactor: 1,
          locale: 'en-GB',
          reducedMotion: visualCase.reducedMotion ? 'reduce' : 'no-preference',
          serviceWorkers: 'block',
          timezoneId: 'UTC',
          viewport: { width: viewport.width, height: viewport.height },
        })
        const page = await context.newPage()

        try {
          await preparePage(page, visualCase, viewport)
          await page.screenshot({
            path: `${artifactRoot}/${visualCase.kind}/${screenshotFileName(visualCase, viewport)}`,
            animations: 'disabled',
            caret: 'hide',
            fullPage: false,
            omitBackground: false,
            scale: 'css',
            type: 'png',
          })
        } finally {
          await captureBrowser.close()
        }
      })
    }
  }
})
