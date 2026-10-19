# AI Tech Consultant

Three small tools built with Claude. Tested on Windows with PowerShell.

## Run all 3 with one command

    powershell -ExecutionPolicy Bypass -File .\start_all.ps1

Three windows open. Wait about 30 seconds.
- Task 1 Knowledge Brain: http://127.0.0.1:8000/docs
- Task 2 Inbox Agent: http://127.0.0.1:3456
- Task 3 Meeting to Scope: http://127.0.0.1:8501

If Task 2 shows "Knowledge service unavailable", refresh the page.

## First-time setup (once)
1. Put your own Anthropic API key in a `.env` file in the repo root. The key name is in `task1-knowledge-brain\.env.example`. Never commit `.env`.
2. Task 1 and Task 3 (Python 3.12): inside each task folder run
   `python -m venv .venv` then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
3. Task 2: inside `task2-inbox-agent` run `npm install`.
4. Task 1 crawl and index step: see `task1-knowledge-brain\README.md`.

## What is simulated
- Task 2 outbox is simulated. Nothing is sent outside this machine.
- The 20-approval demo (Task 2) and the first baseline approval (Task 3) were seeded by script.
- Task 3 hourly rate is empty on purpose. It gives hours only, no price.

## Known limits
- Only 19 articles are indexed, so many feasibility answers are "needs clarification".
- Task 1 similarity threshold was tuned on its own 20 test cases.
- Task 3 expected answers were written with an AI assistant, not an independent reviewer.
- Results change a little from run to run. See EVALS.md.

## More
DESIGN.md (how it is built), EVALS.md (test results), AI_LOG.md (how AI was used).