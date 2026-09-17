"""Scraper for NSE's public (unofficial) IPO endpoints.

NSE blocks naive requests (Akamai). Workaround: warm up a session by visiting
the public IPO page first to obtain cookies, then reuse that session for the
JSON API calls with an appropriate Referer header.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import requests

from .common import USER_AGENT, request_with_retry

BASE = "https://www.nseindia.com"
WARMUP_PATH = "/market-data/all-upcoming-issues-ipo"


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    request_with_retry(
        session,
        "GET",
        BASE + WARMUP_PATH,
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    return session


def _api_headers() -> dict:
    return {
        "Accept": "application/json",
        "Referer": BASE + WARMUP_PATH,
    }


def fetch_current_issues(session: requests.Session) -> list:
    resp = request_with_retry(
        session, "GET", f"{BASE}/api/ipo-current-issue", headers=_api_headers()
    )
    return resp.json()


def fetch_upcoming_issues(session: requests.Session) -> list:
    resp = request_with_retry(
        session,
        "GET",
        f"{BASE}/api/all-upcoming-issues",
        params={"category": "ipo"},
        headers=_api_headers(),
    )
    return resp.json()


def fetch_past_issues(session: requests.Session, months_back: int = 3) -> list:
    to_date = datetime.now(UTC)
    from_date = to_date - timedelta(days=months_back * 30)
    resp = request_with_retry(
        session,
        "GET",
        f"{BASE}/api/public-past-issues",
        params={
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y"),
        },
        headers=_api_headers(),
    )
    return resp.json()


def fetch_bid_details(session: requests.Session, symbol: str, series: str) -> dict:
    """Fetch NSE-only demand for one currently open issue."""
    resp = request_with_retry(
        session,
        "GET",
        f"{BASE}/api/ipo-bid-details",
        params={"symbol": symbol, "series": series},
        headers={
            **_api_headers(),
            "Referer": f"{BASE}/market-data/issue-information?symbol={symbol}&series={series}",
        },
        timeout=12,
        max_retries=2,
    )
    return resp.json()


def fetch_consolidated_bid_details(session: requests.Session, symbol: str) -> dict:
    """Fetch exchange-consolidated category demand for one open issue."""
    resp = request_with_retry(
        session,
        "GET",
        f"{BASE}/api/ipo-active-category",
        params={"symbol": symbol},
        headers={
            **_api_headers(),
            "Referer": f"{BASE}/market-data/issue-information?symbol={symbol}",
        },
        timeout=12,
        max_retries=2,
    )
    return resp.json()


def _unique_current_issues(rows: list) -> list:
    """Keep one request target per symbol even if NSE returns duplicate rows."""
    unique = {}
    for row in rows:
        symbol = row.get("symbol")
        if symbol and symbol not in unique:
            unique[symbol] = row
    return list(unique.values())


def _fetch_subscription_batch(
    rows: list, session: requests.Session | None = None
) -> tuple[dict, list[str]]:
    """Fetch a batch serially, preserving the courtesy gap on one NSE session."""
    owns_session = session is None
    session = session or get_session()
    subscriptions = {}
    errors = []
    try:
        for row in rows:
            symbol = row["symbol"]
            series = row.get("series") or "EQ"
            result = {}
            try:
                result["nse"] = fetch_bid_details(session, symbol, series)
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{symbol} NSE bids: {exc}")
            try:
                result["consolidated"] = fetch_consolidated_bid_details(session, symbol)
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{symbol} consolidated bids: {exc}")
            if result:
                subscriptions[symbol] = result
    finally:
        if owns_session:
            session.close()
    return subscriptions, errors


def fetch_all(months_back: int = 12) -> dict:
    """Fetch issues plus official NSE and consolidated demand details."""
    session = None
    try:
        session = get_session()
        current = fetch_current_issues(session)
        targets = _unique_current_issues(current)

        # Two serial lanes halve the long per-symbol queue while retaining the
        # normal request gap and avoiding an unbounded burst against NSE.
        with ThreadPoolExecutor(max_workers=2) as pool:
            remote_details = (
                pool.submit(_fetch_subscription_batch, targets[1::2])
                if len(targets) > 1
                else None
            )
            upcoming = fetch_upcoming_issues(session)
            past = (
                fetch_past_issues(session, months_back=months_back)
                if months_back > 0
                else []
            )
            subscriptions, subscription_errors = _fetch_subscription_batch(
                targets[::2], session
            )
            if remote_details:
                remote_subscriptions, remote_errors = remote_details.result()
                subscriptions.update(remote_subscriptions)
                subscription_errors.extend(remote_errors)
        return {
            "ok": True,
            "error": None,
            "current": current,
            "upcoming": upcoming,
            "past": past,
            "subscriptions": subscriptions,
            "subscriptionErrors": subscription_errors,
        }
    except Exception as exc:  # noqa: BLE001 - want to record any failure, not crash the whole run
        return {
            "ok": False,
            "error": str(exc),
            "current": [],
            "upcoming": [],
            "past": [],
            "subscriptions": {},
            "subscriptionErrors": [],
        }
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    import json

    result = fetch_all()
    print(json.dumps(result, indent=2)[:2000])
    print(
        f"\ncurrent={len(result['current'])} upcoming={len(result['upcoming'])} past={len(result['past'])}"
    )
