/**
 * Boots the React webview and installs routing.
 *
 * Native capability and vault checks occur inside App so startup can be tested
 * against either the real Tauri bridge or a closed synthetic transport.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter/index.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import './index.css'
import App from './App.tsx'
import { initializeDisplayPreferences } from './app/displayPreferences.ts'

initializeDisplayPreferences()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
