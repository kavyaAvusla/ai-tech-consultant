import csv
from collections import defaultdict
from pathlib import Path

rows = list(csv.DictReader(Path("evaluation/results.csv").open(encoding="utf-8")))
by_model = defaultdict(lambda: {"n": 0, "pass": 0, "cost": 0.0, "lat": 0.0, "fail": []})
for row in rows:
    m = by_model[row["model"]]
    m["n"] += 1
    m["pass"] += int(row["passed"] == "true")
    m["cost"] += float(row["cost"] or 0)
    m["lat"] += float(row["latency_ms"] or 0)
    if row["passed"] != "true":
        m["fail"].append(row["case_id"])
print("model n pass cost_usd avg_lat_ms fails")
for model, m in by_model.items():
    print(
        model,
        m["n"],
        m["pass"],
        f"{m['cost']:.6f}",
        int(m["lat"] / max(m["n"], 1)),
        m["fail"] or "-",
    )
print("total_cost", f"{sum(m['cost'] for m in by_model.values()):.6f}")
