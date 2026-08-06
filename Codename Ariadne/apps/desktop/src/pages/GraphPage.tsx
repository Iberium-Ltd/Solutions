/** Evidence-backed identity graph projection; visual edges do not create facts. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import cytoscape from 'cytoscape'
import {
  ArrowUpRight,
  ChevronRight,
  CircleHelp,
  EyeOff,
  FileCheck2,
  Focus,
  LocateFixed,
  Network,
  Search,
  SlidersHorizontal,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import {
  graphEdges,
  graphNodes,
} from '@ariadne/synthetic-data'
import type {
  AuditDetail,
  GraphSnapshot,
} from '../../../../packages/contracts/src/generated/api'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  Progress,
} from '../components/Primitives'
import { nativeRuntimeAvailable } from '../app/coreBoundary'
import {
  connectProfileGraph,
  positionGraphNodes,
  projectAuditConnections,
} from '../app/graphAuditProjection'
import type {
  GraphViewEdge,
  GraphViewNode,
} from '../app/graphAuditProjection'
import {
  getIdentityAudit,
  getIdentityWorkspace,
} from '../app/identityDiscoveryBoundary'
import { loadGraphSnapshot } from '../app/phase3Boundary'
import { usePhase3WorkflowStore } from '../app/phase3WorkflowStore'
import { Toggle } from '../components/Toggle'
import '../styles/pages-results.css'

type GraphSelection = {
  id: string
  kind: 'node' | 'edge'
}

const privateNodeTypes = new Set(['email', 'location'])

const simulatedNodes: ReadonlyArray<GraphViewNode> = graphNodes.map((node) => ({
  data: {
    ...node.data,
    private: privateNodeTypes.has(node.data.type),
  },
  position: { ...node.position },
}))

const simulatedEdges: ReadonlyArray<GraphViewEdge> = graphEdges.map((edge) => ({
  data: { ...edge.data },
}))

const edgeExplanations: Record<string, { source: string; visibility: string; explanation: string; contradiction: string }> = {
  e1: {
    source: 'Reviewed synthetic profile brief',
    visibility: 'User supplied',
    explanation: 'The reviewed profile explicitly records the synthetic handle as historically used by this identity.',
    contradiction: 'Immutable platform account ID is not available.',
  },
  e2: {
    source: 'Reviewed synthetic profile brief',
    visibility: 'Sensitive · local only',
    explanation: 'The email was explicitly confirmed during entity review and remained on device.',
    contradiction: 'No external mailbox validation was attempted.',
  },
  e3: {
    source: 'Fictional CV fragment',
    visibility: 'Public claim',
    explanation: 'A reviewed organisation reference supports the historical employment relationship.',
    contradiction: 'Independent registry confirmation is not present.',
  },
  e4: {
    source: 'Fictional profile note',
    visibility: 'Sensitive · coarse region',
    explanation: 'A historical location was approved for local correlation at coarse precision.',
    contradiction: 'Exact dates and exact coordinates are intentionally absent.',
  },
  e5: {
    source: 'Boreal Search · synthetic result',
    visibility: 'Public pseudonymous',
    explanation: 'An exact uncommon handle and aligned project reference connect the reviewed username to the legacy profile finding.',
    contradiction: 'The chronology is incomplete and no immutable account ID was observed.',
  },
  e6: {
    source: 'Local Evidence Capture',
    visibility: 'Encrypted local artifact',
    explanation: 'The captured artifact preserves the synthetic finding URL, viewport, time, and response metadata.',
    contradiction: 'Artifact integrity does not establish the truth of the source claim.',
  },
}

function words(value: string): string {
  return value
    .toLocaleLowerCase('en-US')
    .split('_')
    .map((part) => `${part.slice(0, 1).toLocaleUpperCase('en-US')}${part.slice(1)}`)
    .join(' ')
}

function observedTime(timestampUs: number): string {
  return new Date(Math.floor(timestampUs / 1_000)).toLocaleString('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'UTC',
  })
}

export function GraphPage() {
  return nativeRuntimeAvailable() ? (
    <NativeGraphPage />
  ) : (
    <GraphWorkspace
      nodes={simulatedNodes}
      edges={simulatedEdges}
      truncated={false}
      mode="SIMULATED"
    />
  )
}

function NativeGraphPage() {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [snapshot, setSnapshot] = useState<GraphSnapshot | null>(null)
  const [latestAudit, setLatestAudit] = useState<AuditDetail | null>(null)
  const [auditResolved, setAuditResolved] = useState(false)
  const [profileLabel, setProfileLabel] = useState('Selected profile')
  const [loadState, setLoadState] = useState<
    'NO_PROFILE' | 'LOADING' | 'READY' | 'ERROR'
  >(profileId === null ? 'NO_PROFILE' : 'LOADING')

  useEffect(() => {
    if (profileId === null) {
      setSnapshot(null)
      setLatestAudit(null)
      setLoadState('NO_PROFILE')
      return
    }
    let cancelled = false
    setLatestAudit(null)
    setAuditResolved(false)
    setLoadState('LOADING')
    void loadGraphSnapshot({
      profileId,
      maxNodes: 200,
      includeSensitive: true,
    })
      .then((result) => {
        if (cancelled) return
        if (result.profileId !== profileId) {
          throw new Error('Graph response scope mismatch')
        }
        setSnapshot(result)
        setLoadState('READY')
      })
      .catch(() => {
        if (cancelled) return
        setSnapshot(null)
        setLoadState('ERROR')
      })
    void (async () => {
      try {
        const workspace = await getIdentityWorkspace({ profileId })
        if (!cancelled) setProfileLabel(workspace.person.displayName)
        const audit = [...workspace.audits].sort(
          (left, right) => right.createdAtUs - left.createdAtUs,
        )[0]
        if (!audit) {
          if (!cancelled) setAuditResolved(true)
          return
        }
        const detail = await getIdentityAudit({
          profileId,
          auditId: audit.auditId,
        })
        if (!cancelled && detail.profileId === profileId) setLatestAudit(detail)
      } catch {
        // The reviewed graph remains useful when no audit analysis exists.
      } finally {
        if (!cancelled) setAuditResolved(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [profileId])

  if (
    profileId === null ||
    loadState !== 'READY' ||
    snapshot === null ||
    snapshot.profileId !== profileId ||
    !auditResolved ||
    latestAudit === null
  ) {
    const noProfile = profileId === null
    const visiblyLoading =
      !noProfile &&
      (loadState === 'LOADING' ||
        (snapshot !== null && snapshot.profileId !== profileId) ||
        !auditResolved)
    const noAudit = auditResolved && latestAudit === null && loadState === 'READY'
    return (
      <div className="page graph-page" data-testid="route-ready">
        <PageHeader
          eyebrow="Identity and provenance graph"
          title="Link Map"
          description="The native graph is scoped to the active local profile and exposes only persisted, reviewed relationships."
          meta={<Badge tone={loadState === 'ERROR' ? 'rose' : 'cyan'}>{noProfile ? 'No active profile' : visiblyLoading ? 'Loading local graph' : noAudit ? 'No audit yet' : 'Graph unavailable'}</Badge>}
        />
        <Panel className="empty-state panel--raised">
          <Network size={26} />
          <h2>{noProfile ? 'Start with local intake' : visiblyLoading ? 'Loading the encrypted graph…' : noAudit ? 'Run an audit to build the evidence web' : 'The graph could not be loaded'}</h2>
          <p>{noProfile ? 'Create or resume a profile through Intake, review its entities, then return here.' : noAudit ? 'No placeholder graph is shown. The first audit will connect reviewed profile records, cited results, and model-assisted hypotheses.' : loadState === 'ERROR' ? 'Confirm the vault is unlocked, then retry by reopening this screen.' : 'Reading profile-scoped nodes, edges, and provenance.'}</p>
          {noProfile ? <Link className="button button--primary" to="/audits/new">Open Intake</Link> : null}
        </Panel>
      </div>
    )
  }

  const reviewedNodes: ReadonlyArray<GraphViewNode> = snapshot.nodes.map((node) => ({
      data: {
        id: node.nodeId,
        label: node.displayLabel,
        type: node.nodeType.toLocaleLowerCase('en-US'),
        confidence: 100,
        private: node.sensitivity !== 'PUBLIC',
      },
      position: { x: 0, y: 0 },
    }))
  const reviewedEdges: ReadonlyArray<GraphViewEdge> = snapshot.edges.map((edge) => ({
    data: {
      id: edge.edgeId,
      source: edge.fromNodeId,
      target: edge.toNodeId,
      label: words(edge.edgeType),
      confidence: Math.round(edge.confidenceMicros / 10_000),
      nativeEdge: edge,
    },
  }))
  const analysisProjection = projectAuditConnections(latestAudit)
  const connected = connectProfileGraph(profileId, profileLabel, [
    ...reviewedNodes,
    ...analysisProjection.nodes,
  ], [
    ...reviewedEdges,
    ...analysisProjection.edges,
  ])
  const nodes = positionGraphNodes(connected.nodes)
  const edges = connected.edges

  return (
    <GraphWorkspace
      nodes={nodes}
      edges={edges}
      truncated={snapshot.truncated || analysisProjection.truncated}
      mode="NATIVE"
    />
  )
}

function GraphWorkspace({
  nodes,
  edges,
  truncated,
  mode,
}: {
  readonly nodes: ReadonlyArray<GraphViewNode>
  readonly edges: ReadonlyArray<GraphViewEdge>
  readonly truncated: boolean
  readonly mode: 'NATIVE' | 'SIMULATED'
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const coreRef = useRef<cytoscape.Core | null>(null)
  const [selection, setSelection] = useState<GraphSelection>({ id: '', kind: 'node' })
  const [hidePrivate, setHidePrivate] = useState(false)
  const [nodeType, setNodeType] = useState('all')
  const [minimumConfidence, setMinimumConfidence] = useState(70)
  const [query, setQuery] = useState('')
  const [layoutReady, setLayoutReady] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return

    const computed = getComputedStyle(containerRef.current)
    const color = (token: string, fallback: string) =>
      computed.getPropertyValue(token).trim() || fallback

    const elements: cytoscape.ElementDefinition[] = [
      ...nodes.map((node) => ({
        data: { ...node.data },
        position: { ...node.position },
      })),
      ...edges.map((edge) => ({ data: { ...edge.data } })),
    ]

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: 'preset', fit: true, padding: 42 },
      minZoom: 0.55,
      maxZoom: 2.2,
      boxSelectionEnabled: false,
      autoungrabify: false,
      style: [
        {
          selector: 'node',
          style: {
            width: 58,
            height: 58,
            label: 'data(label)',
            'font-family': color('--font-interface', 'sans-serif'),
            'font-size': 11,
            'font-weight': 600,
            color: color('--color-text-secondary', '#c7d1de'),
            'text-valign': 'bottom',
            'text-margin-y': 10,
            'text-background-color': color('--graphite-900', '#0f141d'),
            'text-background-opacity': 0.9,
            'text-background-padding': '4px',
            'background-color': color('--graphite-750', '#202b3a'),
            'border-color': color('--metal-650', '#2b3849'),
            'border-width': 2,
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'node[type = "person"]',
          style: {
            shape: 'ellipse',
            width: 68,
            height: 68,
            'background-color': color('--signal-violet', '#b99cff'),
            'background-opacity': 0.28,
            'border-color': color('--signal-violet', '#b99cff'),
          },
        },
        {
          selector: 'node[type = "username"]',
          style: {
            shape: 'round-rectangle',
            'background-color': color('--signal-cyan', '#58dff5'),
            'background-opacity': 0.18,
            'border-color': color('--signal-cyan', '#58dff5'),
          },
        },
        {
          selector: 'node[type = "email"]',
          style: {
            shape: 'diamond',
            'background-color': color('--signal-blue', '#8ab4ff'),
            'background-opacity': 0.14,
            'border-color': color('--signal-blue', '#8ab4ff'),
            'border-width': 4,
          },
        },
        {
          selector: 'node[type = "organisation"]',
          style: {
            shape: 'rectangle',
            'background-color': color('--signal-green', '#70e5a2'),
            'background-opacity': 0.13,
            'border-color': color('--signal-green', '#70e5a2'),
          },
        },
        {
          selector: 'node[type = "location"]',
          style: {
            shape: 'hexagon',
            'background-color': color('--signal-amber', '#f4b860'),
            'background-opacity': 0.14,
            'border-color': color('--signal-amber', '#f4b860'),
            'border-width': 4,
          },
        },
        {
          selector: 'node[type = "finding"]',
          style: {
            shape: 'round-rectangle',
            width: 72,
            'background-color': color('--signal-rose', '#ff7b8d'),
            'background-opacity': 0.14,
            'border-color': color('--signal-rose', '#ff7b8d'),
          },
        },
        {
          selector: 'node[provisional]',
          style: {
            'border-style': 'dashed',
          },
        },
        {
          selector: 'node[type = "evidence"]',
          style: {
            shape: 'barrel',
            'background-color': color('--signal-green', '#70e5a2'),
            'background-opacity': 0.13,
            'border-color': color('--signal-green', '#70e5a2'),
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1.4,
            'line-color': color('--metal-650', '#2b3849'),
            'target-arrow-color': color('--metal-650', '#2b3849'),
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.7,
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-family': color('--font-data', 'monospace'),
            'font-size': 10,
            color: color('--color-text-muted', '#94a3b6'),
            'text-background-color': color('--graphite-900', '#0f141d'),
            'text-background-opacity': 0.9,
            'text-background-padding': '2px',
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'edge[analysisEdge]',
          style: {
            'line-style': 'dashed',
            'line-color': color('--signal-violet', '#b99cff'),
            'target-arrow-color': color('--signal-violet', '#b99cff'),
          },
        },
        {
          selector: 'edge[structuralEdge]',
          style: {
            'line-style': 'dotted',
            'line-color': color('--signal-cyan', '#58dff5'),
            'target-arrow-color': color('--signal-cyan', '#58dff5'),
            opacity: 0.58,
          },
        },
        {
          selector: ':selected',
          style: {
            'border-width': 3,
            'border-color': color('--signal-cyan-soft', '#a2f1fc'),
            'line-color': color('--signal-cyan', '#58dff5'),
            'target-arrow-color': color('--signal-cyan', '#58dff5'),
            'underlay-color': color('--signal-cyan', '#58dff5'),
            'underlay-opacity': 0.12,
            'underlay-padding': 7,
            'z-index': 10,
          },
        },
      ],
    })

    coreRef.current = cy
    const initialId = edges[0]?.data.id ?? nodes[0]?.data.id
    if (initialId !== undefined) {
      const initial = cy.getElementById(initialId)
      initial.select()
      setSelection({
        id: initialId,
        kind: edges.length > 0 ? 'edge' : 'node',
      })
    }

    const handleSelect: cytoscape.EventHandler = (event) => {
      const target = event.target
      if (target === cy) return
      setSelection({
        id: target.id(),
        kind: target.isNode() ? 'node' : 'edge',
      })
    }
    cy.on('select', 'node, edge', handleSelect)
    cy.ready(() => {
      cy.fit(undefined, 42)
      setLayoutReady(true)
      if (containerRef.current) containerRef.current.dataset.layoutSettled = 'true'
      document.documentElement.dataset.graphLayout = 'settled'
    })

    return () => {
      delete document.documentElement.dataset.graphLayout
      coreRef.current = null
      cy.destroy()
    }
  }, [edges, nodes])

  useEffect(() => {
    const cy = coreRef.current
    if (!cy) return
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const type = String(node.data('type'))
        const confidence = Number(node.data('confidence'))
        const visible =
          (!hidePrivate || node.data('private') !== true) &&
          (nodeType === 'all' || type === nodeType) &&
          confidence >= minimumConfidence
        node.style('display', visible ? 'element' : 'none')
      })
    })
  }, [hidePrivate, minimumConfidence, nodeType, layoutReady, nodes])

  const visibleNodes = useMemo(
    () => nodes.filter((node) => {
      const visibleByPrivacy = !hidePrivate || !node.data.private
      const visibleByType = nodeType === 'all' || node.data.type === nodeType
      return visibleByPrivacy && visibleByType && node.data.confidence >= minimumConfidence
    }),
    [hidePrivate, minimumConfidence, nodeType, nodes],
  )

  const selectedEdge = selection.kind === 'edge'
    ? edges.find((edge) => edge.data.id === selection.id)
    : undefined
  const selectedNode = selection.kind === 'node'
    ? nodes.find((node) => node.data.id === selection.id)
    : undefined

  const nodeLabel = (id: string) =>
    nodes.find((node) => node.data.id === id)?.data.label ?? id
  const selectedNativeEdge = selectedEdge?.data.nativeEdge
  const selectedAnalysisEdge = selectedEdge?.data.analysisEdge
  const selectedStructuralEdge = selectedEdge?.data.structuralEdge
  const selectedEvidence = selectedNativeEdge?.evidence[0]
  const simulatedExplanation = selectedEdge
    ? edgeExplanations[selectedEdge.data.id]
    : undefined
  const hiddenPrivateCount = nodes.filter((node) => node.data.private).length
  const selectedExplanation =
    selectedNativeEdge?.explanation ??
    selectedAnalysisEdge?.rationale ??
    selectedStructuralEdge?.explanation ??
    simulatedExplanation?.explanation ??
    'No explanation is available.'
  const selectedSource = selectedEvidence
    ? `Source ${selectedEvidence.sourceId} · segment ${selectedEvidence.segmentOrdinal + 1}`
    : selectedAnalysisEdge
      ? `${selectedAnalysisEdge.citations.length} exact cited result URLs`
      : selectedStructuralEdge
        ? selectedStructuralEdge.source
        : simulatedExplanation?.source ?? 'Local source unavailable'
  const selectedVisibility = selectedEvidence
    ? words(selectedEvidence.visibility)
    : selectedAnalysisEdge
      ? 'Public sources · local proposal'
      : selectedStructuralEdge
        ? 'Local profile structure'
        : simulatedExplanation?.visibility ?? 'Unknown'
  const selectedObserved = selectedEvidence
    ? observedTime(selectedEvidence.observedAtUs)
    : selectedAnalysisEdge
      ? observedTime(selectedAnalysisEdge.createdAtUs)
      : selectedStructuralEdge
        ? 'Current persisted profile'
        : '11 Jul 2026 · 14:36 UTC'
  const selectedOrigin = selectedEvidence
    ? words(selectedEvidence.originType)
    : selectedAnalysisEdge
      ? `Local AI · ${selectedAnalysisEdge.provider ?? 'provider unavailable'} · ${selectedAnalysisEdge.modelId ?? 'model unavailable'}`
      : selectedStructuralEdge
        ? 'Deterministic profile projection'
        : 'Automated · human review pending'
  const selectedContradiction = selectedNativeEdge
    ? selectedNativeEdge.contradictionCount > 0
      ? `${selectedNativeEdge.contradictionCount} contradictory observation${selectedNativeEdge.contradictionCount === 1 ? '' : 's'} recorded. Inspect the evidence samples before relying on this relationship.`
      : 'No contradictory observation is currently recorded; absence of contradiction is not independent confirmation.'
    : selectedAnalysisEdge
      ? `Provisional AI proposal: ${selectedAnalysisEdge.statement} Human review is required before treating this as a verified relationship.`
      : selectedStructuralEdge
        ? 'This structural link does not prove ownership or identity equivalence. Open a semantic relationship or cited result for stronger evidence.'
        : simulatedExplanation?.contradiction ??
          'No contradiction note is available.'

  const focusElement = (id: string, kind: GraphSelection['kind']) => {
    const cy = coreRef.current
    if (!cy) return
    const element = cy.getElementById(id)
    if (element.empty()) return
    cy.elements().unselect()
    element.select()
    cy.center(element)
    setSelection({ id, kind })
  }

  const focusSearch = () => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return
    const match = nodes.find((node) =>
      node.data.label.toLocaleLowerCase().includes(normalized),
    )
    if (match) focusElement(match.data.id, 'node')
  }

  return (
    <div
      className="page graph-page"
      data-testid="route-ready"
      data-layout-ready={layoutReady ? 'true' : 'false'}
    >
      <PageHeader
        eyebrow="Identity and provenance graph"
        title="Link Map"
        description="Explore reviewed entities, findings, and evidence. Every visible connection carries provenance, confidence, and an explanation."
        meta={
          <>
            <Badge tone="green" dot>{mode === 'NATIVE' ? 'Native encrypted graph' : 'Deterministic local layout'}</Badge>
            <Badge tone="cyan">{nodes.length} nodes · {edges.length} edges</Badge>
            {truncated ? <Badge tone="amber">Bounded view · more available</Badge> : null}
            {hidePrivate && hiddenPrivateCount > 0 ? <Badge tone="amber"><EyeOff size={11} /> {hiddenPrivateCount} private nodes hidden</Badge> : null}
          </>
        }
        actions={
          <>
            <Link className="button button--secondary" to="/findings">Review findings</Link>
            <Button variant="secondary"><FileCheck2 size={14} /> Evidence index</Button>
          </>
        }
      />

      <Panel className="graph-workspace panel--raised">
        <div className="graph-toolbar">
          <form
            className="graph-search"
            onSubmit={(event) => { event.preventDefault(); focusSearch() }}
          >
            <Search size={14} />
            <label className="sr-only" htmlFor="graph-search">Search graph</label>
            <input
              id="graph-search"
              type="search"
              placeholder="Search and focus a node"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button variant="ghost" size="compact" type="submit"><LocateFixed size={12} /> Focus</Button>
          </form>
          <label className="graph-toolbar__filter">
            <SlidersHorizontal size={13} />
            <span>Node type</span>
            <select value={nodeType} onChange={(event) => setNodeType(event.target.value)}>
              <option value="all">All types</option>
              <option value="person">People</option>
              <option value="username">Usernames</option>
              <option value="finding">Findings</option>
              <option value="evidence">Evidence</option>
            </select>
          </label>
          <label className="graph-confidence">
            <span>Confidence ≥ <strong className="mono">{minimumConfidence}%</strong></span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={minimumConfidence}
              onChange={(event) => setMinimumConfidence(Number(event.target.value))}
            />
          </label>
          <Toggle
            className="graph-private-toggle"
            checked={hidePrivate}
            onCheckedChange={setHidePrivate}
            label="Hide private nodes"
          />
        </div>

        <div className="graph-layout">
          <section className="graph-canvas-wrap" aria-label="Interactive graph canvas">
            <div className="graph-canvas__grid" aria-hidden="true" />
            <div
              ref={containerRef}
              className="graph-canvas"
              role="img"
              aria-label={`Identity graph showing ${visibleNodes.length} visible nodes and provenance connections. Use the accessible graph index for keyboard selection.`}
            />
            <div className="graph-canvas__tools" aria-label="Graph view controls">
              <button type="button" onClick={() => coreRef.current?.zoom(coreRef.current.zoom() * 1.15)} aria-label="Zoom in"><ZoomIn size={15} /></button>
              <button type="button" onClick={() => coreRef.current?.zoom(coreRef.current.zoom() / 1.15)} aria-label="Zoom out"><ZoomOut size={15} /></button>
              <button type="button" onClick={() => coreRef.current?.fit(undefined, 42)} aria-label="Fit graph"><Focus size={15} /></button>
            </div>
            <div className="graph-legend" aria-label="Graph legend">
              <span><i className="is-identity" /> Identity</span>
              <span><i className="is-finding" /> Finding</span>
              <span><i className="is-evidence" /> Evidence</span>
              <span><i className="is-private" /> Private boundary</span>
            </div>
            <div className="graph-canvas__status mono">
              <Network size={12} /> preset:v1 · {visibleNodes.length}/{nodes.length} nodes visible
            </div>
          </section>

          <aside className="graph-inspector" aria-label="Selected graph item">
            {selectedEdge ? (
              <>
                <div className="graph-inspector__header">
                  <span className="eyebrow">Selected relationship</span>
                  <Badge tone="cyan">{selectedEdge.data.label}</Badge>
                  <h2>{nodeLabel(selectedEdge.data.source)} <ChevronRight size={14} /> {nodeLabel(selectedEdge.data.target)}</h2>
                  <p>{selectedStructuralEdge ? 'Profile structure · not an ownership claim' : 'Directional, evidence-backed relationship'}</p>
                </div>
                <div className="graph-inspector__confidence">
                  <div><span>Confidence</span><strong>{selectedEdge.data.confidence}%</strong></div>
                  <Progress value={selectedEdge.data.confidence} label={`${selectedEdge.data.confidence} percent confidence`} />
                </div>
                <section className="why-connected">
                  <h3><CircleHelp size={14} /> Why is this connected?</h3>
                  <p>{selectedExplanation}</p>
                  <dl>
                    <div><dt>Source</dt><dd>{selectedSource}</dd></div>
                    <div><dt>Visibility</dt><dd>{selectedVisibility}</dd></div>
                    <div><dt>Observed</dt><dd className="mono">{selectedObserved}</dd></div>
                    <div><dt>Origin</dt><dd>{selectedOrigin}</dd></div>
                  </dl>
                </section>
                <div className="graph-contradiction">
                  <strong>Contradiction / gap</strong>
                  <span>{selectedContradiction}</span>
                </div>
                <div className="graph-evidence-link">
                  <span className="status-icon status-icon--green"><FileCheck2 size={14} /></span>
                  <div><strong>{selectedNativeEdge ? `${selectedNativeEdge.supportCount} supporting · ${selectedNativeEdge.contradictionCount} contradicting` : selectedAnalysisEdge ? `${selectedAnalysisEdge.citations.length} cited public results` : selectedStructuralEdge ? 'Profile membership only' : 'Evidence 04'}</strong><small>{selectedNativeEdge ? `${selectedNativeEdge.evidence.length} bounded source sample${selectedNativeEdge.evidence.length === 1 ? '' : 's'}${selectedNativeEdge.evidenceTruncated ? ' · more available' : ''}` : selectedAnalysisEdge ? 'Provisional connection · human review required' : selectedStructuralEdge ? 'Select semantic edges for exact evidence' : 'Encrypted artifact · hash verified'}</small></div>
                  {mode === 'SIMULATED' ? <Link to="/findings/finding_syn_profile" aria-label="Open evidence for selected relationship"><ArrowUpRight size={14} /></Link> : null}
                </div>
                {selectedNativeEdge && selectedNativeEdge.evidence.length > 0 ? (
                  <details className="graph-index">
                    <summary>Exact source references <span className="mono">{selectedNativeEdge.evidence.length}</span></summary>
                    <div className="graph-index__content graph-source-index">
                      <ul>
                        {selectedNativeEdge.evidence.map((evidence) => (
                          <li key={`${evidence.sourceId}:${evidence.segmentOrdinal}:${evidence.originType}`}>
                            <span className="mono wrap-anywhere">{evidence.sourceId}</span>
                            <small>
                              Segment {evidence.segmentOrdinal + 1}
                              {evidence.sourceSpanStart === null ? '' : ` · span ${evidence.sourceSpanStart}–${evidence.sourceSpanEnd}`}
                              {' · '}{words(evidence.disposition)} · {Math.round(evidence.confidenceMicros / 10_000)}% · {words(evidence.originType)} · {words(evidence.visibility)}
                            </small>
                            <small>{observedTime(evidence.observedAtUs)} UTC · {evidence.explanation}</small>
                          </li>
                        ))}
                      </ul>
                      {selectedNativeEdge.evidenceTruncated ? <p>More source references exist outside this bounded graph response.</p> : null}
                    </div>
                  </details>
                ) : null}
                {selectedAnalysisEdge ? (
                  <details className="graph-index" open>
                    <summary>Exact cited result URLs <span className="mono">{selectedAnalysisEdge.citations.length}</span></summary>
                    <div className="graph-index__content graph-source-index">
                      <ul>
                        {selectedAnalysisEdge.citations.map((citation) => (
                          <li key={citation.referenceId}>
                            <span>{citation.title}</span>
                            <small className="mono wrap-anywhere">{citation.url}</small>
                            <small>Analysis reference {citation.referenceId}</small>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </details>
                ) : null}
              </>
            ) : selectedNode ? (
              <>
                <div className="graph-inspector__header">
                  <span className="eyebrow">Selected node</span>
                  <Badge tone="violet">{selectedNode.data.type}</Badge>
                  <h2>{selectedNode.data.label}</h2>
                  <p>{selectedNode.data.id.startsWith('profile-root:') ? 'Central hub for this selected audit profile' : selectedNode.data.provisional ? 'Provisional cited audit result · human review required' : mode === 'NATIVE' ? 'Reviewed local graph entity' : 'Reviewed synthetic graph entity'}</p>
                </div>
                <div className="graph-inspector__confidence">
                  <div><span>Entity confidence</span><strong>{selectedNode.data.confidence}%</strong></div>
                  <Progress value={selectedNode.data.confidence} />
                </div>
                <div className="graph-node-summary">
                  <span>Connections</span>
                  <strong>{edges.filter((edge) => edge.data.source === selectedNode.data.id || edge.data.target === selectedNode.data.id).length}</strong>
                  <p>Select a relationship on the canvas or in the accessible index to inspect its explanation and evidence.</p>
                </div>
              </>
            ) : null}

            <details className="graph-index">
              <summary>Accessible graph index <span className="mono">{visibleNodes.length} nodes</span></summary>
              <div className="graph-index__content">
                <h3>Visible nodes</h3>
                {visibleNodes.map((node) => (
                  <button
                    type="button"
                    key={node.data.id}
                    onClick={() => focusElement(node.data.id, 'node')}
                    aria-pressed={selection.id === node.data.id}
                  >
                    <span>{node.data.label}</span>
                    <small>{node.data.type} · {node.data.confidence}%</small>
                  </button>
                ))}
                <h3>Relationships</h3>
                {edges.map((edge) => (
                  <button
                    type="button"
                    key={edge.data.id}
                    onClick={() => focusElement(edge.data.id, 'edge')}
                    aria-pressed={selection.id === edge.data.id}
                  >
                    <span>{edge.data.label}</span>
                    <small>{nodeLabel(edge.data.source)} → {nodeLabel(edge.data.target)}</small>
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
