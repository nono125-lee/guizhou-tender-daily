from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_tender_keywords
from ..public_export import normalize_date, normalize_public_item
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
from .guizhou_ztb import (
    MONEY_RE,
    _deadline,
    _extract,
    _parties,
    _plain_text,
    _registration_period,
)


BASE_URL = "https://cgjy.tobacco.com.cn"
SOURCE_NAME = "中烟电子采购平台"
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")
SECTIONS = ("zbNotice", "competition")
REGION_INCLUDE = (
    "贵州",
    "贵阳",
    "遵义",
    "六盘水",
    "安顺",
    "毕节",
    "铜仁",
    "黔南",
    "黔东南",
    "黔西南",
    "贵安",
    "仁怀",
    "清镇",
    "福泉",
    "凯里",
    "都匀",
    "兴义",
)
RESULT_NOTICE_WORDS = (
    "结果公告",
    "中标公告",
    "成交公告",
    "候选人",
    "流标",
    "废标",
    "终止",
    "中止",
    "暂停",
    "变更",
    "澄清",
    "答疑",
    "延期",
    "更正",
)
LIST_RE = re.compile(
    r'<a\s+href="(?P<url>/[^"]+/\d+\.jhtml)"[^>]*>.*?'
    r'<span\s+class="span_hover"\s+title="(?P<title>[^"]+)"[^>]*>'
    r'.*?</span>.*?<i[^>]*>.*?(?P<date>\d{4}-\d{2}-\d{2}).*?</i>',
    re.IGNORECASE | re.DOTALL,
)
TITLE_RE = re.compile(r"<h2[^>]*>(?P<title>.*?)</h2>", re.IGNORECASE | re.DOTALL)
PUBLISH_RE = re.compile(
    r"发布时间[：:]\s*(?P<date>\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)"
)
DEADLINE_RE = re.compile(
    r"(?:递交截止时间|投标截止时间|响应截止时间|开标时间)[：:\s]*"
    r"(?P<date>\d{4}[年-]\d{1,2}[月-]\d{1,2}日?"
    r"(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|\:\d{1,2})?)?)"
)
PROJECT_NAME_RE = re.compile(
    r"(?:项目名称|项目名)\s*[：:]\s*(?P<value>.{2,180}?)(?=\s+(?:项目编号|采购内容|招标内容|采购范围|招标范围|项目概况|资金|预算|最高限价|二[、.]|三[、.]|$))"
)
BLOCK_END_RE = re.compile(r"</(?:p|div|h[1-6]|li|tr|table)>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SECTION_LABEL_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.．]\s*|\d+(?:\.\d+)?[、.．]?\s*)?"
    r"(?:"
    r"项目概况(?:\s*(?:和|及|与)\s*(?:招标|采购)?\s*范围)?|"
    r"招标内容|采购内容(?:与范围)?|招标范围|采购范围"
    r")\s*[：:]?\s*(?P<value>.*)$"
)
SECTION_STOP_RE = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十]+[、.．]\s*|"
    r"\d+[、.．]\s*(?!\d)|"
    r"(?:供应商|投标人|申请人|响应人).{0,16}资格|"
    r"(?:获取|购买|领取|报名).{0,20}(?:时间|期限|方式)|"
    r"(?:响应文件|投标文件).{0,16}(?:截止时间|递交)|"
    r"(?:递交截止时间|开标时间|联系方式|联系人|联系电话)|"
    r"(?:采购人|招标人|采购单位|采购代理机构|招标代理机构|代理机构)"
    r"\s*[：:]"
    r")"
)


def _fetch_text(url: str, timeout: int = 20, attempts: int = 3) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"中烟平台页面访问失败：{type(last_error).__name__}") from last_error


def _page_url(section: str, page: int) -> str:
    if page == 1:
        return f"{BASE_URL}/{section}/index.jhtml"
    return f"{BASE_URL}/{section}/index_{page}.jhtml"


def _list_items(content: str) -> list[dict]:
    items = []
    for match in LIST_RE.finditer(content):
        title = clean_text(html.unescape(match.group("title")))
        items.append(
            {
                "url": urljoin(BASE_URL, match.group("url")),
                "title": title,
                "published_at": match.group("date"),
            }
        )
    return items


