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
]


class ResultLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._write_header()

    def _write_header(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            return
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
    ) -> None:
        row = {
            "prompt_id": prompt_id,
            "system_id": system_id,
            "retrieved_k": retrieved_k if retrieved_k is not None else "",
            "faithfulness": faithfulness if faithfulness is not None else "",
            "answer_relevancy": answer_relevancy if answer_relevancy is not None else "",
            "context_recall": context_recall if context_recall is not None else "",
        }
        with self._lock:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writerow(row)