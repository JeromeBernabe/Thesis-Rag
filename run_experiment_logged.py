"""Run experiment with full per-step training logging for visualization."""
import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from prompts.build_eval_prompts import build_eval_prompts, load_eval_prompts
from src.baseline_rag import BaselineRAG
from src.data_loader import build_indexed_corpus, format_doc_text
from src.dqn_agent import DQNAgent
from src.dqn_rag import DQNRAG
from src.logger import ResultLogger, promote
from src.ragas_eval import RagasScorer
from src.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_experiment")

TRAINING_CSV_COLUMNS = [
    "step", "k", "faithfulness", "answer_relevancy", "context_recall",
    "reward", "loss", "epsilon", "q_values_k1", "q_values_k2",
    "q_values_k3", "q_values_k4", "q_values_k5",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "judge_prompt_tokens", "judge_completion_tokens",
    "embedding_time_s", "retrieval_time_s", "generation_time_s",
    "judge_time_s", "total_time_s",
]


class TrainingLogger:
    """Append-only CSV sink for per-step training dynamics.

    Same rule as `ResultLogger`, for the same reason: opening with ``"w"``
    deletes the previous run's training log, and on this dataset training is
    two to three hours of 50 steps that nothing can reconstruct. The header is
    written only when the file is new, and each step is flushed and fsynced so
    a killed host still leaves the steps that completed.
    """

    def __init__(self, path: Path, *, fresh: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fresh or not (self.path.exists() and self.path.stat().st_size > 0):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRAINING_CSV_COLUMNS)
                writer.writeheader()
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

    def log(self, row: dict) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TRAINING_CSV_COLUMNS)
            writer.writerow(row)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass


def get_q_values(agent: DQNAgent, state) -> list[float]:
    """Q-values for every action; delegates to the agent's own accessor."""
    return agent.q_values(state)


def collection_name_for(dataset: str) -> str:
    return settings.DATASET_COLLECTION_NAMES.get(dataset, "math_docs")


def index_corpus(dataset: str, store: VectorStore, data_dir=None) -> int:
    ids, records = build_indexed_corpus(dataset, data_dir)
    if not records:
        raise SystemExit(f"No {dataset} records found.")
    if settings.MAX_CORPUS_DOCS and len(records) > settings.MAX_CORPUS_DOCS:
        logger.info("%s: limiting corpus from %d to %d", dataset, len(records), settings.MAX_CORPUS_DOCS)
        ids = ids[:settings.MAX_CORPUS_DOCS]
        records = records[:settings.MAX_CORPUS_DOCS]
    if store.count > 0:
        logger.info("%s: vector store has %d docs; skipping indexing.", dataset, store.count)
        return store.count
    documents = [format_doc_text(dataset, r) for r in records]
    batch_size = 128
    for start in range(0, len(documents), batch_size):
        store.add_documents(ids[start:start + batch_size], documents[start:start + batch_size])
        logger.info("%s: indexed %d/%d", dataset, min(start + batch_size, len(documents)), len(documents))
    return store.count


