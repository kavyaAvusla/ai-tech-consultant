# Task 1 — Knowledge Brain

Local crawl + parse + embeddings for Brilliant Directories support articles, with a small FastAPI service. Claude is used for answers (and optional screenshot captions). Embeddings are local (`fastembed`); nothing except Claude needs a cloud API key.

Do not commit `.env`. Never print `ANTHROPIC_API_KEY`.

## Setup (Windows, Python 3.12)

From `task1-knowledge-brain`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Put secrets in the repo-root `.env` (already gitignored):

```
ANTHROPIC_API_KEY=...
MODEL_NAME=claude-haiku-5-5
APP_API_KEY=choose-a-long-random-string
CRAWL_LIMIT=20
```

## Crawl / daily update

Resumable. Prints `added/updated/removed/failed` plus `vision_described` (successful captions only) and index counts.

```powershell
.\.venv\Scripts\python.exe -m app --limit 20
```

Index only (no extra crawl):

```powershell
.\.venv\Scripts\python.exe -m app --index-only
```

SQLite manifest: `data/brain.sqlite`. Chroma: `data/chroma/`.

## API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Docs: http://127.0.0.1:8000/docs  
Health (no key): `GET /health`

All other routes need header `X-API-Key: <APP_API_KEY from .env>`.

```powershell
$headers = @{ "X-API-Key" = $env:APP_API_KEY; "Content-Type" = "application/json" }

Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ingestion/status -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/ingestion/run -Method POST -Headers $headers -Body '{"limit":20}'
Invoke-RestMethod http://127.0.0.1:8000/query -Method POST -Headers $headers -Body '{"question":"How do I upload a social media image?"}'
Invoke-RestMethod http://127.0.0.1:8000/escalations -Method POST -Headers $headers -Body '{"question":"Does BD support quantum faxing?","reason":"manual"}'
Invoke-RestMethod http://127.0.0.1:8000/escalations/1/resolve -Method POST -Headers $headers -Body '{"note":"Not a product feature."}'
```

If Anthropic credits are empty, `/query` returns **402** with `code: billing` instead of crashing. Weak retrieval returns `"not enough evidence"` and creates an escalation.

Resolved escalations are stored as versioned `knowledge_records` and appended to `eval_cases`.
