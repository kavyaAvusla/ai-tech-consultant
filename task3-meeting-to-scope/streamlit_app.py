from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.db import get_baseline, init_db, latest_version, list_versions, load_run_bundle
from app.versions import mark_sent
from app.schemas import FEASIBILITY_LABELS

st.set_page_config(page_title="Meeting to scope", layout="wide")
st.title("Meeting to scope")
st.caption("Role-played meetings only. No real clients. Task 1 is called over HTTP, not imported.")

init_db()
meeting_id = st.selectbox(
    "Meeting",
    ["mtg-a-search-mobile", "mtg-b-checkout", "mtg-c-search-followup"],
    format_func=lambda value: {
        "mtg-a-search-mobile": "Meeting A — search, filters, mobile",
        "mtg-b-checkout": "Meeting B — checkout and payments",
        "mtg-c-search-followup": "Meeting C — follow-up to A",
    }[value],
)
bundle = load_run_bundle(meeting_id)
if bundle is None:
    st.info("No stored run for this meeting yet. From task3-meeting-to-scope run: python -m app run --meeting meeting_a")
    st.stop()

rate_text = st.text_input("Reviewer hourly rate", value="", help="Leave empty to show hours only.")
rate: float | None = None
if rate_text.strip():
    try:
        rate = float(rate_text.strip())
    except ValueError:
        st.error("Hourly rate must be a number, or left empty.")
        rate = None

st.subheader("Requirements")
st.dataframe(
    [
        {
            "id": row["id"],
            "status": row["status"],
            "explicitness": row["explicitness"],
            "priority": row["priority"],
            "estimate_status": row["estimate_status"],
            "speaker": row["speaker"],
            "timestamp": row["source_timestamp"],
            "description": row["description"],
            "source_quote": row["source_quote"],
            "existing_solution": row["existing_solution"],
        }
        for row in bundle["requirements"]
    ],
    hide_index=True,
    width="stretch",
)

st.subheader("Feasibility")
st.dataframe(
    [
        {
            "id": row["requirement_id"],
            "classification": FEASIBILITY_LABELS.get(row["classification"], row["classification"]),
            "evidence": row["kb_evidence"],
            "verification": row["verification_status"],
            "feature_absence_claimed": row["feature_absence_claimed"],
            "existing_solution": row["existing_solution"],
        }
        for row in bundle["feasibility"]
    ],
    hide_index=True,
    width="stretch",
)

estimate = bundle["estimate"]
st.subheader("Estimate")
if rate is None:
    st.write("Hourly rate is empty. Hours only. No price is quoted.")
else:
    likely = float(estimate["likely_hours_total"])
    st.write(
        f"Reviewer rate {rate:g} applied to {likely:g} likely hours "
        f"is {likely * rate:g}. This figure is calculated here. It is not a quoted price."
    )
st.dataframe(
    [
        {
            "task": task["id"],
            "requirement": task["requirement_id"],
            "low_hours": task["low_hours"],
            "likely_hours": task["likely_hours"],
            "high_hours": task["high_hours"],
            "blocked": task["blocked"],
            "reasoning": task["reasoning"],
            "assumptions": "; ".join(task["assumptions"]),
            "dependencies": "; ".join(task["dependencies"]),
        }
        for task in estimate["tasks"]
    ],
    hide_index=True,
    width="stretch",
)

st.subheader("Proposal")
for section in bundle["proposal"]["sections"]:
    st.markdown(f"### {section['heading']}")
    st.write(section["body"])

project_id = bundle["run"]["project_id"]
baseline = get_baseline(project_id)
revised = latest_version(project_id, "mtg-c-search-followup")
st.subheader("Version history")
history_rows = list_versions(project_id)
if history_rows:
    st.dataframe(
        [
            {
                "version": row["version_number"],
                "status": row["status"],
                "baseline": "yes" if row["is_baseline"] else "",
                "reviewer": row["reviewer_name"] or "",
                "timestamp": row["reviewed_at"] or row["created_at"],
                "meeting": row["meeting_id"],
            }
            for row in history_rows
        ],
        hide_index=True,
        width="stretch",
    )
else:
    st.write("No versions yet.")

if revised and revised["status"] != "approved":
    st.warning("The revised scope is not approved. Sending is blocked.")
    if st.button("Simulate send of the revised version"):
        try:
            mark_sent(revised["id"])
        except RuntimeError as exc:
            st.error(str(exc))

if baseline and revised and revised["change_report"]:
    report = revised["change_report"]
    st.subheader("Approved baseline vs revised follow-up")
    st.caption("Comparison uses the approved baseline, not a later AI draft.")
    if report["assumptions"]:
        st.info("Assumption: " + " ".join(report["assumptions"]))
    if report["open_questions"]:
        st.warning("Open questions: " + " | ".join(report["open_questions"]))
    for label in ("added", "removed", "modified", "unresolved"):
        if report[label]:
            bits = []
            for row in report[label]:
                extra = " (extra quotation)" if row.get("extra_quotation") else ""
                bits.append(f"{row.get('id')} {row.get('description', row.get('reason', ''))}{extra}")
            st.write(f"**{label.title()}:** " + "; ".join(bits))
    left, right = st.columns(2)
    with left:
        st.markdown("### Original approved scope")
        for section in baseline["scope"]["sections"]:
            st.markdown(f"**{section['heading']}**")
            st.write(section["body"])
    with right:
        st.markdown("### Revised scope (not approved)")
        for section in revised["scope"]["sections"]:
            st.markdown(f"**{section['heading']}**")
            st.write(section["body"])
