from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors.eqyzc_construction import collect as collect_eqyzc
from .collectors.ggzy_construction import collect as collect_ggzy
from .collectors.ztb_construction import collect as collect_ztb
from .construction_rules import load_config
from .normalize import normalized_title


ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site/construction"
LATEST = SITE / "data/latest.json"
STATE = SITE / "data/ztb-state.json"
SOURCES = ROOT / "config/construction_sources.json"


def update() -> dict:
    config = load_config()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    previous = (
        json.loads(LATEST.read_text(encoding="utf-8"))
        if LATEST.exists()
        else {"items": []}
    )
    warnings = []
    items = []
    for source in sources:
        if source["collector"] not in {"ggzy", "eqyzc"}:
            continue
        try:
            collector = collect_ggzy if source["collector"] == "ggzy" else collect_eqyzc
            items.extend(collector(config, [source]))
        except Exception as error:
            warnings.append(f"{source['name']}采集异常：{type(error).__name__}")
    try:
        items.extend(collect_ztb(config, STATE))
    except Exception as error:
        warnings.append(
            f"贵州省招标投标公共服务平台采集异常：{type(error).__name__}"
        )
    by_url = {
        item.get("url"): item
        for item in previous.get("items", [])
        if item.get("url")
    }
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date().isoformat()
    for item in items:
        old = by_url.get(item["url"])
        item["first_seen_at"] = (
            old.get("first_seen_at")
            if old
            else now.isoformat()
        )
        item["new_on_date"] = old.get("new_on_date", today) if old else today
        item["is_new"] = item["new_on_date"] == today
        by_url[item["url"]] = item
    cutoff = now.date() - timedelta(days=45)
    recent = [
        item
        for item in by_url.values()
        if item.get("published_at")
        and datetime.fromisoformat(item["published_at"][:10]).date() >= cutoff
    ]
    deduplicated = {}
    for item in recent:
        name = item.get("project_name") or item.get("title", "")
        name = re.sub(
            r"(?:招标|采购|询比|磋商|谈判)(?:采购)?公告$",
            "",
            name,
        )
        key = normalized_title(name)
        old = deduplicated.get(key)
        score = (
            bool(item.get("budget"))
            + bool(item.get("agency") and item.get("agency") != "公告未载明")
            + bool(item.get("bid_deadline"))
            + bool(item.get("registration_period"))
        )
        old_score = (
            bool(old.get("budget"))
            + bool(old.get("agency") and old.get("agency") != "公告未载明")
            + bool(old.get("bid_deadline"))
            + bool(old.get("registration_period"))
            if old
            else -1
        )
        if not old or score > old_score:
            deduplicated[key] = item
    merged = list(deduplicated.values())
    merged.sort(
        key=lambda item: (item.get("published_at", ""), item.get("url", "")),
        reverse=True,
    )
    for item in merged:
        item["buyer"] = item.get("buyer") or "公告未载明"
        item["agency"] = item.get("agency") or "公告未载明"
    payload = {
        "updated_at": now.isoformat(),
        "coverage": "贵州省施工类标讯资格条件专项筛选",
        "warnings": warnings,
        "items": merged,
        "stats": {
            "total": len(merged),
            "new_today": sum(item.get("is_new", False) for item in merged),
            "sources": len({item.get("source_name") for item in merged}),
        },
    }
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    payload = update()
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
