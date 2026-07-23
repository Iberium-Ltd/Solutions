/**
 * Standard accessible boolean control used by settings and policy panels,
 * centralizing label association and disabled-state behavior.
 */
import * as Switch from '@radix-ui/react-switch'
import clsx from 'clsx'

export function Toggle({
  checked,
  onCheckedChange,
  label,
  description,
  disabled = false,
  className,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  label: string
  description?: string
  disabled?: boolean
  className?: string
}) {
  return (
    <label className={clsx('toggle-row', className, disabled && 'is-disabled')}>
      <span className="toggle-row__copy">
        <span>{label}</span>
        {description && <small>{description}</small>}
      </span>
      <Switch.Root
        className="switch"
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-label={label}
      >
        <Switch.Thumb className="switch__thumb" />
      </Switch.Root>
    </label>
  )
}
