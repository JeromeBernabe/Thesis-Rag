"""Phase 0.5: Inspect dataset structure before running experiments.

Scans data/datasets/ for all known dataset files, detects format, prints
column/field names, and shows sample records.
"""

import csv
import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402


def _read_jsonl_sample(path: Path, n: int = 3) -> tuple[int, list[str], list[dict]]:
    count = 0
    fields = []
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                if not fields:
                    fields = list(rec.keys())
                if len(samples) < n:
                    samples.append(rec)
    return count, fields, samples


def _read_json_sample(path: Path, n: int = 3) -> tuple[int, list[str], list[dict]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        for key in ("data", "records", "examples", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return 0, [], []
    count = len(data)
    fields = []
    samples = []
    for rec in data[:n]:
        if isinstance(rec, dict):
            if not fields:
                fields = list(rec.keys())
            samples.append(rec)
    return count, fields, samples


def _read_csv_sample(path: Path, n: int = 3) -> tuple[int, list[str], list[dict]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        samples = []
        count = 0
        for row in reader:
            count += 1
            if len(samples) < n:
                samples.append(dict(row))
    return count, list(fields), samples


def inspect_file(path: Path, sample_n: int = 3) -> None:
    suffix = path.suffix.lower()
    if suffix == ".jsonl" or suffix == ".ndjson":
        count, fields, samples = _read_jsonl_sample(path, sample_n)
        fmt = "JSONL"
    elif suffix == ".json":
        count, fields, samples = _read_json_sample(path, sample_n)
        fmt = "JSON"
    elif suffix == ".csv":
        count, fields, samples = _read_csv_sample(path, sample_n)
        fmt = "CSV"
    else:
        print(f"  {path.name}: unsupported format ({suffix})")
        return

    print(f"  {path.name} ({fmt})")
    print(f"    Records: {count}")
    print(f"    Fields:  {fields}")
    for i, sample in enumerate(samples):
        print(f"    Sample {i + 1}:")
        for k, v in sample.items():
            val_str = str(v)
            if len(val_str) > 120:
                val_str = val_str[:120] + "..."
            print(f"      {k}: {val_str}")
    print()


def main() -> None:
    print("=" * 70)
    print("DATASET INSPECTION")
    print("=" * 70)
    print()

    datasets_dir = settings.DATASETS_DIR
    print(f"Scanning: {datasets_dir}")
    print()

    if not datasets_dir.exists():
        print(f"ERROR: {datasets_dir} does not exist.")
        return

    files = sorted(datasets_dir.rglob("*"))
    data_files = [f for f in files if f.is_file() and f.suffix in (".json", ".jsonl", ".ndjson", ".csv")]

    if not data_files:
        print("No data files found.")
        return

    for path in data_files:
        rel = path.relative_to(datasets_dir)
        print(f"[{rel.parent}]")
        inspect_file(path)

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for ds in settings.VALID_DATASETS:
        corpus_patterns = settings.DATASET_CORPUS_FILES.get(ds, [])
        test_patterns = settings.DATASET_TEST_FILES.get(ds, [])
        print(f"  {ds}:")
        print(f"    Corpus files: {corpus_patterns}")
        print(f"    Test files:   {test_patterns}")
    print()
    print("Review the output above. If the detected fields look correct,")
    print("you can proceed with running the experiment.")


if __name__ == "__main__":
    main()
