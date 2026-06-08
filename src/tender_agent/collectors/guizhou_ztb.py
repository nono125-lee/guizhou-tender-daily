from __future__ import annotations

import html
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_keywords


BASE_URL = "http://ztb.guizhou.gov.cn"
DETAIL_API = f"{BASE_URL}/api/trade"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MONEY_RE = re.compile(
    r"(?:采购预算|预算金额|最高限价|项目预算)[：:\s]*"
    r"([¥￥]?\s?[\d,.]+\s*(?:万元|元)?)"
)
DEADLINE_PATTERNS = [
    re.compile(
        r"(?:响应文件|投标文件).{0,20}?(?:截止时间|递交截止时间)[：:\s]*"
        r"(\d{4}年\d{1,2}月\d{1,2}日[^，。；<]{0,20})"
    ),
    re.compile(
        r"(?:开标时间|投标截止时间)[：:\s]*"
        r"(\d{4}年\d{1,2}月\d{1,2}日[^，。；<]{0,20})"
    ),
]


def _plain_text(content: str) -> str:
    return SPACE_RE.sub(
        " ",
        html.unescape(TAG_RE.sub(" ", content or "")),
    ).strip()


def _fetch_json(url: str, retries: int = 2) -> dict | None:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Accept": "application/json",
        },
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except HTTPError as error:
            if error.code == 404:
                return None
        except (URLError, TimeoutError, json.JSONDecodeError):
            pass
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    return None


def _extract(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return clean_text(match.group(1)) if match else ""


def _deadline(text: str) -> str:
    for pattern in DEADLINE_PATTERNS:
        value = _extract(pattern, text)
        if value:
            return value
    return ""


def collect(
    keywords: list[str],
    state_path: str | Path,
    existing_path: str | Path,
    max_scan: int = 800,
    stop_after_misses: int = 120,
) -> dict:
    state_file = Path(state_path)
    existing_file = Path(existing_path)
    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {"last_id": 888140}
    )
    existing = (
        json.loads(existing_file.read_text(encoding="utf-8"))
        if existing_file.exists()
        else {"items": []}
    )
    seen_urls = {item["url"] for item in existing.get("items", [])}
    new_items: list[dict] = []
    last_id = int(state.get("last_id", 888140))
    highest_seen = last_id
    misses = 0

    for tender_id in range(last_id + 1, last_id + max_scan + 1):
        data = _fetch_json(f"{DETAIL_API}/{tender_id}")
        if not data or not data.get("Title"):
            misses += 1
            if misses >= stop_after_misses:
                break
            continue
        misses = 0
        highest_seen = tender_id
        if data.get("BTypeCategory") != "affiche":
            continue
        content = _plain_text(data.get("Content", ""))
        title = clean_text(data.get("Title"))
        matches = matched_keywords(f"{title} {content}", keywords)
        if not matches:
            continue
        publish_date = clean_text(data.get("PublishDate"))
        url = f"{BASE_URL}/trade/bulletin/?id={tender_id}"
        if url in seen_urls:
            continue
        new_items.append(
            {
                "published_at": publish_date,
                "title": title,
                "url": url,
                "budget": _extract(MONEY_RE, content),
                "summary": content[:180],
                "location": "贵州省",
                "buyer": clean_text(data.get("Source")),
                "bid_deadline": _deadline(content),
                "registration_deadline": "",
                "matched_keywords": matches,
                "source_name": "贵州省招标投标公共服务平台",
            }
        )
        seen_urls.add(url)

    cutoff = date.today() - timedelta(days=45)
    merged = new_items + existing.get("items", [])
    kept = []
    for item in merged:
        try:
            item_date = datetime.fromisoformat(item["published_at"][:10]).date()
        except (ValueError, TypeError, KeyError):
            item_date = date.today()
        if item_date >= cutoff:
            kept.append(item)
    kept.sort(
        key=lambda item: (item.get("published_at", ""), item.get("url", "")),
        reverse=True,
    )
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    payload = {
        "updated_at": now,
        "coverage": "贵州省招标投标公共服务平台公开公告；其他信息源持续接入",
        "items": kept,
        "stats": {
            "total": len(kept),
            "new_today": len(new_items),
            "sources": len({item["source_name"] for item in kept}),
        },
        "warnings": (
            []
            if highest_seen > last_id
            else ["本次未发现新公告编号，已保留上次成功数据"]
        ),
    }
    existing_file.parent.mkdir(parents=True, exist_ok=True)
    existing_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "last_id": highest_seen,
                "last_run_at": now,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return payload
