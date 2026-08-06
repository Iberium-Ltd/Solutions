/** Load the active profile and its newest persisted audit for vault-backed overview screens. */
import { useEffect, useState } from 'react'
import type { AuditDetail, PersonWorkspace } from '../../../../packages/contracts/src/generated/api'
import { getIdentityAudit, getIdentityWorkspace } from './identityDiscoveryBoundary'
import { usePhase3WorkflowStore } from './phase3WorkflowStore'

export type IdentityOverviewState =
  | { status: 'NO_PROFILE'; workspace: null; audit: null; error: null }
  | { status: 'LOADING'; workspace: null; audit: null; error: null }
  | { status: 'EMPTY'; workspace: PersonWorkspace; audit: null; error: null }
  | { status: 'READY'; workspace: PersonWorkspace; audit: AuditDetail; error: null }
  | { status: 'ERROR'; workspace: null; audit: null; error: string }

function readableError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = Reflect.get(error, 'message')
    if (typeof message === 'string' && message.trim()) return message
  }
  return 'The active audit workspace could not be loaded.'
}

export function useIdentityOverview(): IdentityOverviewState {
  const profileId = usePhase3WorkflowStore((state) => state.profileId)
  const [state, setState] = useState<IdentityOverviewState>({
    status: profileId ? 'LOADING' : 'NO_PROFILE',
    workspace: null,
    audit: null,
    error: null,
  })

  useEffect(() => {
    let active = true
    if (!profileId) {
      setState({ status: 'NO_PROFILE', workspace: null, audit: null, error: null })
      return () => { active = false }
    }

    setState({ status: 'LOADING', workspace: null, audit: null, error: null })
    void (async () => {
      try {
        const workspace = await getIdentityWorkspace({ profileId })
        const latest = [...workspace.audits].sort(
          (left, right) => right.updatedAtUs - left.updatedAtUs,
        )[0]
        if (!active) return
        if (!latest) {
          setState({ status: 'EMPTY', workspace, audit: null, error: null })
          return
        }
        const audit = await getIdentityAudit({ profileId, auditId: latest.auditId })
        if (active) setState({ status: 'READY', workspace, audit, error: null })
      } catch (error) {
        if (active) {
          setState({ status: 'ERROR', workspace: null, audit: null, error: readableError(error) })
        }
      }
    })()
    return () => { active = false }
  }, [profileId])

  return state
}
