import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleHelp,
  Clock3,
  ExternalLink,
  Filter,
  Globe2,
  KeyRound,
  Radar,
  Search,
  Server,
  ShieldAlert,
} from 'lucide-react'
import { providers, type Health } from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel, Progress } from '../components/Primitives'
import { Toggle } from '../components/Toggle'
import '../styles/pages-controls.css'

type ProviderRecord = {
  id: string
  name: string
  country: string
  regions: readonly string[]
  type: string
  health: Health
  risk: string
  retention: string
  enabled: boolean
  sendsIdentifiers: boolean
  coverage: number
  accessBasis: string
  auth: string
  operator: string
  hosting: string
  terms: string
  removalRoute: string
  healthTime: string
  broker: boolean
}

const registryMetadata: Record<string, Omit<ProviderRecord, 'id' | 'name' | 'country' | 'regions' | 'type' | 'health' | 'risk' | 'retention' | 'enabled' | 'sendsIdentifiers' | 'coverage'>> = {
  'local-corpus': { accessBasis: 'User-imported local data', auth: 'None', operator: 'On device', hosting: 'On device', terms: 'Local processing policy', removalRoute: 'Delete local corpus', healthTime: '14:40 UTC', broker: false },
  'boreal-search': { accessBasis: 'Official public API', auth: 'API key required', operator: 'FI', hosting: 'EU', terms: 'terms.example.invalid/boreal', removalRoute: 'removal.example.invalid/boreal', healthTime: '14:39 UTC', broker: false },
  'meridian-archive': { accessBasis: 'Ordinary public access', auth: 'None', operator: 'NL', hosting: 'EU', terms: 'terms.example.invalid/meridian', removalRoute: 'Manual archive request', healthTime: '14:37 UTC', broker: false },
  'code-atlas': { accessBasis: 'Official public API', auth: 'Optional token', operator: 'DE', hosting: 'EU', terms: 'terms.example.invalid/code-atlas', removalRoute: 'Source repository correction', healthTime: '14:39 UTC', broker: false },
  'image-observatory': { accessBasis: 'Approved image search', auth: 'Explicit approval', operator: 'US', hosting: 'US', terms: 'terms.example.invalid/images', removalRoute: 'Provider support route', healthTime: '14:34 UTC', broker: false },
  'civic-ledger': { accessBasis: 'Official public register', auth: 'Session required', operator: 'GB', hosting: 'GB', terms: 'terms.example.invalid/civic', removalRoute: 'Register correction route', healthTime: '14:31 UTC', broker: false },
}

const brokerProvider: ProviderRecord = {
  id: 'atlas-people-index',
  name: 'Atlas People Index',
  country: 'US',
  regions: ['US'],
  type: 'people_search_broker',
  health: 'operational',
  risk: 'High',
  retention: 'Unknown',
  enabled: false,
  sendsIdentifiers: true,
  coverage: 64,
  accessBasis: 'Public broker search',
  auth: 'None declared',
  operator: 'US',
  hosting: 'US',
  terms: 'terms.example.invalid/atlas-index',
  removalRoute: 'removal.example.invalid/atlas-index',
  healthTime: '14:35 UTC',
  broker: true,
}

const providerRecords: ProviderRecord[] = [
  ...providers.map((provider) => ({ ...provider, ...registryMetadata[provider.id] })),
  brokerProvider,
]

const healthTone = (health: Health) => {
  if (health === 'operational') return 'green' as const
  if (health === 'degraded') return 'amber' as const
  return 'rose' as const
}

const riskTone = (risk: string) => {
  if (risk === 'Low') return 'green' as const
  if (risk === 'Medium') return 'amber' as const
  return 'rose' as const
}

