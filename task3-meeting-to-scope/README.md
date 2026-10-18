# Task 3 — Meeting to scope

Python pipeline that turns a role-played meeting into requirements, a feasibility check, a scope, an hour estimate, and a proposal. Task 1 is called only through `POST /query` on the Knowledge Brain. This folder does not import Task 1 code.

The transcripts are role-played. They do not describe real clients.

## Setup (Windows, Python 3.12)

```powershell
cd task3-meeting-to-scope
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Copy these into `.env` by hand. Do not commit `.env` and do not paste the values into chat:

- `KB_API_KEY` — same value as `APP_API_KEY` in the repo-root `.env`
- `ANTHROPIC_API_KEY` — same value as `ANTHROPIC_API_KEY` in the repo-root `.env`

`KB_API_URL` and `MODEL_NAME` are already set in `.env.example`. Leave `HOURLY_RATE` empty until a reviewer chooses a number. Empty means the tools show hours and do not quote a price.

If those two secrets are still blank in this folder, the process reads the repo-root `.env` in memory. It does not copy them into this folder's `.env`.

Start Task 1 first, on `http://127.0.0.1:8000`.

## Commands

```powershell
.\.venv\Scripts\python.exe -m app selfcheck
.\.venv\Scripts\python.exe -m app run --meeting meeting_a
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

`meeting_b` and `meeting_c` use the same command. Meeting C shares `project_id` with Meeting A.

SQLite is created at `data/meeting_scope.sqlite` (gitignored). Each agent output stores `prompt_version`. Prompts live in `prompts/v1/`.

## Scope sections

The Scope Agent always writes these ten sections, in order: Context, Goals, In scope, Out of scope, Assumptions, Dependencies, Risks, Open questions, Approach, Acceptance criteria.

A missing Knowledge Brain result is not treated as proof that a feature does not exist. The proposal does not promise an item marked unverified, and it does not invent a delivery date.
