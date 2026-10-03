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
  isTerminal,
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
  rows: (PromptRowRecord & { prompt_index: number | null })[]
  /** Training steps as they stream in. */
  training: { step: number; k: number | null; reward: number | null; loss: number | null; epsilon: number | null; q_values: (number | null)[] }[]
  runError: string | null

  /** Fetch startup config and history. Safe to call more than once. */
  init: () => Promise<void>
  refreshRuns: () => Promise<void>
  setAppInfo: (info: AppInfo) => void
  setHostError: (message: string) => void

  startRun: (request: RunRequest) => Promise<void>
  cancelRun: () => Promise<void>

  /** Apply one event from the sidecar. Exported for tests. */
  applyEvent: (event: RunEvent) => void
  /** Rebuild the live view from a recorded event timeline. */
  replay: (runId: string, events: RunEvent[]) => void
  /** Return to the idle state so a new run can be configured. */
  reset: () => void
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
    const state = get()

    // Ignore events from a previous run that finished after this one started.
    if (state.activeRunId && event.run_id !== state.activeRunId) return
    if (!state.activeRunId) set({ activeRunId: event.run_id })

    const data = event.data as Record<string, never>
    let progress = state.progress
    let rows = state.rows
    let training = state.training
    let status = state.status
    let runError = state.runError
    let logs = state.logs

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
        break
      }
      case 'run_failed': {
        status = 'failed'
        runError = (data as unknown as { error: string }).error
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

    set({
      progress,
      rows,
      training,
      status,
      runError,
      logs,
      ...(isTerminal(event) ? { status: event.type === 'run_failed' ? ('failed' as const) : ('completed' as const) } : {}),
    })

    if (isTerminal(event)) void get().refreshRuns()
  },

  replay(runId, events) {
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
  },

  reset() {
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