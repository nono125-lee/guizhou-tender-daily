from __future__ import annotations

import json
from datetime import datetime

from .repository import Repository


def build_daily_digest(
    repository: Repository,
    date_text: str | None = None,
    limit: int = 50,
) -> dict:
    selected_date = date_text or repository.latest_collection_date()
    if not selected_date:
        return {
            "date": "",
            "generated_at": datetime.now().astimezone().isoformat(),
            "total": 0,
            "items": [],
            "message": "暂无标讯数据",
        }
    rows = repository.daily_tenders(selected_date, limit=limit)
    items = []
    for row in rows:
        item = dict(row)
        item["matched_keywords"] = json.loads(item["matched_keywords"])
        items.append(item)
    return {
        "date": selected_date,
        "generated_at": datetime.now().astimezone().isoformat(),
        "total": len(items),
        "items": items,
        "message": f"{selected_date} 共 {len(items)} 条贵州图文广告相关标讯",
        "warnings": (
            [f"{repository.future_collection_date_count()} 条记录的采集日期晚于今天，已排除"]
            if repository.future_collection_date_count()
            else []
        ),
    }
