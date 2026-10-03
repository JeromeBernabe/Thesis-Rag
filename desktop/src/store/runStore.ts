/**
 * The live run, and the run history, as one store.
 *
 * The sidecar's event stream is the single source of truth. This store keeps a
 * running projection of it - phase, progress, log lines, partial results - so the
 * Run page can render without refetching, and so a page reload can rebuild the
 * view from the recorded event timeline instead of showing a blank console.
 *
 * Events are appended, never mutated in place. A run is finished the moment its
 * terminal event arrives; the Results page reads from the database, not from here.
 */

import { create } from 'zustand'

import * as api from '@/lib/api'
import {
  EVENT_TYPES,
  type Phase,
  type PromptRowRecord,
  type RunEvent,
  type SystemId,
} from '@/types/events'
import type { AppInfo, RunRecord, RunRequest } from '@/types/models'

/** How many log lines to keep. A chatty run would otherwise grow without bound. */
const MAX_LOG_LINES = 500

/** How many prompt rows to keep in memory for the live table. */
const MAX_LIVE_ROWS = 2000

/**
 * Queued events to apply before flushing, whichever way.
 *
 * A long run emits far more events than a frame can absorb: a 20k-prompt run
 * produced around 240k of them, and applying each one as it arrived meant a
 * Zustand update and a React render per event, which wedged the WebView outright.
 * Events are queued instead and folded into a single update per frame, so the
 * cost of a burst becomes one render rather than one per event.
 *
 * Exported so the batching test can assert against the real cap rather than a
 * copy of it.
 */
export const MAX_PENDING_EVENTS = 4000

/** A stored prompt row as the live table holds it. */
type LiveRow = PromptRowRecord & { prompt_index: number | null }

/** One training step as the live charts hold it. */
interface TrainingStep {
  step: number
  k: number | null
  reward: number | null
  loss: number | null
  epsilon: number | null
  q_values: (number | null)[]
}

export type RunStatus = 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'cancelled'

/** One line in the console, ready to render. */
export interface LogLine {
  seq: number
  ts_ms: number
  level: 'info' | 'warning' | 'error' | 'event'
  message: string
}

interface LiveProgress {
  /** Current phase and its human-readable detail. */
  phase: Phase | null
  phaseDetail: string
  /** Which phase finished, for the phase checklist. */
  completedPhases: Phase[]
  /** Indexing progress, when the run is building a collection. */
  indexDone: number
  indexTotal: number
  /** How many prompts each system has finished. */
  promptsDone: Record<string, number>
  promptsTotal: number
  /** Prompts the judge has scored, which is where the wall-clock goes. */
  judgedCount: number
  startedAt: number | null
}

const EMPTY_PROGRESS: LiveProgress = {
  phase: null,
  phaseDetail: '',
  completedPhases: [],
  indexDone: 0,
  indexTotal: 0,
  promptsDone: {},
  promptsTotal: 0,
  judgedCount: 0,
  startedAt: null,
}

export interface RunState {
  appInfo: AppInfo | null
  /** Non-null when Tauri could not be reached, e.g. the page opened in a browser. */
  hostError: string | null

  runs: RunRecord[]
  runsLoading: boolean

  activeRunId: string | null
  status: RunStatus
  progress: LiveProgress
  logs: LogLine[]
  /** Partial rows, keyed the same way the database is. */
  rows: LiveRow[]
  /** Training steps as they stream in. */
  training: TrainingStep[]
  runError: string | null

  /** Fetch startup config and history. Safe to call more than once. */
  init: () => Promise<void>
  refreshRuns: () => Promise<void>
  setAppInfo: (info: AppInfo) => void
  setHostError: (message: string) => void

  startRun: (request: RunRequest) => Promise<void>
  cancelRun: () => Promise<void>

  /**
   * Queue one event from the sidecar, flushing at most once per frame.
   *
   * Returns before the event is applied, so anything reading state straight after
   * a call has to `flushEvents` first. That is the point: the alternative was one
   * render per event.
   */
  applyEvent: (event: RunEvent) => void
  /** Apply everything queued, now. Idempotent when the queue is empty. */
  flushEvents: () => void
  /** Rebuild the live view from a recorded event timeline. */
  replay: (runId: string, events: RunEvent[]) => void
  /** Return to the idle state so a new run can be configured. */
  reset: () => void
}

