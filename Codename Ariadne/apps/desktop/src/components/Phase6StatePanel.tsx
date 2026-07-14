import {
  DatabaseZap,
  GitCompareArrows,
  Inbox,
  LoaderCircle,
  ShieldX,
} from 'lucide-react'
import { Button, Panel } from './Primitives'

type Phase6State = 'loading' | 'no-profile' | 'empty' | 'error' | 'insufficient'

const stateIcon = {
  loading: LoaderCircle,
  'no-profile': ShieldX,
  empty: Inbox,
  error: DatabaseZap,
  insufficient: GitCompareArrows,
} as const

export function Phase6StatePanel({
  state,
  title,
  detail,
  compact = false,
  onRetry,
}: {
  readonly state: Phase6State
  readonly title: string
  readonly detail: string
  readonly compact?: boolean
  readonly onRetry?: () => void
}) {
  const Icon = stateIcon[state]
  return (
    <Panel
      className={`phase6-state-panel phase6-state-panel--${state}${compact ? ' phase6-state-panel--compact' : ''} panel--raised`}
      role={state === 'error' ? 'alert' : 'status'}
      aria-busy={state === 'loading'}
    >
      <span className="phase6-state-panel__icon" aria-hidden="true">
        <Icon size={22} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{detail}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" size="compact" onClick={onRetry}>
          Retry local load
        </Button>
      ) : null}
    </Panel>
  )
}
