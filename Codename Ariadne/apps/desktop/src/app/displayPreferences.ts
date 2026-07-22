/**
 * Local presentation preferences only. Values are revalidated when loaded and
 * expressed as root attributes so every screen responds to one coherent scale.
 */
import { create } from 'zustand'

export const FONT_SCALE_OPTIONS = [90, 100, 110, 125, 140] as const
export const DISPLAY_PRESET_OPTIONS = [
  'auto',
  'laptop',
  'standard',
  'ultrawide',
] as const

export type FontScale = (typeof FONT_SCALE_OPTIONS)[number]
export type DisplayPreset = (typeof DISPLAY_PRESET_OPTIONS)[number]

export type ThemePreference = 'dark' | 'light'

export interface DisplayPreferences {
  readonly fontScale: FontScale
  readonly displayPreset: DisplayPreset
  readonly theme: ThemePreference
}

interface DisplayPreferencesState extends DisplayPreferences {
  setFontScale: (fontScale: FontScale) => void
  setDisplayPreset: (displayPreset: DisplayPreset) => void
  setTheme: (theme: ThemePreference) => void
  reloadFromStorage: () => void
}

export const DISPLAY_PREFERENCES_STORAGE_KEY =
  'ariadne.display-preferences.v1'

export const DEFAULT_DISPLAY_PREFERENCES: DisplayPreferences = {
  fontScale: 100,
  displayPreset: 'auto',
  theme: 'dark',
}

function isFontScale(value: unknown): value is FontScale {
  return FONT_SCALE_OPTIONS.some((option) => option === value)
}

function isDisplayPreset(value: unknown): value is DisplayPreset {
  return DISPLAY_PRESET_OPTIONS.some((option) => option === value)
}

function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'dark' || value === 'light'
}

export function readDisplayPreferences(
  storage?: Pick<Storage, 'getItem'>,
): DisplayPreferences {
  let activeStorage = storage
  if (activeStorage === undefined && typeof window !== 'undefined') {
    try {
      activeStorage = window.localStorage
    } catch {
      return DEFAULT_DISPLAY_PREFERENCES
    }
  }
  if (activeStorage === undefined) return DEFAULT_DISPLAY_PREFERENCES

  try {
    const stored = activeStorage.getItem(DISPLAY_PREFERENCES_STORAGE_KEY)
    if (stored === null) return DEFAULT_DISPLAY_PREFERENCES
    const candidate = JSON.parse(stored) as Record<string, unknown>
    return {
      fontScale: isFontScale(candidate.fontScale)
        ? candidate.fontScale
        : DEFAULT_DISPLAY_PREFERENCES.fontScale,
      displayPreset: isDisplayPreset(candidate.displayPreset)
        ? candidate.displayPreset
        : DEFAULT_DISPLAY_PREFERENCES.displayPreset,
      theme: isThemePreference(candidate.theme)
        ? candidate.theme
        : DEFAULT_DISPLAY_PREFERENCES.theme,
    }
  } catch {
    return DEFAULT_DISPLAY_PREFERENCES
  }
}

function persistDisplayPreferences(preferences: DisplayPreferences) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      DISPLAY_PREFERENCES_STORAGE_KEY,
      JSON.stringify(preferences),
    )
  } catch {
    // A blocked or full storage area must not prevent display changes.
  }
}

export function applyDisplayPreferences(
  preferences: DisplayPreferences,
  root: HTMLElement = document.documentElement,
) {
  root.dataset.fontScale = String(preferences.fontScale)
  root.dataset.displayPreset = preferences.displayPreset
  root.dataset.theme = preferences.theme
  root.style.setProperty('--font-scale', String(preferences.fontScale / 100))
}

const initialPreferences = readDisplayPreferences()

export const useDisplayPreferences = create<DisplayPreferencesState>((set) => ({
  ...initialPreferences,
  setFontScale: (fontScale) => {
    set((state) => {
      const preferences = {
        fontScale,
        displayPreset: state.displayPreset,
        theme: state.theme,
      }
      persistDisplayPreferences(preferences)
      return preferences
    })
  },
  setDisplayPreset: (displayPreset) => {
    set((state) => {
      const preferences = {
        fontScale: state.fontScale,
        displayPreset,
        theme: state.theme,
      }
      persistDisplayPreferences(preferences)
      return preferences
    })
  },
  setTheme: (theme) => {
    set((state) => {
      const preferences = {
        fontScale: state.fontScale,
        displayPreset: state.displayPreset,
        theme,
      }
      persistDisplayPreferences(preferences)
      return preferences
    })
  },
  reloadFromStorage: () => set(readDisplayPreferences()),
}))

export function initializeDisplayPreferences() {
  const { fontScale, displayPreset, theme } = useDisplayPreferences.getState()
  applyDisplayPreferences({ fontScale, displayPreset, theme })
}
