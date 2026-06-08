from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .importers import HistoricalTender, SourceAccount
from .normalize import canonical_url, tender_fingerprint


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS source_accounts (
    id INTEGER PRIMARY KEY,
    source_no TEXT,
    source_name TEXT NOT NULL,
    url TEXT NOT NULL,
    company TEXT,
    login_identity TEXT,
    username TEXT,
    password TEXT,
    notes TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source_name, url, company, username)
);
CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    collected_at TEXT,
    title TEXT NOT NULL,
    url TEXT,
    canonical_url TEXT,
    budget TEXT,
    summary TEXT,
    location TEXT,
    registration_fee TEXT,
    registration_deadline TEXT,
    buyer TEXT,
    contact TEXT,
    phone TEXT,
    agency TEXT,
    bid_deadline TEXT,
    submission_channel TEXT,
    submission_method TEXT,
    submission_place TEXT,
    industry_id TEXT NOT NULL DEFAULT 'graphic-advertising',
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    region_status TEXT NOT NULL DEFAULT 'review',
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);
CREATE TABLE IF NOT EXISTS push_log (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    openid_hash TEXT,
    template_id TEXT,
    status TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    openid TEXT NOT NULL UNIQUE,
    template_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()
        os.chmod(self.path, 0o600)

    def close(self) -> None:
        self.connection.close()

    def import_sources(self, accounts: list[SourceAccount]) -> int:
        inserted = 0
        for account in accounts:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO source_accounts (
                    source_no, source_name, url, company, login_identity,
                    username, password, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.source_no,
                    account.source_name,
                    account.url,
                    account.company,
                    account.login_identity,
                    account.username,
                    account.password,
                    account.notes,
                ),
            )
            inserted += cursor.rowcount
        self.connection.commit()
        return inserted

    def upsert_tender(
        self,
        tender: HistoricalTender,
        matched: list[str],
        region_status: str,
    ) -> bool:
        fingerprint = tender_fingerprint(
            tender.title, tender.url, tender.buyer, tender.bid_deadline
        )
        values = asdict(tender)
        cursor = self.connection.execute(
            """
            INSERT INTO tenders (
                fingerprint, collected_at, title, url, canonical_url, budget,
                summary, location, registration_fee, registration_deadline,
                buyer, contact, phone, agency, bid_deadline, submission_channel,
                submission_method, submission_place, matched_keywords,
                region_status
            ) VALUES (
                :fingerprint, :collected_at, :title, :url, :canonical_url,
                :budget, :summary, :location, :registration_fee,
                :registration_deadline, :buyer, :contact, :phone, :agency,
                :bid_deadline, :submission_channel, :submission_method,
                :submission_place, :matched_keywords, :region_status
            )
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen_at = CURRENT_TIMESTAMP,
                matched_keywords = excluded.matched_keywords,
                region_status = excluded.region_status
            """,
            {
                **values,
                "fingerprint": fingerprint,
                "canonical_url": canonical_url(tender.url),
                "matched_keywords": json.dumps(matched, ensure_ascii=False),
                "region_status": region_status,
            },
        )
        self.connection.commit()
        return cursor.rowcount > 0 and cursor.lastrowid is not None

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("source_accounts", "tenders"):
            result[table] = self.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        result["included_tenders"] = self.connection.execute(
            "SELECT COUNT(*) FROM tenders WHERE region_status = 'included'"
        ).fetchone()[0]
        result["review_tenders"] = self.connection.execute(
            "SELECT COUNT(*) FROM tenders WHERE region_status = 'review'"
        ).fetchone()[0]
        result["active_subscriptions"] = self.connection.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'"
        ).fetchone()[0]
        result["future_date_anomalies"] = self.future_collection_date_count()
        return result

    def latest_collection_date(self) -> str | None:
        row = self.connection.execute(
            """
            SELECT MAX(substr(collected_at, 1, 10))
            FROM tenders
            WHERE collected_at IS NOT NULL AND collected_at != ''
              AND substr(collected_at, 1, 10) <= ?
            """,
            (date.today().isoformat(),),
        ).fetchone()
        return row[0] if row else None

    def future_collection_date_count(self) -> int:
        return self.connection.execute(
            """
            SELECT COUNT(*)
            FROM tenders
            WHERE substr(collected_at, 1, 10) > ?
            """,
            (date.today().isoformat(),),
        ).fetchone()[0]

    def daily_tenders(self, date_text: str, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT title, url, budget, summary, location, buyer, bid_deadline,
                   registration_deadline, matched_keywords
            FROM tenders
            WHERE substr(collected_at, 1, 10) = ?
              AND region_status = 'included'
              AND matched_keywords != '[]'
            ORDER BY
              CASE WHEN bid_deadline = '' THEN 1 ELSE 0 END,
              bid_deadline ASC,
              id ASC
            LIMIT ?
            """,
            (date_text, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_subscription(
        self, openid: str, template_id: str, status: str = "active"
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO subscriptions (openid, template_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(openid) DO UPDATE SET
                template_id = excluded.template_id,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (openid, template_id, status),
        )
        self.connection.commit()
