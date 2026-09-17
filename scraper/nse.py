"""Scraper for NSE's public (unofficial) IPO endpoints.

NSE blocks naive requests (Akamai). Workaround: warm up a session by visiting
the public IPO page first to obtain cookies, then reuse that session for the
JSON API calls with an appropriate Referer header.
"""

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


def fetch_all(months_back: int = 12) -> dict:
    """Fetch issues plus official NSE and consolidated demand details."""
    try:
        session = get_session()
        current = fetch_current_issues(session)
        upcoming = fetch_upcoming_issues(session)
        past = (
            fetch_past_issues(session, months_back=months_back)
            if months_back > 0
            else []
        )
        subscriptions = {}
        subscription_errors = []
        for row in current:
            symbol = row.get("symbol")
            series = row.get("series") or "EQ"
            if not symbol:
                continue
            try:
                subscriptions[symbol] = {
                    "nse": fetch_bid_details(session, symbol, series),
                    "consolidated": fetch_consolidated_bid_details(session, symbol),
                }
            except (requests.RequestException, ValueError) as exc:
                subscription_errors.append(f"{symbol}: {exc}")
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


if __name__ == "__main__":
    import json

    result = fetch_all()
    print(json.dumps(result, indent=2)[:2000])
    print(
        f"\ncurrent={len(result['current'])} upcoming={len(result['upcoming'])} past={len(result['past'])}"
    )
