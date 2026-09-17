"""Merge NSE, BSE and GMP scrape results into the normalized market feed."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from . import bse, gmp, nse
from .common import normalize_name, utcnow_iso


def _parse_price_band(text):
    if not text:
        return None
    text = text.replace("Rs.", "").replace("₹", "")
    parts = [p.strip() for p in text.replace(" to ", "-").split("-") if p.strip()]
    try:
        if len(parts) == 2:
            return {"min": float(parts[0]), "max": float(parts[1])}
        if len(parts) == 1:
            return {"min": float(parts[0]), "max": float(parts[0])}
    except ValueError:
        pass
    return None


def _nse_date(text):
    # e.g. "16-Sep-2026" -> "2026-09-16"
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%b-%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None


def _bse_date(text):
    # e.g. "2026-09-15T00:00:00" -> "2026-09-15"
    if not text:
        return None
    return text.split("T")[0]


def _record():
    return {
        "companyName": None,
        "issueKey": None,
        "normalizedName": None,
        "platform": None,  # "SME" | "Mainboard" | None
        "exchanges": set(),
        "status": None,
        "openDate": None,
        "closeDate": None,
        "listingDate": None,
        "priceBand": None,
        "lotSize": None,
        "faceValue": None,
        "issueSize": None,
        "gmp": None,
        "subscription": None,
        "nseSymbol": None,
        "nse": None,
        "bse": None,
    }


def build_merged(nse_data: dict, bse_data: dict, gmp_data: dict) -> tuple[list, list]:
    by_key = {}

    def get_or_create(name):
        key = normalize_name(name)
        if not key:
            return None, None
        if key not in by_key:
            rec = _record()
            rec["companyName"] = name
            rec["issueKey"] = key.replace(" ", "")
            rec["normalizedName"] = key
            by_key[key] = rec
        return key, by_key[key]

    # NSE official upcoming and 12-month historical lists.
    for bucket in ("upcoming", "past"):
        for row in nse_data.get(bucket, []):
            name = row.get("companyName") or row.get("company")
            key, rec = get_or_create(name)
            if not rec:
                continue
            rec["exchanges"].add("NSE")
            rec["nse"] = row
            rec["nseSymbol"] = row.get("symbol") or rec["nseSymbol"]
            if row.get("symbol"):
                rec["issueKey"] = normalize_name(row["symbol"]).replace(" ", "")
            rec["openDate"] = rec["openDate"] or _nse_date(
                row.get("issueStartDate") or row.get("ipoStartDate")
            )
            rec["closeDate"] = rec["closeDate"] or _nse_date(
                row.get("issueEndDate") or row.get("ipoEndDate")
            )
            if rec["priceBand"] is None:
                rec["priceBand"] = _parse_price_band(
                    row.get("issuePrice") or row.get("priceRange")
                )
            rec["listingDate"] = rec["listingDate"] or _nse_date(row.get("listingDate"))
            rec["lotSize"] = (
                rec["lotSize"] or row.get("lotSize") or row.get("marketLot")
            )
            rec["faceValue"] = rec["faceValue"] or row.get("faceValue")
            rec["issueSize"] = rec["issueSize"] or row.get("issueSize")
            if "SME" in (row.get("series") or ""):
                rec["platform"] = "SME"
            rec["status"] = "closed" if bucket == "past" else "upcoming"

    for row in nse_data.get("current", []):
        name = row.get("companyName")
        key, rec = get_or_create(name)
        if rec:
            rec["exchanges"].add("NSE")
            rec["status"] = "open"
            rec["nse"] = row
            rec["nseSymbol"] = row.get("symbol") or rec["nseSymbol"]
            rec["openDate"] = rec["openDate"] or _nse_date(
                row.get("issueStartDate") or row.get("ipoStartDate")
            )
            rec["closeDate"] = rec["closeDate"] or _nse_date(
                row.get("issueEndDate") or row.get("ipoEndDate")
            )
            if rec["priceBand"] is None:
                rec["priceBand"] = _parse_price_band(
                    row.get("issuePrice") or row.get("priceRange")
                )
            rec["listingDate"] = rec["listingDate"] or _nse_date(row.get("listingDate"))
            rec["lotSize"] = (
                rec["lotSize"] or row.get("lotSize") or row.get("marketLot")
            )
            rec["faceValue"] = rec["faceValue"] or row.get("faceValue")
            rec["issueSize"] = rec["issueSize"] or row.get("issueSize")
            if "SME" in (row.get("series") or ""):
                rec["platform"] = "SME"
            if row.get("symbol"):
                rec["issueKey"] = normalize_name(row["symbol"]).replace(" ", "")
                raw_subscription = nse_data.get("subscriptions", {}).get(row["symbol"])
                rec["subscription"] = _subscription(raw_subscription)

    # BSE: single list, Status F (forthcoming) / L (live-to-list, subscription open or closed)
    for row in bse_data.get("issues", []):
        name = row.get("Scrip_Name")
        key, rec = get_or_create(name)
        if not rec:
            continue
        rec["exchanges"].add("BSE")
        rec["bse"] = row
        rec["platform"] = rec["platform"] or (
            "SME" if row.get("eXCHANGE_PLATFORM") == "SME" else "Mainboard"
        )
        rec["openDate"] = rec["openDate"] or _bse_date(row.get("Start_Dt"))
        rec["closeDate"] = rec["closeDate"] or _bse_date(row.get("End_Dt"))
        rec["faceValue"] = rec["faceValue"] or row.get("Face_Val")
        if rec["priceBand"] is None:
            rec["priceBand"] = _parse_price_band(row.get("Price_Band"))
        if not rec["status"]:
            rec["status"] = _bse_status(row)

    # GMP: merge in by normalized name; GMP names are the shortest/least formal,
    # so this is a best-effort match, not guaranteed to hit every record.
    unmatched_gmp = []
    for row in gmp_data.get("gmp", []):
        key = normalize_name(row["companyName"])
        rec = by_key.get(key)
        if rec is None:
            symbol_matches = [
                item
                for item in by_key.values()
                if normalize_name(item.get("nseSymbol") or "") == key
            ]
            rec = symbol_matches[0] if len(symbol_matches) == 1 else None
        if rec is None:
            # try prefix match: GMP names often drop trailing words BSE/NSE keep
            candidates = [k for k in by_key if k.startswith(key) or key.startswith(k)]
            rec = by_key[candidates[0]] if len(candidates) == 1 else None
        if rec is None:
            unmatched_gmp.append(row)
            continue
        rec["gmp"] = row
        rec["status"] = rec["status"] or row.get("status")
        rec["platform"] = rec["platform"] or (
            "SME" if row.get("category") == "SME" else None
        )
        rec["listingDate"] = rec["listingDate"] or row.get("listingDate")
        if row.get("issueSize"):
            rec["issueSize"] = row["issueSize"]
        rec["lotSize"] = rec["lotSize"] or row.get("lotSize")

    for rec in by_key.values():
        rec["exchanges"] = sorted(rec["exchanges"])

    return _deduplicate(list(by_key.values())), unmatched_gmp


def _deduplicate(records: list[dict]) -> list[dict]:
    """Collapse exchange aliases such as `R S L` and `RSL` onto one issue key."""
    unique = {}
    status_priority = {None: 0, "closed": 1, "upcoming": 2, "open": 3}
    for record in records:
        key = record["issueKey"]
        existing = unique.get(key)
        if existing is None:
            unique[key] = record
            continue
        existing["exchanges"] = sorted(
            set(existing.get("exchanges", [])) | set(record.get("exchanges", []))
        )
        if status_priority.get(record.get("status"), 0) > status_priority.get(
            existing.get("status"), 0
        ):
            existing["status"] = record["status"]
        for field in (
            "platform",
            "openDate",
            "closeDate",
            "listingDate",
            "priceBand",
            "lotSize",
            "faceValue",
            "issueSize",
            "gmp",
            "subscription",
            "nseSymbol",
            "nse",
            "bse",
        ):
            if existing.get(field) in (None, [], "") and record.get(field) not in (
                None,
                [],
                "",
            ):
                existing[field] = record[field]
    return list(unique.values())


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("x", "").strip())
    except ValueError:
        return None


def _integer(value):
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _subscription(raw: dict | None) -> dict | None:
    if not raw:
        return None
    nse_payload = raw.get("nse") or {}
    consolidated_payload = raw.get("consolidated") or {}

    def normalize(rows):
        result = []
        for row in rows or []:
            result.append(
                {
                    "srNo": row.get("srNo"),
                    "category": row.get("category"),
                    "sharesOffered": _integer(
                        row.get("noOfSharesOffered", row.get("noOfShareOffered"))
                    ),
                    "sharesBid": _integer(
                        row.get("noOfsharesBid", row.get("noOfSharesBid"))
                    ),
                    "times": _number(row.get("noOfTime", row.get("noOfTotalMeant"))),
                }
            )
        return result

    nse_rows = normalize(nse_payload.get("data"))
    consolidated_rows = normalize(consolidated_payload.get("dataList"))
    total = next(
        (
            row.get("times")
            for row in reversed(consolidated_rows)
            if "total" in (row.get("category") or "").lower()
        ),
        None,
    )
    if total is None and consolidated_rows:
        offered = sum(row.get("sharesOffered") or 0 for row in consolidated_rows)
        bid = sum(row.get("sharesBid") or 0 for row in consolidated_rows)
        total = round(bid / offered, 2) if offered else None
    return {
        "source": "NSE Consolidated Bid Details",
        "totalTimes": total,
        "updatedAt": consolidated_payload.get("updateTime")
        or nse_payload.get("updateTime"),
        "nseBidDetails": nse_rows,
        "consolidatedBidDetails": consolidated_rows,
    }


def _bse_status(row: dict) -> str | None:
    if row.get("Status") == "F":
        return "upcoming"
    start = _bse_date(row.get("Start_Dt"))
    end = _bse_date(row.get("End_Dt"))
    today = datetime.now(UTC).date().isoformat()
    if start and start > today:
        return "upcoming"
    if end and end < today:
        return "closed"
    if start and end and start <= today <= end:
        return "open"
    return None


def _trim(rec: dict) -> dict:
    gmp_row = rec.get("gmp")
    return {
        "issueKey": rec["issueKey"],
        "companyName": rec["companyName"],
        "platform": rec["platform"],
        "exchanges": rec["exchanges"],
        "status": rec["status"],
        "openDate": rec["openDate"],
        "closeDate": rec["closeDate"],
        "listingDate": rec["listingDate"],
        "priceBand": rec["priceBand"],
        "lotSize": rec["lotSize"],
        "faceValue": rec["faceValue"],
        "issueSize": _display_issue_size(rec["issueSize"], rec["priceBand"]),
        "gmp": gmp_row["gmp"] if gmp_row else None,
        "subscription": rec.get("subscription"),
        "gmpUpdatedOn": gmp_row.get("updatedOn") if gmp_row else None,
        "detailUrl": gmp_row.get("detailUrl") if gmp_row else None,
    }


def _display_issue_size(value, price_band: dict | None) -> str | None:
    """NSE reports share count; present it as capital instead of raw shares."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if any(unit in text.lower() for unit in ("cr", "crore", "lakh", "₹", "rs")):
        return text
    shares = _number(value)
    upper_price = (price_band or {}).get("max")
    if shares is not None and upper_price is not None:
        crore = shares * float(upper_price) / 10_000_000
        return f"~₹{crore:,.2f} Cr"
    return text


