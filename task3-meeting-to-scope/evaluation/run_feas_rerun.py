"""Re-run only feasibility cases. Writes results_v2_feas_rerun.csv."""
import csv
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))
import run_eval_v2 as r

FIELDS = ["task", "case_id", "model", "expected", "actual", "quality",
          "latency_ms", "cost", "passed", "failure_reason"]

def main():
    cases = [c for c in csv.DictReader(r.CASES.open(encoding="utf-8"))
             if c["task"] == "feasibility"]
    rows = []
    for case in cases:
        for model in (r.HAIKU, r.SONNET):
            print(case["case_id"], model, flush=True)
            rows.append(r.run_case(case, model))
    out = EVAL_DIR / "results_v2_feas_rerun.csv"
    with out.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)

if __name__ == "__main__":
    main()