/** Events waiting for the next flush, and whether a flush is already scheduled. */
let pending: RunEvent[] = []
let flushScheduled = false

/**
 * Ask for the next frame, falling back to a timer.
 *
 * `requestAnimationFrame` does not fire in a hidden tab, and an app whose window
 * is minimised would then accumulate events forever with nothing applying them -
 * so the queue is also flushed outright once it grows past `MAX_PENDING_EVENTS`.
 */
function scheduleFlush(): void {
  if (flushScheduled) return
  flushScheduled = true
  const run = () => {
    flushScheduled = false
    useRunStore.getState().flushEvents()
  }
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(run)
  } else {
    setTimeout(run, 16)
  }
}

/**
 * The slice of state an event stream can change.
 *
 * Folded in place over a whole batch, then committed as one update. Kept separate
 * from the store so the reduction is a pure function of (state, events) and can be
 * reasoned about - and tested - without a store, a scheduler or a React tree.
 */
interface Accumulator {
  activeRunId: string | null
  progress: LiveProgress
  rows: LiveRow[]
  training: TrainingStep[]
  status: RunStatus
  runError: string | null
  logs: LogLine[]
  /** Set when the batch contained an end-of-run event, which refreshes history. */
  sawTerminal: boolean
}

function accumulatorFrom(state: RunState): Accumulator {
  return {
    activeRunId: state.activeRunId,
    progress: state.progress,
    rows: state.rows,
    training: state.training,
    status: state.status,
    runError: state.runError,
    logs: state.logs,
    sawTerminal: false,
  }
}

/** Whether the event carries a known type we render specially. */
function isKnownType(type: string): boolean {
  return (EVENT_TYPES as readonly string[]).includes(type)
}

function pushLog(logs: LogLine[], line: LogLine): LogLine[] {
  const next = logs.length >= MAX_LOG_LINES ? logs.slice(logs.length - MAX_LOG_LINES + 1) : logs.slice()
  next.push(line)
  return next
}

export const useRunStore = create<RunState>((set, get) => ({
  appInfo: null,
  hostError: null,
  runs: [],
  runsLoading: false,
  activeRunId: null,
  status: 'idle',
  progress: EMPTY_PROGRESS,
  logs: [],
  rows: [],
  training: [],
  runError: null,

  setAppInfo: (appInfo) => set({ appInfo, hostError: null }),

  setHostError: (hostError) => set({ hostError }),

  async init() {
    try {
      const appInfo = await api.getAppInfo()
      set({ appInfo, hostError: null })
    } catch (error) {
      set({ hostError: describe(error) })
    }
    await get().refreshRuns()
  },

  async refreshRuns() {
    set({ runsLoading: true })
    try {
      const runs = await api.listRuns()
      set({ runs, runsLoading: false })
    } catch (error) {
      set({ runsLoading: false, hostError: describe(error) })
    }
  },

  async startRun(request) {
    // Anything still queued belongs to the previous run and would otherwise be
    // folded into this one, since the cleared state has no run id to reject it.
    pending = []
    set({ status: 'starting', runError: null, logs: [], rows: [], training: [], progress: EMPTY_PROGRESS })
    try {
      const handle = await api.startRun(request)
      set({
        activeRunId: handle.runId,
        status: 'running',
        progress: { ...EMPTY_PROGRESS, startedAt: Date.now() },
      })
      void get().refreshRuns()
    } catch (error) {
      set({ status: 'failed', runError: describe(error) })
    }
  },

  async cancelRun() {
    try {
      await api.cancelRun()
      set({ status: 'cancelled' })
    } catch (error) {
      set({ runError: describe(error) })
    }
  },

  applyEvent(event) {
    pending.push(event)
    // A burst this deep would wait a long time for a frame that may never come,
    // and the queue itself is the memory cost, so give up on waiting.
    if (pending.length >= MAX_PENDING_EVENTS) {
      get().flushEvents()
      return
    }
    scheduleFlush()
  },

  flushEvents() {
    if (pending.length === 0) return
    const batch = pending
    pending = []

    let sawTerminal = false
    set((state) => {
      const acc = accumulatorFrom(state)
      for (const event of batch) reduceEvent(acc, event)
      sawTerminal = acc.sawTerminal
      return {
        activeRunId: acc.activeRunId,
        progress: acc.progress,
        rows: acc.rows,
        training: acc.training,
        status: acc.status,
        runError: acc.runError,
        logs: acc.logs,
      }
    })

    if (sawTerminal) void get().refreshRuns()
  },

  replay(runId, events) {
    // Queued events belong to the run being replaced, so they go first: they would
    // otherwise be folded into the replayed run, and `activeRunId` is null at this
    // point so nothing would reject them as stale.
    pending = []
    set({
      activeRunId: runId,
      logs: [],
      rows: [],
      training: [],
      progress: EMPTY_PROGRESS,
      runError: null,
      status: 'running',
    })
    for (const event of events) get().applyEvent(event)
    // A recorded timeline is already complete, so there is no frame worth waiting
    // for - and folding thousands of events one render at a time is what wedged
    // the window in the first place.
    get().flushEvents()
  },

  reset() {
    pending = []
    set({
      activeRunId: null,
      status: 'idle',
      progress: EMPTY_PROGRESS,
      logs: [],
      rows: [],
      training: [],
      runError: null,
    })
  },
}))

