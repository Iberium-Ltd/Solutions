/** Read-only adapter from cited audit analysis to provisional graph elements. */
import type {
  AuditDetail,
  GraphEdge,
} from '../../../../packages/contracts/src/generated/api'

export type AnalysisGraphEdge = {
  readonly statement: string
  readonly rationale: string
  readonly citations: ReadonlyArray<{
    readonly referenceId: string
    readonly url: string
    readonly title: string
  }>
  readonly provider: string | null
  readonly modelId: string | null
  readonly createdAtUs: number
}

export type GraphViewNode = {
  readonly data: {
    readonly id: string
    readonly label: string
    readonly type: string
    readonly confidence: number
    readonly private: boolean
    readonly provisional?: boolean
  }
  readonly position: { readonly x: number; readonly y: number }
}

export type GraphViewEdge = {
  readonly data: {
    readonly id: string
    readonly source: string
    readonly target: string
    readonly label: string
    readonly confidence: number
    readonly nativeEdge?: GraphEdge
    readonly analysisEdge?: AnalysisGraphEdge
    readonly structuralEdge?: {
      readonly explanation: string
      readonly source: string
    }
  }
}

/**
 * Add an explicit profile hub so reviewed identifiers and cited audit results
 * form one navigable evidence web. These structural edges express membership
 * in the selected audit profile, never proof that two external accounts share
 * an owner.
 */
export function connectProfileGraph(
  profileId: string,
  profileLabel: string,
  nodes: ReadonlyArray<GraphViewNode>,
  edges: ReadonlyArray<GraphViewEdge>,
): AuditGraphProjection {
  const rootId = `profile-root:${profileId}`
  const root: GraphViewNode = {
    data: {
      id: rootId,
      label: profileLabel,
      type: 'person',
      confidence: 100,
      private: true,
    },
    position: { x: 480, y: 270 },
  }
  const structuralEdges = nodes.map((node, index): GraphViewEdge => ({
    data: {
      id: `profile-membership:${index}:${node.data.id}`,
      source: rootId,
      target: node.data.id,
      label: node.data.provisional ? 'Cited audit result' : 'Reviewed profile record',
      confidence: node.data.confidence,
      structuralEdge: {
        source: node.data.provisional ? 'Persisted audit analysis' : 'Reviewed local profile',
        explanation: node.data.provisional
          ? 'This result is cited by the selected audit analysis. The link records audit membership, not identity ownership.'
          : 'This reviewed entity belongs to the selected local profile. Profile membership alone is not independent proof of external account ownership.',
      },
    },
  }))
  return {
    nodes: [root, ...nodes],
    // Preserve evidence-backed and model-proposed relationships first so the
    // inspector opens on the most informative connection. Structural profile
    // membership remains available as navigation context.
    edges: [...edges, ...structuralEdges],
    truncated: false,
  }
}

export type AuditGraphProjection = {
  readonly nodes: ReadonlyArray<GraphViewNode>
  readonly edges: ReadonlyArray<GraphViewEdge>
  readonly truncated: boolean
}

const maximumAnalysisNodes = 80
const maximumAnalysisEdges = 100

function analysisConfidence(value: string | null | undefined): number {
  switch (value?.trim().toLocaleUpperCase('en-US')) {
    case 'HIGH':
    case 'VERY_HIGH':
      return 90
    case 'MEDIUM':
      return 75
    case 'LOW':
    case 'VERY_LOW':
      return 55
    default:
      return 65
  }
}

/**
 * Converts only cited CONNECTION suggestions into a provisional view. The
 * projection never writes AI output into Ariadne's reviewed identity graph.
 */
