import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from prompts.build_eval_prompts import build_eval_prompts, load_eval_prompts  # noqa: E402
from src.baseline_rag import BaselineRAG  # noqa: E402
from src.data_loader import build_indexed_corpus, format_doc_text  # noqa: E402
from src.dqn_agent import DQNAgent  # noqa: E402
from src.dqn_rag import DQNRAG  # noqa: E402
from src.logger import ResultLogger, promote  # noqa: E402
from src.ragas_eval import RagasScorer  # noqa: E402
from src.vector_store import VectorStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_experiment")


def collection_name_for(dataset: str) -> str:
    return settings.DATASET_COLLECTION_NAMES.get(dataset, "math_docs")


def index_corpus(dataset: str, store: VectorStore, data_dir=None) -> int:
    ids, records = build_indexed_corpus(dataset, data_dir)
    if not records:
        raise SystemExit(
            f"No {dataset} records found in {settings.DATASETS_DIR}. Drop data files there first."
        )
    if settings.MAX_CORPUS_DOCS and len(records) > settings.MAX_CORPUS_DOCS:
        logger.info("%s: limiting corpus from %d to %d documents.", dataset, len(records), settings.MAX_CORPUS_DOCS)
        ids = ids[:settings.MAX_CORPUS_DOCS]
        records = records[:settings.MAX_CORPUS_DOCS]
    if store.count > 0:
        logger.info("%s: vector store already has %d documents; skipping indexing.", dataset, store.count)
        return store.count
    documents = [format_doc_text(dataset, r) for r in records]
    batch_size = 128
    for start in range(0, len(documents), batch_size):
        store.add_documents(
            ids[start:start + batch_size],
            documents[start:start + batch_size],
        )
        logger.info("%s: indexed %d/%d documents", dataset, min(start + batch_size, len(documents)), len(documents))
    logger.info("%s: indexed %d documents into '%s'.", dataset, store.count, settings.DATASET_COLLECTION_NAMES.get(dataset))
    return store.count


def run_system_a(dataset: str, prompts: list[dict], logger_out: ResultLogger) -> None:
    logger.info("[%s] Running System A (baseline RAG, k=%d) on %d prompts...", dataset, settings.BASELINE_K, len(prompts))
    baseline = BaselineRAG(VectorStore(collection_name=collection_name_for(dataset)), dataset=dataset)
    scorer = RagasScorer()
    # Judged and written per prompt. The old version generated every answer,
    # then judged all of them, then wrote - so a kill during the (long) scoring
    # pass lost the whole run, which is exactly what happened to the math run.
    for i, prompt in enumerate(prompts):
        result = baseline.answer(prompt["question"])
        scores = scorer.score_single(
            prompt["question"],
            result["answer"],
            result["contexts"],
            reference=prompt.get("ground_truth"),
        )
        logger_out.log(
            prompt_id=prompt["id"],
            system_id="A",
            faithfulness=scores.get("faithfulness"),
            answer_relevancy=scores.get("answer_relevancy"),
            context_recall=scores.get("context_recall"),
            retrieved_k=settings.BASELINE_K,
            prompt_tokens=scores.get("judge_prompt_tokens"),
            completion_tokens=scores.get("judge_completion_tokens"),
            total_tokens=result["total_tokens"],
            judge_prompt_tokens=scores.get("judge_prompt_tokens"),
            judge_completion_tokens=scores.get("judge_completion_tokens"),
            retrieval_time_s=result["retrieval_time_s"],
            generation_time_s=result["generation_time_s"],
            judge_time_s=scores.get("judge_time_s"),
            total_time_s=result["retrieval_time_s"] + result["generation_time_s"] + scores.get("judge_time_s", 0.0),
        )
        if (i + 1) % 10 == 0 or i == len(prompts) - 1:
            logger.info("  System A answered %d/%d prompts", i + 1, len(prompts))
    logger.info("[%s] System A complete: %d rows logged.", dataset, len(prompts))


