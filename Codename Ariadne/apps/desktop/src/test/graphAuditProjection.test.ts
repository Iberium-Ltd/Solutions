/** Verifies AI suggestions stay provisional and retain exact synthetic citations. */
import { describe, expect, it } from 'vitest'
import type { AuditDetail } from '../../../../packages/contracts/src/generated/api'
import { projectAuditConnections } from '../app/graphAuditProjection'

describe('audit connection graph projection', () => {
  it('projects only cited CONNECTION insights without promoting them', () => {
    const detail = {
      aiAnalysis: {
        analysisId: 'analysis-synthetic',
        status: 'SUCCEEDED',
        resultCode: 'OK',
        provider: 'OLLAMA',
        modelId: 'synthetic-local-model',
        engineVersion: '1',
        title: 'Synthetic cited analysis',
        summary: 'Synthetic summary.',
        insights: [
          {
            kind: 'CONNECTION',
            statement: 'Two synthetic pages may describe the same project.',
            rationale: 'Both cited results use the same fictional handle.',
            confidence: 'MEDIUM',
            evidenceRefs: ['R1', 'R2'],
          },
          {
            kind: 'FACT',
            statement: 'A fact is not a graph edge.',
            rationale: 'It has only one citation.',
            confidence: 'HIGH',
            evidenceRefs: ['R1'],
          },
        ],
        citations: [
          {
            referenceId: 'R1',
            resultId: 'result-synthetic-one',
            url: 'https://example.invalid/one',
            title: 'Synthetic result one',
          },
          {
            referenceId: 'R2',
            resultId: 'result-synthetic-two',
            url: 'https://example.invalid/two',
            title: 'Synthetic result two',
          },
        ],
        limitations: [],
        createdAtUs: 1_750_000_000_000_000,
      },
    } satisfies Pick<AuditDetail, 'aiAnalysis'>

    const projection = projectAuditConnections(detail)

    expect(projection.nodes).toHaveLength(2)
    expect(projection.nodes.every((node) => node.data.provisional)).toBe(true)
    expect(projection.edges).toHaveLength(1)
    expect(projection.edges[0]?.data).toMatchObject({
      label: 'AI suggested connection',
      confidence: 75,
      analysisEdge: {
        provider: 'OLLAMA',
        modelId: 'synthetic-local-model',
      },
    })
    expect(projection.edges[0]?.data.analysisEdge?.citations.map(
      (citation) => citation.url,
    )).toEqual([
      'https://example.invalid/one',
      'https://example.invalid/two',
    ])
  })

  it('rejects uncited, failed, and single-source suggestions', () => {
    expect(projectAuditConnections(null)).toEqual({
      nodes: [], edges: [], truncated: false,
    })
    expect(projectAuditConnections({
      aiAnalysis: {
        analysisId: 'analysis-empty',
        status: 'SUCCEEDED',
        resultCode: 'OK',
        provider: null,
        modelId: null,
        engineVersion: null,
        title: 'No connection',
        summary: '',
        insights: [{
          kind: 'CONNECTION',
          statement: 'Unsupported.',
          rationale: 'Only one source.',
          evidenceRefs: ['R1'],
        }],
        citations: [{
          referenceId: 'R1',
          resultId: 'one',
          url: 'https://example.invalid/one',
          title: 'One',
        }],
        limitations: [],
        createdAtUs: 1,
      },
    })).toEqual({ nodes: [], edges: [], truncated: false })
  })

  it('keeps cited deterministic fallback connections visible for review', () => {
    const projection = projectAuditConnections({
      aiAnalysis: {
        analysisId: 'analysis-fallback',
        status: 'FALLBACK',
        resultCode: 'LOCAL_AI_UNAVAILABLE',
        provider: null,
        modelId: null,
        engineVersion: 'deterministic-v1',
        title: 'Bounded fallback',
        summary: 'Cited local fallback.',
        insights: [{
          kind: 'CONNECTION',
          statement: 'Two synthetic results share a reviewed clue.',
          rationale: 'The deterministic fallback retained both exact URLs.',
          confidence: 'LOW',
          evidenceRefs: ['R1', 'R2'],
        }],
        citations: [
          { referenceId: 'R1', resultId: 'one', url: 'https://example.invalid/one', title: 'One' },
          { referenceId: 'R2', resultId: 'two', url: 'https://example.invalid/two', title: 'Two' },
        ],
        limitations: ['Local model unavailable.'],
        createdAtUs: 2,
      },
    })

    expect(projection.edges).toHaveLength(1)
    expect(projection.edges[0]?.data.confidence).toBe(55)
  })
})