def _source_health(source_data: dict) -> dict:
    """Expose scrape health without leaking bulky, source-specific payloads."""
    return {
        "ok": bool(source_data.get("ok")),
        "error": source_data.get("error")
        or "; ".join(source_data.get("subscriptionErrors", []))
        or None,
        "recordCount": sum(
            len(value)
            for key, value in source_data.items()
            if isinstance(value, list) and key != "subscriptionErrors"
        ),
    }


def collect() -> dict:
    """Fetch all providers concurrently and return the complete public feed."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        nse_future = pool.submit(nse.fetch_all, months_back=12)
        bse_future = pool.submit(bse.fetch_all)
        gmp_future = pool.submit(gmp.fetch_all)
        nse_data = nse_future.result()
        bse_data = bse_future.result()
        gmp_data = gmp_future.result()

    ipos, unmatched_gmp = build_merged(nse_data, bse_data, gmp_data)
    ipos = [r for r in ipos if r["status"] in ("open", "upcoming", "closed")]
    status_order = {"open": 0, "upcoming": 1, "closed": 2}
    ipos.sort(
        key=lambda r: (
            status_order.get(r["status"], 9),
            -(int((r["openDate"] or "0000-00-00").replace("-", "")))
            if r["status"] == "closed"
            else 0,
            r["openDate"] or "9999-99-99",
            r["companyName"] or "",
        )
    )
    trimmed = [_trim(r) for r in ipos]

    return {
        "generatedAt": utcnow_iso(),
        "sources": {
            "nse": _source_health(nse_data),
            "bse": _source_health(bse_data),
            "investorGain": _source_health(gmp_data),
        },
        "earlyGmp": unmatched_gmp,
        "ipos": trimmed,
    }
