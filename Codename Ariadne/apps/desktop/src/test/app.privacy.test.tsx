/** Detects accidental personal data, unsafe telemetry claims, and remote assets in UI. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import * as syntheticFixtures from '@ariadne/synthetic-data'
import App from '../App'

function collectStrings(value: unknown, output: string[] = []): string[] {
  if (typeof value === 'string') {
    output.push(value)
  } else if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, output)
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value as Record<string, unknown>)) {
      collectStrings(item, output)
    }
  }
  return output
}

describe('synthetic fixture privacy boundary', () => {
  it('uses reserved domains for every fixture email address and URL', () => {
    const strings = collectStrings(syntheticFixtures)
    const emails = strings.flatMap(
      (value) =>
        value.match(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi) ?? [],
    )
    const urls = strings.flatMap(
      (value) => value.match(/https?:\/\/[^\s<>"']+/gi) ?? [],
    )

    expect(emails.length).toBeGreaterThan(0)
    expect(urls.length).toBeGreaterThan(0)
    for (const email of emails) {
      expect(email.toLocaleLowerCase()).toMatch(
        /@(?:[a-z0-9-]+\.)*example\.invalid$/,
      )
    }
    for (const value of urls) {
      expect(new URL(value.replace(/[),.;]+$/, '')).hostname).toMatch(
        /(?:^|\.)example\.invalid$/,
      )
    }
  })

  it('does not include exact coordinate pairs in fixture strings', () => {
    const exactCoordinatePair =
      /[-+]?\d{1,3}\.\d{4,}\s*[,°]\s*[-+]?\d{1,3}\.\d{4,}/
    for (const value of collectStrings(syntheticFixtures)) {
      expect(value).not.toMatch(exactCoordinatePair)
    }
  })

  it('keeps the synthetic boundary visible and exposes no automatic external action', async () => {
    window.history.replaceState(null, '', '/dashboard?fixture=standard')
    render(<App />)

    expect((await screen.findAllByText(/synthetic prototype/i))[0]).toBeVisible()
    expect((await screen.findAllByText(/no external requests/i))[0]).toBeVisible()

    const unsafeActions = Array.from(
      document.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'),
    ).filter((element) =>
      /\b(?:send externally|submit report|transmit now|publish publicly|file report|contact provider)\b/i.test(
        element.innerText,
      ),
    )
    expect(unsafeActions).toEqual([])
  })
})
