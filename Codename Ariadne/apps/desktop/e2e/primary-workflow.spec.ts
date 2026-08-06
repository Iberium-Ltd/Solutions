/**
 * Exercises the complete native-shaped foreground journey with a closed,
 * synthetic Tauri runtime so route handoffs, citations, and export are tested
 * without transmitting real identity data.
 */
import { expect, test, type Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { completedAuditDetail } from '../src/test/identityAuditFixture'

const BASE_URL = 'http://127.0.0.1:1420'
const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const screenshotPass = process.env.PRIMARY_WORKFLOW_SCREENSHOT_PASS?.trim() ?? ''
const artifactRoot = screenshotPass
  ? `${repositoryRoot}/artifacts/ui-screenshots/${screenshotPass}`
  : null

if (screenshotPass && !/^[a-z0-9][a-z0-9-]*$/iu.test(screenshotPass)) {
  throw new Error('PRIMARY_WORKFLOW_SCREENSHOT_PASS has an invalid value')
}

const profileId = completedAuditDetail.profileId
const sourceId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const entityId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
const segmentId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const extractionRunId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'

const profile = {
  profileId,
  displayLabel: 'Synthetic self-audit',
  purpose: 'Authorised synthetic workflow verification',
  status: 'ACTIVE',
  revision: 1,
}

const origin = {
  sourceId,
  sourceDisplayName: 'Synthetic workflow seed',
  sourceSha256: 'a'.repeat(64),
  segmentId,
  segmentIndex: 0,
  segmentLocator: '{"kind":"line","index":0}',
  sourceSpanStart: 9,
  sourceSpanEnd: 28,
  extractionRunId,
  extractorKind: 'DETERMINISTIC',
  extractorName: 'synthetic-entity-compiler',
  extractorVersion: '1.0.0',
  originKind: 'DETERMINISTIC',
  observedAtUs: 1_750_000_000_123_456,
  confidenceMicros: 1_000_000,
  explanation: 'Synthetic exact-source observation for workflow verification.',
}

const unreviewedEntity = {
  entityId,
  entityType: 'USERNAME',
  displayValue: 'synthetic_orbit_742',
  sensitivity: 'PUBLIC',
  reviewState: 'UNREVIEWED',
  temporalState: 'UNKNOWN',
  searchPolicy: 'REQUIRE_APPROVAL',
  transmissionPolicy: 'REQUIRE_EACH_APPROVAL',
  confidenceMicros: 1_000_000,
  provenanceLabel: 'Synthetic workflow seed · line 1',
  origins: [origin],
  originsTruncated: false,
  revision: 1,
}

const confirmedEntity = {
  ...unreviewedEntity,
  reviewState: 'CONFIRMED',
  temporalState: 'CURRENT',
  searchPolicy: 'ALLOW',
  transmissionPolicy: 'POLICY_CONTROLLED',
  revision: 2,
}

const providers = [
  'DUCKDUCKGO_HTML',
  'GITHUB_USERS',
  'GITLAB_USERS',
  'NPM_REGISTRY',
  'RDAP_DOMAIN',
  'WAYBACK_CDX',
  'CERTIFICATE_TRANSPARENCY',
]

const terminalTasks = providers.map((providerId, index) => ({
  ...completedAuditDetail.tasks[0],
  taskId: `33333333-3333-4333-8333-33333333333${index}`,
  providerId,
  state: index === 0 ? 'SUCCEEDED_RESULTS' : 'SUCCEEDED_EMPTY',
  resultCount: index === 0 ? 1 : 0,
  stopReason: index === 0 ? null : 'NO_RESULTS',
}))

const completedDetail = {
  ...completedAuditDetail,
  tasks: terminalTasks,
  results: completedAuditDetail.results.map((result) => ({
    ...result,
    taskId: terminalTasks[0].taskId,
  })),
  receipts: completedAuditDetail.receipts.map((receipt) => ({
    ...receipt,
    taskId: terminalTasks[0].taskId,
  })),
  audit: {
    ...completedAuditDetail.audit,
    name: 'Synthetic complete identity audit',
    providerIds: providers,
    totalTasks: providers.length,
    terminalTasks: providers.length,
    taskStates: [
      { state: 'SUCCEEDED_RESULTS', count: 1 },
      { state: 'SUCCEEDED_EMPTY', count: providers.length - 1 },
    ],
  },
}

const queuedDetail = {
  ...completedDetail,
  tasks: terminalTasks.map((task) => ({
    ...task,
    state: 'QUEUED',
    resultCount: 0,
    stopReason: null,
  })),
  results: [],
  leads: [],
  proposals: [],
  receipts: [],
  aiAnalysis: null,
  audit: {
    ...completedDetail.audit,
    state: 'READY',
    stage: 'PLANNING',
    terminalTasks: 0,
    resultCount: 0,
    leadCount: 0,
    proposalCount: 0,
    progressMicros: 120_000,
    stopReason: null,
    taskStates: [{ state: 'QUEUED', count: providers.length }],
    finishedAtUs: null,
    revision: 1,
  },
}

const runningDetail = {
  ...queuedDetail,
  tasks: queuedDetail.tasks.map((task, index) => ({
    ...task,
    state: index === 0 ? 'RUNNING' : 'QUEUED',
  })),
  audit: {
    ...queuedDetail.audit,
    state: 'RUNNING',
    stage: 'SEARCHING',
    progressMicros: 420_000,
    taskStates: [
      { state: 'RUNNING', count: 1 },
      { state: 'QUEUED', count: providers.length - 1 },
    ],
    revision: 2,
  },
}

const workspace = {
  person: {
    profileId,
    displayName: profile.displayLabel,
    purpose: profile.purpose,
    status: profile.status,
    notes: '',
    tags: ['synthetic', 'self-audit'],
    profileRevision: 1,
    detailsRevision: 0,
    identityCount: 1,
    sourceCount: 1,
    auditCount: 0,
    unresolvedProposalCount: 0,
  },
  sources: [],
  audits: [],
  hasMoreSources: false,
  hasMoreAudits: false,
}

type RuntimeFixture = {
  readonly profile: typeof profile
  readonly unreviewedEntity: typeof unreviewedEntity
  readonly confirmedEntity: typeof confirmedEntity
  readonly workspace: typeof workspace
  readonly queuedDetail: typeof queuedDetail
  readonly runningDetail: typeof runningDetail
  readonly completedDetail: typeof completedDetail
}

async function installSyntheticNativeRuntime(page: Page) {
  await page.addInitScript((fixture: RuntimeFixture) => {
    const requestId = '99999999-9999-4999-8999-999999999999'
    const vaultId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    const sourceId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    let vaultCreated = false
    let profileCreated = false
    let entityConfirmed = false
    let executionCount = 0

    const response = (data: unknown) => ({ requestId, data })
    const session = () => response({
      lockState: vaultCreated ? 'UNLOCKED' : 'LOCKED',
      vaultState: vaultCreated ? 'UNLOCKED' : 'NO_VAULT',
      compatibility: 'COMPATIBLE',
      authenticatedTransport: true,
      sessionExpiresAt: null,
      activeRevealCapabilities: 0,
    })

    Object.defineProperty(window, 'isTauri', {
      configurable: true,
      value: true,
    })
    const tauriWindow = window as typeof window & {
      __TAURI_INTERNALS__: {
        invoke: (
          command: string,
          arguments_?: Record<string, unknown>,
        ) => Promise<unknown>
      }
    }
    tauriWindow.__TAURI_INTERNALS__ = {
      invoke: async (command) => {
        if (command === 'core_capabilities') {
          return response({
            versions: {
              contract: 1,
              schema: 'ariadne-v1',
              events: 1,
              core: '0.1.0',
            },
            transport: 'UNIX_SOCKET',
            cipher: {
              required: 'SQLCIPHER',
              available: true,
              sqliteVersion: '3.53.3',
              cipherVersion: '4.17.0 community',
            },
            features: [],
          })
        }
        if (command === 'core_session') return session()
        if (command === 'core_create_vault') {
          vaultCreated = true
          return response({
            vaultId,
            lockState: 'UNLOCKED',
            vaultState: 'UNLOCKED',
          })
        }
        if (command === 'core_list_profiles') {
          return response({
            profiles: profileCreated ? [fixture.profile] : [],
            hasMore: false,
          })
        }
        if (command === 'core_create_profile') {
          profileCreated = true
          return response(fixture.profile)
        }
        if (command === 'core_intake_paste') {
          return response({
            sourceId,
            profileId: fixture.profile.profileId,
            state: 'READY_FOR_REVIEW',
            sourceKind: 'PASTED_TEXT',
            segmentCount: 1,
            candidateCount: 1,
            localAiStatus: 'DISABLED',
            localAiProvider: null,
            localAiModel: null,
            localAiEngineVersion: null,
            localAiSuggestionCount: 0,
            duplicateCount: 0,
            quarantineCount: 0,
            revision: 1,
          })
        }
        if (command === 'core_review_entities') {
          return response({
            profileId: fixture.profile.profileId,
            entities: [
              entityConfirmed
                ? fixture.confirmedEntity
                : fixture.unreviewedEntity,
            ],
            quarantineCount: 0,
            hasMore: false,
          })
        }
        if (command === 'core_decide_entity') {
          entityConfirmed = true
          return response(fixture.confirmedEntity)
        }
        if (command === 'core_identity_workspace') {
          return response(fixture.workspace)
        }
        if (command === 'core_create_identity_audit') {
          executionCount = 0
          return response(fixture.queuedDetail)
        }
        if (command === 'core_get_identity_audit') {
          return response(
            executionCount >= 2
              ? fixture.completedDetail
              : fixture.queuedDetail,
          )
        }
        if (command === 'core_execute_identity_audit_batch') {
          executionCount += 1
          if (executionCount === 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 900))
            return response(fixture.runningDetail)
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1_400))
          return response(fixture.completedDetail)
        }
        throw new Error(`Unexpected synthetic native command: ${command}`)
      },
    }
  }, {
    profile,
    unreviewedEntity,
    confirmedEntity,
    workspace,
    queuedDetail,
    runningDetail,
    completedDetail,
  })
}

