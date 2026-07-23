/** Proves only allowlisted browser destinations can cross the native URL boundary. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isApprovedExternalUrl, openApprovedExternalUrl } from '../app/externalUrlBoundary'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

describe('approved external browser handoff', () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'isTauri')
    invokeMock.mockReset()
  })

  it('accepts only fixed portals, exact search URLs, and HIBP breach sources', () => {
    expect(isApprovedExternalUrl('https://www.google.com/search?q=synthetic%20alias')).toBe(true)
    expect(isApprovedExternalUrl('https://search.brave.com/search?q=synthetic&source=web')).toBe(true)
    expect(isApprovedExternalUrl('https://dehashed.com/')).toBe(true)
    expect(isApprovedExternalUrl('https://haveibeenpwned.com/api/v3/breach/SyntheticBreach')).toBe(true)
    expect(isApprovedExternalUrl('https://evil.invalid/search?q=synthetic')).toBe(false)
    expect(isApprovedExternalUrl('https://www.google.com.evil.invalid/search?q=synthetic')).toBe(false)
    expect(isApprovedExternalUrl('https://www.google.com/search?q=synthetic&redirect=evil')).toBe(false)
    expect(isApprovedExternalUrl('http://www.google.com/search?q=synthetic')).toBe(false)
  })

  it('uses the native command without letting the WebView navigate', async () => {
    Object.defineProperty(globalThis, 'isTauri', { configurable: true, value: true })
    invokeMock.mockResolvedValue(undefined)
    await openApprovedExternalUrl('https://www.bing.com/search?q=synthetic')
    expect(invokeMock).toHaveBeenCalledWith('open_external_url', {
      url: 'https://www.bing.com/search?q=synthetic',
    })
  })

  it('refuses an unapproved destination before invoking native code', async () => {
    Object.defineProperty(globalThis, 'isTauri', { configurable: true, value: true })
    await expect(openApprovedExternalUrl('https://evil.invalid/')).rejects.toThrow('External URL refused')
    expect(invokeMock).not.toHaveBeenCalled()
  })
})
