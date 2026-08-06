/** Shared navigation and vault-state shell; route content owns domain operations. */
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import {
  Activity,
  Bell,
  Binary,
  BrainCircuit,
  Moon,
  BriefcaseBusiness,
  ChevronRight,
  Command,
  DatabaseZap,
  FileSearch,
  FileStack,
  FileText,
  GitCompareArrows,
  Globe2,
  HardDrive,
  HelpCircle,
  LayoutDashboard,
  LockKeyhole,
  Map,
  Menu,
  Network,
  Plus,
  Radar,
  Search,
  Settings2,
  ShieldCheck,
  Sun,
  UserRound,
  Wrench,
} from 'lucide-react'
import * as Tooltip from '@radix-ui/react-tooltip'
import { syntheticProfile, syntheticRun } from '@ariadne/synthetic-data'
import { AriadneMark } from './AriadneMark'
import { Badge, Button, Progress, SyntheticBanner } from './Primitives'
import { usePrototypeStore } from '../app/prototypeStore'
import { useCoreBoundary } from '../app/coreBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import {
  applyDisplayPreferences,
  DISPLAY_PREFERENCES_STORAGE_KEY,
  useDisplayPreferences,
} from '../app/displayPreferences'
import { NativeProfileSwitcher } from './ProfileSwitcher'
import { useIdentityOverview } from '../app/useIdentityOverview'
import { getLocalAISettings, unloadLocalAIModel } from '../app/localAiBoundary'

/** Explicitly release the selected local model while keeping its saved choice. */
function LocalModelControl() {
  const [settings, setSettings] = useState<Awaited<ReturnType<typeof getLocalAISettings>> | null>(null)
  const [pending, setPending] = useState(false)
  const [unloaded, setUnloaded] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    void getLocalAISettings().then((value) => {
      if (active) setSettings(value)
    }).catch(() => undefined)
    return () => { active = false }
  }, [])

  if (!settings?.enabled || !settings.selectedModel) return null
  const label = unloaded
    ? `${settings.selectedModel} is unloaded; Ariadne will load it on the next AI action`
    : error
      ? `The model could not be unloaded; retry ${settings.selectedModel}`
    : `Release selected local model ${settings.selectedModel} if it is resident`
  return (
    <button
      className="icon-button"
      type="button"
      aria-label={label}
      title={label}
      disabled={pending || unloaded}
      onClick={() => {
        setPending(true)
        setError(false)
        void unloadLocalAIModel({
          provider: settings.provider,
          endpoint: settings.endpoint,
          selectedModel: settings.selectedModel,
        }).then((result) => {
          if (result.status === 'UNLOADED') setUnloaded(true)
        }).catch(() => setError(true)).finally(() => setPending(false))
      }}
    >
      <BrainCircuit size={17} />
      {!unloaded && <span className="model-loaded-dot" />}
    </button>
  )
}

/** Small audit-backed notification tray; no placeholder alerts are fabricated. */
function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const overview = useIdentityOverview()
  const notices = overview.status === 'READY'
    ? [
        overview.audit.audit.state === 'PARTIAL'
          ? `Audit “${overview.audit.audit.name}” finished partially.`
          : null,
        overview.audit.proposals.length > 0
          ? `${overview.audit.proposals.length} audit proposals are available for review.`
          : null,
        overview.audit.tasks.some((task) => ['BLOCKED', 'AUTH_REQUIRED', 'RATE_LIMITED'].includes(task.state))
          ? 'One or more provider tasks need access or retry review.'
          : null,
        overview.audit.aiAnalysis?.status === 'FALLBACK'
          ? 'Local AI analysis used a deterministic fallback; open the audit for the reason.'
          : null,
      ].filter((notice): notice is string => notice !== null)
    : []

  useEffect(() => {
    if (!open) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open])

  return (
    <div className="topbar-notifications">
      <button
        className="icon-button"
        type="button"
        aria-label="Open notifications"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Bell size={17} />
        {notices.length > 0 && <span className="notification-dot" />}
      </button>
      {open && (
        <div className="notification-popover" role="dialog" aria-label="Audit notifications">
          <strong>Notifications</strong>
          {overview.status === 'LOADING' ? <p>Checking the latest audit…</p>
            : overview.status === 'ERROR' ? <p>{overview.error}</p>
              : notices.length === 0 ? <p>No audit notifications.</p>
                : <ul>{notices.map((notice) => <li key={notice}>{notice}</li>)}</ul>}
        </div>
      )}
    </div>
  )
}

