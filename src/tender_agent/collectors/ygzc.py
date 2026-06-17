from __future__ import annotations

import hashlib
import html
import json
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_tender_keywords
from ..public_export import normalize_public_item
from .guizhou_ztb import (
    _deadline,
    _parties,
    _plain_text,
    _registration_period,
)


BASE_URL = "https://www.ygzcfwy.net"
LIST_API = f"{BASE_URL}/api/portal/bidnotice/list"
DETAIL_API = f"{BASE_URL}/api/portal/details"
SOURCE_NAME = "贵阳市公共资源交易国有企业招标采购平台"
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")
DETAIL_URL_TEMPLATE = f"{BASE_URL}/#/details.html?businessId={{}}&activeId=3"
MONEY_FIELDS = ("项目预算", "预算金额", "采购预算", "最高限价")
RESULT_TYPE_CODE = "CGGG"
BLOCK_END_RE = re.compile(
    r"</(?:p|div|h[1-6]|li|tr|table)>",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
SECTION_LABEL_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.．]\s*)?"
    r"(?:招标内容|采购内容|招标范围|采购范围|项目概况)"
    r"\s*[：:]?\s*(.*)$"
)
SECTION_STOP_RE = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十]+[、.．]\s*|"
    r"(?:获取|购买|领取|报名).{0,20}(?:时间|期限|方式)[：:]|"
    r"(?:供应商|投标人|申请人|响应人).{0,16}资格|"
    r"(?:采购人|招标人|采购单位|采购代理机构|招标代理机构|代理机构)"
    r"\s*[：:]|"
    r"(?:响应文件|投标文件).{0,16}(?:截止时间|递交)|"
    r"(?:开标时间|联系方式|联系人|联系电话|项目预算|预算金额|最高限价)"
    r"\s*[：:]"
    r")"
)


def _request_json(
    url: str,
    params: dict | None = None,
    timeout: int = 20,
    attempts: int = 3,
) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"{BASE_URL}/#/transaction.html",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8-sig"))
            if result.get("code") != 0:
                raise RuntimeError(result.get("msg") or "接口返回异常")
            return result
        except (
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            RuntimeError,
        ) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(attempt + 1)
    raise RuntimeError(
        f"贵阳市国企招采平台接口访问失败：{type(last_error).__name__}"
    ) from last_error


def _field_map(detail: dict) -> dict[str, str]:
    return {
        clean_text(field.get("name")): clean_text(field.get("value"))
        for field in detail.get("fields", [])
        if clean_text(field.get("name"))
    }


def _content_lines(content: str) -> list[str]:
    with_breaks = BLOCK_END_RE.sub("\n", content or "")
    plain = html.unescape(TAG_RE.sub(" ", with_breaks))
    return [
        clean_text(line)
        for line in plain.splitlines()
        if clean_text(line)
    ]


def _project_content_from_html(content: str) -> str:
    lines = _content_lines(content)
    for index, line in enumerate(lines):
        match = SECTION_LABEL_RE.match(line)
        if not match:
            continue
        values = []
        if clean_text(match.group(1)):
            values.append(clean_text(match.group(1)))
        for following in lines[index + 1:]:
            if SECTION_STOP_RE.match(following):
                break
            values.append(following)
        value = clean_text(" ".join(values)).strip("：:；;。 ")
        if value and not value.startswith("详见"):
            return value
    return ""


def _date_text(value: object, include_time: bool) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(
        r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?"
        r"(?:[ T]?\s*(\d{1,2}):(\d{2}))?",
        text,
    )
    if not match:
        return text
    date_value = (
        f"{int(match.group(1)):04d}-"
        f"{int(match.group(2)):02d}-"
        f"{int(match.group(3)):02d}"
    )
    if include_time and match.group(4):
        return f"{date_value} {int(match.group(4)):02d}:{match.group(5)}"
    return date_value


def _budget_text(fields: dict[str, str]) -> str:
    value = next((fields[name] for name in MONEY_FIELDS if fields.get(name)), "")
    if not value:
        return ""
    if any(unit in value for unit in ("元", "万")):
        return value
    try:
        amount = float(value.replace(",", ""))
    except ValueError:
        return value
    if amount >= 10000:
        return f"{amount / 10000:g}万元"
    return f"{amount:g}元"


def _registration_from_times(
    listing: dict,
    detail: dict,
    text: str,
    publish_date: str,
) -> str:
    period = _registration_period(text, publish_date)
    if period:
        return period
    summary = detail.get("timeSummary") or {}
    start = _date_text(
        summary.get("callSignStime")
        or summary.get("signStartTime")
        or listing.get("startTime"),
        False,
    )
    end = _date_text(
        summary.get("callSignEtime")
        or summary.get("signEndTime")
        or listing.get("endTime"),
        False,
    )
    return f"{start}至{end}" if start and end else ""


