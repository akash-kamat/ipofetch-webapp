import requests

from api.analysis import (
    OpenRouterClient,
    _analysis_snapshot,
    _finalize_report,
    _gmp_score,
    _parse_json,
    _qib_score,
    _subscription_metrics,
    _total_score,
    analysis_fingerprint,
)
from api.models import AnalysisReport

ISSUE = {
    "issueKey": "example",
    "companyName": "Example Limited",
    "status": "open",
    "openDate": "2026-09-17",
    "closeDate": "2026-09-19",
    "priceBand": {"min": 100, "max": 110},
    "lotSize": 100,
    "gmp": {"value": 22, "percent": 20},
    "subscription": {
        "totalTimes": 7.2,
        "updatedAt": "17-Sep-2026 12:30:00",
        "nseBidDetails": [],
        "consolidatedBidDetails": [
            {"category": "Qualified Institutional Buyers (QIBs)", "times": 12.4},
            {"category": "Non Institutional Investors", "times": 8.1},
            {"category": "Retail Individual Investors", "times": 3.2},
        ],
    },
}


def test_subscription_metrics_prefer_consolidated_bid_details():
    values = _subscription_metrics(ISSUE)

    assert values == {
        "qib": 12.4,
        "nii": 8.1,
        "retail": 3.2,
        "other": None,
        "total": 7.2,
    }


def test_deterministic_scoring_boundaries():
    assert [_qib_score(value) for value in (0.9, 1, 2, 5, 10, 25, 51)] == [
        0,
        5,
        10,
        14,
        17,
        19,
        20,
    ]
    assert [_total_score(value) for value in (0.9, 1, 2, 5, 10, 25, 51)] == [
        0,
        3,
        5,
        7,
        8,
        9,
        10,
    ]
    assert [_gmp_score(value) for value in (-1, 0, 2.1, 5.1, 10.1, 20.1, 31)] == [
        0,
        5,
        8,
        12,
        16,
        18,
        20,
    ]


def test_fingerprint_changes_only_when_analysis_input_changes():
    first = analysis_fingerprint(ISSUE, "model-a")
    same = analysis_fingerprint({**ISSUE, "unrelated": "ignored"}, "model-a")
    changed = analysis_fingerprint({**ISSUE, "gmp": {"value": 25}}, "model-a")

    assert first == same
    assert first != changed


def test_openrouter_request_uses_web_search_and_strict_schema():
    body = OpenRouterClient(api_key="test", model="vendor/model").request_body(
        ISSUE, "2026-09-17T06:00:00Z"
    )

    assert body["model"] == "vendor/model"
    assert body["plugins"][0]["id"] == "web"
    assert body["plugins"][0]["engine"] == "firecrawl"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "provider" not in body
    assert "12.4" in body["messages"][1]["content"]


def test_analysis_snapshot_removes_duplicate_raw_bid_counts():
    issue = {
        **ISSUE,
        "subscription": {
            **ISSUE["subscription"],
            "nseBidDetails": [
                {
                    "category": "Retail",
                    "sharesOffered": 100,
                    "sharesBid": 200,
                    "times": 2,
                }
            ],
        },
    }

    snapshot = _analysis_snapshot(issue)

    assert "nseBidDetails" not in snapshot["subscription"]
    assert snapshot["subscription"]["consolidatedBidDetails"][0] == {
        "category": "Qualified Institutional Buyers (QIBs)",
        "times": 12.4,
    }


def test_parse_json_accepts_reasoning_before_the_object():
    assert _parse_json('<think>research notes</think>\n{"result":"ok"}') == {
        "result": "ok"
    }


def test_compatibility_request_keeps_search_and_moves_schema_into_prompt():
    client = OpenRouterClient(api_key="test", model="vendor/model")
    body = client.request_body(ISSUE, "2026-09-17T06:00:00Z")

    compatible = client.compatibility_request_body(body)

    assert "response_format" not in compatible
    assert "provider" not in compatible
    assert compatible["plugins"] == [body["plugins"][0]]
    assert '"issueStructure"' in compatible["messages"][-1]["content"]
    assert "output contract" in compatible["messages"][-1]["content"]


