"""Sidecar orchestration: run the experiment while streaming NDJSON events.

This is the Python process Tauri spawns. It mirrors the phase order of
``run_experiment.py`` / ``run_experiment_logged.py`` but reports progress as it
goes instead of only writing a CSV at the end, which is what makes the Run page
live.

Phase order
-----------
``preflight -> index -> projection -> system_a -> system_b_train ->
system_b_infer -> stats -> done``

``projection`` sits after ``index`` because the 3D embedding cloud is computed
from the corpus embeddings Chroma already holds; running it earlier would
project a stale or empty store.

Dry runs
--------
``--dry-run`` swaps the corpus, generator, judge and agent for deterministic
in-process fakes. It exists for two reasons:

* the test suite drives the whole orchestration without Ollama, CUDA or the
  2.4 GB Chroma store, and
* the app's "Smoke test" button gives a user a way to confirm the install works
  before committing to an hours-long real run.

A dry run is marked in every event and in ``run_finished`` so a result can never
be mistaken for a real measurement.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench_bridge.config_snapshot import capture_settings_snapshot, environment_snapshot  # noqa: E402
from bench_bridge.events import EventEmitter, EventType, PHASES, short_id  # noqa: E402
from bench_bridge.stats import build_stats_payload  # noqa: E402

METRICS = ("faithfulness", "answer_relevancy", "context_recall")


@dataclass
class RunSpec:
    """Everything the UI can configure for one run."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    dataset: str = "hotpot"
    systems: list[str] = field(default_factory=lambda: ["A", "B"])
    limit: int | None = 50
    seed: int = 42
    build_prompts: bool = False
    reset_store: bool = False
    no_judge: bool = False
    dry_run: bool = False
    skip_projection: bool = False
    data_dir: str | None = None
    notes: str | None = None

    def validate(self, valid_datasets: tuple[str, ...]) -> None:
        if self.dataset not in valid_datasets:
            raise ValueError(
                f"unknown dataset {self.dataset!r}; expected one of {list(valid_datasets)}"
            )
        unknown = [s for s in self.systems if s.upper() not in {"A", "B"}]
        if unknown:
            raise ValueError(f"unknown systems {unknown}; expected 'A' and/or 'B'")
        if not self.systems:
            raise ValueError("at least one system must be selected")
        if self.limit is not None and self.limit < 1:
            raise ValueError(f"limit must be >= 1, got {self.limit}")

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "dataset": self.dataset,
            "systems": self.systems,
            "limit": self.limit,
            "seed": self.seed,
            "build_prompts": self.build_prompts,
            "reset_store": self.reset_store,
            "no_judge": self.no_judge,
            "dry_run": self.dry_run,
            "skip_projection": self.skip_projection,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, raw: str) -> "RunSpec":
        data = json.loads(raw)
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------- fakes


class _FakeStore:
    """Deterministic stand-in for `VectorStore` used by ``--dry-run``."""

    def __init__(self, count: int = 400):
        self._count = count

    @property
    def count(self) -> int:
        return self._count

    def query_detailed(self, question: str, k: int = 3) -> dict:
        n = max(1, min(k, 8))
        return {
            "ids": [f"dry-{i}" for i in range(n)],
            "documents": [f"dry-run context {i} for {question[:24]}" for i in range(n)],
            "distances": [round(1.0 - i * 0.1, 4) for i in range(n)],
        }

    def query(self, question: str, k: int = 3) -> list[str]:
        return self.query_detailed(question, k)["documents"]

    def query_embeddings_detailed(self, embedding, k: int = 3) -> dict:
        n = max(1, min(k, 8))
        return {
            "ids": [f"dry-emb-{i}" for i in range(n)],
            "documents": [f"dry-run context {i}" for i in range(n)],
            "distances": [round(1.0 - i * 0.1, 4) for i in range(n)],
        }

    def query_embeddings(self, embedding, k: int = 3) -> list[str]:
        return self.query_embeddings_detailed(embedding, k)["documents"]


class _FakeGenerator:
    def __init__(self, _dataset=None):
        pass

    def answer(self, question: str, contexts: list[str]) -> dict:
        text = f"[dry-run] answer grounded in {len(contexts)} passage(s)."
        prompt_tokens = sum(len(c.split()) for c in contexts)
        completion_tokens = len(text.split())
        return {
            "answer": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "generation_time_s": 0.05,
        }


