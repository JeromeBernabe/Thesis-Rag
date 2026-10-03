/**
 * Small UI primitives.
 *
 * Written locally rather than pulled from shadcn's generator: the set actually
 * needed is six components, and keeping them in-tree means no codegen step and no
 * dependency whose version can drift between checkouts.
 */

import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, LabelHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { Slot } from '@radix-ui/react-slot'

import { cn } from '@/lib/utils'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent/85 disabled:hover:bg-accent',
  secondary: 'bg-surface-raised text-ink hover:bg-border disabled:hover:bg-surface-raised',
  ghost: 'bg-transparent text-ink-muted hover:bg-surface-raised hover:text-ink',
  danger: 'bg-danger text-white hover:bg-danger/85 disabled:hover:bg-danger',
}

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-xs',
  md: 'h-9 px-3.5 text-sm',
  lg: 'h-11 px-5 text-base',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Render as the single child element instead of a `<button>`. */
  asChild?: boolean
}

export function Button({
  className,
  variant = 'secondary',
  size = 'md',
  asChild = false,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : 'button'
  return (
    <Component
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded font-medium whitespace-nowrap',
        'transition-colors outline-none select-none',
        'focus-visible:ring-2 focus-visible:ring-accent/60',
        'disabled:cursor-not-allowed disabled:opacity-45',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    />
  )
}

export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('bg-surface-raised rounded-panel border border-border', className)}
      {...props}
    />
  )
}

/**
 * The page's one and only `h1`.
 *
 * `PanelHeader` titles are `h2`, which leaves the document with no top-level
 * heading: a screen reader announces the panels with nothing above them, and the
 * three pages become indistinguishable in a heading list. The text is hidden
 * because the shell's tab bar already names the current page visually - this
 * exists for document structure, not for reading twice.
 */
export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="sr-only">{children}</h1>
}

export function PanelHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3 border-b border-border px-4 py-3',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-ink truncate text-sm font-semibold">{title}</h2>
        {subtitle ? <p className="text-ink-faint mt-0.5 text-xs">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('text-ink-muted mb-1 block text-xs font-medium', className)}
      {...props}
    />
  )
}

export const inputClass = cn(
  'bg-surface-inset border-border text-ink rounded border px-2.5 py-1.5 text-sm w-full',
  'placeholder:text-ink-faint outline-none',
  'focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent/50',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputClass, className)} {...props} />
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(inputClass, 'cursor-pointer', className)} {...props} />
}

export function Checkbox({
  label,
  description,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; description?: string }) {
  return (
    <label className={cn('flex cursor-pointer items-start gap-2.5', className)}>
      <input
        type="checkbox"
        className={cn(
          'accent-accent mt-0.5 size-4 shrink-0 rounded',
          'focus-visible:ring-2 focus-visible:ring-accent/60',
        )}
        {...props}
      />
      <span className="min-w-0">
        <span className="text-ink block text-sm">{label}</span>
        {description ? (
          <span className="text-ink-faint block text-xs">{description}</span>
        ) : null}
      </span>
    </label>
  )
}

/** Horizontal meter. `null` renders an empty track, never a zero-width fill. */
export function ProgressBar({
  value,
  label,
  className,
}: {
  value: number | null
  label?: ReactNode
  className?: string
}) {
  const pct = value === null ? null : Math.max(0, Math.min(100, value * 100))
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div
        className="bg-surface-inset border-border h-1.5 min-w-0 flex-1 overflow-hidden rounded-full border"
        role="progressbar"
        aria-valuenow={pct === null ? undefined : Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={typeof label === 'string' ? label : undefined}
      >
        {pct === null ? null : (
          <div
            className="bg-accent h-full transition-[width] duration-200"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {label ? <span className="text-ink-muted tnum text-xs">{label}</span> : null}
    </div>
  )
}

/** A metric tile. `value` is passed pre-formatted by the caller. */
export function StatTile({
  label,
  value,
  hint,
  tone = 'neutral',
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'neutral' | 'a' | 'b' | 'danger'
  className?: string
}) {
  const toneClass = {
    neutral: 'text-ink',
    a: 'text-system-a',
    b: 'text-system-b',
    danger: 'text-danger',
  }[tone]
  return (
    <Panel className={cn('p-3', className)}>
      <div className="text-ink-faint text-[0.7rem] font-medium tracking-wide uppercase">
        {label}
      </div>
      <div className={cn('tnum mt-1 text-xl font-semibold', toneClass)}>{value}</div>
      {hint ? <div className="text-ink-faint mt-0.5 text-xs">{hint}</div> : null}
    </Panel>
  )
}

/** Empty-state block. Shown instead of a blank chart or table. */
export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string
  detail?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <p className="text-ink text-sm font-medium">{title}</p>
      {detail ? <p className="text-ink-faint max-w-md text-xs">{detail}</p> : null}
      {action}
    </div>
  )
}

/** Coloured dot for system identity, used in legends and run lists. */
export function SystemDot({ system, className }: { system: 'A' | 'B'; className?: string }) {
  return (
    <>
      <span
        aria-hidden
        className={cn(
          'inline-block size-2 shrink-0 rounded-full',
          system === 'A' ? 'bg-system-a' : 'bg-system-b',
          className,
        )}
      />
      {/* The dot alone is colour, which is invisible to a screen reader and
          ambiguous to anyone who cannot separate the two hues. Whenever a dot is
          the marker, the system needs a name next to it. */}
      <span className="sr-only">System {system}</span>
    </>
  )
}