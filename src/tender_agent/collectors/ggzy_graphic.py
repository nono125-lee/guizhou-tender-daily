from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_keywords, matched_tender_keywords
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
DEFAULT_STATE_PATH = Path(__file__).resolve().parents[3] / "site" / "data" / "ggzy-state.json"
OVERLAP_HOURS = 6
WEEKLY_BACKSCAN_DAYS = 14
MONTHLY_BACKSCAN_DAYS = 45
MAX_DETAIL_RETRIES = 3


def _request(url: str, payload: dict | None = None, timeout: int = 25) -> str:
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Content-Type": "application/json;charset=UTF-8",
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def _request_json(url: str, payload: dict | None = None, timeout: int = 25) -> dict | None:
    """Fetch JSON with retries; returns None on persistent failure."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            data = json.loads(_request(url, payload, timeout=timeout))
            return data
        except HTTPError as error:
            if error.code == 404:
                return None
            last_error = error
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < 2:
            time.sleep(0.8 * (attempt + 1))
    if last_error is not None:
        raise RuntimeError(
            f"GGZY API 请求失败：{type(last_error).__name__}"
        ) from last_error
    return None


def _fetch_detail_with_retry(meta_id: str) -> str | None:
    """Fetch a single detail page. Returns HTML text or None on failure."""
    url = f"https://ggzy.guizhou.gov.cn/tradeInfo/detailHtml?metaId={meta_id}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _request(url, timeout=20)
        except HTTPError as error:
            if error.code == 404:
                return None
            last_error = error
        except (URLError, OSError, TimeoutError) as error:
            last_error = error
        if attempt < 2:
            time.sleep(1.0 * (attempt + 1))
    return None


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
        data = _request_json(LIST_API, payload)
        if data is None:
            break
        listings = data.get("list", [])
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


def _extract_meta_id(url: str) -> str:
    """Extract metaId from a ggzy detail URL."""
    import re
    match = re.search(r"metaId=(\d+)", url or "")
    return match.group(1) if match else ""


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


def _load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"sources": {}}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": {}}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_name(f".{state_path.name}.{id(state)}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(state_path)


def _source_state(state: dict, source_id: str) -> dict:
    if "sources" not in state:
        state["sources"] = {}
    if source_id not in state["sources"]:
        state["sources"][source_id] = {
            "processed_meta_ids": [],
            "retry_queue": [],
            "last_success_cursor": None,
            "last_scan_complete": False,
        }
    return state["sources"][source_id]


def collect(
    keywords: list[str],
    existing_items: list[dict],
    sources: list[dict],
    lookback_days: int = 30,
    max_pages: int | None = None,
    max_details_per_source: int = 300,
    state_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """Collect ggzy notices with title-priority queue.

    Returns (items, scan_report) where scan_report has per-source metrics.
    """
    now = datetime.now(PLATFORM_TIMEZONE)
    start = now - timedelta(days=lookback_days)
    # Overlap: look back an extra OVERLAP_HOURS to catch items that may have shifted
    start_with_overlap = start - timedelta(hours=OVERLAP_HOURS)

    existing_urls = {item.get("url", "") for item in existing_items}
    all_items: dict[str, dict] = {}
    scan_report: dict = {"sources": {}, "scan_complete": True, "warnings": []}

    state = _load_state(state_path or DEFAULT_STATE_PATH)

    for source in sources:
        source_id = source.get("id", source.get("name", "unknown"))
        ss = _source_state(state, source_id)
        processed_ids = set(ss.get("processed_meta_ids", []))
        retry_queue = list(ss.get("retry_queue", []))

        source_report: dict = {
            "source_id": source_id,
            "source_name": source["name"],
            "total_listings": 0,
            "pages_scanned": 0,
            "oldest_time_scanned": None,
            "title_matches": 0,
            "content_matches": 0,
            "detail_quota_used": 0,
            "detail_retries": 0,
            "detail_failures": 0,
            "scan_complete": True,
            "warnings": [],
        }

        # ---- Phase 1: Scan all list pages, classify listings ----
        title_matches: list[dict] = []       # title hits keyword → priority
        content_candidates: list[dict] = []  # need detail to check content fields

        for listing in _page_listings(source, start_with_overlap, now, max_pages=max_pages):
            source_report["total_listings"] += 1
            url = listing.get("apiUrl", "")
            if not url or url in existing_urls or not _is_original_notice(listing):
                continue

            meta_id = _extract_meta_id(url)
            if meta_id and meta_id in processed_ids:
                continue

            title = clean_text(listing.get("docTitle"))
            title_keyword_hits = matched_keywords(title, keywords)

            if title_keyword_hits:
                title_matches.append(listing)
            else:
                content_candidates.append(listing)

            # Track oldest time seen
            doc_time = listing.get("docRelTime")
            if doc_time:
                ts = int(doc_time) / 1000
                if source_report["oldest_time_scanned"] is None or ts < source_report["oldest_time_scanned"]:
                    source_report["oldest_time_scanned"] = ts

        # Track pages scanned (estimate from page_size=100)
        source_report["pages_scanned"] = (source_report["total_listings"] + 99) // 100

        # ---- Phase 2: Process title matches FIRST (priority queue, no cap) ----
        for listing in title_matches:
            url = listing.get("apiUrl", "")
            meta_id = _extract_meta_id(url)
            html_text = _fetch_detail_with_retry(meta_id) if meta_id else None
            if html_text is None:
                if meta_id:
                    retry_queue.append({"meta_id": meta_id, "failures": 0, "source_id": source_id})
                source_report["detail_failures"] += 1
                continue

            item = item_from_listing(source, listing, html_text, keywords)
            if item:
                all_items[item["url"]] = item
                existing_urls.add(item["url"])
                source_report["title_matches"] += 1

            if meta_id:
                processed_ids.add(meta_id)

        # ---- Phase 3: Process retry queue ----
        new_retries: list[dict] = []
        for entry in retry_queue:
            if entry.get("failures", 0) >= MAX_DETAIL_RETRIES:
                continue
            html_text = _fetch_detail_with_retry(entry["meta_id"])
            if html_text is None:
                entry["failures"] = entry.get("failures", 0) + 1
                if entry["failures"] < MAX_DETAIL_RETRIES:
                    new_retries.append(entry)
                else:
                    source_report["detail_failures"] += 1
                continue
            # We need the listing dict to build the item, but retry entries only have meta_id
            # We can construct a minimal listing from the meta_id
            minimal_listing = {"apiUrl": f"https://ggzy.guizhou.gov.cn/tradeInfo/detailHtml?metaId={entry['meta_id']}"}
            item = item_from_listing(source, minimal_listing, html_text, keywords)
            if item:
                all_items[item["url"]] = item
                existing_urls.add(item["url"])
                source_report["detail_retries"] += 1
            processed_ids.add(entry["meta_id"])
        retry_queue = new_retries

        # ---- Phase 4: Content candidates (subject to detail quota) ----
        detail_count = 0
        for listing in content_candidates:
            if detail_count >= max_details_per_source:
                source_report["scan_complete"] = False
                source_report["warnings"].append(
                    f"{source['name']}：正文探索配额已用尽（{max_details_per_source}条），"
                    f"仍有 {len(content_candidates) - detail_count} 条未检查"
                )
                break

            url = listing.get("apiUrl", "")
            meta_id = _extract_meta_id(url)
            detail_count += 1
            source_report["detail_quota_used"] = detail_count

            html_text = _fetch_detail_with_retry(meta_id) if meta_id else None
            if html_text is None:
                if meta_id:
                    retry_queue.append({"meta_id": meta_id, "failures": 0, "source_id": source_id})
                source_report["detail_failures"] += 1
                continue

            item = item_from_listing(source, listing, html_text, keywords)
            if item:
                all_items[item["url"]] = item
                existing_urls.add(item["url"])
                source_report["content_matches"] += 1

            if meta_id:
                processed_ids.add(meta_id)

        # ---- Update source state ----
        ss["processed_meta_ids"] = sorted(processed_ids, key=int)[-10000:]  # keep last 10k
        ss["retry_queue"] = retry_queue
        ss["last_success_cursor"] = now.isoformat()
        ss["last_scan_complete"] = source_report["scan_complete"]

        # ---- Aggregate warnings ----
        if not source_report["scan_complete"]:
            scan_report["scan_complete"] = False
        if source_report["detail_failures"] > 0:
            source_report["warnings"].append(
                f"{source['name']}：{source_report['detail_failures']} 条详情获取失败"
            )
        if source_report["warnings"]:
            scan_report["warnings"].extend(source_report["warnings"])

        scan_report["sources"][source_id] = source_report

    # Save state
    _save_state(state_path or DEFAULT_STATE_PATH, state)

    return list(all_items.values()), scan_report
