from fastapi.testclient import TestClient

from api import index

SAMPLE = {
    "generatedAt": "2026-09-16T12:00:00Z",
    "sources": {
        "nse": {"ok": True, "error": None, "recordCount": 1},
        "bse": {"ok": True, "error": None, "recordCount": 1},
        "investorGain": {"ok": True, "error": None, "recordCount": 2},
    },
    "earlyGmp": [{"companyName": "Early Co"}],
    "ipos": [
        {
            "issueKey": "example",
            "companyName": "Example Limited",
            "status": "open",
            "issueSize": "₹125.50 Cr",
            "gmp": {"value": 15, "percent": 12.5},
            "subscription": {
                "source": "NSE Consolidated Bid Details",
                "totalTimes": 1.38,
                "updatedAt": "16-Sep-2026 17:30:00",
                "nseBidDetails": [],
                "consolidatedBidDetails": [],
            },
        },
        {
            "issueKey": "oldexample",
            "companyName": "Old Example Limited",
            "status": "closed",
            "issueSize": None,
            "gmp": None,
        },
    ],
    "overview": {
        "totalIssues": 2,
        "openIssues": 1,
        "upcomingIssues": 0,
        "closedIssues": 1,
        "quotedIssues": 1,
        "averageGmpPercent": 12.5,
        "disclosedCapitalCrore": 125.5,
        "earlyGmpIssues": 1,
    },
    "meta": {
        "delivery": "database",
        "cacheTtlSeconds": 900,
        "servedAt": "2026-09-16T12:01:00Z",
        "refreshInProgress": False,
    },
}


class FakeService:
    def get_market(self, force=False):
        payload = {**SAMPLE, "meta": {**SAMPLE["meta"]}}
        if force:
            payload["meta"]["delivery"] = "live"
        return payload


def test_market_endpoint_returns_validated_summary(monkeypatch):
    monkeypatch.setattr(index, "service", FakeService())
    response = TestClient(index.app).get("/api/market")

    assert response.status_code == 200
    assert response.json()["overview"]["closedIssues"] == 1
    assert response.json()["ipos"][0]["subscription"]["totalTimes"] == 1.38


def test_manual_refresh_uses_force(monkeypatch):
    monkeypatch.setattr(index, "service", FakeService())
    response = TestClient(index.app).post("/api/refresh")
    assert response.status_code == 200
    assert response.json()["meta"]["delivery"] == "live"


def test_ipo_detail_accepts_stable_issue_key(monkeypatch):
    monkeypatch.setattr(index, "service", FakeService())
    response = TestClient(index.app).get("/api/ipos/example")
    assert response.status_code == 200
    assert response.json()["companyName"] == "Example Limited"
