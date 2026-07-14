import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearPhase3WorkflowMemory,
  usePhase3WorkflowStore,
} from '../app/phase3WorkflowStore'

describe('Phase 3 workflow memory boundary', () => {
  beforeEach(() => {
    usePhase3WorkflowStore.getState().reset()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('keeps only opaque identifiers in ephemeral state', () => {
    const profileId = '11111111-1111-4111-8111-111111111111'
    const sourceId = '22222222-2222-4222-8222-222222222222'

    usePhase3WorkflowStore.getState().setProfileId(profileId)
    usePhase3WorkflowStore.getState().setSourceId(sourceId)

    expect(usePhase3WorkflowStore.getState()).toMatchObject({
      profileId,
      sourceId,
    })
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it('clears source navigation state when intake changes', () => {
    usePhase3WorkflowStore
      .getState()
      .setSourceId('22222222-2222-4222-8222-222222222222')

    usePhase3WorkflowStore.getState().clearSource()

    expect(usePhase3WorkflowStore.getState().sourceId).toBeNull()
  })

  it('clears the prior source capability when the active profile changes', () => {
    usePhase3WorkflowStore
      .getState()
      .setProfileId('11111111-1111-4111-8111-111111111111')
    usePhase3WorkflowStore
      .getState()
      .setSourceId('22222222-2222-4222-8222-222222222222')

    usePhase3WorkflowStore
      .getState()
      .setProfileId('33333333-3333-4333-8333-333333333333')

    expect(usePhase3WorkflowStore.getState()).toMatchObject({
      profileId: '33333333-3333-4333-8333-333333333333',
      sourceId: null,
    })
  })

  it('synchronously revokes every workflow identifier on lock', () => {
    usePhase3WorkflowStore
      .getState()
      .setProfileId('11111111-1111-4111-8111-111111111111')
    usePhase3WorkflowStore
      .getState()
      .setSourceId('22222222-2222-4222-8222-222222222222')

    clearPhase3WorkflowMemory()

    expect(usePhase3WorkflowStore.getState()).toMatchObject({
      profileId: null,
      sourceId: null,
    })
  })
})
