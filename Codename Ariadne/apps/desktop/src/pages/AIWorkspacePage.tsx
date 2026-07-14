import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Cloud,
  FileText,
  GitBranch,
  Link2,
  ListTree,
  LoaderCircle,
  SearchCheck,
  Sparkles,
} from 'lucide-react'
import type {
  LocalAISettings,
  LocalAIWorkspaceDocument,
  LocalAIWorkspaceExecution,
  LocalAIWorkspaceResult,
  LocalAIWorkspaceScope,
  LocalAIWorkspaceTask,
} from '../../../../packages/contracts/src/generated/api'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  discoverLocalAIModels,
  getLocalAISettings,
  updateLocalAISettings,
} from '../app/localAiBoundary'
import { analyzeLocalAIWorkspace } from '../app/localAiWorkspaceBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import '../styles/pages-ai-workspace.css'

const TASKS: ReadonlyArray<{
  task: LocalAIWorkspaceTask
  label: string
  detail: string
  icon: typeof Sparkles
}> = [
  { task: 'SUMMARY', label: 'Summarize', detail: 'Cited overview', icon: Sparkles },
  { task: 'ORGANIZE', label: 'Organize', detail: 'Group records', icon: ListTree },
  { task: 'QUESTION', label: 'Ask', detail: 'Grounded answer', icon: BrainCircuit },
  { task: 'CONNECTIONS', label: 'Connections', detail: 'Review links', icon: GitBranch },
  { task: 'GAP_ANALYSIS', label: 'Evidence gaps', detail: 'Plan next checks', icon: SearchCheck },
]

const SCOPES: ReadonlyArray<{
  scope: LocalAIWorkspaceScope
  label: string
}> = [
  { scope: 'ENTITIES', label: 'Entities' },
  { scope: 'GRAPH', label: 'Graph' },
  { scope: 'FINDINGS', label: 'Findings' },
  { scope: 'REMEDIATION', label: 'Remediation' },
  { scope: 'AUDIT_COVERAGE', label: 'Audit coverage' },
  { scope: 'DOCUMENT', label: 'Pasted or selected document' },
]

const initialScopes: ReadonlyArray<LocalAIWorkspaceScope> = [
  'ENTITIES',
  'GRAPH',
  'FINDINGS',
  'REMEDIATION',
  'AUDIT_COVERAGE',
]

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return 'The local analysis could not be completed.'
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(value),
  )
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('')
}

function SourceRefs({
  refs,
  result,
  label,
}: {
  refs: readonly string[]
  result: LocalAIWorkspaceResult
  label: string
}) {
  const sources = refs.map((reference) => {
    const source = result.sources.find((candidate) => candidate.ref === reference)
    if (!source) throw new Error('A cited source is missing from the validated catalog')
    return source
  })
  return (
    <div className="ai-source-group">
      <span className="ai-source-group__label">{label}</span>
      {sources.map((source) => (
        <article className="ai-source" key={`${label}-${source.ref}`}>
          <div className="ai-source__topline">
            <Badge tone="cyan">{source.kind.replaceAll('_', ' ')}</Badge>
            <code>{source.ref}</code>
          </div>
          <strong>{source.label}</strong>
          <span className="ai-source__locator">{source.locator}</span>
          {source.sourceId && <span>Source ID <code>{source.sourceId}</code></span>}
          {source.sourceDisplayName && <span>Source <strong>{source.sourceDisplayName}</strong></span>}
          {source.artifactId && <span>Artifact ID <code>{source.artifactId}</code></span>}
          {source.segmentId && (
            <span>
              Segment <code>{source.segmentId}</code> · index {source.segmentIndex} ·{' '}
              <code>{source.segmentLocator}</code>
            </span>
          )}
          {source.sourceSpanStart != null && (
            <span>Source span {source.sourceSpanStart}–{source.sourceSpanEnd}</span>
          )}
          {source.extractionRunId && (
            <span>
              Extraction run <code>{source.extractionRunId}</code>
              {source.extractorName && ` · ${source.extractorKind} · ${source.extractorName} ${source.extractorVersion}`}
            </span>
          )}
          {source.runId && <span>Capture run <code>{source.runId}</code></span>}
          {(source.originKind || source.originType || source.disposition) && (
            <span>
              Origin {source.originKind ?? source.originType}
              {source.disposition && ` · ${source.disposition}`}
              {source.confidenceMicros != null && ` · ${source.confidenceMicros} µ-confidence`}
            </span>
          )}
          {source.sourceUrl && (
            <a href={source.sourceUrl} target="_blank" rel="noreferrer">
              <Link2 size={12} /> {source.sourceUrl}
            </a>
          )}
          {source.contentSha256 && (
            <span className="ai-source__digest">
              SHA-256 <code>{source.contentSha256}</code>
            </span>
          )}
          {source.sourceUrlSha256 && (
            <span className="ai-source__digest">
              URL SHA-256 <code>{source.sourceUrlSha256}</code>
            </span>
          )}
        </article>
      ))}
    </div>
  )
}

