"""Scraper for NSE's public (unofficial) IPO endpoints.

NSE blocks naive requests (Akamai). Workaround: warm up a session by visiting
the public IPO page first to obtain cookies, then reuse that session for the
JSON API calls with an appropriate Referer header.
"""
from datetime import datetime, timedelta

import requests

from common import USER_AGENT, request_with_retry, strip_html

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
    to_date = datetime.utcnow()
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


def fetch_all(months_back: int = 3) -> dict:
    """Returns {"ok": bool, "error": str|None, "current": [...], "upcoming": [...], "past": [...]}"""
    try:
        session = get_session()
        current = fetch_current_issues(session)
        upcoming = fetch_upcoming_issues(session)
        past = fetch_past_issues(session, months_back=months_back) if months_back > 0 else []
        return {"ok": True, "error": None, "current": current, "upcoming": upcoming, "past": past}
    except Exception as exc:  # noqa: BLE001 - want to record any failure, not crash the whole run
        return {"ok": False, "error": str(exc), "current": [], "upcoming": [], "past": []}


if __name__ == "__main__":
    import json

    result = fetch_all()
    print(json.dumps(result, indent=2)[:2000])
    print(f"\ncurrent={len(result['current'])} upcoming={len(result['upcoming'])} past={len(result['past'])}")
