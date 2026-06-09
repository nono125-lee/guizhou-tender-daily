from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
MARKER_RE = re.compile(
    r"<!--\s*TENDER_FEEDBACK_JSON\s*(.*?)\s*-->",
    re.DOTALL,
)
ALLOWED_FIELDS = {
    "title",
    "budget",
    "buyer",
    "agency",
    "bid_deadline",
    "registration_period",
    "source_name",
}
FIELD_LABELS = {
    "title": "项目名称",
    "budget": "预算",
    "buyer": "采购人",
    "agency": "采购代理机构",
    "bid_deadline": "投标截止时间",
    "registration_period": "报名日期",
    "source_name": "信息源名称",
}


class FeedbackConflict(ValueError):
    pass


def empty_rules() -> dict:
    return {
        "version": 1,
        "updated_at": "",
        "items": {},
        "summary": {
            "confirmed": 0,
            "excluded": 0,
            "corrected": 0,
            "correction_fields": {},
            "exclusion_reasons": [],
        },
        "processed_event_ids": [],
    }


def load_rules(path: Path | None = None) -> dict:
    target = path or ROOT / "config/feedback_rules.json"
    if not target.exists():
        return empty_rules()
    rules = json.loads(target.read_text(encoding="utf-8"))
    return {**empty_rules(), **rules}


def parse_feedback_body(body: str) -> list[dict]:
    match = MARKER_RE.search(body or "")
    if not match:
        raise ValueError("反馈单缺少可识别的数据。")
    payload = json.loads(match.group(1))
    events = payload.get("events", [])
    if not isinstance(events, list) or not events:
        raise ValueError("反馈单中没有反馈记录。")
    return events


def _event_key(event: dict) -> str:
    item = event.get("item") or {}
    url = str(event.get("url") or item.get("url") or "").strip()
    if not url:
        raise ValueError("反馈记录缺少公告网址。")
    return url


def _validate_event(event: dict) -> None:
    if not str(event.get("id", "")).strip():
        raise ValueError("反馈记录缺少事件编号。")
    action = event.get("action")
    if action not in {"confirm", "exclude", "correct"}:
        raise ValueError(f"无法识别的反馈动作：{action}")
    _event_key(event)
    if action == "exclude" and not str(event.get("reason", "")).strip():
        raise ValueError("排除反馈必须填写原因。")
    if action == "correct":
        field = event.get("field")
        if field not in ALLOWED_FIELDS:
            raise ValueError(f"不允许纠正字段：{field}")
        if not str(event.get("new_value", "")).strip():
            raise ValueError(f"{FIELD_LABELS[field]}的纠正内容不能为空。")


def summarize_rules(rules: dict) -> None:
    records = list(rules.get("items", {}).values())
    correction_fields = Counter()
    reasons = Counter()
    for record in records:
        correction_fields.update(record.get("corrections", {}).keys())
        reason = str(record.get("exclude_reason", "")).strip()
        if reason:
            reasons[reason] += 1
    rules["summary"] = {
        "confirmed": sum(r.get("status") == "confirmed" for r in records),
        "excluded": sum(r.get("status") == "excluded" for r in records),
        "corrected": sum(bool(r.get("corrections")) for r in records),
        "correction_fields": dict(correction_fields),
        "exclusion_reasons": [
            {"reason": reason, "count": count}
            for reason, count in reasons.most_common()
        ],
    }


def apply_events(rules: dict, events: list[dict], now: str | None = None) -> dict:
    result = copy.deepcopy(rules)
    result.setdefault("items", {})
    processed = set(result.get("processed_event_ids", []))
    timestamp = now or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    batch_statuses: dict[str, set[str]] = {}

    for event in events:
        _validate_event(event)
        event_id = str(event["id"])
        if event_id in processed:
            continue
        url = _event_key(event)
        action = event["action"]
        if action in {"confirm", "exclude"}:
            batch_statuses.setdefault(url, set()).add(action)

    conflicting = [
        url for url, statuses in batch_statuses.items() if len(statuses) > 1
    ]
    if conflicting:
        raise FeedbackConflict(
            "同一项目同时出现确认和排除，请再次判断：" + "、".join(conflicting)
        )

    for event in events:
        event_id = str(event["id"])
        if event_id in processed:
            continue
        url = _event_key(event)
        action = event["action"]
        item = event.get("item") or {}
        record = result["items"].setdefault(
            url,
            {
                "url": url,
                "original_title": item.get("title", ""),
                "status": "",
                "exclude_reason": "",
                "corrections": {},
                "item_snapshot": item,
                "history": [],
            },
        )
        old_status = record.get("status", "")
        new_status = {
            "confirm": "confirmed",
            "exclude": "excluded",
        }.get(action, old_status)
        if old_status and new_status and old_status != new_status:
            raise FeedbackConflict(
                f"“{record.get('original_title') or url}”此前为"
                f"{'有效' if old_status == 'confirmed' else '排除'}，"
                f"本次判断相反，需要再次确认。"
            )
        if item:
            record["item_snapshot"] = {**record.get("item_snapshot", {}), **item}
            record["original_title"] = (
                record.get("original_title") or item.get("title", "")
            )
        if action == "confirm":
            record["status"] = "confirmed"
            record["exclude_reason"] = ""
        elif action == "exclude":
            record["status"] = "excluded"
            record["exclude_reason"] = str(event["reason"]).strip()
        else:
            record.setdefault("corrections", {})[event["field"]] = str(
                event["new_value"]
            ).strip()
        record.setdefault("history", []).append(
            {
                key: event.get(key)
                for key in (
                    "id",
                    "action",
                    "field",
                    "old_value",
                    "new_value",
                    "reason",
                    "created_at",
                )
                if event.get(key) not in (None, "")
            }
        )
        record["updated_at"] = timestamp
        processed.add(event_id)

    result["processed_event_ids"] = sorted(processed)
    result["updated_at"] = timestamp
    summarize_rules(result)
    return result


