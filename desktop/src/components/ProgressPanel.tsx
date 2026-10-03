/**
 * Phase checklist and counters for the active run.
 *
 * Shows the phases as a sequence rather than a spinner because a run has eight
 * of them and several take minutes; knowing which one is running is most of what
 * the user wants while waiting.
 */

import { type Phase } from '@/types/events'
import { useRunStore } from '@/store/runStore'
import { Panel, PanelHeader, ProgressBar, StatTile } from '@/components/ui'
import { useElapsedSeconds } from '@/hooks/useElapsedSeconds'
import { fmtDuration } from '@/lib/format'

export function ProgressPanel({ phases }: { phases: readonly Phase[] }) {
  const status = useRunStore((s) => s.status)
  const progress = useRunStore((s) => s.progress)

  const activeIndex = progress.phase ? phases.indexOf(progress.phase) : -1
  const done = activeIndex < 0 ? progress.completedPhases.length : activeIndex
  const elapsed = useElapsedSeconds(status === 'running', progress.startedAt)

  const systems = Object.keys(progress.promptsDone)
  const promptsTarget = progress.promptsTotal
  const promptsFrac =
    promptsTarget > 0
      ? Math.min(
          1,
          systems.reduce((sum, system) => sum + (progress.promptsDone[system] ?? 0), 0) /
            (promptsTarget * Math.max(1, systems.length)),
        )
      : null

  return (
    <Panel>
      <PanelHeader
        title={status === 'idle' ? 'Progress' : `Progress - ${status}`}
        subtitle={progress.phaseDetail || 'Waiting for a run'}
        actions={
          <span className="text-ink-faint tnum text-xs">{fmtDuration(elapsed)}</span>
        }
      />
      <div className="p-3">
        <ol className="mb-3 flex flex-wrap gap-1.5">
          {phases.map((phase, index) => {
            const isDone = index < activeIndex || (activeIndex === -1 && progress.completedPhases.includes(phase))
            const isCurrent = index === activeIndex && progress.completedPhases.at(-1) !== phase
            return (
              <li
                key={phase}
                aria-current={isCurrent ? 'step' : undefined}
                className={[
                  'rounded border px-2 py-0.5 font-mono text-[0.7rem]',
                  isDone
                    ? 'border-success/40 bg-success/15 text-success'
                    : isCurrent
                      ? 'border-accent bg-accent/20 text-accent'
                      : 'border-border bg-surface-inset text-ink-faint',
                ].join(' ')}
              >
                {phase}
              </li>
            )
          })}
        </ol>

        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <StatTile
            label="Phases"
            value={`${done}/${phases.length}`}
            hint={progress.phase ?? 'not started'}
          />
          <StatTile
            label="Prompts done"
            value={promptsFrac === null ? '—' : `${Math.round(promptsFrac * 100)}%`}
            hint={promptsTarget > 0 ? `${promptsTarget} per system` : undefined}
          />
          <StatTile label="Judged" value={progress.judgedCount} hint="RAGAS calls" />
          <StatTile
            label="Indexing"
            value={progress.indexTotal > 0 ? `${progress.indexDone}/${progress.indexTotal}` : '—'}
            hint={progress.indexTotal > 0 ? 'documents' : undefined}
          />
        </div>

        {promptsFrac !== null ? (
          <ProgressBar value={promptsFrac} label={`${done} phases`} className="mt-3" />
        ) : null}
      </div>
    </Panel>
  )
}