import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Cloud,
  FileStack,
  FileText,
  GitBranch,
  ListTree,
  LoaderCircle,
  Plus,
  SearchCheck,
  Sparkles,
  Trash2,
} from 'lucide-react'
import type { LocalAISettings } from '../../../../packages/contracts/src/generated/api'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  analyzeLocalCorpusAI,
  prepareLocalCorpusDocument,
  type LocalCorpusAIExecution,
  type LocalCorpusAIRequest,
  type LocalCorpusAIResult,
  type LocalCorpusAITask,
  type LocalCorpusDocumentRequest,
} from '../app/localCorpusAiBoundary'
import {
  discoverLocalAIModels,
  getLocalAISettings,
  updateLocalAISettings,
} from '../app/localAiBoundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Badge, Button, PageHeader, Panel } from '../components/Primitives'
import '../styles/pages-corpus-ai.css'

const TASKS: ReadonlyArray<{
  value: LocalCorpusAITask
  label: string
  detail: string
  icon: typeof Sparkles
}> = [
  { value: 'SUMMARY', label: 'Summarize', detail: 'Cited corpus overview', icon: Sparkles },
  { value: 'ORGANIZE', label: 'Organize', detail: 'Group across files', icon: ListTree },
  { value: 'QUESTION', label: 'Ask', detail: 'Grounded corpus answer', icon: BrainCircuit },
  { value: 'CONNECTIONS', label: 'Connections', detail: 'Cross-file hypotheses', icon: GitBranch },
  { value: 'GAP_ANALYSIS', label: 'Evidence gaps', detail: 'Prioritize review', icon: SearchCheck },
]

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'The local corpus analysis could not be completed.'
}

function unique(values: readonly string[]): readonly string[] {
  return [...new Set(values)]
}

function CorpusSources({
  references,
  result,
  label,
}: {
  references: readonly string[]
  result: LocalCorpusAIResult
  label: string
}) {
  const entries = unique(references).map((reference) => {
    const entry = result.sourceCatalog.find((candidate) => candidate.referenceId === reference)
    if (!entry) throw new Error('A validated corpus citation has no source entry')
    return entry
  })
  return (
    <div className="corpus-source-group">
      <span className="corpus-source-group__label">{label}</span>
      {entries.map((entry) => (
        <article className="corpus-source" key={`${label}-${entry.referenceId}`}>
          <div className="corpus-source__identity">
            <Badge tone={entry.referenceKind === 'SEGMENT' ? 'cyan' : 'violet'}>
              {entry.referenceKind}
            </Badge>
            <code>{entry.referenceId}</code>
          </div>
          {entry.sources.map((source) => (
            <div className="corpus-source__pointer" key={source.segmentId}>
              <strong>{source.documentName}</strong>
              <span>{source.locator}</span>
              <code>{source.segmentId}</code>
            </div>
          ))}
        </article>
      ))}
    </div>
  )
}

