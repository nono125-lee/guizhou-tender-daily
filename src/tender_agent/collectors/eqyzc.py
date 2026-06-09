from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_keywords, matched_tender_keywords
from ..public_export import normalize_public_item


BASE_URL = "https://www.e-qyzc.com"
API_BASE = f"{BASE_URL}/api/saas-portal/noauth/trans/trade"
LIST_API = f"{API_BASE}/pageEs"
DETAIL_API = f"{API_BASE}/getByTradeId"
SOURCE_NAME = "黔云招采电子招标采购交易平台"
PLATFORM_TIMEZONE = ZoneInfo("America/Los_Angeles")
DETAIL_URL_RE = re.compile(
    r"[?&]id=(?P<id>\d+).*?[?&]noticeType=(?P<notice_type>\d+)"
)
PURCHASE_MODES = ",".join(
    [
        "888432838512144384",
        "888433019450224641",
        "888433072352980992",
        "888433135829577729",
        "888433219245895680",
        "892444899492474880",
        "903650807144759296",
        "1279211173293543425",
        "1332494542189219841",
        "1355289959029518337",
    ]
)


def _request_json(
    url: str,
    payload: dict | None = None,
    timeout: int = 15,
    attempts: int = 3,
) -> dict:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        url,
        data=data,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        },
        method="POST" if payload is not None else "GET",
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8-sig"))
            break
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(
            f"黔云招采接口访问失败：{type(last_error).__name__}"
        ) from last_error
    if not result.get("success"):
        raise RuntimeError(
            f"黔云招采接口返回异常：{result.get('errMessage') or 'unknown'}"
        )
    return result


def _page_payload(
    page_num: int,
    page_size: int,
    release_start: int,
    release_end: int,
) -> dict:
    return {
        "pageNum": page_num,
        "pageSize": page_size,
        "releaseStartTime": release_start,
        "releaseEndTime": release_end,
        "bidEndTimeStart": "",
        "bidEndTimeEnd": "",
        "noticeType": "",
        "purchaseMode": PURCHASE_MODES,
        "tradePattern": "",
        "sasacPurchaseDirectory": "",
        "tradingCenterTransactionDirectory": "",
        "publishStatus": "1",
        "accordingLawTender": None,
        "platformIdList": [],
        "businessName": "",
    }


def _datetime_text(timestamp: int | None, include_time: bool) -> str:
    if not timestamp:
        return ""
    value = datetime.fromtimestamp(
        timestamp / 1000,
        PLATFORM_TIMEZONE,
    )
    return value.strftime("%Y-%m-%d %H:%M" if include_time else "%Y-%m-%d")


def _detail_url(trade_id: str, notice_type: int, publish_status: int) -> str:
    query = urlencode(
        {
            "id": trade_id,
            "noticeType": notice_type,
            "publishStatus": publish_status,
        }
    )
    return f"{BASE_URL}/#/trade-info-detail?{query}"


def item_from_detail(
    listing: dict,
    detail_payload: dict,
    keywords: list[str],
) -> dict | None:
    detail = detail_payload.get("data", {}).get("biddingNotice")
    if not detail:
        return None
    title = clean_text(listing.get("businessName") or detail.get("businessName"))
    project_overview = clean_text(detail.get("projectOverview"))
    bidding_scope = clean_text(detail.get("biddingScope"))
    overview = (
        bidding_scope
        if bidding_scope
        else project_overview
        if project_overview and not project_overview.startswith("详见")
        else clean_text(detail.get("bidSectionName"))
        or clean_text(listing.get("purchaseProjectName"))
    )
    project_name = clean_text(detail.get("purchaseProjectName"))
    matches = matched_tender_keywords(
        project_name or title,
        [bidding_scope, project_overview],
        keywords,
    )
    if not matches:
        return None
    registration_start = _datetime_text(
        detail.get("tenderDocGetStartTime")
        or detail.get("registrationStartTime"),
        False,
    )
    registration_end = _datetime_text(
        detail.get("tenderDocGetEndTime")
        or detail.get("registrationEndTime"),
        False,
    )
    registration_period = (
        f"{registration_start}至{registration_end}"
        if registration_start and registration_end
        else ""
    )
    return normalize_public_item(
        {
            "published_at": _datetime_text(
                listing.get("releaseTime") or detail.get("releaseTime"),
                False,
            ),
            "date_basis": "official",
            "title": title,
            "url": _detail_url(
                str(listing["id"]),
                int(listing.get("noticeType") or 1),
                int(listing.get("publishStatus") or 1),
            ),
            "budget": _budget_text(
                detail.get("reckonPrice"),
                detail.get("extMap"),
            ),
            "summary": overview,
            "project_content": overview or project_name,
            "location": clean_text(detail.get("address")) or "贵州省",
            "buyer": clean_text(detail.get("tendererName")),
            "agency": clean_text(
                detail.get("tenderAgencyName")
                or detail.get("handleUnitName")
            ),
            "bid_deadline": _datetime_text(detail.get("bidEndTime"), True),
            "registration_period": registration_period,
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
        }
    )


