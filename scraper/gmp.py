"""Scraper for InvestorGain's live IPO GMP (Grey Market Premium) data.

GMP is informal, unregulated, self-reported data -- there is no official
source. InvestorGain's public GMP page (investorgain.com/report/live-ipo-gmp/331/ipo/)
is a client-rendered Next.js page: the table is empty in the initial HTML and
is filled in by a browser-side fetch to a separate JSON API. We call that
JSON API directly instead of rendering the page (no browser/Playwright
needed), which is both simpler and much lighter in CI.

Caveats:
- This endpoint is undocumented and can change without notice.
- Several fields (Name, GMP) come back as raw HTML fragments and are parsed
  with string/regex extraction below.
"""
import re
from datetime import datetime

import requests

from common import USER_AGENT, request_with_retry, strip_html

API_BASE = "https://webnodejs.investorgain.com/cloud/v2/report/data-read"
REPORT_ID = 331  # live IPO GMP report
PAGE_URL_REFERER = "https://www.investorgain.com/report/live-ipo-gmp/331/ipo/"

_GMP_VALUE_RE = re.compile(r"₹\s*<b>(.*?)</b>\s*\(([^)]*)\)", re.IGNORECASE)
_NAME_RE = re.compile(r">([^<]+)</a>")
_STATUS_MAP = {"U": "upcoming", "O": "open", "C": "closed"}


def _fiscal_year_str(today: datetime) -> str:
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": PAGE_URL_REFERER,
            "Origin": "https://www.investorgain.com",
        }
    )
    return session


def _parse_gmp_field(raw: str):
    """'&#8377;<b>45</b> (12%)' -> {"value": 45.0, "percent": 12.0}; '--' -> None."""
    text = strip_html(raw)
    match = _GMP_VALUE_RE.search(raw) or re.search(r"₹\s*(\S+)\s*\(([^)]*)\)", text)
    if not match:
        return {"value": None, "percent": None}
    value_raw, percent_raw = match.group(1).strip(), match.group(2).strip()
    value = None if value_raw in ("--", "-", "") else _to_float(value_raw)
    percent = None if "%" not in percent_raw else _to_float(percent_raw.replace("%", ""))
    return {"value": value, "percent": percent}


def _parse_name_field(raw: str) -> str:
    match = _NAME_RE.search(raw)
    return match.group(1).strip() if match else strip_html(raw)


def _to_float(text: str):
    try:
        return float(re.sub(r"[^0-9.\-]", "", text))
    except ValueError:
        return None


def _clean_row(row: dict) -> dict:
    return {
        "companyName": _parse_name_field(row.get("Name", "")),
        "status": _STATUS_MAP.get(row.get("~ipo_status1"), row.get("~ipo_status1")),
        "category": row.get("~IPO_Category"),
        "gmp": _parse_gmp_field(row.get("GMP", "")),
        "subscriptionTimes": strip_html(row.get("Sub", "")) or None,
        "price": strip_html(row.get("Price (₹)", "")) or None,
        "issueSize": strip_html(row.get("IPO Size", "")) or None,
        "lotSize": strip_html(row.get("Lot", "")) or None,
        "openDate": row.get("~Srt_Open"),
        "closeDate": row.get("~Srt_Close"),
        "listingDate": row.get("~Str_Listing"),
        "updatedOn": strip_html(row.get("Updated-On", "")) or None,
        "detailUrl": (
            "https://www.investorgain.com" + row["~urlrewrite_folder_name"]
            if row.get("~urlrewrite_folder_name")
            else None
        ),
    }


def fetch_gmp(session: requests.Session, category: str = "all") -> list:
    today = datetime.utcnow()
    fy = _fiscal_year_str(today)
    url = (
        f"{API_BASE}/{REPORT_ID}/1/{today.month}/{today.year}/{fy}/0/{category}"
    )
    resp = request_with_retry(session, "GET", url, params={"search": ""})
    data = resp.json()
    rows = data.get("reportTableData", [])
    return [_clean_row(r) for r in rows]


def fetch_all() -> dict:
    """Returns {"ok": bool, "error": str|None, "gmp": [...]}"""
    try:
        session = get_session()
        rows = fetch_gmp(session)
        return {"ok": True, "error": None, "gmp": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "gmp": []}


if __name__ == "__main__":
    import json

    result = fetch_all()
    print(json.dumps(result, indent=2)[:2500])
    print(f"\ngmp rows={len(result['gmp'])}")