const navGroups = [
  {
    label: 'Overview',
    items: [
      { label: 'Mission Control', to: '/dashboard', icon: LayoutDashboard },
      { label: 'People', to: '/people', icon: UserRound },
      { label: 'Import identifiers', to: '/audits/new', icon: Plus },
      { label: 'Operations', to: '/operations/latest', icon: Activity },
      { label: 'Findings', to: '/findings', icon: FileSearch, count: 6 },
    ],
  },
  {
    label: 'Advanced',
    items: [
      { label: 'Discovery Console', to: '/tools', icon: Wrench },
      { label: 'AI Workspace', to: '/ai/workspace', icon: BrainCircuit },
      { label: 'Corpus AI', to: '/ai/corpus', icon: FileStack },
      { label: 'Link Map', to: '/graph', icon: Network },
      { label: 'Geographic Map', to: '/map', icon: Map },
      {
        label: 'Case Desk',
        to: '/cases/impersonation/current',
        icon: BriefcaseBusiness,
      },
    ],
  },
  {
    label: 'Track',
    items: [
      { label: 'Compare Runs', to: '/compare', icon: GitCompareArrows },
      { label: 'Removal Tracker', to: '/remediation', icon: DatabaseZap, count: 4 },
      { label: 'Reports', to: '/reports', icon: FileText },
    ],
  },
  {
    label: 'Control',
    items: [
      { label: 'Source Coverage', to: '/providers', icon: Radar },
      { label: 'Transmission Preflight', to: '/privacy/transmission', icon: Globe2 },
      { label: 'Privacy & Settings', to: '/settings/privacy', icon: Settings2 },
      { label: 'Getting started', to: '/help/getting-started', icon: HelpCircle },
    ],
  },
] as const

