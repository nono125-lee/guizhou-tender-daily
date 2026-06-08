from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .repository import Repository


def export_public_snapshot(
    repository: Repository,
    output: str | Path,
    limit: int = 200,
) -> dict:
    rows = repository.connection.execute(
        """
        SELECT collected_at, title, url, budget, summary, location, buyer,
               bid_deadline, registration_deadline, matched_keywords
        FROM tenders
        WHERE region_status = 'included'
          AND matched_keywords != '[]'
          AND substr(collected_at, 1, 10) <= date('now')
        ORDER BY substr(collected_at, 1, 10) DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["published_at"] = item.pop("collected_at")
        item["matched_keywords"] = json.loads(item["matched_keywords"])
        item["source_name"] = _source_name(item["url"])
        items.append(item)
    payload = {
        "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "coverage": "贵州省招标投标公共服务平台及历史已核实记录",
        "items": items,
        "stats": {
            "total": len(items),
            "sources": len({item["source_name"] for item in items}),
        },
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _source_name(url: str) -> str:
    if "ztb.guizhou.gov.cn" in url:
        return "贵州省招标投标公共服务平台"
    if "zcygov.cn" in url:
        return "政采云"
    if "tobacco.com.cn" in url:
        return "烟草行业采购平台"
    return "其他公开来源"

