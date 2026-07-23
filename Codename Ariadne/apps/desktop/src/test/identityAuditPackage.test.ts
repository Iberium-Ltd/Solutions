/** Proves terminal audit exports are deterministic, cited, and state-gated. */
import { describe, expect, it } from 'vitest'
import { buildIdentityAuditPackage } from '../app/identityAuditPackage'
import { completedAuditDetail } from './identityAuditFixture'

describe('identity audit package', () => {
  it('builds deterministic cited Markdown and JSON from the terminal run', async () => {
    const markdown = await buildIdentityAuditPackage(completedAuditDetail, 'MARKDOWN')
    const markdownAgain = await buildIdentityAuditPackage(completedAuditDetail, 'MARKDOWN')
    expect(markdown).toEqual(markdownAgain)
    expect(markdown.content).toContain('## Exact sources and results')
    expect(markdown.content).toContain('https://profile.example.invalid/synthetic-result')
    expect(markdown.content).toContain('result:synthetic-1')
    expect(markdown.content).toContain('frontier exhausted')
    expect(markdown.content).toContain('## Connected leads')
    expect(markdown.content).toContain('## Execution receipts')
    expect(markdown.content).toContain('Results truncated: no')
    expect(markdown.sha256).toMatch(/^[0-9a-f]{64}$/u)
    expect(markdown.filename).toBe(`ariadne-audit-${completedAuditDetail.audit.auditId}.md`)

    const jsonArtifact = await buildIdentityAuditPackage(completedAuditDetail, 'JSON')
    const parsed = JSON.parse(jsonArtifact.content) as Record<string, unknown>
    expect(parsed.format).toBe('ariadne-identity-audit-package-v1')
    expect(parsed.leads).toHaveLength(1)
    expect(jsonArtifact.filename).toBe(
      `ariadne-audit-${completedAuditDetail.audit.auditId}.json`,
    )
  })

  it('refuses to package an audit that is still running', async () => {
    await expect(buildIdentityAuditPackage({
      ...completedAuditDetail,
      audit: { ...completedAuditDetail.audit, state: 'RUNNING', stage: 'SEARCHING' },
    }, 'MARKDOWN')).rejects.toThrow('terminal')
  })
})
