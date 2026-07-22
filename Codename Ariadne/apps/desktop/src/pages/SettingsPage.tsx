/** Local preferences, vault controls, and explicit optional-model configuration. */
import { useEffect, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  Database,
  Download,
  HardDrive,
  KeyRound,
  LockKeyhole,
  Monitor,
  Paintbrush,
  PlugZap,
  RefreshCw,
  Save,
  ShieldCheck,
  TimerReset,
  Trash2,
  WifiOff,
} from 'lucide-react'
import { Badge, Button, PageHeader, Panel, Progress } from '../components/Primitives'
import { Toggle } from '../components/Toggle'
import { usePrototypeStore } from '../app/prototypeStore'
import {
  DISPLAY_PRESET_OPTIONS,
  FONT_SCALE_OPTIONS,
  useDisplayPreferences,
  type DisplayPreset,
} from '../app/displayPreferences'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  discoverLocalAIModels,
  getLocalAISettings,
  isLoopbackLocalAIEndpoint,
  testLocalAIConnection,
  updateLocalAISettings,
} from '../app/localAiBoundary'
import type {
  LocalAIConnectionStatus,
  LocalAIProvider,
} from '../../../../packages/contracts/src/generated/api'
import '../styles/pages-controls.css'

type MotionPreference = 'system' | 'reduced' | 'full'
type SettingsSection = 'privacy' | 'data' | 'connections' | 'appearance'

interface LocalAIDraft {
  readonly enabled: boolean
  readonly provider: LocalAIProvider
  readonly endpoint: string
  readonly selectedModel: string | null
  readonly revision: number
}

const initialLocalAI: LocalAIDraft = {
  enabled: false,
  provider: 'OLLAMA',
  endpoint: 'http://127.0.0.1:11434',
  selectedModel: null,
  revision: 1,
}

const sectionNav = [
  { id: 'privacy' as const, label: 'Privacy posture', icon: ShieldCheck },
  { id: 'data' as const, label: 'Data & retention', icon: Database },
  { id: 'connections' as const, label: 'Connectors & AI', icon: PlugZap },
  { id: 'appearance' as const, label: 'Appearance & motion', icon: Paintbrush },
]

const displayPresetLabels: Record<DisplayPreset, string> = {
  auto: 'Auto',
  laptop: 'Laptop',
  standard: 'Standard',
  ultrawide: 'Ultrawide',
}

const displayPresetDescriptions: Record<DisplayPreset, string> = {
  auto: 'Adapts content width and density to the current window.',
  laptop: 'Keeps the workspace focused and compact on smaller displays.',
  standard: 'Balances readable line lengths with two-column workspaces.',
  ultrawide: 'Uses additional horizontal room for evidence-rich layouts.',
}

