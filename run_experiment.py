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
from src.logger import ResultLogger  # noqa: E402
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
    answers = []
    contexts = []
    refs = []
    gen_tokens = []
    gen_times = []
    retrieve_times = []
    for i, prompt in enumerate(prompts):
        result = baseline.answer(prompt["question"])
        answers.append(result["answer"])
        contexts.append(result["contexts"])
        refs.append(prompt.get("ground_truth"))
        gen_tokens.append(result["total_tokens"])
        gen_times.append(result["generation_time_s"])
        retrieve_times.append(result["retrieval_time_s"])
        if (i + 1) % 10 == 0 or i == len(prompts) - 1:
            logger.info("  System A answered %d/%d prompts", i + 1, len(prompts))
    logger.info("[%s] Scoring System A with RAGAS (sequential)...", dataset)
    scores = scorer.score(
        [p["question"] for p in prompts],
        answers,
        contexts,
        references=refs,
    )
    for i, prompt in enumerate(prompts):
        logger_out.log(
            prompt_id=prompt["id"],
            system_id="A",
            faithfulness=scores[i].get("faithfulness"),
            answer_relevancy=scores[i].get("answer_relevancy"),
            context_recall=scores[i].get("context_recall"),
            retrieved_k=settings.BASELINE_K,
            prompt_tokens=scores[i].get("judge_prompt_tokens"),
            completion_tokens=scores[i].get("judge_completion_tokens"),
            total_tokens=gen_tokens[i],
            judge_prompt_tokens=scores[i].get("judge_prompt_tokens"),
            judge_completion_tokens=scores[i].get("judge_completion_tokens"),
            retrieval_time_s=retrieve_times[i],
            generation_time_s=gen_times[i],
            judge_time_s=scores[i].get("judge_time_s"),
            total_time_s=retrieve_times[i] + gen_times[i] + scores[i].get("judge_time_s", 0.0),
        )
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
    answers = []
    contexts = []
    refs = []
    ks = []
    inf_tokens = []
    inf_gen_times = []
    inf_retrieve_times = []
    for i, prompt in enumerate(prompts):
        result = dqn.answer(prompt["question"])
        answers.append(result["answer"])
        contexts.append(result["contexts"])
        refs.append(prompt.get("ground_truth"))
        ks.append(result["k"])
        inf_tokens.append(result["total_tokens"])
        inf_gen_times.append(result["generation_time_s"])
        inf_retrieve_times.append(result["retrieval_time_s"])
    logger.info("[%s] Scoring System B with RAGAS (sequential)...", dataset)
    scores = scorer.score(
        [p["question"] for p in prompts],
        answers,
        contexts,
        references=refs,
    )
    for i, prompt in enumerate(prompts):
        logger_out.log(
            prompt_id=prompt["id"],
            system_id="B",
            faithfulness=scores[i].get("faithfulness"),
            answer_relevancy=scores[i].get("answer_relevancy"),
            context_recall=scores[i].get("context_recall"),
            retrieved_k=ks[i],
            prompt_tokens=scores[i].get("judge_prompt_tokens"),
            completion_tokens=scores[i].get("judge_completion_tokens"),
            total_tokens=inf_tokens[i],
            judge_prompt_tokens=scores[i].get("judge_prompt_tokens"),
            judge_completion_tokens=scores[i].get("judge_completion_tokens"),
            retrieval_time_s=inf_retrieve_times[i],
            generation_time_s=inf_gen_times[i],
            judge_time_s=scores[i].get("judge_time_s"),
            total_time_s=inf_retrieve_times[i] + inf_gen_times[i] + scores[i].get("judge_time_s", 0.0),
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

    logger_out = ResultLogger(results_path)

    start = time.time()
    if not skip_a:
        run_system_a(dataset, prompts, logger_out)
    if not skip_b:
        run_system_b(dataset, prompts, logger_out)
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
