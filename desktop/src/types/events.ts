/**
 * The event envelope spoken by the Python sidecar.
 *
 * This mirrors two files that must stay in lockstep with it:
 *
 * - `bench_bridge/events.py` - what the sidecar writes
 * - `desktop/src-tauri/src/events.rs` - what the Rust host parses and re-emits
 *
 * The Rust host forwards each event verbatim on `bench://event`, so this file
 * describes the shape the webview actually receives rather than a re-derivation
 * of it. A change on any side needs the same change here.
 */

/** Must equal `events.SCHEMA_VERSION`. */
export const SCHEMA_VERSION = 1

/** Tauri event name used to push events into the webview. */
export const WEBVIEW_EVENT = 'bench://event'

/**
 * Every event type the sidecar can emit.
 *
 * Kept sorted to match `EventType.all()` and `types::ALL`, so the three lists
 * can be diffed by eye.
 */
export const EVENT_TYPES = [
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
] as const

export type EventType = (typeof EVENT_TYPES)[number]

/** Coarse run phases, matching `events.PHASES`. */
export const PHASES = [
  'preflight',
  'index',
  'projection',
  'system_a',
  'system_b_train',
  'system_b_infer',
  'stats',
  'done',
] as const

export type Phase = (typeof PHASES)[number]

/** The two inference systems under comparison. */
export type SystemId = 'A' | 'B'

/** Run lifecycle, as stored in the `runs` table. */
export type RunStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'imported'

/** One decoded event. */
export interface RunEvent {
  v: number
  seq: number
  ts_ms: number
  run_id: string
  type: EventType | string
  data: Record<string, unknown>
}

/**
 * Narrow an event to one type, giving the payload a concrete shape.
 *
 * Returns `null` when the event is of a different type, so callers can filter a
 * mixed stream with a type guard rather than casting.
 */
export function isEvent<T extends EventType>(
  event: RunEvent,
  type: T,
): event is RunEvent & { type: T; data: EventData[T] } {
  return event.type === type
}

/** Whether this event ends the run, successfully or not. */
export function isTerminal(event: RunEvent): boolean {
  return event.type === 'run_finished' || event.type === 'run_failed'
}

/** Payload shapes, keyed by event type. */
export interface EventData {
  run_started: {
    run_id: string
    dataset: string
    systems: SystemId[]
    limit: number | null
    prompt_count: number
    corpus_count: number
    seed: number | null
    no_judge: boolean
    dry_run: boolean
    embed_model: string | null
    generator_model: string | null
    judge_model: string | null
    python_version: string | null
    git_sha: string | null
    config_json: string | null
    [key: string]: unknown
  }
  phase: { phase: Phase; detail: string }
  index_progress: { done: number; total: number; rate_per_s?: number }
  projection_ready: {
    dataset: string
    collection: string
    dim: number
    n_points: number
    points_path: string
    meta_path: string
    explained_variance: number | null
    source_count: number | null
  }
  prompt_started: {
    system: SystemId
    index: number
    total: number
    prompt_id: string
    question: string
    ground_truth: string | null
  }
  embedding: { system: SystemId; prompt_id: string; time_s: number }
  decision: {
    system: SystemId
    prompt_id: string
    phase: string
    action: number
    k: number
    q_values: (number | null)[]
    epsilon: number | null
    chosen_rank: number | null
    greedy: boolean | null
  }
  retrieval: {
    system: SystemId
    index: number
    prompt_id: string
    k: number
    ids: string[]
    distances: (number | null)[]
    previews: string[]
    time_s?: number
  }
  generation: {
    system: SystemId
    index: number
    prompt_id: string
    answer: string
    time_s?: number
    total_tokens?: number
  }
  ragas: {
    system: SystemId
    index: number
    prompt_id: string
    faithfulness: number | null
    answer_relevancy: number | null
    context_recall: number | null
    judge_prompt_tokens?: number | null
    judge_completion_tokens?: number | null
    judge_time_s?: number | null
  }
  reward: {
    system: SystemId
    k_distribution: Record<string, number>
    note?: string
    reward?: number | null
    prompt_id?: string
  }
  train_step: {
    step: number
    prompt_id: string
    k: number
    reward: number | null
    loss: number | null
    epsilon: number
    /** One estimate per discrete action, so up to five entries. */
    q_values: (number | null)[]
    faithfulness?: number | null
    answer_relevancy?: number | null
    context_recall?: number | null
    total_time_s?: number | null
  }
  prompt_completed: {
    system: SystemId
    index: number
    prompt_id: string
    k: number
    /**
     * The finished row, so the host can persist metrics, token counts and
     * per-stage timings that it cannot recompute from the thin progress events.
     *
     * Optional: a sidecar older than this payload sends only the keys above.
     */
    row?: PromptRowRecord
    elapsed_s?: number
  }
  stats: StatsPayload
  log: { level: 'info' | 'warning' | 'error'; message: string }
  run_finished: {
    run_id: string
    dataset: string
    prompt_count: number
    corpus_count: number
    systems: SystemId[]
    dry_run: boolean
    no_judge: boolean
    prompt_rows: number
    training_rows: number
    duration_s: number
  }
  run_failed: { error: string; traceback: string }
}

