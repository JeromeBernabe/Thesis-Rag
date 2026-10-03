/**
 * Simulation page: a staged replay of the pipeline.
 *
 * Deliberately deferred rather than wired to a live run. This is the exploratory
 * view - "what happens to a single question" - whereas the Run page shows what
 * happened to fifty. Binding the two would mean one page trying to be both a
 * monitor and a teaching tool.
 *
 * It reads from the stored rows of a chosen run, so the timings and answers it
 * shows are real measurements rather than invented numbers.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import * as api from '@/lib/api'
import { describe } from '@/store/runStore'
import { fmtDuration, fmtNum } from '@/lib/format'
import { Button, EmptyState, Panel, PanelHeader, Select, StatTile, SystemDot , PageTitle } from '@/components/ui'
import { PipelineView, STAGES, type StageTimings } from '@/components/three/PipelineView'
import type { PromptRow, RunDetail } from '@/types/models'

export function SimulationPage() {
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof api.listRuns>>>([])
  const [runId, setRunId] = useState('')
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [system, setSystem] = useState<'A' | 'B'>('B')
  const [playing, setPlaying] = useState(true)
  const [stageIndex, setStageIndex] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api
      .listRuns()
      .then((list) => {
        setRuns(list)
        setRunId((current) => current || list[0]?.run_id || '')
      })
      .catch((e: unknown) => setError(describe(e)))
  }, [])

  useEffect(() => {
    if (!runId) {
      setDetail(null)
      return
    }
    let cancelled = false
    setError(null)
    void api
      .getRunDetail(runId)
      .then((next) => {
        if (!cancelled) setDetail(next)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(describe(e))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const rows = useMemo(
    () => (detail?.promptRows ?? []).filter((row) => row.system === system),
    [detail, system],
  )

  /**
   * Fall back to a system the run actually has.
   *
   * An A-only run has no B rows, so holding `B` would show an empty pipeline and a
   * stage list that still claims to include the decision, reward and training
   * stages the baseline never ran. Better to show what exists.
   */
  const hasRowsForSystem = useCallback(
    (candidate: 'A' | 'B') => (detail?.promptRows ?? []).some((row) => row.system === candidate),
    [detail],
  )

  useEffect(() => {
    if (!detail) return
    if (hasRowsForSystem(system)) return
    const fallback = (['A', 'B'] as const).find(hasRowsForSystem)
    if (fallback) setSystem(fallback)
  }, [detail, system, hasRowsForSystem])

  /** Whether the run contains this system at all, for the switcher. */
  const availableSystems = useMemo(() => {
    const declared = detail?.run.systems ?? []
    const fromRows = [...new Set((detail?.promptRows ?? []).map((row) => row.system))]
    return [...new Set([...declared, ...fromRows])].sort()
  }, [detail])

  /** The first prompt of the chosen system, used for the worked example. */
  const example = rows[0] ?? null

  // Per-stage timings from a single row, so the animation reflects real work.
  const timings = useMemo<StageTimings>(() => {
    if (!example) return {}
    return {
      embedding: example.embedding_time_s ?? 0,
      decision: 0,
      retrieval: example.retrieval_time_s ?? 0,
      generation: example.generation_time_s ?? 0,
      judge: example.judge_time_s ?? 0,
      reward: 0,
      training: 0,
    }
  }, [example])

  const stages = system === 'A' ? STAGES.filter((stage) => !stage.bOnly) : STAGES
  const currentStage = stages[Math.min(stageIndex, stages.length - 1)]

  const onStageChange = useCallback((index: number) => setStageIndex(index), [])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <PageTitle>Simulation</PageTitle>
      <Panel>
        <div className="flex flex-wrap items-center gap-3 p-3">
          <Select aria-label="Run" value={runId} onChange={(e) => setRunId(e.target.value)} className="w-80">
            {runs.length === 0 ? <option value="">no runs yet</option> : null}
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.dataset} - {run.run_id.slice(0, 8)}
              </option>
            ))}
          </Select>

          {availableSystems.length > 1 ? (
            <Select
              aria-label="System"
              value={system}
              onChange={(e) => setSystem(e.target.value as 'A' | 'B')}
              className="w-40"
            >
              {availableSystems.map((id) => (
                <option key={id} value={id}>
                  System {id}
                </option>
              ))}
            </Select>
          ) : availableSystems.length === 1 ? (
            // A single-system run gets a label rather than a dead dropdown, so it
            // is clear which system is being replayed and that there is no choice.
            <span className="flex items-center gap-1.5 text-xs">
              <SystemDot system={availableSystems[0]} />
              <span className="text-ink">System {availableSystems[0]}</span>
            </span>
          ) : null}

          <Button size="sm" variant={playing ? 'secondary' : 'primary'} onClick={() => setPlaying((p) => !p)}>
            {playing ? 'Pause' : 'Play'}
          </Button>

          {detail ? (
            <span className="text-ink-faint text-xs">
              {rows.length} prompts for system {system}
            </span>
          ) : null}
        </div>
      </Panel>

      {error ? (
        <Panel className="text-danger p-4 text-sm">{error}</Panel>
      ) : !detail ? (
        <Panel className="flex min-h-64 items-center justify-center">
          <EmptyState
            title="Nothing to simulate"
            detail="Run a benchmark first. The simulation replays one prompt of a real run, so its timings are measured rather than invented."
          />
        </Panel>
      ) : (
        <>
          <Panel>
            <PanelHeader
              title="Pipeline"
              subtitle={`System ${system} - ${stages.length} stages, timed from the first stored prompt`}
              actions={
                <span className="flex items-center gap-1.5 text-xs">
                  <SystemDot system={system} />
                  {example?.phase ?? 'no row'}
                </span>
              }
            />
            <div className="p-3">
              <PipelineView
                system={system}
                timings={timings}
                playing={playing}
                onStageChange={onStageChange}
              />
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_20rem]">
            <Panel>
              <PanelHeader
                title={`Stage ${stages.indexOf(currentStage) + 1}: ${currentStage?.label ?? '—'}`}
                subtitle={currentStage?.detail}
              />
              <div className="flex flex-col gap-3 p-4">
                <div>
                  <p className="text-ink-faint text-xs font-medium">Question</p>
                  <p className="text-sm">{example?.question ?? '—'}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-ink-faint text-xs font-medium">Ground truth</p>
                    <p className="text-ink-muted text-sm">{example?.ground_truth ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-ink-faint text-xs font-medium">k chosen</p>
                    <p className="text-ink-muted text-sm">{example?.retrieved_k ?? '—'}</p>
                  </div>
                </div>
                <div>
                  <p className="text-ink-faint text-xs font-medium">Answer</p>
                  <p className="text-ink-muted text-sm">{example?.answer ?? '—'}</p>
                </div>
                {example?.retrieved_ids?.length ? (
                  <div>
                    <p className="text-ink-faint text-xs font-medium">
                      Retrieved chunks ({example.retrieved_ids.length})
                    </p>
                    <ul className="text-ink-faint mt-1 flex flex-wrap gap-1 font-mono text-[0.7rem]">
                      {example.retrieved_ids.map((id) => (
                        <li key={id} className="border-border bg-surface-inset rounded border px-1.5 py-0.5">
                          {id}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Measured" subtitle="From the stored row" />
              <div className="flex flex-col gap-2 p-3">
                <StatTile label="Retrieval" value={fmtDuration(example?.retrieval_time_s)} />
                <StatTile label="Generation" value={fmtDuration(example?.generation_time_s)} />
                <StatTile label="Judge" value={fmtDuration(example?.judge_time_s)} />
                <StatTile label="Total" value={fmtDuration(example?.total_time_s)} />
                <StatTile label="Faithfulness" value={fmtNum(example?.faithfulness, 3)} />
                <StatTile label="Answer relevancy" value={fmtNum(example?.answer_relevancy, 3)} />
                <StatTile label="Context recall" value={fmtNum(example?.context_recall, 3)} />
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}

/** Re-exported for the Run page's summary, which shows the same stage list. */
export type { PromptRow }
