from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_tender_keywords
from ..public_export import normalize_public_item
from .guizhou_ztb import (
    MONEY_RE,
    _deadline,
    _extract,
    _parties,
    _plain_text,
    _project_content,
    _registration_period,
)


LIST_API = "https://ggzy.guizhou.gov.cn/tradeInfo/es/list"
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _request(url: str, payload: dict | None = None) -> str:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Content-Type": "application/json;charset=UTF-8",
        },
    )
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def _page_listings(
    source: dict,
    start: datetime,
    end: datetime,
    page_size: int = 100,
    max_pages: int | None = None,
):
    page_num = 1
    while max_pages is None or page_num <= max_pages:
        payload = {
            "channelId": source["channel_id"],
            "pageNum": page_num,
            "pageSize": page_size,
            "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
        }
        listings = json.loads(_request(LIST_API, payload)).get("list", [])
        if not listings:
            break
        yield from listings
        if len(listings) < page_size:
            break
        page_num += 1


def _is_original_notice(listing: dict) -> bool:
    announcement = clean_text(listing.get("announcement"))
    title = clean_text(listing.get("docTitle"))
    if any(word in announcement + title for word in ("结果", "中标", "成交", "候选人", "变更", "澄清", "答疑", "计划")):
        return False
    return "公告" in announcement or "公告" in title


def _published_at(listing: dict) -> str:
    if not listing.get("docRelTime"):
        return ""
    return datetime.fromtimestamp(
        int(listing["docRelTime"]) / 1000,
        PLATFORM_TIMEZONE,
    ).date().isoformat()


def item_from_listing(
    source: dict,
    listing: dict,
    html_text: str,
    keywords: list[str],
) -> dict | None:
    text = _plain_text(html_text)
    title = clean_text(listing.get("docTitle"))
    project_content = _project_content(text)
    matches = matched_tender_keywords(title, [project_content], keywords)
    if not matches:
        return None
    published_at = _published_at(listing)
    buyer, agency = _parties(text, "")
    item = normalize_public_item(
        {
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": title,
            "url": listing.get("apiUrl", ""),
            "budget": _extract(MONEY_RE, text),
            "summary": project_content,
            "project_content": project_content,
            "project_content_basis": "section-v3",
            "location": clean_text(listing.get("docSourceName")) or "贵州省",
            "buyer": buyer,
            "agency": agency,
            "bid_deadline": _deadline(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": source["name"],
        }
    )
    item["source_name"] = source["name"]
    return item


def collect(
    keywords: list[str],
    existing_items: list[dict],
    sources: list[dict],
    lookback_days: int = 30,
    max_pages: int | None = None,
    max_details_per_source: int = 300,
) -> list[dict]:
    now = datetime.now(PLATFORM_TIMEZONE)
    start = now - timedelta(days=lookback_days)
    existing_urls = {item.get("url", "") for item in existing_items}
    results = {}
    for source in sources:
        detail_count = 0
        for listing in _page_listings(source, start, now, max_pages=max_pages):
            url = listing.get("apiUrl", "")
            if not url or url in existing_urls or not _is_original_notice(listing):
                continue
            if detail_count >= max_details_per_source:
                break
            detail_count += 1
            html_text = _request(url)
            item = item_from_listing(source, listing, html_text, keywords)
            if item:
                results[item["url"]] = item
                existing_urls.add(item["url"])
    return list(results.values())