def run_system_a(dataset: str, prompts: list[dict], result_logger: ResultLogger) -> None:
    logger.info("[%s] Running System A (baseline, k=%d) on %d prompts...", dataset, settings.BASELINE_K, len(prompts))
    baseline = BaselineRAG(VectorStore(collection_name=collection_name_for(dataset)), dataset=dataset)
    scorer = RagasScorer()

    # Scored and written one prompt at a time rather than in a single batch at
    # the end. Batch scoring holds every row in memory until the last prompt is
    # judged, and System A's scoring pass alone took 1h39m on 50 prompts - so a
    # host killed during that window lost the generation *and* the judging, which
    # is the entire cost of the run. `score_single` is the same code path as
    # `score` with a one-element list, so this changes when rows are written, not
    # what is written.
    for i, prompt in enumerate(prompts):
        result = baseline.answer(prompt["question"])
        scores = scorer.score_single(
            prompt["question"],
            result["answer"],
            result["contexts"],
            reference=prompt.get("ground_truth"),
        )
        result_logger.log(
            prompt_id=prompt["id"], system_id="A",
            faithfulness=scores.get("faithfulness"),
            answer_relevancy=scores.get("answer_relevancy"),
            context_recall=scores.get("context_recall"),
            retrieved_k=settings.BASELINE_K,
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            total_tokens=result["total_tokens"],
            judge_prompt_tokens=scores.get("judge_prompt_tokens"),
            judge_completion_tokens=scores.get("judge_completion_tokens"),
            retrieval_time_s=result["retrieval_time_s"],
            generation_time_s=result["generation_time_s"],
            judge_time_s=scores.get("judge_time_s"),
            total_time_s=result["retrieval_time_s"] + result["generation_time_s"] + scores.get("judge_time_s", 0.0),
        )
        if (i + 1) % 10 == 0 or i == len(prompts) - 1:
            logger.info("  System A: %d/%d", i + 1, len(prompts))
    logger.info("[%s] System A complete.", dataset)