def apply_rules_to_payload(payload: dict, rules: dict) -> None:
    records = rules.get("items", {})
    by_url = {
        item.get("url", ""): item
        for item in payload.get("items", [])
        if item.get("url")
    }
    for url, record in records.items():
        if record.get("status") == "confirmed" and url not in by_url:
            snapshot = copy.deepcopy(record.get("item_snapshot") or {})
            if snapshot:
                snapshot["url"] = url
                by_url[url] = snapshot

    kept = []
    for url, item in by_url.items():
        record = records.get(url)
        if not record:
            kept.append(item)
            continue
        for field, value in record.get("corrections", {}).items():
            item[field] = value
        item["review_status"] = record.get("status", "")
        item["review_note"] = record.get("exclude_reason", "")
        item["corrected_fields"] = sorted(record.get("corrections", {}))
        if record.get("status") != "excluded":
            kept.append(item)
    payload["items"] = kept


def write_public_state(rules: dict, path: Path) -> None:
    state = {
        "updated_at": rules.get("updated_at", ""),
        "processed_event_ids": rules.get("processed_event_ids", []),
        "summary": {
            key: rules.get("summary", {}).get(key, 0)
            for key in ("confirmed", "excluded", "corrected")
        },
    }
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _result_markdown(events: list[dict], rules: dict) -> str:
    counts = Counter(event["action"] for event in events)
    corrections = [
        f"- {event.get('item', {}).get('title', event.get('url'))}："
        f"{FIELD_LABELS[event['field']]}改为“{event['new_value']}”"
        for event in events
        if event["action"] == "correct"
    ]
    lines = [
        "反馈已处理并纳入后续标讯更新约束。",
        "",
        f"- 确认有效：{counts['confirm']} 条",
        f"- 排除无效：{counts['exclude']} 条",
        f"- 字段纠正：{counts['correct']} 项",
        f"- 当前累计确认：{rules['summary']['confirmed']} 条",
        f"- 当前累计排除：{rules['summary']['excluded']} 条",
    ]
    if corrections:
        lines.extend(["", "本次纠正：", *corrections])
    return "\n".join(lines)


def ingest(args: argparse.Namespace) -> int:
    event_payload = json.loads(args.event.read_text(encoding="utf-8"))
    events = parse_feedback_body(event_payload.get("issue", {}).get("body", ""))
    payload = json.loads(args.latest.read_text(encoding="utf-8"))
    current_by_url = {
        item.get("url", ""): item
        for item in payload.get("items", [])
        if item.get("url")
    }
    for event in events:
        url = _event_key(event)
        event["item"] = {
            **current_by_url.get(url, {}),
            **(event.get("item") or {}),
        }
    rules = load_rules(args.rules)
    try:
        updated_rules = apply_events(rules, events)
    except FeedbackConflict as error:
        args.result.write_text(
            "这批反馈存在需要再次判断的冲突，系统没有自动修改：\n\n"
            f"{error}\n",
            encoding="utf-8",
        )
        return 2

    apply_rules_to_payload(payload, updated_rules)
    payload["updated_at"] = updated_rules["updated_at"]
    payload.setdefault("stats", {})["total"] = len(payload.get("items", []))
    payload["stats"]["feedback_confirmed"] = updated_rules["summary"]["confirmed"]
    payload["stats"]["feedback_excluded"] = updated_rules["summary"]["excluded"]
    payload["stats"]["feedback_corrected"] = updated_rules["summary"]["corrected"]
    args.rules.write_text(
        json.dumps(updated_rules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.latest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_public_state(updated_rules, args.public_state)
    args.result.write_text(
        _result_markdown(events, updated_rules),
        encoding="utf-8",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="处理网页标讯人工反馈")
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument(
        "--rules",
        type=Path,
        default=ROOT / "config/feedback_rules.json",
    )
    parser.add_argument(
        "--latest",
        type=Path,
        default=ROOT / "site/data/latest.json",
    )
    parser.add_argument(
        "--public-state",
        type=Path,
        default=ROOT / "site/data/feedback-state.json",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=ROOT / ".feedback-result.md",
    )
    return parser


def main() -> int:
    return ingest(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
