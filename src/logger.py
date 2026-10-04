import csv
import os
import threading
from pathlib import Path


def promote(staged: Path, final: Path) -> None:
    """Replace `final` with `staged`, only once the run has produced something.

    Appending is safe for *crashes* but unsafe for *reruns*. Two runs of the
    same dataset in one CSV give `prompt_id` duplicates across `system_id`, and
    `df.pivot(...)` then raises "Index contains duplicate entries" - so a
    completed file cannot be extended and still be analysable. There is no way
    to tell "row 51 continues run 1" from "row 51 begins run 2".

    So a run writes to a sibling staging file and renames it into place at the
    end. A crashed run therefore leaves the previous results intact *and* keeps
    its own partial output for inspection or resumption, which is the only
    version of "append" that does not corrupt the analysis.
    """
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, final)

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


def _fsync(handle) -> None:
    """Push a handle's bytes to the platter.

    Every row is worth hours of judge time, so a row that has not reached the
    disk has not been recorded. Best effort: a filesystem that refuses to fsync
    (some network mounts, and the Windows console handle under some conditions)
    should degrade to a flushed-but-unsynced row rather than lose the run.
    """
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass


class ResultLogger:
    """Append-only CSV sink for per-prompt results.

    **Why this does not truncate.** The obvious implementation opens the
    destination with mode ``"w"`` in the constructor to write a header. That
    destroys the file, and a benchmark run takes six to nine hours per dataset -
    so starting the next run deletes the previous one before it has produced
    anything to replace it, and a crash an hour in leaves a header-only file.
    This has happened: `results/ragas_results_math.csv` is 78 bytes of header.

    The header is therefore written only when the file does not exist yet, and
    an existing file is appended to. Callers that genuinely want to discard the
    previous run pass ``fresh=True``.

    Rows are flushed and fsynced as they are written, so a run killed by a host
    that never gets to clean up still leaves every row that was completed. That
    is the whole point: the expensive part is the judge, and losing its output
    to a process death is what makes the results unreproducible.
    """

    def __init__(self, path: Path, *, fresh: bool = False):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ensure_header(fresh=fresh)

    def _ensure_header(self, *, fresh: bool) -> None:
        """Create the file with a header, or leave an existing one untouched.

        Neither ``"w"`` nor ``"a"`` alone can express "header only if this file
        is new": ``"w"`` destroys completed work, and ``"a"`` with an
        unconditional ``writeheader()`` appends a second header row to an
        existing file. So the size is checked first and the mode is chosen to
        match.

        The parent directory is created either way - a missing ``results/``
        should not be a reason to fail before the run has even started.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fresh:
            # Explicitly requested overwrite. Still written and synced, so a
            # crash mid-write cannot leave a half-deleted file.
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
                f.flush()
                _fsync(f)
            return
        if self.path.exists() and self.path.stat().st_size > 0:
            # Already has content. Appending is the safe default: whatever is in
            # here is somebody's completed, hours-old work.
            return
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
            f.flush()
            _fsync(f)

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
                csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(row)
                # Without this the row sits in a buffer and a killed process
                # takes it with it. The lock covers the append only; a slow fsync
                # on one thread must not block another's.
                f.flush()
                _fsync(f)