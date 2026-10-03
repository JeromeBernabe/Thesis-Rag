/**
 * Stub the Tauri IPC layer for end-to-end tests.
 *
 * `window.__TAURI_INTERNALS__` is what `@tauri-apps/api` calls into. Replacing it
 * lets the real application code run - real store, real components, real charts -
 * against fixtures, so these tests exercise the UI rather than a mock of it.
 */

import type { Page } from '@playwright/test'

/** A completed prompt row, matching what the sidecar sends. */
const ROW_A = {
  system: 'A',
  prompt_id: 'p1',
  phase: 'system_a',
  question: 'The 2001 Intercontinental Cup was played on 27 November 2001, which Ghanaian retired professional footballer was named man of the match?',
  ground_truth: 'Samuel Osei Kuffour',
  answer: 'Samuel Kuffour.',
  retrieved_k: 3,
  retrieved_ids: ['doc-5a78b7b4554299029c4b5e4f', 'doc-5ae5e8b95542996de7b71a68'],
  retrieved_distances: [0.21, 0.28],
  faithfulness: 0.92,
  answer_relevancy: 0.81,
  context_recall: 0.74,
  prompt_tokens: 120,
  completion_tokens: 12,
  total_tokens: 132,
  judge_prompt_tokens: 400,
  judge_completion_tokens: 40,
  embedding_time_s: 0.011,
  retrieval_time_s: 0.031,
  generation_time_s: 2.51,
  judge_time_s: 91.4,
  total_time_s: 93.9,
  reward: null,
}

const ROW_B = {
  ...ROW_A,
  system: 'B',
  phase: 'system_b_infer',
  retrieved_k: 4,
  answer: 'Samuel Osei Kuffour, the retired Ghanaian defender.',
  faithfulness: 0.95,
  answer_relevancy: 0.88,
  context_recall: 0.9,
  reward: 0.72,
}

const RUN = {
  run_id: 'e2e-run-0001',
  created_at: 1_700_000_000_000,
  started_at: 1_700_000_000_000,
  finished_at: 1_700_000_120_000,
  status: 'completed',
  dataset: 'hotpot',
  systems: ['A', 'B'],
  prompt_count: 2,
  corpus_count: 30_000,
  seed: 42,
  no_judge: false,
  dry_run: false,
  duration_s: 120,
  error: null,
  projection_ready: true,
  config_json: null,
  embed_model: 'nomic-embed-text',
  generator_model: 'qwen3:8b',
  judge_model: 'qwen3:8b',
  python_version: '3.12.0',
  git_sha: 'abc1234',
  prompt_rows: 4,
  training_rows: 2,
  result_csv_path: null,
  training_csv_path: null,
  notes: null,
}

