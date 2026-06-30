from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors.eqyzc_construction import collect as collect_eqyzc
from .collectors.ggzy_construction import collect as collect_ggzy
from .collectors.ztb_construction import collect as collect_ztb
from .collectors import asgq, plap
from .collectors.tobacco import collect_construction as collect_tobacco
from .construction_incremental import (
    get_source_state,
    load_state,
    save_state,
)
from .construction_rules import (
    load_config,
    qualification_matches,
    trim_qualification,
)
from .feedback import apply_rules_to_payload, load_rules
from .normalize import normalized_title


ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site/construction"
LATEST = SITE / "data/latest.json"
STATE = SITE / "data/ztb-state.json"
COLLECTOR_STATE = SITE / "data/collector-state.json"
SOURCES = ROOT / "config/construction_sources.json"
FEEDBACK_RULES = ROOT / "config/construction_feedback_rules.json"
CHANGE_FIELDS = (
    "budget",
    "project_content",
    "buyer",
    "agency",
    "bid_deadline",
    "registration_period",
    "fixed_asset_code",
    "approval_refs",
)


def _published_date(item: dict):
    try:
        return datetime.fromisoformat(item.get("published_at", "")[:10]).date()
    except (TypeError, ValueError):
        return None


def update() -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    config = load_config()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    collector_state = load_state(COLLECTOR_STATE)
    previous = (
        json.loads(LATEST.read_text(encoding="utf-8"))
        if LATEST.exists()
        else {"items": []}
    )
    feedback_rules = load_rules(FEEDBACK_RULES)
    feedback_records = feedback_rules.get("items", {})
    confirmed_urls = {
        url
        for url, record in feedback_records.items()
        if record.get("status") == "confirmed"
    }
    excluded_urls = {
        url
        for url, record in feedback_records.items()
        if record.get("status") == "excluded"
    }
    frozen_urls = confirmed_urls | excluded_urls
    warnings = []
    items = []
    for source in sources:
        if source["collector"] not in {"ggzy", "eqyzc", "asgq", "plap", "tobacco"}:
            continue
        working_state = copy.deepcopy(
            get_source_state(collector_state, source["id"])
        )
        try:
            if source["collector"] == "ggzy":
                collected = collect_ggzy(
                    config,
                    [source],
                    skip_urls=frozen_urls,
                    source_state=working_state,
                    now=now,
                )
            elif source["collector"] == "eqyzc":
                collected = collect_eqyzc(
                    config,
                    [source],
                    skip_urls=frozen_urls,
                    source_state=working_state,
                    now=now,
                )
            elif source["collector"] == "asgq":
                collected = asgq.collect_construction(
                    config,
                    source_state=working_state,
                    now=now,
                )
            elif source["collector"] == "plap":
                collected = plap.collect_construction(
                    config,
                    source_state=working_state,
                    now=now,
                )
            else:
                collected = collect_tobacco(
                    config,
                    source_state=working_state,
                    now=now,
                )
            items.extend(collected)
            collector_state["sources"][source["id"]] = working_state
        except Exception as error:
            warnings.append(f"{source['name']}采集异常：{type(error).__name__}")
    ztb_source = next(
        (
            source
            for source in sources
            if source["collector"] == "ztb"
        ),
        {"id": "ztb-guizhou"},
    )
    ztb_state = copy.deepcopy(
        get_source_state(collector_state, ztb_source["id"])
    )
    try:
        items.extend(
            collect_ztb(
                config,
                STATE,
                skip_urls=frozen_urls,
                source_state=ztb_state,
                now=now,
            )
        )
        collector_state["sources"][ztb_source["id"]] = ztb_state
    except Exception as error:
        warnings.append(
            f"贵州省招标投标公共服务平台采集异常：{type(error).__name__}"
        )
    save_state(COLLECTOR_STATE, collector_state)
    by_url = {
        item.get("url"): item
        for item in previous.get("items", [])
        if item.get("url") and item.get("url") not in excluded_urls
    }
    today = now.date().isoformat()
    refresh_cutoff = now.date() - timedelta(days=7)
    for item in items:
        if item["url"] in frozen_urls:
            continue
        if item.pop("_is_change", False):
            old = by_url.get(item["url"])
            if not old:
                continue
            for field in CHANGE_FIELDS:
                if item.get(field):
                    old[field] = item[field]
            old["last_change_at"] = (
                item.get("change_published_at") or now.date().isoformat()
            )
            old["last_change_notice_id"] = item.get("source_notice_id", "")
            continue
        published = _published_date(item)
        if not published:
            continue
        old = by_url.get(item["url"])
        if old and published < refresh_cutoff:
            continue
        item["first_seen_at"] = (
            old.get("first_seen_at")
            if old
            else now.isoformat()
        )
        item["new_on_date"] = old.get("new_on_date", today) if old else today
        item["is_new"] = item["new_on_date"] == today
        by_url[item["url"]] = item
    feedback_payload = {"items": list(by_url.values())}
    apply_rules_to_payload(feedback_payload, feedback_rules)
    cutoff = now.date() - timedelta(days=45)
    recent = []
    for item in feedback_payload["items"]:
        item["is_new"] = item.get("new_on_date") == today
        published = _published_date(item)
        if not published or published < cutoff:
            continue
        qualification = trim_qualification(
            item.get("qualification_requirement", "")
        )
        item["qualification_requirement"] = qualification
        if item.get("review_status") != "confirmed":
            matches = qualification_matches(
                item.get("project_name") or item.get("title", ""),
                qualification,
                config,
            )
            if not matches:
                continue
            item["matched_keywords"] = matches
        recent.append(item)
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
            "feedback_confirmed": feedback_rules["summary"]["confirmed"],
            "feedback_excluded": feedback_rules["summary"]["excluded"],
            "feedback_corrected": feedback_rules["summary"]["corrected"],
            "pending_retries": sum(
                len(source.get("failed_ids", {}))
                for source in collector_state.get("sources", {}).values()
            ),
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
