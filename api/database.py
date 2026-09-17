"""Durable Neon storage and cross-instance refresh coordination."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_refreshes (
    id uuid PRIMARY KEY,
    trigger text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    generated_at timestamptz,
    sources jsonb,
    error text
);
CREATE TABLE IF NOT EXISTS market_issues (
    refresh_id uuid NOT NULL REFERENCES market_refreshes(id) ON DELETE CASCADE,
    position integer NOT NULL,
    issue_key text NOT NULL,
    company_name text NOT NULL,
    platform text,
    exchanges text[] NOT NULL DEFAULT '{}',
    status text,
    open_date text,
    close_date text,
    listing_date text,
    price_min double precision,
    price_max double precision,
    lot_size text,
    face_value text,
    issue_size text,
    gmp_value double precision,
    gmp_percent double precision,
    gmp_updated_on text,
    detail_url text,
    subscription_total double precision,
    subscription_updated_at text,
    PRIMARY KEY (refresh_id, issue_key)
);
CREATE TABLE IF NOT EXISTS subscription_details (
    refresh_id uuid NOT NULL,
    issue_key text NOT NULL,
    scope text NOT NULL CHECK (scope IN ('nse', 'consolidated')),
    position integer NOT NULL,
    sr_no text,
    category text,
    shares_offered bigint,
    shares_bid bigint,
    times double precision,
    PRIMARY KEY (refresh_id, issue_key, scope, position),
    FOREIGN KEY (refresh_id, issue_key)
        REFERENCES market_issues(refresh_id, issue_key) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS early_gmp_records (
    refresh_id uuid NOT NULL REFERENCES market_refreshes(id) ON DELETE CASCADE,
    position integer NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (refresh_id, position)
);
CREATE TABLE IF NOT EXISTS market_refresh_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    current_refresh_id uuid,
    lock_owner uuid,
    locked_until timestamptz,
    last_manual_at timestamptz
);
ALTER TABLE market_refresh_state ADD COLUMN IF NOT EXISTS lock_owner uuid;
INSERT INTO market_refresh_state(singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;
CREATE TABLE IF NOT EXISTS ipo_analysis_reports (
    id uuid PRIMARY KEY,
    issue_key text NOT NULL,
    company_name text NOT NULL,
    input_fingerprint text NOT NULL,
    model text NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now(),
    market_generated_at text NOT NULL,
    report jsonb NOT NULL,
    usage jsonb,
    UNIQUE (issue_key, input_fingerprint)
);
CREATE INDEX IF NOT EXISTS ipo_analysis_reports_latest_idx
ON ipo_analysis_reports(issue_key, generated_at DESC);
CREATE TABLE IF NOT EXISTS ipo_analysis_state (
    issue_key text PRIMARY KEY,
    lock_token uuid,
    input_fingerprint text,
    locked_until timestamptz,
    last_generated_at timestamptz
);
"""


@dataclass
class StoredMarket:
    payload: dict
    completed_at: datetime


