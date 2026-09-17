"""Shared HTTP/session and normalization helpers used by all scrapers."""

import re
import time
from datetime import UTC, datetime

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30
REQUEST_GAP_SECONDS = 0.6
MAX_RETRIES = 3

_SUFFIX_RE = re.compile(r"\b(limited|ltd|private|pvt|iv|inc|llp)\b\.?", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_TAG_RE = re.compile(r"<[^>]+>")


def normalize_name(name: str) -> str:
    """Collapse a company name to a matchable key (strip legal suffixes/punctuation)."""
    if not name:
        return ""
    text = strip_html(name).lower()
    text = _SUFFIX_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape a handful of common entities."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&#8377;", "₹").replace("&nbsp;", " ").replace("&amp;", "&")
    return " ".join(text.split())


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    **kwargs,
):
    """GET/POST with exponential backoff. Raises the last error if all retries fail."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code in (401, 403):
                raise requests.HTTPError(f"{resp.status_code} for {url}", response=resp)
            resp.raise_for_status()
            time.sleep(REQUEST_GAP_SECONDS)
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    raise last_exc


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