def run_system_b(dataset: str, prompts: list[dict], logger_out: ResultLogger) -> None:
    logger.info("[%s] Running System B (DQN-RAG) on %d prompts...", dataset, len(prompts))
    scorer = RagasScorer()
    agent = DQNAgent()
    dqn = DQNRAG(VectorStore(collection_name=collection_name_for(dataset)), scorer, agent=agent, dataset=dataset)

    logger.info("[%s] Phase B.1: training DQN (single-step episodes, epsilon-greedy)...", dataset)
    for i, prompt in enumerate(prompts):
        episode = dqn.train_episode(prompt["question"], prompt.get("ground_truth"))
        logger.info(
            "  step %d/%d | k=%d | F=%.3f AR=%.3f CR=%.3f | R=%.3f | loss=%s | eps=%.3f | %.1fs",
            i + 1,
            len(prompts),
            episode["k"],
            episode["faithfulness"] if episode["faithfulness"] is not None else float("nan"),
            episode["answer_relevancy"] if episode["answer_relevancy"] is not None else float("nan"),
            episode.get("context_recall") if episode.get("context_recall") is not None else float("nan"),
            episode["reward"],
            f"{episode['loss']:.4f}" if episode["loss"] is not None else "n/a",
            episode["epsilon"],
            episode["total_time_s"],
        )

    logger.info("[%s] Phase B.2: inference (greedy policy) on %d prompts...", dataset, len(prompts))
    # Per prompt for the same reason as System A: two hours of training must not
    # be discarded by a kill in the half hour that follows it.
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
        logger_out.log(
            prompt_id=prompt["id"],
            system_id="B",
            faithfulness=scores.get("faithfulness"),
            answer_relevancy=scores.get("answer_relevancy"),
            context_recall=scores.get("context_recall"),
            retrieved_k=result["k"],
            prompt_tokens=scores.get("judge_prompt_tokens"),
            completion_tokens=scores.get("judge_completion_tokens"),
            total_tokens=result["total_tokens"],
            judge_prompt_tokens=scores.get("judge_prompt_tokens"),
            judge_completion_tokens=scores.get("judge_completion_tokens"),
            retrieval_time_s=result["retrieval_time_s"],
            generation_time_s=result["generation_time_s"],
            judge_time_s=scores.get("judge_time_s"),
            total_time_s=result["retrieval_time_s"] + result["generation_time_s"] + scores.get("judge_time_s", 0.0),
        )
    from collections import Counter

    logger.info("[%s] System B complete. Retrieved-k distribution (inference): %s", dataset, dict(Counter(ks)))


def run_dataset(
    dataset: str,
    limit: int | None,
    build_prompts: bool,
    reset_store: bool,
    skip_a: bool,
    skip_b: bool,
    results_path,
    data_dir=None,
) -> None:
    dataset = dataset.lower()
    if dataset not in settings.VALID_DATASETS:
        raise SystemExit(f"Unknown dataset {dataset!r}. Must be one of {settings.VALID_DATASETS}")

    if build_prompts:
        build_eval_prompts(dataset=dataset, num_prompts=settings.NUM_EVAL_PROMPTS, data_dir=data_dir)

    prompts = load_eval_prompts(dataset)
    if limit is not None:
        prompts = prompts[:limit]
    if not prompts:
        raise SystemExit(
            f"No {dataset} prompts found. Run with --build-prompts to generate them."
        )
    logger.info("[%s] Loaded %d evaluation prompts.", dataset, len(prompts))

    store = VectorStore(collection_name=collection_name_for(dataset), reset=reset_store)
    index_corpus(dataset, store, data_dir=data_dir)

    # Stage, then publish on success. See `src.logger.promote`: appending a
    # second run to a finished CSV duplicates every (prompt_id, system_id) key
    # and makes the paired analysis raise. Staging means a crashed run cannot
    # destroy the previous results, and its own partial output survives for
    # inspection.
    results_path = Path(results_path)
    staged_path = results_path.with_name(results_path.name + ".partial")
    if staged_path.exists():
        logger.info("Discarding partial output from an earlier attempt: %s", staged_path.name)
        staged_path.unlink()

    logger_out = ResultLogger(staged_path)

    start = time.time()
    if not skip_a:
        run_system_a(dataset, prompts, logger_out)
    if not skip_b:
        run_system_b(dataset, prompts, logger_out)

    promote(staged_path, results_path)
    logger.info("[%s] Experiment finished in %.1f s. Results -> %s", dataset, time.time() - start, results_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4: run the RAG comparison experiment.")
    parser.add_argument("--dataset", default=None,
                        help="dataset to run: fintech | hotpot | math | all (default: all)")
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N prompts per dataset (smoke test).")
    parser.add_argument("--build-prompts", action="store_true",
                        help="(re)build eval_prompts.json for each dataset first.")
    parser.add_argument("--reset-store", action="store_true",
                        help="wipe the ChromaDB collections and re-index.")
    parser.add_argument("--skip-a", action="store_true", help="skip System A.")
    parser.add_argument("--skip-b", action="store_true", help="skip System B.")
    parser.add_argument("--results", default=None)
    parser.add_argument("--data-dir", default=None,
                        help="data directory (default: data/datasets)")
    args = parser.parse_args()

    if args.dataset:
        datasets = [d.strip() for d in args.dataset.split(",")]
        for d in datasets:
            if d not in settings.VALID_DATASETS:
                raise SystemExit(f"Unknown dataset {d!r}. Must be one of {settings.VALID_DATASETS}")
    else:
        datasets = list(settings.VALID_DATASETS)

    for dataset in datasets:
        logger.info("=" * 70)
        logger.info("Running experiment for dataset: %s", dataset)
        logger.info("=" * 70)
        results_path = args.results or settings.DATASET_RESULTS_PATH[dataset]
        run_dataset(
            dataset=dataset,
            limit=args.limit,
            build_prompts=args.build_prompts,
            reset_store=args.reset_store,
            skip_a=args.skip_a,
            skip_b=args.skip_b,
            results_path=results_path,
            data_dir=args.data_dir,
        )


if __name__ == "__main__":
    main()
