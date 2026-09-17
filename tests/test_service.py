from datetime import UTC, datetime, timedelta
from uuid import uuid4

from api.database import StoredMarket
from api.service import MarketService

PAYLOAD = {
    "generatedAt": "2026-09-17T00:00:00Z",
    "sources": {"nse": {"ok": True, "error": None, "recordCount": 1}},
    "earlyGmp": [],
    "ipos": [{"issueKey": "one", "companyName": "One", "status": "closed"}],
}


class FakeRepository:
    def __init__(self, stored=None, lease=True):
        self.stored = stored
        self.lease = lease
        self.saved = None
        self.failed = None
        self.load_calls = 0

    def load_current(self):
        self.load_calls += 1
        return self.stored

    def start_refresh(self, trigger):
        return uuid4() if self.lease else None

    def save_success(self, refresh_id, payload):
        self.saved = payload

    def save_failure(self, refresh_id, error):
        self.failed = error


def test_fresh_database_result_does_not_scrape(monkeypatch):
    stored = StoredMarket(PAYLOAD, datetime.now(UTC))
    repository = FakeRepository(stored)
    monkeypatch.setattr(
        "api.service.merge.collect", lambda: (_ for _ in ()).throw(AssertionError())
    )

    result = MarketService(repository).get_market()

    assert result["meta"]["delivery"] == "database"
    assert result["overview"]["closedIssues"] == 1


def test_failed_refresh_serves_last_success(monkeypatch):
    stored = StoredMarket(PAYLOAD, datetime.now(UTC) - timedelta(hours=1))
    repository = FakeRepository(stored)
    monkeypatch.setattr(
        "api.service.merge.collect", lambda: (_ for _ in ()).throw(RuntimeError("down"))
    )

    result = MarketService(repository).get_market()

    assert result["meta"]["delivery"] == "stale"
    assert repository.failed == "down"


def test_manual_refresh_does_not_load_old_snapshot_before_scraping(monkeypatch):
    stored = StoredMarket(PAYLOAD, datetime.now(UTC))
    repository = FakeRepository(stored)
    monkeypatch.setattr("api.service.merge.collect", lambda: PAYLOAD)

    result = MarketService(repository).get_market(force=True)

    assert result["meta"]["delivery"] == "live"
    assert repository.load_calls == 0
    assert repository.saved == PAYLOAD
