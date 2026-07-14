#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import fcntl
import html
import json
import os
import random
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from priority_match import (
    latest_ultra_long_plans,
    load_json_source,
    merge_priority_notices,
    resolve_construction_source,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSET_SITE = SKILL_ROOT / "assets/site"
BASE_URL = "http://ztb.guizhou.gov.cn"
SEARCH_API = f"{BASE_URL}/api/trade/search"
DETAIL_API = f"{BASE_URL}/api/trade/GetDetail"
SOURCE_PAGE = f"{BASE_URL}/trade/?prjtype=A&category=AP1"
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(r"20\d{2}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?")
PHONE_RE = re.compile(r"1[3-9]\d{9}")
TIMEZONE = ZoneInfo("Asia/Shanghai")
DETAIL_CACHE_TTL_DAYS = 30
DEFAULT_REQUEST_INTERVAL = 0.25
WINDOW_RANK = {"td": 0, "l3d": 1, "l10d": 2, "l1m": 3, "l3m": 4, "l1y": 5, "all": 6}
DETAIL_FIELDS = (
    "project_name",
    "fixed_asset_code",
    "approval",
    "buyer",
    "agency",
    "budget",
    "fund_source",
    "fund_source_tags",
    "project_content",
    "planned_bid_time",
    "planned_tender_content",
    "planned_trade_place",
    "project_location",
    "supervisor",
)


class RequestPacer:
    def __init__(self, interval: float) -> None:
        self.interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_at = now + self.interval


class TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag in {"br", "p", "div"} and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = clean_text("".join(self._cell))
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            row = [cell for cell in self._row if cell]
            if row:
                self.rows.append(row)
            self._row = None


def clean_text(value: object) -> str:
    return SPACE_RE.sub(" ", html.unescape(str(value or ""))).strip()


def plain_text(content: str) -> str:
    return clean_text(TAG_RE.sub(" ", content or ""))


def compact_label(value: str) -> str:
    return re.sub(r"[\s:：()（）★*]", "", value or "")


def fetch_json(
    url: str,
    timeout: int = 20,
    retries: int = 2,
    pacer: RequestPacer | None = None,
) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TenderPlan/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if pacer:
                pacer.wait()
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8-sig")
            return json.loads(raw)
        except Exception as error:  # network and JSON errors are recorded by caller
            last_error = error
            if attempt < retries:
                retry_after = ""
                if isinstance(error, HTTPError) and error.headers:
                    retry_after = error.headers.get("Retry-After", "")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = 0.8 * (2**attempt) + random.uniform(0.0, 0.3)
                time.sleep(min(delay, 30.0))
    raise RuntimeError(f"{type(last_error).__name__}: {last_error}")


def search_url(pub_date: str, page_index: int, keywords: str = "") -> str:
    params = {
        "pubDate": pub_date,
        "pubType": "all",
        "region": "5200",
        "industry": "all",
        "prjType": "A",
        "noticeType": "AP1",
        "noticeClassify": "all",
        "pageIndex": str(page_index),
        "args": keywords,
    }
    return f"{SEARCH_API}?{urlencode(params)}"


def empty_state() -> dict:
    return {
        "schema_version": 1,
        "last_attempt_at": "",
        "last_success_at": "",
        "last_weekly_backfill_at": "",
        "last_monthly_backfill_at": "",
        "last_mode": "",
    }


def empty_detail_cache() -> dict:
    return {"schema_version": 1, "entries": {}, "failures": {}}


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def elapsed_calendar_days(value: str, now: datetime) -> int | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    return max(0, (now.astimezone(TIMEZONE).date() - parsed.date()).days)


def select_run(state: dict, manual_pub_date: str | None, now: datetime) -> tuple[str, str]:
    if manual_pub_date:
        return "manual", manual_pub_date

    gap = elapsed_calendar_days(state.get("last_success_at", ""), now)
    if gap is None:
        return "bootstrap", "l3m"
    if gap == 0:
        selected = ("daily", "td")
    elif gap == 1:
        selected = ("daily", "l3d")
    elif gap <= 9:
        selected = ("catchup", "l10d")
    elif gap <= 29:
        selected = ("catchup", "l1m")
    else:
        selected = ("catchup", "l3m")

    candidates = [selected]
    monthly_gap = elapsed_calendar_days(state.get("last_monthly_backfill_at", ""), now)
    weekly_gap = elapsed_calendar_days(state.get("last_weekly_backfill_at", ""), now)
    if monthly_gap is None or monthly_gap >= 30:
        candidates.append(("monthly", "l3m"))
    if weekly_gap is None or weekly_gap >= 7:
        candidates.append(("weekly", "l1m"))
    return max(candidates, key=lambda item: WINDOW_RANK[item[1]])


def complete_state(state: dict, now: datetime, mode: str, pub_date: str) -> None:
    timestamp = now.astimezone(TIMEZONE).isoformat()
    state["last_success_at"] = timestamp
    state["last_mode"] = mode
    if WINDOW_RANK[pub_date] >= WINDOW_RANK["l1m"]:
        state["last_weekly_backfill_at"] = timestamp
    if WINDOW_RANK[pub_date] >= WINDOW_RANK["l3m"]:
        state["last_monthly_backfill_at"] = timestamp


def read_json_file(path: Path, default: dict, warnings: list[str], label: str) -> dict:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        warnings.append(f"{label}读取异常，已使用空状态：{type(error).__name__}")
        return default
    return value if isinstance(value, dict) else default


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def exclusive_run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("已有另一个招标计划采集进程正在运行") from error
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def retention_cutoff(now: datetime, mode: str, pub_date: str) -> date | None:
    current = now.astimezone(TIMEZONE).date()
    if mode == "manual" and pub_date == "all":
        return None
    if mode == "manual" and pub_date == "l1y":
        return current - timedelta(days=366)
    return subtract_months(current, 3)


def item_date(item: dict) -> date | None:
    value = str(item.get("published_at") or "")[:10]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def merge_items(
    existing_items: list[dict],
    window_items: list[dict],
    cutoff: date | None,
    rebuild: bool = False,
) -> tuple[list[dict], int]:
    merged: dict[str, dict] = {}
    if not rebuild:
        merged = {
            str(item.get("source_notice_id")): dict(item)
            for item in existing_items
            if item.get("source_notice_id")
        }
    for item in window_items:
        notice_id = str(item.get("source_notice_id") or "")
        if not notice_id:
            continue
        combined = dict(merged.get(notice_id, {}))
        for key, value in item.items():
            if value not in (None, "", []) or key not in combined:
                combined[key] = value
        merged[notice_id] = combined

    before_prune = len(merged)
    if cutoff:
        merged = {
            notice_id: item
            for notice_id, item in merged.items()
            if not item_date(item) or item_date(item) >= cutoff
        }
    items = list(merged.values())
    items.sort(
        key=lambda row: (row.get("published_at", ""), row.get("source_notice_id", "")),
        reverse=True,
    )
    return items, before_prune - len(items)


def detail_from_item(item: dict) -> dict:
    return {key: item[key] for key in DETAIL_FIELDS if key in item}


def seed_detail_cache(cache: dict, existing_payload: dict, now: datetime) -> int:
    entries = cache.setdefault("entries", {})
    if entries:
        return 0
    cached_at = existing_payload.get("updated_at") or now.astimezone(TIMEZONE).isoformat()
    if not parse_datetime(str(cached_at)):
        cached_at = now.astimezone(TIMEZONE).isoformat()
    seeded = 0
    for item in existing_payload.get("items", []):
        notice_id = str(item.get("source_notice_id") or "")
        fields = detail_from_item(item)
        meaningful = any(
            fields.get(key)
            for key in DETAIL_FIELDS
            if key not in {"buyer", "agency", "fund_source_tags"}
        )
        if notice_id and meaningful:
            entries[notice_id] = {"fields": fields, "cached_at": cached_at}
            seeded += 1
    return seeded


def cached_detail(
    cache: dict,
    notice_id: str,
    now: datetime,
    ttl_days: int,
) -> tuple[dict | None, bool]:
    record = cache.get("entries", {}).get(str(notice_id), {})
    fields = record.get("fields")
    cached_at = parse_datetime(str(record.get("cached_at") or ""))
    if not isinstance(fields, dict) or not cached_at:
        return None, False
    is_fresh = now.astimezone(TIMEZONE) - cached_at < timedelta(days=max(0, ttl_days))
    return fields, is_fresh


def apply_detail(item: dict, detail: dict) -> None:
    for key, value in detail.items():
        if key in {"buyer", "agency"}:
            if value:
                item[key] = value
        else:
            item[key] = value


def prune_detail_cache(cache: dict, items: list[dict]) -> None:
    retained_ids = {
        str(item.get("source_notice_id"))
        for item in items
        if item.get("source_notice_id")
    }
    cache["entries"] = {
        notice_id: record
        for notice_id, record in cache.get("entries", {}).items()
        if notice_id in retained_ids
    }
    cache["failures"] = {
        notice_id: record
        for notice_id, record in cache.get("failures", {}).items()
        if notice_id in retained_ids
    }


def get_label_value(rows: list[list[str]], labels: tuple[str, ...]) -> str:
    normalized = tuple(compact_label(label) for label in labels)
    for row in rows:
        for index, cell in enumerate(row):
            cell_label = compact_label(cell)
            if any(label and label in cell_label for label in normalized):
                if index + 1 < len(row):
                    return clean_text(row[index + 1])
    return ""


def first_date(text: str) -> str:
    match = DATE_RE.search(text or "")
    return match.group(0) if match else ""


def parse_rows(content: str) -> list[list[str]]:
    parser = TableTextParser()
    parser.feed(content or "")
    return parser.rows


def infer_planned_tender(rows: list[list[str]]) -> tuple[str, str, str]:
    for row in rows:
        row_text = " ".join(row)
        planned_at = first_date(row_text)
        if not planned_at:
            continue
        content = ""
        place = ""
        for cell in row:
            if DATE_RE.fullmatch(cell):
                continue
            if "交易中心" in cell or "交易场所" in cell:
                place = cell
                continue
            if re.fullmatch(r"\d{4,}", cell):
                continue
            if cell not in {"序号", "招标内容", "预计招标时间", "拟交易场所"} and len(cell) <= 80:
                content = content or cell
        return planned_at, content, place
    return "", "", ""


def fund_tags(value: str) -> list[str]:
    text = value or ""
    tags: list[str] = []
    patterns = [
        ("超长期", r"超长期(?:特别)?国债|特别国债"),
        ("政府投资", r"政府投资|政府性投资|政府资金"),
        ("财政资金", r"财政|预算内|一般公共预算|中央预算"),
        ("上级补助", r"上级补助|中央补助|省级补助|补助资金|专项补助"),
        ("地方自筹", r"地方自筹|县级自筹|市级自筹|区级自筹|自筹资金|自筹"),
        ("专项债", r"专项债|地方政府债|债券"),
        ("企业自筹", r"企业自筹|业主自筹|单位自筹|公司自筹"),
        ("银行贷款", r"银行贷款|贷款|融资"),
        ("社会资本", r"社会资本|社会投资|民间投资"),
        ("国有资金", r"国有资金|国企|企业资金"),
    ]
    for tag, pattern in patterns:
        if re.search(pattern, text):
            tags.append(tag)
    if text and not tags:
        tags.append("其他")
    if not text:
        tags.append("未载明")
    return tags


def normalize_budget(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if re.search(r"万元|元|亿元", value):
        return value
    if re.fullmatch(r"[\d,.]+", value):
        return f"{value}万元"
    return value


def parse_detail(detail: dict) -> dict:
    content = detail.get("Content") or ""
    rows = parse_rows(content)
    text = plain_text(content)
    planned_at, planned_content, planned_place = infer_planned_tender(rows)
    fund_source = get_label_value(rows, ("资金来源",))
    buyer = get_label_value(rows, ("招标人名称", "招标人"))
    agency = get_label_value(rows, ("招标人委托的代理机构名称", "代理机构名称"))
    detail_data = {
        "project_name": get_label_value(rows, ("工程建设项目名称", "项目名称")),
        "fixed_asset_code": get_label_value(rows, ("固定资产投资项目代码",)),
        "approval": get_label_value(rows, ("项目批准文件及文号", "批准文件")),
        "buyer": buyer,
        "agency": agency,
        "budget": normalize_budget(get_label_value(rows, ("投资估算", "总投资", "项目投资"))),
        "fund_source": fund_source,
        "fund_source_tags": fund_tags(fund_source),
        "project_content": get_label_value(rows, ("项目建设内容", "建设内容", "项目概况")),
        "planned_bid_time": planned_at or first_date(text),
        "planned_tender_content": planned_content,
        "planned_trade_place": planned_place,
        "project_location": get_label_value(rows, ("项目建设地点", "建设地点")),
        "supervisor": get_label_value(rows, ("行政监督部门", "监督部门")),
    }
    if PHONE_RE.fullmatch(detail_data["buyer"]):
        detail_data["buyer"] = ""
    if PHONE_RE.fullmatch(detail_data["agency"]):
        detail_data["agency"] = ""
    return detail_data


def normalize_listing(item: dict) -> dict:
    notice_id = str(item.get("Id") or "")
    source_name = (
        item.get("TradeCenterName")
        if item.get("IsTradeCenterPush") and item.get("TradeCenterName")
        else "贵州省招标投标公共服务平台"
    )
    return {
        "source_notice_id": notice_id,
        "title": clean_text(item.get("Title")),
        "published_at": clean_text(item.get("PubDate")),
        "region": clean_text(item.get("RegionName")),
        "buyer": clean_text(item.get("TenderName")),
        "agency": clean_text(item.get("TenderAgencyName")),
        "source_name": clean_text(source_name),
        "notice_type": clean_text(item.get("BTypeName")),
        "url": f"{BASE_URL}/trade/bulletin/?id={notice_id}",
    }


def fetch_page(
    pub_date: str,
    page_index: int,
    keywords: str,
    pacer: RequestPacer | None = None,
) -> dict:
    return fetch_json(search_url(pub_date, page_index, keywords), pacer=pacer)


def fetch_detail(
    notice_id: str,
    pacer: RequestPacer | None = None,
) -> tuple[str, dict | None, str | None]:
    try:
        detail = fetch_json(
            f"{DETAIL_API}/{notice_id}", timeout=25, retries=2, pacer=pacer
        )
        return notice_id, parse_detail(detail), None
    except Exception as error:
        return notice_id, None, f"{notice_id}: {type(error).__name__}"


def copy_site_assets(site_dir: Path) -> None:
    for relative in ("index.html", "assets/style.css", "assets/app.js"):
        source = ASSET_SITE / relative
        target = site_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def collect(
    args: argparse.Namespace,
    existing_payload: dict,
    detail_cache: dict,
    now: datetime,
    pacer: RequestPacer,
    initial_warnings: list[str] | None = None,
) -> tuple[dict, bool]:
    warnings = list(initial_warnings or [])
    first = fetch_page(args.pub_date, 1, args.keywords, pacer)
    total_pages = int(first.get("totalPage") or 0)
    if args.all_pages:
        page_count = total_pages
    else:
        page_count = args.max_pages or total_pages
    page_count = max(0, min(page_count, total_pages))

    listings = [normalize_listing(item) for item in first.get("data", [])]
    list_complete = page_count == total_pages
    if page_count > 1:
        for page in range(2, page_count + 1):
            try:
                payload = fetch_page(args.pub_date, page, args.keywords, pacer)
                listings.extend(normalize_listing(item) for item in payload.get("data", []))
            except Exception as error:
                list_complete = False
                warnings.append(f"第 {page} 页列表采集异常：{type(error).__name__}")

    deduped = {}
    for item in listings:
        if item["source_notice_id"]:
            deduped[item["source_notice_id"]] = item
    source_window_items = len(deduped)
    failures = detail_cache.setdefault("failures", {})
    if not args.rebuild:
        for record in failures.values():
            retry_listing = record.get("listing")
            notice_id = str((retry_listing or {}).get("source_notice_id") or "")
            if notice_id and notice_id not in deduped:
                deduped[notice_id] = dict(retry_listing)
    listings = list(deduped.values())

    cache_hits = 0
    cache_misses = 0
    detail_fetch_success = 0
    detail_fetch_failed = 0
    stale_cache_used = 0

    if args.no_details:
        pass
    else:
        stale_by_id: dict[str, dict] = {}
        pending: list[dict] = []
        for item in listings:
            notice_id = item["source_notice_id"]
            cached, is_fresh = cached_detail(
                detail_cache, notice_id, now, args.detail_cache_ttl_days
            )
            if cached and is_fresh and not args.refresh_details:
                apply_detail(item, cached)
                cache_hits += 1
                failures.pop(notice_id, None)
                continue
            cache_misses += 1
            if cached:
                stale_by_id[notice_id] = cached
            pending.append(item)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(fetch_detail, item["source_notice_id"], pacer): item
                for item in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                notice_id, detail, error = future.result()
                if error:
                    detail_fetch_failed += 1
                    warnings.append(f"详情采集异常 {error}")
                    stale = stale_by_id.get(notice_id)
                    if stale:
                        apply_detail(item, stale)
                        stale_cache_used += 1
                    previous = failures.get(notice_id, {})
                    failures[notice_id] = {
                        "listing": item,
                        "attempts": int(previous.get("attempts", 0)) + 1,
                        "last_error": error,
                        "last_attempt_at": now.astimezone(TIMEZONE).isoformat(),
                    }
                    continue
                if detail:
                    detail_fetch_success += 1
                    apply_detail(item, detail)
                    detail_cache.setdefault("entries", {})[notice_id] = {
                        "fields": detail,
                        "cached_at": now.astimezone(TIMEZONE).isoformat(),
                    }
                    failures.pop(notice_id, None)

    cutoff = retention_cutoff(now, args.mode, args.pub_date)
    listings, pruned_items = merge_items(
        existing_payload.get("items", []),
        listings,
        cutoff,
        rebuild=args.rebuild,
    )
    today = now.astimezone(TIMEZONE).date().isoformat()
    for item in listings:
        item.setdefault("fund_source", "")
        item.setdefault("fund_source_tags", fund_tags(item.get("fund_source", "")))
        item["is_new"] = item.get("published_at", "").startswith(today)

    stats = {
        "total": len(listings),
        "merged_total": len(listings),
        "window_items": source_window_items,
        "source_total": int(first.get("totalNum") or 0),
        "source_total_pages": total_pages,
        "collected_pages": page_count,
        "list_complete": list_complete,
        "mode": args.mode,
        "pub_date": args.pub_date,
        "detail_cache_hits": cache_hits,
        "detail_cache_misses": cache_misses,
        "detail_fetch_success": detail_fetch_success,
        "detail_fetch_failed": detail_fetch_failed,
        "stale_cache_used": stale_cache_used,
        "pruned_items": pruned_items,
        "new_today": sum(1 for item in listings if item.get("is_new")),
        "regions": len({item.get("region") for item in listings if item.get("region")}),
        "fund_source_tags": len({tag for item in listings for tag in item.get("fund_source_tags", [])}),
    }
    payload = {
        "schema_version": 1,
        "updated_at": now.astimezone(TIMEZONE).isoformat(),
        "coverage": "贵州省工程建设招标计划",
        "source_url": SOURCE_PAGE,
        "query": {
            "pub_date": args.pub_date,
            "keywords": args.keywords,
            "all_pages": args.all_pages,
            "max_pages": args.max_pages,
        },
        "warnings": warnings[:200],
        "stats": stats,
        "items": listings,
    }
    return payload, list_complete


def write_payload(site_dir: Path, payload: dict) -> None:
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(data_dir / "latest.json", payload)
    copy_site_assets(site_dir)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Guizhou tender plan notices.")
    parser.add_argument("--site-dir", type=Path, default=Path.cwd() / "site/tender-plan")
    parser.add_argument("--pub-date", choices=["td", "l3d", "l10d", "l1m", "l3m", "l1y", "all"])
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--all-pages", action="store_true")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-details", action="store_true")
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="运行状态目录，默认为项目根目录下 .runtime/tender-plan。",
    )
    parser.add_argument(
        "--detail-cache-ttl-days",
        type=int,
        default=DETAIL_CACHE_TTL_DAYS,
        help="详情缓存有效天数，默认 30 天。",
    )
    parser.add_argument(
        "--refresh-details",
        action="store_true",
        help="忽略未过期详情缓存并重新请求。",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL,
        help="所有源站请求的最小全局间隔秒数，默认 0.25。",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="不合并现有 latest.json，按指定窗口重建。",
    )
    parser.add_argument(
        "--construction-data",
        default="auto",
        help="施工标讯 latest.json 路径或 URL；默认优先读取本机标讯项目。",
    )
    parser.add_argument(
        "--no-construction-match",
        action="store_true",
        help="跳过重点资金计划与施工标讯关联。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.workers < 1:
        raise SystemExit("--workers 必须大于等于 1")
    if args.detail_cache_ttl_days < 0:
        raise SystemExit("--detail-cache-ttl-days 不能为负数")
    if args.request_interval < 0:
        raise SystemExit("--request-interval 不能为负数")

    now = datetime.now(TIMEZONE)
    runtime_dir = args.state_dir or args.site_dir.parent.parent / ".runtime/tender-plan"
    state_path = runtime_dir / "run-state.json"
    cache_path = runtime_dir / "detail-cache.json"
    latest_path = args.site_dir / "data/latest.json"

    with exclusive_run_lock(runtime_dir / "collect.lock"):
        load_warnings: list[str] = []
        state = {
            **empty_state(),
            **read_json_file(state_path, empty_state(), load_warnings, "运行状态"),
        }
        detail_cache = {
            **empty_detail_cache(),
            **read_json_file(
                cache_path, empty_detail_cache(), load_warnings, "详情缓存"
            ),
        }
        if not isinstance(detail_cache.get("entries"), dict):
            detail_cache["entries"] = {}
        if not isinstance(detail_cache.get("failures"), dict):
            detail_cache["failures"] = {}
        existing_payload = read_json_file(
            latest_path, {"items": []}, load_warnings, "现有 latest.json"
        )
        manual_pub_date = args.pub_date or ("l3m" if args.rebuild else None)
        args.mode, args.pub_date = select_run(state, manual_pub_date, now)
        if not existing_payload.get("items") and args.mode != "manual":
            args.mode, args.pub_date = "bootstrap", "l3m"

        state["last_attempt_at"] = now.isoformat()
        atomic_write_json(state_path, state)
        cache_seeded = seed_detail_cache(detail_cache, existing_payload, now)
        pacer = RequestPacer(args.request_interval)
        payload, list_complete = collect(
            args,
            existing_payload,
            detail_cache,
            now,
            pacer,
            load_warnings,
        )
        payload["stats"]["detail_cache_seeded"] = cache_seeded

        if not args.no_construction_match:
            construction_source = resolve_construction_source(args.construction_data)
            try:
                construction_payload = load_json_source(construction_source)
                merge_priority_notices(payload, construction_payload, construction_source)
            except Exception as error:
                payload["warnings"].append(
                    f"施工标讯关联异常：{type(error).__name__}: {error}"
                )
                payload["priority_notices"] = []
                payload["stats"].update(
                    {
                        "ultra_long_projects": len(
                            latest_ultra_long_plans(payload.get("items", []))
                        ),
                        "priority_projects": 0,
                        "priority_notices": 0,
                        "priority_new_today": 0,
                    }
                )

        prune_detail_cache(detail_cache, payload.get("items", []))
        atomic_write_json(cache_path, detail_cache)
        write_payload(args.site_dir, payload)
        is_partial = bool(
            args.keywords
            or (args.max_pages and not args.all_pages)
            or args.no_details
        )
        if list_complete and not is_partial:
            complete_state(state, now, args.mode, args.pub_date)
        atomic_write_json(state_path, state)

    print(json.dumps(payload["stats"], ensure_ascii=False))
    if payload["warnings"]:
        print(json.dumps({"warnings": payload["warnings"][:10]}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
