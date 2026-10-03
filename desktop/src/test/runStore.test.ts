import { beforeEach, describe, expect, it, vi } from 'vitest'

// Tauri is absent under jsdom, so the API module is replaced wholesale. Patching
// its exports at runtime is not possible: an ES module namespace is read-only.
// The factory returns `apiMock` itself - its keys are the function names the
// module exports - rather than the wrapper module.
vi.mock('@/lib/api', async () => (await import('@/test/apiMock')).apiMock)

import { useRunStore } from '@/store/runStore'
import { SCHEMA_VERSION, isTerminal, type RunEvent } from '@/types/events'
import { apiMock, resetApiMock } from '@/test/apiMock'

/** Build an event the way the sidecar would, so the store sees real shapes. */
function event(type: string, data: Record<string, unknown>, seq = 1, runId = 'run1'): RunEvent {
  return { v: SCHEMA_VERSION, seq, ts_ms: 1000 + seq, run_id: runId, type, data }
}

/** A completed prompt row, as the sidecar now sends it. */
function row(overrides: Record<string, unknown> = {}) {
  return {
    system: 'A',
    prompt_id: 'p1',
    phase: 'system_a',
    question: 'Who won?',
    ground_truth: 'Samuel Osei Kuffour',
    answer: 'Samuel Kuffour.',
    retrieved_k: 3,
    retrieved_ids: ['doc-aaa', 'doc-bbb', 'doc-ccc'],
    retrieved_distances: [0.2, 0.3, 0.4],
    faithfulness: 0.9,
    answer_relevancy: 0.8,
    context_recall: 0.7,
    prompt_tokens: 10,
    completion_tokens: 5,
    total_tokens: 15,
    judge_prompt_tokens: null,
    judge_completion_tokens: null,
    embedding_time_s: 0.01,
    retrieval_time_s: 0.02,
    generation_time_s: 1.5,
    judge_time_s: null,
    total_time_s: 1.53,
    ...overrides,
  }
}