def run_system_b(dataset: str, prompts: list[dict], result_logger: ResultLogger, training_csv: Path) -> None:
    logger.info("[%s] Running System B (DQN) on %d prompts...", dataset, len(prompts))
    scorer = RagasScorer()
    agent = DQNAgent()
    dqn = DQNRAG(VectorStore(collection_name=collection_name_for(dataset)), scorer, agent=agent, dataset=dataset)
    tlog = TrainingLogger(training_csv)

    logger.info("[%s] Phase B.1: training DQN...", dataset)
    for i, prompt in enumerate(prompts):
        episode = dqn.train_episode(prompt["question"], prompt.get("ground_truth"))

        import torch, numpy as np
        state = dqn._state(prompt["question"])
        q_vals = get_q_values(agent, state)

        tlog.log({
            "step": i + 1, "k": episode["k"],
            "faithfulness": episode["faithfulness"] if episode["faithfulness"] is not None else "",
            "answer_relevancy": episode["answer_relevancy"] if episode["answer_relevancy"] is not None else "",
            "context_recall": episode["context_recall"] if episode["context_recall"] is not None else "",
            "reward": episode["reward"],
            "loss": f"{episode['loss']:.6f}" if episode["loss"] is not None else "",
            "epsilon": episode["epsilon"],
            "q_values_k1": f"{q_vals[0]:.4f}", "q_values_k2": f"{q_vals[1]:.4f}",
            "q_values_k3": f"{q_vals[2]:.4f}", "q_values_k4": f"{q_vals[3]:.4f}",
            "q_values_k5": f"{q_vals[4]:.4f}",
            "prompt_tokens": episode["prompt_tokens"],
            "completion_tokens": episode["completion_tokens"],
            "total_tokens": episode["total_tokens"],
            "judge_prompt_tokens": episode["judge_prompt_tokens"],
            "judge_completion_tokens": episode["judge_completion_tokens"],
            "embedding_time_s": f"{episode['embedding_time_s']:.4f}",
            "retrieval_time_s": f"{episode['retrieval_time_s']:.4f}",
            "generation_time_s": f"{episode['generation_time_s']:.4f}",
            "judge_time_s": f"{episode['judge_time_s']:.4f}",
            "total_time_s": f"{episode['total_time_s']:.4f}",
        })

        loss_str = f"{episode['loss']:.4f}" if episode["loss"] is not None else "n/a"
        logger.info("  step %d/%d | k=%d | F=%.3f AR=%.3f CR=%.3f | R=%.3f | loss=%s | eps=%.3f | %.1fs",
                     i + 1, len(prompts), episode["k"],
                     episode["faithfulness"] if episode["faithfulness"] is not None else float("nan"),
                     episode["answer_relevancy"] if episode["answer_relevancy"] is not None else float("nan"),
                     episode["context_recall"] if episode["context_recall"] is not None else float("nan"),
                     episode["reward"], loss_str, episode["epsilon"], episode["total_time_s"])

    logger.info("[%s] Phase B.2: inference (greedy)...", dataset)
    # Same reasoning as System A: infer, judge and write one prompt at a time, so
    # the run is worth what it has already paid for even if it is killed. The
    # training phase above is the long pole, and this is what would otherwise
    # throw away two hours of training by dying in the half hour after it.
    ks = []
    for i, prompt in enumerate(prompts):
        result = dqn.answer(prompt["question"])
        ks.append(result["k"])
        scores = scorer.score_single(
            prompt["question"],
            result["answer"],
            result["contexts"],
            reference=prompt.get("ground_truth"),
        )
        result_logger.log(
            prompt_id=prompt["id"], system_id="B",
            faithfulness=scores.get("faithfulness"),
            answer_relevancy=scores.get("answer_relevancy"),
            context_recall=scores.get("context_recall"),
            retrieved_k=result["k"],
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            total_tokens=result["total_tokens"],
            judge_prompt_tokens=scores.get("judge_prompt_tokens"),
            judge_completion_tokens=scores.get("judge_completion_tokens"),
            retrieval_time_s=result["retrieval_time_s"],
            generation_time_s=result["generation_time_s"],
            judge_time_s=scores.get("judge_time_s"),
            total_time_s=result["retrieval_time_s"] + result["generation_time_s"] + scores.get("judge_time_s", 0.0),
        )
        if (i + 1) % 10 == 0 or i == len(prompts) - 1:
            logger.info("  System B inference: %d/%d", i + 1, len(prompts))
    from collections import Counter
    logger.info("[%s] System B complete. k-distribution: %s", dataset, dict(Counter(ks)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--results", default=None)
    parser.add_argument("--training-csv", default=None, help="Path for per-step training CSV")
    parser.add_argument("--skip-a", action="store_true")
    parser.add_argument("--skip-b", action="store_true")

    args = parser.parse_args()

    dataset = args.dataset.lower()
    if dataset not in settings.VALID_DATASETS:
        raise SystemExit(f"Unknown dataset: {dataset}")

    prompts = load_eval_prompts(dataset)[:args.limit]
    logger.info("[%s] Loaded %d prompts.", dataset, len(prompts))

    store = VectorStore(collection_name=collection_name_for(dataset))
    index_corpus(dataset, store)

    results_path = args.results or str(settings.RESULTS_DIR / f"ragas_results_{dataset}_logged.csv")
    training_csv = args.training_csv or str(settings.RESULTS_DIR / f"training_log_{dataset}.csv")

    # Staged, then renamed into place on success. See `src.logger.promote`: a
    # completed CSV cannot be appended to without producing duplicate
    # (prompt_id, system_id) pairs, which makes the paired analysis raise rather
    # than merely misreport. Staging keeps the previous results readable while a
    # new run is in flight, so a crash costs this run's hours rather than the
    # last run's too.
    results_path = Path(results_path)
    training_csv = Path(training_csv)
    staged_results = results_path.with_name(results_path.name + ".partial")
    staged_training = training_csv.with_name(training_csv.name + ".partial")
    for stale in (staged_results, staged_training):
        if stale.exists():
            logger.info("[%s] Discarding partial output from an earlier attempt: %s", dataset, stale.name)
            stale.unlink()

    result_logger = ResultLogger(staged_results)
    start = time.time()
    if not args.skip_a:
        run_system_a(dataset, prompts, result_logger)
    if not args.skip_b:
        run_system_b(dataset, prompts, result_logger, staged_training)

    # Only now, with both systems judged, does the new output become the
    # official one. A failure above propagates and leaves the previous results in
    # place alongside the .partial file.
    promote(staged_results, results_path)
    if staged_training.exists():
        promote(staged_training, training_csv)
    logger.info("[%s] Done in %.1fs. Results: %s | Training: %s", dataset, time.time() - start, results_path, training_csv)


if __name__ == "__main__":
    main()
