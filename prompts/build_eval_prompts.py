import argparse
import json
import random

from config import settings
from src.data_loader import dataset_test_records


def build_eval_prompts(
    dataset: str = "math",
    num_prompts: int = settings.NUM_EVAL_PROMPTS,
    output_path=None,
    seed: int = settings.PROMPT_BUILD_SEED,
    require_solution: bool = True,
    data_dir=None,
) -> list[dict]:
    dataset = dataset.lower()
    if dataset not in settings.VALID_DATASETS:
        raise SystemExit(
            f"Unknown dataset {dataset!r}. Must be one of {settings.VALID_DATASETS}"
        )
    if output_path is None:
        output_path = settings.DATASET_EVAL_PROMPTS_PATH[dataset]
    records = dataset_test_records(dataset, data_dir)
    if not records:
        raise SystemExit(
            f"No {dataset} test records found in {settings.DATASETS_DIR}. "
            "Drop your data files there first."
        )

    usable = [
        r for r in records if r["problem"] and (r["solution"] if require_solution else True)
    ]
    if not usable:
        raise SystemExit("No records with both a question and an answer were found.")
    usable.sort(key=lambda r: r["id"])
    rng = random.Random(seed)
    rng.shuffle(usable)
    selected = usable[:num_prompts]
    prompts = [
        {"id": r["id"], "question": r["problem"], "ground_truth": r["solution"]}
        for r in selected
    ]
    output_path = str(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(prompts)} {dataset} eval prompts to {output_path}")
    return prompts


def load_eval_prompts(dataset: str = "math", path=None):
    if path is None:
        path = settings.DATASET_EVAL_PROMPTS_PATH.get(dataset, settings.PROMPTS_DIR / "eval_prompts_math.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build eval prompts from a dataset.")
    parser.add_argument("--dataset", default="math", choices=list(settings.VALID_DATASETS))
    parser.add_argument("--num", type=int, default=settings.NUM_EVAL_PROMPTS)
    parser.add_argument("--seed", type=int, default=settings.PROMPT_BUILD_SEED)
    parser.add_argument("--dir", default=None, help="data directory (default: data/datasets)")
    args = parser.parse_args()
    build_eval_prompts(dataset=args.dataset, num_prompts=args.num, seed=args.seed, data_dir=args.dir)