def test_parameter_routing_failure_retries_with_compatibility_body(monkeypatch):
    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)

        def json(self):
            return self.payload

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return FakeResponse(
                {
                    "error": {
                        "message": "No endpoints found that can handle the requested parameters"
                    }
                },
                404,
            )
        return FakeResponse(
            {
                "choices": [{"message": {"content": '{"result":"ok"}'}}],
                "usage": {"total_tokens": 1},
            }
        )

    monkeypatch.setattr("api.analysis.requests.post", fake_post)
    client = OpenRouterClient(api_key="test", model="vendor/model")

    report, usage = client.analyse(ISSUE, "2026-09-17T06:00:00Z")

    assert report == {"result": "ok", "sources": []}
    assert usage == {"total_tokens": 1}
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_final_report_uses_authoritative_market_scores():
    citation = {"title": "NSE", "url": "https://www.nseindia.com/", "publishedAt": None}

    def score(value, maximum):
        return {"score": value, "maximum": maximum, "rationale": "Researched"}

    def section(value, maximum):
        return {
            "summary": "Researched summary",
            "facts": [],
            "score": score(value, maximum),
            "sources": [citation],
        }

    raw = {
        "dataAsOf": "old",
        "issueStructure": {
            "issueSize": "₹100 Cr",
            "freshIssue": "₹60 Cr",
            "ofs": "₹40 Cr",
            "priceBand": "₹100-110",
            "lotSize": "100",
            "minimumInvestment": "₹11,000",
            "useOfProceeds": ["Expansion"],
            "promoterHoldingBefore": "70%",
            "promoterHoldingAfter": "60%",
            "sources": [citation],
        },
        "subscription": {
            "qibTimes": 999,
            "niiTimes": 999,
            "retailTimes": 999,
            "employeeOrShareholderTimes": None,
            "totalTimes": 999,
            "asOf": "old",
            "qibDemandExplanation": "Strong",
            "qibScore": score(20, 20),
            "totalScore": score(10, 10),
        },
        "gmp": {
            "currentGmp": 999,
            "currentPercent": 99,
            "trend": "Positive",
            "impliedListingPrice": 132,
            "expectedListingGain": "20%",
            "score": score(20, 20),
            "sources": [citation],
        },
        "legal": {"summary": "Low risk", "findings": [], "score": score(22, 25)},
        "valuation": {
            "metrics": [],
            "peers": [],
            "summary": "Fair",
            "score": score(6, 8),
        },
        "market": section(4, 5),
        "industry": section(2, 3),
        "anchorInvestors": section(3, 4),
        "freshOfs": section(2, 3),
        "fundamentals": section(1, 2),
        "totalScore": 100,
        "verdict": "STRONG APPLY",
        "applyDecision": "APPLY",
        "hardRedFlag": False,
        "hardRedFlagReason": "None found",
        "listingGain": {
            "bearCase": "0%",
            "baseCase": "10%",
            "bullCase": "20%",
            "expectedGainPercent": "10%",
            "expectedPriceRange": "₹110-120",
        },
        "reasons": ["Reason"],
        "sources": [citation],
        "dataLimitations": [],
        "disclaimer": "Model text",
    }

    report = _finalize_report(
        AnalysisReport.model_validate(raw), ISSUE, "2026-09-17T06:00:00Z"
    )

    assert report.subscription.qib_times == 12.4
    assert report.subscription.qib_score.score == 17
    assert report.subscription.total_score.score == 7
    assert report.gmp.current_gmp == 22
    assert report.gmp.score.score == 16
    assert report.total_score == 80
    assert report.verdict == "STRONG APPLY"