export function ProvidersPage() {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | Health | 'disabled'>('all')
  const [selectedId, setSelectedId] = useState('meridian-archive')
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(providerRecords.map((provider) => [provider.id, provider.enabled])),
  )

  const visibleProviders = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return providerRecords.filter((provider) => {
      const matchesSearch = !normalized || [
        provider.name,
        provider.type,
        provider.country,
        provider.accessBasis,
      ].some((value) => value.toLowerCase().includes(normalized))
      const matchesFilter = filter === 'all'
        || (filter === 'disabled' ? !enabled[provider.id] : provider.health === filter)
      return matchesSearch && matchesFilter
    })
  }, [enabled, filter, query])

  const selected = providerRecords.find((provider) => provider.id === selectedId) ?? providerRecords[0]

  useEffect(() => {
    document.title = 'Source Radar · Codename Ariadne'
    document.documentElement.dataset.captureReady = 'true'
    return () => {
      delete document.documentElement.dataset.captureReady
    }
  }, [])

  return (
    <div className="page controls-page providers-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Source Radar · Global registry"
        title="Provider coverage has boundaries"
        description="Review health, access basis, operator and hosting jurisdiction, retention, authentication, and transmission risk before a source enters a plan."
        meta={
          <>
            <Badge tone="amber" dot>1 degraded</Badge>
            <Badge tone="rose">2 unavailable or blocked</Badge>
            <Badge tone="cyan">Checked 14:40 UTC · simulated</Badge>
          </>
        }
        actions={<Button><Radar size={15} aria-hidden="true" /> Run local health check</Button>}
      />

      <div className="controls-provider-summary" aria-label="Provider registry summary">
        <article className="controls-provider-coverage">
          <div className="controls-summary-label"><Globe2 size={15} /><span>Enabled coverage</span><strong>4 / 7</strong></div>
          <Progress value={72} tone="cyan" label="72 percent of synthetic source categories covered" />
          <small>Coverage is by registered source category, not proof of complete exposure discovery.</small>
        </article>
        <article>
          <span className="status-icon status-icon--amber"><AlertTriangle size={16} /></span>
          <div><strong>Meridian Archive degraded</strong><small>Higher latency · partial archive years</small></div>
          <Badge tone="amber">14:37 UTC</Badge>
        </article>
        <article>
          <span className="status-icon status-icon--rose"><Ban size={16} /></span>
          <div><strong>Image search blocked</strong><small>Explicit approval is still required</small></div>
          <Badge tone="rose">NOT_CHECKED</Badge>
        </article>
      </div>

      <div className="controls-filterbar">
        <label className="controls-search-field">
          <Search size={15} aria-hidden="true" />
          <span className="sr-only">Search providers</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search provider, type, country, or access basis" />
          <kbd>/</kbd>
        </label>
        <label className="controls-compact-select">
          <Filter size={14} aria-hidden="true" />
          <span className="sr-only">Filter provider health</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
            <option value="all">All providers</option>
            <option value="operational">Operational</option>
            <option value="degraded">Degraded</option>
            <option value="blocked">Blocked</option>
            <option value="offline">Offline</option>
            <option value="disabled">Disabled by policy</option>
          </select>
        </label>
        <span className="controls-filter-count">{visibleProviders.length} of {providerRecords.length}</span>
      </div>

      <div className="controls-provider-layout">
        <Panel className="controls-provider-table-panel panel--raised" eyebrow="Registry" title="Providers and policy state">
          {visibleProviders.length ? (
            <div className="controls-table-scroll" role="region" aria-label="Provider registry table" tabIndex={0}>
              <table className="data-table controls-provider-table">
                <caption className="sr-only">Synthetic source providers, health, jurisdiction, retention, risk, and enable state</caption>
                <thead>
                  <tr>
                    <th scope="col">Provider</th>
                    <th scope="col">Health</th>
                    <th scope="col">Operator / host</th>
                    <th scope="col">Access basis</th>
                    <th scope="col">Retention</th>
                    <th scope="col">Risk</th>
                    <th scope="col">Enabled</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleProviders.map((provider) => (
                    <tr key={provider.id} className={selected.id === provider.id ? 'is-selected' : ''}>
                      <th scope="row">
                        <button type="button" onClick={() => setSelectedId(provider.id)}>
                          <span>{provider.name}</span>
                          <small>{provider.type.replaceAll('_', ' ')}</small>
                        </button>
                        {provider.broker && <Badge tone="rose">Broker · off by default</Badge>}
                      </th>
                      <td>
                        <Badge tone={healthTone(provider.health)} dot>{provider.health}</Badge>
                        <small>{provider.healthTime}</small>
                      </td>
                      <td><strong>{provider.operator}</strong><small>{provider.hosting}</small></td>
                      <td>{provider.accessBasis}<small>{provider.auth}</small></td>
                      <td className={provider.retention === 'Unknown' ? 'is-warning' : ''}>{provider.retention}</td>
                      <td><Badge tone={riskTone(provider.risk)}>{provider.risk}</Badge></td>
                      <td>
                        <Toggle
                          className="controls-table-toggle"
                          checked={Boolean(enabled[provider.id])}
                          onCheckedChange={(checked) => setEnabled((current) => ({ ...current, [provider.id]: checked }))}
                          label={`${enabled[provider.id] ? 'Disable' : 'Enable'} ${provider.name}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state controls-provider-empty">
              <span className="empty-state__icon"><Search size={22} /></span>
              <h2>No providers match this local filter</h2>
              <p>The registry is unchanged. Clear search and health filters to restore the full synthetic catalog.</p>
              <Button onClick={() => { setQuery(''); setFilter('all') }}>Clear filters</Button>
            </div>
          )}
        </Panel>

        <Panel
          className="controls-provider-inspector panel--raised"
          eyebrow="Provider detail"
          title={selected.name}
          action={<Badge tone={healthTone(selected.health)} dot>{selected.health}</Badge>}
        >
          <div className="controls-provider-hero">
            <span className="status-icon status-icon--cyan"><Server size={18} /></span>
            <div>
              <strong>{selected.type.replaceAll('_', ' ')}</strong>
              <small className="mono">provider:{selected.id}</small>
            </div>
            <Badge tone={riskTone(selected.risk)}>{selected.risk} risk</Badge>
          </div>

          {selected.retention === 'Unknown' && (
            <div className="controls-callout controls-callout--amber">
              <CircleHelp size={16} aria-hidden="true" />
              <span>Retention is unknown. Transmission requires an explicit per-run decision.</span>
            </div>
          )}

          {selected.broker && (
            <div className="controls-callout controls-callout--danger">
              <ShieldAlert size={16} aria-hidden="true" />
              <span>People-search claims remain lower confidence until corroborated and this provider stays disabled by default.</span>
            </div>
          )}

          <dl className="controls-compact-dl">
            <div><dt>Operator country</dt><dd>{selected.operator}</dd></div>
            <div><dt>Hosting regions</dt><dd>{selected.hosting}</dd></div>
            <div><dt>Access basis</dt><dd>{selected.accessBasis}</dd></div>
            <div><dt>Authentication</dt><dd><KeyRound size={12} /> {selected.auth}</dd></div>
            <div><dt>Identifiers leave device</dt><dd>{selected.sendsIdentifiers ? 'Yes · approval required' : 'No'}</dd></div>
            <div><dt>Retention</dt><dd>{selected.retention}</dd></div>
            <div><dt>Coverage sample</dt><dd>{selected.coverage}% simulated</dd></div>
          </dl>

          <div className="controls-registry-links">
            <button type="button"><ExternalLink size={13} /> Terms <span>{selected.terms}</span></button>
            <button type="button"><ExternalLink size={13} /> Removal route <span>{selected.removalRoute}</span></button>
          </div>

          <div className="controls-inspector-actions controls-inspector-actions--stack">
            <Button variant="primary" onClick={() => setEnabled((current) => ({ ...current, [selected.id]: !current[selected.id] }))}>
              {enabled[selected.id] ? 'Disable for new plans' : 'Review and enable'}
            </Button>
            <Button><Clock3 size={13} aria-hidden="true" /> View health history</Button>
          </div>
          <div className="controls-registry-verified">
            <CheckCircle2 size={14} aria-hidden="true" />
            <span>Registry metadata reviewed locally · 11 Jul 2026</span>
          </div>
        </Panel>
      </div>
    </div>
  )
}

export default ProvidersPage
