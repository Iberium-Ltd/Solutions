/** Installs shared DOM assertions and cleanup required by every renderer test. */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

class MockResizeObserver implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class MockIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = '0px'
  readonly scrollMargin = '0px'
  readonly thresholds = [0]

  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  value: MockResizeObserver,
})
Object.defineProperty(globalThis, 'IntersectionObserver', {
  configurable: true,
  value: MockIntersectionObserver,
})
Object.defineProperty(window, 'matchMedia', {
  configurable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => true,
  }),
})
Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: {
    readText: vi.fn(async () => ''),
    writeText: vi.fn(async () => undefined),
  },
})

HTMLElement.prototype.scrollIntoView = vi.fn()
Element.prototype.scrollTo = vi.fn()
Element.prototype.hasPointerCapture = vi.fn(() => false)
Element.prototype.setPointerCapture = vi.fn()
Element.prototype.releasePointerCapture = vi.fn()

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '', '/')
  document.title = 'Codename Ariadne · Synthetic prototype'
  delete document.documentElement.dataset.captureReady
  delete document.documentElement.dataset.graphLayout
  delete document.documentElement.dataset.motion
  delete document.documentElement.dataset.displayPreset
  delete document.documentElement.dataset.fontScale
  document.documentElement.style.removeProperty('--font-scale')
})
