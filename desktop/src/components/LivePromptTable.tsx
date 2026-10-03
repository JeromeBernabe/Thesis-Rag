/**
 * Prompts completed so far, during a live run.
 *
 * Reads from the store's live rows rather than the database, so it updates
 * without polling. The A and B answers for one question sit next to each other,
 * because the comparison is the point of the experiment.
 */

import { useMemo, useState } from 'react'

import { METRIC_SHORT, METRICS, type SystemId } from '@/types/events'
import { useRunStore } from '@/store/runStore'
import { EmptyState, Panel, PanelHeader, SystemDot } from '@/components/ui'
import { fmtNum } from '@/lib/format'

type MetricFilter = 'all' | (typeof METRICS)[number]

export function LivePromptTable() {
  const rows = useRunStore((s) => s.rows)
  const [filter, setFilter] = useState<MetricFilter>('all')

  const systems = useMemo<SystemId[]>(() => {
    const found = new Set(rows.map((row) => row.system))
    return [...found].sort()
  }, [rows])

  // Group by question so the two systems' answers can be shown side by side.
  const groups = useMemo(() => {
    const byPrompt = new Map<string, typeof rows>()
    for (const row of rows) {
      const list = byPrompt.get(row.prompt_id) ?? []
      list.push(row)
      byPrompt.set(row.prompt_id, list)
    }
    return [...byPrompt.entries()].sort((a, b) => (a[1][0]?.prompt_index ?? 0) - (b[1][0]?.prompt_index ?? 0))
  }, [rows])

  const visible = useMemo(
    () =>
      filter === 'all'
        ? groups
        : groups.filter(([, list]) => list.some((row) => row[filter] !== null)),
    [filter, groups],
  )

  return (
    <Panel className="flex min-h-0 flex-1 flex-col">
      <PanelHeader
        title="Prompts"
        subtitle={`${rows.length} rows across ${groups.length} prompts`}
        actions={
          <select
            aria-label="Filter by metric"
            value={filter}
            onChange={(e) => setFilter(e.target.value as MetricFilter)}
            className="border-border bg-surface-inset text-ink-muted rounded border px-2 py-1 text-xs"
          >
            <option value="all">All prompts</option>
            {METRICS.map((metric) => (
              <option key={metric} value={metric}>
                Judged: {METRIC_SHORT[metric]}
              </option>
            ))}
          </select>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        {visible.length === 0 ? (
          <EmptyState
            title={rows.length === 0 ? 'No prompts yet' : 'No prompts match this filter'}
            detail={
              rows.length === 0
                ? 'Rows appear here as each prompt finishes.'
                : 'The judge has not scored any prompt with this metric yet.'
            }
          />
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead className="bg-surface-inset text-ink-faint sticky top-0">
              <tr>
                <th className="border-border border-b px-2 py-1.5 text-left font-medium">#</th>
                <th className="border-border border-b px-2 py-1.5 text-left font-medium">Question</th>
                {systems.map((system) => (
                  <th key={system} className="border-border border-b px-2 py-1.5 text-left font-medium">
                    <span className="flex items-center gap-1.5">
                      <SystemDot system={system} />
                      {system} k
                    </span>
                  </th>
                ))}
                {systems.map((system) => (
                  <th key={`${system}-m`} className="border-border border-b px-2 py-1.5 text-left font-medium">
                    {system} {METRIC_SHORT.faithfulness}
                  </th>
                ))}
                {systems.map((system) => (
                  <th
                    key={`${system}-answer_relevancy`}
                    className="border-border border-b px-2 py-1.5 text-left font-medium"
                  >
                    {system} {METRIC_SHORT.answer_relevancy}
                  </th>
                ))}
                {systems.map((system) => (
                  <th
                    key={`${system}-context_recall`}
                    className="border-border border-b px-2 py-1.5 text-left font-medium"
                  >
                    {system} {METRIC_SHORT.context_recall}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map(([promptId, list]) => {
                const index = list[0]?.prompt_index
                const question = list.find((row) => row.question)?.question
                return (
                  <tr key={promptId} className="hover:bg-surface-inset/60 border-border/40 border-b align-top">
                    <td className="text-ink-faint tnum px-2 py-1.5">
                      {index === null || index === undefined ? '—' : index + 1}
                    </td>
                    <td className="max-w-md px-2 py-1.5">
                      <div className="line-clamp-2">{question}</div>
                    </td>
                    {systems.map((system) => {
                      const row = list.find((r) => r.system === system)
                      return (
                        <td key={system} className="max-w-xs px-2 py-1.5">
                          {row ? (
                            <>
                              <span className="tnum text-ink-muted">{row.retrieved_k ?? '—'}</span>
                              <div className="text-ink line-clamp-2">{row.answer}</div>
                            </>
                          ) : (
                            <span className="text-ink-faint">pending</span>
                          )}
                        </td>
                      )
                    })}
                    {systems.map((system) => {
                      const row = list.find((r) => r.system === system)
                      return (
                        <td key={`${system}-m`} className="text-ink-muted tnum px-2 py-1.5">
                          {row ? fmtNum(row.faithfulness, 2) : '—'}
                        </td>
                      )
                    })}
                    {systems.map((system) => {
                      const row = list.find((r) => r.system === system)
                      return (
                        <td key={`${system}-answer_relevancy`} className="text-ink-muted tnum px-2 py-1.5">
                          {row ? fmtNum(row.answer_relevancy, 2) : '—'}
                        </td>
                      )
                    })}
                    {systems.map((system) => {
                      const row = list.find((r) => r.system === system)
                      return (
                        <td key={`${system}-context_recall`} className="text-ink-muted tnum px-2 py-1.5">
                          {row ? fmtNum(row.context_recall, 2) : '—'}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  )
}