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
            "companyName": "Example Limited",
            "status": "open",
            "issueSize": "₹125.50 Cr",
            "gmp": {"value": 15, "percent": 12.5},
        },
        {
            "companyName": "No Quote Limited",
            "status": "upcoming",
            "issueSize": None,
            "gmp": None,
        },
    ],
}


def test_market_endpoint_returns_backend_summary(monkeypatch):
    monkeypatch.setattr(index.merge, "collect", lambda: SAMPLE)
    monkeypatch.setattr(index, "_cache_payload", None)
    client = TestClient(index.app)

    response = client.get("/api/market")

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["delivery"] == "live"
    assert payload["overview"] == {
        "totalIssues": 2,
        "openIssues": 1,
        "upcomingIssues": 1,
        "quotedIssues": 1,
        "averageGmpPercent": 12.5,
        "disclosedCapitalCrore": 125.5,
        "earlyGmpIssues": 1,
    }


def test_ipo_detail_endpoint(monkeypatch):
    monkeypatch.setattr(index, "_cache_payload", SAMPLE)
    monkeypatch.setattr(index, "_cache_time", index.time.monotonic())
    response = TestClient(index.app).get("/api/ipos/examplelimited")
    assert response.status_code == 200
    assert response.json()["companyName"] == "Example Limited"
