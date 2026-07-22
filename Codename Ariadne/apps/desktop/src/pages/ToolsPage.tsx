/** Optional authorised research tools kept outside the primary audit workflow. */
import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  ArrowRight,
  AtSign,
  BadgeInfo,
  BriefcaseBusiness,
  Building2,
  Camera,
  CheckCircle2,
  Clock3,
  Copy,
  Database,
  ExternalLink,
  FileSearch,
  Filter,
  Fingerprint,
  FolderSearch,
  GitBranch,
  Globe2,
  Image,
  KeyRound,
  Landmark,
  Link2,
  LoaderCircle,
  MailSearch,
  MapPin,
  Network,
  Phone,
  Plus,
  Radar,
  Route,
  Search,
  Save,
  ShieldCheck,
  Trash2,
  UserSearch,
  WalletCards,
  Wifi,
  Wrench,
} from 'lucide-react'
import { providers, syntheticProfile, toolCatalog } from '@ariadne/synthetic-data'
import { Badge, Button, PageHeader, Panel, Progress } from '../components/Primitives'
import { AdvancedSearchComposer } from '../components/AdvancedSearchComposer'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  capturePublicDiscovery,
  searchPublicDiscovery,
  type PublicDiscoveryCaptureResult,
  type PublicDiscoveryProvider,
  type PublicDiscoveryResultItem,
  type PublicDiscoverySearchResult,
} from '../app/publicDiscoveryBoundary'
import {
  searchHibpAccount,
  searchHibpDomain,
  type HibpAccountMode,
  type HibpAccountSearchResult,
  type HibpDomainSearchResult,
} from '../app/hibpBoundary'
import {
  compileInvestigationPlan,
  type InvestigationIdentifier,
  type InvestigationIdentifierKind,
  type InvestigationPlan,
  type InvestigationPlanStep,
  type InvestigationProvider,
} from '../app/investigationPlanBoundary'
import { manualResearchPortals } from '../app/manualResearchPortals'
import { openApprovedExternalUrl } from '../app/externalUrlBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { usePrototypeStore } from '../app/prototypeStore'
import '../styles/pages-public-discovery.css'

const toolIcons = {
  email: MailSearch,
  'at-sign': AtSign,
  'user-search': UserSearch,
  phone: Phone,
  'map-pin': MapPin,
  globe: Globe2,
  link: Link2,
  'building-2': Building2,
  'scan-face': Image,
  'git-branch': GitBranch,
  archive: Archive,
  landmark: Landmark,
  'mail-search': MailSearch,
  github: GitBranch,
  'folder-search': FolderSearch,
  camera: Camera,
  'git-compare': GitBranch,
  'list-checks': WalletCards,
  radar: Radar,
  'share-2': Network,
  'briefcase-business': BriefcaseBusiness,
} as const

const riskTone = (risk: string) => {
  if (risk.includes('High') || risk === 'Private') return 'amber'
  if (risk === 'Sensitive' || risk === 'Authorised') return 'violet'
  if (risk.includes('Local')) return 'green'
  return 'cyan'
}

const providerDetails: Record<
  PublicDiscoveryProvider,
  {
    readonly label: string
    readonly operator: string
    readonly description: string
  }
> = {
  DUCKDUCKGO_HTML: {
    label: 'Public web search',
    operator: 'DuckDuckGo HTML',
    description: 'Search public web pages using the exact query you approve.',
  },
  GITHUB_USERS: {
    label: 'GitHub users',
    operator: 'GitHub public API',
    description: 'Search public GitHub user and organisation accounts.',
  },
}

const reasonLabels: Record<string, string> = {
  COMPLETE: 'Search completed.',
  NO_RESULTS: 'No public results matched this query.',
  PARTIAL_RESULTS: 'Partial results returned; review coverage before drawing conclusions.',
  SELF_AUDIT_AUTHORIZATION_REQUIRED: 'Confirm that this is your authorised self-audit.',
  RESTRICTED_VALUE: 'This value cannot be sent to a public provider.',
  UPSTREAM_RATE_LIMITED: 'The provider rate-limited this request. Try again later.',
  CAPTCHA_OR_CHALLENGE: 'The provider presented a challenge; Ariadne did not attempt to bypass it.',
  UPSTREAM_ACCESS_BLOCKED: 'The provider refused this request.',
  REDIRECT_REFUSED: 'The provider redirected the request; Ariadne refused the redirect.',
  TIMEOUT: 'The provider did not respond before the local timeout.',
  RESPONSE_LIMIT: 'The provider response exceeded the local safety limit.',
  NETWORK_UNAVAILABLE: 'The network or provider is currently unavailable.',
  UPSTREAM_UNAVAILABLE: 'The provider is currently unavailable.',
  UPSTREAM_REJECTED: 'The provider rejected this request.',
  INVALID_RESPONSE: 'The provider returned an invalid or unsupported response.',
}

