/**
 * A ticking elapsed-time readout for the active run.
 *
 * Reading `Date.now()` during render is both impure and, more to the point,
 * wrong for this job: the value would only be recomputed when something else
 * caused a re-render. Runs spend minutes inside a single phase - embedding a
 * corpus, waiting on RAGAS - and can emit no events at all while doing it, so a
 * render-time clock visibly stalls exactly when the user is watching it.
 *
 * When nothing is running the interval is never started, so an idle panel costs
 * nothing.
 */

import { useEffect, useState } from 'react'

/** Fast enough to look live, slow enough to stay off the critical path. */
export const TICK_MS = 1000

/**
 * Seconds elapsed since `startedAt`, or null when there is nothing to measure.
 *
 * @param active Whether the clock should run at all.
 * @param startedAt Epoch milliseconds the run began, or null if it has not.
 */
export function useElapsedSeconds(
  active: boolean,
  startedAt: number | null,
  tickMs: number = TICK_MS,
): number | null {
  const [now, setNow] = useState<number | null>(null)

  useEffect(() => {
    if (!active || startedAt === null) {
      return
    }
    // Catch up immediately: the panel may mount well after the run began, or
    // well after the last tick.
    setNow(Date.now())
    const id = setInterval(() => setNow(Date.now()), tickMs)
    return () => clearInterval(id)
  }, [active, startedAt, tickMs])

  if (!active || startedAt === null) {
    return null
  }
  // Before the first effect runs, fall back to zero rather than rendering a
  // negative or absurd duration.
  return ((now ?? startedAt) - startedAt) / 1000
}