async function capture(page: Page, name: string, files: string[]) {
  if (artifactRoot === null) return
  await mkdir(artifactRoot, { recursive: true })
  const filename = `${name}.png`
  await page.screenshot({
    path: `${artifactRoot}/${filename}`,
    fullPage: true,
    animations: 'disabled',
  })
  files.push(filename)
}

test('native primary workflow reaches a cited final package @primary-workflow', async ({
  page,
}) => {
  test.setTimeout(60_000)
  const problems: string[] = []
  const screenshots: string[] = []

  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => problems.push(`page: ${error.message}`))
  page.on('requestfailed', (request) => {
    problems.push(
      `request: ${request.method()} ${request.url()} · ${request.failure()?.errorText ?? 'failed'}`,
    )
  })
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (
      url.origin !== BASE_URL &&
      url.protocol !== 'blob:' &&
      url.protocol !== 'data:'
    ) {
      problems.push(`external request: ${route.request().method()} ${url.href}`)
      await route.abort('blockedbyclient')
      return
    }
    await route.continue()
  })
  await installSyntheticNativeRuntime(page)
  await page.setViewportSize({ width: 1720, height: 1000 })
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)

  await expect(page.getByRole('heading', {
    level: 1,
    name: 'Create your local vault',
  })).toBeVisible()
  await capture(page, '00-vault-creation', screenshots)

  await page.getByRole('button', {
    name: 'Create vault and choose profile',
  }).click()
  await expect(page).toHaveURL(/\/audits\/new$/u)
  await expect(page.getByRole('heading', {
    level: 1,
    name: 'Start a profile-scoped audit',
  })).toBeVisible()
  await capture(page, '01-named-profile', screenshots)

  await page.getByLabel('Profile name').fill(profile.displayLabel)
  await page.getByRole('button', {
    name: 'Create profile and continue',
  }).click()
  await expect(page).toHaveURL(/\/audits\/new\/intake$/u)
  await expect(page.getByRole('heading', {
    level: 1,
    name: 'Add source material',
  })).toBeVisible()

  await page.getByRole('textbox', { name: 'Local source text' }).fill(
    [
      'name,Synthetic Orion,current,Primary name',
      'username,synthetic_orbit_742,current,Primary username',
      'url,https://profile.example.invalid/synthetic_orbit_742,current,Known profile',
      'Synthetic Orion works at Synthetic Research Cooperative.',
      'Synthetic Orion is based in Example City.',
    ].join('\n'),
  )
  await page.getByRole('button', { name: 'Extract locally' }).click()
  await expect(page.getByText('Local extraction ready for review.')).toBeVisible()
  await capture(page, '02-local-intake', screenshots)

  await page.getByRole('link', { name: /Review candidates/u }).first().click()
  await expect(page).toHaveURL(/\/audits\/new\/entities$/u)
  await expect(page.getByText('synthetic_orbit_742').first()).toBeVisible()
  await capture(page, '03-entity-review', screenshots)

  const controls = page.getByRole('heading', {
    level: 2,
    name: 'Decision controls',
  }).locator('xpath=ancestor::section[1]')
  await controls.getByRole('combobox', { name: 'Decision' }).selectOption('CONFIRMED')
  await controls.getByRole('combobox', {
    name: 'Temporal state',
  }).selectOption('CURRENT')
  await controls.getByRole('combobox', {
    name: 'Search policy',
  }).selectOption('ALLOW')
  await controls.getByRole('combobox', {
    name: 'Transmission policy',
  }).selectOption('POLICY_CONTROLLED')
  await controls.getByRole('button', { name: 'Apply decision' }).click()
  await expect(page.getByText('Next: run the complete audit.')).toBeVisible()
  await page.getByRole('link', { name: /Continue to full audit/u }).click()

  await expect(page).toHaveURL(/\/people\?start=1$/u)
  await expect(page.getByRole('heading', {
    level: 1,
    name: profile.displayLabel,
  })).toBeVisible()
  await page.locator('#run-full-audit').scrollIntoViewIfNeeded()
  await capture(page, '04-audit-setup', screenshots)

  await page.locator('#run-full-audit').getByRole('button', {
    name: /^Start (?:deterministic audit|with .+)/u,
  }).click()
  await expect(page).toHaveURL(
    new RegExp(`/identity/audits/${completedDetail.audit.auditId}$`, 'u'),
  )
  await expect(page.getByText(
    /Executing the next bounded task batch/u,
  )).toBeVisible()
  await capture(page, '05-durable-progress', screenshots)

  await expect(page.getByRole('heading', {
    level: 2,
    name: 'Finish this audit',
  })).toBeVisible()
  await expect(page.getByText(
    'https://profile.example.invalid/synthetic-result',
  )).toBeVisible()
  await page.getByRole('heading', {
    level: 2,
    name: '1 discovered results',
  }).evaluate((element) => element.scrollIntoView({ block: 'start' }))
  await capture(page, '06-exact-source-review', screenshots)

  await page.getByRole('tab', { name: 'AI analysis (1)' }).click()
  await expect(page.getByText('Synthetic cited analysis')).toBeVisible()
  await expect(page.getByText('result:synthetic-1').first()).toBeVisible()
  await page.getByRole('heading', {
    level: 2,
    name: 'Synthetic cited analysis',
  }).evaluate((element) => element.scrollIntoView({ block: 'start' }))
  await capture(page, '07-cited-ai-review', screenshots)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Generate and download' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(
    `ariadne-audit-${completedDetail.audit.auditId}.md`,
  )
  await expect(page.getByText(download.suggestedFilename())).toBeVisible()
  if (artifactRoot !== null) {
    await download.saveAs(`${artifactRoot}/${download.suggestedFilename()}`)
  }
  await capture(page, '08-final-cited-package', screenshots)

  expect(problems, problems.join('\n')).toEqual([])
  if (artifactRoot !== null) {
    await writeFile(
      `${artifactRoot}/manifest.json`,
      `${JSON.stringify({
        pass: screenshotPass,
        fixture: 'synthetic-primary-workflow-v2',
        viewport: { width: 1720, height: 1000 },
        screenshots,
        downloadedArtifact: download.suggestedFilename(),
        externalRequests: 0,
        runtimeProblems: problems,
      }, null, 2)}\n`,
      'utf8',
    )
  }
})
