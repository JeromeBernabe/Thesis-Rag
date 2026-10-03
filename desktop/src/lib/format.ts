/**
 * Formatting helpers.
 *
 * Collected in one place because the rule that matters - a missing value is shown
 * as an em dash, never as `0` - has to hold identically in every table, chart
 * tooltip and stat tile. A run with no judge must not look like a run that scored
 * zero.
 */

/** The placeholder for a value that does not exist. */
export const DASH = '—'

/**
 * A number, or the dash when absent.
 *
 * `0` is a real score and must survive; only `null`/`undefined` become a dash.
 */
export function fmtNum(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return value.toFixed(digits)
}

/** An integer count, or the dash. */
export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return String(Math.round(value))
}

/** A duration in seconds, rendered with a sensible unit. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return DASH
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds - minutes * 60)
  if (minutes < 60) return `${minutes}m ${rest}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes - hours * 60}m`
}

/** A wall-clock time from an epoch-millisecond stamp. */
export function fmtTime(tsMs: number | null | undefined): string {
  if (!tsMs) return DASH
  return new Date(tsMs).toLocaleTimeString()
}

/** A date and time, for run listings. */
export function fmtDateTime(tsMs: number | null | undefined): string {
  if (!tsMs) return DASH
  const date = new Date(tsMs)
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`
}

/** A signed percentage, for deltas between two systems. */
export function fmtDelta(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  const pct = value * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(digits)}%`
}

/** A p-value, marked as significant at the usual 0.05 threshold. */
export function fmtPValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  if (value < 0.001) return '< 0.001'
  return value.toFixed(3)
}

/** A t or w statistic. */
export function fmtStat(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return value.toFixed(2)
}

/** A short run id, for dense tables. */
export function shortRunId(runId: string): string {
  return runId.length <= 12 ? runId : `${runId.slice(0, 8)}…`
}

/**
 * The k values a run actually used, ascending.
 *
 * Read from the distribution map rather than assuming 1..5, so a run that only
 * ever picked k=3 does not show four phantom bars.
 */
export function kValues(distribution: Record<string, number> | null | undefined): number[] {
  if (!distribution) return []
  return Object.keys(distribution)
    .map(Number)
    .filter((k) => Number.isFinite(k))
    .sort((a, b) => a - b)
}