const routeNames: Array<[RegExp, string]> = [
  [/^\/dashboard/, 'Mission Control'],
  [/^\/audits\/new\/intake/, 'Intake'],
  [/^\/audits\/new\/entities/, 'Entity Review'],
  [/^\/audits\/new/, 'New Audit'],
  [/^\/identity\/audits\//, 'Identity Audit'],
  [/^\/people/, 'People'],
  [/^\/tools/, 'Discovery Console'],
  [/^\/ai\/corpus/, 'Corpus AI'],
  [/^\/ai\/workspace/, 'AI Workspace'],
  [/^\/operations/, 'Live Operations'],
  [/^\/findings\//, 'Finding Detail'],
  [/^\/findings/, 'Findings'],
  [/^\/graph/, 'Link Map'],
  [/^\/map/, 'Geographic Map'],
  [/^\/cases/, 'Case Desk'],
  [/^\/compare/, 'Compare Runs'],
  [/^\/remediation/, 'Removal Tracker'],
  [/^\/reports/, 'Reports'],
  [/^\/providers/, 'Source Coverage'],
  [/^\/privacy\/transmission/, 'Transmission Preflight'],
  [/^\/settings/, 'Privacy & Settings'],
  [/^\/help\/getting-started/, 'Getting Started'],
  [/^\/states/, 'State Laboratory'],
]

const nativeVaultRoutes = [
  /^\/new-audit/,
  /^\/people/,
  /^\/dashboard/,
  /^\/identity\/audits/,
  /^\/audits\/new\/intake/,
  /^\/audits\/new\/entities/,
  /^\/findings/,
  /^\/graph/,
  /^\/map/,
  /^\/tools/,
  /^\/ai\/corpus/,
  /^\/ai\/workspace/,
  /^\/compare/,
  /^\/remediation/,
  /^\/reports/,
  /^\/operations/,
  /^\/providers/,
  /^\/cases/,
  /^\/privacy\/transmission/,
  /^\/settings/,
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const redirectAfterVaultCreation = useRef(false)
  const {
    sidebarCollapsed,
    toggleSidebar,
    reducedMotion,
    simulationPaused,
  } = usePrototypeStore()
  const coreBoundary = useCoreBoundary()
  const activeProfileId = usePhase3WorkflowStore((state) => state.profileId)
  const fontScale = useDisplayPreferences((state) => state.fontScale)
  const displayPreset = useDisplayPreferences((state) => state.displayPreset)
  const theme = useDisplayPreferences((state) => state.theme)
  const setTheme = useDisplayPreferences((state) => state.setTheme)
  const reloadDisplayPreferences = useDisplayPreferences(
    (state) => state.reloadFromStorage,
  )
  const routeName =
    routeNames.find(([pattern]) => pattern.test(location.pathname))?.[1] ??
    'Workspace'
  const liveSession =
    coreBoundary.state.mode === 'AVAILABLE'
      ? coreBoundary.state.session
      : undefined
  const vaultStatus = liveSession
    ? coreBoundary.vaultActionPending
      ? liveSession.vaultState === 'NO_VAULT'
        ? 'Creating'
        : liveSession.lockState === 'UNLOCKED'
          ? 'Locking'
          : 'Unlocking'
      : liveSession.vaultState === 'NO_VAULT'
        ? 'No vault'
        : liveSession.lockState === 'UNLOCKED'
          ? 'Unlocked'
          : liveSession.lockState === 'LOCKING'
            ? 'Locking'
            : 'Locked'
    : coreBoundary.state.mode === 'CONNECTING'
      ? 'Checking'
      : coreBoundary.state.mode === 'UNAVAILABLE'
        ? 'Unavailable'
        : 'Unlocked'
  const coreStatus =
    coreBoundary.state.mode === 'AVAILABLE'
      ? 'local service'
      : coreBoundary.state.mode === 'CONNECTING'
        ? 'connecting'
        : coreBoundary.state.mode === 'UNAVAILABLE'
          ? 'unavailable'
          : 'simulated'
  const vaultProtectionStatus = liveSession
    ? liveSession.vaultState === 'NO_VAULT'
      ? 'No vault configured'
      : 'Vault protected'
    : coreBoundary.state.mode === 'CONNECTING'
      ? 'Checking vault'
      : coreBoundary.state.mode === 'UNAVAILABLE'
        ? 'Core unavailable'
        : 'Vault protected'
  const vaultAction = liveSession
    ? liveSession.vaultState === 'NO_VAULT'
      ? {
          label: 'Create local vault',
          run: coreBoundary.createVault,
        }
      : liveSession.lockState === 'LOCKED'
        ? {
            label: 'Unlock local vault',
            run: coreBoundary.unlockVault,
          }
        : liveSession.lockState === 'UNLOCKED'
          ? {
              label: 'Lock local vault',
              run: coreBoundary.lock,
            }
          : null
    : null
  const workspaceUnlocked =
    coreBoundary.state.mode === 'SIMULATED' ||
    (liveSession?.lockState === 'UNLOCKED' &&
      !coreBoundary.vaultActionPending)
  const gettingStartedRoute = location.pathname.startsWith(
    '/help/getting-started',
  )
  const nativeVaultRoute = nativeVaultRoutes.some((pattern) =>
    pattern.test(location.pathname),
  )
  const workspaceScopeKey =
    coreBoundary.state.mode === 'SIMULATED'
      ? 'synthetic-profile'
      : (activeProfileId ?? 'no-active-profile')
  const vaultCardContents = (
    <>
      <div className="vault-card__icon">
        <LockKeyhole size={16} />
      </div>
      <div className="vault-card__copy">
        <span>
          {liveSession?.vaultState === 'NO_VAULT'
            ? 'Setup required'
            : 'Local vault'}
        </span>
        <strong>
          {liveSession?.vaultState === 'NO_VAULT'
            ? 'Create local vault'
            : liveSession?.lockState === 'LOCKED'
              ? 'Unlock local vault'
              : vaultStatus}
        </strong>
      </div>
      <span
        className={clsx(
          'vault-card__pulse',
          liveSession?.vaultState === 'NO_VAULT' && 'is-setup',
          liveSession?.vaultState !== 'NO_VAULT' &&
            liveSession?.lockState === 'LOCKED' &&
            'is-locked',
        )}
        aria-hidden="true"
      />
    </>
  )

  const runVaultAction = () => {
    if (!vaultAction) return
    if (liveSession?.vaultState === 'NO_VAULT') {
      redirectAfterVaultCreation.current = true
    }
    void vaultAction.run()
  }

  useEffect(() => {
    if (
      redirectAfterVaultCreation.current &&
      liveSession?.vaultState === 'UNLOCKED' &&
      liveSession.lockState === 'UNLOCKED'
    ) {
      redirectAfterVaultCreation.current = false
      navigate('/audits/new')
    }
  }, [liveSession, navigate])

  useEffect(() => {
    applyDisplayPreferences({ fontScale, displayPreset, theme })
  }, [displayPreset, fontScale, theme])

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (
        event.key === null ||
        event.key === DISPLAY_PREFERENCES_STORAGE_KEY
      ) {
        reloadDisplayPreferences()
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [reloadDisplayPreferences])

  useEffect(() => {
    const systemPreference = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    )
    const searchParams = new URLSearchParams(location.search)
    const fixtureReduced =
      searchParams.get('scenario') === 'reduced-motion' ||
      searchParams.get('case') === 'reduced-motion'
    const applyMotionPreference = () => {
      document.documentElement.dataset.motion =
        reducedMotion || fixtureReduced || systemPreference.matches
          ? 'reduced'
          : 'full'
    }

    applyMotionPreference()
    systemPreference.addEventListener('change', applyMotionPreference)
    return () => {
      systemPreference.removeEventListener('change', applyMotionPreference)
    }
  }, [location.search, reducedMotion])

  useEffect(() => {
    document.title = `${routeName} · Codename Ariadne`
    document.documentElement.dataset.captureReady = 'false'
    const frame = requestAnimationFrame(() => {
      document.documentElement.dataset.captureReady = 'true'
    })
    return () => {
      cancelAnimationFrame(frame)
      document.documentElement.dataset.captureReady = 'false'
    }
  }, [location.pathname, routeName])

  useEffect(() => {
    const main = document.querySelector<HTMLElement>('#main-content')
    let observer: MutationObserver | undefined
    const focusReadyTitle = () => {
      if (!main?.querySelector('[data-testid="route-ready"]')) return false
      main
        .querySelector<HTMLElement>('#page-title')
        ?.focus({ preventScroll: true })
      observer?.disconnect()
      return true
    }

    if (!focusReadyTitle() && main) {
      observer = new MutationObserver(focusReadyTitle)
      observer.observe(main, { childList: true, subtree: true })
    }
    return () => observer?.disconnect()
  }, [location.pathname])

  return (
    <Tooltip.Provider delayDuration={250}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div
        className={clsx(
          'app-shell',
          sidebarCollapsed && 'app-shell--collapsed',
          coreBoundary.state.mode !== 'SIMULATED' &&
            'app-shell--native-runtime',
        )}
        data-display-preset={displayPreset}
        data-font-scale={fontScale}
        data-theme={theme}
        data-app-ready="true"
      >
        <aside className="sidebar" aria-label="Primary navigation">
          <div className="brand">
            <AriadneMark className="brand__mark" />
            <div className="brand__copy">
              <strong>CODENAME</strong>
              <span>ARIADNE</span>
            </div>
            <Tooltip.Root>
              <Tooltip.Trigger asChild>
                <button
                  className="icon-button sidebar__collapse"
                  onClick={toggleSidebar}
                  aria-label="Toggle navigation width"
                >
                  <Menu size={17} />
                </button>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content className="tooltip" side="right">
                  Toggle navigation
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          </div>

          <Link
            to={
              coreBoundary.state.mode === 'SIMULATED'
                ? '/audits/new'
                : '/audits/new'
            }
            className="new-audit-button"
            aria-label={
              coreBoundary.state.mode === 'SIMULATED'
                ? 'New audit'
                : 'Import identifiers'
            }
          >
            <Plus size={17} />
            <span>
              {coreBoundary.state.mode === 'SIMULATED'
                ? 'New audit'
                : 'Import'}
            </span>
            <kbd>⌘N</kbd>
          </Link>

          <nav className="nav-groups">
            {navGroups.map((group) => (
              <div className="nav-group" key={group.label}>
                <span className="nav-group__label">{group.label}</span>
                {group.items.map((item) => {
                  const Icon = item.icon
                  const isActive =
                    location.pathname === item.to ||
                    (item.to !== '/dashboard' &&
                      location.pathname.startsWith(`${item.to}/`)) ||
                    (item.to === '/operations/latest' &&
                      location.pathname.startsWith('/operations/')) ||
                    (item.to === '/cases/impersonation/current' &&
                      location.pathname.startsWith('/cases/'))
                  return (
                    <Tooltip.Root key={item.to}>
                      <Tooltip.Trigger asChild>
                        <Link
                          to={item.to}
                          className={clsx('nav-item', isActive && 'is-active')}
                          aria-label={item.label}
                          aria-current={isActive ? 'page' : undefined}
                        >
                          <Icon size={17} strokeWidth={1.8} />
                          <span className="nav-item__label">{item.label}</span>
                          {coreBoundary.state.mode === 'SIMULATED' &&
                          'count' in item &&
                          item.count ? (
                            <span className="nav-item__count">{item.count}</span>
                          ) : null}
                        </Link>
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content className="tooltip" side="right">
                          {item.label}
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
                  )
                })}
              </div>
            ))}
          </nav>

          {vaultAction ? (
            <button
              className="vault-card"
              type="button"
              onClick={runVaultAction}
              disabled={coreBoundary.vaultActionPending}
              aria-label={vaultAction.label}
              aria-busy={coreBoundary.vaultActionPending}
            >
              {vaultCardContents}
            </button>
          ) : (
            <div className="vault-card" aria-live="polite">
              {vaultCardContents}
            </div>
          )}
          {coreBoundary.vaultActionError && (
            <div className="vault-card-error" role="alert">
              {coreBoundary.vaultActionError}
            </div>
          )}
        </aside>

        <div className="workspace">
          <header className="topbar">
            <div className="breadcrumbs" aria-label="Breadcrumb">
              <span>Workspace</span>
              <ChevronRight size={13} />
              <strong>{routeName}</strong>
            </div>
            <div className="topbar__actions">
              <button
                className="command-search"
                type="button"
                aria-label="Open command search"
              >
                <Search size={15} />
                <span>Search commands</span>
                <kbd>
                  <Command size={11} />K
                </kbd>
              </button>
              <Badge tone="green" dot>
                Local only
              </Badge>
              {workspaceUnlocked && <LocalModelControl />}
              <button
                className="icon-button"
                type="button"
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                aria-pressed={theme === 'light'}
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              >
                {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
              </button>
              {workspaceUnlocked ? <NotificationCenter /> : (
                <button className="icon-button" type="button" aria-label="Notifications unavailable while vault is locked" disabled>
                  <Bell size={17} />
                </button>
              )}
              {coreBoundary.state.mode === 'SIMULATED' ? (
                <button
                  className="profile-chip"
                  type="button"
                  aria-label="Open synthetic profile menu"
                >
                  <span>{syntheticProfile.initials}</span>
                  <div>
                    <strong>{syntheticProfile.name}</strong>
                    <small>Synthetic profile</small>
                  </div>
                </button>
              ) : workspaceUnlocked ? (
                <NativeProfileSwitcher />
              ) : (
                <div
                  className="profile-switcher profile-switcher--protected"
                  aria-label="Local profiles protected"
                >
                  <span aria-hidden="true">LP</span>
                  <div>
                    <strong>
                      {liveSession?.vaultState === 'NO_VAULT'
                        ? 'Vault setup required'
                        : 'Profiles protected'}
                    </strong>
                    <small>
                      {liveSession?.vaultState === 'NO_VAULT'
                        ? 'Create local vault to begin'
                        : 'Unlock the local vault'}
                    </small>
                  </div>
                </div>
              )}
            </div>
          </header>

          <div className="contextbar">
            {coreBoundary.state.mode === 'SIMULATED' ? (
              <SyntheticBanner compact />
            ) : !workspaceUnlocked ? (
              <div className="surface-banner surface-banner--setup">
                <LockKeyhole size={14} aria-hidden="true" />
                <span>Native app setup · local vault required</span>
              </div>
            ) : gettingStartedRoute ? (
              <div className="surface-banner surface-banner--guide">
                <HelpCircle size={14} aria-hidden="true" />
                <span>Getting-started guide · no vault records shown</span>
              </div>
            ) : nativeVaultRoute ? (
              <div className="surface-banner surface-banner--native">
                <HardDrive size={14} aria-hidden="true" />
                <span>Native vault-backed screen</span>
              </div>
            ) : (
              <div className="surface-banner surface-banner--synthetic">
                <ShieldCheck size={14} aria-hidden="true" />
                <span>Synthetic demonstration · not your vault data</span>
              </div>
            )}
            <div className="contextbar__right">
              <ShieldCheck size={14} />
              <span>{vaultProtectionStatus}</span>
              <span className="contextbar__separator" />
              <Binary size={14} />
              <span>Ariadne Core · {coreStatus}</span>
            </div>
          </div>

          <main
            id="main-content"
            className="main-content"
            aria-labelledby="page-title"
          >
            {workspaceUnlocked || gettingStartedRoute ? (
              <Fragment key={workspaceScopeKey}>{children}</Fragment>
            ) : (
              <div
                className="page protected-workspace"
                data-testid="vault-workspace-guard"
              >
                <h1 id="page-title" data-testid="route-ready" tabIndex={-1}>
                  {liveSession?.vaultState === 'NO_VAULT'
                    ? 'Create your local vault'
                    : liveSession?.lockState === 'LOCKED'
                      ? 'Unlock your local vault'
                      : coreBoundary.state.mode === 'CONNECTING'
                        ? 'Connecting to Ariadne Core'
                        : coreBoundary.state.mode === 'UNAVAILABLE'
                          ? 'Local service unavailable'
                          : 'Local workspace protected'}
                </h1>
                <p>
                  {liveSession?.vaultState === 'NO_VAULT'
                    ? 'This one-time step creates the encrypted workspace Ariadne needs before you can add source material.'
                    : liveSession?.lockState === 'LOCKED'
                      ? 'Unlock your existing encrypted workspace to continue. Ariadne has not started a background audit.'
                      : coreBoundary.state.mode === 'CONNECTING'
                        ? 'The native app is starting its local service. No external request is being made.'
                        : coreBoundary.state.mode === 'UNAVAILABLE'
                          ? 'Ariadne could not reach its bundled local service. Restart the app, then try again.'
                          : 'The local vault is changing state. Your workspace remains protected.'}
                </p>
                {vaultAction ? (
                  <div className="protected-workspace__actions">
                    <Button
                      variant="primary"
                      onClick={runVaultAction}
                      disabled={coreBoundary.vaultActionPending}
                      aria-busy={coreBoundary.vaultActionPending}
                    >
                      {liveSession?.vaultState === 'NO_VAULT'
                        ? 'Create vault and choose profile'
                        : 'Unlock and continue'}
                    </Button>
                    <Link
                      className="button button--secondary"
                      to="/help/getting-started"
                    >
                      View getting-started guide
                    </Link>
                  </div>
                ) : (
                  <Link
                    className="protected-workspace__guide-link"
                    to="/help/getting-started"
                  >
                    View the getting-started guide
                    <ChevronRight size={14} aria-hidden="true" />
                  </Link>
                )}
                <ol className="protected-workspace__steps" aria-label="First steps">
                  <li><strong>1. Vault</strong><span>Create or unlock local storage</span></li>
                  <li><strong>2. Intake</strong><span>Add source material</span></li>
                  <li><strong>3. Review</strong><span>Confirm entities and findings</span></li>
                </ol>
              </div>
            )}
          </main>

          {coreBoundary.state.mode === 'SIMULATED' ? (
            <div className="activity-strip" role="status" aria-live="polite">
              <div className="activity-strip__lead">
                <span
                  className={clsx(
                    'activity-dot',
                    simulationPaused && 'is-paused',
                  )}
                />
                <div>
                  <strong>
                    {simulationPaused
                      ? 'Simulation paused'
                      : syntheticRun.phase}
                  </strong>
                  <small>{syntheticRun.shortId} · no external requests</small>
                </div>
              </div>
              <Progress value={syntheticRun.progress} />
              <span className="activity-strip__value">
                {syntheticRun.progress}%
              </span>
              <Link
                to={`/operations/${syntheticRun.id}`}
                className="activity-strip__link"
              >
                Open console <ChevronRight size={14} />
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </Tooltip.Provider>
  )
}
