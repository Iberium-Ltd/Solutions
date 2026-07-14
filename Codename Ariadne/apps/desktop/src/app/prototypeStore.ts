import { create } from 'zustand'

type PrototypeState = {
  sidebarCollapsed: boolean
  simulationPaused: boolean
  reducedMotion: boolean
  selectedTool: string
  transmissionMode: 'local' | 'eu' | 'worldwide' | 'custom'
  toggleSidebar: () => void
  toggleSimulation: () => void
  toggleReducedMotion: () => void
  selectTool: (tool: string) => void
  setTransmissionMode: (mode: PrototypeState['transmissionMode']) => void
}

export const usePrototypeStore = create<PrototypeState>((set) => ({
  sidebarCollapsed: false,
  simulationPaused: false,
  reducedMotion: false,
  selectedTool: 'Username Sweep',
  transmissionMode: 'local',
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  toggleSimulation: () =>
    set((state) => ({ simulationPaused: !state.simulationPaused })),
  toggleReducedMotion: () =>
    set((state) => ({ reducedMotion: !state.reducedMotion })),
  selectTool: (tool) => set({ selectedTool: tool }),
  setTransmissionMode: (mode) => set({ transmissionMode: mode }),
}))

