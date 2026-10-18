from __future__ import annotations

import argparse

from app.config import redact
from app.pipeline import run_meeting
from app.selfcheck import run_selfcheck


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one meeting from transcript through proposal")
    run.add_argument("--meeting", default="meeting_a")
    sub.add_parser("selfcheck", help="Check transcripts, chunking, merge, and validators")
    args = parser.parse_args(argv)
    try:
        if args.command == "selfcheck":
            run_selfcheck()
        else:
            run_meeting(args.meeting)
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from exc


if __name__ == "__main__":
    main()