def _article_html(content: str) -> str:
    match = re.search(
        r'<div\s+class="service_title"[^>]*>.*?(?P<body><h2.*?)(?:<div\s+class="copyright_title"|</body>)',
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group("body")
    return content


def _content_lines(content: str) -> list[str]:
    with_breaks = BLOCK_END_RE.sub("\n", content or "")
    plain = html.unescape(TAG_RE.sub(" ", with_breaks))
    return [clean_text(line) for line in plain.splitlines() if clean_text(line)]


def _project_content_from_html(content: str) -> str:
    lines = _content_lines(content)
    for index, line in enumerate(lines):
        match = SECTION_LABEL_RE.match(line)
        if not match:
            continue
        values = []
        value = clean_text(match.group("value"))
        if value:
            values.append(value)
        for following in lines[index + 1:]:
            if SECTION_STOP_RE.match(following):
                break
            nested = SECTION_LABEL_RE.match(following)
            values.append(
                clean_text(nested.group("value")) if nested else following
            )
        result = clean_text(" ".join(values)).strip("：:；;。 ")
        if result and not result.startswith("详见"):
            return result
    return ""


def _party_from_lines(content: str) -> tuple[str, str]:
    buyer = ""
    agency = ""
    for line in _content_lines(content):
        if not buyer:
            match = re.search(
                r"(?:采购人|招标人|采购单位)\s*(?:名称)?\s*(?:[：:]|为)\s*(.{2,80})$",
                line,
            )
            if match:
                buyer = clean_text(match.group(1)).strip("：:，,；;。 ")
        if not agency:
            match = re.search(
                r"(?:采购代理机构|招标代理机构|代理机构)\s*(?:名称)?\s*(?:[：:]|为)\s*(.{2,80})$",
                line,
            )
            if match:
                agency = clean_text(match.group(1)).strip("：:，,；;。 ")
    return buyer, agency


def _deadline_text(text: str) -> str:
    value = _deadline(text)
    if value:
        return value
    match = DEADLINE_RE.search(text)
    if not match:
        return ""
    return normalize_date(match.group("date"), "", True)


def _publish_date(content: str, fallback: str) -> str:
    match = PUBLISH_RE.search(_plain_text(content))
    if match:
        return normalize_date(match.group("date"), "", False)
    return normalize_date(fallback, "", False)


def _title(content: str, fallback: str) -> str:
    match = TITLE_RE.search(content)
    if match:
        return clean_text(html.unescape(TAG_RE.sub(" ", match.group("title"))))
    return clean_text(fallback)


def _project_name(title: str, text: str) -> str:
    match = PROJECT_NAME_RE.search(text)
    if match:
        value = clean_text(match.group("value")).strip("：:；;。 ")
        if value:
            return value
    return re.sub(
        r"[-_\s]*(?:公开招标|竞争谈判|竞争性谈判|询价|询比|磋商)?"
        r"(?:招标|采购)?公告$",
        "",
        clean_text(title),
    ).strip()


def _has_region(text: str) -> bool:
    return any(name in clean_text(text) for name in REGION_INCLUDE)


def _is_result_notice(title: str) -> bool:
    return any(word in title for word in RESULT_NOTICE_WORDS)


def _keyword_signature(keywords: list[str]) -> str:
    value = "\n".join(sorted(set(keywords))).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _load_state(path: Path, keywords: list[str]) -> dict:
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    signature = _keyword_signature(keywords)
    if state.get("keyword_signature") != signature:
        state = {"processed": {}, "failed_urls": []}
    state["keyword_signature"] = signature
    state.setdefault("processed", {})
    state.setdefault("failed_urls", [])
    return state


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def item_from_detail(listing: dict, detail_html: str, keywords: list[str]) -> dict | None:
    article = _article_html(detail_html)
    text = _plain_text(article)
    title = _title(article, listing.get("title", ""))
    if _is_result_notice(title):
        return None
    project_name = _project_name(title, text)
    project_content = _project_content_from_html(article)
    if not _has_region(" ".join([title, project_name, project_content, text[:1200]])):
        return None
    matches = matched_tender_keywords(project_name, [project_content], keywords)
    if not matches:
        return None
    published_at = _publish_date(article, listing.get("published_at", ""))
    buyer, agency = _parties(text, "")
    line_buyer, line_agency = _party_from_lines(article)
    return normalize_public_item(
        {
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": project_name,
            "url": listing["url"],
            "budget": _extract(MONEY_RE, text),
            "summary": project_content,
            "project_content": project_content,
            "project_content_basis": "section-v3",
            "location": "贵州省",
            "buyer": buyer or line_buyer,
            "agency": agency or line_agency,
            "bid_deadline": _deadline_text(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
        }
    )


def collect(
    keywords: list[str],
    existing_items: list[dict],
    state_path: str | Path,
    lookback_days: int = 7,
    max_pages: int = 30,
) -> list[dict]:
    state_file = Path(state_path)
    state = _load_state(state_file, keywords)
    processed = state["processed"]
    failed_urls = set(state["failed_urls"])
    existing_urls = {item.get("url", "") for item in existing_items}
    cutoff = datetime.now(PLATFORM_TIMEZONE).date() - timedelta(days=lookback_days)
    candidates: list[dict] = []

    for section in SECTIONS:
        for page in range(1, max_pages + 1):
            listings = _list_items(_fetch_text(_page_url(section, page)))
            if not listings:
                break
            stop_section = False
            for listing in listings:
                try:
                    publish_date = datetime.fromisoformat(
                        listing["published_at"][:10]
                    ).date()
                except ValueError:
                    publish_date = datetime.now(PLATFORM_TIMEZONE).date()
                if publish_date < cutoff:
                    stop_section = True
                    continue
                if listing["url"] in existing_urls or (
                    listing["url"] in processed and listing["url"] not in failed_urls
                ):
                    continue
                if _is_result_notice(listing["title"]):
                    processed[listing["url"]] = {
                        "published_at": listing["published_at"],
                        "status": "result_notice",
                    }
                    continue
                candidates.append(listing)
            if stop_section:
                break

    items = []
    new_failed_urls: set[str] = set()
    for listing in candidates:
        try:
            item = item_from_detail(listing, _fetch_text(listing["url"]), keywords)
        except Exception:
            new_failed_urls.add(listing["url"])
            continue
        processed[listing["url"]] = {
            "published_at": listing.get("published_at", ""),
            "status": "matched" if item else "not_matched",
        }
        failed_urls.discard(listing["url"])
        if item:
            items.append(item)
            existing_urls.add(item["url"])

    retention_cutoff = cutoff - timedelta(days=38)
    state["processed"] = {
        url: result
        for url, result in processed.items()
        if not result.get("published_at")
        or datetime.fromisoformat(result["published_at"][:10]).date() >= retention_cutoff
    }
    state["failed_urls"] = sorted(failed_urls | new_failed_urls)
    state["last_run_at"] = datetime.now(PLATFORM_TIMEZONE).isoformat()
    _save_state(state_file, state)
    return items


def construction_item(listing: dict, detail_html: str, config: dict) -> dict | None:
    article = _article_html(detail_html)
    text = _plain_text(article)
    title = _title(article, listing.get("title", ""))
    if _is_result_notice(title):
        return None
    project_name = _project_name(title, text)
    qualification = qualification_section(text)
    matches = qualification_matches(project_name or title, qualification, config)
    if not matches:
        return None
    published_at = _publish_date(article, listing.get("published_at", ""))
    buyer, agency = _parties(text, "")
    line_buyer, line_agency = _party_from_lines(article)
    project_content = _project_content_from_html(article)
    return normalize_public_item(
        {
            **project_match_fields(text),
            "published_at": published_at,
            "date_basis": "official",
            "title": title,
            "project_name": project_name,
            "url": listing["url"],
            "budget": _extract(MONEY_RE, text),
            "project_content": project_content,
            "qualification_requirement": qualification,
            "location": "贵州省",
            "buyer": buyer or line_buyer,
            "agency": agency or line_agency,
            "bid_deadline": _deadline_text(text),
            "registration_period": _registration_period(text, published_at),
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
            "source_notice_id": listing["url"].rsplit("/", 1)[-1].replace(".jhtml", ""),
        }
    )


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
    candidates = []
    for section in SECTIONS:
        for page in range(1, 8):
            listings = _list_items(_fetch_text(_page_url(section, page)))
            if not listings:
                break
            stop = False
            for listing in listings:
                try:
                    publish_date = datetime.fromisoformat(
                        listing["published_at"][:10]
                    ).date()
                except ValueError:
                    publish_date = now.date()
                if publish_date < cutoff:
                    stop = True
                    continue
                if _is_result_notice(listing["title"]):
                    continue
                if not _has_region(listing["title"]):
                    continue
                notice_id = listing["url"]
                if source_state is not None and not should_process(
                    source_state, notice_id
                ):
                    continue
                candidates.append(listing)
            if stop:
                break
    items = {}
    for listing in candidates:
        notice_id = listing["url"]
        detail_html = _fetch_text(listing["url"])
        item = construction_item(listing, detail_html, config)
        if source_state is not None:
            record_processed(
                source_state,
                notice_id,
                status="matched" if item else "not_matched",
                release_at=listing.get("published_at", ""),
                url=listing["url"],
            )
        if item:
            items[item["url"]] = item
    if source_state is not None:
        complete_source(source_state, now, mode)
    return list(items.values())
