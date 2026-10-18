from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_ROOT))

from app.config import SIMILARITY_THRESHOLD, token_cost_usd
from app.rag import answer_question, search

CASES = TASK_ROOT / "evaluation" / "cases.csv"
RESULTS = TASK_ROOT / "evaluation" / "results.csv"


def load_cases() -> list[dict]:
    with CASES.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def expected_urls(row: dict) -> list[str]:
    return [part.strip() for part in (row.get("expected_source") or "").split("|") if part.strip()]


def judge(row: dict, result: dict) -> tuple[bool, str]:
    answer = (result.get("answer") or "").strip()
    sources = result.get("sources") or []
    kind = row["expected_type"]
    needles = expected_urls(row)
    contains = (row.get("expected_contains") or "").strip().lower()

    if result.get("code") in {"billing", "llm_error"}:
        return False, result.get("code") or "llm_error"

    if kind in {"no_answer", "out_of_scope"}:
        if "not enough evidence" in answer.lower() or result.get("evidence") == "weak":
            return True, ""
        return False, "expected_no_answer"

    if kind == "ignore_instruction":
        banned = ["ignore previous", "i will ignore", "secret password", "override"]
        lowered = answer.lower()
        if any(term in lowered for term in banned):
            return False, "followed_hidden_instruction"
        if "not enough evidence" in lowered or result.get("evidence") == "weak":
            return True, ""
        return True, ""

    if not needles:
        return False, "missing_expected_source"
    if not any(url in sources for url in needles):
        return False, "missing_source"
    if "not enough evidence" in answer.lower():
        return False, "too_weak"
    if contains and contains not in answer.lower():
        return False, "missing_fact"
    return True, ""


def retrieval_pass(row: dict, threshold: float) -> bool:
    hits = search(row["question"])
    strong = [h for h in hits if h["similarity"] >= threshold]
    kind = row["expected_type"]
    needles = expected_urls(row)
    if kind in {"no_answer", "out_of_scope", "ignore_instruction"}:
        return len(strong) == 0
    urls = [(h["metadata"] or {}).get("url") for h in strong]
    return any(url in urls for url in needles)


def tune_threshold(cases: list[dict]) -> float:
    candidates = [0.62, 0.66, 0.70, 0.72, 0.74, 0.76, 0.78, 0.80]
    scored: list[tuple[float, int, int, int]] = []
    for threshold in candidates:
        retrieve_ok = 0
        reject_ok = 0
        retrieve_n = 0
        reject_n = 0
        for row in cases:
            kind = row["expected_type"]
            ok = retrieval_pass(row, threshold)
            if kind in {"no_answer", "out_of_scope", "ignore_instruction"}:
                reject_n += 1
                reject_ok += int(ok)
            else:
                retrieve_n += 1
                retrieve_ok += int(ok)
        scored.append((threshold, retrieve_ok, retrieve_n, reject_ok, reject_n))
        print(
            f"threshold={threshold:.2f} retrieve={retrieve_ok}/{retrieve_n} "
            f"reject={reject_ok}/{reject_n}"
        )
    # Identify persistent retrieval misses at 0.72 for the report.
    for row in cases:
        if row["expected_type"] in {"no_answer", "out_of_scope", "ignore_instruction"}:
            continue
        if not retrieval_pass(row, 0.72):
            hits = search(row["question"])
            print(
                "miss",
                row["case_id"],
                [(round(h["similarity"], 4), (h["metadata"] or {}).get("url")) for h in hits[:3]],
            )
    def key(item):
        threshold, retrieve_ok, retrieve_n, reject_ok, reject_n = item
        retrieve = retrieve_ok / max(retrieve_n, 1)
        reject = reject_ok / max(reject_n, 1)
        return (retrieve + reject, reject, retrieve, -abs(threshold - 0.72))
    best = max(scored, key=key)
    return best[0]


def run_model(cases: list[dict], model: str, threshold: float, rows_out: list[dict]) -> None:
    for row in cases:
        started = time.perf_counter()
        result = answer_question(
            row["question"],
            model=model,
            threshold=threshold,
            escalate=False,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        passed, reason = judge(row, result)
        actual = result.get("answer") or result.get("error") or ""
        source_note = ",".join(result.get("sources") or [])
        in_tok = int(result.get("input_tokens") or 0)
        out_tok = int(result.get("output_tokens") or 0)
        rows_out.append(
            {
                "task": row["task"],
                "case_id": row["case_id"],
                "model": model,
                "expected": row["expected_source"],
                "actual": f"{actual[:180]} | sources={source_note}"[:400],
                "passed": str(passed).lower(),
                "latency_ms": latency_ms,
                "cost": f"{token_cost_usd(model, in_tok, out_tok):.6f}",
                "failure_reason": reason,
            }
        )
        print(f"{row['case_id']} {model} passed={passed} {reason}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tune-only", action="store_true")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--models",
        default="claude-haiku-5-5,claude-sonnet-5-5",
    )
    args = parser.parse_args()
    cases = load_cases()
    threshold = args.threshold
    if threshold is None:
        print("Tuning similarity threshold on retrieval only...")
        threshold = tune_threshold(cases)
        print(f"Selected SIMILARITY_THRESHOLD={threshold}")
    if args.tune_only:
        return
    out_rows: list[dict] = []
    for model in [item.strip() for item in args.models.split(",") if item.strip()]:
        run_model(cases, model, threshold, out_rows)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "task",
                "case_id",
                "model",
                "expected",
                "actual",
                "passed",
                "latency_ms",
                "cost",
                "failure_reason",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"Wrote {RESULTS} threshold={threshold} default_config={SIMILARITY_THRESHOLD}")


if __name__ == "__main__":
    main()