function normalizeQuery(value: string) {
  return value.normalize('NFKC').split(/\s+/u).filter(Boolean).join(' ')
}

function PublicDiscoveryWorkbench({ seed }: {
  seed: { readonly query: string; readonly provider: PublicDiscoveryProvider; readonly nonce: number } | null
}) {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [provider, setProvider] = useState<PublicDiscoveryProvider>('DUCKDUCKGO_HTML')
  const [query, setQuery] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState<PublicDiscoverySearchResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null)
  const [savedCaptures, setSavedCaptures] = useState<
    ReadonlyMap<string, PublicDiscoveryCaptureResult>
  >(new Map())
  const [savingUrl, setSavingUrl] = useState<string | null>(null)
  const details = providerDetails[provider]
  const normalizedQuery = normalizeQuery(query)
  const normalizedQueryBytes = new TextEncoder().encode(normalizedQuery).byteLength
  const queryWithinBoundary = normalizedQueryBytes <= 1_024

  useEffect(() => {
    if (!seed) return
    setProvider(seed.provider)
    setQuery(seed.query)
    setResult(null)
    setError(null)
  }, [seed])

  const runSearch = async () => {
    if (!authorized || normalizedQuery.length === 0 || !queryWithinBoundary || pending) return
    setPending(true)
    setError(null)
    setResult(null)
    try {
      const response = await searchPublicDiscovery({
        provider,
        query: normalizedQuery,
        authorizedSelfAudit: true,
        maxResults: 10,
      })
      setQuery(normalizedQuery)
      setResult(response)
    } catch {
      setError('The bounded public search could not be completed. No result was saved.')
    } finally {
      setPending(false)
    }
  }

  const copyUrl = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      setCopiedUrl(url)
    } catch {
      setError('The result URL could not be copied.')
    }
  }

  const saveFinding = async (item: PublicDiscoveryResultItem) => {
    if (
      profileId === null ||
      savingUrl !== null ||
      savedCaptures.has(item.url) ||
      result === null
    ) return
    setSavingUrl(item.url)
    setError(null)
    try {
      const capture = await capturePublicDiscovery({
        profileId,
        provider: item.provider,
        query: normalizedQuery,
        rank: item.rank,
        title: item.title,
        url: item.url,
        snippet: item.snippet,
        sourceId: item.sourceId,
        capturedAtUs: Date.now() * 1_000,
        authorizedSelfAudit: true,
      })
      setSavedCaptures((current) => new Map(current).set(item.url, capture))
    } catch {
      setError('The result could not be saved to the selected profile.')
    } finally {
      setSavingUrl(null)
    }
  }

  return (
    <div className="page-grid public-discovery-layout">
        <Panel
          className="span-4 panel--raised public-discovery-runner"
          eyebrow="Step 1 · approve payload"
          title="Search one public provider"
          action={<Wifi size={15} />}
        >
          <div className="panel__body stack">
            <fieldset className="public-discovery-provider-picker">
              <legend>Provider</legend>
              {(Object.keys(providerDetails) as PublicDiscoveryProvider[]).map((item) => {
                const option = providerDetails[item]
                return (
                  <label className={provider === item ? 'is-selected' : ''} key={item}>
                    <input
                      checked={provider === item}
                      name="public-discovery-provider"
                      onChange={() => {
                        setProvider(item)
                        setResult(null)
                      }}
                      type="radio"
                    />
                    <span><strong>{option.label}</strong><small>{option.operator}</small></span>
                  </label>
                )
              })}
            </fieldset>

            <div className="field">
              <label htmlFor="public-discovery-query">Exact query sent to {details.operator}</label>
              <div className="input-with-icon">
                <Search size={14} />
                <input
                  autoComplete="off"
                  className="input"
                  id="public-discovery-query"
                  maxLength={1_024}
                  onChange={(event) => {
                    setQuery(event.target.value)
                    setResult(null)
                  }}
                  placeholder={provider === 'GITHUB_USERS' ? 'Public username or organisation' : 'Name, username, domain, or quoted phrase'}
                  spellCheck={false}
                  value={query}
                />
              </div>
              <small>{details.description} The query is not written to Ariadne's database.</small>
              {!queryWithinBoundary && <small>Shorten this query to 1,024 UTF-8 bytes before sending it.</small>}
            </div>

            <label className="public-discovery-consent">
              <input
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
                type="checkbox"
              />
              <span>
                <strong>I authorise this self-audit search</strong>
                <small>I own or am authorised to investigate this identifier and approve sending the exact query above.</small>
              </span>
            </label>

            <div className="callout callout--warning">
              <ShieldCheck size={15} />
              <span>Provider retention is unknown. Do not enter passwords, tokens, recovery codes, or private document contents.</span>
            </div>

            <Button
              disabled={!authorized || normalizedQuery.length === 0 || !queryWithinBoundary || pending}
              onClick={() => void runSearch()}
              variant="primary"
            >
              {pending ? <LoaderCircle className="spin" size={14} /> : <Radar size={14} />}
              {pending ? 'Searching…' : 'Run authorised search'}
            </Button>
          </div>
        </Panel>

        <Panel
          className="span-8 public-discovery-results"
          eyebrow="Step 2 · review before saving"
          title={result === null ? 'No search run yet' : `${result.results.length} public results`}
          action={
            result === null ? null : (
              <Badge tone={result.state === 'SUCCEEDED' ? 'green' : 'amber'}>{result.state.replaceAll('_', ' ')}</Badge>
            )
          }
        >
          <div className="panel__body stack">
            {error !== null ? <div className="callout callout--danger" role="alert">{error}</div> : null}
            {result === null && !pending ? (
              <div className="public-discovery-empty">
                <FileSearch size={24} />
                <strong>Nothing has been transmitted</strong>
                <span>Choose a provider, inspect the exact query, confirm authorisation, and run the search.</span>
              </div>
            ) : null}
            {pending ? (
              <div className="public-discovery-empty" aria-live="polite">
                <LoaderCircle className="spin" size={24} />
                <strong>Waiting for {details.operator}</strong>
                <span>One bounded request is in progress. Ariadne will not follow redirects or challenges.</span>
              </div>
            ) : null}
            {result !== null ? (
              <>
                <div className="public-discovery-status">
                  {result.state === 'SUCCEEDED' ? <CheckCircle2 size={15} /> : <BadgeInfo size={15} />}
                  <span>{reasonLabels[result.reason] ?? result.reason.replaceAll('_', ' ')}</span>
                  {result.truncated ? <Badge tone="amber">Truncated</Badge> : null}
                </div>
                {result.results.map((item) => {
                  const capture = savedCaptures.get(item.url)
                  const saved = capture !== undefined
                  return (
                    <article className="public-discovery-result" key={item.url}>
                      <div className="public-discovery-result__rank mono">{String(item.rank).padStart(2, '0')}</div>
                      <div className="public-discovery-result__copy">
                        <strong>{item.title}</strong>
                        <small>{providerDetails[item.provider].operator}{item.sourceId === null ? '' : ` · source ID ${item.sourceId}`}</small>
                        <span className="mono">{item.url}</span>
                        {item.snippet === null ? null : <p>{item.snippet}</p>}
                        {capture === undefined ? null : (
                          <small className="mono">
                            Exact URL reference retained · artifact {capture.artifactId} · finding {capture.findingId}
                          </small>
                        )}
                      </div>
                      <div className="public-discovery-result__actions">
                        <Button onClick={() => void copyUrl(item.url)} size="compact" variant="ghost">
                          <Copy size={13} /> {copiedUrl === item.url ? 'Copied' : 'Copy URL'}
                        </Button>
                        <Button
                          disabled={profileId === null || saved || savingUrl !== null}
                          onClick={() => void saveFinding(item)}
                          size="compact"
                          variant="secondary"
                        >
                          {savingUrl === item.url ? <LoaderCircle className="spin" size={13} /> : <Save size={13} />}
                          {saved ? 'Saved' : 'Save finding'}
                        </Button>
                      </div>
                    </article>
                  )
                })}
                {profileId === null && result.results.length > 0 ? (
                  <div className="callout callout--info">Select or create a profile in the top bar before saving a reviewed result.</div>
                ) : null}
              </>
            ) : null}
          </div>
        </Panel>
    </div>
  )
}

