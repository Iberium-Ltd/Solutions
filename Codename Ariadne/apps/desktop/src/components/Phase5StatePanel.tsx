import {
  AlertTriangle,
  DatabaseZap,
  Inbox,
  LoaderCircle,
  ShieldX,
} from 'lucide-react'
import { Button, Panel } from './Primitives'

type Phase5State = 'loading' | 'no-profile' | 'empty' | 'error' | 'not-found'

const stateIcon = {
  loading: LoaderCircle,
  'no-profile': ShieldX,
  empty: Inbox,
  error: DatabaseZap,
  'not-found': AlertTriangle,
} as const

export function Phase5StatePanel({
  state,
  title,
  detail,
  onRetry,
}: {
  readonly state: Phase5State
  readonly title: string
  readonly detail: string
  readonly onRetry?: () => void
}) {
  const Icon = stateIcon[state]
  const role = state === 'error' || state === 'not-found' ? 'alert' : 'status'
  return (
    <Panel
      className={`phase5-state-panel phase5-state-panel--${state} panel--raised`}
      role={role}
      aria-busy={state === 'loading'}
    >
      <span className="phase5-state-panel__icon" aria-hidden="true">
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
