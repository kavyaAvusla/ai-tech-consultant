from __future__ import annotations

from typing import Any

from app.schemas import FEASIBILITY_LABELS


def print_bundle(bundle: dict[str, Any]) -> None:
    print("\nREQUIREMENTS")
    print(_table(
        ["id", "status", "explicit", "priority", "estimate", "speaker", "time", "description"],
        [
            [
                row["id"],
                row["status"],
                row["explicitness"],
                row["priority"],
                row["estimate_status"],
                row["speaker"],
                row["source_timestamp"],
                row["description"],
            ]
            for row in bundle["requirements"]
        ],
    ))
    print("\nFEASIBILITY")
    print(_table(
        ["id", "classification", "evidence", "verification", "existing_solution"],
        [
            [
                row["requirement_id"],
                FEASIBILITY_LABELS.get(row["classification"], row["classification"]),
                row["kb_evidence"],
                row["verification_status"],
                row["existing_solution"],
            ]
            for row in bundle["feasibility"]
        ],
    ))
    estimate = bundle["estimate"] or {"tasks": [], "hourly_rate": None, "likely_hours_total": 0}
    headers = ["task", "requirement", "low_h", "likely_h", "high_h", "blocked", "reasoning"]
    rows = []
    for task in estimate["tasks"]:
        rows.append([
            task["id"],
            task["requirement_id"],
            _hours(task["low_hours"]),
            _hours(task["likely_hours"]),
            _hours(task["high_hours"]),
            "yes" if task["blocked"] else "no",
            task["reasoning"],
        ])
    print("\nESTIMATE")
    rate = estimate.get("hourly_rate")
    if rate is None:
        print("Hourly rate is empty. Hours only. No price is quoted.")
    else:
        print(f"Reviewer hourly rate is set. Likely cost uses that rate and is not a model-invented price.")
    print(_table(headers, rows))
    print(f"Likely hours total (unblocked): {estimate.get('likely_hours_total')}")
    print("\nPROPOSAL HEADINGS")
    proposal = bundle.get("proposal") or {"sections": []}
    for section in proposal["sections"]:
        print(f"- {section['heading']}")


def _hours(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value:g}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    widths = [len(header) for header in headers]
    rendered = []
    for row in rows:
        cells = [_clip(cell) for cell in row]
        rendered.append(cells)
        for index, cell in enumerate(cells):
            widths[index] = max(widths[index], len(cell))
    lines = [" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("-+-".join("-" * width for width in widths))
    for cells in rendered:
        lines.append(" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)))
    return "\n".join(lines)


def _clip(value: Any, limit: int = 88) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
