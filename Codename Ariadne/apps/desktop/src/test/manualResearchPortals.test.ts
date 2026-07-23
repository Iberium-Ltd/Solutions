/** Keeps manual portal URLs fixed, visible, and separate from automated evidence. */
import { describe, expect, it } from 'vitest'
import {
  isApprovedManualPortalUrl,
  manualResearchPortals,
} from '../app/manualResearchPortals'

describe('manual research portals', () => {
  it('contains unique, fixed HTTPS destinations', () => {
    expect(new Set(manualResearchPortals.map((portal) => portal.id)).size).toBe(
      manualResearchPortals.length,
    )
    expect(new Set(manualResearchPortals.map((portal) => portal.url)).size).toBe(
      manualResearchPortals.length,
    )
    for (const portal of manualResearchPortals) {
      const destination = new URL(portal.url)
      expect(destination.protocol).toBe('https:')
      expect(destination.username).toBe('')
      expect(destination.password).toBe('')
      expect(destination.hash).toBe('')
      expect(isApprovedManualPortalUrl(portal.url)).toBe(true)
    }
  })

  it('does not approve lookalike or identifier-bearing destinations', () => {
    expect(isApprovedManualPortalUrl('https://spokeo.example.invalid/')).toBe(false)
    expect(isApprovedManualPortalUrl('https://www.spokeo.com/?q=synthetic')).toBe(false)
    expect(isApprovedManualPortalUrl('http://www.spokeo.com/')).toBe(false)
  })
})
