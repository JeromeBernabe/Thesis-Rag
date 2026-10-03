import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async () => (await import('@/test/apiMock')).apiMock)

import { APP_INFO, apiMock, resetApiMock } from '@/test/apiMock'
import { useRunStore } from '@/store/runStore'
import { SCHEMA_VERSION, type RunEvent } from '@/types/events'
import { RunPage } from '@/pages/RunPage'
import { EventConsole } from '@/components/EventConsole'
import { ProgressPanel } from '@/components/ProgressPanel'
import { LivePromptTable } from '@/components/LivePromptTable'
import { PHASES } from '@/types/events'

function event(type: string, data: Record<string, unknown>, seq = 1): RunEvent {
  return { v: SCHEMA_VERSION, seq, ts_ms: 1000 + seq, run_id: 'run1', type, data }
}

/**
 * Queue events and settle them before rendering.
 *
 * The store folds queued events into one update per frame, so `applyEvent` on its
 * own has not reached the state these components read.
 */
function apply(...events: RunEvent[]): void {
  const store = useRunStore.getState()
  act(() => {
    for (const event of events) store.applyEvent(event)
    store.flushEvents()
  })
}

describe('RunPage', () => {
  beforeEach(() => {
    resetApiMock()
    useRunStore.getState().reset()
    useRunStore.getState().setAppInfo(APP_INFO)
  })

  it('offers every dataset the host reports', () => {
    render(<RunPage />)
    const select = screen.getByLabelText('Dataset') as HTMLSelectElement
    expect([...select.options].map((o) => o.value)).toEqual(APP_INFO.datasets)
  })

  it('starts a run with the chosen settings', async () => {
    const user = userEvent.setup()
    apiMock.startRun.mockResolvedValue({ runId: 'run7', pid: 1, dryRun: false })
    render(<RunPage />)

    await user.selectOptions(screen.getByLabelText('Dataset'), 'fintech')
    const limit = screen.getByLabelText('Prompts')
    await user.clear(limit)
    await user.type(limit, '5')
    await user.click(screen.getByRole('button', { name: 'Start run' }))

    expect(apiMock.startRun).toHaveBeenCalledWith({
      dataset: 'fintech',
      systems: ['A', 'B'],
      limit: 5,
      seed: 42,
      noJudge: true,
      dryRun: false,
      buildPrompts: false,
    })
  })

  it('keeps at least one system selected', async () => {
    const user = userEvent.setup()
    render(<RunPage />)
    // Both start selected. Deselect the baseline, leaving only the DQN; trying to
    // deselect that too must be refused, since a run with neither is not a run.
    await user.click(screen.getByRole('button', { name: /Baseline/ }))
    await user.click(screen.getByRole('button', { name: /DQN/ }))

    apiMock.startRun.mockResolvedValue({ runId: 'run7', pid: 1, dryRun: false })
    await user.click(screen.getByRole('button', { name: 'Start run' }))
    expect(apiMock.startRun).toHaveBeenCalledWith(expect.objectContaining({ systems: ['B'] }))
  })

  it('adds a system back after deselecting it', async () => {
    const user = userEvent.setup()
    render(<RunPage />)
    await user.click(screen.getByRole('button', { name: /DQN/ }))
    apiMock.startRun.mockResolvedValue({ runId: 'run7', pid: 1, dryRun: false })
    await user.click(screen.getByRole('button', { name: 'Start run' }))
    expect(apiMock.startRun).toHaveBeenCalledWith(expect.objectContaining({ systems: ['A'] }))
  })

  it('warns that skipping the judge leaves the metrics empty', () => {
    render(<RunPage />)
    // This is the most consequential default in the form, so it is stated plainly.
    expect(screen.getByText(/the judge runs 80-190s per prompt/i)).toBeInTheDocument()
  })

  it('offers cancel instead of start while a run is in progress', () => {
    useRunStore.setState({ status: 'running', activeRunId: 'run1' })
    render(<RunPage />)
    expect(screen.getByRole('button', { name: 'Cancel run' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start run' })).not.toBeInTheDocument()
  })

  it('shows the error when the host refuses to start', () => {
    useRunStore.setState({ status: 'failed', runError: 'a run is already in progress' })
    render(<RunPage />)
    expect(screen.getByRole('alert')).toHaveTextContent('a run is already in progress')
  })
})

describe('EventConsole', () => {
  beforeEach(() => {
    useRunStore.getState().reset()
  })

  it('says it is waiting before anything arrives', () => {
    render(<EventConsole />)
    expect(screen.getByText(/waiting for events/i)).toBeInTheDocument()
  })

  it('renders log lines in sequence with their level', () => {
    apply(
      event('log', { level: 'info', message: 'hotpot: using 30000 documents' }, 1),
      event('log', { level: 'error', message: 'ollama unreachable' }, 2),
    )
    render(<EventConsole />)
    expect(screen.getByText('hotpot: using 30000 documents')).toBeInTheDocument()
    expect(screen.getByText('ollama unreachable')).toBeInTheDocument()
  })

  it('renders a non-log event as a timeline entry', () => {
    apply(event('retrieval', { system: 'A', index: 0, prompt_id: 'p1', k: 3 }, 1))
    render(<EventConsole />)
    expect(screen.getByText(/A retrieved k=3/)).toBeInTheDocument()
  })

  it('keeps embedding noise out of the console', () => {
    // Embeddings fire per chunk; showing them would bury everything else.
    apply(event('embedding', { system: 'A', time_s: 0.01 }, 1))
    render(<EventConsole />)
    expect(screen.getByText(/waiting for events/i)).toBeInTheDocument()
  })
})

describe('ProgressPanel', () => {
  beforeEach(() => {
    useRunStore.getState().reset()
  })

  it('lists every phase up front so the sequence is visible', () => {
    render(<ProgressPanel phases={PHASES} />)
    for (const phase of PHASES) {
      expect(screen.getByText(phase)).toBeInTheDocument()
    }
  })

  it('marks phases already passed', () => {
    apply(
      event('phase', { phase: 'preflight', detail: 'checking' }, 1),
      event('phase', { phase: 'system_a', detail: 'baseline' }, 2),
    )
    render(<ProgressPanel phases={PHASES} />)
    const done = screen.getByText('preflight').closest('li')
    expect(done?.className).toContain('text-success')
  })

  it('keeps the elapsed clock moving while the sidecar is silent', async () => {
    // A run can spend minutes inside one phase without emitting anything. The
    // clock used to read `Date.now()` during render, so it froze for the whole
    // silent stretch and only jumped when some unrelated event landed.
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
      apply(
        event('run_started', { dataset: 'hotpot' }, 1),
        event('phase', { phase: 'preflight', detail: 'checking' }, 2),
      )

      render(<ProgressPanel phases={PHASES} />)
      const clock = () => screen.getByText(/^(\d+ ms|\d+(\.\d)? s|\d+m \d+s|\d+h \d+m)$/)
      expect(clock().textContent).toBe('0 ms')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(65_000)
      })

      expect(clock().textContent).toBe('1m 5s')
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not run a clock when nothing is running', () => {
    vi.useFakeTimers()
    try {
      const setInterval = vi.spyOn(globalThis, 'setInterval')
      apply(
        event('run_started', { dataset: 'hotpot' }, 1),
        event('run_finished', { status: 'completed' }, 2),
      )
      render(<ProgressPanel phases={PHASES} />)
      expect(setInterval).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('LivePromptTable', () => {
  beforeEach(() => {
    useRunStore.getState().reset()
  })

  it('is empty before any prompt finishes', () => {
    render(<LivePromptTable />)
    expect(screen.getByText('No prompts yet')).toBeInTheDocument()
  })

  it('shows the two systems side by side for one question', () => {
    const row = {
      system: 'A',
      prompt_id: 'p1',
      phase: 'system_a',
      question: 'Who won?',
      ground_truth: 'Samuel Osei Kuffour',
      answer: 'Samuel Kuffour.',
      retrieved_k: 3,
      retrieved_ids: ['doc-a'],
      retrieved_distances: [0.2],
      faithfulness: 0.9,
      answer_relevancy: 0.8,
      context_recall: 0.7,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
      judge_prompt_tokens: null,
      judge_completion_tokens: null,
      embedding_time_s: null,
      retrieval_time_s: null,
      generation_time_s: null,
      judge_time_s: null,
      total_time_s: null,
    }
    apply(
      event('prompt_completed', { system: 'A', index: 0, prompt_id: 'p1', k: 3, row }, 1),
      event('prompt_completed', { system: 'B', index: 0, prompt_id: 'p1', k: 4, row: { ...row, system: 'B', retrieved_k: 4, answer: 'Kuffour' } }, 2),
    )

    render(<LivePromptTable />)
    expect(screen.getByText('Who won?')).toBeInTheDocument()
    expect(screen.getByText('Samuel Kuffour.')).toBeInTheDocument()
    expect(screen.getByText('Kuffour')).toBeInTheDocument()
    expect(screen.getByText(/2 rows across 1 prompts/)).toBeInTheDocument()
  })

  // The filter offers all three metrics, so a column per metric has to exist for
  // each system. This is what catches a metric that is filtered on but never drawn.
  it('renders a column per system for each of the three metrics', () => {
    const base = {
      prompt_id: 'p1',
      phase: 'system_a',
      question: 'Who won?',
      ground_truth: 'Samuel Osei Kuffour',
      retrieved_ids: ['doc-a'],
      retrieved_distances: [0.2],
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
      judge_prompt_tokens: null,
      judge_completion_tokens: null,
      embedding_time_s: null,
      retrieval_time_s: null,
      generation_time_s: null,
      judge_time_s: null,
      total_time_s: null,
    }
    apply(
      event(
        'prompt_completed',
        {
          system: 'A',
          index: 0,
          prompt_id: 'p1',
          k: 3,
          row: {
            ...base,
            system: 'A',
            answer: 'A answer',
            retrieved_k: 3,
            faithfulness: 0.91,
            answer_relevancy: 0.72,
            context_recall: 0.53,
          },
        },
        1,
      ),
      event(
        'prompt_completed',
        {
          system: 'B',
          index: 0,
          prompt_id: 'p1',
          k: 4,
          row: {
            ...base,
            system: 'B',
            answer: 'B answer',
            retrieved_k: 4,
            faithfulness: 0.34,
            answer_relevancy: 0.45,
            context_recall: 0.56,
          },
        },
        2,
      ),
    )

    render(<LivePromptTable />)

    for (const label of ['Faith.', 'Relev.', 'Recall']) {
      expect(screen.getByText(`A ${label}`)).toBeInTheDocument()
      expect(screen.getByText(`B ${label}`)).toBeInTheDocument()
    }

    // Distinct per system and per metric, so each cell can be asserted on its own.
    for (const value of ['0.91', '0.72', '0.53', '0.34', '0.45', '0.56']) {
      expect(screen.getByText(value)).toBeInTheDocument()
    }
  })
})
