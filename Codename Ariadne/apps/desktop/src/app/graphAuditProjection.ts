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

/** Positions reviewed and provisional nodes together in one deterministic ring. */
export function positionGraphNodes(
  nodes: ReadonlyArray<GraphViewNode>,
): ReadonlyArray<GraphViewNode> {
  const nodeCount = nodes.length
  return nodes.map((node, index) => {
    const angle = nodeCount === 0 ? 0 : (Math.PI * 2 * index) / nodeCount
    const radiusX = nodeCount < 4 ? 190 : 300
    const radiusY = nodeCount < 4 ? 130 : 210
    return {
      ...node,
      position: {
        x: 480 + Math.cos(angle) * radiusX,
        y: 270 + Math.sin(angle) * radiusY,
      },
    }
  })
}
