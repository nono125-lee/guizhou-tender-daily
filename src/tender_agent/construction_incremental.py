from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Shanghai")
OVERLAP_HOURS = 6
BOOTSTRAP_DAYS = 30
WEEKLY_BACKFILL_DAYS = 14
MONTHLY_BACKFILL_DAYS = 45
STATE_RETENTION_DAYS = 60
FAILURE_RETENTION_DAYS = 7


def empty_state() -> dict:
    return {"version": 1, "sources": {}}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    return {**empty_state(), **state}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_source_state(state: dict, source_id: str) -> dict:
    return state.setdefault("sources", {}).setdefault(
        source_id,
        {
            "last_success_at": "",
            "last_weekly_backfill_at": "",
            "last_monthly_backfill_at": "",
            "processed_ids": {},
            "failed_ids": {},
            "projects": {},
            "detail_fingerprints": {},
        },
    )


def _datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def collection_window(source_state: dict, now: datetime) -> tuple[datetime, str]:
    now = now.astimezone(TIMEZONE)
    last_success = _datetime(source_state.get("last_success_at", ""))
    last_weekly = _datetime(source_state.get("last_weekly_backfill_at", ""))
    last_monthly = _datetime(source_state.get("last_monthly_backfill_at", ""))
    if not last_success:
        return now - timedelta(days=BOOTSTRAP_DAYS), "bootstrap"
    if not last_monthly or now - last_monthly >= timedelta(days=30):
        return now - timedelta(days=MONTHLY_BACKFILL_DAYS), "monthly"
    if not last_weekly or now - last_weekly >= timedelta(days=7):
        return now - timedelta(days=WEEKLY_BACKFILL_DAYS), "weekly"
    return last_success - timedelta(hours=OVERLAP_HOURS), "incremental"


def should_process(source_state: dict, notice_id: str) -> bool:
    notice_id = str(notice_id)
    if notice_id in source_state.get("failed_ids", {}):
        return True
    record = source_state.get("processed_ids", {}).get(notice_id, {})
    return not record or record.get("status") == "unlinked_change"


def record_processed(
    source_state: dict,
    notice_id: str,
    *,
    status: str,
    release_at: str = "",
    project_code: str = "",
    url: str = "",
) -> None:
    notice_id = str(notice_id)
    source_state.setdefault("processed_ids", {})[notice_id] = {
        "status": status,
        "release_at": release_at,
        "project_code": project_code,
        "url": url,
    }
    source_state.setdefault("failed_ids", {}).pop(notice_id, None)


def record_failure(
    source_state: dict,
    notice_id: str,
    listing: dict,
    error: Exception,
    now: datetime,
) -> None:
    notice_id = str(notice_id)
    old = source_state.setdefault("failed_ids", {}).get(notice_id, {})
    source_state["failed_ids"][notice_id] = {
        "attempts": int(old.get("attempts", 0)) + 1,
        "first_failed_at": old.get("first_failed_at") or now.isoformat(),
        "last_error": type(error).__name__,
        "last_attempt_at": now.isoformat(),
        "listing": listing,
    }


def retry_listings(source_state: dict) -> list[dict]:
    return [
        record["listing"]
        for record in source_state.get("failed_ids", {}).values()
        if record.get("listing")
    ]


def record_project(
    source_state: dict,
    project_code: str,
    *,
    url: str,
    notice_id: str,
) -> None:
    if not project_code:
        return
    source_state.setdefault("projects", {})[project_code] = {
        "url": url,
        "notice_id": str(notice_id),
    }


def detail_fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def complete_source(source_state: dict, now: datetime, mode: str) -> None:
    timestamp = now.astimezone(TIMEZONE).isoformat()
    source_state["last_success_at"] = timestamp
    source_state["last_mode"] = mode
    if mode in {"bootstrap", "weekly", "monthly"}:
        source_state["last_weekly_backfill_at"] = timestamp
    if mode in {"bootstrap", "monthly"}:
        source_state["last_monthly_backfill_at"] = timestamp
    prune_state(source_state, now)


def prune_state(source_state: dict, now: datetime) -> None:
    cutoff = now.astimezone(TIMEZONE) - timedelta(days=STATE_RETENTION_DAYS)
    kept = {}
    for notice_id, record in source_state.get("processed_ids", {}).items():
        release = _datetime(record.get("release_at", ""))
        if not release or release >= cutoff:
            kept[notice_id] = record
    source_state["processed_ids"] = kept
    fingerprints = source_state.get("detail_fingerprints", {})
    source_state["detail_fingerprints"] = {
        notice_id: value
        for notice_id, value in fingerprints.items()
        if notice_id in kept
    }
    failure_cutoff = now.astimezone(TIMEZONE) - timedelta(
        days=FAILURE_RETENTION_DAYS
    )
    source_state["failed_ids"] = {
        notice_id: record
        for notice_id, record in source_state.get("failed_ids", {}).items()
        if (
            not _datetime(record.get("first_failed_at", ""))
            or _datetime(record.get("first_failed_at", "")) >= failure_cutoff
        )
    }
