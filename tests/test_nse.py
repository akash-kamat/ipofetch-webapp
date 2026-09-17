import requests

from scraper import nse


class FakeSession:
    def close(self):
        pass


def test_current_issue_targets_are_deduplicated_by_symbol():
    rows = [
        {"symbol": "ONE", "series": "EQ"},
        {"symbol": "ONE", "series": "SME"},
        {"symbol": "TWO", "series": "EQ"},
        {"companyName": "No symbol"},
    ]

    assert [row["symbol"] for row in nse._unique_current_issues(rows)] == [
        "ONE",
        "TWO",
    ]


def test_subscription_sources_fail_independently(monkeypatch):
    monkeypatch.setattr(
        nse,
        "fetch_bid_details",
        lambda session, symbol, series: (_ for _ in ()).throw(
            requests.Timeout("NSE-only timeout")
        ),
    )
    monkeypatch.setattr(
        nse,
        "fetch_consolidated_bid_details",
        lambda session, symbol: {"dataList": [{"category": "Total"}]},
    )

    subscriptions, errors = nse._fetch_subscription_batch(
        [{"symbol": "ONE", "series": "EQ"}], FakeSession()
    )

    assert subscriptions == {
        "ONE": {"consolidated": {"dataList": [{"category": "Total"}]}}
    }
    assert errors == ["ONE NSE bids: NSE-only timeout"]
