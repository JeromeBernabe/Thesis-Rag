import csv
import json
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PROBLEM_KEYS = ("problem", "question", "prompt", "query")
SOLUTION_KEYS = ("solution", "answer", "response", "ground_truth", "output", "rationale")


def _detect_record_keys(record: dict) -> tuple[str | None, str | None]:
    problem_key = next(
        (k for k in record if k.lower() in PROBLEM_KEYS), None
    )
    solution_key = next(
        (k for k in record if k.lower() in SOLUTION_KEYS), None
    )
    return problem_key, solution_key


def _parse_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping unparseable line in %s", path)
    return records


def _parse_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "records", "examples", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def _parse_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse_txt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    records = []
    for i, part in enumerate(parts):
        records.append({"problem": part, "solution": "", "id": f"{path.stem}-{i}"})
    return records


# ---------------------------------------------------------------------------
# Generic loader (used for Math CSV and sample JSON)
# ---------------------------------------------------------------------------

def load_math_records(directory: Path | None = None, file_patterns=None) -> list[dict]:
    directory = Path(directory) if directory is not None else settings.MATH_DATASET_DIR
    if file_patterns is None:
        files = sorted(directory.glob("*"))
    else:
        files = []
        for pat in file_patterns:
            files.extend(sorted(directory.glob(pat)))
        files = sorted(set(files))
    records: list[dict] = []
    for path in files:
        if not path.is_file():
            continue
        try:
            if path.suffix in (".jsonl", ".ndjson"):
                raw = _parse_jsonl(path)
            elif path.suffix == ".json":
                raw = _parse_json(path)
            elif path.suffix == ".csv":
                raw = _parse_csv(path)
            elif path.suffix in (".txt", ".md"):
                raw = _parse_txt(path)
            else:
                logger.info("ignoring unsupported file type: %s", path.name)
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to parse %s: %s", path.name, exc)
            continue

        for i, record in enumerate(raw):
            if not isinstance(record, dict):
                continue
            problem_key, solution_key = _detect_record_keys(record)
            if problem_key is None:
                continue
            problem = str(record.get(problem_key, "")).strip()
            solution = (
                str(record.get(solution_key, "")).strip()
                if solution_key is not None
                else ""
            )
            if not problem:
                continue
            rid = record.get("id") or record.get("prompt_id") or f"{path.stem}-{i}"
            records.append(
                {"id": str(rid), "problem": problem, "solution": solution}
            )
    return records


# ---------------------------------------------------------------------------
# FinTech loader
# ---------------------------------------------------------------------------

def _build_fintech_doc_text(rec: dict) -> str:
    parts = []
    pre = rec.get("pre_text", [])
    if pre:
        parts.append("Pre-text:\n" + " ".join(str(p) for p in pre))
    post = rec.get("post_text", [])
    if post:
        parts.append("Post-text:\n" + " ".join(str(p) for p in post))
    table = rec.get("table_ori") or rec.get("table")
    if table:
        if isinstance(table, list):
            table_lines = []
            for row in table:
                if isinstance(row, list):
                    table_lines.append(" | ".join(str(c) for c in row))
                elif isinstance(row, dict):
                    table_lines.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
                else:
                    table_lines.append(str(row))
            parts.append("Table:\n" + "\n".join(table_lines))
    return "\n\n".join(parts)


def load_fintech_records(directory: Path | None = None, file_patterns=None) -> list[dict]:
    directory = Path(directory) if directory is not None else settings.FINTECH_DIR
    if file_patterns is None:
        file_patterns = ["FinTech-*.json"]
    records: list[dict] = []
    files = []
    for pat in file_patterns:
        files.extend(sorted(directory.glob(pat)))
    files = sorted(set(files))
    for path in files:
        if not path.is_file():
            continue
        try:
            raw = _parse_json(path)
        except Exception as exc:
            logger.warning("failed to parse %s: %s", path.name, exc)
            continue
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            qa = rec.get("qa")
            if not isinstance(qa, dict):
                continue
            question = str(qa.get("question", "")).strip()
            answer = str(qa.get("answer", "")).strip()
            if not question:
                continue
            rid = rec.get("id", "")
            doc_text = _build_fintech_doc_text(rec)
            records.append({
                "id": str(rid),
                "problem": question,
                "solution": answer,
                "doc_text": doc_text,
            })
    logger.info("Loaded %d FinTech records from %s", len(records), directory)
    return records


# ---------------------------------------------------------------------------
# Hotpot loader
# ---------------------------------------------------------------------------

def _flatten_hotpot_context(context: list) -> str:
    parts = []
    for item in context:
        if isinstance(item, list) and len(item) == 2:
            title, sentences = item
            if isinstance(sentences, list):
                parts.append(f"{title}: {' '.join(str(s) for s in sentences)}")
            else:
                parts.append(f"{title}: {sentences}")
        elif isinstance(item, str):
            parts.append(item)
    return "\n\n".join(parts)


