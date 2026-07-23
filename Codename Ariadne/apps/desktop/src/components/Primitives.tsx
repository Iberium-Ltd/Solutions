/**
 * Supplies consistent presentation primitives shared by route components.
 *
 * These components intentionally hold no business authority; they centralize
 * layout, semantics, focus behavior, and visual status vocabulary.
 */
import clsx from 'clsx'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { ArrowUpRight, ShieldCheck } from 'lucide-react'
import { syntheticNotice } from '@ariadne/synthetic-data'

export type Tone =
  | 'neutral'
  | 'cyan'
  | 'violet'
  | 'green'
  | 'amber'
  | 'rose'
  | 'blue'

export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className,
}: {
  children: ReactNode
  tone?: Tone
  dot?: boolean
  className?: string
}) {
  return (
    <span className={clsx('badge', `badge--${tone}`, className)}>
      {dot && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  )
}

export function Button({
  children,
  variant = 'secondary',
  size = 'default',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'default' | 'compact'
}) {
  return (
    <button
      type="button"
      className={clsx(
        'button',
        `button--${variant}`,
        size === 'compact' && 'button--compact',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

export function Panel({
  children,
  className,
  title,
  eyebrow,
  action,
  as: Element = 'section',
  ...props
}: HTMLAttributes<HTMLElement> & {
  title?: ReactNode
  eyebrow?: ReactNode
  action?: ReactNode
  as?: 'section' | 'article' | 'div'
}) {
  return (
    <Element className={clsx('panel', className)} {...props}>
      {(title || eyebrow || action) && (
        <header className="panel__header">
          <div className="panel__heading">
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            {title && <h2 className="panel__title">{title}</h2>}
          </div>
          {action && <div className="panel__action">{action}</div>}
        </header>
      )}
      {children}
    </Element>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  meta,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
  meta?: ReactNode
}) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        <span className="eyebrow">{eyebrow}</span>
        <h1 id="page-title" tabIndex={-1}>
          {title}
        </h1>
        <p>{description}</p>
        {meta && <div className="page-header__meta">{meta}</div>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  )
}

export function Metric({
  label,
  value,
  detail,
  tone = 'cyan',
  children,
}: {
  label: string
  value: string
  detail: string
  tone?: Tone
  children?: ReactNode
}) {
  return (
    <article className={clsx('metric', `metric--${tone}`)}>
      <div className="metric__topline">
        <span>{label}</span>
        <span className="metric__signal" aria-hidden="true" />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
      {children}
    </article>
  )
}

export function Progress({
  value,
  label,
  tone = 'cyan',
}: {
  value: number
  label?: string
  tone?: Tone
}) {
  const clampedValue = Math.min(100, Math.max(0, value))
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={label ?? `${clampedValue}% complete`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clampedValue}
    >
      <span
        className={clsx('progress__fill', `progress__fill--${tone}`)}
        style={{ inlineSize: `${clampedValue}%` }}
      />
    </div>
  )
}

export function SyntheticBanner({ compact = false }: { compact?: boolean }) {
  return (
    <div className={clsx('synthetic-banner', compact && 'synthetic-banner--compact')}>
      <ShieldCheck size={14} aria-hidden="true" />
      <span>{syntheticNotice}</span>
    </div>
  )
}

export function TextLink({ children }: { children: ReactNode }) {
  return (
    <span className="text-link">
      {children}
      <ArrowUpRight size={13} aria-hidden="true" />
    </span>
  )
}

export function DefinitionList({
  items,
}: {
  items: ReadonlyArray<readonly [string, ReactNode]>
}) {
  return (
    <dl className="definition-list">
      {items.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
