from __future__ import annotations

import argparse

from app.config import redact
from app.changes import run_followup
from app.db import list_versions
from app.pipeline import load_transcripts, resolve_transcript
from app.pipeline import run_meeting
from app.selfcheck import run_selfcheck
from app.versions import approve_baseline, mark_sent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one meeting from transcript through proposal")
    run.add_argument("--meeting", default="meeting_a")
    approve = sub.add_parser("approve", help="Approve the latest run as the baseline")
    approve.add_argument("--meeting", default="meeting_a")
    approve.add_argument("--reviewer", required=True)
    follow = sub.add_parser("followup", help="Compare a follow-up meeting with the approved baseline")
    follow.add_argument("--meeting", default="meeting_c")
    send = sub.add_parser("send", help="Simulated send. Refuses unapproved versions")
    send.add_argument("--version-id", type=int, required=True)
    history = sub.add_parser("history")
    history.add_argument("--project", default="proj-lakeside-directory")
    sub.add_parser("selfcheck", help="Check transcripts, chunking, merge, and validators")
    args = parser.parse_args(argv)
    try:
        if args.command == "selfcheck":
            run_selfcheck()
        elif args.command == "approve":
            saved = approve_baseline(args.meeting, args.reviewer)
            print(f"Approved baseline version {saved['version_number']} (id {saved['id']}) by {args.reviewer}")
            _print_history(saved["project_id"])
        elif args.command == "followup":
            run_followup(args.meeting)
            transcript = resolve_transcript(args.meeting, load_transcripts())
            _print_history(transcript.project_id)
        elif args.command == "send":
            saved = mark_sent(args.version_id)
            print(f"Marked version {saved['version_number']} sent")
        elif args.command == "history":
            _print_history(args.project)
        else:
            run_meeting(args.meeting)
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from exc


def _print_history(project_id: str) -> None:
    print(f"\nVERSION HISTORY {project_id}")
    for row in list_versions(project_id):
        baseline = " baseline" if row["is_baseline"] else ""
        reviewer = row["reviewer_name"] or "-"
        when = row["reviewed_at"] or row["created_at"]
        print(
            f"v{row['version_number']} id={row['id']} status={row['status']}{baseline} "
            f"reviewer={reviewer} at={when} meeting={row['meeting_id']}"
        )


if __name__ == "__main__":
    main()
