import csv

files = ["fintech", "hotpot", "math", "ragtruth"]
metrics = ["faithfulness", "answer_relevancy", "context_recall"]

header = "{:<10} {:<8} {:<18} {:>6} {:>6} {:>6}".format(
    "Dataset", "System", "Metric", "Valid", "NaN", "Total"
)
print(header)
print("-" * 65)
for ds in files:
    rows = list(csv.DictReader(open(f"results/ragas_results_{ds}.csv", encoding="utf-8")))
    for sys_id in ["A", "B"]:
        for m in metrics:
            total = sum(1 for r in rows if r["system_id"] == sys_id)
            valid = sum(1 for r in rows if r["system_id"] == sys_id and r[m])
            nan = total - valid
            print("{:<10} {:<8} {:<18} {:>6} {:>6} {:>6}".format(ds, sys_id, m, valid, nan, total))
