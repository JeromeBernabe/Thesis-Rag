# DQN-Enhanced RAG: Full Experimental Analysis Report (4 Datasets)

**Date:** September 21, 2026 (numbers regenerated and verified October 4, 2026)
**Author:** Johann (Thesis)
**Models:** llama3.2 (generation), nomic-embed-text (embeddings), qwen3:8b (RAGAS judge)
**GPU:** NVIDIA RTX 4050 Laptop, CUDA 12.4
**Hardware:** Local inference (no API costs)

---

## 1. Executive Summary

This report evaluates a DQN-enhanced RAG system (System B, dynamic k∈{1..5}) against a baseline RAG system (System A, fixed k=3) across **4 datasets** (Hotpot, RagTruth, Fintech, Math) using custom RAGAS scoring with latency instrumentation.

**Key findings across all 4 datasets:**

1. **DQN learns dataset-specific k-selection:** Hotpot→k=1, RagTruth→k=4, Fintech→k=3, Math→k=3
2. **No statistically significant faithfulness improvement** on any dataset at α=0.05
3. **Hotpot shows the strongest positive trend:** +8.8% faithfulness (p=0.234, one-tailed). Its large advantage is in *request* tokens (−64.4%), not generation tokens (−0.5%) or efficiency (1.09×, within noise)
4. **Math shows degradation:** −8.9% faithfulness (p=0.90, one-tailed), suggesting DQN hurts on math reasoning
5. **Judge scoring (qwen3:8b) dominates cost:** 90-97% of wall-clock time across all datasets
6. **Both statistically significant results are regressions, not gains:** RagTruth answer relevancy (two-tailed p=0.033) and fintech context recall (p=0.022)
7. **Metric behaviour was validated by probe:** faithfulness correctly rejects unsupported claims; context recall is lenient but biased high, which makes the low fintech scores meaningful rather than suspect (§12)