def load_hotpot_records(directory: Path | None = None, file_patterns=None) -> list[dict]:
    directory = Path(directory) if directory is not None else settings.HOTPOT_DIR
    if file_patterns is None:
        file_patterns = ["hotpot_*.json"]
    records: list[dict] = []
    files = []
    for pat in file_patterns:
        files.extend(sorted(directory.glob(pat)))
    files = sorted(set(files))
    for path in files:
        if not path.is_file():
            continue
        try:
            raw = _parse_json(path)
        except Exception as exc:
            logger.warning("failed to parse %s: %s", path.name, exc)
            continue
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            question = str(rec.get("question", "")).strip()
            if not question:
                continue
            rid = rec.get("_id", "")
            context = rec.get("context", [])
            doc_text = _flatten_hotpot_context(context)
            answer_ref = doc_text
            records.append({
                "id": str(rid),
                "problem": question,
                "solution": answer_ref,
                "doc_text": doc_text,
            })
    logger.info("Loaded %d hotpot records from %s", len(records), directory)
    return records


# ---------------------------------------------------------------------------
# RagTruth loader
# ---------------------------------------------------------------------------

def load_ragtruth_source_records(directory: Path | None = None, file_patterns=None) -> list[dict]:
    """Load RagTruth source documents (corpus for indexing)."""
    directory = Path(directory) if directory is not None else settings.RAGTRUTH_DIR
    if file_patterns is None:
        file_patterns = ["Rag_Truth_Source.jsonl"]
    records: list[dict] = []
    files = []
    for pat in file_patterns:
        files.extend(sorted(directory.glob(pat)))
    files = sorted(set(files))
    for path in files:
        if not path.is_file():
            continue
        try:
            raw = _parse_jsonl(path)
        except Exception as exc:
            logger.warning("failed to parse %s: %s", path.name, exc)
            continue
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            source_id = str(rec.get("source_id", "")).strip()
            source_info = str(rec.get("source_info", "")).strip()
            if not source_id or not source_info:
                continue
            records.append({
                "id": source_id,
                "problem": source_info,
                "solution": "",
                "doc_text": source_info,
            })
    logger.info("Loaded %d RagTruth source records from %s", len(records), directory)
    return records


def load_ragtruth_response_records(directory: Path | None = None, file_patterns=None) -> list[dict]:
    """Load RagTruth responses (filtered to a single model) for eval prompts."""
    directory = Path(directory) if directory is not None else settings.RAGTRUTH_DIR
    if file_patterns is None:
        file_patterns = ["Rag_Truth_Response.jsonl"]
    target_model = settings.RAGTRUTH_RESPONSE_MODEL
    records: list[dict] = []
    files = []
    for pat in file_patterns:
        files.extend(sorted(directory.glob(pat)))
    files = sorted(set(files))
    for path in files:
        if not path.is_file():
            continue
        try:
            raw = _parse_jsonl(path)
        except Exception as exc:
            logger.warning("failed to parse %s: %s", path.name, exc)
            continue
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            model = str(rec.get("model", "")).strip()
            if model != target_model:
                continue
            rid = str(rec.get("id", "")).strip()
            source_id = str(rec.get("source_id", "")).strip()
            response = str(rec.get("response", "")).strip()
            if not rid or not response:
                continue
            records.append({
                "id": rid,
                "problem": response,
                "solution": response,
                "source_id": source_id,
            })
    logger.info("Loaded %d RagTruth response records (model=%s) from %s",
                len(records), target_model, directory)
    return records


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def load_records(
    dataset: str,
    directory: Path | None = None,
    file_patterns=None,
) -> list[dict]:
    dataset = dataset.lower()
    if dataset == "fintech":
        return load_fintech_records(directory, file_patterns)
    elif dataset == "hotpot":
        return load_hotpot_records(directory, file_patterns)
    elif dataset == "math":
        return load_math_records(directory, file_patterns)
    elif dataset == "ragtruth":
        return load_ragtruth_source_records(directory, file_patterns)
    else:
        raise ValueError(f"Unknown dataset: {dataset!r}. Must be one of {settings.VALID_DATASETS}")


def dataset_corpus_records(dataset: str, directory: Path | None = None) -> list[dict]:
    """Load the corpus (index) records for a dataset (training files)."""
    if dataset == "ragtruth":
        return load_ragtruth_source_records(directory)
    if directory is None:
        directory = settings.DATASETS_DIR
    patterns = settings.DATASET_CORPUS_FILES.get(dataset)
    return load_records(dataset, directory, patterns)


def dataset_test_records(dataset: str, directory: Path | None = None) -> list[dict]:
    """Load the test records for a dataset (used to build eval prompts)."""
    if dataset == "ragtruth":
        return load_ragtruth_response_records(directory)
    if directory is None:
        directory = settings.DATASETS_DIR
    patterns = settings.DATASET_TEST_FILES.get(dataset)
    return load_records(dataset, directory, patterns)


def format_doc_text(dataset: str, record: dict) -> str:
    """Render a record as an indexed document string."""
    if dataset == "fintech":
        text = record.get("doc_text")
        if text:
            return text
        return f"Pre-text:\n{record.get('pre_text', '')}"
    elif dataset == "hotpot":
        return record.get("doc_text", "")
    elif dataset == "ragtruth":
        return record.get("doc_text", record.get("problem", ""))
    else:
        return f"Problem:\n{record['problem']}\n\nSolution:\n{record['solution']}".strip()


def build_indexed_corpus(
    dataset: str,
    directory: Path | None = None,
) -> tuple[list[str], list[dict]]:
    records = dataset_corpus_records(dataset, directory)
    ids = [f"doc-{r['id']}" for r in records]
    return ids, records
