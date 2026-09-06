import math

from config import settings


def compute_reward(
    faithfulness: float,
    answer_relevancy: float,
    k: int,
    context_recall: float = None,
    w_f: float = settings.REWARD_W_FAITHFULNESS,
    w_a: float = settings.REWARD_W_RELEVANCY,
    w_k: float = settings.REWARD_W_K,
    w_c: float = 0.30,
) -> float:
    if faithfulness is None:
        faithfulness = 0.0
    if answer_relevancy is None:
        answer_relevancy = 0.0
    if context_recall is None:
        context_recall = 0.0
    k_cost = w_k * math.log(1 + k)
    return w_f * faithfulness + w_a * answer_relevancy + w_c * context_recall - k_cost
