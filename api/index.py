"""FastAPI application used locally and by Vercel's Python runtime."""

from __future__ import annotations

import copy
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse

from scraper import merge

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "ipos.json"
CACHE_TTL_SECONDS = 15 * 60

app = FastAPI(
    title="IPO market API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

_cache_lock = threading.Lock()
_cache_payload: dict | None = None
_cache_time = 0.0


def _number(value) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?[\d,.]+", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _overview(payload: dict) -> dict:
    ipos = payload.get("ipos", [])
    quoted = [
        ipo
        for ipo in ipos
        if (ipo.get("gmp") or {}).get("value") is not None
        and (ipo.get("gmp") or {}).get("percent") is not None
    ]
    capital = sum(_number(ipo.get("issueSize")) or 0 for ipo in ipos)
    return {
        "totalIssues": len(ipos),
        "openIssues": sum(ipo.get("status") == "open" for ipo in ipos),
        "upcomingIssues": sum(ipo.get("status") == "upcoming" for ipo in ipos),
        "quotedIssues": len(quoted),
        "averageGmpPercent": round(
            sum(ipo["gmp"]["percent"] for ipo in quoted) / len(quoted), 2
        )
        if quoted
        else None,
        "disclosedCapitalCrore": round(capital, 2),
        "earlyGmpIssues": len(payload.get("earlyGmp", [])),
    }


def _load_snapshot() -> dict:
    with SNAPSHOT.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if "earlyGmp" not in payload:
        payload["earlyGmp"] = [
            {"companyName": name} for name in payload.pop("unmatchedGmpNames", [])
        ]
    return payload


def _with_meta(payload: dict, delivery: str) -> dict:
    result = copy.deepcopy(payload)
    result["overview"] = _overview(result)
    result["meta"] = {
        "delivery": delivery,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
        "servedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return result


def get_market(force: bool = False) -> dict:
    """Return cached live data, refreshing all providers when necessary."""
    global _cache_payload, _cache_time

    now = time.monotonic()
    if not force and _cache_payload and now - _cache_time < CACHE_TTL_SECONDS:
        return _with_meta(_cache_payload, "cache")

    with _cache_lock:
        now = time.monotonic()
        if not force and _cache_payload and now - _cache_time < CACHE_TTL_SECONDS:
            return _with_meta(_cache_payload, "cache")
        try:
            live = merge.collect()
            if not live.get("ipos") and not any(
                source.get("ok") for source in live.get("sources", {}).values()
            ):
                raise RuntimeError("all live providers failed")
            _cache_payload = live
            _cache_time = time.monotonic()
            return _with_meta(live, "live")
        except Exception:  # noqa: BLE001 - snapshot is the availability boundary
            snapshot = _load_snapshot()
            _cache_payload = snapshot
            _cache_time = time.monotonic()
            return _with_meta(snapshot, "snapshot")


@app.get("/api/market")
def market(
    response: Response,
    refresh: bool = Query(False, description="Bypass the 15-minute process cache"),
):
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return get_market(force=refresh)


@app.post("/api/refresh")
def refresh_market(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return get_market(force=True)


@app.get("/api/ipos/{company_key}")
def ipo_detail(company_key: str):
    key = re.sub(r"[^a-z0-9]", "", company_key.lower())
    for ipo in get_market().get("ipos", []):
        candidate = re.sub(r"[^a-z0-9]", "", ipo.get("companyName", "").lower())
        if candidate == key:
            return ipo
    raise HTTPException(status_code=404, detail="IPO not found")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "ipo-market-api"}


# These routes make one-command local development possible. Vercel serves the
# same files at the edge and sends only /api/* to this function.
@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js", include_in_schema=False)
def frontend_js():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")


@app.get("/styles.css", include_in_schema=False)
def frontend_css():
    return FileResponse(ROOT / "styles.css", media_type="text/css")
