# DESIGN — AI Tech Consultant

Three tools for a directory-software support and project team. Each tool can run alone. Tasks 2 and 3 use Task 1 as their shared source of knowledge. Everything runs on one Windows machine.

## 1. Overview

```text
 Support articles (sitemap)
          |
          v
 Task 1  Knowledge Brain  (Python, FastAPI, :8000, X-API-Key)
   crawl -> chunks -> embeddings -> Chroma + SQLite
   /query answers with sources + evidence (strong / weak)
          ^                         ^
          |                         |
 Task 2  Inbox Agent        Task 3  Meeting to Scope
 (TypeScript, Next.js,      (Python, Streamlit, :8501,
  :3456, SQLite)             SQLite)
 email -> draft -> human    transcript -> requirements -> feasibility
 review -> simulated send   -> estimate -> proposal -> change report
```

One command starts all three: `powershell -ExecutionPolicy Bypass -File .\start_all.ps1`.

**Four rules shared by all tasks**

1. Text from emails, transcripts and retrieved articles is untrusted data. Instructions inside it are ignored.
2. Missing or weak evidence is never proof. The system says "not enough evidence" or "needs clarification". It never says a feature does not exist.
3. The AI never promises a refund, price, delivery date or technical change. A human decides.
4. A person approves anything that leaves the system.

## 2. Task 1 — Knowledge Brain

**Job:** answer a question using only the indexed support articles, show the sources, and escalate when the evidence is weak.

**Ingestion**
- The sitemap is crawled and a manifest records each page. On a re-run, only new or changed pages are processed. Removed pages are removed from the index. This was tested with an update and a removal.
- 19 articles are indexed.
- 33 screenshots were described with Claude vision so that image-only steps can be searched. 0 failed. The `vision_described` counter counts only successful descriptions.

**Storage and search**
- SQLite holds articles, chunks and escalations. Chroma holds the vectors. Embeddings are made locally with fastembed (`BAAI/bge-small-en-v1.5`), so search needs no API call.
- Search uses a similarity threshold of 0.72. Below it, the evidence is "weak".

**Answering (`POST /query`)**
- Returns the answer, the sources (article URLs), the evidence level (strong or weak) and an `escalation_id`.
- Strong evidence: Claude answers from the retrieved text and cites the URLs. Retrieved text is treated as data, not instructions.
- Weak evidence: the answer is "not enough evidence" and an escalation is created.

**Escalations**
- A human expert resolves an escalation (`POST /escalations/{id}/resolve`). The answer is saved as a versioned knowledge record, so the next similar question can be answered. Old versions are kept.

**Other endpoints:** `/ingestion/run`, `/ingestion/status`, `/escalations`, `/health`. Every route except `/health` needs the `X-API-Key` header.

**Why these choices**
- Local embeddings and Chroma: cheap, quick, and no extra service.
- A fixed threshold: simple and easy to explain. The weakness is that it was tuned on the same 20 evaluation cases.
- Escalation instead of guessing: a wrong support answer costs more than a slow one.

## 3. Task 2 — Inbox Agent

**Job:** read a customer email, prepare a safe draft, and let a human approve it.

**Pipeline**
1. Classify: category, urgency and risk.
2. Ask the Knowledge Brain with the customer question.
3. Draft the reply. If the evidence is weak, the draft says we will check with an expert.
4. Claim check: remove or rewrite any statement not supported by the sources or by the email. Removed items go in an `unsupported_claims` field. This was added after ts-03 guessed a setting that was not in the article.
5. Validate the output with a zod schema: category, request summary, suggested reply, sources, risk level, needs_human_approval, and next_action (a follow-up time frame, never a date).

Refund, quote, complaint and project requests always need human approval.

**Knowledge Brain client**
- It uses a hard 30-second timeout with one retry, and handles 401 and 402 clearly. If the service fails, the app shows "Knowledge service unavailable". It never invents a reply.
- The timeout was added after one Sonnet case (ts-05) ran for about 19 minutes.

**Review screen (Next.js)**
- Shows the original email, category, risk, evidence with links, and the draft.
- Buttons: Approve and send, Edit then send, Reject and write replacement, Mark as needs expert. Edit and reject need a written reason.
- "Send" only writes to a simulated outbox. An idempotency key stops duplicate sends on retry.