const STATS = {
  schema_version: 1,
  alpha: 0.05,
  metrics: ['faithfulness', 'answer_relevancy', 'context_recall'],
  per_system: {
    A: {
      prompt_count: 2,
      metrics: {
        faithfulness: { n: 2, mean: 0.9, std: 0.02, sem: 0.014, median: 0.9, min: 0.89, max: 0.91 },
        answer_relevancy: { n: 2, mean: 0.79, std: 0.03, sem: 0.021, median: 0.79, min: 0.78, max: 0.8 },
        context_recall: { n: 2, mean: 0.7, std: 0.04, sem: 0.028, median: 0.7, min: 0.68, max: 0.72 },
      },
      total_time_s: { n: 2, mean: 93.9, std: 1, sem: 0.7, median: 93.9, min: 93.4, max: 94.4 },
      total_tokens: { n: 2, mean: 132, std: 0, sem: 0, median: 132, min: 132, max: 132 },
      k_distribution: { '3': 2 },
      mean_k: 3,
    },
    B: {
      prompt_count: 2,
      metrics: {
        faithfulness: { n: 2, mean: 0.95, std: 0.01, sem: 0.007, median: 0.95, min: 0.94, max: 0.96 },
        answer_relevancy: { n: 2, mean: 0.86, std: 0.02, sem: 0.014, median: 0.86, min: 0.85, max: 0.87 },
        context_recall: { n: 2, mean: 0.85, std: 0.05, sem: 0.035, median: 0.85, min: 0.82, max: 0.88 },
      },
      total_time_s: { n: 2, mean: 95.1, std: 1, sem: 0.7, median: 95.1, min: 94.6, max: 95.6 },
      total_tokens: { n: 2, mean: 140, std: 5, sem: 3.5, median: 140, min: 135, max: 145 },
      k_distribution: { '4': 2 },
      mean_k: 4,
    },
  },
  comparison: {
    faithfulness: {
      n: 2,
      t_stat: 1.41,
      p_two_tailed: 0.32,
      p_one_tailed_better: 0.16,
      w_stat: 0,
      p_wilcoxon_two_tailed: 0.5,
      mean_diff: 0.05,
      significant_at_alpha: false,
    },
    answer_relevancy: {
      n: 2,
      t_stat: 1.73,
      p_two_tailed: 0.22,
      p_one_tailed_better: 0.11,
      w_stat: 0,
      p_wilcoxon_two_tailed: 0.5,
      mean_diff: 0.07,
      significant_at_alpha: false,
    },
    context_recall: {
      n: 2,
      t_stat: 2.12,
      p_two_tailed: 0.18,
      p_one_tailed_better: 0.09,
      w_stat: 0,
      p_wilcoxon_two_tailed: 0.5,
      mean_diff: 0.15,
      significant_at_alpha: false,
    },
  },
  training: {
    steps: 2,
    curve: [
      {
        step: 1,
        k: 1,
        reward: 0.41,
        loss: 0.62,
        epsilon: 1,
        q_values: [0.1, 0.2, 0.35, 0.3, 0.25],
        faithfulness: 0.6,
      },
      {
        step: 2,
        k: 4,
        reward: 0.72,
        loss: 0.31,
        epsilon: 0.72,
        q_values: [0.12, 0.22, 0.33, 0.48, 0.27],
        faithfulness: 0.88,
      },
    ],
    reward: { n: 2, mean: 0.565, std: 0.22, sem: 0.155, median: 0.565, min: 0.41, max: 0.72 },
    final_epsilon: 0.72,
  },
  paired_prompt_count: 2,
  compared_counts: { faithfulness: 2, answer_relevancy: 2, context_recall: 2 },
}

const DETAIL = {
  run: RUN,
  stats: STATS,
  promptRows: [
    { ...ROW_A, prompt_index: 0 },
    { ...ROW_B, prompt_index: 0 },
    { ...ROW_A, prompt_index: 1, prompt_id: 'p2', answer: 'Ghana.', faithfulness: 0.89 },
    { ...ROW_B, prompt_index: 1, prompt_id: 'p2', answer: 'Ghana won.', faithfulness: 0.96 },
  ],
  trainingRows: STATS.training.curve.map((point) => ({
    step: point.step,
    prompt_id: `p${point.step}`,
    k: point.k,
    faithfulness: point.faithfulness,
    answer_relevancy: null,
    context_recall: null,
    reward: point.reward,
    loss: point.loss,
    epsilon: point.epsilon,
    q_values: point.q_values,
    total_time_s: 95,
  })),
}

/**
 * A small but real projection: 400 points, so the ids and the highlight matching
 * are exercised rather than mocked away.
 *
 * `get_projection_data` must be stubbed for the 3D view to appear at all - the
 * webview cannot read the projection files itself, which is the whole reason the
 * Rust command exists.
 */
