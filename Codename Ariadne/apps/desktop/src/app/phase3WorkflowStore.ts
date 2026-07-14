import { create } from 'zustand'

type Phase3WorkflowState = {
  profileId: string | null
  sourceId: string | null
  setProfileId: (profileId: string) => void
  setSourceId: (sourceId: string) => void
  clearSource: () => void
  reset: () => void
}

/**
 * Ephemeral navigation state for the native intake workflow.
 *
 * This store deliberately has no persistence middleware: only opaque identifiers
 * live here, and they disappear when the webview is reloaded or closed.
 */
export const usePhase3WorkflowStore = create<Phase3WorkflowState>((set) => ({
  profileId: null,
  sourceId: null,
  setProfileId: (profileId) =>
    set((current) =>
      current.profileId === profileId
        ? current
        : { profileId, sourceId: null },
    ),
  setSourceId: (sourceId) => set({ sourceId }),
  clearSource: () => set({ sourceId: null }),
  reset: () => set({ profileId: null, sourceId: null }),
}))

/** Synchronously revoke all Phase 3 navigation capabilities on vault lock. */
export function clearPhase3WorkflowMemory(): void {
  usePhase3WorkflowStore.getState().reset()
}
