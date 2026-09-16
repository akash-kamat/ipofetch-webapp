from scraper import merge


def test_price_band_parses_range_and_fixed_price():
    assert merge._parse_price_band("Rs. 100 - 120") == {"min": 100.0, "max": 120.0}
    assert merge._parse_price_band("₹75") == {"min": 75.0, "max": 75.0}
    assert merge._parse_price_band(None) is None


def test_merged_record_keeps_dashboard_metadata():
    nse_data = {
        "ok": True,
        "error": None,
        "upcoming": [
            {
                "companyName": "Signal Industries Limited",
                "issueStartDate": "17-Sep-2026",
                "issueEndDate": "21-Sep-2026",
                "issuePrice": "100-110",
            }
        ],
        "current": [],
    }
    bse_data = {
        "ok": True,
        "error": None,
        "issues": [
            {
                "Scrip_Name": "Signal Industries Ltd",
                "eXCHANGE_PLATFORM": "MAINBOARD",
                "Start_Dt": "2026-09-17T00:00:00",
                "End_Dt": "2026-09-21T00:00:00",
                "Face_Val": 10,
                "Price_Band": "100-110",
                "Status": "F",
            }
        ],
    }
    gmp_data = {
        "ok": True,
        "error": None,
        "gmp": [
            {
                "companyName": "Signal Industries",
                "status": "upcoming",
                "category": "MAINBOARD",
                "gmp": {"value": 20.0, "percent": 18.18},
                "subscriptionTimes": "-",
                "listingDate": "2026-09-24",
                "issueSize": "₹100 Cr",
                "lotSize": "100",
                "updatedOn": "16-Sep-2026 10:00",
                "detailUrl": "https://example.com/signal",
            }
        ],
    }

    records, unmatched = merge.build_merged(nse_data, bse_data, gmp_data)
    trimmed = merge._trim(records[0])

    assert unmatched == []
    assert trimmed["exchanges"] == ["BSE", "NSE"]
    assert trimmed["platform"] == "Mainboard"
    assert trimmed["gmp"] == {"value": 20.0, "percent": 18.18}
    assert trimmed["gmpUpdatedOn"] == "16-Sep-2026 10:00"
    assert trimmed["detailUrl"] == "https://example.com/signal"


def test_source_health_is_safe_for_missing_fields():
    assert merge._source_health({"ok": True, "error": None, "issues": [1, 2]}) == {
        "ok": True,
        "error": None,
        "recordCount": 2,
    }
    assert merge._source_health({}) == {
        "ok": False,
        "error": None,
        "recordCount": 0,
    }


def test_unmatched_gmp_keeps_the_complete_record():
    row = {
        "companyName": "Early Signal",
        "status": "upcoming",
        "category": "SME",
        "gmp": {"value": 12, "percent": 10},
        "detailUrl": "https://example.com/early",
    }
    _, unmatched = merge.build_merged(
        {"current": [], "upcoming": []}, {"issues": []}, {"gmp": [row]}
    )
    assert unmatched == [row]