**Feedback and the 20-approval rule**
- Each decision is stored with the original email, predicted category, sources, draft, edited reply, final reply, model, prompt version, outcome, reason and time. Records are versioned.
- Per category, the app counts consecutive drafts whose final text equals the generated draft (compared as normalised text, not by the Approve click). Any edit, rejection, failed claim check or failed quality check resets the count to 0.
- At 20, the category is only "eligible for a controlled autonomy trial". Refund, legal, account security and serious complaints are never eligible. Autonomy can be turned off and reversed.
- Email addresses and phone numbers are masked in logs.

**Why:** a person stays in control. The 20-approval rule gives evidence before any autonomy, and it compares final text so a lazy click does not count.

## 4. Task 3 — Meeting to Scope

**Job:** turn meeting transcripts into requirements, feasibility, hours and a proposal, and show what changed after the next meeting.

**Five agent modules** (`prompts/<version>/`): transcript analyst, product feasibility, estimation, scope, proposal.
- **Transcript analyst:** extracts requirements with a status (clear, unclear, disputed, out of scope), explicit or inferred labels, acceptance criteria, missing information and open questions. If the client gave no acceptance criterion, it may add one that is marked `PROPOSED (client to confirm)` and only restates what the client said.
- **Feasibility:** asks the Knowledge Brain (answers are cached) and classifies each requirement: existing configuration, existing feature with a limit, potential custom development, or needs clarification. Strong evidence is needed for anything except "needs clarification". Output text that claims a feature is absent is rewritten.
- **Estimation:** low, likely and high hours for each requirement. Disputed or out-of-scope items get no hours and are marked blocked. The hourly rate is empty on purpose, so the app gives hours, not a price.
- **Scope and proposal:** what is included, excluded and assumed.

**Data:** SQLite stores runs, transcripts, sections, agent outputs, requirements, decisions, open questions, feasibility, scopes, estimates, proposals and document versions.

**Versions and change report**
- The first scope is approved as a baseline. Later meetings create new draft versions.
- The change report compares a draft with the approved baseline, not with an earlier AI draft. It lists Added, Removed, Modified and Unresolved items. For Meeting C: Added REQ-011, Removed REQ-008, Modified the delivery-date expectation (shown as the client's expectation, not our promise), and REQ-002 unresolved.
- An unapproved version cannot be sent. Sending is blocked until a reviewer approves.

**Prompt versions:** `PROMPT_VERSION` in the Task 3 `.env` picks `prompts/v1` or `prompts/v2` (default v1). Old prompts are kept, so a change can be rolled back.

## 5. Models, cost and speed

- Default model: `claude-haiku-5-5`. `claude-sonnet-5-5` was used for comparison. Model names come from configuration.
- Cost is calculated from real token counts. Haiku was far cheaper than Sonnet and as good or better on these cases, so Haiku is the default. Numbers are in `EVALS.md`.
- Keys stay in local `.env` files. They are not committed and not printed.

## 6. Failure handling

| Failure | What the system does |
|---|---|
| Knowledge Brain down or slow | 30-second timeout, one retry, then a visible failure state. No made-up reply. |
| Weak evidence | "Not enough evidence", escalation or "needs clarification" |
| Low API credit (402) | Clear error, no crash |
| Prompt injection in email, transcript or article | Ignored. Tested in all three tasks. |
| Model output is invalid | zod or JSON check fails, and the case is recorded as failed |
| Duplicate send | Idempotency key blocks it |

## 7. What is real and what is simulated

- Real: the crawl and indexing, search, Claude calls, review screen, change report, and all evaluation runs.
- Simulated: sending (Task 2 outbox, Task 3 "Simulate send"). Nothing leaves this machine.
- Seeded by script: the 20 approvals in the Task 2 demo and the first baseline approval in Task 3.
- Role-played: the three meeting transcripts.

## 8. Known limits and next steps

- Only 19 articles are indexed, so many feasibility answers are "needs clarification".
- The Task 1 threshold was tuned on its own test cases, so its score is probably too good.
- Task 3 expected answers were written with an AI assistant, not an independent reviewer.
- Estimates vary from run to run (Meeting A gave 64, 48 and 36 hours in three runs). Treat them as a rough guide.
- Results are noisy. 20 to 32 cases per task show direction, not proof.
- Next: an independent test set, more articles, repeated runs to measure noise, and real email sending only after the 20-approval rule has been met with real data.
