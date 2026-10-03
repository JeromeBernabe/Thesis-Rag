/**
 * Typed wrappers around the Tauri commands.
 *
 * Two things this layer is responsible for:
 *
 * - Tauri is not present under Vitest or in a plain browser, so `invoke` is
 *   routed through a seam that tests replace. Importing `invoke` at module scope
 *   would make every unit test need a Tauri shim.
 * - The binary projection file is read here rather than in a component, so the
 *   3D view only ever deals with a typed `Float32Array`.
 */

import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import type { RunEvent } from '@/types/events'
import type {
  AppInfo,
  ImportReport,
  ProjectionInfo,
  ProjectionMeta,
  ProjectionPoints,
  RunDetail,
  RunHandle,
  RunRecord,
  RunRequest,
} from '@/types/models'

/**
 * How projection files are read.
 *
 * The default goes through Tauri's filesystem plugin-free HTTP asset protocol;
 * tests and the browser fallback swap in `fetch`, which behaves identically for
 * a `file://` URL.
 */
/** Startup configuration and defaults. */
export function getAppInfo(): Promise<AppInfo> {
  return invoke<AppInfo>('app_info')
}

/** Start a run. The process is spawned before this resolves. */
export function startRun(request: RunRequest): Promise<RunHandle> {
  return invoke<RunHandle>('start_run', { request })
}

/** Cancel the active run; resolves with the id of the run that was cancelled. */
export function cancelRun(): Promise<string> {
  return invoke<string>('cancel_run')
}

/** Whether a run is currently in progress. */
export function runInProgress(): Promise<boolean> {
  return invoke<boolean>('run_in_progress')
}

/** All runs, newest first. */
export function listRuns(): Promise<RunRecord[]> {
  return invoke<RunRecord[]>('list_runs')
}

/** Run metadata, rows, training steps and statistics in one call. */
export function getRunDetail(runId: string): Promise<RunDetail> {
  return invoke<RunDetail>('get_run_detail', { runId })
}

/** The recorded event timeline, for replaying a finished run. */
export function getRunEvents(runId: string): Promise<{ seq: number; ts_ms: number; type: string; data: Record<string, unknown> }[]> {
  return invoke('get_run_events', { runId })
}

export function getStats(runId: string): Promise<unknown> {
  return invoke('get_stats', { runId })
}

export function deleteRun(runId: string): Promise<void> {
  return invoke<void>('delete_run', { runId })
}

/** Precomputed 3D projection metadata for a dataset, if one exists. */
export function getProjection(dataset: string): Promise<ProjectionInfo | null> {
  return invoke<ProjectionInfo | null>('get_projection', { dataset })
}

/** Datasets that have a projection ready. */
export function listProjections(): Promise<string[]> {
  return invoke<string[]>('list_projections')
}

/**
 * Read a projection's point cloud and metadata.
 *
 * The sidecar writes two files on disk, and the webview cannot read either: it has
 * no filesystem access to arbitrary paths, and on Windows `C:\...` is not a URL
 * that `fetch` can open. Rust reads both and returns them already parsed, which
 * also keeps the sandbox narrow - no filesystem plugin, no asset-scope grant.
 *
 * Resolves to `null` when the dataset has never been projected. The length check
 * is a second line of defence: Rust rejects a truncated buffer, but the numbers
 * arriving here are trusted enough to hand straight to `THREE.BufferAttribute`,
 * where a bad count produces a silently corrupt cloud rather than an error.
 */
export async function getProjectionData(dataset: string): Promise<ProjectionPoints | null> {
  const payload = await invoke<{ meta: ProjectionMeta; points: number[] } | null>(
    'get_projection_data',
    { dataset },
  )
  if (!payload) return null

  const xyz = new Float32Array(payload.points)
  if (xyz.length % 3 !== 0) {
    throw new Error(`${dataset}: ${xyz.length} floats is not a whole number of XYZ triples`)
  }
  return {
    meta: payload.meta,
    xyz,
    count: xyz.length / 3,
  }
}

/** Import the committed CSVs under `results/` as imported runs. */
export function importLegacy(sourceDir?: string): Promise<ImportReport> {
  return invoke<ImportReport>('import_legacy', { sourceDir: sourceDir ?? null })
}

/**
 * Subscribe to sidecar events.
 *
 * Returns an unlisten function, matching the shape `useEffect` cleanups want.
 * A malformed event is dropped rather than thrown: one bad line from the
 * sidecar must not tear down the live view.
 */
export async function onEvent(handler: (event: RunEvent) => void): Promise<() => void> {
  const unlisten = await listen<RunEvent>('bench://event', ({ payload }) => {
    try {
      handler(payload)
    } catch (error) {
      console.error('event handler threw', error)
    }
  })
  return unlisten
}