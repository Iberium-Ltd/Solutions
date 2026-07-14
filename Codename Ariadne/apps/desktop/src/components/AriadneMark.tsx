import type { SVGProps } from 'react'

export function AriadneMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <path
        d="M5 30V15l7-7h11l8 8v14"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12 30V18l4-4h5l5 5v11"
        stroke="var(--color-review)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="5" cy="30" r="2.4" fill="var(--color-success)" />
      <circle cx="31" cy="30" r="2.4" fill="var(--color-warning)" />
      <circle cx="19" cy="30" r="3.2" fill="currentColor" />
    </svg>
  )
}

