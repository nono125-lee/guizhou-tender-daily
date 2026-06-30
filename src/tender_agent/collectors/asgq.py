from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
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


BASE_URL = "https://asgq.etrading.cn"
LIST_API = f"{BASE_URL}/inteligentsearch_wz/rest/esinteligentsearch/getFullTextDataNew"
SOURCE_NAME = "“黔顺云采”集采平台"
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")
ORIGINAL_CATEGORIES = ("002001001", "002002001", "002003001", "002008001")
TAG_RE = re.compile(r"<[^>]+>")


def _plain(value: str) -> str:
    return clean_text(html.unescape(TAG_RE.sub(" ", value or "")))


def _request_json(payload: dict) -> dict:
    request = Request(
        LIST_API,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": f"{BASE_URL}/jyxx/002002/002002001/bussinessInfo.html",
        },
    )
    with urlopen(request, timeout=25) as response:
        result = json.loads(response.read().decode("utf-8-sig"))
    content = result.get("content")
    return json.loads(content) if isinstance(content, str) else result


def _payload(category: str, start: datetime, end: datetime, page: int, size: int) -> dict:
    return {
        "token": "",
        "pn": page * size,
        "rn": size,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title;infod",
        "cnum": "002",
        "sort": "{webdate:0}",
        "ssort": "title",
        "cl": 1000,
        "terminal": "",
        "condition": [
            {
                "equal": category,
                "fieldName": "categorynum",
                "isLike": "true",
                "likeType": "2",
            },
            {
                "equal": "安顺国企电子招投标平台",
                "fieldName": "infod",
                "isLike": "true",
                "likeType": "2",
            },
        ],
        "time": [
            {
                "fieldName": "webdate",
                "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {"fieldName": "youxiaodate", "startTime": "", "endTime": ""},
        ],
        "highlights": "title;content",
        "statistics": None,
        "unionCondition": None,
        "accuracy": "",
        "noParticiple": "0",
        "searchRange": None,
        "isBusiness": "1",
    }


def _listings(start: datetime, end: datetime, page_size: int = 20, max_pages: int = 10):
    for category in ORIGINAL_CATEGORIES:
        for page in range(max_pages):
            result = _request_json(_payload(category, start, end, page, page_size))
            records = result.get("result", {}).get("records", [])
            if not records:
                break
            yield from records
            if len(records) < page_size:
                break


def _url(record: dict) -> str:
    link = clean_text(record.get("linkurl"))
    return link if link.startswith("http") else f"{BASE_URL}{link}"


def _allowed_project_content(text: str) -> str:
    value = _project_content(text)
    value = re.split(
        r"(?:[一二三四五六七八九十\d]+[、.．]\s*)?"
        r"(?:申请人|供应商|投标人|响应人).{0,8}?"
        r"(?:资格要求|资格条件|资质要求|特殊资格要求)",
        value,
        maxsplit=1,
    )[0]
    return clean_text(value).strip("：:；;。 ")


def graphic_item(record: dict, keywords: list[str]) -> dict | None:
    title = _plain(record.get("title"))
    text = _plain(record.get("content"))
    project_content = _allowed_project_content(text)
    matches = matched_tender_keywords(title, [project_content], keywords)
    if not matches:
        return None
    published_at = clean_text(record.get("webdate"))[:10]
    buyer, agency = _parties(text, "")
    return normalize_public_item(
        {
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": title,
            "url": _url(record),
            "budget": _extract(MONEY_RE, text),
            "summary": project_content,
            "project_content": project_content,
            "project_content_basis": "section-v3",
            "location": "贵州省安顺市",
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
    text = _plain(record.get("content"))
    qualification = qualification_section(text)
    matches = qualification_matches(title, qualification, config)
    if not matches:
        return None
    published_at = clean_text(record.get("webdate"))[:10]
    buyer, agency = _parties(text, "")
    return normalize_public_item(
        {
            **project_match_fields(text),
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": title,
            "url": _url(record),
            "budget": _extract(MONEY_RE, text),
            "project_content": _allowed_project_content(text),
            "qualification_requirement": qualification,
            "location": "贵州省安顺市",
            "buyer": buyer,
            "agency": agency,
            "bid_deadline": _deadline(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
            "source_notice_id": clean_text(record.get("infoid")),
        }
    )


def collect_graphic(
    keywords: list[str],
    existing_items: list[dict],
    lookback_days: int = 7,
) -> list[dict]:
    now = datetime.now(PLATFORM_TIMEZONE)
    start = now - timedelta(days=lookback_days)
    existing_urls = {item.get("url", "") for item in existing_items}
    items = {}
    for record in _listings(start, now):
        url = _url(record)
        if url in existing_urls:
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
    items = {}
    for record in _listings(start, now):
        notice_id = clean_text(record.get("infoid") or record.get("id"))
        if source_state is not None and not should_process(source_state, notice_id):
            continue
        item = construction_item(record, config)
        if source_state is not None:
            record_processed(
                source_state,
                notice_id,
                status="matched" if item else "not_matched",
                release_at=clean_text(record.get("webdate")),
                url=_url(record),
            )
        if item:
            items[item["url"]] = item
    if source_state is not None:
        complete_source(source_state, now, mode)
    return list(items.values())
