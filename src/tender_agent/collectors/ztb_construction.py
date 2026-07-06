from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..construction_incremental import (
    collection_window,
    complete_source,
    detail_fingerprint,
    record_failure,
    record_processed,
    retry_listings,
    should_process,
)
from ..construction_rules import (
    project_match_fields,
    qualification_matches,
    qualification_section,
)
from ..normalize import clean_text
from ..public_export import normalize_public_item
from .guizhou_ztb import (
    BASE_URL,
    DETAIL_API,
    MONEY_RE,
    _deadline,
    _extract,
    _fetch_json,
    _parties,
    _plain_text,
    _project_content,
    _registration_period,
)


def collect(
    config: dict,
    state_path: Path,
    max_scan: int = 1200,
    skip_urls: set[str] | None = None,
    source_state: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"last_id": 888000}
    )
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if source_state is not None:
        last_id = int(source_state.get("last_id") or state.get("last_id", 888000))
        _, mode = collection_window(source_state, now)
    else:
        last_id = int(state.get("last_id", 888000))
        mode = "legacy"
    highest = last_id
    frontier_misses = 0
    items = []
    skipped = skip_urls or set()
    retry_ids = [
        int(listing["tender_id"])
        for listing in retry_listings(source_state or {})
        if listing.get("tender_id")
    ]
    if mode == "monthly":
        scan_start = max(1, last_id - 2000)
    elif mode == "weekly":
        scan_start = max(1, last_id - 500)
    else:
        scan_start = last_id + 1
    tender_ids = list(dict.fromkeys(retry_ids + list(
        range(scan_start, last_id + max_scan + 1)
    )))
    for tender_id in tender_ids:
        notice_id = str(tender_id)
        if (
            source_state is not None
            and tender_id <= last_id
            and not should_process(source_state, notice_id)
        ):
            continue
        try:
            data = _fetch_json(
                f"{DETAIL_API}/{tender_id}",
                retries=0,
                timeout=4,
                raise_on_error=True,
            )
        except RuntimeError as error:
            if tender_id > last_id:
                frontier_misses += 1
            if source_state is not None:
                record_failure(
                    source_state,
                    notice_id,
                    {"tender_id": tender_id},
                    error,
                    now,
                )
            if tender_id > last_id and frontier_misses >= 30:
                break
            continue
        if data is None:
            if tender_id > last_id:
                frontier_misses += 1
            if source_state is not None:
                if tender_id <= last_id:
                    record_processed(
                        source_state,
                        notice_id,
                        status="missing_notice",
                        release_at=now.isoformat(),
                    )
                else:
                    source_state.setdefault("failed_ids", {}).pop(
                        notice_id, None
                    )
            if tender_id > last_id and frontier_misses >= 30:
                break
            continue
        if not isinstance(data, dict) or not data.get("Title"):
            if tender_id > last_id:
                frontier_misses += 1
            if source_state is not None:
                record_failure(
                    source_state,
                    notice_id,
                    {"tender_id": tender_id},
                    RuntimeError("公告详情缺少标题"),
                    now,
                )
            if tender_id > last_id and frontier_misses >= 30:
                break
            continue
        frontier_misses = 0
        highest = tender_id
        published = clean_text(data.get("PublishDate"))
        release_at = (
            f"{published[:10]}T00:00:00+08:00"
            if published
            else ""
        )
        if data.get("BTypeCategory") != "affiche":
            if source_state is not None:
                record_processed(
                    source_state,
                    notice_id,
                    status="ignored_notice_type",
                    release_at=release_at,
                )
            continue
        url = f"{BASE_URL}/trade/bulletin/?id={tender_id}"
        if url in skipped:
            if source_state is not None:
                record_processed(
                    source_state,
                    notice_id,
                    status="frozen",
                    release_at=release_at,
                    url=url,
                )
            continue
        title = clean_text(data.get("Title"))
        text = _plain_text(data.get("Content", ""))
        qualification = qualification_section(text)
        matches = qualification_matches(title, qualification, config)
        if not matches:
            if source_state is not None:
                source_state.setdefault("detail_fingerprints", {})[
                    notice_id
                ] = detail_fingerprint(data)
                record_processed(
                    source_state,
                    notice_id,
                    status="not_matched",
                    release_at=release_at,
                    url=url,
                )
            continue
        buyer, agency = _parties(text, data.get("Source", ""))
        items.append(
            normalize_public_item(
                {
                    **project_match_fields(text),
                    "published_at": published,
                    "date_basis": "official",
                    "title": title,
                    "project_name": title,
                    "url": url,
                    "budget": _extract(MONEY_RE, text),
                    "project_content": _project_content(text),
                    "qualification_requirement": qualification,
                    "location": "贵州省",
                    "buyer": buyer,
                    "agency": agency,
                    "bid_deadline": _deadline(text),
                    "registration_period": _registration_period(text, published),
                    "matched_keywords": matches,
                    "source_name": "贵州省招标投标公共服务平台",
                    "source_notice_id": notice_id,
                }
            )
        )
        if source_state is not None:
            source_state.setdefault("detail_fingerprints", {})[
                notice_id
            ] = detail_fingerprint(data)
            record_processed(
                source_state,
                notice_id,
                status="matched",
                release_at=release_at,
                url=url,
            )
    if source_state is not None:
        source_state["last_id"] = highest
        complete_source(source_state, now, mode)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_id": highest,
                "last_run_at": now.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return items
