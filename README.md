# IPO market data

A full-stack Indian IPO dashboard. FastAPI collects official issue and
subscription data from NSE/BSE plus informal GMP data from InvestorGain, Neon
stores the last successful refresh, and the browser presents search, comparison,
details, saved issues, and CSV export.

## How it works

```text
NSE issues + bid details ─┐
BSE public issues ────────┼─ normalize ─ FastAPI ─ Neon ─ browser UI
InvestorGain GMP ─────────┘                 │
                              refresh lease + 15-minute freshness window
```

- `GET /api/market` serves the current Neon dataset. If it is older than 15
  minutes, the request refreshes it first.
- `POST /api/refresh` requests a manual refresh. A database lease and five-minute
  manual cooldown prevent duplicate scraping across Vercel instances.
- A failed provider refresh never replaces the last successful dataset.
- The browser reloads data every 15 minutes while open and also offers a manual
  refresh button. This does not require a GitHub Action or background worker.
- Closed NSE IPOs from the last 12 months are retained alongside open and
  upcoming issues.

NSE subscription data has two distinct views. The headline number uses
**Consolidated Bid Details**, while each issue dialog shows both **NSE Bid
Details** and **Consolidated Bid Details**, split by investor category.

## Project layout

- `api/index.py` — HTTP routes and static-file delivery
- `api/service.py` — refresh policy, stale fallback, and market summaries
- `api/database.py` — Neon schema, versioned records, and refresh lease
- `api/models.py` — validated response models
- `scraper/` — paced provider clients and normalization/merge logic
- `index.html`, `app.js`, `styles.css` — browser application
- `tests/` — API, service, and normalization tests

## Local development

Copy `.env.example` to `.env` and set your Neon connection string:

```dotenv
DATABASE_URL=postgresql://user:password@host/database?sslmode=require
```

Then use `uv` for all Python work:

```bash
uv sync
uv run uvicorn api.index:app --reload
```

Open <http://127.0.0.1:8000>. The schema is created automatically on the first
API request. Run checks with:

```bash
uv run pytest
node --check app.js
```

## API

- `GET /api/market` — all open, upcoming, and recently closed issues
- `POST /api/refresh` — manual provider refresh
- `GET /api/ipos/{issue-key}` — one normalized issue
- `GET /api/health` — service liveness
- `GET /api/docs` — interactive OpenAPI documentation

## Vercel deployment

Import the repository into Vercel and add `DATABASE_URL` to the project’s
environment variables. The included `vercel.json` configures the FastAPI
function. No scheduled GitHub workflow or committed data snapshot is used.

NSE/BSE endpoints are public but unofficial and may change. GMP is unregulated
market sentiment and is not investment advice.
