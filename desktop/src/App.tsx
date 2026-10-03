/**
 * Application shell: title bar, navigation, and the routed page.
 *
 * Routing is a hash rather than the history API on purpose. In production Tauri
 * serves the built assets from its own protocol, and a history-API path such as
 * `/results` is a request for a file called `results` - which does not exist. The
 * dev server papers over this with an SPA fallback, so the problem only appears
 * once the app is packaged. `#/results` survives a reload everywhere, so dev,
 * `vite preview` and the packaged window all behave the same.
 */

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'

import * as api from '@/lib/api'
import { describe, useRunStore } from '@/store/runStore'
import { Button, SystemDot } from '@/components/ui'
import { RunPage } from '@/pages/RunPage'

/**
 * Results and Simulation are split out of the initial bundle.
 *
 * Between them they pull in Recharts and three.js - roughly 1.6 MB of the 1.9 MB
 * total. The Run page does not need either, and a run is the thing a user most
 * often wants to start immediately, so those two routes load on demand. There is
 * no visual flash because the placeholder occupies the same box as the page.
 */
const ResultsPage = lazy(() => import('@/pages/ResultsPage').then((m) => ({ default: m.ResultsPage })))
const SimulationPage = lazy(() =>
  import('@/pages/SimulationPage').then((m) => ({ default: m.SimulationPage })),
)

/** The three pages, in navigation order. */
const ROUTES = [
  { key: 'run', label: 'Run', hash: '#/' },
  { key: 'results', label: 'Results', hash: '#/results' },
  { key: 'simulation', label: 'Simulation', hash: '#/simulation' },
] as const

type RouteKey = (typeof ROUTES)[number]['key']

/** The current route, from the fragment. An unknown or empty fragment means Run. */
function routeFromHash(hash: string): RouteKey {
  const path = hash.replace(/^#/, '') || '/'
  return ROUTES.find((route) => path === route.hash.replace(/^#/, ''))?.key ?? 'run'
}

export function App() {
  const [route, setRoute] = useState<RouteKey>(() => routeFromHash(window.location.hash))
  const [subscribeError, setSubscribeError] = useState<string | null>(null)

  const hostError = useRunStore((s) => s.hostError)
  const status = useRunStore((s) => s.status)
  const activeRunId = useRunStore((s) => s.activeRunId)
  const runs = useRunStore((s) => s.runs)
  const init = useRunStore((s) => s.init)
  const applyEvent = useRunStore((s) => s.applyEvent)

  const navigate = useCallback((next: string) => {
    window.location.hash = next
    setRoute(routeFromHash(next))
  }, [])

  // One subscription for the whole app: the store is the only consumer, and a
  // per-page subscription would drop events during a route change.
  useEffect(() => {
    // StrictMode mounts effects twice in development. The first subscription may
    // still be in flight when its cleanup runs, at which point there is no stop
    // function to call yet - so track teardown separately rather than relying on
    // `stopRef` being populated by then.
    let disposed = false
    let stop: (() => void) | null = null

    void init()
    void api
      .onEvent((event) => applyEvent(event))
      .then((unlisten) => {
        if (disposed) {
          // Resolved after teardown: dispose of it immediately or it leaks for the
          // lifetime of the window, still writing into a dead store.
          unlisten()
          return
        }
        stop = unlisten
      })
      .catch((error: unknown) => {
        if (!disposed) setSubscribeError(describe(error))
      })

    return () => {
      disposed = true
      stop?.()
      stop = null
    }
  }, [applyEvent, init])

  // A hash change fires `hashchange` rather than `popstate`, and it also covers
  // the back button - both of which must re-read the fragment.
  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Refresh history when a run finishes, so the Results picker is current.
  const refreshRuns = useRunStore((s) => s.refreshRuns)
  const lastStatus = useRef(status)
  useEffect(() => {
    if (lastStatus.current !== status && (status === 'completed' || status === 'failed')) {
      void refreshRuns()
    }
    lastStatus.current = status
  }, [status, refreshRuns])

  return (
    <div className="flex h-full flex-col">
      <header className="border-border bg-surface-raised flex h-11 shrink-0 items-center gap-4 border-b px-3">
        <div className="flex items-center gap-2">
          <span className="bg-accent size-2.5 rounded-sm" aria-hidden />
          <span className="text-sm font-semibold">DQN-RAG Bench</span>
        </div>

        <nav aria-label="Primary" className="flex items-center gap-1">
          {ROUTES.map((r) => (
            <Button
              key={r.key}
              size="sm"
              variant={route === r.key ? 'secondary' : 'ghost'}
              aria-current={route === r.key ? 'page' : undefined}
              onClick={() => navigate(r.hash)}
            >
              {r.label}
            </Button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <RunStatusPill />
          <span className="text-ink-faint tnum text-xs" title={activeRunId ?? undefined}>
            {runs.length} run{runs.length === 1 ? '' : 's'}
          </span>
        </div>
      </header>

      {(hostError || subscribeError) && (
        <div
          role="alert"
          className="border-danger/40 bg-danger/10 text-danger shrink-0 border-b px-3 py-1.5 text-xs"
        >
          {hostError ?? subscribeError}
          {hostError ? ' - the app must be launched with `npm run tauri dev`, not a browser.' : ''}
        </div>
      )}

      <main className="min-h-0 flex-1 overflow-hidden">
        <Suspense fallback={<RoutePlaceholder />}>
          {route === 'run' ? (
            <RunPage />
          ) : route === 'results' ? (
            <ResultsPage />
          ) : (
            <SimulationPage />
          )}
        </Suspense>
      </main>
    </div>
  )
}

/** Fills the routed area so navigating does not collapse the layout mid-load. */
function RoutePlaceholder() {
  return (
    <div className="text-ink-faint grid h-full place-items-center text-sm">
      <span>Loading…</span>
    </div>
  )
}

/** Compact run status, so the shell always shows what is happening. */
function RunStatusPill() {
  const status = useRunStore((s) => s.status)
  const label: Record<typeof status, string> = {
    idle: 'idle',
    starting: 'starting',
    running: 'running',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
  }
  const tone: Record<typeof status, string> = {
    idle: 'text-ink-faint',
    starting: 'text-warning',
    running: 'text-accent',
    completed: 'text-success',
    failed: 'text-danger',
    cancelled: 'text-warning',
  }
  return (
    <span className="flex items-center gap-1.5 text-xs">
      {status === 'running' ? (
        <span className="bg-accent size-1.5 animate-pulse rounded-full" aria-hidden />
      ) : null}
      <span className={tone[status]}>{label[status]}</span>
      {status === 'running' ? <SystemDot system="B" /> : null}
    </span>
  )
}