class _FakeScorer:
    def __init__(self, *_args, **_kwargs):
        pass

    def score_single(
        self,
        question: str,
        response: str,
        retrieved_contexts: list[str],
        reference: str | None = None,
        metric_names: list[str] | None = None,
    ) -> dict:
        # Deterministic pseudo-metrics derived from the inputs so the charts
        # have plausible movement without a judge model.
        seed = sum(ord(c) for c in question) % 97
        return {
            "faithfulness": round(0.55 + (seed % 40) / 100.0, 4),
            "answer_relevancy": round(0.50 + (seed % 45) / 100.0, 4),
            "context_recall": None if reference is None else round(0.40 + (seed % 50) / 100.0, 4),
            "judge_prompt_tokens": 120,
            "judge_completion_tokens": 45,
            "judge_time_s": 0.1,
        }


class _FakeEmbedder:
    """768-dimensional deterministic embedding, matching EMBEDDING_DIM.

    SHA-256 only yields 32 bytes, so the digest is expanded by re-hashing with a
    counter. Determinism matters: the dry run must produce identical
    coordinates on every invocation for the 3D view to be comparable.
    """

    def __init__(self, dim: int = 768):
        self.dim = dim

    def embed_query(self, text: str) -> list[float]:
        import hashlib

        out: list[float] = []
        counter = 0
        while len(out) < self.dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            out.extend(byte / 255.0 for byte in digest)
            counter += 1
        return out[: self.dim]


class _FakeAgent:
    """A DQN double whose policy drifts towards k=3 as training proceeds.

    Gives the pipeline view something to animate - the Q-values settle and the
    epsilon-greedy choice narrows - without torch.
    """

    def __init__(self, num_actions: int = 5, batch_size: int = 2):
        self.num_actions = num_actions
        self.epsilon = 1.0
        # batch_size is deliberately below the usual prompt count so a dry run
        # actually reaches the weight-update path; with the real value of 8 a
        # 3-prompt smoke test would never train at all and the training charts
        # would be flat lines.
        self.batch_size = batch_size
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.95
        self.steps = 0

        class _Buf:
            def __init__(self):
                self.items: list = []

            def __len__(self):
                return len(self.items)

        self.replay_buffer = _Buf()

    def _bias(self) -> list[float]:
        # Prefers k=3 (index 2), increasingly confident as steps accumulate.
        drift = min(1.0, self.steps / 20.0)
        return [0.1, 0.3 + 0.2 * drift, 0.9 * drift, 0.4 - 0.1 * drift, 0.05]

    def q_values(self, state) -> list[float]:
        return self._bias()

    def greedy_action(self, state) -> int:
        q = self._bias()
        return max(range(self.num_actions), key=q.__getitem__)

    def select_action(self, state) -> int:
        import random

        if random.random() < self.epsilon:
            return random.randrange(self.num_actions)
        return self.greedy_action(state)

    def store(self, state, action, reward) -> None:
        self.replay_buffer.items.append((state, action, reward))

    def train_step(self) -> float | None:
        if len(self.replay_buffer) < self.batch_size:
            return None
        self.steps += 1
        return round(1.0 / (self.steps + 1), 6)

    def decay_epsilon(self) -> None:
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def save(self, path=None) -> None:
        pass

    def load(self, path=None) -> None:
        pass


# --------------------------------------------------------------------- runner


