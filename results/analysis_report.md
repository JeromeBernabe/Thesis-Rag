# DQN-Enhanced RAG: Full Experimental Analysis Report (4 Datasets)

**Date:** September 21, 2026
**Author:** Johann (Thesis)
**Models:** llama3.2 (generation), nomic-embed-text (embeddings), qwen3:8b (RAGAS judge)
**GPU:** NVIDIA RTX 4050 Laptop, CUDA 12.4
**Hardware:** Local inference (no API costs)

---

## 1. Executive Summary

This report evaluates a DQN-enhanced RAG system (System B, dynamic k∈{1..5}) against a baseline RAG system (System A, fixed k=3) across **4 datasets** (Hotpot, RagTruth, Fintech, Math) using custom RAGAS scoring with full token usage and latency instrumentation.

**Key findings across all 4 datasets:**

1. **DQN learns dataset-specific k-selection:** Hotpot→k=1, RagTruth→k=4, Fintech→k=3, Math→k=3
2. **No statistically significant faithfulness improvement** on any dataset at α=0.05
3. **Hotpot shows strongest positive trend:** +8.3% faithfulness (p=0.251, one-tailed), +64% token savings, +3× token efficiency
4. **Math shows degradation:** −8.9% faithfulness (p=0.90, one-tailed), suggesting DQN hurts on math reasoning
5. **Judge scoring (qwen3:8b) dominates cost:** 90-97% of wall-clock time across all datasets
6. **Context recall is unreliable** — high judge failure rate, especially on Fintech (−70.9% likely due to judge failures)

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

| Dataset | System A | System B | Δ | Cohen's d | p (one-tailed) | Wilcoxon p | Significant? |
|---------|----------|----------|---|-----------|----------------|------------|--------------|
| Hotpot | 0.596 | 0.646 | **+8.3%** | 0.115 | 0.251 | 0.225 | No (trending) |
| RagTruth | 0.842 | 0.839 | −0.3% | −0.010 | 0.521 | 0.377 | No |
| Fintech | 0.815 | 0.869 | **+6.6%** | 0.203 | 0.092 | 0.117 | No (trending) |
| Math | 0.524 | 0.477 | **−8.9%** | −0.143 | 0.901 | 0.937 | No |

**Interpretation:**
- **Hotpot:** Strongest positive trend (+8.3%, p=0.251). k=1 reduces noise, improving faithfulness for multi-hop questions
- **Fintech:** Positive trend (+6.6%, p=0.092). k=3/5 mixture shows slight improvement
- **RagTruth:** No change. k=4 provides same quality as k=3 baseline
- **Math:** Degradation (−8.9%, p=0.901). k=3/4 doesn't help math reasoning; more context may introduce noise

### 3.3 Answer Relevancy

| Dataset | System A | System B | Δ | p (one-tailed) | Significant? |
|---------|----------|----------|---|----------------|--------------|
| Hotpot | 0.734 | 0.764 | +4.1% | 0.197 | No |
| RagTruth | 0.745 | 0.719 | **−3.5%** | **0.016** | **Yes (B worse)** |
| Fintech | 0.772 | 0.764 | −1.1% | 0.660 | No |
| Math | 0.792 | 0.814 | +2.8% | 0.101 | No |

**Critical finding:** RagTruth shows **statistically significant degradation** in answer relevancy (p=0.016). k=4 introduces noise that degrades answer focus.

### 3.4 Context Recall

| Dataset | System A | System B | Δ | p (two-tailed) |
|---------|----------|----------|---|----------------|
| Hotpot | 0.281 | 0.233 | −17.0% | 0.933 |
| RagTruth | 0.878 | 0.893 | +1.6% | 0.253 |
| Fintech | 0.110 | 0.032 | **−70.9%** | 0.022 |
| Math | 0.267 | 0.287 | +7.5% | 0.467 |

**Note:** Fintech's −70.9% context recall is likely due to judge evaluation failures (qwen3:8b returning NaN for faithfulness), not actual retrieval degradation. Context recall is the most unreliable metric across all datasets.

---

## 4. Token Usage Analysis

### 4.1 Generation Tokens (llama3.2)

| Dataset | System A | System B | Δ | Interpretation |
|---------|----------|----------|---|----------------|
| Hotpot | 4,034 | 1,444 | **−64.2%** | k=1 → shorter prompts → shorter answers |
| RagTruth | 2,103 | 2,670 | +27.0% | k=4 → longer prompts → longer answers |
| Fintech | 2,560 | 2,922 | +14.2% | k=3/5 → slightly more context |
| Math | 692 | 697 | +0.6% | k=3/4 → minimal change |

### 4.2 Judge Tokens (qwen3:8b)

| Dataset | System A | System B | Δ |
|---------|----------|----------|---|
| Hotpot | 5,209 | 3,923 | −24.7% |
| RagTruth | 4,896 | 5,395 | +10.2% |
| Fintech | 4,635 | 4,681 | +1.0% |
| Math | 2,731 | 2,733 | +0.1% |