type HibpSeed = {
  readonly value: string
  readonly kind: 'EMAIL' | 'DOMAIN'
  readonly nonce: number
}

function HibpWorkbench({ seed }: { seed: HibpSeed | null }) {
  const [scope, setScope] = useState<'ACCOUNT' | 'DOMAIN'>('ACCOUNT')
  const [target, setTarget] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [mode, setMode] = useState<HibpAccountMode>('K_ANONYMITY')
  const [authorized, setAuthorized] = useState(false)
  const [directAuthorized, setDirectAuthorized] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accountResult, setAccountResult] = useState<HibpAccountSearchResult | null>(null)
  const [domainResult, setDomainResult] = useState<HibpDomainSearchResult | null>(null)

  useEffect(() => {
    if (!seed) return
    setScope(seed.kind === 'EMAIL' ? 'ACCOUNT' : 'DOMAIN')
    setTarget(seed.value)
    setAccountResult(null)
    setDomainResult(null)
    setError(null)
  }, [seed])

  const run = async () => {
    if (!authorized || !target.trim() || !apiKey.trim() || pending) return
    setPending(true)
    setError(null)
    setAccountResult(null)
    setDomainResult(null)
    try {
      if (scope === 'ACCOUNT') {
        setAccountResult(await searchHibpAccount({
          email: target.trim(),
          apiKey: apiKey.trim(),
          mode,
          authorizedSelfAudit: true,
          authorizedDirectIdentifierTransmission: mode === 'DIRECT' && directAuthorized,
        }))
      } else {
        setDomainResult(await searchHibpDomain({
          domain: target.trim(),
          apiKey: apiKey.trim(),
          authorizedSelfAudit: true,
        }))
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The HIBP request failed safely.')
    } finally {
      setApiKey('')
      setPending(false)
    }
  }

  const result = accountResult ?? domainResult
  const breachCount = accountResult?.breaches.length ??
    domainResult?.accounts.reduce((sum, account) => sum + account.breaches.length, 0) ?? 0
  const openSource = async (url: string) => {
    try {
      await openApprovedExternalUrl(url)
    } catch {
      setError('The approved HIBP source could not be opened in the default browser.')
    }
  }

  return (
    <div className="page-grid public-discovery-layout hibp-layout">
      <Panel className="span-4 panel--raised" eyebrow="Authorised breach awareness" title="Have I Been Pwned v3" action={<KeyRound size={15} />}>
        <div className="panel__body stack">
          <div className="segmented-control" aria-label="HIBP search scope">
            <button className={scope === 'ACCOUNT' ? 'is-active' : ''} onClick={() => { setScope('ACCOUNT'); setAccountResult(null); setDomainResult(null) }}>Email account</button>
            <button className={scope === 'DOMAIN' ? 'is-active' : ''} onClick={() => { setScope('DOMAIN'); setAccountResult(null); setDomainResult(null) }}>Verified domain</button>
          </div>
          <label className="field">
            <span>{scope === 'ACCOUNT' ? 'Email address' : 'Provider-verified domain'}</span>
            <input autoComplete="off" maxLength={254} onChange={(event) => setTarget(event.target.value)} placeholder={scope === 'ACCOUNT' ? 'you@example.invalid' : 'example.invalid'} spellCheck={false} type={scope === 'ACCOUNT' ? 'email' : 'text'} value={target} />
          </label>
          {scope === 'ACCOUNT' && (
            <fieldset className="public-discovery-provider-picker">
              <legend>Email disclosure mode</legend>
              <label className={mode === 'K_ANONYMITY' ? 'is-selected' : ''}><input checked={mode === 'K_ANONYMITY'} name="hibp-mode" onChange={() => setMode('K_ANONYMITY')} type="radio" /><span><strong>K-anonymity</strong><small>Send a partial SHA-1 prefix</small></span></label>
              <label className={mode === 'DIRECT' ? 'is-selected' : ''}><input checked={mode === 'DIRECT'} name="hibp-mode" onChange={() => setMode('DIRECT')} type="radio" /><span><strong>Direct email</strong><small>Send the complete address</small></span></label>
            </fieldset>
          )}
          <label className="field">
            <span>HIBP API key · cleared after request</span>
            <input autoComplete="off" maxLength={32} onChange={(event) => setApiKey(event.target.value)} placeholder="32-character subscription key" spellCheck={false} type="password" value={apiKey} />
            <small>The key is used only for this request and never returned or written to the vault.</small>
          </label>
          <label className="public-discovery-consent"><input checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} type="checkbox" /><span><strong>I authorise this self-audit</strong><small>I own or control this account/domain, or have explicit authority to investigate it.</small></span></label>
          {scope === 'ACCOUNT' && mode === 'DIRECT' && (
            <label className="public-discovery-consent"><input checked={directAuthorized} onChange={(event) => setDirectAuthorized(event.target.checked)} type="checkbox" /><span><strong>I approve direct email transmission</strong><small>The full address will be sent to haveibeenpwned.com.</small></span></label>
          )}
          <Button disabled={!authorized || !target.trim() || !apiKey.trim() || pending || (scope === 'ACCOUNT' && mode === 'DIRECT' && !directAuthorized)} onClick={() => void run()} variant="primary">
            {pending ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />}{pending ? 'Checking…' : 'Run HIBP check'}
          </Button>
        </div>
      </Panel>

      <Panel className="span-8" eyebrow="Exact provider evidence" title={result ? `${breachCount} breach references` : 'No HIBP check yet'} action={result ? <Badge tone={result.state === 'SUCCEEDED' ? 'green' : 'amber'}>{result.state.replaceAll('_', ' ')}</Badge> : null}>
        <div className="panel__body stack">
          {error && <div className="callout callout--danger" role="alert">{error}</div>}
          {!result && !pending && <div className="public-discovery-empty"><KeyRound size={24} /><strong>No identifier has been transmitted</strong><span>Choose the least-disclosing supported mode, confirm authority, and run one bounded request.</span></div>}
          {pending && <div className="public-discovery-empty"><LoaderCircle className="spin" size={24} /><strong>Waiting for Have I Been Pwned</strong><span>Redirects are disabled and rate-limit instructions are preserved.</span></div>}
          {result && (
            <>
              <div className="public-discovery-status"><ShieldCheck size={15} /><span>{reasonLabels[result.reason] ?? result.reason.replaceAll('_', ' ')}</span>{result.retryAfterSeconds !== null && <Badge tone="amber">Retry after {result.retryAfterSeconds}s</Badge>}</div>
              <div className="hibp-attribution"><span>Source and attribution</span><a href={result.providerHomeUrl} onClick={(event) => { event.preventDefault(); void openSource(result.providerHomeUrl) }} target="_blank" rel="noreferrer">Have I Been Pwned <ExternalLink size={12} /></a><a href={result.apiDocumentationUrl} onClick={(event) => { event.preventDefault(); void openSource(result.apiDocumentationUrl) }} target="_blank" rel="noreferrer">API v3 documentation <ExternalLink size={12} /></a><Badge>{result.license}</Badge></div>
              {accountResult?.breaches.map((breach) => (
                <article className="hibp-breach" key={breach.sourceUrl}><div><strong>{breach.name}</strong><small>Exact HIBP breach-record source</small></div><a href={breach.sourceUrl} onClick={(event) => { event.preventDefault(); void openSource(breach.sourceUrl) }} target="_blank" rel="noreferrer">{breach.sourceUrl} <ExternalLink size={12} /></a></article>
              ))}
              {domainResult?.accounts.map((account) => (
                <article className="hibp-account" key={account.alias}><header><strong>{account.alias}</strong><Badge tone="amber">{account.breaches.length} breaches</Badge></header>{account.breaches.map((breach) => <a href={breach.sourceUrl} key={breach.sourceUrl} onClick={(event) => { event.preventDefault(); void openSource(breach.sourceUrl) }} target="_blank" rel="noreferrer"><span>{breach.name}</span><code>{breach.sourceUrl}</code><ExternalLink size={12} /></a>)}</article>
              ))}
              {result.requests.map((request) => (
                <details className="hibp-request" key={request.sequence}><summary>Request {request.sequence} · {request.operation.replaceAll('_', ' ')}</summary><dl><div><dt>Exact endpoint</dt><dd><code>{request.requestUrl}</code></dd></div><div><dt>Identifier disclosure</dt><dd>{request.identifierDisclosure.replaceAll('_', ' ')}</dd></div><div><dt>HTTP / bytes</dt><dd>{request.httpStatus ?? 'No response'} · {request.responseBytes}</dd></div><div><dt>Observed</dt><dd>{request.observedAt}</dd></div><div><dt>Request SHA-256</dt><dd><code>{request.requestSha256}</code></dd></div></dl></details>
              ))}
            </>
          )}
        </div>
      </Panel>
    </div>
  )
}

