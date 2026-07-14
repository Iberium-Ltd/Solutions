import { useCallback, useEffect, useState } from 'react'
import type {
  SessionState,
  SystemCapabilities,
  VaultLifecycleResult,
} from '../../../../packages/contracts/src/generated/api'
import { clearPhase3WorkflowMemory } from './phase3WorkflowStore'

interface CommandResponse<T> {
  readonly requestId: string
  readonly data: T
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const FEATURE_KEYS = new Set([
  'authenticated_local_api',
  'database',
  'migrations',
  'encryption',
  'settings',
  'task_engine',
  'events',
  'import_export',
  'key_lease',
  'vault_lifecycle',
  'intake',
  'identity_compiler',
  'entity_review',
  'identity_graph',
  'local_ai',
  'query_policy',
  'public_discovery',
  'evidence',
  'attribution',
  'audit_comparison',
  'remediation',
])
const FEATURE_STATUSES = new Set([
  'AVAILABLE',
  'NOT_IMPLEMENTED',
  'UNAVAILABLE',
])
const SESSION_POLL_INTERVAL_MS = 1_000

export function nativeRuntimeAvailable(): boolean {
  return Boolean((globalThis as { isTauri?: boolean }).isTauri)
}

async function invokeNative<T>(
  command: string,
  arguments_: Record<string, unknown> | undefined = undefined,
): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return arguments_ === undefined
    ? invoke<T>(command)
    : invoke<T>(command, arguments_)
}

type CoreBoundaryState =
  | { readonly mode: 'SIMULATED' }
  | { readonly mode: 'CONNECTING' }
  | {
      readonly mode: 'AVAILABLE'
      readonly capabilities: SystemCapabilities
      readonly session: SessionState
    }
  | { readonly mode: 'UNAVAILABLE' }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function commandData(value: unknown): unknown {
  if (!isRecord(value) || !UUID_PATTERN.test(String(value.requestId))) {
    throw new Error('Core command response is invalid')
  }
  return value.data
}

function parseCapabilities(value: unknown): SystemCapabilities {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !isRecord(data.versions) ||
    data.versions.contract !== 1 ||
    data.versions.schema !== 'ariadne-v1' ||
    data.versions.events !== 1 ||
    data.versions.core !== '0.1.0' ||
    (data.transport !== 'DEV_LOOPBACK' && data.transport !== 'UNIX_SOCKET') ||
    !isRecord(data.cipher) ||
    data.cipher.required !== 'SQLCIPHER' ||
    typeof data.cipher.available !== 'boolean' ||
    !(
      data.cipher.sqliteVersion === null ||
      typeof data.cipher.sqliteVersion === 'string'
    ) ||
    !(
      data.cipher.cipherVersion === null ||
      typeof data.cipher.cipherVersion === 'string'
    ) ||
    !Array.isArray(data.features) ||
    !data.features.every(
      (feature) =>
        isRecord(feature) &&
        FEATURE_KEYS.has(String(feature.key)) &&
        FEATURE_STATUSES.has(String(feature.status)),
    )
  ) {
    throw new Error('Core capabilities are invalid')
  }
  return data as unknown as SystemCapabilities
}

function parseSession(value: unknown): SessionState {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !['LOCKED', 'UNLOCKED', 'LOCKING'].includes(String(data.lockState)) ||
    !['NO_VAULT', 'LOCKED', 'UNLOCKED', 'UNAVAILABLE'].includes(
      String(data.vaultState),
    ) ||
    data.authenticatedTransport !== true ||
    data.compatibility !== 'COMPATIBLE' ||
    !(
      data.sessionExpiresAt === null ||
      typeof data.sessionExpiresAt === 'string'
    ) ||
    !Number.isSafeInteger(data.activeRevealCapabilities) ||
    Number(data.activeRevealCapabilities) < 0
  ) {
    throw new Error('Core session is invalid')
  }
  return data as unknown as SessionState
}

function parseLifecycle(value: unknown): VaultLifecycleResult {
  const data = commandData(value)
  if (
    !isRecord(data) ||
    !UUID_PATTERN.test(String(data.vaultId)) ||
    !['LOCKED', 'UNLOCKED'].includes(String(data.lockState)) ||
    data.lockState !== data.vaultState
  ) {
    throw new Error('Core lifecycle response is invalid')
  }
  return data as unknown as VaultLifecycleResult
}