function CorpusResult({ result }: { result: LocalCorpusAIResult }) {
  return (
    <div className="corpus-result" aria-live="polite">
      <div className="corpus-result__identity">
        <Badge tone={result.executionMode === 'DETERMINISTIC' ? 'cyan' : 'violet'} dot>
          {result.executionMode === 'DETERMINISTIC' && result.provider === null
            ? 'Deterministic local analysis'
            : `${result.provider} · ${result.modelId}`}
        </Badge>
        <Badge tone={result.externalNetworkUsed ? 'amber' : 'green'}>
          {result.externalNetworkUsed ? 'External request used' : 'No external request'}
        </Badge>
        <Badge tone="amber">Draft · human review required</Badge>
        {result.fallbackReason && <Badge tone="amber">Model fallback · {result.fallbackReason}</Badge>}
      </div>

      <section className="corpus-narrative">
        <span>DRAFT SUMMARY · NOT A FACT</span>
        <h2>{result.title}</h2>
        <p>{result.draftSummary}</p>
      </section>

      {result.sections.length > 0 && (
        <section className="corpus-output-section">
          <header><h2>Organized review notes</h2><span>Labels distinguish cited notes from hypotheses</span></header>
          <div className="corpus-section-grid">
            {result.sections.map((section) => (
              <article key={section.heading}>
                <h3>{section.heading}</h3>
                {section.items.map((item) => (
                  <div className="corpus-note" key={`${item.label}-${item.text}`}>
                    <div><Badge tone={item.label === 'HYPOTHESIS' ? 'amber' : item.label === 'LIMITATION' ? 'neutral' : 'cyan'}>{item.label.replaceAll('_', ' ')}</Badge><Badge>{item.origin.replaceAll('_', ' ')}</Badge></div>
                    <p>{item.text}</p>
                    {item.evidenceRefs.length > 0 ? (
                      <CorpusSources references={item.evidenceRefs} result={result} label="Note sources" />
                    ) : (
                      <small>Uncited {item.label.toLowerCase()} · do not treat as a fact</small>
                    )}
                  </div>
                ))}
              </article>
            ))}
          </div>
        </section>
      )}

      {result.facts.length > 0 && (
        <section className="corpus-output-section">
          <header><h2>Cited facts</h2><span>Every factual statement resolves to exact file segments</span></header>
          <div className="corpus-fact-list">
            {result.facts.map((fact) => (
              <article className="corpus-fact" key={`${fact.statement}-${fact.evidenceRefs.join('-')}`}>
                <div className="corpus-fact__statement">
                  <CheckCircle2 size={16} />
                  <p>{fact.statement}</p>
                  <Badge tone={fact.confidence === 'HIGH' ? 'green' : fact.confidence === 'LOW' ? 'amber' : 'cyan'}>{fact.confidence}</Badge>
                  <Badge>{fact.origin.replaceAll('_', ' ')}</Badge>
                </div>
                <CorpusSources references={fact.evidenceRefs} result={result} label="Fact sources" />
              </article>
            ))}
          </div>
        </section>
      )}

      {result.connections.length > 0 && (
        <section className="corpus-output-section">
          <header><h2>Cross-document hypotheses</h2><span>Possible connections; never confirmed automatically</span></header>
          <div className="corpus-connection-list">
            {result.connections.map((connection) => (
              <article className="corpus-connection" key={`${connection.fromRef}-${connection.relationship}-${connection.toRef}`}>
                <div className="corpus-connection__path">
                  <code>{connection.fromRef}</code>
                  <span>{connection.relationship.replaceAll('_', ' ')}</span>
                  <code>{connection.toRef}</code>
                  <Badge tone="amber">HYPOTHESIS · {connection.confidence}</Badge>
                </div>
                <p>{connection.rationale}</p>
                <CorpusSources references={[connection.fromRef, connection.toRef]} result={result} label="Endpoint sources" />
                <CorpusSources references={connection.sharedEntityRefs} result={result} label="Shared entity sources" />
                <CorpusSources references={connection.supportingRefs} result={result} label="All supporting sources" />
                {connection.contradictionRefs.length > 0 && <CorpusSources references={connection.contradictionRefs} result={result} label="Contradicting sources" />}
                <div className="corpus-verification"><SearchCheck size={14} /><span><strong>Verify next:</strong> {connection.verificationSuggestion}</span></div>
              </article>
            ))}
          </div>
        </section>
      )}

      {result.nextSteps.length > 0 && (
        <section className="corpus-output-section">
          <header><h2>Suggested next checks</h2><span>Review-only; nothing was searched, saved, or executed</span></header>
          <div className="corpus-step-list">
            {result.nextSteps.map((step) => (
              <article className="corpus-step" key={`${step.priority}-${step.suggestion}`}>
                <Badge tone="violet">P{step.priority}</Badge>
                <div><h3>{step.suggestion}</h3><p>{step.rationale}</p><CorpusSources references={step.supportingRefs} result={result} label="Suggestion basis" /></div>
              </article>
            ))}
          </div>
        </section>
      )}

      {(result.unanswered || result.uncertainties.length > 0) && (
        <section className="corpus-output-section corpus-uncertainties">
          <header><h2>Unanswered and uncertain</h2><span>Explicit limits on the result</span></header>
          {result.unanswered && <div className="corpus-notice corpus-notice--amber"><AlertTriangle size={15} />{result.unanswered}</div>}
          {result.uncertainties.map((item) => (
            <article key={`${item.label}-${item.text}`}>
              <Badge tone={item.label === 'HYPOTHESIS' ? 'amber' : 'neutral'}>{item.label}</Badge>
              <p>{item.text}</p>
              {item.evidenceRefs.length > 0 && <CorpusSources references={item.evidenceRefs} result={result} label="Uncertainty sources" />}
            </article>
          ))}
        </section>
      )}

      <section className="corpus-output-section corpus-catalog">
        <header><h2>Exact source catalog</h2><span>{result.sourceCatalog.length} cited reference entries</span></header>
        <CorpusSources references={result.sourceCatalog.map((entry) => entry.referenceId)} result={result} label="Complete catalog" />
      </section>

      <section className="corpus-manifest">
        <dl>
          <div><dt>Corpus</dt><dd><code>{result.corpusId}</code></dd></div>
          <div><dt>Manifest SHA-256</dt><dd><code>{result.inputManifestSha256}</code></dd></div>
          <div><dt>Projection SHA-256</dt><dd><code>{result.inputSha256}</code></dd></div>
          <div><dt>Included</dt><dd>{result.includedCounts.documents} files · {result.includedCounts.segments} segments · {result.includedCounts.entities} entities</dd></div>
          <div><dt>Restricted values redacted</dt><dd>{result.restrictedValuesRedacted}</dd></div>
          <div><dt>Persistence</dt><dd>None · ephemeral result</dd></div>
        </dl>
      </section>
    </div>
  )
}

