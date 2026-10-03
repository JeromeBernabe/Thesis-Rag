/**
 * Run page: configure a benchmark, start it, and watch it happen.
 *
 * Split into a form column and a live column because the two have very different
 * update rates: the form is inert during a run, while the console changes on every
 * event. Keeping them separate stops a chatty run from re-rendering the inputs.
 */

import { useMemo, useState } from 'react'

import { PHASES, type SystemId } from '@/types/events'
import { useRunStore } from '@/store/runStore'
import { Button, Checkbox, EmptyState, Input, Label, Panel, PanelHeader, Select , PageTitle } from '@/components/ui'
import { EventConsole } from '@/components/EventConsole'
import { ProgressPanel } from '@/components/ProgressPanel'
import { LivePromptTable } from '@/components/LivePromptTable'

export function RunPage() {
  const appInfo = useRunStore((s) => s.appInfo)
  const hostError = useRunStore((s) => s.hostError)
  const status = useRunStore((s) => s.status)
  const runError = useRunStore((s) => s.runError)
  const activeRunId = useRunStore((s) => s.activeRunId)
  const startRun = useRunStore((s) => s.startRun)
  const cancelRun = useRunStore((s) => s.cancelRun)
  const reset = useRunStore((s) => s.reset)
  const runs = useRunStore((s) => s.runs)

  const [dataset, setDataset] = useState('hotpot')
  const [systems, setSystems] = useState<SystemId[]>(['A', 'B'])
  const [limit, setLimit] = useState(50)
  const [seed, setSeed] = useState(42)
  const [noJudge, setNoJudge] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [buildPrompts, setBuildPrompts] = useState(false)

  const busy = status === 'running' || status === 'starting'
  const datasets = appInfo?.datasets ?? ['hotpot', 'fintech', 'math', 'ragtruth']

  const activeRun = useMemo(
    () => runs.find((run) => run.run_id === activeRunId) ?? null,
    [activeRunId, runs],
  )

  const toggleSystem = (system: SystemId) => {
    setSystems((current) => {
      // At least one system must stay selected: a run with neither is not a run.
      if (current.includes(system)) {
        return current.length === 1 ? current : current.filter((s) => s !== system)
      }
      return [...current, system].sort()
    })
  }

  const submit = () => {
    void startRun({
      dataset,
      systems,
      limit: Number.isFinite(limit) ? limit : null,
      seed: Number.isFinite(seed) ? seed : null,
      noJudge,
      dryRun,
      buildPrompts,
    })
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[22rem_1fr] gap-3 p-3">
      {/* `sr-only` is absolutely positioned, so it adds no grid track. */}
      <PageTitle>Run</PageTitle>
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
        <Panel>
          <PanelHeader title="Configure" subtitle="One run over one dataset" />
          <div className="flex flex-col gap-3 p-4">
            <div>
              <Label htmlFor="dataset">Dataset</Label>
              <Select
                id="dataset"
                value={dataset}
                disabled={busy}
                onChange={(e) => setDataset(e.target.value)}
              >
                {datasets.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
            </div>

            <div>
              <Label>Systems</Label>
              <div className="flex gap-2">
                {(['A', 'B'] as SystemId[]).map((system) => (
                  <button
                    key={system}
                    type="button"
                    disabled={busy}
                    aria-pressed={systems.includes(system)}
                    onClick={() => toggleSystem(system)}
                    className={[
                      'flex flex-1 items-center gap-2 rounded border px-2.5 py-1.5 text-sm',
                      'transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                      systems.includes(system)
                        ? 'border-accent bg-accent/15 text-ink'
                        : 'border-border bg-surface-inset text-ink-muted hover:border-border-strong',
                    ].join(' ')}
                  >
                    <span
                      aria-hidden
                      className={`size-2 rounded-full ${system === 'A' ? 'bg-system-a' : 'bg-system-b'}`}
                    />
                    <span className="flex-1 text-left">
                      {system === 'A' ? 'Baseline' : 'DQN'}
                    </span>
                    <span className="text-ink-faint text-xs">
                      {system === 'A' ? 'fixed k' : 'learned k'}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label htmlFor="limit">Prompts</Label>
                <Input
                  id="limit"
                  type="number"
                  min={1}
                  value={limit}
                  disabled={busy}
                  onChange={(e) => setLimit(Number(e.target.value))}
                />
              </div>
              <div>
                <Label htmlFor="seed">Seed</Label>
                <Input
                  id="seed"
                  type="number"
                  value={seed}
                  disabled={busy}
                  onChange={(e) => setSeed(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="flex flex-col gap-2.5">
              <Checkbox
                label="Skip judge"
                description="Faster, but leaves the three metrics empty"
                checked={noJudge}
                disabled={busy}
                onChange={(e) => setNoJudge(e.target.checked)}
              />
              <Checkbox
                label="Dry run"
                description="Fake store, agent and judge - no models touched"
                checked={dryRun}
                disabled={busy}
                onChange={(e) => setDryRun(e.target.checked)}
              />
              <Checkbox
                label="Rebuild prompts"
                description="Re-index the dataset collection first"
                checked={buildPrompts}
                disabled={busy}
                onChange={(e) => setBuildPrompts(e.target.checked)}
              />
            </div>

            {noJudge && !dryRun ? (
              <p className="text-xs">
                <span className="text-warning">Note:</span> the judge runs 80-190s per prompt. With the
                judge off, the metrics on the Results page will be empty rather than zero.
              </p>
            ) : null}

            {busy ? (
              <Button variant="danger" onClick={() => void cancelRun()}>
                Cancel run
              </Button>
            ) : (
              <Button variant="primary" onClick={submit} disabled={Boolean(hostError)}>
                Start run
              </Button>
            )}

            {status === 'completed' || status === 'cancelled' || status === 'failed' ? (
              <Button variant="ghost" onClick={reset}>
                Configure another run
              </Button>
            ) : null}

            {runError ? (
              <p role="alert" className="text-danger text-xs">
                {runError}
              </p>
            ) : null}

            {appInfo ? (
              <dl className="text-ink-faint grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
                <dt>Python</dt>
                <dd className="truncate" title={appInfo.python}>
                  {appInfo.python}
                </dd>
                <dt>Database</dt>
                <dd className="truncate" title={appInfo.dbPath}>
                  {appInfo.dbPath}
                </dd>
                <dt>Schema</dt>
                <dd>v{appInfo.schemaVersion}</dd>
              </dl>
            ) : null}
          </div>
        </Panel>

        {activeRun ? (
          <Panel>
            <PanelHeader title="This run" subtitle={activeRun.run_id} />
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 p-4 text-xs">
              <dt className="text-ink-faint">Status</dt>
              <dd>{activeRun.status}</dd>
              <dt className="text-ink-faint">Dataset</dt>
              <dd>{activeRun.dataset}</dd>
              <dt className="text-ink-faint">Rows</dt>
              <dd className="tnum">{activeRun.prompt_rows ?? 0}</dd>
            </dl>
          </Panel>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-col gap-3">
        <ProgressPanel phases={PHASES} />
        {activeRunId || status !== 'idle' ? (
          <>
            <EventConsole />
            <LivePromptTable />
          </>
        ) : (
          <Panel className="flex min-h-0 items-center justify-center">
            <EmptyState
              title="No run yet"
              detail="Configure a run on the left and start it. Events stream here as the sidecar emits them."
            />
          </Panel>
        )}
      </div>
    </div>
  )
}
