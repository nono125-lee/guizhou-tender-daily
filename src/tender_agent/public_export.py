from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .repository import Repository


ROOT = Path(__file__).resolve().parents[2]
CHINESE_DATE_RE = re.compile(
    r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:\s*(?P<hour>\d{1,2})[：:时](?P<minute>\d{1,2})?)?"
)


def load_source_names(path: str | Path | None = None) -> dict[str, str]:
    source = Path(path) if path else ROOT / "config/source_names.json"
    return json.loads(source.read_text(encoding="utf-8"))


def normalize_date(value: str, reference_date: str, include_time: bool) -> str:
    """Normalise date text to ISO-like format. Does NOT infer missing parts or shift timezones."""
    text = (value or "").strip().strip("\"'")
    if not text:
        return ""
    # Chinese date: 2026年6月20日 → 2026-06-20
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
    # Already ISO: 2026-06-20 or 2026-06-20 14:30
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?", text)
    if iso_match:
        if include_time and iso_match.group(2):
            return f"{iso_match.group(1)} {iso_match.group(2)}"
        return iso_match.group(1)
    # Dot-separated: 2026.06.20 → 2026-06-20
    dot_match = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})", text)
    if dot_match:
        return f"{dot_match.group(1)}-{dot_match.group(2)}-{dot_match.group(3)}"
    # Do NOT fill partial dates (e.g. "06-20") — that would be guessing the year.
    # Return the original text as-is.
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
        else registration_end
    )
    result["source_name"] = result.get("source_name") or source_name_for_url(
        result.get("url", ""), source_names
    )
    result["project_content"] = (
        result.get("project_content")
        or ""
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
               agency, bid_deadline, registration_deadline, matched_keywords
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