/**
 * Fold one event into `acc`, in place.
 *
 * Reads and writes only the accumulator, never the store, so a whole batch can be
 * reduced before anything is committed.
 */
function reduceEvent(acc: Accumulator, event: RunEvent): void {
  // Ignore events from a previous run that finished after this one started. Read
  // the accumulator rather than the store, because an earlier event in this same
  // batch may have adopted a run id.
  if (acc.activeRunId && event.run_id !== acc.activeRunId) return
  if (!acc.activeRunId) acc.activeRunId = event.run_id

  const data = event.data as Record<string, never>
  let progress = acc.progress
  let rows = acc.rows
  let training = acc.training
  let status = acc.status
  let runError = acc.runError
  let logs = acc.logs

  switch (event.type) {
    case 'run_started': {
      const info = data as unknown as {
        prompt_count?: number
        systems?: SystemId[]
      }
      // The event stream, not the command, is the source of truth for status:
      // a run replayed from the database never called `start_run`.
      status = 'running'
      progress = { ...EMPTY_PROGRESS, startedAt: Date.now(), promptsTotal: info.prompt_count ?? 0 }
      break
    }
    case 'phase': {
      const phase = (data as unknown as { phase: Phase; detail: string }).phase
      progress = {
        ...progress,
        phase,
        phaseDetail: (data as unknown as { detail: string }).detail ?? '',
        completedPhases: progress.completedPhases.includes(phase)
          ? progress.completedPhases
          : [...progress.completedPhases, phase],
      }
      break
    }
    case 'index_progress': {
      const payload = data as unknown as { done: number; total: number }
      progress = { ...progress, indexDone: payload.done, indexTotal: payload.total }
      break
    }
    case 'prompt_started': {
      const payload = data as unknown as { total: number }
      progress = { ...progress, promptsTotal: payload.total || progress.promptsTotal }
      break
    }
    case 'prompt_completed': {
      const payload = data as unknown as { system: string; row?: PromptRowRecord }
      const done = { ...progress.promptsDone }
      done[payload.system] = (done[payload.system] ?? 0) + 1
      progress = { ...progress, promptsDone: done }
      if (payload.row) {
        rows = upsertRow(rows, {
          ...payload.row,
          prompt_index: (data as unknown as { index: number }).index ?? null,
        })
      }
      break
    }
    case 'ragas': {
      progress = { ...progress, judgedCount: progress.judgedCount + 1 }
      break
    }
    case 'train_step': {
      training = [
        ...training,
        {
          step: (data as unknown as { step: number }).step,
          k: (data as unknown as { k: number | null }).k ?? null,
          reward: (data as unknown as { reward: number | null }).reward ?? null,
          loss: (data as unknown as { loss: number | null }).loss ?? null,
          epsilon: (data as unknown as { epsilon: number | null }).epsilon ?? null,
          q_values: (data as unknown as { q_values: (number | null)[] }).q_values ?? [],
        },
      ]
      break
    }
    case 'run_finished': {
      status = 'completed'
      acc.sawTerminal = true
      break
    }
    case 'run_failed': {
      status = 'failed'
      runError = (data as unknown as { error: string }).error
      acc.sawTerminal = true
      break
    }
    default:
      break
  }

  // Anything with a message goes to the console: logs always, and every other
  // event type at a lower weight so the timeline still reads as a timeline.
  if (event.type === 'log') {
    const payload = data as unknown as { level: 'info' | 'warning' | 'error'; message: string }
    logs = pushLog(logs, { seq: event.seq, ts_ms: event.ts_ms, level: payload.level, message: payload.message })
  } else if (event.type !== 'embedding' && event.type !== 'index_progress') {
    const level = event.type === 'run_failed' ? ('error' as const) : ('event' as const)
    logs = pushLog(logs, { seq: event.seq, ts_ms: event.ts_ms, level, message: summarize(event) })
  }

  acc.progress = progress
  acc.rows = rows
  acc.training = training
  acc.status = status
  acc.runError = runError
  acc.logs = logs
}