export function projectAuditConnections(
  detail: Pick<AuditDetail, 'aiAnalysis'> | null,
): AuditGraphProjection {
  const analysis = detail?.aiAnalysis
  if (
    !analysis ||
    !['SUCCEEDED', 'FALLBACK'].includes(analysis.status)
  ) {
    return { nodes: [], edges: [], truncated: false }
  }

  const citationByReference = new Map(
    analysis.citations.map((citation) => [citation.referenceId, citation]),
  )
  const nodes = new Map<string, GraphViewNode>()
  const edges: GraphViewEdge[] = []
  let truncated = false

  for (const [insightIndex, insight] of analysis.insights.entries()) {
    if (insight.kind !== 'CONNECTION') continue
    const citations = insight.evidenceRefs
      .map((referenceId) => citationByReference.get(referenceId))
      .filter((citation) => citation !== undefined)
    const firstCitation = citations[0]
    if (!firstCitation || citations.length < 2) continue

    for (const citation of citations) {
      const nodeId = `audit-result:${citation.resultId}`
      if (!nodes.has(nodeId)) {
        if (nodes.size >= maximumAnalysisNodes) {
          truncated = true
          continue
        }
        nodes.set(nodeId, {
          data: {
            id: nodeId,
            label: citation.title.trim() || citation.url,
            type: 'finding',
            confidence: analysisConfidence(insight.confidence),
            private: false,
            provisional: true,
          },
          position: { x: 0, y: 0 },
        })
      }
    }

    const sourceId = `audit-result:${firstCitation.resultId}`
    if (!nodes.has(sourceId)) continue
    for (const [targetIndex, citation] of citations.slice(1).entries()) {
      const targetId = `audit-result:${citation.resultId}`
      if (!nodes.has(targetId)) continue
      if (edges.length >= maximumAnalysisEdges) {
        truncated = true
        break
      }
      edges.push({
        data: {
          id: `audit-analysis:${analysis.analysisId}:${insightIndex}:${targetIndex}`,
          source: sourceId,
          target: targetId,
          label: 'AI suggested connection',
          confidence: analysisConfidence(insight.confidence),
          analysisEdge: {
            statement: insight.statement,
            rationale: insight.rationale,
            citations: citations.map((item) => ({
              referenceId: item.referenceId,
              url: item.url,
              title: item.title,
            })),
            provider: analysis.provider,
            modelId: analysis.modelId,
            createdAtUs: analysis.createdAtUs,
          },
        },
      })
    }
  }
  return { nodes: [...nodes.values()], edges, truncated }
}

/** Place node kinds in semantic clusters around the central profile hub. */
export function positionGraphNodes(
  nodes: ReadonlyArray<GraphViewNode>,
): ReadonlyArray<GraphViewNode> {
  const clusters: Record<string, { x: number; y: number; columns: number }> = {
    person: { x: 470, y: 255, columns: 2 },
    name: { x: 390, y: 60, columns: 3 },
    alias: { x: 390, y: 60, columns: 3 },
    username: { x: 720, y: 90, columns: 3 },
    email: { x: 100, y: 95, columns: 2 },
    phone: { x: 100, y: 360, columns: 2 },
    organisation: { x: 280, y: 460, columns: 3 },
    occupation: { x: 280, y: 460, columns: 3 },
    education: { x: 470, y: 470, columns: 3 },
    location: { x: 565, y: 455, columns: 2 },
    finding: { x: 780, y: 345, columns: 3 },
    evidence: { x: 840, y: 500, columns: 3 },
  }
  const counts = new Map<string, number>()
  return nodes.map((node) => {
    if (node.data.id.startsWith('profile-root:')) return { ...node, position: { x: 480, y: 270 } }
    const kind = node.data.type.toLocaleLowerCase('en-US')
    const cluster = clusters[kind] ?? { x: 620, y: 500, columns: 3 }
    const index = counts.get(kind) ?? 0
    counts.set(kind, index + 1)
    const column = index % cluster.columns
    const row = Math.floor(index / cluster.columns)
    return {
      ...node,
      position: {
        x: cluster.x + column * 92,
        y: cluster.y + row * 82,
      },
    }
  })
}