class Runner:
    """Executes a :class:`RunSpec`, emitting an event per meaningful step."""

    def __init__(self, spec: RunSpec, emitter: EventEmitter | None = None):
        self.spec = spec
        self.emitter = emitter or EventEmitter(spec.run_id)
        self.prompt_rows: list[dict] = []
        self.training_rows: list[dict] = []
        self._started = time.time()

    # ------------------------------------------------------------- utilities

    def _settings(self):
        from config import settings

        return settings

    def _emit_run_started(self, prompt_count: int, corpus_count: int) -> None:
        settings = self._settings()
        self.emitter.emit(
            EventType.RUN_STARTED,
            {
                **self.spec.to_dict(),
                "prompt_count": prompt_count,
                "corpus_count": corpus_count,
                "config": capture_settings_snapshot(settings),
                "environment": environment_snapshot(),
                "valid_datasets": list(settings.VALID_DATASETS),
                "baseline_k": settings.BASELINE_K,
                "action_min_k": settings.ACTION_MIN_K,
                "action_max_k": settings.ACTION_MAX_K,
                "num_actions": settings.NUM_ACTIONS,
            },
        )

    def _embed_query_event(self, question: str, system: str) -> float:
        t0 = time.perf_counter()
        self.emitter.emit(
            EventType.EMBEDDING,
            {"system": system, "question": question, "state": "started"},
        )
        elapsed = time.perf_counter() - t0
        self.emitter.emit(
            EventType.EMBEDDING,
            {
                "system": system,
                "question": question,
                "state": "done",
                "time_s": round(elapsed, 4),
            },
        )
        return elapsed

    # ---------------------------------------------------------------- phases

    def _load_prompts(self) -> list[dict]:
        from prompts.build_eval_prompts import build_eval_prompts, load_eval_prompts

        settings = self._settings()
        if self.spec.build_prompts:
            build_eval_prompts(
                dataset=self.spec.dataset,
                num_prompts=self.spec.limit or settings.NUM_EVAL_PROMPTS,
                data_dir=self.spec.data_dir,
            )
        if self.spec.dry_run:
            count = self.spec.limit or 5
            return [
                {
                    "prompt_id": f"dry-{i:04d}",
                    "question": f"[dry-run] evaluation prompt {i}?",
                    "ground_truth": f"[dry-run] reference answer {i}",
                }
                for i in range(count)
            ]
        prompts = load_eval_prompts(self.spec.dataset)
        if self.spec.limit is not None:
            prompts = prompts[: self.spec.limit]
        if not prompts:
            raise ValueError(
                f"no prompts for {self.spec.dataset!r}; enable build_prompts to create them"
            )
        return prompts

    def _build_store(self):
        settings = self._settings()
        if self.spec.dry_run:
            return _FakeStore(), 400
        from src.vector_store import VectorStore

        name = settings.DATASET_COLLECTION_NAMES.get(
            self.spec.dataset, f"{self.spec.dataset}_docs"
        )
        store = VectorStore(collection_name=name, reset=self.spec.reset_store)
        return store, store.count

    def _index(self, store) -> int:
        settings = self._settings()
        if self.spec.dry_run or store.count > 0:
            self.emitter.info(
                f"{self.spec.dataset}: using {store.count} existing documents; skipping indexing."
            )
            return store.count

        from src.data_loader import build_indexed_corpus, format_doc_text

        data_dir = self.spec.data_dir
        ids, records = build_indexed_corpus(self.spec.dataset, data_dir)
        if not records:
            raise ValueError(f"no {self.spec.dataset} records under {settings.DATASETS_DIR}")
        if settings.MAX_CORPUS_DOCS and len(records) > settings.MAX_CORPUS_DOCS:
            ids, records = ids[: settings.MAX_CORPUS_DOCS], records[: settings.MAX_CORPUS_DOCS]

        total = len(records)
        documents = [format_doc_text(self.spec.dataset, r) for r in records]
        batch = 128
        for start in range(0, total, batch):
            store.add_documents(ids[start : start + batch], documents[start : start + batch])
            done = min(start + batch, total)
            self.emitter.emit(
                EventType.INDEX_PROGRESS,
                {"indexed": done, "total": total, "fraction": round(done / total, 4)},
            )
        return store.count

    def _project(self, store) -> dict | None:
        """Compute and persist the 3D PCA projection of the corpus."""
        from bench_bridge.projection import build_from_collection, write_projection

        out_dir = REPO_ROOT / "data" / "bench" / "projections"
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.time()
            if now - last[0] > 0.25 or done == total:
                last[0] = now
                self.emitter.emit(
                    EventType.INDEX_PROGRESS,
                    {"stage": "projection", "indexed": done, "total": total},
                )

        collection = getattr(store, "collection", None)
        if collection is None:
            self.emitter.warning("no Chroma collection available; skipping projection")
            return None

        result = build_from_collection(
            collection, self.spec.dataset, out_dir, progress=progress
        )
        points_path, meta_path = write_projection(result, out_dir)
        payload = {
            "dataset": result.dataset,
            "collection": result.collection,
            "dim": result.dim,
            "n_points": result.n_points,
            "source_count": result.source_count,
            "points_path": str(points_path),
            "meta_path": str(meta_path),
            "explained_variance_ratio": result.explained_variance_ratio,
            "explained_variance_total": round(sum(result.explained_variance_ratio), 4),
            "bounds": result.bounds,
        }
        self.emitter.emit(EventType.PROJECTION_READY, payload)
        return payload

    # --------------------------------------------------------------- systems

    def _prompt_started(self, system: str, index: int, prompt: dict, total: int) -> None:
        self.emitter.emit(
            EventType.PROMPT_STARTED,
            {
                "system": system,
                "index": index,
                "total": total,
                "prompt_id": str(prompt.get("prompt_id", index)),
                "question": prompt.get("question", ""),
                "ground_truth": prompt.get("ground_truth"),
            },
        )

    def _emit_retrieval(
        self, system: str, index: int, prompt_id: str, result: dict, k: int
    ) -> None:
        """Report the chunks the wrapper already retrieved - never re-query."""
        ids = result.get("retrieved_ids") or []
        distances = result.get("retrieved_distances") or []
        docs = result.get("contexts") or []
        self.emitter.emit(
            EventType.RETRIEVAL,
            {
                "system": system,
                "index": index,
                "prompt_id": prompt_id,
                "k": k,
                "ids": [short_id(i) for i in ids],
                "distances": [round(float(d), 6) for d in distances],
                # Preview text only: full passages are already persisted with the
                # row, and sending them all would bloat the live event stream.
                "previews": [str(d)[:180] for d in docs],
            },
        )

    def _emit_generation(self, system: str, index: int, prompt_id: str, answer: str) -> None:
        self.emitter.emit(
            EventType.GENERATION,
            {
                "system": system,
                "index": index,
                "prompt_id": prompt_id,
                "answer": str(answer)[:4000],
            },
        )

    def _row_from(
        self,
        system: str,
        index: int,
        prompt: dict,
        result: dict,
        judged: dict | None = None,
    ) -> dict:
        judged = judged or {}
        return {
            "system": system,
            "system_id": system,
            "index": index,
            "prompt_id": str(prompt.get("prompt_id", index)),
            "phase": "system_a" if system == "A" else "system_b_infer",
            "question": prompt.get("question", ""),
            "ground_truth": prompt.get("ground_truth"),
            "answer": result.get("answer", ""),
            "contexts": result.get("contexts", []),
            # Persisted alongside the row so the Results page can put the
            # retrieved chunks on the 3D map without re-running retrieval.
            "retrieved_ids": result.get("retrieved_ids", []),
            "retrieved_distances": result.get("retrieved_distances", []),
            "retrieved_k": result.get("k"),
            "faithfulness": judged.get("faithfulness"),
            "answer_relevancy": judged.get("answer_relevancy"),
            "context_recall": judged.get("context_recall"),
            "prompt_tokens": result.get("prompt_tokens"),
            "completion_tokens": result.get("completion_tokens"),
            "total_tokens": result.get("total_tokens"),
            "judge_prompt_tokens": judged.get("judge_prompt_tokens"),
            "judge_completion_tokens": judged.get("judge_completion_tokens"),
            "embedding_time_s": result.get("embedding_time_s"),
            "retrieval_time_s": result.get("retrieval_time_s"),
            "generation_time_s": result.get("generation_time_s"),
            "judge_time_s": judged.get("judge_time_s"),
            "total_time_s": result.get("total_time_s"),
        }

    def _public_row(self, row: dict) -> dict:
        """A completed row, stripped of fields that do not belong on the wire.

        The desktop app persists `prompt_rows` from the event stream alone - it
        has no other way to learn what a prompt scored. So the row travels with
        `prompt_completed`, minus the two things that would bloat it:

        - `contexts`, the retrieved passage text, which is already on the
          `retrieval` event as short previews and is re-read from the vector
          store on demand rather than streamed.
        - keys that duplicate fields already in the event envelope
          (`system_id`, `index`).
        """
        return {
            k: v
            for k, v in row.items()
            if k not in ("contexts", "system_id", "index")
        }

    def _judge(self, scorer, prompt: dict, result: dict, system: str) -> dict | None:
        if self.spec.no_judge:
            return None
        from src.result_shapes import canonical_judge

        t0 = time.perf_counter()
        scores = scorer.score_single(
            prompt["question"],
            result["answer"],
            result["contexts"],
            reference=prompt.get("ground_truth"),
            metric_names=list(METRICS),
        )
        judged = canonical_judge(scores)
        # `system` is passed in rather than read off `result`, because nothing
        # in the RAG layers sets it: `result.get("system", "A")` silently
        # labelled every System B judge event as System A. Stored rows were
        # unaffected (they go through `_row_from`, which is told the system), so
        # the final statistics stayed correct while the live console showed B's
        # scores landing in A's row.
        self.emitter.emit(
            EventType.RAGAS,
            {
                "system": system,
                "prompt_id": str(prompt.get("prompt_id", "")),
                **judged,
                "time_s": round(time.perf_counter() - t0, 4),
            },
        )
        return judged

    def run_system_a(self, store, prompts: list[dict], scorer) -> None:
        settings = self._settings()
        self.emitter.phase("system_a", f"baseline RAG, k={settings.BASELINE_K}")
        self.emitter.info(
            f"System A: fixed k={settings.BASELINE_K} over {len(prompts)} prompts"
            + (" (judge disabled)" if self.spec.no_judge else "")
        )

        baseline = self._make_baseline(store)
        ks: Counter = Counter()

        for index, prompt in enumerate(prompts):
            prompt_id = str(prompt.get("prompt_id", index))
            self._prompt_started("A", index, prompt, len(prompts))

            result = baseline.answer_detailed(prompt["question"])
            self._emit_retrieval("A", index, prompt_id, result, result["k"])
            self._emit_generation("A", index, prompt_id, result["answer"])

            judged = self._judge(scorer, prompt, result, "A")
            row = self._row_from("A", index, prompt, result, judged)
            if row["total_time_s"] is None:
                row["total_time_s"] = (row["retrieval_time_s"] or 0.0) + (
                    row["generation_time_s"] or 0.0
                ) + (row["judge_time_s"] or 0.0)
            self.prompt_rows.append(row)
            ks[row["retrieved_k"]] += 1
            self.emitter.emit(
                EventType.PROMPT_COMPLETED,
                {
                    "system": "A",
                    "index": index,
                    "prompt_id": row["prompt_id"],
                    "k": row["retrieved_k"],
                    # Carries the full row so the app can persist metrics,
                    # token counts and timings it cannot recompute itself.
                    "row": self._public_row(row),
                },
            )

        self.emitter.emit(
            EventType.REWARD,
            {"system": "A", "k_distribution": dict(ks), "note": "System A has no learned policy"},
        )

    def run_system_b_train(self, store, prompts: list[dict], scorer) -> None:
        self.emitter.phase("system_b_train", f"DQN training on {len(prompts)} prompts")
        self.emitter.info("System B phase B.1: exploratory episodes with reward feedback")

        system = self._make_dqn(store, scorer)
        for index, prompt in enumerate(prompts):
            prompt_id = str(prompt.get("prompt_id", index))
            self._prompt_started("B", index, prompt, len(prompts))

            episode = system.train_episode_detailed(
                prompt["question"], ground_truth=prompt.get("ground_truth")
            )
            self._emit_retrieval("B", index, prompt_id, episode, episode["k"])
            self._emit_decision(index, prompt, episode)

            row = {
                "run_id": self.spec.run_id,
                "system": "B",
                "step": index + 1,
                "prompt_id": str(prompt.get("prompt_id", index)),
                "k": episode["k"],
                "faithfulness": episode["faithfulness"],
                "answer_relevancy": episode["answer_relevancy"],
                "context_recall": episode["context_recall"],
                "reward": episode["reward"],
                "loss": episode["loss"],
                "epsilon": episode["epsilon"],
                "q_values": episode["q_values"],
                "prompt_tokens": episode["prompt_tokens"],
                "completion_tokens": episode["completion_tokens"],
                "total_tokens": episode["total_tokens"],
                "judge_prompt_tokens": episode["judge_prompt_tokens"],
                "judge_completion_tokens": episode["judge_completion_tokens"],
                "embedding_time_s": episode["embedding_time_s"],
                "retrieval_time_s": episode["retrieval_time_s"],
                "generation_time_s": episode["generation_time_s"],
                "judge_time_s": episode["judge_time_s"],
                "total_time_s": episode["total_time_s"],
            }
            self.training_rows.append(row)
            # `q_values` travels with the step: the Results page plots the
            # Q-value curve, and five floats are not worth omitting.
            self.emitter.emit(EventType.TRAIN_STEP, dict(row))

    def run_system_b_infer(self, store, prompts: list[dict], scorer) -> None:
        self.emitter.phase("system_b_infer", f"greedy inference over {len(prompts)} prompts")
        self.emitter.info("System B phase B.2: greedy policy, no exploration")

        system = self._make_dqn(store, scorer)
        ks: Counter = Counter()

        for index, prompt in enumerate(prompts):
            prompt_id = str(prompt.get("prompt_id", index))
            self._prompt_started("B", index, prompt, len(prompts))

            result = system.answer_detailed(prompt["question"])
            self._emit_retrieval("B", index, prompt_id, result, result["k"])
            self._emit_decision(index, prompt, result, phase="system_b_infer")
            self._emit_generation("B", index, prompt_id, result["answer"])

            judged = self._judge(scorer, prompt, result, "B")
            row = self._row_from("B", index, prompt, result, judged)
            row["phase"] = "system_b_infer"
            row["reward"] = result.get("reward")
            if row["total_time_s"] is None:
                row["total_time_s"] = (row["embedding_time_s"] or 0.0) + (
                    row["retrieval_time_s"] or 0.0
                ) + (row["generation_time_s"] or 0.0) + (row["judge_time_s"] or 0.0)
            self.prompt_rows.append(row)
            ks[row["retrieved_k"]] += 1
            self.emitter.emit(
                EventType.PROMPT_COMPLETED,
                {
                    "system": "B",
                    "index": index,
                    "prompt_id": row["prompt_id"],
                    "k": row["retrieved_k"],
                    "row": self._public_row(row),
                },
            )

        self.emitter.emit(EventType.REWARD, {"system": "B", "k_distribution": dict(ks)})

    def _emit_decision(
        self, index: int, prompt: dict, payload: dict, phase: str = "system_b_train"
    ) -> None:
        q = payload.get("q_values") or []
        self.emitter.emit(
            EventType.DECISION,
            {
                "system": "B",
                "phase": phase,
                "index": index,
                "prompt_id": str(prompt.get("prompt_id", index)),
                "action": payload.get("action"),
                "k": payload.get("k"),
                "q_values": [round(float(v), 6) for v in q],
                "chosen_rank": (
                    sorted(range(len(q)), key=lambda i: q[i], reverse=True).index(payload["action"]) + 1
                    if q and payload.get("action") is not None and payload["action"] < len(q)
                    else None
                ),
                "epsilon": payload.get("epsilon"),
                "reward": payload.get("reward"),
            },
        )

    # ------------------------------------------------------------ components

    def _make_baseline(self, store):
        if self.spec.dry_run:
            from config import settings

            return _DryBaseline(store, k=settings.BASELINE_K)
        from src.baseline_rag import BaselineRAG

        return BaselineRAG(vector_store=store, dataset=self.spec.dataset)

    def _make_dqn(self, store, scorer):
        """Build the DQN system once and reuse it across B.1 and B.2.

        This mirrors `run_experiment.run_system_b`, which constructs a single
        DQNAgent/DQNRAG and runs training then inference against it. Building a
        second instance for inference would silently discard everything B.1
        learned and report a greedy policy from a randomly initialised network.

        The dry-run doubles are assigned onto the instance rather than by
        patching module globals: patching would leak into anything else that
        imports those modules later in the same process.
        """
        if getattr(self, "_dqn_cache", None) is not None:
            return self._dqn_cache

        from src.dqn_rag import DQNRAG

        if self.spec.dry_run:
            system = DQNRAG(
                vector_store=store,
                scorer=scorer,
                agent=_FakeAgent(),
                dataset=self.spec.dataset,
                checkpoint_path=None,
            )
            system.generator = _FakeGenerator()
            system.embedder = _FakeEmbedder()
        else:
            system = DQNRAG(
                vector_store=store, scorer=scorer, dataset=self.spec.dataset
            )

        self._dqn_cache = system
        return system

    def execute(self) -> dict:
        settings = self._settings()
        self.spec.validate(settings.VALID_DATASETS)

        prompts = self._load_prompts()

        scorer = _FakeScorer() if self.spec.dry_run else self._make_scorer()
        store, existing = self._build_store()
        self._emit_run_started(len(prompts), existing)

        self.emitter.phase("preflight", "configuration accepted")
        corpus_count = self._index(store)

        if not self.spec.skip_projection:
            self.emitter.phase("projection", "computing the 3D embedding map")
            self._project(store)
        else:
            self.emitter.info("projection skipped by configuration")

        if "A" in [s.upper() for s in self.spec.systems]:
            self.run_system_a(store, prompts, scorer)
        if "B" in [s.upper() for s in self.spec.systems]:
            self.run_system_b_train(store, prompts, scorer)
            self.run_system_b_infer(store, prompts, scorer)

        self.emitter.phase("stats", "aggregating results")
        stats = build_stats_payload(self.prompt_rows, self.training_rows)
        self.emitter.emit(EventType.STATS, stats)

        duration = time.time() - self._started
        summary = {
            "run_id": self.spec.run_id,
            "dataset": self.spec.dataset,
            "prompt_count": len(prompts),
            "corpus_count": corpus_count,
            "systems": self.spec.systems,
            "dry_run": self.spec.dry_run,
            "no_judge": self.spec.no_judge,
            "prompt_rows": len(self.prompt_rows),
            "training_rows": len(self.training_rows),
            "duration_s": round(duration, 3),
        }
        self.emitter.phase("done", "finished")
        self.emitter.emit(EventType.RUN_FINISHED, summary)
        return summary

    def _make_scorer(self):
        from src.ragas_eval import RagasScorer

        return RagasScorer()

    def run_guarded(self) -> int:
        """Run, converting any failure into a ``run_failed`` event.

        Returns a process exit code: 0 on success, 1 on failure. The traceback is
        included in the event payload because the user has no other way to see
        the sidecar's stderr.
        """
        try:
            self.execute()
            return 0
        except BaseException as exc:  # noqa: BLE001 - must report, not crash silently
            self.emitter.emit(
                EventType.RUN_FAILED,
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
            )
            return 1