/** Insert or replace a row, keeping the table keyed as the database is. */
function upsertRow<T extends { system: string; prompt_id: string }>(
  rows: T[],
  row: T,
): T[] {
  const at = rows.findIndex((r) => r.system === row.system && r.prompt_id === row.prompt_id)
  if (at === -1) {
    const next = rows.length >= MAX_LIVE_ROWS ? rows.slice(rows.length - MAX_LIVE_ROWS + 1) : rows.slice()
    next.push(row)
    return next
  }
  const next = rows.slice()
  next[at] = { ...next[at], ...row }
  return next
}

/** One-line description of an event, for the console. */
function summarize(event: RunEvent): string {
  const d = event.data as Record<string, unknown>
  switch (event.type) {
    case 'phase':
      return `phase ${String(d.phase)} - ${String(d.detail ?? '')}`
    case 'prompt_started':
      return `${String(d.system)} prompt ${Number(d.index) + 1}/${Number(d.total)} - ${String(d.question ?? '')}`
    case 'retrieval':
      return `${String(d.system)} retrieved k=${String(d.k)}`
    case 'generation':
      return `${String(d.system)} generated ${String(d.answer ?? '')}`
    case 'ragas':
      return `${String(d.system)} judged faith=${fmt(d.faithfulness)} relev=${fmt(d.answer_relevancy)} recall=${fmt(d.context_recall)}`
    case 'decision':
      return `${String(d.system)} ${String(d.phase)} chose k=${String(d.k)} (epsilon ${fmt(d.epsilon)})`
    case 'reward':
      return `${String(d.system)} k distribution ${JSON.stringify(d.k_distribution ?? {})}`
    case 'train_step':
      return `step ${String(d.step)} k=${String(d.k)} reward=${fmt(d.reward)}`
    case 'prompt_completed':
      return `${String(d.system)} prompt ${Number(d.index) + 1} done (k=${String(d.k)})`
    case 'stats':
      return 'statistics computed'
    case 'run_started':
      return `run started - ${String(d.dataset)} x${String(d.prompt_count)} prompts`
    case 'run_finished':
      return `run finished in ${fmt(d.duration_s)}s`
    case 'run_failed':
      return `run failed - ${String(d.error)}`
    default:
      return isKnownType(event.type) ? event.type : `${event.type} (unrecognised)`
  }
}

function fmt(value: unknown): string {
  if (value === null || value === undefined) return 'n/a'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3)
  return String(value)
}

/** Turn a rejected promise into something worth showing a user. */
export function describe(error: unknown): string {
  if (typeof error === 'string') return error
  if (error instanceof Error) return error.message
  return String(error)
}