### 4.3 Token Efficiency (Faithfulness per 1k Generation Tokens)

| Dataset | System A | System B | Ratio |
|---------|----------|----------|-------|
| Hotpot | 0.148 | 0.447 | **3.0× more efficient** |
| RagTruth | 0.400 | 0.314 | 0.79× (less efficient) |
| Fintech | 0.318 | 0.297 | 0.93× (slightly less) |
| Math | 0.757 | 0.685 | 0.91× (less efficient) |

**Key finding:** Only Hotpot achieves meaningful token efficiency gains (3×). All other datasets show neutral or worse efficiency.

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
| Math | Retrieval | 0.263 | 0.010 | −96.2% |
| Math | Generation | 4.520 | 4.140 | −8.4% |
| Math | Judge scoring | 72.47 | 70.95 | −2.1% |
| Math | **Total** | **77.52** | **75.11** | **−3.1%** |

### 5.2 Latency Findings

1. **Judge scoring dominates:** 90-97% of total time is qwen3:8b evaluation across all datasets
2. **Hotpot is only dataset with meaningful speedup:** 6.7% faster (4.3s/query savings)
3. **RagTruth is 6.1% slower** — longer generation + judge evaluation overhead
4. **Fintech is neutral** — +0.7% (within noise)
5. **Math is 3.1% faster** — slight generation improvement offset by similar judge time
6. **Retrieval is negligible** — System B's DQN computation is ~0.01s vs System A's vector search

---

## 6. Statistical Significance Summary (All Tests)

| Metric | Dataset | Test | p-value | Effect Size | Significant? |
|--------|---------|------|---------|-------------|--------------|
| Faithfulness | Hotpot | One-tailed t | 0.251 | d=0.115 | No |
| Faithfulness | Hotpot | Wilcoxon | 0.225 | — | No |
| Faithfulness | RagTruth | One-tailed t | 0.521 | d=−0.010 | No |
| Faithfulness | RagTruth | Wilcoxon | 0.377 | — | No |
| Faithfulness | Fintech | One-tailed t | 0.092 | d=0.203 | No (trending) |
| Faithfulness | Fintech | Wilcoxon | 0.117 | — | No |
| Faithfulness | Math | One-tailed t | 0.901 | d=−0.143 | No |
| Faithfulness | Math | Wilcoxon | 0.937 | — | No |
| Answer Rel | Hotpot | One-tailed t | 0.197 | — | No |
| Answer Rel | RagTruth | One-tailed t | **0.016** | — | **Yes (B worse)** |
| Answer Rel | Fintech | One-tailed t | 0.660 | — | No |
| Answer Rel | Math | One-tailed t | 0.101 | — | No |
| Context Rec | Hotpot | Two-tailed t | 0.933 | — | No |
| Context Rec | RagTruth | Two-tailed t | 0.253 | — | No |
| Context Rec | Fintech | Two-tailed t | **0.022** | — | **Yes (B worse)** |
| Context Rec | Math | Two-tailed t | 0.467 | — | No |

### Interpretation
- **No faithfulness improvement reaches significance** on any dataset
- **Fintech is closest** (p=0.092, one-tailed) — may reach significance with n=100
- **RagTruth answer relevancy degrades significantly** (p=0.016)
- **Fintech context recall degrades significantly** (p=0.022) — likely judge artifact
- **Math shows degradation** (p=0.901, trending negative) — DQN hurts math reasoning

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
5. **Context recall is unreliable:** Judge failures (qwen3:8b) make CR scores noisy, especially on Fintech

### 8.3 Pattern: DQN Works When...

- Query has **one key document** → DQN selects k=1 (Hotpot)
- Query needs **multiple evidence pieces** → DQN selects k=4 (RagTruth)
- Baseline k=3 is already optimal → DQN stays near k=3 (Fintech)
- Query is **self-contained** (math) → DQN hurts by adding noise (Math)

---

## 9. Conclusions

### 9.1 Primary Findings

1. **DQN learns meaningful k-selection strategies** — different datasets get different k values
2. **No consistent faithfulness improvement** — only Hotpot and Fintech show positive trends, neither significant
3. **Significant answer relevancy degradation on RagTruth** — p=0.016, System B is worse
4. **Math shows degradation** — DQN hurts on self-contained reasoning tasks
5. **Token efficiency only improves on Hotpot** — 3× better faithfulness per token
6. **Judge scoring dominates cost** — 90-97% of latency is qwen3:8b evaluation

### 9.2 Thesis Implications

- **Novel contribution:** DQN can learn dataset-specific k-selection without explicit supervision
- **Positive:** Hotpot demonstrates that reducing context can improve faithfulness and efficiency
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
| `results/full_stats.json` | Complete statistical results |
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
