# IPO market data

A Vercel-ready web application for live Indian IPO monitoring. A FastAPI
backend collects NSE, BSE, and InvestorGain data; the frontend uses the API
exclusively and provides issue tracking, comparisons, saved issues, CSV export,
early-GMP coverage, and provider diagnostics.

## Architecture

```text
NSE current/upcoming ─┐
BSE public issues ────┼─ concurrent collection ─ normalization ─ FastAPI ─ UI
InvestorGain GMP ─────┘                              │
                                      last-known-good JSON fallback
```

`GET /api/market` refreshes all providers on a cold process, then caches the
result for 15 minutes. `POST /api/refresh` forces a live collection. If every
provider fails, the API serves `data/ipos.json` as a last-known-good response;
the browser never reads that file directly.

The response includes every normalized official issue field, complete unmatched
GMP records, source health and record counts, computed market totals, and
delivery metadata. API documentation is available at `/api/docs`.

## Features

- Open/upcoming issue totals, current event schedule, capital and GMP metrics
- Search, status/platform filters, column sorting, and local saved issues
- Two- or three-company comparison with price, dates, GMP, and subscription data
- Complete record drawer including face value, exchanges, minimum bid, estimated
  listing price, timestamps, and source link
- CSV export of the current filtered issue set
- Full early-GMP table for records that do not yet match NSE/BSE
- Live provider health, row counts, cache mode, and response timestamps

## Local development

Use `uv` for all Python work:

```bash
uv sync
uv run uvicorn api.index:app --reload
```

Open <http://127.0.0.1:8000>. Run the suite with:

```bash
uv run pytest
```

Refresh the committed fallback snapshot:

```bash
uv run python -m scraper.merge --out data/ipos.json
```

## API

- `GET /api/market` — complete market payload; live on cold start, then cached
- `GET /api/market?refresh=true` — bypass the process cache
- `POST /api/refresh` — force collection from all three providers
- `GET /api/ipos/{normalized-company-name}` — one normalized issue record
- `GET /api/health` — service liveness
- `GET /api/docs` — interactive OpenAPI documentation

## Vercel deployment

Import the repository into Vercel and deploy. `vercel.json` routes `/api/*` to
the FastAPI function, gives live collection up to 60 seconds, and leaves the
HTML/CSS/JS as edge-served static assets. There are no required environment
variables or external databases.

Vercel function memory is reusable but not durable, so the 15-minute cache is
best-effort per warm instance. The committed snapshot provides cold-start outage
fallback, while the included GitHub Action refreshes it every two hours.

NSE/BSE endpoints are public but unofficial and may change. GMP is unregulated
market sentiment and should not be treated as investment advice.
