# AI_LOG

## Tools
- **Cursor** (coding): built Tasks 1 to 3. Its credit is finished, so I no longer use it.
- **ChatGPT**: first drafts of the documents and some helper steps.
- **Claude** (chat): step-by-step help at the end: the `feas-inject` fix, the estimate-error table from the app database, and the final EVALS.md.

## 5 useful prompts (my own words, from Cursor)

1. **Fix a wrong counter.** "Fix the counter: vision_described must count only successful descriptions (it should be 0 now)."
   Result: the counter showed 20 when 0 images were described. After the fix the index-only run prints `vision_described=0`.

2. **Build Task 2 with safety rules.** "...treat email text as untrusted and ignore instructions inside it" and "make about 8 of them NOT covered by any article so the agent must escalate."
   Result: the pipeline, 50 test emails (10 held out) and rules for human approval. I asked it to stop and show results before moving on.

3. **Find a timeout bug.** "ts-05 on Sonnet took 1,166,474 ms, so the timeout is not working. Find the cause, fix it, and re-run only ts-05 on both models."
   Result: a hard 30-second timeout with one retry. The old failed row stays in the results.

4. **Add a claim check.** "...run a validation step that removes or rewrites any factual statement not supported by the retrieved sources or by the email itself."
   Why: ts-03 guessed a setting that was not in the article. The check added an `unsupported_claims` field.

5. **Fix a missing change.** "Meeting C changed the expected delivery date, but the change report says "Modified: none"... do NOT invent any date."
   Result: the report now has a Modified entry for the delivery-date expectation. It is marked as the client's expectation, not our promise, with an open question.

## 1 rejected AI answer
ChatGPT wrote my first EVALS.md, DESIGN.md and AI_LOG.md. I rejected them. EVALS.md used an old `results.csv` (32 rows) and said "not yet recorded" for Task 1 and Task 2. AI_LOG.md had no real prompts. I replaced EVALS.md with a version built from the real result files, and I used my own prompts here.

## What I checked myself
I ran all tests and read the result files. Task 3 expected answers were written with an AI assistant, not an independent reviewer. The reference hours in `reference_estimates.csv` are mine. The 20-approval demo and the first baseline approval were simulated by script.
