import logging
import time

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings

logger = logging.getLogger(__name__)

MATH_SYSTEM_PROMPT = (
    "You are a helpful math assistant. Answer the user's math problem using only "
    "the provided context. If the context is not sufficient, say so clearly. "
    "Show your reasoning and the final answer."
)

GENERAL_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question using only the "
    "provided context. If the context is not sufficient, say so clearly. "
    "Be concise and give the final answer."
)

SYSTEM_PROMPTS = {
    "fintech": GENERAL_SYSTEM_PROMPT,
    "hotpot": GENERAL_SYSTEM_PROMPT,
    "math": MATH_SYSTEM_PROMPT,
    "ragtruth": GENERAL_SYSTEM_PROMPT,
}


class Generator:
    def __init__(
        self,
        dataset: str = "math",
        model: str = settings.GENERATOR_MODEL,
        base_url: str = settings.OLLAMA_BASE_URL,
        temperature: float = settings.GENERATION_TEMPERATURE,
        max_tokens: int = settings.GENERATION_MAX_TOKENS,
    ):
        self.dataset = dataset
        self.system_prompt = SYSTEM_PROMPTS.get(dataset, GENERAL_SYSTEM_PROMPT)
        self._llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=temperature,
            num_predict=max_tokens,
            num_ctx=8192,
        )

    def answer(self, question: str, contexts: list[str]) -> str:
        context_block = "\n\n".join(
            f"[Context {i + 1}]\n{c}" for i, c in enumerate(contexts)
        )
        user_prompt = (
            f"Context:\n{context_block}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self._invoke_with_retry(messages)
        text = response.content if isinstance(response.content, str) else str(response.content)
        return text.strip()

    def _invoke_with_retry(self, messages, max_retries: int = 5):
        for attempt in range(max_retries + 1):
            try:
                return self._llm.invoke(messages)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM generation attempt %d failed: %s", attempt + 1, exc)
                if attempt >= max_retries:
                    raise
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError("unreachable")


_default_generator: Generator | None = None


def get_generator(dataset: str = "math") -> Generator:
    global _default_generator
    if _default_generator is None or _default_generator.dataset != dataset:
        _default_generator = Generator(dataset=dataset)
    return _default_generator