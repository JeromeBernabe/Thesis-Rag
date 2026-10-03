import logging
import time
from pathlib import Path

from config import settings
from src.dqn_agent import DQNAgent
from src.embeddings import get_embedder
from src.generator import get_generator
from src.ragas_eval import RagasScorer
from src.result_shapes import canonical_answer, canonical_judge
from src.reward import compute_reward
from src.vector_store import VectorStore

logger = logging.getLogger(__name__)

#: Indices into the agent's action space map to k = index + ACTION_MIN_K.
ACTION_MIN_K = settings.ACTION_MIN_K
NUM_ACTIONS = settings.NUM_ACTIONS


class DQNRAG:
    """System B: DQN-driven retrieval depth k in {1..5}."""

    def __init__(
        self,
        vector_store: VectorStore,
        scorer: RagasScorer,
        agent: DQNAgent | None = None,
        dataset: str = "math",
        checkpoint_path: Path = None,
    ):
        self.dataset = dataset
        self.vector_store = vector_store
        self.scorer = scorer
        self.generator = get_generator(dataset)
        self.embedder = get_embedder()
        self.checkpoint_path = (
            Path(checkpoint_path)
            if checkpoint_path is not None
            else settings.DATASET_CHECKPOINT_PATH[dataset]
        )
        self.agent = agent if agent is not None else DQNAgent()
        self._warned_skip = False

    # ------------------------------------------------------------- primitives

    def _state(self, question: str) -> list[float]:
        return self.embedder.embed_query(question)

    def _act(self, action: int) -> int:
        return action + ACTION_MIN_K

    def _q_values(self, state) -> list[float]:
        """Q-values for the current state, one per action (k = index + ACTION_MIN_K).

        Prefers the agent's own accessor so this wrapper does not need to know
        about the torch device or the network layout.
        """
        getter = getattr(self.agent, "q_values", None)
        if getter is not None:
            return list(getter(state))

        import torch

        arr = torch.tensor([list(state)], dtype=torch.float32, device=settings.DEVICE)
        with torch.no_grad():
            q = self.agent.q_net(arr).squeeze(0)
        return [float(q[i]) for i in range(NUM_ACTIONS)]

    def _retrieve(self, state, k: int) -> list[str]:
        return self.vector_store.query_embeddings(state, k)

    def _retrieve_detailed(self, state, k: int) -> dict:
        """Retrieval that keeps ids and distances for the embedding-space view."""
        return self.vector_store.query_embeddings_detailed(state, k)

    def _generate(self, question: str, contexts: list[str]):
        return self.generator.answer(question, contexts)

    # ---------------------------------------------------------------- training

    def train_episode(self, question: str, ground_truth: str | None = None) -> dict:
        """Exploration episode: pick k, generate, judge, learn."""
        return self._train_episode(question, ground_truth, detailed=False)

    def train_episode_detailed(
        self, question: str, ground_truth: str | None = None
    ) -> dict:
        """`train_episode` plus retrieved ids and distances, from one query."""
        return self._train_episode(question, ground_truth, detailed=True)

    def _train_episode(
        self, question: str, ground_truth: str | None, detailed: bool
    ) -> dict:
        t_embed0 = time.perf_counter()
        state = self._state(question)
        embedding_time_s = time.perf_counter() - t_embed0

        action = self.agent.select_action(state)
        k = self._act(action)
        q_values = self._q_values(state)

        t0 = time.perf_counter()
        if detailed:
            found = self._retrieve_detailed(state, k)
            contexts = found["documents"]
        else:
            contexts = self._retrieve(state, k)
        retrieval_time_s = time.perf_counter() - t0

        generated = canonical_answer(self._generate(question, contexts))

        scores = self.scorer.score_single(
            question,
            generated["answer"],
            contexts,
            reference=ground_truth,
            metric_names=["faithfulness", "answer_relevancy", "context_recall"],
        )
        judged = canonical_judge(scores)
        faithfulness = judged["faithfulness"]
        answer_relevancy = judged["answer_relevancy"]
        context_recall = judged["context_recall"]
        reward = compute_reward(faithfulness, answer_relevancy, k, context_recall)

        self.agent.store(state, action, reward)
        loss = self.agent.train_step()
        if loss is None:
            if not self._warned_skip:
                logger.warning(
                    "Replay buffer has %d experiences (< batch size %d); skipping "
                    "DQN weight update this step.",
                    len(self.agent.replay_buffer),
                    self.agent.batch_size,
                )
                self._warned_skip = True
        self.agent.decay_epsilon()
        self.agent.save(self.checkpoint_path)

        total_time_s = (
            embedding_time_s
            + retrieval_time_s
            + generated["generation_time_s"]
            + judged["judge_time_s"]
        )

        result = {
            "action": action,
            "k": k,
            "answer": generated["answer"],
            "contexts": contexts,
            "q_values": q_values,
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_recall": context_recall,
            "reward": reward,
            "loss": loss,
            "epsilon": self.agent.epsilon,
            "prompt_tokens": generated["prompt_tokens"],
            "completion_tokens": generated["completion_tokens"],
            "total_tokens": generated["total_tokens"],
            "judge_prompt_tokens": judged["judge_prompt_tokens"],
            "judge_completion_tokens": judged["judge_completion_tokens"],
            "embedding_time_s": embedding_time_s,
            "retrieval_time_s": retrieval_time_s,
            "generation_time_s": generated["generation_time_s"],
            "judge_time_s": judged["judge_time_s"],
            "total_time_s": total_time_s,
        }
        if detailed:
            result["retrieved_ids"] = found["ids"]
            result["retrieved_distances"] = found["distances"]
        return result

    # --------------------------------------------------------------- inference

    def _infer(self, question: str) -> tuple[int, list[float], list[float], float]:
        """Embed the question and take the greedy action.

        Returns ``(action, q_values, state, embedding_time_s)``. Inference shares
        one embedding step between `answer` and `answer_detailed`.
        """
        t_embed0 = time.perf_counter()
        state = self._state(question)
        embedding_time_s = time.perf_counter() - t_embed0
        action = self.agent.greedy_action(state)
        return action, self._q_values(state), state, embedding_time_s

    def answer(self, question: str) -> dict:
        """Inference mode: greedy policy, no exploration."""
        return self._infer_answer(question, detailed=False)

    def answer_detailed(self, question: str) -> dict:
        """`answer` plus retrieved ids and distances, from a single query."""
        return self._infer_answer(question, detailed=True)

    def _infer_answer(self, question: str, detailed: bool) -> dict:
        action, q_values, state, embedding_time_s = self._infer(question)
        k = self._act(action)

        t0 = time.perf_counter()
        if detailed:
            found = self._retrieve_detailed(state, k)
            contexts = found["documents"]
        else:
            contexts = self._retrieve(state, k)
        retrieval_time_s = time.perf_counter() - t0

        generated = canonical_answer(self._generate(question, contexts))

        result = {
            "answer": generated["answer"],
            "contexts": contexts,
            "k": k,
            "action": action,
            "q_values": q_values,
            "epsilon": self.agent.epsilon,
            "prompt_tokens": generated["prompt_tokens"],
            "completion_tokens": generated["completion_tokens"],
            "total_tokens": generated["total_tokens"],
            "embedding_time_s": embedding_time_s,
            "retrieval_time_s": retrieval_time_s,
            "generation_time_s": generated["generation_time_s"],
        }
        if detailed:
            result["retrieved_ids"] = found["ids"]
            result["retrieved_distances"] = found["distances"]
        return result