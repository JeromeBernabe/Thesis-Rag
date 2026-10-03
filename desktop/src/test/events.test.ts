import { describe, expect, it } from 'vitest'

import {
  EVENT_TYPES,
  METRICS,
  PHASES,
  SCHEMA_VERSION,
  isEvent,
  isTerminal,
} from '@/types/events'
import { varianceExplained, type ProjectionMeta } from '@/types/models'

describe('event protocol mirror', () => {
  it('declares schema version 1', () => {
    expect(SCHEMA_VERSION).toBe(1)
  })

  it('lists every event type exactly once, in sorted order', () => {
    expect(new Set(EVENT_TYPES).size).toBe(EVENT_TYPES.length)
    const sorted = [...EVENT_TYPES].sort()
    expect([...EVENT_TYPES]).toEqual(sorted)
  })

  it('keeps the two lists in step with the Python source', () => {
    // These three lists must agree. A drift here means the app silently ignores
    // an event, which is worse than a crash because the run still looks fine.
    const expected = [
      'decision',
      'embedding',
      'generation',
      'index_progress',
      'log',
      'phase',
      'projection_ready',
      'prompt_completed',
      'prompt_started',
      'ragas',
      'retrieval',
      'reward',
      'run_failed',
      'run_finished',
      'run_started',
      'stats',
      'train_step',
    ]
    expect([...EVENT_TYPES]).toEqual(expected)
  })

  it('lists phases in execution order', () => {
    expect(PHASES).toEqual([
      'preflight',
      'index',
      'projection',
      'system_a',
      'system_b_train',
      'system_b_infer',
      'stats',
      'done',
    ])
  })

  it('narrows an event to a payload type', () => {
    const event = {
      v: 1,
      seq: 3,
      ts_ms: 1,
      run_id: 'r',
      type: 'log',
      data: { level: 'info', message: 'hi' },
    } as const
    if (isEvent(event, 'log')) {
      // Narrowed: `message` is a string, not `unknown`.
      expect(event.data.message.toUpperCase()).toBe('HI')
    } else {
      throw new Error('expected the guard to narrow')
    }
    expect(isEvent(event, 'phase')).toBe(false)
  })

  it('treats only the two end-of-run events as terminal', () => {
    const base = { v: 1, seq: 1, ts_ms: 1, run_id: 'r', data: {} }
    expect(isTerminal({ ...base, type: 'run_finished' })).toBe(true)
    expect(isTerminal({ ...base, type: 'run_failed' })).toBe(true)
    expect(isTerminal({ ...base, type: 'stats' })).toBe(false)
  })
})

describe('metrics', () => {
  it('are the three the judge produces', () => {
    expect(METRICS).toEqual(['faithfulness', 'answer_relevancy', 'context_recall'])
  })
})

describe('varianceExplained', () => {
  // Tuples rather than arrays: the sidecar always writes exactly three axes, and a
  // bounds object of the wrong arity should not typecheck.
  const base: ProjectionMeta = {
    dataset: 'hotpot',
    collection: 'hotpot',
    n_points: 10,
    dim: 768,
    components: [],
    mean: [],
    ids: [],
    bounds: {
      min: [0, 0, 0],
      max: [1, 1, 1],
    },
    explained_variance: [9, 4, 1],
    explained_variance_ratio: [0.5, 0.25, 0.1],
    source_count: 100,
  }

  it('sums the per-component ratios', () => {
    expect(varianceExplained(base)).toBeCloseTo(0.85)
  })

  it('is null when the sidecar reported no variance', () => {
    // A sampled projection writes zeros; reporting 0% would claim the three axes
    // explain nothing, which is a different and wrong statement.
    expect(varianceExplained({ ...base, explained_variance_ratio: null })).toBeNull()
    expect(varianceExplained({ ...base, explained_variance_ratio: [] })).toBeNull()
    expect(varianceExplained({ ...base, explained_variance_ratio: [0, 0, 0] })).toBeNull()
  })
})