function makeProjection() {
  const n = 400
  // A deterministic spiral-ish cloud, so the camera framing has something to fit.
  const points: number[] = []
  const ids: string[] = []
  for (let i = 0; i < n; i++) {
    const angle = i * 0.61
    const radius = 1 + (i % 40) / 12
    points.push(Math.cos(angle) * radius, Math.sin(angle) * radius * 0.6, (i % 17) / 5 - 1.7)
    ids.push(`doc-${i.toString(16).padStart(24, '0')}-${i}`)
  }

  // The two ids the fixture rows retrieved, in the projection's longer form.
  ids[12] = 'doc-5a78b7b4554299029c4b5e4f-0'
  ids[37] = 'doc-5ae5e8b95542996de7b71a68-1'

  return {
    meta: {
      dataset: 'hotpot',
      collection: 'hotpot',
      n_points: n,
      dim: 768,
      components: [[0.6, 0.5, 0.2], [0.1, 0.3, 0.7], [0.2, 0.1, 0.4]],
      mean: [0, 0, 0],
      ids,
      bounds: { min: [-3, -2, -2], max: [3, 2, 2] },
      explained_variance: [0.21, 0.12, 0.07],
      explained_variance_ratio: [0.52, 0.28, 0.11],
      source_count: 30_000,
    },
    points,
  }
}

const PROJECTION = makeProjection()

/** Install the stub. Must run before the app bundle executes. */
export async function stubTauri(page: Page, options: { empty?: boolean } = {}): Promise<void> {
  await page.addInitScript(
    ({ detail, runs, projection }) => {
      const handlers = new Map<string, (args: Record<string, unknown>) => unknown>()

      handlers.set('app_info', () => ({
        datasets: ['hotpot', 'fintech', 'math', 'ragtruth'],
        defaultDataset: 'hotpot',
        defaultLimit: 50,
        defaultSeed: 42,
        python: 'python',
        projectRoot: 'C:/repo',
        dbPath: 'C:/repo/data/bench/runs.sqlite3',
        schemaVersion: 1,
      }))

      handlers.set('list_runs', () => runs)
      handlers.set('get_run_detail', () => detail)
      handlers.set('get_stats', () => detail.stats)
      handlers.set('get_run_events', () => [])
      handlers.set('run_in_progress', () => false)
      handlers.set('get_projection', () => ({
        dataset: 'hotpot',
        collection: 'hotpot',
        nPoints: 400,
        pointsPath: 'C:/repo/data/bench/hotpot.points.bin',
        metaPath: 'C:/repo/data/bench/hotpot.meta.json',
        explainedVariance: 0.21,
      }))
      handlers.set('get_projection_data', (args) =>
        (args as { dataset?: string }).dataset === 'hotpot' ? projection : null,
      )
      handlers.set('list_projections', () => ['hotpot'])
      handlers.set('start_run', (args) => ({ runId: 'e2e-run-0002', pid: 1, dryRun: false, ...args }))
      handlers.set('cancel_run', () => 'e2e-run-0002')
      handlers.set('delete_run', () => undefined)
      handlers.set('import_legacy', () => ({ runs: [], promptRows: 0, trainingRows: 0, skipped: [] }))

      // `invoke` resolves through this callback; `listen` registers here too.
      ;(window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {
        invoke(command: string, args?: Record<string, unknown>) {
          const handler = handlers.get(command)
          if (!handler) return Promise.reject(new Error(`unstubbed command: ${command}`))
          return Promise.resolve(handler(args ?? {}))
        },
        transformCallback(callback: (event: unknown) => void) {
          return callback
        },
        convertFileSrc(path: string) {
          return path
        },
        metadata: { currentWindow: { label: 'main' }, currentWebview: { label: 'main' } },
      }

      // The plugin-level event bus listens through these two.
      ;(window as unknown as { __TAURI_EVENT_PLUGIN_INTERNALS__: unknown }).__TAURI_EVENT_PLUGIN_INTERNALS__ = {
        unregisterListener: () => {},
      }
    },
    { detail: DETAIL, runs: options.empty ? [] : [RUN], projection: PROJECTION },
  )
}