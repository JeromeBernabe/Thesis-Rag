/**
 * Shapes returned by the Tauri commands in `src-tauri/src/commands.rs`.
 *
 * These are read straight out of SQLite by the Rust side and handed over as
 * plain JSON, so nullability here matters: a metric the judge never produced is
 * `null`, not `0`, and the charts must render a gap rather than a zero.
 */

import type { Metric, MetricSummary, PairedTest, PromptRowRecord, SystemId, SystemSummary, StatsPayload, TrainingPoint } from './events'

/** Row shape from the `runs` table. */
export interface RunRecord {
  run_id: string
  created_at: number
  started_at: number | null
  finished_at: number | null
  /**
   * `cancelled` is written by the host, not the sidecar: stopping a run kills
   * the process, so there is no terminal event to carry the status.
   */
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'imported'
  dataset: string
  systems: SystemId[] | null
  prompt_count: number
  corpus_count: number | null
  seed: number | null
  no_judge: boolean
  dry_run: boolean
  duration_s: number | null
  error: string | null
  projection_ready?: boolean
  config_json?: Record<string, unknown> | null
  embed_model?: string | null
  generator_model?: string | null
  judge_model?: string | null
  python_version?: string | null
  git_sha?: string | null
  prompt_rows?: number | null
  training_rows?: number | null
  result_csv_path?: string | null
  training_csv_path?: string | null
  notes?: string | null
}

/**
 * One row from `prompt_rows`: a single system answering a single prompt.
 *
 * The same record the sidecar sent on `prompt_completed`, plus `prompt_index`,
 * which the host takes from the event envelope because it is identical for both
 * systems - that is what lets the Results page pair A and B per question.
 */
export interface PromptRow extends PromptRowRecord {
  prompt_index: number | null
}

/** One row from `training_steps`. */
export interface TrainingRow {
  step: number
  prompt_id: string | null
  k: number | null
  faithfulness: number | null
  answer_relevancy: number | null
  context_recall: number | null
  reward: number | null
  loss: number | null
  epsilon: number | null
  q_values: (number | null)[]
  total_time_s: number | null
}

/** Everything the Results page needs for one run, in one round trip. */
export interface RunDetail {
  run: RunRecord
  stats: StatsPayload | null
  promptRows: PromptRow[]
  trainingRows: TrainingRow[]
}

/** Projection metadata from the `projections` table. */
export interface ProjectionInfo {
  dataset: string
  collection: string
  dim: number
  n_points: number
  pointsPath: string
  metaPath: string
  explainedVariance: number | null
  sourceCount: number | null
  createdAt: number
}

/**
 * Projection sidecar file, written by `bench_bridge/projection.py`.
 *
 * `points` is loaded separately from the little-endian float32 XYZ triples, so
 * this carries only the small JSON part.
 */
export interface ProjectionMeta {
  dataset: string
  collection: string
  n_points: number
  dim: number
  /** PCA components, shaped `dim x 3`, for projecting a new embedding. */
  components: number[][]
  mean: number[]
  ids: string[]
  bounds: { min: [number, number, number]; max: [number, number, number] }
  /** Per-component eigenvalue, one entry per output axis. */
  explained_variance: number[] | null
  /** Per-component fraction of total variance, summing to at most 1. */
  explained_variance_ratio: number[] | null
  source_count: number | null
}

/**
 * Share of total variance captured by the first three components.
 *
 * Null when the sidecar wrote no variance figures - a projection built by
 * sampling rather than a full PCA pass reports zeros, which would otherwise read
 * as "these three axes explain nothing".
 */
export function varianceExplained(meta: ProjectionMeta): number | null {
  const ratios = meta.explained_variance_ratio
  if (!ratios || ratios.length === 0) return null
  const total = ratios.reduce((sum, value) => sum + value, 0)
  return total > 0 ? total : null
}

/** A projection, ready to draw: the cloud plus the metadata that describes it. */
export interface ProjectionPoints {
  /** Flat xyz triples, `n_points * 3` long. */
  xyz: Float32Array
  count: number
  meta: ProjectionMeta
}

/** Configuration and defaults reported at startup. */
export interface AppInfo {
  datasets: string[]
  defaultDataset: string
  defaultLimit: number
  defaultSeed: number
  python: string
  projectRoot: string
  dbPath: string
  schemaVersion: number
}

/** What the Run page needs to open a run. */
export interface RunHandle {
  runId: string
  pid: number
  dryRun: boolean
}

/** Request body for `start_run`. */
export interface RunRequest {
  dataset: string
  systems: SystemId[]
  limit?: number | null
  seed?: number | null
  noJudge?: boolean
  dryRun?: boolean
  buildPrompts?: boolean
  runId?: string | null
}

/** Report from importing the committed CSVs under `results/`. */
export interface ImportReport {
  runs: string[]
  promptRows: number
  trainingRows: number
  skipped: string[]
}

/** Re-exported so chart code can reach the stats types from one import. */
export type { Metric, MetricSummary, PairedTest, StatsPayload, SystemId, SystemSummary, TrainingPoint }