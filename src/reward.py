from config import settings


def compute_reward(
    faithfulness: float,
    answer_relevancy: float,
    k: int,
    w_f: float = settings.REWARD_W_FAITHFULNESS,
    w_a: float = settings.REWARD_W_RELEVANCY,
    w_k: float = settings.REWARD_W_K,
) -> float:
    if faithfulness is None:
        faithfulness = 0.0
    if answer_relevancy is None:
        answer_relevancy = 0.0
    k_cost = w_k * (k / settings.ACTION_MAX_K)
    return w_f * faithfulness + w_a * answer_relevancy - k_cost