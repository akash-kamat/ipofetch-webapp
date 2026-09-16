"""Scraper for BSE's public (unofficial) IPO list endpoint.

Unlike NSE, BSE's API does not require a cookie handshake -- it only checks
the Referer header. flag=1 returns live/recent/forthcoming issues (both
MainBoard and SME platforms).
"""
import requests

from .common import USER_AGENT, request_with_retry

BASE = "https://api.bseindia.com/BseIndiaAPI/api"


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": "https://www.bseindia.com/",
        }
    )
    return session


def fetch_public_issues(session: requests.Session) -> list:
    resp = request_with_retry(
        session,
        "GET",
        f"{BASE}/GetPublicIssue_par_updated/w",
        params={"flag": 1, "status": "", "exchange": "", "ir_flag": "IPO"},
    )
    data = resp.json()
    return data.get("Table", [])


def fetch_all() -> dict:
    """Returns {"ok": bool, "error": str|None, "issues": [...]}"""
    try:
        session = get_session()
        issues = fetch_public_issues(session)
        return {"ok": True, "error": None, "issues": issues}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "issues": []}


if __name__ == "__main__":
    import json

    result = fetch_all()
    print(json.dumps(result, indent=2)[:2000])
    print(f"\nissues={len(result['issues'])}")
