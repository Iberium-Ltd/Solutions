/**
 * Draws compact trend context without a charting dependency. Callers provide
 * bounded points, while this component remains presentation-only.
 */
import clsx from 'clsx'

export function Sparkline({
  values,
  className,
  label = 'Synthetic trend',
}: {
  values: readonly number[]
  className?: string
  label?: string
}) {
  const width = 220
  const height = 62
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(1, max - min)
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(1, values.length - 1)) * width
      const y = height - 6 - ((value - min) / spread) * (height - 14)
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg
      className={clsx('sparkline', className)}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--color-accent)" stopOpacity=".28" />
          <stop offset="1" stopColor="var(--color-accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d={`M 0 ${height - 1} L ${points} L ${width} ${height - 1} Z`}
        fill="url(#spark-fill)"
      />
      <polyline
        points={points}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
