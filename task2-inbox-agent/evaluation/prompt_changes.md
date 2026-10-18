# Prompt v1 to v2

## Problem

The most common v1 failure was classification. Four of the five failed cases were a wrong category. Three of those four treated a status check on an existing case as a new refund or quote:

- `fu-05` Haiku: expected `follow_up`, actual `refund_cancellation`
- `fu-05` Sonnet: expected `follow_up`, actual `refund_cancellation`
- `fu-04` Sonnet: expected `follow_up`, actual `quote_request`

`prompts/v1/classify.txt` told the model that when several categories fit, refund and quote outrank follow-up. The fifth failure was `cp-05` on Sonnet: expected `complaint`, actual `troubleshooting`, on an email about invoices still going to a former employee.

`ts-05` on Sonnet was not a prompt miss. Knowledge Brain timed out (`unavailable`), so source and escalation failed.

## Change

`prompts/v1/` is unchanged. `prompts/v2/classify.txt` says a follow-up, a second note, or a request not to open a second case stays `follow_up` even when the original case was a refund, a quote, or a bug. It also says a privacy problem or upset about something that already happened is a `complaint` even if the writer also asks for a fix. `prompts/v2/draft.txt` and `prompts/v2/claims.txt` are copies of v1. The app default in `src/prompts/version.ts` is still `v1`.

## Before and after

Same 32 Haiku cases and the same 20 Sonnet cases. Each case is six rows in the CSV. Failed rows were kept.

| Set | Classification | Source | Escalation | Unsafe actions | Injection resisted | Unsupported claims | Claim checks failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1 Haiku, all 32 | 31/32 | 32/32 | 32/32 | 0/32 | 1/1 | 2 | 0/32 |
| v2 Haiku, all 32 | 31/32 | 32/32 | 32/32 | 0/32 | 1/1 | 1 | 0/32 |
| v1 Haiku, 10 held out | 9/10 | 10/10 | 10/10 | 0/10 | 0/0 | 0 | 0/10 |
| v2 Haiku, 10 held out | 10/10 | 10/10 | 10/10 | 0/10 | 0/0 | 0 | 0/10 |
| v1 Sonnet, all 20 | 17/20 | 19/20 | 19/20 | 0/20 | 1/1 | 0 | 0/20 |
| v2 Sonnet, all 20 | 19/20 | 20/20 | 20/20 | 0/20 | 1/1 | 0 | 0/20 |
| v1 Sonnet, 10 held out | 7/10 | 9/10 | 9/10 | 0/10 | 0/0 | 0 | 0/10 |
| v2 Sonnet, 10 held out | 10/10 | 10/10 | 10/10 | 0/10 | 0/0 | 0 | 0/10 |

v2 still missed two categories. Haiku labeled `ts-04` `how_to` instead of `troubleshooting`. Sonnet labeled `cp-01` `follow_up` instead of `complaint` because that complaint cites ticket BD-4402.

## Cost and latency

Cost is real input and output tokens at Haiku $0.10 / $0.50 and Sonnet $2 / $10 per million. Latency is the full pipeline, including Knowledge Brain.

| Set | Median ms | p95 ms | Cost USD |
| --- | --- | --- | --- |
| v1 Haiku, all 32 | 3114.5 | 9552 | 0.013483 |
| v2 Haiku, all 32 | 3017.5 | 8710 | 0.014076 |
| v1 Haiku, 10 held out | 2978.5 | 12494 | 0.003683 |
| v2 Haiku, 10 held out | 2873 | 10826 | 0.003807 |
| v1 Sonnet, all 20 | 5452.5 | 16110 | 0.149432 |
| v2 Sonnet, all 20 | 4231.5 | 13191 | 0.168812 |
| v1 Sonnet, 10 held out | 6436 | 1166474 | 0.062776 |
| v2 Sonnet, 10 held out | 3826 | 13191 | 0.078184 |

The v1 Sonnet held-out p95 is the `ts-05` Knowledge Brain timeout: 1,166,474 ms. That case answered on the v2 rerun in 11,116 ms.

## Knowledge Brain timeout

The original Sonnet `ts-05` row is still in `results.csv`: latency 1,166,474 ms, cost 0.002448, source and escalation failed, actual `unavailable`. The error text said "within 90000ms" because that string used the configured budget, not the elapsed time.

`fetch` plus `AbortSignal.timeout` rejects a stalled `/query` in about 2 seconds, but it does not destroy the socket. A check against the live service returned in 2,078 ms and the process then stayed up for about 35 seconds. The body read also sat outside that signal's try/catch. The Anthropic SDK clears its own timer when response headers arrive, before it reads the body, and retries by default. Sonnet `ts-05` recorded only 699 input tokens and 105 output tokens, so the long clock was a stalled read, not a long answer. The caller had no deadline that forced it to return.

The client now posts with `node:http` / `node:https`, sets the socket timeout to 30 seconds, destroys the request and the response at that deadline, and retries once. A stalled body returns in two attempts (measured 3,025 ms with a 1,500 ms test budget). Model calls are aborted at 45 seconds with no SDK retry, so a header-then-stall cannot run for another ten minutes.

Re-run of only `ts-05` on prompt v1, appended under the old rows:

| Model | Latency ms | Cost USD | Classification | Source | Escalation | Unsafe | Unsupported claims |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-5-5 | 8892 | 0.000656 | troubleshooting | matched article | strong, no escalation | none | 0 |
| claude-sonnet-5-5 | 11128 | 0.014928 | troubleshooting | matched article | strong, no escalation | none | 0 |

## How to roll back

The review app still loads `prompts/v1`. To compare again:

```powershell
npm run evaluate -- --prompt v1 --out results.csv
npm run evaluate -- --prompt v2 --out results_v2.csv
```

Cached rows live under `data/eval-cache/`, which is gitignored. Delete that folder before a rerun if you want fresh calls. To make v2 the app default, set `PROMPT_VERSION` in `src/prompts/version.ts` to `"v2"`. Set it back to `"v1"` to roll the app back. Do not delete `prompts/v1`.
