/** Geographic evidence projection; map points retain their temporal/source context. */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  CircleHelp,
  Globe2,
  Layers3,
  LocateFixed,
  LockKeyhole,
  MapPin,
  RadioTower,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { mapPoints } from '@ariadne/synthetic-data'
import {
  Badge,
  Button,
  DefinitionList,
  Metric,
  PageHeader,
  Panel,
  type Tone,
} from '../components/Primitives'
import type { AuditDetail } from '../../../../packages/contracts/src/generated/api'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  getIdentityAudit,
  getIdentityWorkspace,
} from '../app/identityDiscoveryBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Toggle } from '../components/Toggle'
import '../styles/pages-results.css'

type MapPoint = (typeof mapPoints)[number]
type MapStyle = 'identity' | 'jurisdiction'

const pointTone: Record<MapPoint['kind'], Tone> = {
  historic: 'amber',
  public: 'green',
  provider: 'cyan',
}

const pointContext: Record<MapPoint['id'], { state: string; source: string; observed: string; privacy: string }> = {
  greyhaven: {
    state: 'Historical identity region',
    source: 'Fictional profile note',
    observed: 'Date-bounded · synthetic history',
    privacy: 'Sensitive · rendered coarsely',
  },
  northbridge: {
    state: 'Public organisation locality',
    source: 'Fictional organisation record',
    observed: 'Current public context',
    privacy: 'Public · city-level only',
  },
  'provider-eu': {
    state: 'Provider hosting region',
    source: 'Synthetic provider registry',
    observed: 'Run configuration · 11 Jul 2026',
    privacy: 'Infrastructure jurisdiction',
  },
  'provider-us': {
    state: 'Provider hosting region',
    source: 'Synthetic provider registry',
    observed: 'Blocked before transmission',
    privacy: 'Infrastructure jurisdiction',
  },
}

const COUNTRY_TLDS: Readonly<Record<string, string>> = {
  au: 'Australia',
  br: 'Brazil',
  ca: 'Canada',
  ch: 'Switzerland',
  cn: 'China',
  de: 'Germany',
  es: 'Spain',
  fr: 'France',
  ie: 'Ireland',
  in: 'India',
  it: 'Italy',
  jp: 'Japan',
  mx: 'Mexico',
  nl: 'Netherlands',
  nz: 'New Zealand',
  pl: 'Poland',
  pt: 'Portugal',
  ru: 'Russia',
  se: 'Sweden',
  uk: 'United Kingdom',
  us: 'United States',
  za: 'South Africa',
}

function sourceCountry(url: string): string {
  try {
    const hostname = new URL(url).hostname.toLocaleLowerCase()
    const suffix = hostname.split('.').at(-1) ?? ''
    return COUNTRY_TLDS[suffix] ?? 'Global or unspecified'
  } catch {
    return 'Unresolved'
  }
}

function NativeMapPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [state, setState] = useState<'LOADING' | 'READY' | 'EMPTY' | 'ERROR'>(
    profileId === null ? 'EMPTY' : 'LOADING',
  )

  useEffect(() => {
    if (profileId === null) {
      setAudit(null)
      setState('EMPTY')
      return
    }
    let cancelled = false
    setState('LOADING')
    void getIdentityWorkspace({ profileId })
      .then(async (workspace) => {
        const latest = workspace.audits[0]
        if (!latest) return null
        return getIdentityAudit({
          profileId,
          auditId: latest.auditId,
          maximumTasks: 1,
        })
      })
      .then((detail) => {
        if (cancelled) return
        setAudit(detail)
        setState(detail === null ? 'EMPTY' : 'READY')
      })
      .catch(() => {
        if (!cancelled) setState('ERROR')
      })
    return () => { cancelled = true }
  }, [profileId])

  const countries = useMemo(() => {
    const grouped = new Map<string, AuditDetail['results']>()
    for (const result of audit?.results ?? []) {
      const country = sourceCountry(result.url)
      grouped.set(country, [...(grouped.get(country) ?? []), result])
    }
    return [...grouped.entries()].sort(
      (left, right) => right[1].length - left[1].length,
    )
  }, [audit])

  if (state !== 'READY' || audit === null) {
    return (
      <div className="page map-page" data-testid="route-ready">
        <PageHeader
          eyebrow="Exact-source geography"
          title="Geographic Map"
          description="Country labels are derived only from exact source domains. Ariadne does not invent a location for generic domains."
          meta={<Badge tone={state === 'ERROR' ? 'rose' : 'cyan'}>{state.toLocaleLowerCase()}</Badge>}
        />
        <Panel className="empty-state panel--raised">
          <Globe2 size={28} />
          <h2>{state === 'LOADING' ? 'Projecting source countries…' : state === 'ERROR' ? 'Source geography could not be loaded' : 'No retained audit sources yet'}</h2>
          <p>{state === 'EMPTY' ? 'Complete or reopen an identity audit to populate this view.' : 'The active profile and its latest retained audit remain unchanged.'}</p>
          <Link className="button button--primary" to="/people">Open People</Link>
        </Panel>
      </div>
    )
  }

  return (
    <div className="page map-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Exact-source geography · latest durable audit"
        title="Geographic Map"
        description="Every country bucket below resolves to retained source URLs. Generic domains stay global or unspecified instead of receiving a guessed country."
        meta={<><Badge tone="green">{audit.results.length} exact sources</Badge><Badge tone="cyan">{countries.length} country or scope buckets</Badge>{audit.aiAnalysis?.status === 'SUCCEEDED' ? <Badge tone="violet">AI connections available</Badge> : null}</>}
        actions={<><Link className="button button--secondary" to="/graph">Open Link Map</Link><Link className="button button--secondary" to={`/identity/audits/${audit.audit.auditId}`}>Open audit</Link></>}
      />
      <div className="grid-4 identity-metrics">
        {countries.slice(0, 4).map(([country, results]) => (
          <Metric
            key={country}
            label={country}
            value={String(results.length)}
            detail={`retained source${results.length === 1 ? '' : 's'}`}
            tone={country === 'Global or unspecified' ? 'neutral' : 'cyan'}
          />
        ))}
      </div>
      <Panel
        className="panel--signal"
        eyebrow="Cited country inventory"
        title={`${audit.results.length} source URLs across ${countries.length} buckets`}
      >
        <div className="identity-result-list">
          {countries.flatMap(([country, results]) =>
            results.map((result) => (
              <article className="identity-result-row" key={result.resultId}>
                <MapPin size={15} />
                <div>
                  <div className="inline">
                    <strong>{result.title || result.url}</strong>
                    <Badge tone={country === 'Global or unspecified' ? 'neutral' : 'cyan'}>{country}</Badge>
                  </div>
                  <code>{result.url}</code>
                  <small>{result.providerId.replaceAll('_', ' ').toLocaleLowerCase()} · domain-derived country scope</small>
                </div>
              </article>
            )),
          )}
        </div>
      </Panel>
      {audit.aiAnalysis?.status === 'SUCCEEDED' ? (
        <Panel eyebrow="AI-assisted connections" title="Cited relationships from this audit">
          <div className="identity-card-grid">
            {audit.aiAnalysis.insights.filter((insight) => insight.kind === 'CONNECTION').map((insight, index) => (
              <article className="identity-knowledge-card" key={`${insight.statement}-${index}`}>
                <Badge tone="violet">Connection</Badge>
                <strong>{insight.statement}</strong>
                <p>{insight.rationale}</p>
                <small>{insight.evidenceRefs.join(' · ')}</small>
              </article>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

export function MapPage() {
  return nativeRuntimeAvailable() ? <NativeMapPage /> : <SimulatedMapPage />
}

function SimulatedMapPage() {
  const [style, setStyle] = useState<MapStyle>('identity')
  const [providerOverlay, setProviderOverlay] = useState(true)
  const [selectedId, setSelectedId] = useState<MapPoint['id']>('greyhaven')
  const [year, setYear] = useState(2026)
  const [query, setQuery] = useState('')

  const visiblePoints = useMemo(
    () => mapPoints.filter((point) => providerOverlay || point.kind !== 'provider'),
    [providerOverlay],
  )
  const selected = mapPoints.find((point) => point.id === selectedId) ?? mapPoints[0]

  const focusSearch = () => {
    const normalized = query.trim().toLocaleLowerCase()
    const match = visiblePoints.find((point) =>
      point.label.toLocaleLowerCase().includes(normalized),
    )
    if (match) setSelectedId(match.id)
  }

  return (
    <div
      className="page map-page"
      data-testid="route-ready"
      data-layout-ready="true"
    >
      <PageHeader
        eyebrow="Coarse location and jurisdiction context"
        title="Geographic Map"
        description="Review historical identity regions separately from provider infrastructure. Sensitive locations remain coarse in the canvas, labels, and accessible list."
        meta={
          <>
            <Badge tone="green"><ShieldCheck size={11} /> Coarse privacy mode</Badge>
            <Badge tone="cyan">4 regions · synthetic</Badge>
            <Badge>Local vector map · no tile requests</Badge>
          </>
        }
        actions={
          <>
            <Link className="button button--secondary" to="/graph">Open Link Map</Link>
            <Button variant="secondary"><Layers3 size={14} /> Saved views</Button>
          </>
        }
      />

      <Panel className="map-workspace panel--raised">
        <div className="map-toolbar">
          <div className="segmented-control map-style-control" aria-label="Map style">
            <button
              type="button"
              className={style === 'identity' ? 'is-active' : undefined}
              onClick={() => setStyle('identity')}
            >
              <MapPin size={12} /> Identity context
            </button>
            <button
              type="button"
              className={style === 'jurisdiction' ? 'is-active' : undefined}
              onClick={() => setStyle('jurisdiction')}
            >
              <Globe2 size={12} /> Jurisdiction field
            </button>
          </div>
          <form
            className="map-search"
            onSubmit={(event) => { event.preventDefault(); focusSearch() }}
          >
            <Search size={14} />
            <label className="sr-only" htmlFor="map-search">Search regions</label>
            <input
              id="map-search"
              type="search"
              placeholder="Find a coarse region"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button type="submit" variant="ghost" size="compact"><LocateFixed size={12} /> Focus</Button>
          </form>
          <label className="map-time-control">
            <span><CalendarClock size={12} /> Time window</span>
            <input
              type="range"
              min="2022"
              max="2026"
              value={year}
              onChange={(event) => setYear(Number(event.target.value))}
            />
            <strong className="mono">≤ {year}</strong>
          </label>
          <Toggle
            className="map-provider-toggle"
            checked={providerOverlay}
            onCheckedChange={setProviderOverlay}
            label="Provider overlay"
          />
        </div>

        <div className="map-layout">
          <section className={`map-canvas map-canvas--${style}`} aria-label="Coarse synthetic location map">
            <svg className="map-canvas__land" viewBox="0 0 1000 560" aria-hidden="true" preserveAspectRatio="none">
              <defs>
                <linearGradient id="map-land" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="var(--graphite-750)" stopOpacity=".85" />
                  <stop offset="1" stopColor="var(--graphite-800)" stopOpacity=".42" />
                </linearGradient>
                <pattern id="map-dots" width="15" height="15" patternUnits="userSpaceOnUse">
                  <circle cx="1" cy="1" r=".75" fill="var(--mist-400)" opacity=".13" />
                </pattern>
              </defs>
              <path d="M80 130 L160 72 258 84 322 135 294 194 236 215 212 296 153 328 117 258 57 223Z" />
              <path d="M295 338 L346 322 382 366 370 456 326 518 285 430Z" />
              <path d="M440 112 L498 78 556 94 576 132 544 164 566 204 530 244 482 218 452 170Z" />
              <path d="M505 246 L580 220 643 260 658 344 618 458 552 492 520 388 466 314Z" />
              <path d="M575 118 L694 73 822 110 922 176 900 236 808 254 744 224 686 275 620 230 612 168Z" />
              <path d="M807 370 L866 348 929 389 910 452 842 465 792 422Z" />
              <rect x="0" y="0" width="1000" height="560" fill="url(#map-dots)" />
              <g className="map-canvas__routes">
                <path d="M230 204 Q430 70 510 168 T760 188" />
                <path d="M506 170 Q420 250 470 298 T545 355" />
              </g>
            </svg>

            {providerOverlay ? (
              <div className="map-jurisdiction-zones" aria-hidden="true">
                <span className="map-zone map-zone--eu" />
                <span className="map-zone map-zone--us" />
              </div>
            ) : null}

            {visiblePoints.map((point) => (
              <button
                type="button"
                key={point.id}
                className={`map-point map-point--${point.kind}${selected.id === point.id ? ' is-selected' : ''}`}
                style={{ insetInlineStart: `${point.x}%`, insetBlockStart: `${point.y}%` }}
                onClick={() => setSelectedId(point.id)}
                aria-pressed={selected.id === point.id}
                aria-label={`${point.label}; ${point.kind === 'provider' ? 'provider hosting region' : point.precision}; ${point.confidence} percent confidence`}
              >
                <span className="map-point__pulse" aria-hidden="true" />
                <span className="map-point__icon">
                  {point.kind === 'provider' ? <RadioTower size={13} /> : point.kind === 'historic' ? <LockKeyhole size={13} /> : <MapPin size={13} />}
                </span>
                <span className="map-point__label"><strong>{point.label}</strong><small>{point.precision}</small></span>
              </button>
            ))}

            <div className="map-canvas__privacy">
              <LockKeyhole size={12} /> Exact private coordinates suppressed
            </div>
            <div className="map-canvas__style">
              <span>{style === 'identity' ? 'IDENTITY CONTEXT' : 'JURISDICTION FIELD'}</span>
              <small className="mono">local-vector:v1 · {year}</small>
            </div>
            <div className="map-legend" aria-label="Map legend">
              <span><i className="is-historic" /> Historical private region</span>
              <span><i className="is-public" /> Public locality</span>
              {providerOverlay ? <span><i className="is-provider" /> Provider jurisdiction</span> : null}
            </div>
          </section>

          <aside className="map-inspector" aria-label="Selected region details">
            <div className="map-inspector__header">
              <span className="eyebrow">Selected coarse region</span>
              <Badge tone={pointTone[selected.kind]}>{selected.kind}</Badge>
              <h2>{selected.label}</h2>
              <p>{pointContext[selected.id].state}</p>
            </div>

            <div className="map-inspector__confidence">
              <span className={`status-icon status-icon--${selected.kind === 'historic' ? 'amber' : selected.kind === 'public' ? 'green' : 'cyan'}`}>
                {selected.kind === 'provider' ? <RadioTower size={15} /> : <MapPin size={15} />}
              </span>
              <div><span>Context confidence</span><strong>{selected.confidence}%</strong></div>
              <Badge>{selected.precision}</Badge>
            </div>

            <DefinitionList
              items={[
                ['Source', pointContext[selected.id].source],
                ['Temporal state', pointContext[selected.id].observed],
                ['Privacy class', pointContext[selected.id].privacy],
                ['Map treatment', selected.kind === 'provider' ? 'Jurisdiction overlay' : 'Coarse region only'],
              ]}
            />

            {selected.id === 'provider-us' ? (
              <div className="map-inspector__notice callout callout--warning">
                <CircleHelp size={14} />
                <span><strong>Transmission blocked.</strong> The illustrative US provider region is shown as infrastructure context only; no image fingerprint left the device.</span>
              </div>
            ) : (
              <div className="map-inspector__notice callout">
                <CheckCircle2 size={14} />
                <span><strong>Privacy boundary active.</strong> The map does not store or display an exact private coordinate.</span>
              </div>
            )}

            <div className="map-inspector__actions">
              <Button variant="secondary" size="compact">Focus connected findings</Button>
              <Link to="/privacy/transmission">Review jurisdiction <ArrowUpRight size={12} /></Link>
            </div>

            <details className="map-region-list">
              <summary>Accessible region list <span className="mono">{visiblePoints.length}</span></summary>
              <div>
                {visiblePoints.map((point) => (
                  <button
                    type="button"
                    key={point.id}
                    onClick={() => setSelectedId(point.id)}
                    aria-pressed={selected.id === point.id}
                  >
                    <span>{point.label}</span>
                    <small>{point.precision} · {pointContext[point.id].state}</small>
                  </button>
                ))}
              </div>
            </details>
          </aside>
        </div>
      </Panel>
    </div>
  )
}
