import logging
from pathlib import Path

from config import settings
from src.dqn_agent import DQNAgent
from src.embeddings import get_embedder
from src.generator import get_generator
from src.ragas_eval import RagasScorer
from src.reward import compute_reward
from src.vector_store import VectorStore

logger = logging.getLogger(__name__)


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
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else settings.DATASET_CHECKPOINT_PATH[dataset]
        self.agent = agent if agent is not None else DQNAgent()
        self._warned_skip = False

    def _state(self, question: str) -> list[float]:
        return self.embedder.embed_query(question)

    def _act(self, action: int) -> int:
        return action + settings.ACTION_MIN_K

    def _retrieve(self, state, k: int) -> list[str]:
        return self.vector_store.query_embeddings(state, k)

    def _generate(self, question: str, contexts: list[str]) -> str:
        return self.generator.answer(question, contexts)

    def train_episode(self, question: str, ground_truth: str | None = None) -> dict:
        state = self._state(question)
        action = self.agent.select_action(state)
        k = self._act(action)

        contexts = self._retrieve(state, k)
        response = self._generate(question, contexts)

        scores = self.scorer.score_single(
            question,
            response,
            contexts,
            reference=ground_truth,
            metric_names=["faithfulness", "answer_relevancy", "context_recall"],
        )
        faithfulness = scores.get("faithfulness")
        answer_relevancy = scores.get("answer_relevancy")
        context_recall = scores.get("context_recall")
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

        return {
            "action": action,
            "k": k,
            "answer": response,
            "contexts": contexts,
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_recall": context_recall,
            "reward": reward,
            "loss": loss,
            "epsilon": self.agent.epsilon,
        }

    def answer(self, question: str) -> dict:
        """Inference mode: greedy policy, no exploration."""
        state = self._state(question)
        action = self.agent.greedy_action(state)
        k = self._act(action)
        contexts = self._retrieve(state, k)
        response = self._generate(question, contexts)
        return {"answer": response, "contexts": contexts, "k": k}