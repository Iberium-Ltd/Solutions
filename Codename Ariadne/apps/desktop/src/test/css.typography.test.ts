/** Enforces the design-system typography floor so compact layouts remain readable. */
import { describe, it } from 'vitest'

const MINIMUM_EXPLICIT_FONT_SIZE_PX = 10
const stylesheets = import.meta.glob('../styles/*.css', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>

type TypographyViolation = {
  file: string
  line: number
  property: 'font' | 'font-size'
  value: string
  pixels: number
}

function withoutComments(source: string) {
  return source.replace(/\/\*[\s\S]*?\*\//g, (comment) =>
    comment.replace(/[^\n]/g, ' '),
  )
}

function explicitSizes(property: 'font' | 'font-size', value: string) {
  const sizePattern = /(-?(?:\d+\.?\d*|\.\d+))(px|rem|em|pt)\b/gi
  const sizes = Array.from(value.matchAll(sizePattern), (match) => {
    const numeric = Number.parseFloat(match[1])
    const unit = match[2].toLocaleLowerCase()
    const pixels = unit === 'px'
      ? numeric
      : unit === 'pt'
        ? numeric * (96 / 72)
        : numeric * 16
    return pixels
  })

  if (property === 'font') return sizes.slice(0, 1)
  if (/^\s*0(?:\s|$|!important)/i.test(value)) sizes.push(0)
  return sizes
}

describe('CSS typography floor', () => {
  it('keeps every explicit font size at or above 10px', () => {
    const violations: TypographyViolation[] = []
    const stylesheetEntries = Object.entries(stylesheets).sort(([left], [right]) =>
      left.localeCompare(right),
    )

    for (const [path, stylesheet] of stylesheetEntries) {
      const source = withoutComments(stylesheet)
      const declarationPattern =
        /(?:^|[;{])\s*(font-size|font)\s*:\s*([^;}\n]+)/gim

      for (const match of source.matchAll(declarationPattern)) {
        const property = match[1].toLocaleLowerCase() as 'font' | 'font-size'
        const value = match[2].trim()
        const declarationOffset = (match.index ?? 0) + match[0].indexOf(match[1])
        const line = source.slice(0, declarationOffset).split('\n').length

        for (const pixels of explicitSizes(property, value)) {
          if (pixels < MINIMUM_EXPLICIT_FONT_SIZE_PX) {
            violations.push({
              file: path.split('/').at(-1) ?? path,
              line,
              property,
              value,
              pixels,
            })
          }
        }
      }
    }

    if (violations.length > 0) {
      const details = violations
        .map(
          ({ file, line, property, value, pixels }) =>
            `${file}:${line} ${property}: ${value} resolves to ${pixels.toFixed(2)}px`,
        )
        .join('\n')
      throw new Error(
        `Explicit CSS typography must be at least ${MINIMUM_EXPLICIT_FONT_SIZE_PX}px.\n${details}`,
      )
    }
  })
})
