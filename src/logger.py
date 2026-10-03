import csv
import threading
from pathlib import Path

CSV_COLUMNS = [
    "prompt_id",
    "system_id",
    "retrieved_k",
    "faithfulness",
    "answer_relevancy",
    "context_recall",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "judge_prompt_tokens",
    "judge_completion_tokens",
    "retrieval_time_s",
    "generation_time_s",
    "judge_time_s",
    "total_time_s",
]


class ResultLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._write_header()

    def _write_header(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()

    def log(
        self,
        prompt_id,
        system_id,
        faithfulness,
        answer_relevancy,
        context_recall,
        retrieved_k=None,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        judge_prompt_tokens=None,
        judge_completion_tokens=None,
        retrieval_time_s=None,
        generation_time_s=None,
        judge_time_s=None,
        total_time_s=None,
    ) -> None:
        row = {
            "prompt_id": prompt_id,
            "system_id": system_id,
            "retrieved_k": retrieved_k if retrieved_k is not None else "",
            "faithfulness": faithfulness if faithfulness is not None else "",
            "answer_relevancy": answer_relevancy if answer_relevancy is not None else "",
            "context_recall": context_recall if context_recall is not None else "",
            "prompt_tokens": prompt_tokens if prompt_tokens is not None else "",
            "completion_tokens": completion_tokens if completion_tokens is not None else "",
            "total_tokens": total_tokens if total_tokens is not None else "",
            "judge_prompt_tokens": judge_prompt_tokens if judge_prompt_tokens is not None else "",
            "judge_completion_tokens": judge_completion_tokens if judge_completion_tokens is not None else "",
            "retrieval_time_s": f"{retrieval_time_s:.4f}" if retrieval_time_s is not None else "",
            "generation_time_s": f"{generation_time_s:.4f}" if generation_time_s is not None else "",
            "judge_time_s": f"{judge_time_s:.4f}" if judge_time_s is not None else "",
            "total_time_s": f"{total_time_s:.4f}" if total_time_s is not None else "",
        }
        with self._lock:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writerow(row)