function WorkspaceResult({ result }: { result: LocalAIWorkspaceResult }) {
  return (
    <div className="ai-result" aria-live="polite">
      <div className="ai-result__identity">
        <Badge tone={result.executionMode === 'DETERMINISTIC' ? 'cyan' : 'violet'} dot>
          {result.executionMode === 'DETERMINISTIC' && result.provider === null
            ? 'Deterministic local analysis'
            : `${result.provider} · ${result.modelId}`}
        </Badge>
        <Badge tone={result.externalNetworkUsed ? 'amber' : 'green'}>
          {result.externalNetworkUsed ? 'External request used' : 'No external request'}
        </Badge>
        <Badge tone="amber">Review required</Badge>
        {result.fallbackReason && (
          <Badge tone="amber">Model fallback · {result.fallbackReason}</Badge>
        )}
      </div>

      <section className="ai-summary" aria-labelledby="ai-summary-title">
        <span>Model-generated summary · not an independently verified fact</span>
        <h2 id="ai-summary-title">{result.title}</h2>
        <p>{result.summary}</p>
      </section>

      {result.sections.length > 0 && (
        <section className="ai-output-section">
          <header>
            <h2>Organized notes</h2>
            <span>Model structure; validate against cited facts below</span>
          </header>
          <div className="ai-section-grid">
            {result.sections.map((section) => (
              <article key={section.heading}>
                <h3>{section.heading}</h3>
                <ul>
                  {section.items.map((item) => (
                    <li key={item.text}>
                      <span>{item.text}</span>
                      <SourceRefs
                        refs={item.evidenceRefs}
                        result={result}
                        label="Section sources"
                      />
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>
      )}

      {result.facts.length > 0 && (
        <section className="ai-output-section">
          <header>
            <h2>Cited facts</h2>
            <span>Every item below has an exact source locator</span>
          </header>
          <div className="ai-fact-list">
            {result.facts.map((fact) => (
              <article className="ai-fact" key={`${fact.statement}-${fact.evidenceRefs.join('-')}`}>
                <div className="ai-fact__statement">
                  <CheckCircle2 size={16} />
                  <p>{fact.statement}</p>
                  <Badge tone={fact.confidence === 'HIGH' ? 'green' : fact.confidence === 'LOW' ? 'amber' : 'cyan'}>
                    {fact.confidence}
                  </Badge>
                </div>
                <SourceRefs refs={fact.evidenceRefs} result={result} label="Evidence sources" />
              </article>
            ))}
          </div>
        </section>
      )}

      {result.connections.length > 0 && (
        <section className="ai-output-section">
          <header>
            <h2>Connection hypotheses</h2>
            <span>Possible relationships only; not confirmations</span>
          </header>
          <div className="ai-connection-list">
            {result.connections.map((connection) => (
              <article className="ai-connection" key={`${connection.fromRef}-${connection.relationship}-${connection.toRef}`}>
                <div className="ai-connection__path">
                  <code>{connection.fromRef}</code>
                  <span>{connection.relationship.replaceAll('_', ' ')}</span>
                  <code>{connection.toRef}</code>
                  <Badge tone={connection.confidence === 'HIGH' ? 'green' : connection.confidence === 'LOW' ? 'amber' : 'violet'}>
                    {connection.confidence}
                  </Badge>
                </div>
                <p>{connection.rationale}</p>
                <div className="ai-connection__sources">
                  <SourceRefs refs={[connection.fromRef, connection.toRef]} result={result} label="Endpoints" />
                  <SourceRefs refs={connection.supportingRefs} result={result} label="Supporting sources" />
                  {connection.contradictionRefs.length > 0 && (
                    <SourceRefs refs={connection.contradictionRefs} result={result} label="Contradicting sources" />
                  )}
                </div>
                <div className="ai-verification">
                  <SearchCheck size={14} />
                  <span><strong>Verify next:</strong> {connection.verificationSuggestion}</span>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {result.nextSteps.length > 0 && (
        <section className="ai-output-section">
          <header>
            <h2>Suggested next checks</h2>
            <span>Review-only suggestions; Ariadne did not execute them</span>
          </header>
          <div className="ai-step-list">
            {result.nextSteps.map((step) => (
              <article className="ai-step" key={`${step.priority}-${step.suggestion}`}>
                <Badge tone="violet">P{step.priority}</Badge>
                <div>
                  <h3>{step.suggestion}</h3>
                  <p>{step.rationale}</p>
                  <SourceRefs refs={step.supportingRefs} result={result} label="Basis sources" />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {result.unanswered && (
        <div className="ai-notice ai-notice--amber"><AlertTriangle size={15} /> {result.unanswered}</div>
      )}
      <section className="ai-limitations">
        <h2>Limits and provenance</h2>
        <ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        <dl>
          <div><dt>Projection hash</dt><dd><code>{result.inputSha256}</code></dd></div>
          <div><dt>Source catalog</dt><dd>{result.sources.length} exact cited sources</dd></div>
          <div><dt>Restricted values redacted</dt><dd>{result.restrictedValuesRedacted}</dd></div>
        </dl>
      </section>
    </div>
  )
}

export function AIWorkspacePage() {
  const native = nativeRuntimeAvailable()
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [task, setTask] = useState<LocalAIWorkspaceTask>('SUMMARY')
  const [scopes, setScopes] = useState<ReadonlyArray<LocalAIWorkspaceScope>>(initialScopes)
  const [question, setQuestion] = useState('')
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [execution, setExecution] = useState<LocalAIWorkspaceExecution>('DETERMINISTIC')
  const [settings, setSettings] = useState<LocalAISettings | null>(null)
  const [models, setModels] = useState<ReadonlyArray<string>>([])
  const [modelId, setModelId] = useState('')
  const [openAiModelId, setOpenAiModelId] = useState('gpt-5.6')
  const [openAiApiKey, setOpenAiApiKey] = useState('')
  const [selectedDocument, setSelectedDocument] = useState<LocalAIWorkspaceDocument | null>(null)
  const [documentText, setDocumentText] = useState('')
  const [pending, setPending] = useState(false)
  const [settingsPending, setSettingsPending] = useState(native)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LocalAIWorkspaceResult | null>(null)

  useEffect(() => {
    document.title = 'Local AI Workspace · Codename Ariadne'
    if (!native) return
    let cancelled = false
    setSettingsPending(true)
    void getLocalAISettings()
      .then(async (loaded) => {
        if (cancelled) return
        setSettings(loaded)
        setModelId(loaded.selectedModel ?? '')
        if (loaded.enabled && loaded.selectedModel) setExecution('LOCAL_MODEL')
        try {
          const discovered = await discoverLocalAIModels({
            provider: loaded.provider,
            endpoint: loaded.endpoint,
            selectedModel: loaded.selectedModel,
          })
          if (!cancelled) {
            const ids = discovered.models.map((model) => model.modelId)
            setModels(ids)
            if (!loaded.selectedModel && ids[0]) setModelId(ids[0])
          }
        } catch {
          if (!cancelled && loaded.selectedModel) setModels([loaded.selectedModel])
        }
      })
      .catch(() => {
        if (!cancelled) setError('Unlock the vault to use the local AI workspace.')
      })
      .finally(() => {
        if (!cancelled) setSettingsPending(false)
      })
    return () => {
      cancelled = true
    }
  }, [native])

  const scopeSet = useMemo(() => new Set(scopes), [scopes])

  const toggleScope = (scope: LocalAIWorkspaceScope) => {
    setScopes((current) =>
      current.includes(scope)
        ? current.filter((candidate) => candidate !== scope)
        : [...current, scope],
    )
    setResult(null)
  }

  const updatePaste = async (content: string) => {
    setDocumentText(content)
    if (!content.trim()) {
      setSelectedDocument(null)
      return
    }
    setSelectedDocument({
      kind: 'PASTE',
      displayName: 'Pasted workspace notes',
      declaredMediaType: 'text/plain',
      content,
      contentSha256: await sha256(content),
    })
  }

  const selectFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > 64 * 1024) {
      setError('Select a UTF-8 text file no larger than 64 KiB.')
      return
    }
    const content = await file.text()
    const mediaType = file.type || ({
      txt: 'text/plain', md: 'text/markdown', csv: 'text/csv',
      json: 'application/json', vcf: 'text/vcard',
    }[file.name.split('.').pop()?.toLowerCase() ?? ''] ?? '')
    setDocumentText(content)
    setSelectedDocument({
      kind: 'FILE',
      displayName: file.name,
      declaredMediaType: mediaType,
      content,
      contentSha256: await sha256(content),
    })
    setError(null)
  }

  const runAnalysis = async () => {
    if (!native) {
      setError('Open Ariadne as the native desktop app to run local analysis.')
      return
    }
    if (!profileId) {
      setError('Select or create a profile before running analysis.')
      return
    }
    if (scopes.length === 0) {
      setError('Select at least one data scope.')
      return
    }
    if (task === 'QUESTION' && !question.trim()) {
      setError('Enter a question to answer from the selected records.')
      return
    }
    if (scopeSet.has('DOCUMENT') && !selectedDocument) {
      setError('Paste text or select a supported document for the document scope.')
      return
    }
    if (execution === 'LOCAL_MODEL' && (!settings || !modelId)) {
      setError('Select an installed local model, or use deterministic mode.')
      return
    }
    if (
      execution === 'OPENAI_RESPONSES' &&
      (!openAiModelId.trim() || !openAiApiKey.trim())
    ) {
      setError('Enter an OpenAI API model and API key for this one request.')
      return
    }

    setPending(true)
    setError(null)
    setResult(null)
    try {
      let activeSettings = settings
      if (
        execution === 'LOCAL_MODEL' &&
        activeSettings &&
        (!activeSettings.enabled || activeSettings.selectedModel !== modelId)
      ) {
        activeSettings = await updateLocalAISettings({
          enabled: true,
          provider: activeSettings.provider,
          endpoint: activeSettings.endpoint,
          selectedModel: modelId,
          expectedRevision: activeSettings.revision,
        })
        setSettings(activeSettings)
      }
      const analyzed = await analyzeLocalAIWorkspace({
        profileId,
        task,
        question: task === 'QUESTION' ? question.trim() : null,
        scopes,
        includeSensitiveEntities: includeSensitive,
        execution,
        modelId:
          execution === 'LOCAL_MODEL'
            ? modelId
            : execution === 'OPENAI_RESPONSES'
              ? openAiModelId.trim()
              : null,
        openaiApiKey:
          execution === 'OPENAI_RESPONSES' ? openAiApiKey.trim() : null,
        document: scopeSet.has('DOCUMENT') ? selectedDocument : null,
      })
      setResult(analyzed)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      if (execution === 'OPENAI_RESPONSES') setOpenAiApiKey('')
      setPending(false)
    }
  }

  return (
    <div className="page ai-workspace-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Grounded reasoning · review only"
        title="AI Workspace"
        description="Use deterministic analysis, a selected local model, or an optional OpenAI Responses request to summarize, organize, question, and connect only the records you choose. Every factual output carries an exact source locator."
        meta={<>
          <Badge tone="green" dot>Deterministic or local by default</Badge>
          <Badge tone="cyan">Optional explicit OpenAI request</Badge>
          <Badge tone="violet">Nothing auto-saved or executed</Badge>
        </>}
      />

      {!native && (
        <div className="ai-notice ai-notice--amber"><AlertTriangle size={15} /> Native desktop runtime required; browser previews cannot read vault data or run models.</div>
      )}
      {!profileId && (
        <div className="ai-notice ai-notice--amber"><AlertTriangle size={15} /> No active profile. Select or create one before running analysis.</div>
      )}

      <div className="ai-workspace-layout">
        <Panel className="ai-compose" eyebrow="1 · Analysis request" title="Choose what Ariadne may inspect">
          <div className="ai-task-grid" role="radiogroup" aria-label="Analysis task">
            {TASKS.map(({ task: candidate, label, detail, icon: Icon }) => (
              <button
                type="button"
                className={candidate === task ? 'is-active' : ''}
                role="radio"
                aria-checked={candidate === task}
                onClick={() => { setTask(candidate); setResult(null) }}
                key={candidate}
              >
                <Icon size={16} /><strong>{label}</strong><span>{detail}</span>
              </button>
            ))}
          </div>

          {task === 'QUESTION' && (
            <label className="field ai-question">
              <span>Question grounded in selected sources</span>
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={2_000} rows={3} placeholder="What do the selected records show, and what remains uncertain?" />
            </label>
          )}

          <fieldset className="ai-scope-fieldset">
            <legend>Data scopes</legend>
            <div className="ai-scope-grid">
              {SCOPES.map(({ scope, label }) => (
                <label key={scope}>
                  <input type="checkbox" checked={scopeSet.has(scope)} onChange={() => toggleScope(scope)} />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="ai-sensitive-toggle">
            <input type="checkbox" checked={includeSensitive} onChange={(event) => setIncludeSensitive(event.target.checked)} />
            <span><strong>Include sensitive entity values</strong><small>Off by default. When off, only public or masked entity views enter the model projection.</small></span>
          </label>

          {scopeSet.has('DOCUMENT') && (
            <section className="ai-document">
              <div><FileText size={15} /><strong>In-memory document</strong><Badge tone="cyan">Not persisted</Badge></div>
              <textarea
                value={documentText}
                onChange={(event) => void updatePaste(event.target.value)}
                maxLength={65_536}
                rows={6}
                placeholder="Paste notes, CSV, JSON, vCard, or plain text…"
              />
              <label className="ai-file-picker">
                <span>Select UTF-8 file</span>
                <input type="file" accept=".txt,.md,.csv,.json,.vcf,text/plain,text/markdown,text/csv,application/json,text/vcard" onChange={(event) => void selectFile(event.target.files?.[0])} />
              </label>
              <small>Passwords, one-time codes, and restricted values are redacted before analysis. Maximum 64 KiB.</small>
            </section>
          )}
        </Panel>

        <Panel className="ai-execution" eyebrow="2 · Execution" title="Choose the reasoning engine">
          {settingsPending ? (
            <div className="ai-loading"><LoaderCircle className="spin" size={16} /> Reading local model settings…</div>
          ) : (
            <>
              <div className="ai-execution-options" role="radiogroup" aria-label="Execution mode">
                <label className={execution === 'LOCAL_MODEL' ? 'is-active' : ''}>
                  <input type="radio" name="execution" value="LOCAL_MODEL" checked={execution === 'LOCAL_MODEL'} onChange={() => setExecution('LOCAL_MODEL')} />
                  <Bot size={17} /><span><strong>Selected local model</strong><small>Structured, cited inference</small></span>
                </label>
                <label className={execution === 'DETERMINISTIC' ? 'is-active' : ''}>
                  <input type="radio" name="execution" value="DETERMINISTIC" checked={execution === 'DETERMINISTIC'} onChange={() => setExecution('DETERMINISTIC')} />
                  <ListTree size={17} /><span><strong>Deterministic</strong><small>Grouping and retrieval only</small></span>
                </label>
                <label className={execution === 'OPENAI_RESPONSES' ? 'is-active' : ''}>
                  <input type="radio" name="execution" value="OPENAI_RESPONSES" checked={execution === 'OPENAI_RESPONSES'} onChange={() => setExecution('OPENAI_RESPONSES')} />
                  <Cloud size={17} /><span><strong>OpenAI Responses</strong><small>Explicit external, cited request</small></span>
                </label>
              </div>

              <label className="field">
                <span>Installed model</span>
                <select value={modelId} disabled={execution !== 'LOCAL_MODEL'} onChange={(event) => setModelId(event.target.value)}>
                  <option value="">Select a local model</option>
                  {models.map((model) => <option value={model} key={model}>{model}</option>)}
                </select>
              </label>
              {execution === 'OPENAI_RESPONSES' && (
                <>
                  <label className="field">
                    <span>OpenAI API model</span>
                    <input
                      autoComplete="off"
                      maxLength={256}
                      onChange={(event) => setOpenAiModelId(event.target.value)}
                      spellCheck={false}
                      value={openAiModelId}
                    />
                    <small>Model access depends on your OpenAI API project. You can replace the suggested alias.</small>
                  </label>
                  <label className="field">
                    <span>OpenAI API key · used once</span>
                    <input
                      autoComplete="off"
                      maxLength={512}
                      onChange={(event) => setOpenAiApiKey(event.target.value)}
                      placeholder="sk-…"
                      spellCheck={false}
                      type="password"
                      value={openAiApiKey}
                    />
                    <small>Held only in this screen's memory, cleared after the request, sent through Ariadne Core to api.openai.com, and never returned or persisted.</small>
                  </label>
                </>
              )}
              {settings && (
                <dl className="ai-runtime-details">
                  <div><dt>Provider</dt><dd>{settings.provider}</dd></div>
                  <div><dt>Loopback endpoint</dt><dd><code>{settings.endpoint}</code></dd></div>
                  <div><dt>Network behavior</dt><dd>{execution === 'OPENAI_RESPONSES' ? 'Explicit one-request OpenAI' : 'No external request'}</dd></div>
                  <div><dt>Write access</dt><dd>None</dd></div>
                </dl>
              )}
            </>
          )}

          <div className="ai-notice">
            <BrainCircuit size={15} /> Summary text and relationship rationales are model-generated hypotheses. Only the “Cited facts” section is presented as factual, and each fact must expose its source.
          </div>
          {error && <div className="ai-notice ai-notice--danger" role="alert"><AlertTriangle size={15} /> {error}</div>}
          <Button variant="primary" onClick={() => void runAnalysis()} disabled={pending || settingsPending || !native || !profileId}>
            {pending ? <><LoaderCircle className="spin" size={15} /> Analyzing…</> : <><Sparkles size={15} /> Run review-only analysis</>}
          </Button>
          <small className="ai-execution__footnote">Local-model runs may activate the installed model selected in Settings. OpenAI runs transmit the selected bounded projection contents to api.openai.com only after this action; citation reference IDs are replaced with aliases. Results remain ephemeral.</small>
        </Panel>
      </div>

      {result ? (
        <WorkspaceResult result={result} />
      ) : (
        <Panel className="ai-empty" eyebrow="3 · Result" title="No analysis in this session">
          <Bot size={24} />
          <p>Choose a bounded scope and run the request. Ariadne will show model identity, fallbacks, exact citations, limits, and verification suggestions here.</p>
        </Panel>
      )}
    </div>
  )
}
