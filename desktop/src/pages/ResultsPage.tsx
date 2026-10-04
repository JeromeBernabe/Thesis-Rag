/**
 * Results page: the analytical view of one run.
 *
 * Reads everything in a single `get_run_detail` call, deliberately. Four separate
 * commands would let the page render a comparison chart built from statistics
 * while the per-prompt table behind it is still loading, which reads as a bug.
 *
 * Layout is metric-first: the summary tiles and comparison chart answer "did it
 * work", the per-metric distributions answer "how", and the 3D views sit below
 * because they are exploratory rather than summary.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import * as api from '@/lib/api'
import { describe } from '@/store/runStore'
import {
  METRICS,
  METRIC_LABELS,
  METRIC_SHORT,
  type StatsPayload,
} from '@/types/events'
import type { PromptRow, RunDetail } from '@/types/models'
import { fmtDelta, fmtDuration, fmtInt, fmtNum, fmtPValue, fmtStat, kValues } from '@/lib/format'
import { Button, EmptyState, Panel, PanelHeader, Select, StatTile, SystemDot , PageTitle } from '@/components/ui'
import { ACCENT, AXIS, ChartFrame, GRID, K_SERIES, MUTED, SERIES, TOOLTIP } from '@/components/charts/ChartFrame'
import { ProjectionView } from '@/components/three/ProjectionView'

export function ResultsPage() {
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof api.listRuns>>>([])
  const [runId, setRunId] = useState<string>('')
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // Refresh the picker when the page opens so a run that just finished is offered.
  useEffect(() => {
    void api
      .listRuns()
      .then((list) => {
        setRuns(list)
        setRunId((current) => current || list[0]?.run_id || '')
      })
      .catch((e: unknown) => setError(describe(e)))
  }, [])

  // Importing the committed CSVs is the only way the historical experiments
  // reach this page, and the only way to compare a new pipeline against them.
  // It was reachable from the command layer and the API wrapper with nothing
  // calling it, so the feature existed only in tests.
  const importThesis = useCallback(() => {
    setImporting(true)
    setError(null)
    setNotice(null)
    void api
      .importLegacy()
      .then((report) => {
        setImporting(false)
        setNotice(
          `imported ${report.runs.length} run(s), ${fmtInt(report.promptRows)} prompt ` +
            `row(s) and ${fmtInt(report.trainingRows)} training row(s)` +
            (report.skipped.length ? `; skipped ${report.skipped.join(', ')}` : ''),
        )
        return api.listRuns().then((list) => {
          setRuns(list)
          // Land on something new if this import added any.
          if (report.runs.length > 0) setRunId(report.runs[0])
        })
      })
      .catch((e: unknown) => {
        setImporting(false)
        setError(describe(e))
      })
  }, [])

  const load = useCallback((id: string) => {
    if (!id) {
      setDetail(null)
      return
    }
    setLoading(true)
    setError(null)
    void api
      .getRunDetail(id)
      .then((next) => {
        setDetail(next)
        setLoading(false)
      })
      .catch((e: unknown) => {
        setError(describe(e))
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    load(runId)
  }, [runId, load])

  const stats = detail?.stats ?? null
  const systems = detail?.run.systems ?? []

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <PageTitle>Results</PageTitle>
      <Panel>
        <div className="flex flex-wrap items-center gap-3 p-3">
          <Select
            aria-label="Run"
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            className="w-80"
          >
            {runs.length === 0 ? <option value="">no runs yet</option> : null}
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.dataset} - {run.status}
                {run.dry_run ? ' (dry)' : ''} - {run.run_id.slice(0, 8)}
              </option>
            ))}
          </Select>

          {detail ? (
            <>
              <span className="text-ink-faint text-xs">
                {systems.map((s, i) => (
                  <span key={s} className="mr-2 inline-flex items-center gap-1">
                    {i > 0 ? '' : null}
                    <SystemDot system={s} /> {s}
                  </span>
                ))}
              </span>
              <span className="text-ink-faint text-xs">
                {detail.run.prompt_count} prompts - {detail.run.corpus_count ?? '?'} docs
              </span>
              <span className="text-ink-faint text-xs">{fmtDuration(detail.run.duration_s)}</span>
              {detail.run.no_judge ? (
                <span className="text-warning text-xs">judge skipped</span>
              ) : null}
              {detail.run.dry_run ? (
                <span className="text-warning text-xs">dry run</span>
              ) : null}
              {loading ? <span className="text-ink-faint text-xs">loading…</span> : null}
            </>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            <Button
              size="sm"
              onClick={importThesis}
              disabled={importing}
              title="Import the committed CSVs under results/ so the earlier experiments appear here"
            >
              {importing ? 'Importing…' : 'Import thesis CSVs'}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                if (detail) void api.deleteRun(detail.run.run_id).then(() => api.listRuns().then(setRuns))
              }}
              disabled={!detail}
              title="Delete this run and its rows"
            >
              Delete run
            </Button>
          </div>
        </div>
      </Panel>

      {notice ? <Panel className="text-ink-faint p-3 text-xs">{notice}</Panel> : null}

      {error ? (
        <Panel className="text-danger p-4 text-sm">{error}</Panel>
      ) : !detail ? (
        <Panel className="flex min-h-64 items-center justify-center">
          <EmptyState
            title="No run selected"
            detail="Pick a run above. Start one from the Run page if there is nothing to look at yet."
          />
        </Panel>
      ) : (
        <>
          <SummaryTiles detail={detail} stats={stats} />
          {stats ? <ComparisonChart stats={stats} /> : <NoStatsNote noJudge={detail.run.no_judge} />}
          <MetricDistributions stats={stats} />
          {detail.run.dataset ? <TrainingCurves rows={detail.trainingRows} stats={stats} /> : null}
          <KDistribution stats={stats} />
          <PromptTable rows={detail.promptRows} />
          <ProjectionView dataset={detail.run.dataset} rows={detail.promptRows} />
        </>
      )}
    </div>
  )
}

function NoStatsNote({ noJudge }: { noJudge: boolean }) {
  return (
    <Panel>
      <EmptyState
        title="No statistics stored"
        detail={
          noJudge
            ? 'This run skipped the judge, so there are no metric statistics to compare. Re-run with the judge enabled to fill the Results page.'
            : 'The run has not reached its statistics phase.'
        }
      />
    </Panel>
  )
}

/** Headline numbers: sample size, and the mean of each metric per system. */
function SummaryTiles({ detail, stats }: { detail: RunDetail; stats: StatsPayload | null }) {
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      <StatTile
        label="Rows stored"
        value={fmtInt(detail.promptRows.length)}
        hint={`${detail.trainingRows.length} training steps`}
      />
      <StatTile label="Paired prompts" value={fmtInt(stats?.paired_prompt_count)} hint="A and B both answered" />
      <StatTile
        label="Mean k (B)"
        value={fmtNum(stats?.per_system?.B?.mean_k, 2)}
        hint={stats ? `A used ${fmtNum(stats.per_system?.A?.mean_k, 2)}` : undefined}
      />
      <StatTile
        label="Duration"
        value={fmtDuration(detail.run.duration_s)}
        hint={detail.run.dry_run ? 'dry run' : detail.run.no_judge ? 'judge off' : 'judged'}
      />
    </div>
  )
}