class _DryBaseline:
    """Baseline shaped like `src.baseline_rag.BaselineRAG` for dry runs."""

    def __init__(self, store, k: int = 3):
        self.store = store
        self.k = k
        self.generator = _FakeGenerator()

    def answer(self, question: str) -> dict:
        return self.answer_detailed(question)

    def answer_detailed(self, question: str) -> dict:
        import time as _time

        t0 = _time.perf_counter()
        detailed = self.store.query_detailed(question, k=self.k)
        retrieval_time_s = _time.perf_counter() - t0
        result = self.generator.answer(question, detailed["documents"])
        result.update(
            {
                "contexts": detailed["documents"],
                "k": self.k,
                "retrieved_ids": detailed["ids"],
                "retrieved_distances": detailed["distances"],
                "retrieval_time_s": retrieval_time_s,
            }
        )
        return result

    def retrieve_detailed(self, question: str) -> dict:
        return self.store.query_detailed(question, k=self.k)


# ------------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bench_bridge",
        description="Run a RAG benchmark and stream NDJSON events to the desktop app.",
    )
    parser.add_argument(
        "--spec-json",
        help="Full RunSpec as JSON (what the app passes); overrides the flags below.",
    )
    parser.add_argument("--dataset", default="hotpot")
    parser.add_argument("--systems", default="A,B", help="comma-separated subset of A,B")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--build-prompts", action="store_true")
    parser.add_argument("--reset-store", action="store_true")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip RAGAS. Makes a run ~100x faster but produces no metrics.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use in-process fakes for everything. No Ollama, CUDA or ChromaDB.",
    )
    parser.add_argument("--skip-projection", action="store_true")
    parser.add_argument("--data-dir", default=None)
    return parser


def spec_from_args(argv: list[str] | None = None) -> RunSpec:
    args = build_parser().parse_args(argv)
    if args.spec_json:
        return RunSpec.from_json(args.spec_json)
    return RunSpec(
        dataset=args.dataset,
        systems=[s.strip().upper() for s in args.systems.split(",") if s.strip()],
        limit=args.limit,
        seed=args.seed,
        build_prompts=args.build_prompts,
        reset_store=args.reset_store,
        no_judge=args.no_judge,
        dry_run=args.dry_run,
        skip_projection=args.skip_projection,
        data_dir=args.data_dir,
    )