class MarketRepository:
    """Small repository around a Neon/Postgres connection string."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self._schema_ready = False
        self._pool = (
            ConnectionPool(
                conninfo=self.database_url,
                min_size=0,
                max_size=2,
                timeout=10,
                max_idle=300,
                kwargs={"connect_timeout": 10, "row_factory": dict_row},
                open=True,
            )
            if self.database_url
            else None
        )

    def _connect(self):
        if self._pool is None:
            raise RuntimeError("DATABASE_URL is not configured")
        return self._pool.connection()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._connect() as connection:
            connection.execute(SCHEMA)
        self._schema_ready = True

    def start_refresh(self, trigger: str) -> uuid.UUID | None:
        """Acquire a two-minute database lease and create a refresh run."""
        self._ensure_schema()
        refresh_id = uuid.uuid4()
        with self._connect() as connection:
            claimed = connection.execute(
                """
                UPDATE market_refresh_state
                SET lock_owner = %s,
                    locked_until = now() + interval '2 minutes',
                    last_manual_at = CASE WHEN %s = 'manual' THEN now() ELSE last_manual_at END
                WHERE singleton = true
                  AND (locked_until IS NULL OR locked_until < now())
                  AND (%s <> 'manual' OR last_manual_at IS NULL
                       OR last_manual_at < now() - interval '5 minutes')
                RETURNING singleton
                """,
                (refresh_id, trigger, trigger),
            ).fetchone()
            if not claimed:
                return None
            connection.execute(
                "INSERT INTO market_refreshes(id, trigger, status) VALUES (%s, %s, 'running')",
                (refresh_id, trigger),
            )
        return refresh_id

    def save_success(self, refresh_id: uuid.UUID, payload: dict) -> None:
        self._ensure_schema()
        with self._connect() as connection, connection.pipeline():
            for position, issue in enumerate(payload.get("ipos", [])):
                price = issue.get("priceBand") or {}
                gmp = issue.get("gmp") or {}
                subscription = issue.get("subscription") or {}
                issue_key = issue.get("issueKey") or _key(issue.get("companyName", ""))
                connection.execute(
                    """
                    INSERT INTO market_issues(
                        refresh_id, position, issue_key, company_name, platform, exchanges,
                        status, open_date, close_date, listing_date, price_min, price_max,
                        lot_size, face_value, issue_size, gmp_value, gmp_percent,
                        gmp_updated_on, detail_url, subscription_total, subscription_updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        refresh_id,
                        position,
                        issue_key,
                        issue.get("companyName"),
                        issue.get("platform"),
                        issue.get("exchanges") or [],
                        issue.get("status"),
                        issue.get("openDate"),
                        issue.get("closeDate"),
                        issue.get("listingDate"),
                        price.get("min"),
                        price.get("max"),
                        _text(issue.get("lotSize")),
                        _text(issue.get("faceValue")),
                        _text(issue.get("issueSize")),
                        gmp.get("value"),
                        gmp.get("percent"),
                        issue.get("gmpUpdatedOn"),
                        issue.get("detailUrl"),
                        subscription.get("totalTimes"),
                        subscription.get("updatedAt"),
                    ),
                )
                for scope, field in (
                    ("nse", "nseBidDetails"),
                    ("consolidated", "consolidatedBidDetails"),
                ):
                    for row_position, row in enumerate(subscription.get(field) or []):
                        connection.execute(
                            """
                            INSERT INTO subscription_details(
                                refresh_id, issue_key, scope, position, sr_no, category,
                                shares_offered, shares_bid, times
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                refresh_id,
                                issue_key,
                                scope,
                                row_position,
                                _text(row.get("srNo")),
                                row.get("category"),
                                row.get("sharesOffered"),
                                row.get("sharesBid"),
                                row.get("times"),
                            ),
                        )

            for position, row in enumerate(payload.get("earlyGmp", [])):
                connection.execute(
                    "INSERT INTO early_gmp_records(refresh_id, position, payload) VALUES (%s, %s, %s)",
                    (refresh_id, position, Jsonb(row)),
                )

            connection.execute(
                """
                UPDATE market_refreshes
                SET status = 'succeeded', completed_at = now(), generated_at = %s, sources = %s
                WHERE id = %s
                """,
                (
                    payload.get("generatedAt"),
                    Jsonb(payload.get("sources", {})),
                    refresh_id,
                ),
            )
            connection.execute(
                """
                UPDATE market_refresh_state
                SET current_refresh_id = %s, lock_owner = NULL, locked_until = NULL
                WHERE singleton = true AND lock_owner = %s
                """,
                (refresh_id, refresh_id),
            )
            connection.execute(
                """
                DELETE FROM market_refreshes WHERE id IN (
                    SELECT id FROM market_refreshes
                    WHERE status <> 'running' AND id <> %s
                    ORDER BY completed_at DESC NULLS LAST OFFSET 9
                )
                """,
                (refresh_id,),
            )

    def save_failure(self, refresh_id: uuid.UUID, error: str) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE market_refreshes SET status = 'failed', completed_at = now(), error = %s
                WHERE id = %s
                """,
                (error[:2000], refresh_id),
            )
            connection.execute(
                """
                UPDATE market_refresh_state SET lock_owner = NULL, locked_until = NULL
                WHERE singleton = true AND lock_owner = %s
                """,
                (refresh_id,),
            )

    def load_current(self) -> StoredMarket | None:
        self._ensure_schema()
        with self._connect() as connection:
            refresh = connection.execute(
                """
                SELECT r.id, r.generated_at, r.completed_at, r.sources
                FROM market_refresh_state s
                JOIN market_refreshes r ON r.id = s.current_refresh_id
                WHERE s.singleton = true AND r.status = 'succeeded'
                """
            ).fetchone()
            if not refresh:
                return None
            issue_rows = connection.execute(
                "SELECT * FROM market_issues WHERE refresh_id = %s ORDER BY position",
                (refresh["id"],),
            ).fetchall()
            detail_rows = connection.execute(
                """
                SELECT issue_key, scope, sr_no, category, shares_offered, shares_bid, times
                FROM subscription_details WHERE refresh_id = %s
                ORDER BY issue_key, scope, position
                """,
                (refresh["id"],),
            ).fetchall()
            early_rows = connection.execute(
                "SELECT payload FROM early_gmp_records WHERE refresh_id = %s ORDER BY position",
                (refresh["id"],),
            ).fetchall()

        details: dict[tuple[str, str], list[dict]] = {}
        for row in detail_rows:
            details.setdefault((row["issue_key"], row["scope"]), []).append(
                {
                    "srNo": row["sr_no"],
                    "category": row["category"],
                    "sharesOffered": row["shares_offered"],
                    "sharesBid": row["shares_bid"],
                    "times": row["times"],
                }
            )
        issues = [_issue_from_row(row, details) for row in issue_rows]
        generated_at = refresh["generated_at"] or refresh["completed_at"]
        payload = {
            "generatedAt": generated_at.isoformat().replace("+00:00", "Z"),
            "sources": refresh["sources"] or {},
            "earlyGmp": [row["payload"] for row in early_rows],
            "ipos": issues,
        }
        return StoredMarket(payload=payload, completed_at=refresh["completed_at"])

    def load_analysis(
        self, issue_key: str, fingerprint: str | None = None
    ) -> dict | None:
        self._ensure_schema()
        where = "issue_key = %s"
        parameters: list[str] = [issue_key]
        if fingerprint:
            where += " AND input_fingerprint = %s"
            parameters.append(fingerprint)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT issue_key, company_name, generated_at, market_generated_at,
                       model, report
                FROM ipo_analysis_reports
                WHERE {where}
                ORDER BY generated_at DESC LIMIT 1
                """,
                parameters,
            ).fetchone()
        return dict(row) if row else None

    def start_analysis(self, issue_key: str, fingerprint: str, force: bool = False):
        """Claim a generation lease with per-issue spend protection."""
        self._ensure_schema()
        token = uuid.uuid4()
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO ipo_analysis_state(
                    issue_key, lock_token, input_fingerprint, locked_until
                ) VALUES (%s, %s, %s, now() + interval '5 minutes')
                ON CONFLICT (issue_key) DO UPDATE
                SET lock_token = EXCLUDED.lock_token,
                    input_fingerprint = EXCLUDED.input_fingerprint,
                    locked_until = EXCLUDED.locked_until
                WHERE (ipo_analysis_state.locked_until IS NULL
                       OR ipo_analysis_state.locked_until < now())
                  AND (ipo_analysis_state.last_generated_at IS NULL
                       OR ipo_analysis_state.last_generated_at < now()
                          - CASE WHEN %s THEN interval '30 minutes'
                                 ELSE interval '15 minutes' END)
                RETURNING lock_token
                """,
                (issue_key, token, fingerprint, force),
            ).fetchone()
        return token if row else None

    def save_analysis(
        self,
        token,
        issue_key: str,
        company_name: str,
        fingerprint: str,
        model: str,
        market_generated_at: str,
        report: dict,
        usage: dict,
    ) -> dict:
        self._ensure_schema()
        report_id = uuid.uuid4()
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO ipo_analysis_reports(
                    id, issue_key, company_name, input_fingerprint, model,
                    market_generated_at, report, usage
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (issue_key, input_fingerprint) DO UPDATE
                SET company_name = EXCLUDED.company_name,
                    model = EXCLUDED.model,
                    generated_at = now(),
                    market_generated_at = EXCLUDED.market_generated_at,
                    report = EXCLUDED.report,
                    usage = EXCLUDED.usage
                RETURNING issue_key, company_name, generated_at,
                          market_generated_at, model, report
                """,
                (
                    report_id,
                    issue_key,
                    company_name,
                    fingerprint,
                    model,
                    market_generated_at,
                    Jsonb(report),
                    Jsonb(usage),
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE ipo_analysis_state
                SET lock_token = NULL, locked_until = NULL, last_generated_at = now()
                WHERE issue_key = %s AND lock_token = %s
                """,
                (issue_key, token),
            )
        return dict(row)

    def fail_analysis(self, issue_key: str, token) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ipo_analysis_state SET lock_token = NULL, locked_until = NULL
                WHERE issue_key = %s AND lock_token = %s
                """,
                (issue_key, token),
            )


def _issue_from_row(row: dict, details: dict) -> dict:
    price = (
        None
        if row["price_min"] is None and row["price_max"] is None
        else {"min": row["price_min"], "max": row["price_max"]}
    )
    gmp = (
        None
        if row["gmp_value"] is None and row["gmp_percent"] is None
        else {"value": row["gmp_value"], "percent": row["gmp_percent"]}
    )
    nse_details = details.get((row["issue_key"], "nse"), [])
    consolidated = details.get((row["issue_key"], "consolidated"), [])
    subscription = None
    if row["subscription_total"] is not None or nse_details or consolidated:
        subscription = {
            "source": "NSE Consolidated Bid Details",
            "totalTimes": row["subscription_total"],
            "updatedAt": row["subscription_updated_at"],
            "nseBidDetails": nse_details,
            "consolidatedBidDetails": consolidated,
        }
    return {
        "issueKey": row["issue_key"],
        "companyName": row["company_name"],
        "platform": row["platform"],
        "exchanges": row["exchanges"],
        "status": row["status"],
        "openDate": row["open_date"],
        "closeDate": row["close_date"],
        "listingDate": row["listing_date"],
        "priceBand": price,
        "lotSize": row["lot_size"],
        "faceValue": row["face_value"],
        "issueSize": row["issue_size"],
        "gmp": gmp,
        "gmpUpdatedOn": row["gmp_updated_on"],
        "detailUrl": row["detail_url"],
        "subscription": subscription,
    }


def _key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _text(value) -> str | None:
    return None if value is None else str(value)
