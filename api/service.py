"""Market refresh orchestration independent of the HTTP layer."""

from __future__ import annotations

import copy
import logging
import re
from datetime import UTC, datetime

from scraper import merge

from .database import MarketRepository, StoredMarket

LOGGER = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 15 * 60


class MarketUnavailable(RuntimeError):
    pass


class MarketService:
    def __init__(self, repository: MarketRepository):
        self.repository = repository

    def get_market(self, force: bool = False) -> dict:
        trigger = "manual" if force else "stale"
        stored = None if force else self.repository.load_current()
        if stored and not _is_stale(stored):
            return _with_meta(stored.payload, "database")

        refresh_id = self.repository.start_refresh(trigger)
        if refresh_id is None:
            if stored is None:
                stored = self.repository.load_current()
            if stored:
                delivery = "stale" if _is_stale(stored) else "database"
                return _with_meta(stored.payload, delivery, refresh_in_progress=True)
            raise MarketUnavailable("Market data is being initialized; retry shortly")

        try:
            live = merge.collect()
            official_ok = any(
                live.get("sources", {}).get(name, {}).get("ok")
                for name in ("nse", "bse")
            )
            if not live.get("ipos") and not official_ok:
                raise RuntimeError("all official market providers failed")
            self.repository.save_success(refresh_id, live)
            return _with_meta(live, "live")
        except Exception as exc:
            LOGGER.exception("Market refresh failed")
            try:
                self.repository.save_failure(refresh_id, str(exc))
            except Exception:
                LOGGER.exception("Could not persist refresh failure")
            if stored is None:
                stored = self.repository.load_current()
            if stored:
                return _with_meta(stored.payload, "stale")
            raise MarketUnavailable("No market data is currently available") from exc


def overview(payload: dict) -> dict:
    ipos = payload.get("ipos", [])
    active = [ipo for ipo in ipos if ipo.get("status") != "closed"]
    quoted = [
        ipo
        for ipo in active
        if (ipo.get("gmp") or {}).get("value") is not None
        and (ipo.get("gmp") or {}).get("percent") is not None
    ]
    capital = sum(_number(ipo.get("issueSize")) or 0 for ipo in active)
    return {
        "totalIssues": len(ipos),
        "openIssues": sum(ipo.get("status") == "open" for ipo in ipos),
        "upcomingIssues": sum(ipo.get("status") == "upcoming" for ipo in ipos),
        "closedIssues": sum(ipo.get("status") == "closed" for ipo in ipos),
        "quotedIssues": len(quoted),
        "averageGmpPercent": round(
            sum(ipo["gmp"]["percent"] for ipo in quoted) / len(quoted), 2
        )
        if quoted
        else None,
        "disclosedCapitalCrore": round(capital, 2),
        "earlyGmpIssues": len(payload.get("earlyGmp", [])),
    }


def _number(value) -> float | None:
    if value is None:
        return None
    text = str(value)
    if not re.search(r"\bcr(?:ore)?\b", text, flags=re.IGNORECASE):
        return None
    match = re.search(r"-?[\d,.]+", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _is_stale(stored: StoredMarket) -> bool:
    completed = stored.completed_at
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - completed).total_seconds() >= CACHE_TTL_SECONDS


def _with_meta(payload: dict, delivery: str, refresh_in_progress: bool = False) -> dict:
    result = copy.deepcopy(payload)
    result["overview"] = overview(result)
    result["meta"] = {
        "delivery": delivery,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
        "servedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "refreshInProgress": refresh_in_progress,
    }
    return result