export function useCoreBoundary() {
  const native = nativeRuntimeAvailable()
  const [state, setState] = useState<CoreBoundaryState>(
    native ? { mode: 'CONNECTING' } : { mode: 'SIMULATED' },
  )
  const [vaultActionPending, setVaultActionPending] = useState(false)
  const [vaultActionError, setVaultActionError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!native) return true
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const [capabilities, session] = await Promise.all([
        invoke<CommandResponse<SystemCapabilities>>('core_capabilities'),
        invoke<CommandResponse<SessionState>>('core_session'),
      ])
      const parsedSession = parseSession(session)
      if (parsedSession.lockState !== 'UNLOCKED') {
        clearPhase3WorkflowMemory()
      }
      setState({
        mode: 'AVAILABLE',
        capabilities: parseCapabilities(capabilities),
        session: parsedSession,
      })
      return true
    } catch {
      return false
    }
  }, [native])

  const refreshUnlockedSession = useCallback(async () => {
    if (!native) return true
    try {
      const session = parseSession(
        await invokeNative<CommandResponse<SessionState>>('core_session'),
      )
      if (session.lockState !== 'UNLOCKED') {
        clearPhase3WorkflowMemory()
      }
      setState((current) =>
        current.mode === 'AVAILABLE' ? { ...current, session } : current,
      )
      return true
    } catch {
      return false
    }
  }, [native])

  useEffect(() => {
    if (!native || state.mode !== 'CONNECTING') return
    let cancelled = false
    let retryTimer: number | undefined
    let attempts = 0

    const connect = async () => {
      if ((await refresh()) || cancelled) return
      attempts += 1
      if (attempts >= 30) {
        setState({ mode: 'UNAVAILABLE' })
        return
      }
      retryTimer = window.setTimeout(() => void connect(), 1_000)
    }

    void connect()
    return () => {
      cancelled = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [native, refresh, state.mode])

  useEffect(() => {
    if (!native) return
    // A normal app-focus transition must not tear down the unlocked workspace.
    // Refresh in place so draft forms and active operations remain mounted while
    // the session is revalidated with Ariadne Core.
    const refreshOnFocus = () => void refresh()
    window.addEventListener('focus', refreshOnFocus)
    return () => window.removeEventListener('focus', refreshOnFocus)
  }, [native, refresh])

  useEffect(() => {
    if (
      !native ||
      state.mode !== 'AVAILABLE' ||
      state.session.lockState !== 'UNLOCKED'
    ) {
      return
    }
    let refreshPending = false
    const timer = window.setInterval(() => {
      if (refreshPending) return
      refreshPending = true
      void refreshUnlockedSession().then((refreshed) => {
        refreshPending = false
        if (!refreshed) setState({ mode: 'CONNECTING' })
      })
    }, SESSION_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [native, refreshUnlockedSession, state])

  const lock = useCallback(async () => {
    if (state.mode !== 'AVAILABLE' || state.session.lockState !== 'UNLOCKED') {
      return
    }
    clearPhase3WorkflowMemory()
    setVaultActionPending(true)
    setVaultActionError(null)
    try {
      parseLifecycle(
        await invokeNative<CommandResponse<VaultLifecycleResult>>(
          'core_lock_current_vault',
        ),
      )
      if (!(await refresh())) setState({ mode: 'CONNECTING' })
    } catch {
      setVaultActionError('The local vault could not be locked. Try again.')
    } finally {
      setVaultActionPending(false)
    }
  }, [refresh, state])

  const createVault = useCallback(async () => {
    if (state.mode !== 'AVAILABLE' || state.session.vaultState !== 'NO_VAULT') {
      return
    }
    setVaultActionPending(true)
    setVaultActionError(null)
    try {
      parseLifecycle(
        await invokeNative<CommandResponse<VaultLifecycleResult>>(
          'core_create_vault',
          { displayName: 'Local Ariadne vault' },
        ),
      )
      if (!(await refresh())) setState({ mode: 'CONNECTING' })
    } catch {
      setVaultActionError(
        'The local vault could not be created. Check system access and try again.',
      )
    } finally {
      setVaultActionPending(false)
    }
  }, [refresh, state])

  const unlockVault = useCallback(async () => {
    if (
      state.mode !== 'AVAILABLE' ||
      state.session.vaultState !== 'LOCKED' ||
      state.session.lockState !== 'LOCKED'
    ) {
      return
    }
    setVaultActionPending(true)
    setVaultActionError(null)
    try {
      parseLifecycle(
        await invokeNative<CommandResponse<VaultLifecycleResult>>(
          'core_unlock_current_vault',
        ),
      )
      if (!(await refresh())) setState({ mode: 'CONNECTING' })
    } catch {
      setVaultActionError(
        'The local vault could not be unlocked. Check system access and try again.',
      )
    } finally {
      setVaultActionPending(false)
    }
  }, [refresh, state])

  return {
    state,
    lock,
    createVault,
    unlockVault,
    vaultActionPending,
    vaultActionError,
  }
}

export const coreBoundaryParsers = {
  capabilities: parseCapabilities,
  session: parseSession,
  lifecycle: parseLifecycle,
}