/**
 * One finished prompt row as it travels on `prompt_completed`.
 *
 * This is the same shape the host stores in `prompt_rows`, minus `contexts`
 * (the retrieved passage text, which is only sent as short previews) and minus
 * the fields that duplicate the event envelope. That is why it is declared here
 * and reused by the read model rather than written twice.
 */
export interface PromptRowRecord {
  system: SystemId
  prompt_id: string
  phase: string | null
  question: string | null
  ground_truth: string | null
  answer: string | null
  retrieved_k: number | null
  retrieved_ids: string[] | null
  retrieved_distances: (number | null)[] | null
  faithfulness: number | null
  answer_relevancy: number | null
  context_recall: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  judge_prompt_tokens: number | null
  judge_completion_tokens: number | null
  embedding_time_s: number | null
  retrieval_time_s: number | null
  generation_time_s: number | null
  judge_time_s: number | null
  total_time_s: number | null
  reward?: number | null
}

/** The three RAGAS metrics under comparison, in display order. */
export const METRICS = ['faithfulness', 'answer_relevancy', 'context_recall'] as const

export type Metric = (typeof METRICS)[number]

/** Human labels for the metrics. */
export const METRIC_LABELS: Record<Metric, string> = {
  faithfulness: 'Faithfulness',
  answer_relevancy: 'Answer Relevancy',
  context_recall: 'Context Recall',
}

/** Short labels, for chart axes where the full name does not fit. */
export const METRIC_SHORT: Record<Metric, string> = {
  faithfulness: 'Faith.',
  answer_relevancy: 'Relev.',
  context_recall: 'Recall',
}

/** Descriptives for one metric within one system. */
export interface MetricSummary {
  n: number
  mean: number | null
  std: number | null
  sem: number | null
  median: number | null
  min: number | null
  max: number | null
}

/** Paired significance test between the two systems for one metric. */
export interface PairedTest {
  n: number
  t_stat: number | null
  p_two_tailed: number | null
  p_one_tailed_better: number | null
  w_stat: number | null
  p_wilcoxon_two_tailed: number | null
  mean_diff: number | null
  significant_at_alpha: boolean
  note?: string
}

/** Everything one system contributes to the results payload. */
export interface SystemSummary {
  prompt_count: number
  metrics: Record<Metric, MetricSummary>
  total_time_s: MetricSummary
  total_tokens: MetricSummary
  k_distribution: Record<string, number>
  mean_k: number | null
}

/** One DQN training step, as plotted on the training curve. */
export interface TrainingPoint {
  step: number
  k: number | null
  reward: number | null
  loss: number | null
  epsilon: number | null
  q_values: (number | null)[]
  faithfulness: number | null
}

/** The statistics payload emitted as the `stats` event and stored in `run_stats`. */
export interface StatsPayload {
  schema_version: number
  alpha: number
  metrics: Metric[]
  per_system: Record<SystemId, SystemSummary>
  comparison: Record<Metric, PairedTest>
  training: {
    steps: number
    curve: TrainingPoint[]
    reward: MetricSummary
    final_epsilon: number | null
  }
  paired_prompt_count: number
  compared_counts: Record<Metric, number>
}