def _budget_text(value: object | None, ext_map: dict | None = None) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        decimal_num = int((ext_map or {}).get("decimalNum") or 0)
        amount = float(value) / (10**decimal_num)
        if amount >= 10000:
            return f"{amount / 10000:g}万元"
        return f"{amount:g}元"
    text = clean_text(value)
    return text if any(unit in text for unit in ("元", "万")) else f"{text}元"


def collect(
    keywords: list[str],
    existing_items: list[dict],
    lookback_days: int = 2,
    page_size: int = 100,
    max_pages: int = 10,
) -> list[dict]:
    cutoff = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(
        days=lookback_days
    )
    release_start = int(
        datetime.combine(
            cutoff,
            datetime.min.time(),
            PLATFORM_TIMEZONE,
        ).timestamp()
        * 1000
    )
    release_end = int(datetime.now(ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    candidates: list[dict] = []
    reached_cutoff = False

    for page_num in range(1, max_pages + 1):
        response = _request_json(
            LIST_API,
            _page_payload(
                page_num,
                page_size,
                release_start,
                release_end,
            ),
        )
        listings = response.get("data", {}).get("list", [])
        if not listings:
            break
        for listing in listings:
            if int(listing.get("noticeType") or 0) != 1:
                continue
            release_date = _datetime_text(listing.get("releaseTime"), False)
            if release_date and datetime.fromisoformat(release_date).date() < cutoff:
                reached_cutoff = True
                continue
            text = " ".join(
                [
                    clean_text(listing.get("businessName")),
                    clean_text(listing.get("purchaseProjectName")),
                    clean_text(listing.get("bidSectionName")),
                ]
            )
            if not matched_keywords(text, keywords):
                continue
            candidates.append(listing)
        if reached_cutoff:
            break

    items = []
    item_urls: set[str] = set()
    candidate_ids = {str(listing["id"]) for listing in candidates}
    for existing in existing_items:
        url = existing.get("url", "")
        if "www.e-qyzc.com" not in url:
            continue
        try:
            published_date = datetime.fromisoformat(
                existing.get("published_at", "")[:10]
            ).date()
        except (TypeError, ValueError):
            continue
        match = DETAIL_URL_RE.search(url)
        if published_date < cutoff or not match:
            continue
        trade_id = match.group("id")
        if trade_id in candidate_ids:
            continue
        candidates.append(
            {
                "id": trade_id,
                "noticeType": int(match.group("notice_type")),
                "publishStatus": 1,
                "businessName": existing.get("title", ""),
                "releaseTime": None,
            }
        )
        candidate_ids.add(trade_id)

    for listing in candidates:
        query = urlencode(
            {
                "id": listing["id"],
                "noticeType": listing.get("noticeType") or 1,
            }
        )
        detail = _request_json(f"{DETAIL_API}?{query}")
        item = item_from_detail(listing, detail, keywords)
        if item and item["url"] not in item_urls:
            items.append(item)
            item_urls.add(item["url"])
    return items
