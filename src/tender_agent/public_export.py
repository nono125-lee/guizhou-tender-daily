from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .repository import Repository


ROOT = Path(__file__).resolve().parents[2]
PARTIAL_DATE_RE = re.compile(
    r"^(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"(?:\s+(?P<hour>\d{1,2})[：:](?P<minute>\d{2}))?$"
)
CHINESE_DATE_RE = re.compile(
    r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:\s*(?P<hour>\d{1,2})[：:时](?P<minute>\d{1,2})?)?"
)


def load_source_names(path: str | Path | None = None) -> dict[str, str]:
    source = Path(path) if path else ROOT / "config/source_names.json"
    return json.loads(source.read_text(encoding="utf-8"))


def normalize_date(value: str, reference_date: str, include_time: bool) -> str:
    text = (value or "").strip().strip("\"'")
    if not text:
        return ""
    chinese = CHINESE_DATE_RE.search(text)
    if chinese:
        date_text = (
            f"{int(chinese.group('year')):04d}-"
            f"{int(chinese.group('month')):02d}-"
            f"{int(chinese.group('day')):02d}"
        )
        if include_time and chinese.group("hour"):
            minute = int(chinese.group("minute") or 0)
            return f"{date_text} {int(chinese.group('hour')):02d}:{minute:02d}"
        return date_text
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        if include_time:
            match = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?", text)
            if match:
                return (
                    f"{match.group(1)} {match.group(2)}"
                    if match.group(2)
                    else match.group(1)
                )
        return text[:10]
    partial = PARTIAL_DATE_RE.match(text)
    if partial and reference_date:
        year = int(reference_date[:4])
        reference_month = int(reference_date[5:7])
        month = int(partial.group("month"))
        if reference_month == 12 and month == 1:
            year += 1
        result = (
            f"{year:04d}-{month:02d}-"
            f"{int(partial.group('day')):02d}"
        )
        if include_time and partial.group("hour"):
            result += (
                f" {int(partial.group('hour')):02d}:"
                f"{int(partial.group('minute')):02d}"
            )
        return result
    return text


def source_name_for_url(
    url: str,
    source_names: dict[str, str] | None = None,
) -> str:
    host = urlsplit(url).netloc.lower()
    names = source_names or load_source_names()
    return names.get(host, host)


def normalize_public_item(
    item: dict,
    source_names: dict[str, str] | None = None,
) -> dict:
    result = dict(item)
    result["date_basis"] = result.get("date_basis") or "collected"
    published = normalize_date(result.get("published_at", ""), "", False)
    result["published_at"] = published
    result["bid_deadline"] = normalize_date(
        result.get("bid_deadline", ""), published, True
    )
    registration_end = normalize_date(
        result.get("registration_deadline", ""), published, False
    )
    result["registration_period"] = result.get("registration_period") or (
        f"{published}至{registration_end}"
        if published and registration_end
        else published or registration_end
    )
    result["source_name"] = source_name_for_url(
        result.get("url", ""), source_names
    )
    result["project_content"] = (
        result.get("project_content")
        or result.get("summary")
        or "请查看原公告了解具体内容。"
    )
    return result


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
          AND url IS NOT NULL
          AND url != ''
          AND substr(collected_at, 1, 10) <= date('now')
        ORDER BY substr(collected_at, 1, 10) DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    source_names = load_source_names()
    items = []
    for row in rows:
        item = dict(row)
        item["published_at"] = item.pop("collected_at")
        item["date_basis"] = "collected"
        item["matched_keywords"] = json.loads(item["matched_keywords"])
        items.append(normalize_public_item(item, source_names))
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