def item_from_detail(
    listing: dict,
    detail_payload: dict,
    keywords: list[str],
) -> dict | None:
    detail = detail_payload.get("data") or {}
    if not detail:
        return None
    fields = _field_map(detail)
    title = clean_text(detail.get("title") or listing.get("title"))
    project_name = fields.get("项目名称") or title
    content = detail.get("content", "")
    text = _plain_text(content)
    project_content = _project_content_from_html(content)
    matches = matched_tender_keywords(
        project_name,
        [project_content],
        keywords,
    )
    if not matches:
        return None
    publish_date = _date_text(
        detail.get("time") or listing.get("pubtime"),
        False,
    )
    buyer, agency = _parties(text, "")
    time_summary = detail.get("timeSummary") or {}
    return normalize_public_item(
        {
            "published_at": publish_date,
            "date_basis": "official",
            "title": title,
            "project_name": project_name,
            "url": DETAIL_URL_TEMPLATE.format(listing["id"]),
            "budget": _budget_text(fields),
            "summary": project_content,
            "project_content": project_content,
            "project_content_basis": "section-v3",
            "location": "贵州省",
            "buyer": buyer,
            "agency": agency,
            "bid_deadline": (
                _date_text(time_summary.get("bidEndTime"), True)
                or _deadline(text)
            ),
            "registration_period": _registration_from_times(
                listing,
                detail,
                text,
                publish_date,
            ),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
        }
    )


def _keyword_signature(keywords: list[str]) -> str:
    value = "\n".join(sorted(set(keywords))).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _load_state(path: Path, keywords: list[str]) -> dict:
    state = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {}
    )
    signature = _keyword_signature(keywords)
    if state.get("keyword_signature") != signature:
        state = {"processed": {}, "failed_ids": []}
    state["keyword_signature"] = signature
    state.setdefault("processed", {})
    state.setdefault("failed_ids", [])
    return state


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect(
    keywords: list[str],
    existing_items: list[dict],
    state_path: str | Path,
    lookback_days: int = 7,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[dict]:
    state_file = Path(state_path)
    state = _load_state(state_file, keywords)
    processed = state["processed"]
    failed_ids = set(state["failed_ids"])
    existing_urls = {item.get("url", "") for item in existing_items}
    cutoff = datetime.now(PLATFORM_TIMEZONE).date() - timedelta(
        days=lookback_days
    )
    candidates: list[dict] = []
    page = 1
    while page <= max_pages:
        response = _request_json(
            LIST_API,
            {
                "keyName": "",
                "menuCode": "",
                "methodType": "",
                "pType": "",
                "pubtime": "1_WEEKS",
                "typeCode": RESULT_TYPE_CODE,
                "page": page,
                "pageSize": page_size,
            },
        )
        result = response.get("data") or {}
        total_pages = max(1, math.ceil(int(result.get("total") or 0) / page_size))
        for listing in result.get("data", []):
            notice_id = str(listing.get("id") or "")
            if not notice_id:
                continue
            publish_date = _date_text(listing.get("pubtime"), False)
            if publish_date:
                try:
                    if datetime.fromisoformat(publish_date).date() < cutoff:
                        continue
                except ValueError:
                    pass
            url = DETAIL_URL_TEMPLATE.format(notice_id)
            if url in existing_urls or (
                notice_id in processed and notice_id not in failed_ids
            ):
                continue
            candidates.append(listing)
        if page >= total_pages:
            break
        page += 1

    items = []
    new_failed_ids: set[str] = set()
    for listing in candidates:
        notice_id = str(listing["id"])
        try:
            detail = _request_json(f"{DETAIL_API}/{notice_id}")
            item = item_from_detail(listing, detail, keywords)
        except Exception:
            new_failed_ids.add(notice_id)
            continue
        processed[notice_id] = {
            "published_at": _date_text(listing.get("pubtime"), False),
            "status": "matched" if item else "not_matched",
        }
        failed_ids.discard(notice_id)
        if item:
            items.append(item)
            existing_urls.add(item["url"])

    retention_cutoff = cutoff - timedelta(days=38)
    state["processed"] = {
        notice_id: result
        for notice_id, result in processed.items()
        if not result.get("published_at")
        or datetime.fromisoformat(result["published_at"]).date() >= retention_cutoff
    }
    state["failed_ids"] = sorted(failed_ids | new_failed_ids)
    state["last_run_at"] = datetime.now(PLATFORM_TIMEZONE).isoformat()
    _save_state(state_file, state)
    return items
