from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..construction_incremental import (
    collection_window,
    complete_source,
    record_processed,
    should_process,
)
from ..construction_rules import (
    project_match_fields,
    qualification_matches,
    qualification_section,
)
from ..normalize import clean_text, matched_tender_keywords
from ..public_export import normalize_public_item
from .guizhou_ztb import (
    MONEY_RE,
    _deadline,
    _extract,
    _parties,
    _project_content,
    _registration_period,
)


BASE_URL = "https://www.plap.mil.cn"
LIST_API = f"{BASE_URL}/freecms-glht/rest/v1/notice/selectInfoForIndex.do"
SOURCE_NAME = "军队采购网"
SITE_ID = "404bb030-5be9-4070-85bd-c94b1473e8de"
GUIZHOU_REGION_CODE = "520000"
NOTICE_TYPES = "00101,001052,00105B,001031"
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")
TAG_RE = re.compile(r"<[^>]+>")


def _plain(value: str) -> str:
    return clean_text(html.unescape(TAG_RE.sub(" ", value or "")))


def _request_json(params: dict) -> dict:
    url = f"{LIST_API}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Accept": "application/json",
            "Referer": f"{BASE_URL}/",
        },
    )
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def _listings(page_size: int = 20, max_pages: int = 10):
    for page in range(1, max_pages + 1):
        data = _request_json(
            {
                "siteid": SITE_ID,
                "noticeType": NOTICE_TYPES,
                "regionCode": GUIZHOU_REGION_CODE,
                "currPage": page,
                "pageSize": page_size,
            }
        )
        rows = data.get("data", [])
        if not rows:
            break
        yield from rows
        if len(rows) < page_size:
            break


def _url(record: dict) -> str:
    page = clean_text(record.get("pageurl") or record.get("htmlpath"))
    if page.startswith("http"):
        return page
    if page.startswith("/freecms-glht"):
        return f"{BASE_URL}{page}"
    return f"{BASE_URL}/freecms-glht{page}"


def _allowed_project_content(text: str) -> str:
    value = _project_content(text)
    value = re.split(
        r"(?:[一二三四五六七八九十\d]+[、.．]\s*)?"
        r"(?:报价)?(?:申请人|供应商|投标人|响应人).{0,8}?"
        r"(?:资格要求|资格条件|资质要求|特殊资格要求)",
        value,
        maxsplit=1,
    )[0]
    return clean_text(value).strip("：:；;。 ")


def _recent(record: dict, cutoff) -> bool:
    try:
        return datetime.fromisoformat(clean_text(record.get("noticeTime"))[:10]).date() >= cutoff
    except ValueError:
        return True


def graphic_item(record: dict, keywords: list[str]) -> dict | None:
    title = _plain(record.get("title"))
    text = _plain(record.get("content") or record.get("description"))
    project_content = _allowed_project_content(text)
    matches = matched_tender_keywords(title, [project_content], keywords)
    if not matches:
        return None
    published_at = clean_text(record.get("noticeTime"))[:10]
    buyer, agency = _parties(text, clean_text(record.get("agentManageName")))
    return normalize_public_item(
        {
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": title,
            "url": _url(record),
            "budget": clean_text(record.get("budget")) or _extract(MONEY_RE, text),
            "summary": project_content,
            "project_content": project_content,
            "project_content_basis": "section-v3",
            "location": clean_text(record.get("regionName")) or "贵州省",
            "buyer": buyer,
            "agency": agency,
            "bid_deadline": _deadline(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
        }
    )


def construction_item(record: dict, config: dict) -> dict | None:
    title = _plain(record.get("title"))
    text = _plain(record.get("content") or record.get("description"))
    qualification = qualification_section(text)
    matches = qualification_matches(title, qualification, config)
    if not matches:
        return None
    published_at = clean_text(record.get("noticeTime"))[:10]
    buyer, agency = _parties(text, clean_text(record.get("agentManageName")))
    return normalize_public_item(
        {
            **project_match_fields(text),
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": title,
            "url": _url(record),
            "budget": clean_text(record.get("budget")) or _extract(MONEY_RE, text),
            "project_content": _allowed_project_content(text),
            "qualification_requirement": qualification,
            "location": clean_text(record.get("regionName")) or "贵州省",
            "buyer": buyer,
            "agency": agency,
            "bid_deadline": _deadline(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
            "source_notice_id": clean_text(record.get("noticeId") or record.get("id")),
        }
    )


def collect_graphic(
    keywords: list[str],
    existing_items: list[dict],
    lookback_days: int = 7,
) -> list[dict]:
    cutoff = datetime.now(PLATFORM_TIMEZONE).date() - timedelta(days=lookback_days)
    existing_urls = {item.get("url", "") for item in existing_items}
    items = {}
    for record in _listings():
        url = _url(record)
        if url in existing_urls or not _recent(record, cutoff):
            continue
        item = graphic_item(record, keywords)
        if item:
            items[item["url"]] = item
    return list(items.values())


def collect_construction(
    config: dict,
    source_state: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(PLATFORM_TIMEZONE)
    if source_state is None:
        start = now - timedelta(days=7)
        mode = "legacy"
    else:
        start, mode = collection_window(source_state, now)
    cutoff = start.date()
    items = {}
    for record in _listings():
        if not _recent(record, cutoff):
            continue
        notice_id = clean_text(record.get("noticeId") or record.get("id"))
        if source_state is not None and not should_process(source_state, notice_id):
            continue
        item = construction_item(record, config)
        if source_state is not None:
            record_processed(
                source_state,
                notice_id,
                status="matched" if item else "not_matched",
                release_at=clean_text(record.get("noticeTime")),
                url=_url(record),
            )
        if item:
            items[item["url"]] = item
    if source_state is not None:
        complete_source(source_state, now, mode)
    return list(items.values())
