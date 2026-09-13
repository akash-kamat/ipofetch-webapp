# ipo-data-pipeline

Scrapes Indian IPO data (Mainboard + SME) from NSE and BSE's unofficial public
endpoints, merges it with Grey Market Premium (GMP) data scraped from
InvestorGain, and writes a single combined JSON feed at `data/ipos.json`.

None of NSE, BSE, or InvestorGain publish an official developer API. Every
endpoint used here was found by inspecting network requests made by their own
websites, and can change or start blocking requests without notice.

## Layout

```
scraper/
  common.py   # shared HTTP session/retry helpers, name normalization
  nse.py      # NSE current / upcoming / past issue endpoints
  bse.py      # BSE public issue list endpoint
  gmp.py      # InvestorGain live GMP JSON endpoint
  merge.py    # runs all three scrapers, joins by company name, writes data/ipos.json
data/
  ipos.json   # generated output (committed by the GitHub Action)
.github/workflows/scrape.yml  # scheduled scrape + commit
```

## Running locally

```
pip install -r requirements.txt
cd scraper
python merge.py --out ../data/ipos.json
```

Each scraper can also be run standalone for debugging (`python nse.py`,
`python bse.py`, `python gmp.py`) — each prints its own JSON to stdout.

## Data sources & how they're fetched

| Source | Endpoint | Notes |
|---|---|---|
| NSE | `nseindia.com/api/ipo-current-issue`, `/api/all-upcoming-issues?category=ipo`, `/api/public-past-issues` | Requires a "cookie warm-up": fetch the public IPO page first to get session cookies (Akamai blocks cold API requests), then reuse the session with a matching `Referer` header. |
| BSE | `api.bseindia.com/BseIndiaAPI/api/GetPublicIssue_par_updated/w?flag=1&status=&exchange=&ir_flag=IPO` | No cookies needed, just a `Referer: https://www.bseindia.com/` header. Returns a fairly narrow near-term window (live/recent forthcoming issues), not full history. |
| GMP | `webnodejs.investorgain.com/cloud/v2/report/data-read/331/{page}/{month}/{year}/{fy}/0/all` | This is the JSON API InvestorGain's own frontend calls — found by intercepting network requests, since the public GMP page (`investorgain.com/report/live-ipo-gmp/331/ipo/`) renders its table client-side and is empty in the raw HTML. `Name` and `GMP` fields come back as HTML fragments and are parsed with regex in `gmp.py`. |

## Output schema (`data/ipos.json`)

Only **open** or **upcoming** IPOs are included — no past/listed IPOs, and no
raw per-source data. Each record has exactly these fields:

```json
{
  "generatedAt": "2026-09-13T05:53:53Z",
  "ipos": [
    {
      "companyName": "Raksan Transformers Limited",
      "platform": "SME",
      "status": "open",
      "openDate": "2026-09-10",
      "closeDate": "2026-09-15",
      "listingDate": "2026-09-18",
      "priceBand": { "min": 258.0, "max": 273.0 },
      "lotSize": "400",
      "faceValue": 10.0,
      "issueSize": "₹150.50 Cr",
      "gmp": { "value": 30.0, "percent": 10.99 },
      "subscriptionTimes": "1.31x"
    }
  ]
}
```

`gmp` and `subscriptionTimes` are `null` when InvestorGain hasn't quoted a
GMP for that IPO yet — not a scrape failure.

## Known limitations / caveats

- **Not all GMP-tracked IPOs match an official record.** InvestorGain tracks
  IPOs earlier (from draft filings/rumor) than NSE/BSE publish official
  forthcoming-issue data for. In a typical run, ~15-20 GMP rows won't have a
  matching BSE/NSE entry yet — this is expected, not a matching bug. These are
  listed in `unmatchedGmpNames` rather than silently dropped.
- **GMP is inherently unofficial, self-reported data** from grey-market
  chatter, published by InvestorGain "for informational purposes only" — treat
  it as a rough sentiment indicator, not a reliable number.
- **NSE occasionally blocks datacenter IPs**, including GitHub Actions
  runners, even with a correct cookie warm-up. If the scheduled workflow
  starts failing with 401/403 from NSE specifically, that's the likely cause —
  BSE and GMP scraping are unaffected since they don't depend on NSE's
  session/IP reputation.
- **All three endpoints are undocumented and reverse-engineered** from what
  each site's own frontend calls. They can change field names, move, or
  start requiring new headers/auth at any time with no notice. `merge.py`
  records `ok`/`error` per source in the output so a broken source degrades
  gracefully instead of failing the whole run (if one source errors, the
  other two still get merged and written).
- Be a good citizen: the request gap (`REQUEST_GAP_SECONDS` in `common.py`)
  and the workflow's twice-daily schedule are intentionally conservative.
  Don't lower them without a reason — these are public sites, not APIs meant
  for high-frequency polling.

## Consuming this feed from your site

Once pushed to GitHub with the Action enabled, the JSON is fetchable directly
(no build step) from either:

- `https://raw.githubusercontent.com/<you>/ipo-data-pipeline/main/data/ipos.json`
- or via GitHub Pages if enabled: `https://<you>.github.io/ipo-data-pipeline/data/ipos.json`

Both serve with permissive CORS, so your website's frontend can `fetch()` it
directly.
