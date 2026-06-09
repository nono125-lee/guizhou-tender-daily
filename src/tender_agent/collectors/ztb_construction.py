from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..construction_rules import qualification_matches, qualification_section
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


def collect(config: dict, state_path: Path, max_scan: int = 1200) -> list[dict]:
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"last_id": 888000}
    )
    last_id = int(state.get("last_id", 888000))
    highest = last_id
    misses = 0
    items = []
    for tender_id in range(last_id + 1, last_id + max_scan + 1):
        data = _fetch_json(f"{DETAIL_API}/{tender_id}", retries=0, timeout=4)
        if not data or not data.get("Title"):
            misses += 1
            if misses >= 30:
                break
            continue
        misses = 0
        highest = tender_id
        if data.get("BTypeCategory") != "affiche":
            continue
        title = clean_text(data.get("Title"))
        text = _plain_text(data.get("Content", ""))
        qualification = qualification_section(text)
        matches = qualification_matches(title, qualification, config)
        if not matches:
            continue
        published = clean_text(data.get("PublishDate"))
        buyer, agency = _parties(text, data.get("Source", ""))
        items.append(
            normalize_public_item(
                {
                    "published_at": published,
                    "date_basis": "official",
                    "title": title,
                    "project_name": title,
                    "url": f"{BASE_URL}/trade/bulletin/?id={tender_id}",
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
                }
            )
        )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_id": highest,
                "last_run_at": datetime.now(
                    ZoneInfo("Asia/Shanghai")
                ).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return items