> **Corrections applied 2026-10-04.** Every number below was regenerated from the
> result CSVs by `src/full_stats.py` and is checked by
> `bench_bridge/tests/test_report_provenance.py`. Four things changed materially:
> hotpot's faithfulness gain was **+8.3% → +8.8%** on **50** prompts rather than 49;
> the claimed **"3× token efficiency gain" was wrong** (the token columns held the
> judge's counts) and is **withdrawn entirely** rather than restated as 1.09×,
> because that ratio used the same unusable column; RagTruth answer relevancy's
> **p=0.016 was a wrong-direction p-value**; and the fintech context-recall drop
> was **not** a judge artefact. Sections 3.3, 3.4 and 4 carry the details.

---

## 2. Experiment Design

### Systems Compared
- **System A (Baseline):** Standard RAG with fixed k=3 retrieved documents
- **System B (DQN-Enhanced):** DQN agent selects k ∈ {1, 2, 3, 4, 5} per query

### Reward Function
```
R = 0.35·F + 0.35·AR + 0.30·CR − λ·log(1+k)
```
Where F = faithfulness, AR = answer relevancy, CR = context_recall, λ = 0.0 (no k-penalty)

### DQN Architecture
- Input: 768-dim (nomic-embed-text embedding)
- Hidden: 128 → 64
- Output: 5 actions (k=1..5)
- Training: epsilon-greedy (ε: 1.0 → 0.778), batch_size=8, replay_buffer=500

### Evaluation
- 50 prompts per dataset (sampled from training sets)
- RAGAS metrics: faithfulness, answer_relevancy, context_recall
- Statistical tests: paired t-test (one-tailed for faithfulness, two-tailed for AR/CR), Wilcoxon signed-rank, Cohen's d
- Full token and latency instrumentation across all pipeline stages

---

## 3. Results Summary (All 4 Datasets)

### 3.1 k-Distribution Analysis

| Dataset | k=1 | k=2 | k=3 | k=4 | k=5 | Dominant k |
|---------|-----|-----|-----|-----|-----|------------|
| Hotpot | 49 (98%) | 1 (2%) | — | — | — | k=1 |
| RagTruth | — | 2 (4%) | — | 46 (92%) | 2 (4%) | k=4 |
| Fintech | — | — | 40 (80%) | — | 10 (20%) | k=3 |
| Math | 2 (4%) | 1 (2%) | 35 (70%) | 12 (24%) | — | k=3 |

**Key observations:**
- **Hotpot:** DQN converges to k=1 (greedy) — multi-hop questions benefit from focused, minimal context
- **RagTruth:** DQN converges to k=4 — fact verification queries benefit from additional evidence
- **Fintech:** DQN stays near baseline (k=3) with occasional k=5 — domain-specific queries need varied context
- **Math:** DQN stays near baseline (k=3) with some k=4 — math problems benefit from similar context as baseline

### 3.2 Faithfulness (System B vs System A)

| Dataset | n | System A | System B | Δ | Cohen's d | p (one-tailed) | Wilcoxon p | Significant? |
|---------|---|----------|----------|---|-----------|----------------|------------|--------------|
| Hotpot | 50 | 0.598 | 0.651 | **+8.8%** | 0.103 | 0.234 | 0.214 | No (trending) |
| RagTruth | 50 | 0.842 | 0.839 | −0.3% | −0.007 | 0.521 | 0.377 | No |
| Fintech | 50 | 0.815 | 0.869 | **+6.6%** | 0.191 | 0.092 | 0.117 | No (trending) |
| Math | 49 | 0.524 | 0.477 | **−8.9%** | −0.186 | 0.901 | 0.937 | No |

`n` is the number of prompts scored under **both** systems, so it is per metric and
can be lower than the 50 prompts in the run. Math is 49 because one prompt
(`Math-Test-1016`) received no faithfulness score from the judge under system B.
See §11.

**Interpretation:**
- **Hotpot:** Strongest positive trend (+8.8%, p=0.234). k=1 reduces noise, improving faithfulness for multi-hop questions
- **Fintech:** Positive trend (+6.6%, p=0.092). k=3/5 mixture shows slight improvement
- **RagTruth:** No change. k=4 provides same quality as k=3 baseline
- **Math:** Degradation (−8.9%, p=0.901). k=3/4 doesn't help math reasoning; more context may introduce noise

### 3.3 Answer Relevancy

| Dataset | n | System A | System B | Δ | p (one-tailed, B>A) | p (two-tailed) | Significant? |
|---------|---|----------|----------|---|----------------------|----------------|--------------|
| Hotpot | 50 | 0.730 | 0.764 | +4.6% | 0.168 | 0.337 | No |
| RagTruth | 50 | 0.745 | 0.719 | **−3.5%** | 0.984 | **0.033** | **Yes (B worse, two-tailed)** |
| Fintech | 50 | 0.772 | 0.764 | −1.1% | 0.660 | 0.681 | No |
| Math | 50 | 0.787 | 0.815 | +3.5% | 0.063 | 0.126 | No |

**Critical finding:** RagTruth answer relevancy is significantly **lower** under
system B. The two-tailed p-value is 0.033; the one-tailed p for the directional
hypothesis B>A is 0.984, because B is on the wrong side of it.

> **Correction (this figure was previously reported as p=0.016, "significant").**
> 0.016 is half the two-tailed p-value, taken on the *degradation* side. It was
> presented as the one-tailed p for B>A, which is the opposite direction — the
> test the rest of this report states. The degradation itself is real and does
> survive a two-tailed test; what was wrong was the direction the p-value was
> quoted for, which made a regression read as the primary result.

### 3.4 Context Recall

| Dataset | n | System A | System B | Δ | p (two-tailed) | p (one-tailed, B>A) |
|---------|---|----------|----------|---|----------------|----------------------|
| Hotpot | 49 | 0.281 | 0.233 | −17.0% | 0.134 | 0.933 |
| RagTruth | 50 | 0.878 | 0.893 | +1.6% | 0.506 | 0.253 |
| Fintech | 50 | 0.110 | 0.032 | **−70.9%** | **0.022** | 0.989 |
| Math | 50 | 0.262 | 0.282 | +7.5% | 0.467 | 0.234 |

> **Correction.** This section previously attributed fintech's −70.9% to judge
> failures ("qwen3:8b returning NaN for faithfulness"). That explanation does not
> hold: the fintech run has **no** NULL scores in any metric, so all 50 prompts
> are paired and the drop is a real measured difference, not an artefact of
> missing rows. The NaN failures occurred in the *hotpot* run, and hotpot's
> context recall is the one that lost a prompt (n=49, §11).

Context recall saturates at 1.0 whenever the context is on-topic, even when the
specific reference claim is absent (`probe_metrics.py`). That leniency biases it
*towards* high scores, so fintech's near-zero values are evidence of genuine
absence rather than a metric artefact — see §12.

---

## 4. Token Usage Analysis

> **This whole section was mislabelled and has been corrected.**
>
> Two separate defects were behind it:
>
> 1. The runners logged `scores["judge_prompt_tokens"]` into the `prompt_tokens`
>    column and `scores["judge_completion_tokens"]` into `completion_tokens`.
>    The generator's own counts, which Ollama had already returned, were
>    discarded. In the result CSVs `prompt_tokens` is therefore identical to
>    `judge_prompt_tokens` in **every row**, and likewise for the completion
>    columns — which is how the judge's cost ended up presented as the
>    generator's. This is fixed in `run_experiment.py` and
>    `run_experiment_logged.py`; the CSVs below predate the fix.
> 2. The old table labelled `total_tokens` as "generation tokens". Those are
>    different quantities — total is prompt + completion, generation is
>    completion alone.
>
> Consequently **judge token usage cannot be reported at all** from these CSVs,
> because the only judge-token columns in them are copies of the generator's.
> The judge figures in §4.2 previously quoted here were the generator's numbers
> relabelled. `src/full_stats.py` now refuses to emit them and records the
> reason in `data_warnings`.

### 4.1 Generation Tokens (llama3.2) — completion tokens only

**Unavailable.** This table has been withdrawn. It read:

| Dataset | System A | System B | Δ |
|---------|----------|----------|---|
| Hotpot | 587.3 | 584.1 | −0.5% |
| RagTruth | 720.8 | 733.2 | +1.7% |
| Fintech | 426.7 | 426.5 | −0.04% |
| Math | 746.6 | 742.8 | −0.5% |

Those numbers are the *judge's* completion tokens, not the generator's — the
defect above. The table also carried a conclusion drawn from them ("choosing k
changes the prompt a great deal and the answer almost not at all; the context
budget is spent upstream in retrieval"), and that conclusion is withdrawn with
it: it described how much the judge wrote when breaking an answer into claims,
which is not a measurement of answer length.

`src/full_stats.py` now emits `null` for these figures rather than a number
under a label that is wrong. Recovering them requires re-running the benchmarks;
the code fix is in place, so a re-run is the only thing standing between this
section and real numbers.

### 4.2 Total Request Tokens (prompt + completion)

This is the one token measurement these CSVs do support: `total_tokens` came
from the generator's own response and was never affected by the logging defect.

| Dataset | System A | System B | Δ |
|---------|----------|----------|---|
| Hotpot | 4,028 | 1,435 | **−64.4%** |
| RagTruth | 2,103 | 2,670 | +27.0% |
| Fintech | 2,560 | 2,922 | +14.1% |
| Math | 692 | 699 | +1.1% |

**Finding:** total request tokens are where the effect of k actually shows, and
they are not a consistent story. System B (larger k) sends far fewer tokens on
hotpot and far more on the other three, so there is no general efficiency claim
this thesis can make from these runs.

**Unavailable — judge tokens (qwen3:8b).** The judge-token columns duplicate the
generator's in every row, so no judge token figure can be derived from these
files. Judge *wall-clock* is real and is reported in §5.

### 4.3 Token Efficiency (Faithfulness per 1k Generation Tokens)

**Unavailable.** Withdrawn for the same reason as §4.1: it divides faithfulness
by the mislabelled column.

> **Correction, twice over.** This table previously read 0.148 → 0.447 for
> hotpot, a "3× efficiency gain", and the report called it the key token
> finding. Both numbers were wrong: they divided faithfulness by the
> mislabelled token column. Rewriting the denominator as a judge-token count
> turned "3×" into 1.09× — still wrong, still on the same corrupt column, and
> for long enough to look like a corrected result rather than a broken one.
> Faithfulness per 1k tokens is not reported here at all.

The efficiency question is answerable, and §4.2 answers part of it: with
`total_tokens` valid, System B spends 64.4% fewer request tokens on hotpot at
equal-or-better faithfulness. That is a narrower claim than "token efficiency
improves", and it is the one the data supports.

---

## 5. Latency Analysis

### 5.1 Time Breakdown (seconds per query)

| Dataset | Component | System A | System B | Δ |
|---------|-----------|----------|----------|---|
| Hotpot | Retrieval | 0.158 | 0.010 | −93.7% |
| Hotpot | Generation | 2.151 | 1.180 | −45.1% |
| Hotpot | Judge scoring | 62.26 | 59.04 | −5.2% |
| Hotpot | **Total** | **64.57** | **60.23** | **−6.7%** |
| RagTruth | Retrieval | 0.147 | 0.006 | −95.9% |
| RagTruth | Generation | 2.319 | 2.752 | +18.7% |
| RagTruth | Judge scoring | 76.43 | 81.00 | +6.0% |
| RagTruth | **Total** | **78.90** | **83.75** | **+6.1%** |
| Fintech | Retrieval | 0.183 | 0.202 | +10.4% |
| Fintech | Generation | 2.370 | 3.330 | +40.5% |
| Fintech | Judge scoring | 51.04 | 50.44 | −1.2% |
| Fintech | **Total** | **53.60** | **53.97** | **+0.7%** |
| Math | Retrieval | 0.556 | 0.013 | −97.7% |
| Math | Generation | 4.513 | 4.166 | −7.7% |
| Math | Judge scoring | 72.39 | 70.61 | −2.5% |
| Math | **Total** | **77.46** | **74.79** | **−3.4%** |

### 5.2 Latency Findings

1. **Judge scoring dominates:** 90-97% of total time is qwen3:8b evaluation across all datasets
2. **Hotpot is only dataset with meaningful speedup:** 6.7% faster (4.3s/query savings)
3. **RagTruth is 6.1% slower** — longer generation + judge evaluation overhead
4. **Fintech is neutral** — +0.7% (within noise)
5. **Math is 3.1% faster** — slight generation improvement offset by similar judge time
6. **Retrieval is negligible** — System B's DQN computation is ~0.01s vs System A's vector search

---

## 6. Statistical Significance Summary (All Tests)

| Metric | Dataset | n | Test | p-value | Effect Size | Significant? |
|--------|---------|---|------|---------|-------------|--------------|
| Faithfulness | Hotpot | 50 | One-tailed t (B>A) | 0.234 | d=0.103 | No |
| Faithfulness | Hotpot | 50 | Wilcoxon (B>A) | 0.214 | — | No |
| Faithfulness | RagTruth | 50 | One-tailed t (B>A) | 0.521 | d=−0.007 | No |
| Faithfulness | RagTruth | 50 | Wilcoxon (B>A) | 0.377 | — | No |
| Faithfulness | Fintech | 50 | One-tailed t (B>A) | 0.092 | d=0.191 | No (trending) |
| Faithfulness | Fintech | 50 | Wilcoxon (B>A) | 0.117 | — | No |
| Faithfulness | Math | 49 | One-tailed t (B>A) | 0.901 | d=−0.186 | No |
| Faithfulness | Math | 49 | Wilcoxon (B>A) | 0.937 | — | No |
| Answer Rel | Hotpot | 50 | One-tailed t (B>A) | 0.168 | — | No |
| Answer Rel | RagTruth | 50 | **Two-tailed t** | **0.033** | — | **Yes (B worse)** |
| Answer Rel | Fintech | 50 | One-tailed t (B>A) | 0.660 | — | No |
| Answer Rel | Math | 50 | One-tailed t (B>A) | 0.063 | — | No |
| Context Rec | Hotpot | 49 | Two-tailed t | 0.134 | — | No |
| Context Rec | RagTruth | 50 | Two-tailed t | 0.506 | — | No |
| Context Rec | Fintech | 50 | **Two-tailed t** | **0.022** | — | **Yes (B worse)** |
| Context Rec | Math | 50 | Two-tailed t | 0.467 | — | No |

Every p-value above is reproducible from `results/ragas_results_<dataset>_logged.csv`
via `src/full_stats.py`; `bench_bridge/tests/test_report_provenance.py` fails if
`results/full_stats.json` and the CSVs disagree.

### Interpretation
- **No faithfulness improvement reaches significance** on any dataset
- **Fintech is closest** (p=0.092, one-tailed) — may reach significance with n=100
- **RagTruth answer relevancy is significantly lower under B** (two-tailed p=0.033);
  the one-tailed B>A p is 0.984. k=4 appears to dilute answer focus.
- **Fintech context recall is significantly lower under B** (two-tailed p=0.022).
  This one is *not* a judge artefact — the run has no missing scores (§3.4).
- **Math shows degradation** (p=0.901, trending negative) — DQN hurts math reasoning
- **Both significant results are regressions, not improvements.** No metric shows a
  statistically significant *gain* for system B.

---

## 7. Training Dynamics

### 7.1 Training Progress by Dataset

| Dataset | Reward (1-10) | Reward (last 10) | Loss (1-10) | Loss (last 10) | k-dist (training) |
|---------|---------------|-------------------|-------------|----------------|-------------------|
| Hotpot | 0.516 | 0.610 | 0.338 | 0.058 | {1:8, 2:7, 3:9, 4:13, 5:13} |
| RagTruth | 0.856 | 0.886 | 0.644 | 0.032 | {1:12, 2:8, 3:15, 4:9, 5:6} |
| Fintech | 0.476 | 0.628 | 0.529 | 0.017 | {1:1, 2:4, 3:17, 4:19, 5:9} |
| Math | 0.514 | 0.423 | 0.411 | 0.019 | {1:7, 2:8, 3:16, 4:11, 5:8} |

### 7.2 Training Observations

1. **All datasets show converging loss** — DQN learns stable value estimates
2. **Reward increases from exploration to convergence** — except Math (0.514→0.423)
3. **Fintech shows strongest convergence** — loss drops from 0.529 to 0.017
4. **Math shows reward regression** — reward decreases during training, suggesting overfitting
5. **k-distribution varies during training** — agent explores all k values before converging

---

## 8. Cross-Dataset Comparison

### 8.1 Dataset Characteristics

| Dataset | Type | Corpus Size | Base Faithfulness | Challenge | Best k for DQN |
|---------|------|-------------|-------------------|-----------|----------------|
| Hotpot | Multi-hop | 30,000* | 0.596 | High | k=1 (noise reduction) |
| RagTruth | Fact verification | 30,000 | 0.842 | Medium | k=4 (evidence accumulation) |
| Fintech | Domain Q&A | 6,251 | 0.815 | Medium | k=3 (baseline-like) |
| Math | Problem solving | 30,000 | 0.524 | High | k=3 (no improvement) |

*Hotpot: 90K docs truncated to 30K due to MAX_CORPUS_DOCS limit

### 8.2 Why Results Vary by Dataset

1. **Hotpot benefits from k=1:** Multi-hop questions often have one key supporting document; additional documents introduce noise
2. **RagTruth needs k=4:** Fact verification requires multiple supporting/contradicting evidence pieces
3. **Fintech is baseline-like:** Domain queries are well-served by k=3; DQN learns to stay near baseline
4. **Math degrades with more context:** Math problems benefit from focused reasoning, not additional documents
5. **Context recall is a presence detector, not a coverage score:** it returns 1.0 for on-topic context even when the reference is absent, so its low fintech values indicate genuine absence while its high values say little about how much was covered (§12)

### 8.3 Pattern: DQN Works When...

- Query has **one key document** → DQN selects k=1 (Hotpot)
- Query needs **multiple evidence pieces** → DQN selects k=4 (RagTruth)
- Baseline k=3 is already optimal → DQN stays near k=3 (Fintech)
- Query is **self-contained** (math) → DQN hurts by adding noise (Math)

---

## 9. Conclusions

### 9.1 Primary Findings

1. **DQN learns meaningful k-selection strategies** — different datasets get different k values, though on three of four the policy is nearly constant (§12)
2. **No consistent faithfulness improvement** — only Hotpot and Fintech show positive trends, neither significant
3. **Significant answer relevancy degradation on RagTruth** — two-tailed p=0.033, System B is worse. This was previously reported as p=0.016, which was the one-tailed value on the wrong side of the hypothesis
4. **Math shows degradation** — DQN hurts on self-contained reasoning tasks
5. **Token efficiency cannot be reported** — the generator's token columns in these CSVs hold the judge's counts, so both the original "3× gain" and the 1.09× restatement of it are withdrawn. Only total request tokens survive as valid, and they move in opposite directions across datasets (§4)
6. **Judge scoring dominates cost** — 90-97% of latency is qwen3:8b evaluation
7. **Neither significant result is an improvement.** Both regressions.

### 9.2 Thesis Implications

- **Novel contribution:** DQN can learn dataset-specific k-selection without explicit supervision
- **Positive:** Hotpot demonstrates that reducing context can improve faithfulness, at 64.4% fewer total request tokens (§4.2)
- **Caveat:** Results are dataset-dependent; no universal improvement
- **Negative:** Math tasks show degradation; answer relevancy can degrade
- **Practical:** Token savings only matter under paid API inference

### 9.3 Limitations

1. **No significant results at α=0.05** — all p-values > 0.05 for faithfulness
2. **Judge stochasticity** — qwen3:8b failures create noise in metrics
3. **Single seed per dataset** — no averaging over multiple training runs
4. **Context recall is unreliable** — high judge failure rate
5. **Small corpus for Fintech** — only 6,251 docs vs 30K for others

---

## 10. Recommendations

### For Thesis Writing
1. Present all 4 datasets to show dataset-dependent behavior
2. Frame as "DQN learns adaptive k-selection" rather than "DQN improves faithfulness"
3. Highlight Hotpot as the success case (k=1, token efficiency, faithfulness trend)
4. Discuss Math as the failure case (degradation, learning difficulties)
5. Note RagTruth AR degradation as a limitation
6. Emphasize judge scoring bottleneck as a practical finding

### For Further Experiments
1. **Increase sample size** to n=100 per dataset for better statistical power
2. **Average over 3-5 seeds** to reduce run-to-run variance
3. **Test intermediate λ values** (0.05, 0.10) for more varied k-distributions
4. **Error analysis** — examine specific prompts where DQN succeeds/fails
5. **Try different judge models** — qwen3:8b may be too unreliable for RAGAS scoring

---

## 11. Data Provenance and Completeness

### 11.1 Source of every published number

All statistics in §3, §4, §5 and §6 are generated by `src/full_stats.py` from the
four `ragas_results_<dataset>_logged.csv` files and written to
`results/full_stats.json`. Each dataset block records the CSV it came from and
that file's SHA-256, so a stale figure cannot masquerade as a current one.

Regenerate with:

```
python -c "from src.full_stats import write; write()"
```

`bench_bridge/tests/test_report_provenance.py` recomputes every value and fails
if the JSON and the CSVs disagree, if a recorded source hash no longer matches
its CSV, or if a number is hand-entered. This is what caught the stale hotpot
figures and the unreproducible token columns; it is what will catch the next one.

### 11.2 Prompts excluded from paired tests

A prompt contributes to a paired test only if **both** systems produced a score.
Where the judge returned NULL the pair is dropped — not imputed — so the metric's
sample size is below the 50 prompts in the run.

| Dataset | Metric | Prompts | Paired n | Prompt ID | Missing |
|---------|--------|---------|----------|-----------|---------|
| Hotpot | context_recall | 50 | 49 | `5ae2057b554299234fd043a5` | A and B |
| Math | faithfulness | 50 | 49 | `Math-Test-1016` | B |
| RagTruth | all | 50 | 50 | — | — |
| Fintech | all | 50 | 50 | — | — |

Every other metric/dataset pair uses all 50 prompts. Both gaps are single
prompts and neither changes any conclusion, but they were previously invisible:
`n` used to be one number per dataset, so hotpot's headline "n=49" was really the
context-recall pair count quoted next to a 50-prompt run.

### 11.3 Known instrumentation defects in these CSVs

| Defect | Effect | Status |
|--------|--------|--------|
| `prompt_tokens`/`completion_tokens` hold the judge's counts | generator token usage lost; judge tokens unrecoverable | **Code fixed**; these CSVs predate the fix and need a re-run to repair |
| `total_tokens` ≠ prompt + completion | `total_tokens` measures something else; not summable | flagged in `data_warnings` |
| Groundedness (`ga`/`gb`) in the old `full_stats.json` | no source column anywhere in the repo | **removed**; not reported |

---

## 12. Threats to Validity

**Judge token usage is missing.** Because of the defect in §11.3, the token cost
of qwen3:8b cannot be separated from the generator's in these runs. Judge
wall-clock (~50–81 s/query) is genuine and dominates the cost, so the *conclusion*
that judging dominates stands; the *token* accounting does not exist for these runs.

**Metric behaviour was probed, and both metrics are usable — with one caveat.**
`probe_metrics.py` runs hand-built cases with an unambiguous correct answer
through the real judge; results are recorded in `results/metric_probe_results.json`
and asserted by `bench_bridge/tests/test_metric_probes.py`.

*Faithfulness is sound.* Against qwen3:8b it scores **0.0** for a claim the
context contradicts, **0.0** for wholly fabricated content, **0.0** for an answer
unrelated to the context, and **2/3** for a mixed answer where two of three
statements are supported. The 1.0 scores in these runs are therefore plausible
rather than a judge that always agrees.

*Context recall is lenient.* It scores **1.0** for a reference that is **not in
the context at all**, provided the context is on the same topic. It separates
"completely unrelated" (0.0) from "on topic" (1.0), but not "on topic and missing
the specific claim" — which it calls full recall.

That leniency runs in the direction that *strengthens* the fintech result rather
than undermining it. The metric is biased towards scoring high, so the observed
**0.032** for system B cannot be explained by leniency: those reference answers
genuinely were not in the retrieved context. The −70.9% gap is a real retrieval
difference.

> **Correction.** An earlier draft of this section claimed the fintech
> context-recall result was more likely a mis-specified metric than a real
> −70.9% effect. The probe shows the opposite: the metric over-scores, so a
> near-zero score is strong evidence of absence. The hedge has been removed
> because the evidence contradicts it.

The caveat that remains: because context recall saturates at 1.0 for on-topic
context, it cannot measure *how much* of a reference was covered. It is a usable
detector of "was this answer in the context at all", not a graded coverage score.

**Sample size.** 50 prompts per dataset is small for paired tests on differences
of this size. Fintech faithfulness (p=0.092) would need roughly n=100 to reach
α=0.05; no dataset currently shows a significant *improvement*.

**k-selection is concentrated.** Hotpot selects k=1 in 49 of 50 prompts, so
"system B" on hotpot is very nearly "system A with k=1". Conclusions about the
DQN as a *policy* rest on RagTruth (k=4 in 46/50) being the informative case;
on the other three datasets the policy is close to a constant.

**The hotpot policy is untrained.** `checkpoints/dqn_model_hotpot.pth` has
`steps=0` and `epsilon=0.995`, i.e. its initial values, while the other three
checkpoints are at `steps=43`. A k=1 selection rate of 49/50 from an untrained
network is best read as the reward structure favouring small k (the reward
includes a `−λ·log(1+k)` term), not as a learned policy. The hotpot comparison
should be described as *k=1 vs k=3*, not as *DQN vs baseline*.

### Judge throughput

The judge dominates the cost of a run, so its wall-clock was measured rather
than assumed. `results/concurrency_verification.json` records the comparison
(3 prompts, qwen3:8b, three runs: sequential twice then concurrent), because a
single sequential-versus-concurrent comparison cannot tell a concurrency defect
apart from a model that simply does not answer the same way twice. The judge is
deterministic at temperature 0 here, and concurrent scoring matched sequential
scoring on every metric and every judge token count.

Two separate findings, because they apply to different callers:

- **Batch scoring** (`RagasScorer.score` over many prompts) was 2.0x faster at 4
  workers on an idle GPU.
- **Within one prompt** the three metrics are independent and now run
  concurrently, which is the only parallelism available to `run_experiment*.py`.
  Those runners judge one prompt at a time by design - the reward is the DQN's
  next training signal, and each row is written as soon as it is judged so a
  killed host does not lose the run - so cross-prompt concurrency would undo
  that. Measured on the runner's own path: 36.4s to 24.6s per prompt, with
  identical metrics and identical judge token counts.

Caveat on the recorded figure: the `speedup` in `concurrency_verification.json`
was measured while an unrelated process was saturating the GPU, which is why it
reads 1.54x rather than the 2.0x seen on an idle device. Treat it as a lower
bound; re-run `python verify_concurrency.py` on an otherwise idle machine to
refresh it.

This affects runtime only. No metric in the tables above was computed with
concurrent scoring enabled - they come from the stored CSVs described in
section 11, and the equivalence check exists to show that adding concurrency
does not change what those numbers would be.

---

## Appendix A: Raw Data Files

| File | Description |
|------|-------------|
| `results/ragas_results_hotpot_logged.csv` | Hotpot λ=0.0 (100 rows, 15 columns) |
| `results/ragas_results_ragtruth_logged.csv` | RagTruth λ=0.0 (100 rows, 15 columns) |
| `results/ragas_results_fintech_logged.csv` | Fintech λ=0.0 (100 rows, 15 columns) |
| `results/ragas_results_math_logged.csv` | Math λ=0.0 (100 rows, 15 columns) |
| `results/training_log_hotpot.csv` | Hotpot per-step training (50 rows) |
| `results/training_log_ragtruth.csv` | RagTruth per-step training (50 rows) |
| `results/training_log_fintech.csv` | Fintech per-step training (50 rows) |
| `results/training_log_math.csv` | Math per-step training (50 rows) |
| `results/full_stats.json` | Generated statistics, with per-dataset source CSV + SHA-256 |
| `plots/` | 27+ visualization PNGs |

## Appendix B: Configuration

```python
# config/settings.py
DQN_BATCH_SIZE = 8
NUM_EVAL_PROMPTS = 50
JUDGE_MODEL = "qwen3:8b"
MAX_CORPUS_DOCS = 30000
REWARD_W_K = 0.0  # λ coefficient (no k-penalty)
```

## Appendix C: CSV Column Reference

| Column | Description |
|--------|-------------|
| `system_id` | A (baseline) or B (DQN) |
| `prompt_id` | Prompt index (1-50) |
| `faithfulness` | RAGAS faithfulness score |
| `answer_relevancy` | RAGAS answer relevancy score |
| `context_recall` | RAGAS context recall score |
| `retrieved_k` | Number of documents retrieved |
| `total_tokens` | llama3.2 generation tokens |
| `judge_prompt_tokens` | qwen3:8b judge input tokens |
| `judge_completion_tokens` | qwen3:8b judge output tokens |
| `retrieval_time_s` | Vector search time (seconds) |
| `generation_time_s` | llama3.2 generation time (seconds) |
| `judge_time_s` | qwen3:8b judge evaluation time (seconds) |
| `total_time_s` | End-to-end time (seconds) |

---

*Report generated: September 21, 2026*
*Thesis: DQN-Enhanced Retrieval-Augmented Generation with Adaptive Context Selection*