describe('runStore', () => {
  beforeEach(() => {
    resetApiMock()
    useRunStore.getState().reset()
  })

  it('starts idle', () => {
    const state = useRunStore.getState()
    expect(state.status).toBe('idle')
    expect(state.activeRunId).toBeNull()
    expect(state.logs).toHaveLength(0)
  })

  it('tracks the run id from the first event', () => {
    useRunStore.getState().applyEvent(event('run_started', { dataset: 'hotpot', prompt_count: 2 }, 1))
    expect(useRunStore.getState().activeRunId).toBe('run1')
  })

  it('accumulates phases in order', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('run_started', { dataset: 'hotpot' }, 1))
    store.applyEvent(event('phase', { phase: 'preflight', detail: 'checking' }, 2))
    store.applyEvent(event('phase', { phase: 'system_a', detail: 'baseline' }, 3))
    const { progress, status } = useRunStore.getState()
    expect(progress.completedPhases).toEqual(['preflight', 'system_a'])
    expect(progress.phase).toBe('system_a')
    expect(progress.phaseDetail).toBe('baseline')
    expect(status).toBe('running')
  })

  it('does not duplicate a phase that is re-announced', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('phase', { phase: 'preflight', detail: 'a' }, 1))
    store.applyEvent(event('phase', { phase: 'preflight', detail: 'b' }, 2))
    expect(useRunStore.getState().progress.completedPhases).toEqual(['preflight'])
  })

  it('stores a completed prompt row with its metrics and retrieved ids', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row: row() }, 1))
    const { rows } = useRunStore.getState()
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      system: 'A',
      prompt_id: 'p1',
      answer: 'Samuel Kuffour.',
      faithfulness: 0.9,
      retrieved_k: 3,
      prompt_index: 0,
    })
    expect(rows[0].retrieved_ids).toHaveLength(3)
  })

  it('replaces a re-delivered row instead of duplicating it', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row: row() }, 1))
    store.applyEvent(
      event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 5, row: row({ retrieved_k: 5, faithfulness: 0.4 }) }, 2),
    )
    const { rows } = useRunStore.getState()
    expect(rows).toHaveLength(1)
    expect(rows[0].retrieved_k).toBe(5)
    expect(rows[0].faithfulness).toBe(0.4)
  })

  it('keeps A and B rows for the same prompt apart', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row: row() }, 1))
    store.applyEvent(event('prompt_completed', { system: 'B', index: 0, prompt_id: 'p1', k: 4, row: row({ system: 'B' }) }, 2))
    const { rows } = useRunStore.getState()
    expect(rows).toHaveLength(2)
    expect(rows.map((r) => r.system).sort()).toEqual(['A', 'B'])
  })

  it('tolerates a prompt_completed without a row payload', () => {
    // An older sidecar sends only the envelope keys.
    const store = useRunStore.getState()
    store.applyEvent(event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3 }, 1))
    expect(useRunStore.getState().rows).toHaveLength(0)
    expect(useRunStore.getState().logs.length).toBeGreaterThan(0)
  })

  it('counts prompts per system', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row: row() }, 1))
    store.applyEvent(event('prompt_completed', { system: 'A', index: 1, prompt_id: 'p2', k: 3, row: row({ prompt_id: 'p2' }) }, 2))
    expect(useRunStore.getState().progress.promptsDone).toEqual({ A: 2 })
  })

  it('accumulates training steps in order', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('train_step', { step: 1, k: 1, reward: 0.1, loss: 0.5, epsilon: 1, q_values: [0.1, 0.2] }, 1))
    store.applyEvent(event('train_step', { step: 2, k: 3, reward: 0.4, loss: 0.2, epsilon: 0.5, q_values: [0.1, 0.2] }, 2))
    const { training } = useRunStore.getState()
    expect(training.map((t) => t.step)).toEqual([1, 2])
    expect(training[1].k).toBe(3)
  })

  it('records judge calls so the slow phase is visible', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('ragas', { system: 'A', prompt_id: 'p1', faithfulness: 0.9 }, 1))
    store.applyEvent(event('ragas', { system: 'A', prompt_id: 'p2', faithfulness: 0.8 }, 2))
    expect(useRunStore.getState().progress.judgedCount).toBe(2)
  })

  it('completes on run_finished and records the error on run_failed', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('run_failed', { error: 'judge exploded', traceback: '...' }, 1))
    const state = useRunStore.getState()
    expect(state.status).toBe('failed')
    expect(state.runError).toBe('judge exploded')
  })

  it('marks completed on run_finished', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('run_finished', { run_id: 'run1', duration_s: 12 }, 1))
    expect(useRunStore.getState().status).toBe('completed')
  })

  it('ignores events from a superseded run', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('run_started', { dataset: 'hotpot' }, 1, 'run2'))
    store.applyEvent(event('log', { level: 'info', message: 'stale' }, 2, 'run1'))
    expect(useRunStore.getState().activeRunId).toBe('run2')
    expect(useRunStore.getState().logs.some((l) => l.message === 'stale')).toBe(false)
  })

  it('keeps log lines, and caps them', () => {
    const store = useRunStore.getState()
    for (let i = 1; i <= 600; i += 1) {
      store.applyEvent(event('log', { level: 'info', message: `line ${i}` }, i))
    }
    const { logs } = useRunStore.getState()
    expect(logs.length).toBeLessThanOrEqual(500)
    // The newest lines are the ones kept.
    expect(logs.at(-1)?.message).toBe('line 600')
  })

  it('marks warnings and errors distinctly', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('log', { level: 'warning', message: 'careful' }, 1))
    store.applyEvent(event('log', { level: 'error', message: 'broken' }, 2))
    expect(useRunStore.getState().logs.map((l) => l.level)).toEqual(['warning', 'error'])
  })

  it('rebuilds the whole view by replaying a recorded timeline', () => {
    const events = [
      event('run_started', { dataset: 'hotpot', prompt_count: 1 }, 1),
      event('phase', { phase: 'system_a', detail: 'baseline' }, 2),
      event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row: row() }, 3),
      event('run_finished', { run_id: 'run1', duration_s: 3 }, 4),
    ]
    useRunStore.getState().replay('run1', events)
    const state = useRunStore.getState()
    expect(state.status).toBe('completed')
    expect(state.rows).toHaveLength(1)
    expect(state.progress.completedPhases).toEqual(['system_a'])
  })

  it('clears everything on reset', () => {
    const store = useRunStore.getState()
    store.applyEvent(event('run_finished', { duration_s: 1 }, 1))
    store.reset()
    const state = useRunStore.getState()
    expect(state.status).toBe('idle')
    expect(state.activeRunId).toBeNull()
    expect(state.logs).toHaveLength(0)
    expect(state.rows).toHaveLength(0)
  })

  it('surfaces a failed start as a failed status', async () => {
    // The store must not throw into the void when the host rejects the request -
    // "a run is already in progress" has to reach the user as text.
    apiMock.startRun.mockRejectedValue(new Error('a run is already in progress'))
    await useRunStore.getState().startRun({ dataset: 'hotpot', systems: ['A'] })
    const state = useRunStore.getState()
    expect(state.status).toBe('failed')
    expect(state.runError).toContain('already in progress')
  })

  it('goes running once the host confirms the spawn', async () => {
    apiMock.startRun.mockResolvedValue({ runId: 'run9', pid: 4242, dryRun: false })
    await useRunStore.getState().startRun({ dataset: 'hotpot', systems: ['A'] })
    const state = useRunStore.getState()
    expect(state.status).toBe('running')
    expect(state.activeRunId).toBe('run9')
  })

  it('reports a cancellation', async () => {
    apiMock.cancelRun.mockResolvedValue('run9')
    await useRunStore.getState().cancelRun()
    expect(useRunStore.getState().status).toBe('cancelled')
  })
})

describe('isTerminal', () => {
  it('is true only for the two end-of-run events', () => {
    expect(isTerminal(event('run_finished', {}))).toBe(true)
    expect(isTerminal(event('run_failed', {}))).toBe(true)
    expect(isTerminal(event('prompt_completed', {}))).toBe(false)
    expect(isTerminal(event('log', {}))).toBe(false)
  })
})