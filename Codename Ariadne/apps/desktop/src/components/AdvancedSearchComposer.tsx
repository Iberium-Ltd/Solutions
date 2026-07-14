import { useMemo, useState } from 'react'
import { Copy, ExternalLink, FileSearch, Search, ShieldCheck } from 'lucide-react'
import {
  buildSearchEngineUrl,
  composeAdvancedSearchQuery,
  searchEngines,
  type AdvancedSearchFields,
} from '../app/searchQueryComposer'
import { Badge, Button, Panel } from './Primitives'
import { openApprovedExternalUrl } from '../app/externalUrlBoundary'

const emptyFields: AdvancedSearchFields = {
  baseQuery: '',
  exactPhrase: '',
  anyTerms: '',
  site: '',
  excludedSite: '',
  fileType: '',
  titleContains: '',
  urlContains: '',
  excludedTerms: '',
  afterDate: '',
  beforeDate: '',
  additionalOperators: '',
}

const BOUNDED_DISCOVERY_QUERY_BYTES = 1_024

export function AdvancedSearchComposer({ onLoadInAriadne }: {
  readonly onLoadInAriadne: (query: string) => void
}) {
  const [fields, setFields] = useState<AdvancedSearchFields>(emptyFields)
  const [authorized, setAuthorized] = useState(false)
  const [copied, setCopied] = useState<'QUERY' | string | null>(null)
  const [launchError, setLaunchError] = useState<string | null>(null)
  const query = useMemo(() => composeAdvancedSearchQuery(fields), [fields])
  const queryBytes = new TextEncoder().encode(query).byteLength
  const ready = authorized && query.length > 0
  const boundedReady = ready && queryBytes <= BOUNDED_DISCOVERY_QUERY_BYTES
  const update = (field: keyof AdvancedSearchFields, value: string) => {
    setFields((current) => ({ ...current, [field]: value }))
    setCopied(null)
  }
  const copy = async (value: string, marker: 'QUERY' | string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(marker)
    } catch {
      setCopied(null)
    }
  }
  const open = async (value: string) => {
    setLaunchError(null)
    try {
      await openApprovedExternalUrl(value)
    } catch {
      setLaunchError('The approved URL could not be opened in the default browser.')
    }
  }

  return (
    <div className="page-grid advanced-search-layout">
      <Panel className="span-7 panel--raised" eyebrow="Local query construction" title="Advanced search composer" action={<Search size={15} />}>
        <div className="panel__body stack">
          <div className="advanced-search-fields">
            <label className="field advanced-search-field--wide"><span>Core query</span><input autoComplete="off" maxLength={512} onChange={(event) => update('baseQuery', event.target.value)} placeholder="Name, username, domain, or another authorised identifier" spellCheck={false} value={fields.baseQuery} /></label>
            <label className="field"><span>Exact phrase</span><input autoComplete="off" maxLength={256} onChange={(event) => update('exactPhrase', event.target.value)} placeholder="Words in this exact order" spellCheck={false} value={fields.exactPhrase} /></label>
            <label className="field"><span>Any of · comma separated</span><input autoComplete="off" maxLength={256} onChange={(event) => update('anyTerms', event.target.value)} placeholder="alias one, alias two" spellCheck={false} value={fields.anyTerms} /></label>
            <label className="field"><span>Only site or domain</span><input autoComplete="off" maxLength={255} onChange={(event) => update('site', event.target.value)} placeholder="example.invalid" spellCheck={false} value={fields.site} /></label>
            <label className="field"><span>Exclude site or domain</span><input autoComplete="off" maxLength={255} onChange={(event) => update('excludedSite', event.target.value)} placeholder="noise.example" spellCheck={false} value={fields.excludedSite} /></label>
            <label className="field"><span>File type</span><select onChange={(event) => update('fileType', event.target.value)} value={fields.fileType}><option value="">Any file type</option>{['pdf', 'docx', 'xlsx', 'pptx', 'csv', 'txt', 'json', 'xml'].map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label>
            <label className="field"><span>Words in page title</span><input autoComplete="off" maxLength={128} onChange={(event) => update('titleContains', event.target.value)} placeholder="Title phrase" spellCheck={false} value={fields.titleContains} /></label>
            <label className="field"><span>Words in URL</span><input autoComplete="off" maxLength={128} onChange={(event) => update('urlContains', event.target.value)} placeholder="profile or directory" spellCheck={false} value={fields.urlContains} /></label>
            <label className="field"><span>Exclude terms · comma separated</span><input autoComplete="off" maxLength={256} onChange={(event) => update('excludedTerms', event.target.value)} placeholder="unrelated term, false match" spellCheck={false} value={fields.excludedTerms} /></label>
            <label className="field"><span>After date</span><input onChange={(event) => update('afterDate', event.target.value)} type="date" value={fields.afterDate} /></label>
            <label className="field"><span>Before date</span><input onChange={(event) => update('beforeDate', event.target.value)} type="date" value={fields.beforeDate} /></label>
            <label className="field advanced-search-field--wide"><span>Additional provider-specific operators</span><input autoComplete="off" maxLength={512} onChange={(event) => update('additionalOperators', event.target.value)} placeholder="Optional expert syntax, appended exactly" spellCheck={false} value={fields.additionalOperators} /></label>
          </div>

          <div className="advanced-search-preview" aria-live="polite">
            <div><span>Exact generated query</span><Badge tone={queryBytes > BOUNDED_DISCOVERY_QUERY_BYTES ? 'amber' : query ? 'cyan' : 'neutral'}>{query ? `${queryBytes} / ${BOUNDED_DISCOVERY_QUERY_BYTES} bytes` : 'Empty'}</Badge></div>
            <code>{query || 'Add one or more query components.'}</code>
          </div>

          <div className="callout callout--info"><FileSearch size={15} /><span>Operators and date syntax are provider-dependent. Ariadne shows the exact query but does not claim identical results across engines.</span></div>
          {queryBytes > BOUNDED_DISCOVERY_QUERY_BYTES && <div className="callout callout--warning">Shorten the query before loading it into Ariadne's 1,024-byte bounded search. Browser handoff links remain user-mediated.</div>}
          <label className="public-discovery-consent"><input checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} type="checkbox" /><span><strong>I authorise this browser search</strong><small>The generated query concerns my own data or a subject I am explicitly authorised to investigate.</small></span></label>
          <div className="advanced-search-actions">
            <Button disabled={!query} onClick={() => void copy(query, 'QUERY')} variant="secondary"><Copy size={13} />{copied === 'QUERY' ? 'Query copied' : 'Copy exact query'}</Button>
            <Button disabled={!boundedReady} onClick={() => onLoadInAriadne(query)} variant="primary"><ShieldCheck size={13} />Load in bounded DuckDuckGo</Button>
          </div>
        </div>
      </Panel>

      <Panel className="span-5" eyebrow="User-mediated browser handoff" title="Search-engine launchpad" action={<ExternalLink size={15} />}>
        <div className="panel__body stack search-engine-list">
          <div className="callout callout--warning">Links open in your default macOS browser. Ariadne does not automate challenges, sign-ins, result pages, or provider access controls.</div>
          {launchError && <div className="callout callout--danger" role="alert">{launchError}</div>}
          {searchEngines.map((engine) => {
            const url = query ? buildSearchEngineUrl(engine.id, query) : ''
            return (
              <article className="search-engine-card" key={engine.id}>
                <div><strong>{engine.label}</strong><small>{engine.description}</small></div>
                <div className="search-engine-card__actions">
                  <Button disabled={!query} onClick={() => void copy(url, engine.id)} size="compact" variant="ghost"><Copy size={12} />{copied === engine.id ? 'Copied' : 'Copy URL'}</Button>
                  <a aria-disabled={!ready} className={ready ? '' : 'is-disabled'} href={ready ? url : undefined} onClick={(event) => { event.preventDefault(); if (ready) void open(url) }} rel="noreferrer" target="_blank">Open <ExternalLink size={12} /></a>
                </div>
              </article>
            )
          })}
          <small className="mono">Browser handoff only · generated URLs are visible and copyable · no result is saved automatically</small>
        </div>
      </Panel>
    </div>
  )
}