export function SettingsPage() {
  const native = nativeRuntimeAvailable()
  const { reducedMotion, toggleReducedMotion } = usePrototypeStore()
  const fontScale = useDisplayPreferences((state) => state.fontScale)
  const displayPreset = useDisplayPreferences((state) => state.displayPreset)
  const setFontScale = useDisplayPreferences((state) => state.setFontScale)
  const setDisplayPreset = useDisplayPreferences(
    (state) => state.setDisplayPreset,
  )
  const [section, setSection] = useState<SettingsSection>('privacy')
  const [dirty, setDirty] = useState(false)
  const [saved, setSaved] = useState(false)
  const [autoLock, setAutoLock] = useState('15')
  const [retention, setRetention] = useState('90')
  const [motion, setMotion] = useState<MotionPreference>(reducedMotion ? 'reduced' : 'system')
  const [settings, setSettings] = useState({
    redactExports: true,
    redactScreenshots: true,
    clipboardClear: true,
    connectors: false,
    telemetry: false,
    compactDensity: false,
  })
  const [localAI, setLocalAI] = useState<LocalAIDraft>(initialLocalAI)
  const [localAIModels, setLocalAIModels] = useState<readonly string[]>([])
  const [localAIPending, setLocalAIPending] = useState(false)
  const [localAIError, setLocalAIError] = useState<string | null>(null)
  const [localAIStatus, setLocalAIStatus] =
    useState<LocalAIConnectionStatus | null>(null)
  const [localAISaved, setLocalAISaved] = useState(false)

  useEffect(() => {
    document.title = 'Privacy & Settings · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  useEffect(() => {
    if (!native) return
    let cancelled = false
    setLocalAIPending(true)
    void getLocalAISettings()
      .then((loaded) => {
        if (cancelled) return
        setLocalAI(loaded)
        setLocalAIModels(
          loaded.selectedModel === null ? [] : [loaded.selectedModel],
        )
        setLocalAIError(null)
      })
      .catch(() => {
        if (!cancelled) {
          setLocalAIError('Unlock the local vault to configure local AI.')
        }
      })
      .finally(() => {
        if (!cancelled) setLocalAIPending(false)
      })
    return () => {
      cancelled = true
    }
  }, [native])

  const updateSetting = (key: keyof typeof settings, value: boolean) => {
    setSettings((current) => ({ ...current, [key]: value }))
    setDirty(true)
    setSaved(false)
  }

  const updateMotion = (value: MotionPreference) => {
    setMotion(value)
    if ((value === 'reduced') !== reducedMotion) toggleReducedMotion()
    setDirty(true)
    setSaved(false)
  }

  const saveSettings = () => {
    setDirty(false)
    setSaved(true)
  }

  const setLocalAIProvider = (provider: LocalAIProvider) => {
    setLocalAI((current) => ({
      ...current,
      enabled: false,
      provider,
      endpoint:
        provider === 'OLLAMA'
          ? 'http://127.0.0.1:11434'
          : 'http://127.0.0.1:1234',
      selectedModel: null,
    }))
    setLocalAIModels([])
    setLocalAIStatus(null)
    setLocalAISaved(false)
    setLocalAIError(null)
  }

  const discoverModels = async () => {
    if (!native || !isLoopbackLocalAIEndpoint(localAI.endpoint)) {
      setLocalAIError('Enter an HTTP loopback endpoint on this Mac.')
      return
    }
    setLocalAIPending(true)
    setLocalAIError(null)
    setLocalAIStatus(null)
    try {
      const result = await discoverLocalAIModels({
        provider: localAI.provider,
        endpoint: localAI.endpoint,
        selectedModel: localAI.selectedModel,
      })
      const models = result.models.map((model) => model.modelId)
      setLocalAIModels(models)
      setLocalAI((current) => ({
        ...current,
        selectedModel:
          current.selectedModel !== null &&
          models.includes(current.selectedModel)
            ? current.selectedModel
            : null,
      }))
      setLocalAIError(
        models.length === 0
          ? 'The local server responded but reported no served models.'
          : null,
      )
    } catch {
      setLocalAIError('No compatible local model server responded at this endpoint.')
    } finally {
      setLocalAIPending(false)
    }
  }

  const testConnection = async () => {
    if (!native || !isLoopbackLocalAIEndpoint(localAI.endpoint)) {
      setLocalAIError('Enter an HTTP loopback endpoint on this Mac.')
      return
    }
    setLocalAIPending(true)
    setLocalAIError(null)
    try {
      const result = await testLocalAIConnection({
        provider: localAI.provider,
        endpoint: localAI.endpoint,
        selectedModel: localAI.selectedModel,
      })
      setLocalAIStatus(result.status)
      if (result.status !== 'AVAILABLE') {
        setLocalAIError(
          result.status === 'MODEL_UNAVAILABLE'
            ? 'The selected model is no longer served by this local runtime.'
            : 'The local runtime did not pass the bounded connection test.',
        )
      }
    } catch {
      setLocalAIStatus('UNAVAILABLE')
      setLocalAIError('The local runtime connection test could not complete.')
    } finally {
      setLocalAIPending(false)
    }
  }

  const saveLocalAI = async () => {
    if (
      !native ||
      !isLoopbackLocalAIEndpoint(localAI.endpoint) ||
      (localAI.enabled && localAI.selectedModel === null)
    ) {
      setLocalAIError(
        'Choose a discovered model before enabling local AI assistance.',
      )
      return
    }
    setLocalAIPending(true)
    setLocalAIError(null)
    setLocalAISaved(false)
    try {
      const savedSettings = await updateLocalAISettings({
        enabled: localAI.enabled,
        provider: localAI.provider,
        endpoint: localAI.endpoint,
        selectedModel: localAI.selectedModel,
        expectedRevision: localAI.revision,
      })
      setLocalAI(savedSettings)
      setLocalAISaved(true)
    } catch {
      setLocalAIError(
        'Local AI settings changed elsewhere or could not be saved. Reload and try again.',
      )
    } finally {
      setLocalAIPending(false)
    }
  }

  return (
    <div className="page controls-page settings-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Privacy & Settings · Local workspace"
        title="Private by default, explicit by design"
        description={native ? 'Control locking, retention, redaction, connectors, local AI, and motion. Local-AI choices are encrypted in the unlocked vault; unfinished prototype controls remain in memory.' : 'Control locking, retention, redaction, connectors, local AI, and motion. Browser prototype changes stay in memory and never create external traffic.'}
        meta={
          <>
            <Badge tone="green" dot>Vault encrypted</Badge>
            <Badge tone="cyan">Telemetry off</Badge>
            <Badge>On-device settings</Badge>
          </>
        }
        actions={
          <Button variant="primary" onClick={saveSettings} disabled={!dirty}>
            <Save size={15} aria-hidden="true" />
            {dirty ? 'Save changes' : saved ? 'Saved locally' : 'No changes'}
          </Button>
        }
      />

      {saved && (
        <div className="controls-inline-notice controls-inline-notice--success" role="status">
          <CheckCircle2 size={16} aria-hidden="true" />
          <span>Privacy settings saved to the synthetic local workspace.</span>
        </div>
      )}

      <div className="controls-settings-layout">
        <aside className="controls-settings-nav" aria-label="Settings sections">
          {sectionNav.map((item) => {
            const Icon = item.icon
            return (
              <button type="button" key={item.id} className={section === item.id ? 'is-active' : ''} onClick={() => setSection(item.id)} aria-current={section === item.id ? 'true' : undefined}>
                <Icon size={16} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            )
          })}
          <div className="controls-settings-nav__footer">
            <LockKeyhole size={15} aria-hidden="true" />
            <div><strong>Local vault</strong><small>AES-256 · simulated</small></div>
          </div>
        </aside>

        <div className="controls-settings-content">
          <Panel className={`controls-posture-panel panel--raised ${section === 'privacy' ? 'is-highlighted' : ''}`} eyebrow="Privacy posture" title="Protection is active" action={<Badge tone="green" dot>Strong</Badge>}>
            <div className="controls-posture-main">
              <div className="controls-posture-score" aria-label="Four of four baseline privacy controls active">
                <ShieldCheck size={26} aria-hidden="true" />
                <div><strong>4 / 4</strong><span>baseline controls</span></div>
              </div>
              <div className="controls-posture-progress">
                <div><span>Encryption, lock, telemetry, redaction</span><strong>100%</strong></div>
                <Progress value={100} tone="green" label="All four baseline privacy controls active" />
                <small>This posture describes configuration, not immunity from device or export compromise.</small>
              </div>
            </div>
            <div className="controls-posture-cards">
              <div><KeyRound size={14} /><span><strong>Key storage</strong><small>macOS Keychain boundary</small></span><Badge tone="green">Protected</Badge></div>
              <div><WifiOff size={14} /><span><strong>Telemetry</strong><small>No analytics or remote fonts</small></span><Badge tone="cyan">Off</Badge></div>
              <div><HardDrive size={14} /><span><strong>Database</strong><small>Local encrypted vault</small></span><Badge tone="green">Encrypted</Badge></div>
              <div className="controls-posture-motion">
                <Monitor size={14} />
                <span><strong>Motion</strong><small>System-aware preference</small></span>
                <button
                  type="button"
                  onClick={() => updateMotion(motion === 'reduced' ? 'system' : 'reduced')}
                  aria-label={`Motion preference: ${motion === 'system' ? 'Follow system' : motion === 'reduced' ? 'Reduced' : 'Full'}. Change motion preference`}
                >
                  {motion === 'system' ? 'Follow system' : motion === 'reduced' ? 'Reduced' : 'Full'}
                </button>
              </div>
            </div>
          </Panel>

          <div className="controls-settings-grid">
            <Panel className={`controls-settings-panel ${section === 'data' ? 'is-highlighted' : ''}`} eyebrow="Local data" title="Lock, retention & redaction">
              <div className="controls-settings-fields">
                <label className="field">
                  <span>Auto-lock after inactivity</span>
                  <select className="select" value={autoLock} onChange={(event) => { setAutoLock(event.target.value); setDirty(true); setSaved(false) }}>
                    <option value="5">5 minutes</option>
                    <option value="15">15 minutes</option>
                    <option value="30">30 minutes</option>
                    <option value="60">1 hour</option>
                  </select>
                  <small>Lock removes sensitive content from the rendered document.</small>
                </label>
                <label className="field">
                  <span>Default evidence retention</span>
                  <select className="select" value={retention} onChange={(event) => { setRetention(event.target.value); setDirty(true); setSaved(false) }}>
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                    <option value="365">1 year</option>
                    <option value="manual">Until manually reviewed</option>
                  </select>
                  <small>Deletion remains reviewable and follows secure-deletion guidance.</small>
                </label>
              </div>
              <div className="controls-toggle-list">
                <Toggle checked={settings.redactExports} onCheckedChange={(value) => updateSetting('redactExports', value)} label="Redacted exports by default" description="Full exports remain a separately warned action." />
                <Toggle checked={settings.redactScreenshots} onCheckedChange={(value) => updateSetting('redactScreenshots', value)} label="Mask sensitive screenshot fields" description="Identifiers and exact locations stay concealed." />
                <Toggle checked={settings.clipboardClear} onCheckedChange={(value) => updateSetting('clipboardClear', value)} label="Clear sensitive clipboard copies" description="Offer a 60-second local clipboard expiry." />
              </div>
              <div className="controls-settings-actions">
                <Button size="compact"><Download size={13} /> Backup encrypted vault</Button>
                <Button size="compact" variant="danger"><Trash2 size={13} /> Review deletion</Button>
              </div>
            </Panel>

            <Panel className={`controls-settings-panel ${section === 'connections' ? 'is-highlighted' : ''}`} eyebrow="Computation & access" title="Connectors and local AI">
              <div className="controls-toggle-list">
                <Toggle
                  checked={localAI.enabled}
                  onCheckedChange={(enabled) => {
                    setLocalAI((current) => ({ ...current, enabled }))
                    setLocalAISaved(false)
                  }}
                  disabled={!native || localAIPending}
                  label="Use local AI assistance"
                  description="Disabled by default. Deterministic extraction remains available and every local-model suggestion requires review."
                />
                <Toggle checked={settings.connectors} onCheckedChange={(value) => updateSetting('connectors', value)} label="Enable authorised connectors" description="No connector is configured in this synthetic workspace." />
                <Toggle checked={settings.telemetry} onCheckedChange={() => undefined} disabled label="Product telemetry" description="Unavailable by design; no analytics endpoint is included." />
              </div>
              <div className="controls-model-card">
                <span className="status-icon status-icon--violet"><Bot size={17} /></span>
                <div><strong>{localAI.selectedModel ?? 'No local model selected'}</strong><small>{native ? `${localAI.provider === 'OLLAMA' ? 'Ollama' : 'OpenAI-compatible'} · loopback only` : 'Native app required · deterministic rules active'}</small></div>
                <Badge tone={localAI.enabled ? 'violet' : 'cyan'}>{localAI.enabled ? 'Enabled' : 'Off'}</Badge>
              </div>
              <div className="controls-local-ai-fields">
                <label className="field">
                  <span>Local runtime</span>
                  <select
                    className="select"
                    value={localAI.provider}
                    disabled={!native || localAIPending}
                    onChange={(event) => setLocalAIProvider(event.target.value as LocalAIProvider)}
                  >
                    <option value="OLLAMA">Ollama</option>
                    <option value="OPENAI_COMPATIBLE">OpenAI-compatible · LM Studio</option>
                  </select>
                </label>
                <label className="field">
                  <span>Loopback endpoint</span>
                  <input
                    className="input mono"
                    value={localAI.endpoint}
                    disabled={!native || localAIPending}
                    onChange={(event) => {
                      setLocalAI((current) => ({ ...current, enabled: false, endpoint: event.target.value, selectedModel: null }))
                      setLocalAIModels([])
                      setLocalAIStatus(null)
                      setLocalAISaved(false)
                    }}
                  />
                  <small>HTTP localhost/127.0.0.0/8/::1 only. No API key or cloud fallback exists.</small>
                </label>
                <label className="field">
                  <span>Explicit model</span>
                  <select
                    className="select"
                    value={localAI.selectedModel ?? ''}
                    disabled={!native || localAIPending || localAIModels.length === 0}
                    onChange={(event) => {
                      setLocalAI((current) => ({ ...current, enabled: false, selectedModel: event.target.value || null }))
                      setLocalAIStatus(null)
                      setLocalAISaved(false)
                    }}
                  >
                    <option value="">Choose a served model</option>
                    {localAIModels.map((model) => <option key={model} value={model}>{model}</option>)}
                  </select>
                </label>
              </div>
              <div className="controls-settings-actions controls-local-ai-actions">
                <Button size="compact" onClick={() => void discoverModels()} disabled={!native || localAIPending}>
                  <RefreshCw size={13} /> Discover served models
                </Button>
                <Button size="compact" onClick={() => void testConnection()} disabled={!native || localAIPending}>
                  <PlugZap size={13} /> Test connection
                </Button>
                <Button size="compact" variant="primary" onClick={() => void saveLocalAI()} disabled={!native || localAIPending || (localAI.enabled && localAI.selectedModel === null)}>
                  <Save size={13} /> Save local AI
                </Button>
              </div>
              {(localAIError || localAISaved || localAIStatus === 'AVAILABLE') && (
                <div className={`controls-inline-notice ${localAIError ? '' : 'controls-inline-notice--success'}`} role="status">
                  {localAIError ? <WifiOff size={15} /> : <CheckCircle2 size={15} />}
                  <span>{localAIError ?? (localAISaved ? 'Local AI choice saved in the encrypted vault.' : localAI.selectedModel === null ? 'The local runtime is available. Discover and choose a served model before enabling assistance.' : 'The selected local runtime and model are available.')}</span>
                </div>
              )}
              <div className="controls-connector-card">
                <span className="status-icon"><PlugZap size={17} /></span>
                <div><strong>No accounts connected</strong><small>Read-only scope and explicit import are required.</small></div>
                <Button size="compact" disabled>Configure</Button>
              </div>
            </Panel>

            <Panel className={`controls-settings-panel controls-appearance-panel ${section === 'appearance' ? 'is-highlighted' : ''}`} eyebrow="Interface" title="Display, type & motion">
              <div className="controls-display-preferences">
                <fieldset className="controls-display-picker">
                  <legend>Interface size</legend>
                  <p id="font-scale-help">Scales text throughout Ariadne while responsive layouts make room for the larger type.</p>
                  <div className="segmented-control controls-font-scale" aria-describedby="font-scale-help">
                    {FONT_SCALE_OPTIONS.map((value) => (
                      <button
                        type="button"
                        key={value}
                        className={fontScale === value ? 'is-active' : ''}
                        onClick={() => setFontScale(value)}
                        aria-pressed={fontScale === value}
                        aria-label={`${value}% interface size`}
                      >
                        {value}%
                      </button>
                    ))}
                  </div>
                </fieldset>
                <fieldset className="controls-display-picker">
                  <legend>Display preset</legend>
                  <p id="display-preset-help">{displayPresetDescriptions[displayPreset]}</p>
                  <div className="segmented-control controls-display-presets" aria-describedby="display-preset-help">
                    {DISPLAY_PRESET_OPTIONS.map((value) => (
                      <button
                        type="button"
                        key={value}
                        className={displayPreset === value ? 'is-active' : ''}
                        onClick={() => setDisplayPreset(value)}
                        aria-pressed={displayPreset === value}
                      >
                        {displayPresetLabels[value]}
                      </button>
                    ))}
                  </div>
                </fieldset>
              </div>
              <div className="controls-display-status" role="status" aria-live="polite">
                <Monitor size={16} aria-hidden="true" />
                <div>
                  <strong>{fontScale}% · {displayPresetLabels[displayPreset]}</strong>
                  <small>Saved locally on this Mac. No workspace or personal data is stored with this preference.</small>
                </div>
              </div>
              <fieldset className="controls-motion-picker">
                <legend>Motion preference</legend>
                <p>Reduced motion stops ambient pulses, scanlines, and graph flow while preserving status and progress.</p>
                <div className="segmented-control">
                  {(['system', 'reduced', 'full'] as MotionPreference[]).map((value) => (
                    <button type="button" key={value} className={motion === value ? 'is-active' : ''} onClick={() => updateMotion(value)} aria-pressed={motion === value}>
                      {value === 'system' ? 'Follow system' : value === 'reduced' ? 'Reduced' : 'Full'}
                    </button>
                  ))}
                </div>
              </fieldset>
              <Toggle checked={settings.compactDensity} onCheckedChange={(value) => updateSetting('compactDensity', value)} label="Compact data density" description="Tighten tables without reducing the type floor." />
              <div className="controls-motion-preview" data-motion-preview={motion}>
                <Monitor size={16} aria-hidden="true" />
                <div><strong>{motion === 'reduced' ? 'Static status preview' : 'Interface motion preview'}</strong><small>{motion === 'system' ? 'Follows macOS preference' : motion === 'reduced' ? 'No nonessential movement' : 'Purposeful transitions enabled'}</small></div>
                <span aria-hidden="true" />
              </div>
              <div className="controls-relock-note"><TimerReset size={14} /><span>Auto-lock changes apply immediately; encryption changes would require relocking.</span></div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