export function CorpusAIPage() {
  const native = nativeRuntimeAvailable()
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [documents, setDocuments] = useState<ReadonlyArray<LocalCorpusDocumentRequest>>([])
  const [task, setTask] = useState<LocalCorpusAITask>('SUMMARY')
  const [question, setQuestion] = useState('')
  const [semanticEnrichment, setSemanticEnrichment] = useState(true)
  const [maxSegments, setMaxSegments] = useState(200)
  const [execution, setExecution] = useState<LocalCorpusAIExecution>('DETERMINISTIC')
  const [settings, setSettings] = useState<LocalAISettings | null>(null)
  const [models, setModels] = useState<ReadonlyArray<string>>([])
  const [modelId, setModelId] = useState('')
  const [openAiModelId, setOpenAiModelId] = useState('gpt-5.6')
  const [openAiApiKey, setOpenAiApiKey] = useState('')
  const [settingsPending, setSettingsPending] = useState(native)
  const [filePending, setFilePending] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LocalCorpusAIResult | null>(null)

  useEffect(() => {
    document.title = 'Corpus AI · Codename Ariadne'
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
          const discovered = await discoverLocalAIModels({ provider: loaded.provider, endpoint: loaded.endpoint, selectedModel: loaded.selectedModel })
          if (!cancelled) {
            const ids = discovered.models.map((model) => model.modelId)
            setModels(ids)
            if (!loaded.selectedModel && ids[0]) setModelId(ids[0])
          }
        } catch {
          if (!cancelled && loaded.selectedModel) setModels([loaded.selectedModel])
        }
      })
      .catch(() => { if (!cancelled) setError('Unlock the vault to use Corpus AI.') })
      .finally(() => { if (!cancelled) setSettingsPending(false) })
    return () => { cancelled = true }
  }, [native])

  const totalBytes = useMemo(
    () => documents.reduce((sum, item) => sum + item.expectedSizeBytes, 0),
    [documents],
  )

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return
    if (documents.length + files.length > 20) {
      setError('A corpus may contain at most 20 documents.')
      return
    }
    setFilePending(true)
    setError(null)
    try {
      const prepared = await Promise.all(Array.from(files, prepareLocalCorpusDocument))
      const additions = prepared.filter((candidate) =>
        !documents.some((existing) => existing.expectedSha256 === candidate.expectedSha256 && existing.displayName === candidate.displayName),
      )
      const nextTotal = totalBytes + additions.reduce((sum, item) => sum + item.expectedSizeBytes, 0)
      if (nextTotal > 4 * 1_048_576) throw new Error('The complete corpus may not exceed 4 MiB.')
      setDocuments((current) => [...current, ...additions])
      setResult(null)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setFilePending(false)
    }
  }

  const removeDocument = (index: number) => {
    setDocuments((current) => current.filter((_, candidate) => candidate !== index))
    setResult(null)
  }

  const runAnalysis = async () => {
    if (!native || !profileId) {
      setError('Open the native app and select an active profile first.')
      return
    }
    if (documents.length === 0) {
      setError('Select at least one supported document.')
      return
    }
    if (task === 'QUESTION' && !question.trim()) {
      setError('Enter a question to answer from this corpus.')
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
      if (execution === 'LOCAL_MODEL' && activeSettings &&
          (!activeSettings.enabled || activeSettings.selectedModel !== modelId)) {
        activeSettings = await updateLocalAISettings({
          enabled: true,
          provider: activeSettings.provider,
          endpoint: activeSettings.endpoint,
          selectedModel: modelId,
          expectedRevision: activeSettings.revision,
        })
        setSettings(activeSettings)
      }
      const request: LocalCorpusAIRequest = {
        documents,
        semanticEnrichmentEnabled: semanticEnrichment,
        profileId,
        task,
        question: task === 'QUESTION' ? question.trim() : null,
        execution,
        modelId:
          execution === 'LOCAL_MODEL'
            ? modelId
            : execution === 'OPENAI_RESPONSES'
              ? openAiModelId.trim()
              : null,
        openaiApiKey:
          execution === 'OPENAI_RESPONSES' ? openAiApiKey.trim() : null,
        maxSegments,
      }
      setResult(await analyzeLocalCorpusAI(request))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      if (execution === 'OPENAI_RESPONSES') setOpenAiApiKey('')
      setPending(false)
    }
  }

  return (
    <div className="page corpus-ai-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Ephemeral multi-file reasoning"
        title="Corpus AI"
        description="Select up to 20 local text documents, then use deterministic analysis, a local model, or an explicit OpenAI Responses request. Every factual claim resolves to exact file and segment provenance."
        meta={<><Badge tone="green" dot>Local by default</Badge><Badge tone="cyan">Optional explicit OpenAI request</Badge><Badge tone="violet">Nothing persisted</Badge></>}
      />

      {!native && <div className="corpus-notice corpus-notice--amber"><AlertTriangle size={15} />Native desktop runtime required.</div>}
      {!profileId && <div className="corpus-notice corpus-notice--amber"><AlertTriangle size={15} />No active profile. Select or create one first.</div>}

      <div className="corpus-layout">
        <Panel className="corpus-files" eyebrow="1 · Local corpus" title={`${documents.length} / 20 documents`} action={<span className="mono muted">{(totalBytes / 1_048_576).toFixed(2)} / 4 MiB</span>}>
          <label className="corpus-file-picker">
            {filePending ? <LoaderCircle className="spin" size={18} /> : <Plus size={18} />}
            <span><strong>Add local documents</strong><small>TXT, Markdown, CSV, JSON, or vCard · UTF-8 · 1 MiB each</small></span>
            <input type="file" multiple accept=".txt,.md,.csv,.json,.vcf,text/plain,text/markdown,text/csv,application/json,text/vcard" disabled={filePending || documents.length >= 20} onChange={(event) => void addFiles(event.target.files)} />
          </label>
          {documents.length === 0 ? (
            <div className="corpus-files__empty"><FileStack size={23} /><span>No source documents selected. Files remain in memory only for this analysis.</span></div>
          ) : (
            <div className="corpus-file-list">
              {documents.map((item, index) => (
                <article key={`${item.displayName}-${item.expectedSha256}`}>
                  <FileText size={15} />
                  <div><strong>{item.displayName}</strong><span>{item.declaredMediaType} · {(item.expectedSizeBytes / 1024).toFixed(1)} KiB</span><code>SHA-256 {item.expectedSha256}</code></div>
                  <Button variant="ghost" size="compact" aria-label={`Remove ${item.displayName}`} onClick={() => removeDocument(index)}><Trash2 size={13} /></Button>
                </article>
              ))}
            </div>
          )}
        </Panel>

        <Panel className="corpus-controls" eyebrow="2 · Reasoning request" title="Task and execution">
          <div className="corpus-task-grid" role="radiogroup" aria-label="Corpus reasoning task">
            {TASKS.map(({ value, label, detail, icon: Icon }) => (
              <button type="button" role="radio" aria-checked={task === value} className={task === value ? 'is-active' : ''} onClick={() => { setTask(value); setResult(null) }} key={value}>
                <Icon size={15} /><span><strong>{label}</strong><small>{detail}</small></span>
              </button>
            ))}
          </div>
          {task === 'QUESTION' && <label className="field corpus-question"><span>Question grounded only in selected files</span><textarea rows={3} maxLength={2_000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What do these documents jointly show, and what remains uncertain?" /></label>}

          <div className="corpus-execution-options" role="radiogroup" aria-label="Corpus execution mode">
            <label className={execution === 'LOCAL_MODEL' ? 'is-active' : ''}><input type="radio" name="corpus-execution" checked={execution === 'LOCAL_MODEL'} onChange={() => setExecution('LOCAL_MODEL')} /><Bot size={16} /><span><strong>Selected local model</strong><small>Structured, cited inference</small></span></label>
            <label className={execution === 'DETERMINISTIC' ? 'is-active' : ''}><input type="radio" name="corpus-execution" checked={execution === 'DETERMINISTIC'} onChange={() => setExecution('DETERMINISTIC')} /><ListTree size={16} /><span><strong>Deterministic</strong><small>Extraction and grouping</small></span></label>
            <label className={execution === 'OPENAI_RESPONSES' ? 'is-active' : ''}><input type="radio" name="corpus-execution" checked={execution === 'OPENAI_RESPONSES'} onChange={() => setExecution('OPENAI_RESPONSES')} /><Cloud size={16} /><span><strong>OpenAI Responses</strong><small>Explicit external, cited request</small></span></label>
          </div>
          <label className="field"><span>Installed model</span><select value={modelId} disabled={execution !== 'LOCAL_MODEL' || settingsPending} onChange={(event) => setModelId(event.target.value)}><option value="">Select a local model</option>{models.map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
          {execution === 'OPENAI_RESPONSES' && (
            <div className="corpus-remote-fields">
              <label className="field"><span>OpenAI API model</span><input autoComplete="off" maxLength={256} onChange={(event) => setOpenAiModelId(event.target.value)} spellCheck={false} value={openAiModelId} /><small>Replace the suggested alias with any model available to your API project.</small></label>
              <label className="field"><span>OpenAI API key · used once</span><input autoComplete="off" maxLength={512} onChange={(event) => setOpenAiApiKey(event.target.value)} placeholder="sk-…" spellCheck={false} type="password" value={openAiApiKey} /><small>Held in this screen's memory, cleared after the request, and never returned or persisted.</small></label>
            </div>
          )}
          <div className="corpus-option-row">
            <label><input type="checkbox" checked={semanticEnrichment} onChange={(event) => setSemanticEnrichment(event.target.checked)} /><span><strong>Extract entity signals</strong><small>Local deterministic preprocessing</small></span></label>
            <label><span><strong>Projection limit</strong><small>Segments sent to reasoning</small></span><select value={maxSegments} onChange={(event) => setMaxSegments(Number(event.target.value))}>{[50, 100, 150, 200].map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
          </div>
          <div className="corpus-notice"><BrainCircuit size={15} />Narratives and relationship rationales are hypotheses. Only explicitly cited facts are presented as factual.</div>
          {execution === 'OPENAI_RESPONSES' && <div className="corpus-notice corpus-notice--amber"><Cloud size={15} />This action sends the selected bounded text projection to api.openai.com; source reference IDs are replaced with aliases before transmission.</div>}
          {error && <div className="corpus-notice corpus-notice--danger" role="alert"><AlertTriangle size={15} />{error}</div>}
          <Button variant="primary" disabled={pending || filePending || settingsPending || !native || !profileId || documents.length === 0} onClick={() => void runAnalysis()}>
            {pending ? <><LoaderCircle className="spin" size={15} />Analyzing corpus…</> : <><Sparkles size={15} />Run ephemeral corpus analysis</>}
          </Button>
        </Panel>
      </div>

      {result ? <CorpusResult result={result} /> : <Panel className="corpus-empty" eyebrow="3 · Result" title="No corpus analysis in this session"><FileStack size={25} /><p>Select local documents and run a bounded task. Exact document names, segment locators, hashes, model identity, fallbacks, and uncertainties will appear here.</p></Panel>}
    </div>
  )
}