type InvestigationHandoff =
  | { readonly surface: 'PUBLIC'; readonly value: string; readonly provider: PublicDiscoveryProvider }
  | { readonly surface: 'HIBP'; readonly value: string; readonly kind: 'EMAIL' | 'DOMAIN' }

function InvestigationPlanner({ onHandoff }: { onHandoff: (handoff: InvestigationHandoff) => void }) {
  const [identifiers, setIdentifiers] = useState<ReadonlyArray<InvestigationIdentifier>>([
    { identifierRef: 'identifier-1', kind: 'USERNAME', value: '' },
  ])
  const [providers, setProviders] = useState<ReadonlyArray<InvestigationProvider>>([
    'DUCKDUCKGO_HTML', 'GITHUB_USERS', 'HAVE_I_BEEN_PWNED_V3',
  ])
  const [authorized, setAuthorized] = useState(false)
  const [hibpKey, setHibpKey] = useState(false)
  const [hibpKAnon, setHibpKAnon] = useState(false)
  const [directEmail, setDirectEmail] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState<InvestigationPlan | null>(null)

  const updateIdentifier = (index: number, patch: Partial<InvestigationIdentifier>) => {
    setIdentifiers((current) => current.map((item, candidate) => candidate === index ? { ...item, ...patch } : item))
    setPlan(null)
  }
  const addIdentifier = () => setIdentifiers((current) => current.length >= 8 ? current : [...current, { identifierRef: `identifier-${current.length + 1}`, kind: 'USERNAME', value: '' }])
  const removeIdentifier = (index: number) => setIdentifiers((current) => current.filter((_, candidate) => candidate !== index).map((item, candidate) => ({ ...item, identifierRef: `identifier-${candidate + 1}` })))
  const toggleProvider = (provider: InvestigationProvider) => setProviders((current) => current.includes(provider) ? current.filter((item) => item !== provider) : [...current, provider])

  const compile = async () => {
    if (identifiers.some((item) => !item.value.trim()) || providers.length === 0) return
    setPending(true); setError(null); setPlan(null)
    try {
      setPlan(await compileInvestigationPlan({ identifiers: identifiers.map((item) => ({ ...item, value: item.value.trim() })), enabledProviders: providers, authorizedSelfAudit: authorized, hibpApiKeyAvailable: hibpKey, hibpKAnonymityAvailable: hibpKAnon, authorizedDirectEmailTransmission: directEmail }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The plan could not be compiled.')
    } finally { setPending(false) }
  }

  const handoff = (step: InvestigationPlanStep) => {
    const identifier = identifiers.find((item) => item.identifierRef === step.identifierRef)
    if (!identifier) return
    if (step.provider === 'HAVE_I_BEEN_PWNED_V3') {
      onHandoff({ surface: 'HIBP', value: identifier.value.trim(), kind: identifier.kind === 'DOMAIN' ? 'DOMAIN' : 'EMAIL' })
    } else {
      onHandoff({ surface: 'PUBLIC', value: identifier.value.trim(), provider: step.provider as PublicDiscoveryProvider })
    }
  }

  return (
    <div className="page-grid investigation-layout">
      <Panel className="span-5 panel--raised" eyebrow="Deterministic workflow compiler" title="Compose an investigation" action={<Route size={15} />}>
        <div className="panel__body stack">
          <div className="investigation-identifiers">
            {identifiers.map((identifier, index) => <div className="investigation-identifier" key={identifier.identifierRef}><select aria-label={`Identifier ${index + 1} kind`} value={identifier.kind} onChange={(event) => updateIdentifier(index, { kind: event.target.value as InvestigationIdentifierKind })}>{['EMAIL', 'USERNAME', 'DOMAIN', 'NAME', 'URL'].map((kind) => <option key={kind} value={kind}>{kind.replaceAll('_', ' ')}</option>)}</select><input aria-label={`Identifier ${index + 1} value`} autoComplete="off" maxLength={1_024} onChange={(event) => updateIdentifier(index, { value: event.target.value })} placeholder="Exact value" spellCheck={false} value={identifier.value} />{identifiers.length > 1 && <Button aria-label={`Remove identifier ${index + 1}`} onClick={() => removeIdentifier(index)} size="compact" variant="ghost"><Trash2 size={13} /></Button>}</div>)}
          </div>
          <Button disabled={identifiers.length >= 8} onClick={addIdentifier} size="compact" variant="secondary"><Plus size={13} />Add identifier</Button>
          <fieldset className="investigation-providers"><legend>Available execution surfaces</legend>{(['DUCKDUCKGO_HTML', 'GITHUB_USERS', 'HAVE_I_BEEN_PWNED_V3'] as InvestigationProvider[]).map((provider) => <label key={provider}><input checked={providers.includes(provider)} onChange={() => toggleProvider(provider)} type="checkbox" /><span>{provider.replaceAll('_', ' ')}</span></label>)}</fieldset>
          <label className="public-discovery-consent"><input checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} type="checkbox" /><span><strong>I authorise this self-audit plan</strong><small>Compilation itself makes no network request.</small></span></label>
          <div className="investigation-capabilities"><label><input checked={hibpKey} onChange={(event) => setHibpKey(event.target.checked)} type="checkbox" />HIBP key available</label><label><input checked={hibpKAnon} disabled={!hibpKey} onChange={(event) => setHibpKAnon(event.target.checked)} type="checkbox" />K-anonymity plan available</label><label><input checked={directEmail} onChange={(event) => setDirectEmail(event.target.checked)} type="checkbox" />Direct email approved</label></div>
          <Button disabled={pending || identifiers.some((item) => !item.value.trim()) || providers.length === 0} onClick={() => void compile()} variant="primary">{pending ? <LoaderCircle className="spin" size={14} /> : <Route size={14} />}{pending ? 'Compiling…' : 'Compile without executing'}</Button>
        </div>
      </Panel>
      <Panel className="span-7" eyebrow="Inspect before execution" title={plan ? `${plan.steps.length} ordered steps` : 'No plan compiled'} action={plan ? <Badge tone="green">Network-free</Badge> : null}>
        <div className="panel__body stack">
          {error && <div className="callout callout--danger" role="alert">{error}</div>}
          {!plan && <div className="public-discovery-empty"><Route size={24} /><strong>Combine identifiers and providers safely</strong><span>The compiler hashes returned identifier references, lists prerequisites and transmission modes, and executes nothing.</span></div>}
          {plan?.notices.map((notice) => <div className="callout callout--warning" key={notice}>{notice.replaceAll('_', ' ')}</div>)}
          {plan?.steps.map((step) => <article className="investigation-step" key={step.stepId}><div className="investigation-step__sequence">{String(step.sequence).padStart(2, '0')}</div><div><header><strong>{step.operation.replaceAll('_', ' ')}</strong><Badge>{step.provider.replaceAll('_', ' ')}</Badge></header><span>{step.identifierKind} · SHA-256 <code>{step.identifierSha256}</code></span><small>{step.transmission.replaceAll('_', ' ')} · {step.executionRoute}</small><div className="chip-wrap">{step.prerequisites.map((item) => <Badge key={item} tone="neutral">{item.replaceAll('_', ' ')}</Badge>)}</div></div><Button onClick={() => handoff(step)} size="compact" variant="secondary"><ArrowRight size={13} />Load</Button></article>)}
          {plan && <small className="mono">{plan.planId} · deterministic · executed: no</small>}
        </div>
      </Panel>
    </div>
  )
}

function ManualPortalDirectory() {
  const [launchError, setLaunchError] = useState<string | null>(null)
  const openPortal = async (url: string) => {
    setLaunchError(null)
    try {
      await openApprovedExternalUrl(url)
    } catch {
      setLaunchError('The approved portal could not be opened in the default browser.')
    }
  }
  return (
    <div className="stack">
      {launchError && <div className="callout callout--danger" role="alert">{launchError}</div>}
      <div className="research-portal-grid">
        {manualResearchPortals.map((portal) => (
          <article className="research-portal" key={portal.id}><header><Badge tone={portal.category === 'BREACH_AWARENESS' ? 'amber' : portal.category === 'REMOVAL' ? 'green' : 'cyan'}>{portal.category.replaceAll('_', ' ')}</Badge><ExternalLink size={14} /></header><h2>{portal.name}</h2><span>{portal.operator}</span><p>{portal.description}</p><small>{portal.accessNote}</small><div className="callout callout--info">{portal.importNote}</div><a href={portal.url} onClick={(event) => { event.preventDefault(); void openPortal(portal.url) }} target="_blank" rel="noreferrer">Open official portal <ExternalLink size={12} /></a></article>
        ))}
      </div>
    </div>
  )
}

type NativeToolSurface = 'PUBLIC' | 'QUERY' | 'HIBP' | 'PLAN' | 'PORTALS'

function NativeToolsPage() {
  const [surface, setSurface] = useState<NativeToolSurface>('PUBLIC')
  const [publicSeed, setPublicSeed] = useState<{ query: string; provider: PublicDiscoveryProvider; nonce: number } | null>(null)
  const [hibpSeed, setHibpSeed] = useState<HibpSeed | null>(null)
  const handoff = (value: InvestigationHandoff) => {
    if (value.surface === 'PUBLIC') {
      setPublicSeed({ query: value.value, provider: value.provider, nonce: Date.now() })
      setSurface('PUBLIC')
    } else {
      setHibpSeed({ value: value.value, kind: value.kind, nonce: Date.now() })
      setSurface('HIBP')
    }
  }
  const loadAdvancedQuery = (query: string) => {
    setPublicSeed({ query, provider: 'DUCKDUCKGO_HTML', nonce: Date.now() })
    setSurface('PUBLIC')
  }
  return (
    <div className="page public-discovery-page" data-testid="route-ready">
      <PageHeader eyebrow="Authorised research workbench" title="Discovery Console" description="Search bounded public sources, compose advanced multi-engine queries, check breach exposure, combine workflows, and retain exact source URLs." meta={<><Badge tone="amber" dot>Explicit external requests</Badge><Badge tone="green">No bypass automation</Badge><Badge tone="violet">Exact-source review</Badge></>} />
      <div className="discovery-surface-tabs" role="tablist" aria-label="Discovery workspace">
        {([['PUBLIC', Search, 'Public search'], ['QUERY', FileSearch, 'Query composer'], ['HIBP', KeyRound, 'Breach exposure'], ['PLAN', Route, 'Plan & combine'], ['PORTALS', ExternalLink, 'Manual portals']] as const).map(([value, Icon, label]) => <button aria-selected={surface === value} className={surface === value ? 'is-active' : ''} key={value} onClick={() => setSurface(value)} role="tab"><Icon size={15} /><span>{label}</span></button>)}
      </div>
      <div hidden={surface !== 'PUBLIC'}><PublicDiscoveryWorkbench seed={publicSeed} /></div>
      <div hidden={surface !== 'QUERY'}><AdvancedSearchComposer onLoadInAriadne={loadAdvancedQuery} /></div>
      <div hidden={surface !== 'HIBP'}><HibpWorkbench seed={hibpSeed} /></div>
      <div hidden={surface !== 'PLAN'}><InvestigationPlanner onHandoff={handoff} /></div>
      <div hidden={surface !== 'PORTALS'}><ManualPortalDirectory /></div>
    </div>
  )
}

function SyntheticToolsPage() {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('All tools')
  const { selectedTool, selectTool } = usePrototypeStore()
  const filteredTools = useMemo(
    () => toolCatalog.filter(([name, , description]) => `${name} ${description}`.toLowerCase().includes(query.toLowerCase())),
    [query],
  )
  const selected = toolCatalog.find(([name]) => name === selectedTool) ?? toolCatalog[1]

  return (
    <div className="page tools-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Independent investigations"
        title="Tool Console"
        description="Run one bounded capability without starting a complete audit. Inputs remain isolated unless you explicitly save them."
        meta={
          <>
            <Badge tone="green" dot>Local-only policy</Badge>
            <Badge tone="cyan">21 tools</Badge>
            <Badge tone="violet">Human review at every boundary</Badge>
          </>
        }
        actions={<Button variant="secondary"><Clock3 size={14} /> Recent traces</Button>}
      />

      <div className="tool-toolbar">
        <label className="tool-search">
          <Search size={15} />
          <span className="sr-only">Search tools</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by capability or identifier…" />
          <kbd>⌘K</kbd>
        </label>
        <div className="segmented-control" aria-label="Tool category">
          {['All tools', 'Trace', 'Local', 'Analyse'].map((item) => (
            <button className={category === item ? 'is-active' : ''} onClick={() => setCategory(item)} key={item}>{item}</button>
          ))}
        </div>
        <Button variant="ghost" size="compact"><Filter size={13} /> Filters</Button>
      </div>

      <div className="compact-workflow-action compact-workflow-action--tool" role="region" aria-label="Targeted trace action">
        <div>
          <strong>{selected[0]} · 2 providers</strong>
          <span>Payload and jurisdiction review required</span>
        </div>
        <Button variant="primary"><Radar size={14} /> Review &amp; simulate trace</Button>
      </div>

      <div className="page-grid tools-layout">
        <Panel className="span-8 tool-catalog-panel" eyebrow="Capability catalog" title={`${filteredTools.length} available tools`} action={<span className="muted mono">{category}</span>}>
          <div className="tool-card-grid">
            {filteredTools.map(([name, icon, description, risk]) => {
              const Icon = toolIcons[icon]
              const isSelected = selectedTool === name
              return (
                <button className={`tool-card ${isSelected ? 'is-selected' : ''}`} key={name} onClick={() => selectTool(name)} aria-pressed={isSelected}>
                  <span className="tool-card__icon"><Icon size={17} /></span>
                  <span className="tool-card__copy"><strong>{name}</strong><span>{description}</span></span>
                  <Badge tone={riskTone(risk)}>{risk}</Badge>
                  <ArrowRight className="tool-card__arrow" size={13} />
                </button>
              )
            })}
          </div>
        </Panel>

        <Panel className="span-4 panel--raised tool-workspace" eyebrow="Targeted trace · isolated" title={selected[0]} action={<Wrench size={15} />}>
          <div className="panel__body stack">
            <div className="tool-selected-intro">
              <span className="status-icon status-icon--violet"><Fingerprint size={15} /></span>
              <p>{selected[2]}</p>
            </div>

            <div className="field">
              <label htmlFor="tool-input">Synthetic input</label>
              <div className="input-with-icon"><AtSign size={14} /><input id="tool-input" className="input mono" defaultValue={syntheticProfile.username} /></div>
              <small>Stored only in this deterministic prototype session.</small>
            </div>

            <div className="tool-detail-section">
              <div className="space-between"><strong>Controlled variants</strong><Badge tone="cyan">3 generated</Badge></div>
              <div className="chip-wrap"><Badge>@night_orbit</Badge><Badge>night_orbit</Badge><Badge>night-orbit</Badge></div>
            </div>

            <div className="tool-detail-section">
              <div className="space-between"><strong>Selected providers</strong><span className="mono muted">2 / 6</span></div>
              {providers.slice(0, 3).map((provider, index) => (
                <div className="tool-provider-row" key={provider.id}>
                  <span className={`provider-mini__health is-${provider.health}`} />
                  <div><strong>{provider.name}</strong><small>{provider.country} · {provider.retention}</small></div>
                  <input type="checkbox" defaultChecked={index < 2} aria-label={`Use ${provider.name}`} />
                </div>
              ))}
            </div>

            <div className="tool-budget">
              <div><Database size={13} /><span>8 checks</span></div>
              <div><Clock3 size={13} /><span>~2 min</span></div>
              <div><Globe2 size={13} /><span>Local + EU</span></div>
            </div>
            <Progress value={36} tone="violet" label="36 percent of configured query budget" />

            <div className="callout callout--success">
              <ShieldCheck size={15} /><span>Exact payload and jurisdiction will be shown again before the simulated run begins.</span>
            </div>
            <Button variant="primary"><Radar size={14} /> Review & simulate trace</Button>
            <Button variant="ghost" size="compact"><BadgeInfo size={13} /> Keep isolated from profile</Button>
          </div>
        </Panel>
      </div>

      <div className="tool-footer-note">
        <FileSearch size={14} />
        <span>Tool results preserve raw and normalised views, provenance, check outcome, and save-to-profile choice.</span>
      </div>
    </div>
  )
}

export function ToolsPage() {
  return nativeRuntimeAvailable() ? <NativeToolsPage /> : <SyntheticToolsPage />
}
