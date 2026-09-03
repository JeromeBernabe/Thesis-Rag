import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from src.stats_analysis import load_results, per_prompt_comparison, report  # noqa: E402

METRICS = ["faithfulness", "answer_relevancy", "context_recall"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5: analyze RAGAS results.")
    parser.add_argument("--results", default=str(settings.RAGAS_RESULTS_PATH))
    parser.add_argument("--per-prompt", action="store_true",
                        help="also print per-prompt comparison tables.")
    parser.add_argument("--save-report", default=str(settings.RESULTS_DIR / "analysis_report.txt"))
    args = parser.parse_args()

    df = load_results(args.results)
    if df.empty:
        raise SystemExit(f"No results found in {args.results}. Run run_experiment.py first.")

    report(df, out_path=args.save_report)

    if args.per_prompt:
        for metric in METRICS:
            print("\n" + "=" * 78)
            print(f"PER-PROMPT COMPARISON: {metric}")
            print("=" * 78)
            print(per_prompt_comparison(df, metric).to_string(index=False))


if __name__ == "__main__":
    main()