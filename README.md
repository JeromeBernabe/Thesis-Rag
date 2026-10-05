# Thesis-Rag

Reinforcement-learning-based adaptive context selection for retrieval-augmented
generation. A DQN chooses *k*, the number of documents to retrieve per query;
System A is a fixed-k=3 baseline and System B is the learned policy. Both are
judged by a local qwen3:8b through RAGAS.

The analysis, including every correction made to earlier drafts, is in
[`results/analysis_report.md`](results/analysis_report.md). Read that first - it
states what the results do and do not support.

## Layout

| Path | What it is |
|------|------------|
| `run_experiment.py` | The experiment. Writes `results/ragas_results_*.csv`. |
| `run_experiment_logged.py` | Same, plus the per-step DQN training CSV. |
| `src/ragas_eval.py` | Judge wrapper, metric calls, token/time accounting. |
| `src/full_stats.py` | Derives every published statistic from the result CSVs. |
| `results/analysis_report.md` | The write-up. Generated numbers come from `full_stats.json`. |
| `checkpoints/` | Trained DQN weights. Git-tracked, hashes recorded in the report. |
| `bench_bridge/tests/` | The test suite that guards all of the above. |
| `desktop/` | Tauri GUI for browsing runs and importing the committed CSVs. |

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ollama must be running with `qwen3:8b` and `nomic-embed-text:latest` pulled.

## Running the experiment

```powershell
python run_experiment_logged.py --dataset hotpot
python run_experiment_logged.py --dataset all      # ~10h at RAGAS_MAX_WORKERS=1
```

Both systems are run unless you pass `--skip-a` / `--skip-b`. `--limit N` runs a
smoke test on the first N prompts.

### Do not point a trial run at the thesis checkpoints

A run **trains and rewrites** `checkpoints/dqn_model_<dataset>.pth` in place,
because each reward is the DQN's next training signal. Those files are committed
evidence for every number in the report. For anything exploratory:

```powershell
$env:BENCH_CHECKPOINTS_DIR = "$env:TEMP\ckpt-trial"
python run_experiment_logged.py --dataset hotpot --limit 2 ...
Remove-Item Env:\BENCH_CHECKPOINTS_DIR
```

Unset, the thesis checkpoints are used and updated as before. This is guarded by
`bench_bridge/tests/test_checkpoint_isolation.py`.

Write trial results somewhere disposable too - `--results <path>` and
`--training-csv <path>` - so they do not overwrite the CSVs the report cites.

## Verifying

```powershell
python -m pytest -q                              # whole suite
powershell -File desktop\scripts\verify.ps1      # python + rust + frontend + e2e
python verify_concurrency.py --workers 4         # judge equivalence, real model
python -m src.full_stats                         # regenerate results/full_stats.json
```

`verify.ps1` takes ~12 minutes. `cargo clippy` is not part of it because the
clippy component is not installed on this machine.

The report's numbers are not hand-entered: `full_stats.json` is regenerated from
the CSVs and `bench_bridge/tests/test_report_provenance.py` fails if the report,
the JSON, and the CSVs disagree, or if a cited CSV has changed since the JSON was
generated. After changing a CSV, regenerate before trusting any figure.

## Known data caveats

- `results/ragas_results_*_logged.csv` were produced before the token-logging fix.
  Their `prompt_tokens`/`completion_tokens` columns hold the **judge's** counts,
  not the generator's, and `total_tokens` is not their sum. Generator token
  usage is unrecoverable from those files; §4.1 and §4.3 of the report are
  withdrawn because of it. A re-run with current code records both correctly.
- `checkpoints/dqn_model_hotpot.pth` has `steps=0`: the hotpot policy was never
  trained, so its result reflects the reward function, not a learned policy.
- One seed per dataset at n=50. The only two statistically significant results in
  the study are regressions.

## Untracked working files

`plots/`, `simulation/`, `run_token_count.py`, `visualize_results.py` and
`tests/analysis_report.md` are scratch output from earlier work, not part of the
experiment. They are deliberately untracked.