from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WATCHLIST = ROOT / "config/priority_projects.json"
PUNCTUATION_RE = re.compile(r"[\s\-\u2014_\xb7,\uff0c\u3002:\uff1a;\uff1b()\uff08\uff09\[\]\u3010\u3011\u201c\u201d\"'\u3001/\\]+")
NOTICE_SUFFIXES = (
    "招标计划",
    "项目招标计划",
    "公开招标公告",
    "竞争性磋商公告",
    "采购公告",
    "施工招标公告",
    "招标公告",
    "公告",
)


def normalize_project_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = PUNCTUATION_RE.sub("", text)
    changed = True
    while changed:
        changed = False
        for suffix in NOTICE_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
    return text


def load_watchlist(path: Path = DEFAULT_WATCHLIST) -> dict:
    if not path.exists():
        return {"schema_version": 1, "projects": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
        raise ValueError("重点招标计划清单格式无效")
    return value


def write_watchlist(payload: dict, path: Path = DEFAULT_WATCHLIST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def add_project(project_name: str, fund_source: str, path: Path = DEFAULT_WATCHLIST) -> dict:
    name = project_name.strip()
    funds = fund_source.strip()
    if not name or not funds:
        raise ValueError("项目名称和资金来源均不能为空")
    payload = load_watchlist(path)
    key = normalize_project_name(name)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    projects = payload["projects"]
    for item in projects:
        if normalize_project_name(item.get("project_name")) == key:
            item["project_name"] = name
            item["fund_source"] = funds
            item["updated_at"] = now
            write_watchlist(payload, path)
            return item
    item = {
        "project_name": name,
        "fund_source": funds,
        "added_at": now,
    }
    projects.append(item)
    write_watchlist(payload, path)
    return item


def _public_plan(watched: dict, plan_items: list[dict]) -> dict:
    watched_name = normalize_project_name(watched.get("project_name"))
    candidates = [
        item
        for item in plan_items
        if normalize_project_name(item.get("project_name") or item.get("title"))
        == watched_name
    ]
    selected = max(
        candidates,
        key=lambda item: str(item.get("published_at") or ""),
        default={},
    )
    fields = (
        "published_at", "title", "project_name", "url", "buyer", "budget",
        "fund_source", "fund_source_tags", "fixed_asset_code", "approval",
        "project_content", "project_location", "source_notice_id",
    )
    plan = {field: selected.get(field) for field in fields}
    plan["project_name"] = watched.get("project_name")
    plan["fund_source"] = watched.get("fund_source")
    plan["user_watched"] = True
    return plan


def _notice_match(watched: dict, notice: dict) -> dict | None:
    plan_name = normalize_project_name(watched.get("project_name"))
    notice_name = normalize_project_name(notice.get("project_name") or notice.get("title"))
    if not plan_name or not notice_name:
        return None
    ratio = SequenceMatcher(None, plan_name, notice_name).ratio()
    shorter = min(len(plan_name), len(notice_name))
    contained = shorter >= 8 and (plan_name in notice_name or notice_name in plan_name)
    if plan_name == notice_name:
        confidence, evidence = 1.0, "用户重点项目与公告项目名称完全一致"
    elif contained:
        confidence, evidence = 0.96, "用户重点项目与公告项目名称为包含关系"
    elif ratio >= 0.82:
        confidence, evidence = round(ratio, 3), f"用户重点项目与公告名称相似度 {ratio:.1%}"
    else:
        return None
    return {
        "method": "user_watchlist+project_name",
        "methods": ["user_watchlist", "project_name"],
        "confidence": confidence,
        "match_level": "important",
        "review_required": False,
        "review_note": "该项目由用户指定为重点关注，请优先查看原公告。",
        "evidence": [evidence, f"资金来源：{watched.get('fund_source') or '未载明'}"],
        "similarities": {"project_name": round(ratio, 3)},
    }


def build_watchlist_matches(
    watchlist: dict,
    plan_items: list[dict],
    notice_payloads: list[dict],
) -> list[dict]:
    notices: dict[str, dict] = {}
    for payload in notice_payloads:
        for notice in payload.get("items", []):
            key = str(notice.get("url") or notice.get("source_notice_id") or "")
            if key:
                notices[key] = notice
    matches = []
    for watched in watchlist.get("projects", []):
        plan = _public_plan(watched, plan_items)
        project_key = normalize_project_name(watched.get("project_name"))
        for notice in notices.values():
            match = _notice_match(watched, notice)
            if not match:
                continue
            public_notice = dict(notice)
            public_notice.pop("contact", None)
            public_notice.pop("phone", None)
            matches.append(
                {
                    "plan_project_key": project_key,
                    "plan": plan,
                    "candidate_plans": [
                        {"plan_project_key": project_key, "plan": plan, "match": match}
                    ],
                    "notice": public_notice,
                    "match": match,
                    "priority_source": "user_watchlist",
                }
            )
    matches.sort(
        key=lambda item: str(item["notice"].get("published_at") or ""),
        reverse=True,
    )
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="维护用户重点招标计划清单")
    parser.add_argument("command", choices=["add"])
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--fund-source", required=True)
    parser.add_argument("--file", type=Path, default=DEFAULT_WATCHLIST)
    args = parser.parse_args(argv)
    item = add_project(args.project_name, args.fund_source, args.file)
    print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
