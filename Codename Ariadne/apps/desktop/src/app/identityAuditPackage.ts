/** Deterministic, inert export of one completed persistent identity audit. */
import type { AuditDetail } from '../../../../packages/contracts/src/generated/api'

export type IdentityAuditPackageFormat = 'MARKDOWN' | 'JSON'

export interface IdentityAuditPackage {
  readonly filename: string
  readonly mediaType: string
  readonly content: string
  readonly sha256: string
  readonly byteCount: number
}

const MAX_PACKAGE_BYTES = 1_000_000

function markdown(value: string): string {
  return value
    .replaceAll('\\', '\\\\')
    .replaceAll('*', '\\*')
    .replaceAll('_', '\\_')
    .replaceAll('[', '\\[')
    .replaceAll(']', '\\]')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function code(value: string): string {
  return value.replaceAll('`', 'ˋ').replaceAll('\n', ' ')
}

function display(value: string | null): string {
  return value === null ? 'None' : value.replaceAll('_', ' ').toLocaleLowerCase()
}

function isoFromMicroseconds(value: number): string {
  return new Date(Math.floor(value / 1_000)).toISOString()
}

function jsonDocument(detail: AuditDetail): object {
  return {
    format: 'ariadne-identity-audit-package-v1',
    audit: {
      auditId: detail.audit.auditId,
      name: detail.audit.name,
      state: detail.audit.state,
      stage: detail.audit.stage,
      mode: detail.audit.mode,
      stopReason: detail.audit.stopReason,
      providerIds: detail.audit.providerIds,
      progressMicros: detail.audit.progressMicros,
      taskStates: detail.audit.taskStates,
      resultCount: detail.audit.resultCount,
      leadCount: detail.audit.leadCount,
      proposalCount: detail.audit.proposalCount,
      startedAtUs: detail.audit.startedAtUs ?? null,
      finishedAtUs: detail.audit.finishedAtUs ?? null,
      generatedFromRevision: detail.audit.revision,
      generatedAtUs: detail.audit.updatedAtUs,
    },
    exactResults: detail.results.map((result) => ({
      resultId: result.resultId,
      providerId: result.providerId,
      category: result.category,
      rank: result.rank,
      url: result.url,
      title: result.title,
      snippet: result.snippet,
      observedAtUs: result.observedAtUs,
      reviewState: result.reviewState,
    })),
    leads: detail.leads,
    analysis: detail.aiAnalysis,
    proposals: detail.proposals,
    coverage: detail.tasks.map((task) => ({
      taskId: task.taskId,
      providerId: task.providerId,
      taskType: task.taskType,
      state: task.state,
      resultCount: task.resultCount,
      stopReason: task.stopReason,
      depth: task.depth,
    })),
    receipts: detail.receipts,
    truncation: {
      tasks: detail.hasMoreTasks,
      results: detail.hasMoreResults,
      leads: detail.hasMoreLeads,
      proposals: detail.hasMoreProposals,
      receipts: detail.hasMoreReceipts,
    },
  }
}

function markdownDocument(detail: AuditDetail): string {
  const lines = [
    '# Ariadne identity audit package',
    '',
    `- Audit: ${markdown(detail.audit.name)}`,
    `- Audit ID: \`${code(detail.audit.auditId)}\``,
    `- State: ${display(detail.audit.state)}`,
    `- Mode: ${display(detail.audit.mode)}`,
    `- Finished: ${isoFromMicroseconds(detail.audit.finishedAtUs ?? detail.audit.updatedAtUs)}`,
    `- Stop reason: ${display(detail.audit.stopReason)}`,
    `- Exact results: ${detail.results.length}`,
    `- Connected leads: ${detail.leads.length}`,
    `- Review proposals: ${detail.proposals.length}`,
    '',
    '## Coverage',
    '',
    ...detail.audit.taskStates.map(
      (item) => `- ${display(item.state)}: ${item.count}`,
    ),
    '',
    '## Exact sources and results',
    '',
  ]
  if (detail.results.length === 0) {
    lines.push('No exact result URL was returned.', '')
  } else {
    detail.results.forEach((result, index) => {
      lines.push(
        `### ${index + 1}. ${markdown(result.title || result.url)}`,
        '',
        `- URL: \`${code(result.url)}\``,
        `- Provider: ${markdown(result.providerId)}`,
        `- Category: ${markdown(result.category)}`,
        `- Observed: ${isoFromMicroseconds(result.observedAtUs)}`,
        `- Review state: ${display(result.reviewState)}`,
        '',
        markdown(result.snippet || 'No provider excerpt returned.'),
        '',
      )
    })
  }
  lines.push('## Connected leads', '')
  if (detail.leads.length === 0) {
    lines.push('No connected lead was retained.', '')
  } else {
    detail.leads.forEach((lead) => {
      lines.push(
        `- **${markdown(lead.leadType)} · ${markdown(lead.displayValue)}**`,
        `  - Source: ${lead.sourceUrl === null ? 'None' : `\`${code(lead.sourceUrl)}\``}`,
        `  - Provider: ${markdown(lead.providerId)}`,
        `  - Confidence: ${Math.round(lead.confidenceMicros / 10_000)}%`,
        `  - Review: ${display(lead.reviewState)} · ownership ${display(lead.ownershipState)}`,
      )
    })
    lines.push('')
  }
  lines.push('## Cited analysis', '')
  if (detail.aiAnalysis === null) {
    lines.push('No analysis was produced for this run.', '')
  } else {
    lines.push(
      `**${markdown(detail.aiAnalysis.title)}**`,
      '',
      markdown(detail.aiAnalysis.summary),
      '',
    )
    detail.aiAnalysis.insights.forEach((insight) => {
      lines.push(
        `- **${display(insight.kind)}:** ${markdown(insight.statement)}`,
        `  - Rationale: ${markdown(insight.rationale)}`,
        `  - Evidence: ${insight.evidenceRefs.map((item) => `\`${code(item)}\``).join(', ') || 'None'}`,
      )
    })
    lines.push('', '### Citation catalog', '')
    detail.aiAnalysis.citations.forEach((citation) => {
      lines.push(
        `- \`${code(citation.referenceId)}\` — ${markdown(citation.title || citation.url)} — \`${code(citation.url)}\``,
      )
    })
    if (detail.aiAnalysis.limitations.length > 0) {
      lines.push('', '### Analysis limitations', '')
      detail.aiAnalysis.limitations.forEach((item) => lines.push(`- ${markdown(item)}`))
    }
    lines.push('')
  }
  lines.push('## Human review proposals', '')
  if (detail.proposals.length === 0) {
    lines.push('No knowledge proposal was retained.', '')
  } else {
    detail.proposals.forEach((proposal) => {
      lines.push(
        `- **${display(proposal.reviewState)} · ${markdown(proposal.entityType)} · ${markdown(proposal.displayValue)}**`,
        `  - Source: \`${code(proposal.sourceUrl)}\``,
        `  - Confidence: ${Math.round(proposal.confidenceMicros / 10_000)}%`,
      )
    })
    lines.push('')
  }
  lines.push('## Coverage gaps and failures', '')
  const gaps = detail.tasks.filter(
    (task) =>
      !['SUCCEEDED_EMPTY', 'SUCCEEDED_RESULTS', 'REVIEWED', 'SAVED'].includes(task.state),
  )
  if (gaps.length === 0) {
    lines.push('No non-success task state was retained.', '')
  } else {
    gaps.forEach((task) => lines.push(
      `- ${markdown(task.providerId)} · ${display(task.state)} · ${display(task.stopReason)}`,
    ))
    lines.push('')
  }
  lines.push('## Execution receipts', '')
  if (detail.receipts.length === 0) {
    lines.push('No execution receipt was retained.', '')
  } else {
    detail.receipts.forEach((receipt) => {
      lines.push(
        `- ${markdown(receipt.toolName)} · ${display(receipt.executionState)} · ${display(receipt.resultCode)} · ${receipt.resultCount} results`,
      )
    })
    lines.push('')
  }
  lines.push(
    '## Projection completeness',
    '',
    `- Tasks truncated: ${detail.hasMoreTasks ? 'yes' : 'no'}`,
    `- Results truncated: ${detail.hasMoreResults ? 'yes' : 'no'}`,
    `- Leads truncated: ${detail.hasMoreLeads ? 'yes' : 'no'}`,
    `- Proposals truncated: ${detail.hasMoreProposals ? 'yes' : 'no'}`,
    `- Receipts truncated: ${detail.hasMoreReceipts ? 'yes' : 'no'}`,
    '',
    '---',
    '',
    'This package reports one bounded Ariadne run. Empty, blocked, failed, or unavailable checks are not proof of nonexistence. Model output remains review-only.',
    '',
  )
  return lines.join('\n')
}

async function sha256(content: Uint8Array): Promise<string> {
  const buffer = new ArrayBuffer(content.byteLength)
  new Uint8Array(buffer).set(content)
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, '0')
  ).join('')
}

export async function buildIdentityAuditPackage(
  detail: AuditDetail,
  format: IdentityAuditPackageFormat,
): Promise<IdentityAuditPackage> {
  if (!['COMPLETED', 'PARTIAL'].includes(detail.audit.state)) {
    throw new Error('Only a terminal completed or partial audit can be packaged')
  }
  const content = format === 'JSON'
    ? `${JSON.stringify(jsonDocument(detail), null, 2)}\n`
    : markdownDocument(detail)
  const bytes = new TextEncoder().encode(content)
  if (bytes.byteLength > MAX_PACKAGE_BYTES) {
    throw new Error('Identity audit package exceeds the local artifact limit')
  }
  const extension = format === 'JSON' ? 'json' : 'md'
  return {
    filename: `ariadne-audit-${detail.audit.auditId}.${extension}`,
    mediaType: format === 'JSON' ? 'application/json' : 'text/markdown',
    content,
    sha256: await sha256(bytes),
    byteCount: bytes.byteLength,
  }
}
