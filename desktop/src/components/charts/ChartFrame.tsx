/**
 * Recharts wrapper.
 *
 * Recharts needs a sized parent to measure against; in a flex column an
 * unconstrained chart collapses to zero height. Rather than sprinkling
 * `h-[300px]` at every call site, the wrapper reserves the height itself and
 * renders a proper empty state instead of an empty axes box.
 */

import type { ReactNode } from 'react'
import { ResponsiveContainer } from 'recharts'

import { EmptyState } from '@/components/ui'

/** Colour tokens, kept in sync with `--color-system-*` in `index.css`. */
export const SERIES = {
  A: 'var(--color-system-a)',
  B: 'var(--color-system-b)',
} as const

/** The single-series accent, for charts with no A/B split. */
export const ACCENT = 'var(--color-accent)'
export const MUTED = 'var(--color-ink-faint)'

/**
 * Distinct colours for the five retrieval-k actions.
 *
 * These are the Q-value lines, which have to be told apart from each other across
 * five overlapping series. The A/B pair cannot be reused: the two systems are
 * being compared against each other, whereas these five are five values of the
 * same quantity, so they need a sequential ramp rather than two categories.
 */
export const K_SERIES = [
  'var(--color-system-a)',
  'var(--color-system-b)',
  'var(--color-warning)',
  'var(--color-accent)',
  'var(--color-danger)',
] as const

/** Axis and grid styling shared by every chart. */
export const AXIS = {
  stroke: 'var(--color-border)',
  tick: { fill: 'var(--color-ink-faint)', fontSize: 11 },
  tickLine: false,
} as const

export const GRID = {
  stroke: 'var(--color-border)',
  strokeOpacity: 0.35,
  strokeDasharray: '2 4',
} as const

/** Tooltip styling shared by every chart. */
export const TOOLTIP = {
  contentStyle: {
    background: 'var(--color-surface-inset)',
    border: '1px solid var(--color-border)',
    borderRadius: '0.375rem',
    color: 'var(--color-ink)',
    fontSize: '0.75rem',
  },
  labelStyle: { color: 'var(--color-ink-muted)' },
  itemStyle: { color: 'var(--color-ink)' },
  cursor: { fill: 'rgba(255,255,255,0.04)' },
} as const

/**
 * A sized chart region.
 *
 * `hasData` decides between the chart and an empty state, so a metric the judge
 * never produced shows a message instead of an empty grid.
 */
export function ChartFrame({
  height = 240,
  hasData,
  emptyTitle = 'No data',
  emptyDetail,
  children,
}: {
  height?: number
  hasData: boolean
  emptyTitle?: string
  emptyDetail?: string
  children: ReactNode
}) {
  if (!hasData) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <EmptyState title={emptyTitle} detail={emptyDetail} />
      </div>
    )
  }
  return (
    <div style={{ height }} className="min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        {children as never}
      </ResponsiveContainer>
    </div>
  )
}