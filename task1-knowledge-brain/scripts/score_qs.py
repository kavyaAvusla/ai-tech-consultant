import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))
from app.rag import search

with open("evaluation/cases.csv", encoding="utf-8", newline="") as fh:
    rows = list(csv.DictReader(fh))
for row in rows:
    hits = search(row["question"])
    top = hits[0] if hits else None
    sim = round(top["similarity"], 4) if top else None
    url = (top["metadata"] or {}).get("url") if top else None
    print(f"{row['case_id']} {row['task']:16} sim={sim} {url}")
