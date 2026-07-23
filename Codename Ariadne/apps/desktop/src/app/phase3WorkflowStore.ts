/**
 * Holds the navigation state shared by intake, review, and profile selection.
 *
 * Durable records stay in the encrypted core; lock handling clears transient
 * identifiers so stale workflow context cannot survive in webview memory.
 */
import { create } from 'zustand'

const ACTIVE_PROFILE_STORAGE_KEY = 'ariadne.active-profile-id.v1'

function rememberProfileId(profileId: string): void {
  try { globalThis.localStorage?.setItem(ACTIVE_PROFILE_STORAGE_KEY, profileId) } catch { /* unavailable storage is non-fatal */ }
}

export function rememberedProfileId(): string | null {
  try { return globalThis.localStorage?.getItem(ACTIVE_PROFILE_STORAGE_KEY) ?? null } catch { return null }
}

export function forgetRememberedProfile(): void {
  try { globalThis.localStorage?.removeItem(ACTIVE_PROFILE_STORAGE_KEY) } catch { /* unavailable storage is non-fatal */ }
}

type Phase3WorkflowState = {
  profileId: string | null
  sourceId: string | null
  setProfileId: (profileId: string) => void
  setSourceId: (sourceId: string) => void
  clearSource: () => void
  reset: () => void
}

/**
 * Ephemeral navigation capabilities for the native intake workflow.
 *
 * Only the last active opaque profile UUID is remembered across webview reloads,
 * then validated against the unlocked vault by ProfileSwitcher. Source authority
 * remains memory-only. Durable person knowledge and audit/frontier state belong
 * to the encrypted core; this store is never a source of truth for recoverable work.
 */
export const usePhase3WorkflowStore = create<Phase3WorkflowState>((set) => ({
  profileId: null,
  sourceId: null,
  setProfileId: (profileId) => {
    rememberProfileId(profileId)
    set((current) =>
      current.profileId === profileId
        ? current
        : { profileId, sourceId: null },
    )
  },
  setSourceId: (sourceId) => set({ sourceId }),
  clearSource: () => set({ sourceId: null }),
  reset: () => set({ profileId: null, sourceId: null }),
}))

/** Synchronously revoke all Phase 3 navigation capabilities on vault lock. */
export function clearPhase3WorkflowMemory(): void {
  usePhase3WorkflowStore.getState().reset()
}
