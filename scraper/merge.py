"""Merge NSE, BSE and GMP scrape results into a single data/ipos.json feed."""
import argparse
import json
import os

import bse
import gmp
import nse
from common import normalize_name, utcnow_iso

DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "data", "ipos.json")


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
        import datetime

        return datetime.datetime.strptime(text, "%d-%b-%Y").strftime("%Y-%m-%d")
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
        "nse": None,
        "bse": None,
    }


def build_merged(nse_data: dict, bse_data: dict, gmp_data: dict) -> list:
    by_key = {}

    def get_or_create(name):
        key = normalize_name(name)
        if not key:
            return None, None
        if key not in by_key:
            rec = _record()
            rec["companyName"] = name
            rec["normalizedName"] = key
            by_key[key] = rec
        return key, by_key[key]

    # NSE: current + upcoming + past (current/upcoming duplicate each other; dedupe by symbol)
    for bucket in ("upcoming", "past"):
        for row in nse_data.get(bucket, []):
            name = row.get("companyName") or row.get("company")
            key, rec = get_or_create(name)
            if not rec:
                continue
            rec["exchanges"].add("NSE")
            rec["nse"] = row
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
            if "SME" in (row.get("series") or ""):
                rec["platform"] = "SME"

    for row in nse_data.get("current", []):
        name = row.get("companyName")
        key, rec = get_or_create(name)
        if rec:
            rec["exchanges"].add("NSE")
            rec["status"] = "open"
            rec["nse"] = row

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
        if row.get("Status") == "F":
            rec["status"] = rec["status"] or "upcoming"

    # GMP: merge in by normalized name; GMP names are the shortest/least formal,
    # so this is a best-effort match, not guaranteed to hit every record.
    unmatched_gmp = []
    for row in gmp_data.get("gmp", []):
        key = normalize_name(row["companyName"])
        rec = by_key.get(key)
        if rec is None:
            # try prefix match: GMP names often drop trailing words BSE/NSE keep
            candidates = [k for k in by_key if k.startswith(key) or key.startswith(k)]
            rec = by_key[candidates[0]] if len(candidates) == 1 else None
        if rec is None:
            unmatched_gmp.append(row["companyName"])
            continue
        rec["gmp"] = row
        rec["status"] = row.get("status") or rec["status"]
        rec["platform"] = rec["platform"] or (
            "SME" if row.get("category") == "SME" else None
        )
        rec["listingDate"] = rec["listingDate"] or row.get("listingDate")
        rec["issueSize"] = rec["issueSize"] or row.get("issueSize")
        rec["lotSize"] = rec["lotSize"] or row.get("lotSize")

    for rec in by_key.values():
        rec["exchanges"] = sorted(rec["exchanges"])

    return list(by_key.values()), unmatched_gmp


def run(out_path: str, past_months: int):
    nse_data = nse.fetch_all(months_back=past_months)
    bse_data = bse.fetch_all()
    gmp_data = gmp.fetch_all()

    ipos, unmatched_gmp = build_merged(nse_data, bse_data, gmp_data)
    ipos.sort(key=lambda r: (r["openDate"] or "", r["companyName"] or ""), reverse=True)

    output = {
        "generatedAt": utcnow_iso(),
        "sources": {
            "nse": {"ok": nse_data["ok"], "error": nse_data["error"]},
            "bse": {"ok": bse_data["ok"], "error": bse_data["error"]},
            "gmp": {"ok": gmp_data["ok"], "error": gmp_data["error"]},
        },
        "counts": {
            "total": len(ipos),
            "withGmp": sum(1 for r in ipos if r["gmp"] is not None),
            "unmatchedGmpRows": len(unmatched_gmp),
        },
        "unmatchedGmpNames": unmatched_gmp,
        "ipos": ipos,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--past-months", type=int, default=3)
    args = parser.parse_args()

    result = run(args.out, args.past_months)
    print(
        f"Wrote {args.out}: total={result['counts']['total']} "
        f"withGmp={result['counts']['withGmp']} "
        f"unmatchedGmpRows={result['counts']['unmatchedGmpRows']} "
        f"sources_ok={ {k: v['ok'] for k, v in result['sources'].items()} }"
    )