/** Grouped bars: mean metric score per system. */
/**
 * A tooltip formatter for a numeric axis.
 *
 * Typed as `unknown` on purpose: Recharts passes a `ValueType` that may be
 * undefined, and every formatter here funnels through `fmtNum`, which renders an
 * absent value as a dash rather than as `NaN`.
 */
const num = (digits: number) => (value: unknown) => fmtNum(value as number | null | undefined, digits)

/** One data point; a metric the judge skipped is `null`, and charts render a gap. */
type Point = Record<string, number | string | null>

function ComparisonChart({ stats }: { stats: StatsPayload }) {
  const systems = (Object.keys(stats.per_system) as (keyof typeof stats.per_system)[]).sort()

  const data: Point[] = METRICS.map((metric) => {
    const point: Point = { metric: METRIC_SHORT[metric], full: METRIC_LABELS[metric] }
    for (const system of systems) {
      point[system] = stats.per_system[system]?.metrics?.[metric]?.mean ?? null
    }
    return point
  })

  const hasData = systems.some((system) => stats.per_system[system]?.metrics?.faithfulness?.mean != null)

  return (
    <Panel>
      <PanelHeader
        title="Metric means by system"
        subtitle="Mean over scored prompts. Bars absent means the judge produced nothing."
      />
      <div className="p-3">
        <ChartFrame hasData={hasData} emptyTitle="No metrics" emptyDetail="This run skipped the judge.">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid {...GRID} vertical={false} />
            <XAxis dataKey="metric" {...AXIS} />
            <YAxis domain={[0, 1]} {...AXIS} />
            <Tooltip {...TOOLTIP} formatter={num(3)} />
            {systems.map((system) => (
              <Bar key={system} dataKey={system} fill={SERIES[system]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ChartFrame>
      </div>
    </Panel>
  )
}

/** One panel per metric: both systems' distributions on one axis. */
function MetricDistributions({ stats }: { stats: StatsPayload | null }) {
  const systems = stats ? (Object.keys(stats.per_system) as ('A' | 'B')[]).sort() : []
  if (!stats) return null

  return (
    <div className="grid grid-cols-1 gap-2 xl:grid-cols-3">
      {METRICS.map((metric) => {
        const test = stats.comparison[metric]
        const hasData = systems.some((s) => (stats.per_system[s]?.metrics?.[metric]?.n ?? 0) > 0)
        return (
          <Panel key={metric}>
            <PanelHeader
              title={METRIC_LABELS[metric]}
              subtitle={
                hasData
                  ? `paired n=${test?.n ?? 0}`
                  : 'not scored in this run'
              }
            />
            <div className="p-3">
              <ChartFrame hasData={hasData} height={180} emptyTitle="Not scored">
                <BarChart
                  data={systems.map((system) => ({
                    system,
                    value: stats.per_system[system]?.metrics?.[metric]?.mean ?? null,
                    n: stats.per_system[system]?.metrics?.[metric]?.n ?? 0,
                  }))}
                  margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                >
                  <CartesianGrid {...GRID} vertical={false} />
                  <XAxis dataKey="system" {...AXIS} />
                  <YAxis domain={[0, 1]} {...AXIS} />
                  <Tooltip {...TOOLTIP} formatter={num(3)} />
                  {/* One `<Bar>` reading `value`, with a `<BarCell>` per system to
                      colour them. A `<Bar>` per system would need a `dataKey` per
                      system, and the rows have a single `value` column, so those
                      bars would silently render nothing. */}
                  <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {systems.map((system) => (
                      <Cell
                        key={system}
                        fill={SERIES[system]}
                        // A system that was not scored gets an empty cell, so the
                        // axis stays shared and comparable across the three panels
                        // instead of pretending the metric was zero.
                        fillOpacity={stats.per_system[system]?.metrics?.[metric]?.mean == null ? 0 : 1}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ChartFrame>
              {hasData ? (
                <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5 text-xs">
                  {systems.map((system) => (
                    <div key={system} className="flex items-center gap-1.5">
                      <dt className="text-ink-faint flex items-center gap-1">
                        <SystemDot system={system} />
                      </dt>
                      <dd className="tnum text-ink">
                        {fmtNum(stats.per_system[system]?.metrics?.[metric]?.mean, 3)}
                        <span className="text-ink-faint">
                          {' '}
                          ± {fmtNum(stats.per_system[system]?.metrics?.[metric]?.sem, 3)}
                        </span>
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {hasData && test ? (
                <p className="text-ink-faint mt-2 border-t border-border/50 pt-2 text-xs">
                  Δ {fmtDelta(test.mean_diff)} · t = {fmtStat(test.t_stat)} · p = {fmtPValue(test.p_two_tailed)}
                  {test.significant_at_alpha ? (
                    <span className="text-success"> · significant</span>
                  ) : (
                    <span> · not significant</span>
                  )}
                </p>
              ) : null}
            </div>
          </Panel>
        )
      })}
    </div>
  )
}

/**
 * The k a greedy policy would choose, from its value estimates.
 *
 * Returns `null` for an all-null Q-vector rather than defaulting to k=1, because
 * a training step before the network has been updated genuinely has no preferred
 * action and drawing one would invent data.
 */
/** The retrieval-k actions the DQN chooses between, in Q-value index order. */
const Q_ACTIONS = [1, 2, 3, 4, 5] as const

/**
 * Which action the greedy policy would pick: the argmax of the Q-values.
 *
 * Returns a k (1-based) rather than a zero-based index, because the index is an
 * implementation detail of the array and every chart and label wants the k.
 */
function argmaxAction(qValues: (number | null)[] | null | undefined): number | null {
  if (!qValues || qValues.length === 0) return null
  let bestIndex = -1
  let bestValue = -Infinity
  qValues.forEach((value, i) => {
    if (value === null || value === undefined) return
    if (value > bestValue) {
      bestValue = value
      bestIndex = i
    }
  })
  return bestIndex === -1 ? null : bestIndex + 1
}

/** Reward, loss, epsilon and the Q-value curve over training steps. */
function TrainingCurves({ rows, stats }: { rows: RunDetail['trainingRows']; stats: StatsPayload | null }) {
  /**
   * Q-values become one series per action so they can be read against each other.
   *
   * A single stacked band would hide the comparison that matters: which k the
   * network rates highest, and whether that changes as it learns. `q_values` is
   * index-aligned with k, so `q1` is the value for k=1.
   */
  const chartData = rows.map((row) => {
    const point: Record<string, number | null> = {
      step: row.step,
      reward: row.reward,
      loss: row.loss,
      epsilon: row.epsilon,
      k: row.k,
      argmax_k: argmaxAction(row.q_values),
    }
    for (let i = 0; i < Q_ACTIONS.length; i++) {
      point[`q${Q_ACTIONS[i]}`] = row.q_values?.[i] ?? null
    }
    return point
  })

  return (
    <Panel>
      <PanelHeader
        title="DQN training"
        subtitle={
          stats?.training
            ? `${stats.training.steps} steps, final ε ${fmtNum(stats.training.final_epsilon, 3)}`
            : `${rows.length} steps`
        }
      />
      <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
        <div>
          <p className="text-ink-faint mb-1 text-xs">Reward per step</p>
          <ChartFrame hasData={chartData.some((p) => p.reward !== null)} height={170}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid {...GRID} vertical={false} />
              <XAxis dataKey="step" {...AXIS} />
              <YAxis domain={[0, 1]} {...AXIS} />
              <Tooltip {...TOOLTIP} formatter={num(3)} />
              <Line type="monotone" dataKey="reward" stroke={ACCENT} dot={false} strokeWidth={1.5} />
            </LineChart>
          </ChartFrame>
        </div>
        <div>
          <p className="text-ink-faint mb-1 text-xs">Loss per step</p>
          {/* Not domain-locked: loss is a regression error whose scale depends on
              the reward distribution, so a fixed axis would clip or flatten it. */}
          <ChartFrame hasData={chartData.some((p) => p.loss !== null)} height={170}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid {...GRID} vertical={false} />
              <XAxis dataKey="step" {...AXIS} />
              <YAxis {...AXIS} />
              <Tooltip {...TOOLTIP} formatter={num(4)} />
              <Line type="monotone" dataKey="loss" stroke={SERIES.A} dot={false} strokeWidth={1.5} />
            </LineChart>
          </ChartFrame>
        </div>
        <div>
          <p className="text-ink-faint mb-1 text-xs">Exploration ε and the k the greedy policy would pick</p>
          <ChartFrame hasData={chartData.some((p) => p.epsilon !== null)} height={170}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid {...GRID} vertical={false} />
              <XAxis dataKey="step" {...AXIS} />
              {/* ε and k share an axis because both are small counts/ratios in
                  the same 0..5 band, and dual axes here would mislead. */}
              <YAxis domain={[0, 5]} {...AXIS} />
              <Tooltip {...TOOLTIP} formatter={num(2)} />
              <Line type="monotone" dataKey="epsilon" stroke={MUTED} dot={false} strokeWidth={1} />
              <Line type="stepAfter" dataKey="argmax_k" stroke={SERIES.B} dot={false} strokeWidth={1.5} />
              <ReferenceLine y={3} stroke={MUTED} strokeDasharray="3 3" />
            </LineChart>
          </ChartFrame>
        </div>
        <div>
          <p className="text-ink-faint mb-1 text-xs">Q-value per action (k)</p>
          <ChartFrame hasData={chartData.some((p) => p.q1 !== null)} height={170}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid {...GRID} vertical={false} />
              <XAxis dataKey="step" {...AXIS} />
              <YAxis {...AXIS} />
              <Tooltip {...TOOLTIP} formatter={num(3)} />
              {Q_ACTIONS.map((k, i) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={`q${k}`}
                  stroke={K_SERIES[i]}
                  dot={false}
                  strokeWidth={1.25}
                />
              ))}
            </LineChart>
          </ChartFrame>
        </div>
      </div>
    </Panel>
  )
}

/** How often each k was chosen. */
function KDistribution({ stats }: { stats: StatsPayload | null }) {
  // Derived inside the memo rather than as a separate value: `Object.keys(...)`
  // allocates a new array every render, so as a dependency it would invalidate the
  // memo on every single render and the caching would buy nothing.
  const { systems, data } = useMemo(() => {
    const keys = stats ? (Object.keys(stats.per_system) as ('A' | 'B')[]).sort() : []
    const all = new Set<number>()
    for (const system of keys) {
      for (const k of kValues(stats!.per_system[system]?.k_distribution)) all.add(k)
    }
    const sorted = [...all].sort((a, b) => a - b)
    const points: Point[] = sorted.map((k) => {
      const point: Point = { k: String(k) }
      for (const system of keys) {
        point[system] = stats!.per_system[system]?.k_distribution?.[String(k)] ?? 0
      }
      return point
    })
    return { systems: keys, data: points }
  }, [stats])

  return (
    <Panel>
      <PanelHeader
        title="k distribution"
        subtitle="How often the system chose each context size"
      />
      <div className="p-3">
        <ChartFrame hasData={data.length > 0} height={200} emptyTitle="No k choices recorded">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid {...GRID} vertical={false} />
            <XAxis dataKey="k" {...AXIS} />
            <YAxis {...AXIS} allowDecimals={false} />
            <Tooltip {...TOOLTIP} />
            {systems.map((system) => (
              <Bar key={system} dataKey={system} fill={SERIES[system]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ChartFrame>
      </div>
    </Panel>
  )
}

/** Every stored row, with the two systems side by side. */
function PromptTable({ rows }: { rows: PromptRow[] }) {
  return (
    <Panel>
      <PanelHeader title="Prompts" subtitle={`${rows.length} stored rows`} />
      <div className="max-h-96 overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="bg-surface-inset text-ink-faint sticky top-0">
            <tr>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">#</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">System</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">k</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">Faith.</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">Relev.</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">Recall</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">Time</th>
              <th className="border-border border-b px-2 py-1.5 text-left font-medium">Answer</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.system}-${row.prompt_id}`}
                className="border-border/40 hover:bg-surface-inset/60 border-b"
              >
                <td className="text-ink-faint tnum px-2 py-1.5">
                  {row.prompt_index === null ? '—' : row.prompt_index + 1}
                </td>
                <td className="px-2 py-1.5">
                  <span className="flex items-center gap-1.5">
                    <SystemDot system={row.system} />
                    {row.system}
                  </span>
                </td>
                <td className="tnum px-2 py-1.5">{row.retrieved_k ?? '—'}</td>
                <td className="tnum px-2 py-1.5">{fmtNum(row.faithfulness, 2)}</td>
                <td className="tnum px-2 py-1.5">{fmtNum(row.answer_relevancy, 2)}</td>
                <td className="tnum px-2 py-1.5">{fmtNum(row.context_recall, 2)}</td>
                <td className="text-ink-muted tnum px-2 py-1.5">{fmtDuration(row.total_time_s)}</td>
                <td className="max-w-sm px-2 py-1.5">
                  <div className="line-clamp-2">{row.answer}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
