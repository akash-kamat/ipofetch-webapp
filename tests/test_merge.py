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
        "past": [],
        "subscriptions": {},
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
    assert trimmed["issueKey"] == "signalindustries"


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
        {"current": [], "upcoming": [], "past": []}, {"issues": []}, {"gmp": [row]}
    )
    assert unmatched == [row]


def test_closed_nse_issues_and_consolidated_subscription_are_kept():
    nse_data = {
        "current": [{"companyName": "Live Limited", "symbol": "LIVE", "series": "EQ"}],
        "upcoming": [],
        "past": [
            {
                "companyName": "Historic Limited",
                "symbol": "HISTORIC",
                "issueStartDate": "01-Jan-2026",
                "issueEndDate": "03-Jan-2026",
            }
        ],
        "subscriptions": {
            "LIVE": {
                "nse": {
                    "data": [
                        {
                            "srNo": 1,
                            "category": "Retail",
                            "noOfSharesOffered": "1,000",
                            "noOfsharesBid": "2,000",
                            "noOfTime": "2.00",
                        }
                    ]
                },
                "consolidated": {
                    "updateTime": "17-Sep-2026 12:00:00",
                    "dataList": [
                        {
                            "srNo": 1,
                            "category": "Total",
                            "noOfShareOffered": "1,500",
                            "noOfSharesBid": "3,000",
                            "noOfTotalMeant": "2.00",
                        }
                    ],
                },
            }
        },
    }
    records, _ = merge.build_merged(nse_data, {"issues": []}, {"gmp": []})
    by_name = {record["companyName"]: merge._trim(record) for record in records}

    assert by_name["Historic Limited"]["status"] == "closed"
    assert by_name["Live Limited"]["subscription"]["totalTimes"] == 2.0
    assert (
        by_name["Live Limited"]["subscription"]["nseBidDetails"][0]["sharesBid"] == 2000
    )


def test_symbol_aliases_are_deduplicated():
    records, _ = merge.build_merged(
        {
            "current": [
                {"companyName": "R S L Limited", "symbol": "RSL", "series": "EQ"},
                {"companyName": "RSL Limited", "symbol": "RSL", "series": "EQ"},
            ],
            "upcoming": [],
            "past": [],
            "subscriptions": {},
        },
        {"issues": []},
        {"gmp": []},
    )
    assert len(records) == 1
    assert records[0]["issueKey"] == "rsl"
