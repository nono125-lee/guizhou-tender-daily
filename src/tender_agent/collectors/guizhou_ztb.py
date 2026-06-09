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

from ..normalize import clean_text, matched_tender_keywords
from ..public_export import normalize_date, normalize_public_item


BASE_URL = "http://ztb.guizhou.gov.cn"
DETAIL_API = f"{BASE_URL}/api/trade"
DETAIL_ID_RE = re.compile(r"[?&]id=(\d+)")
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
REGISTRATION_PATTERNS = [
    re.compile(
        r"(?:获取|购买|领取)(?:采购|磋商|招标|询比)?文件.{0,20}?"
        r"(?:时间|期限)[：:\s]*"
        r"(?P<start>\d{4}年\d{1,2}月\d{1,2}日)"
        r".{0,20}?(?:至|到|-)"
        r"(?P<end>\d{4}年\d{1,2}月\d{1,2}日)"
    ),
    re.compile(
        r"报名时间[：:\s]*"
        r"(?P<start>\d{4}年\d{1,2}月\d{1,2}日)"
        r".{0,20}?(?:至|到|-)"
        r"(?P<end>\d{4}年\d{1,2}月\d{1,2}日)"
    ),
]
PROJECT_CONTENT_PATTERNS = [
    re.compile(
        r"(?:项目概况和招标范围|项目概况及招标范围|招标或采购范围|"
        r"招标范围|采购范围|采购主要内容|招标内容|采购内容及主要技术参数|"
        r"采购内容|采购需求|项目主要内容|项目内容)"
        r"[：:\s]*(.{2,800}?)"
        r"(?=(?:供应商|投标人|申请人|响应人).{0,12}?资格|"
        r"(?:获取|购买|领取).{0,12}?(?:采购|磋商|招标|询比)?文件|"
        r"(?:响应文件|投标文件).{0,12}?(?:递交|提交|截止)|"
        r"(?:采购数量|采购预算|预算金额|最高限价|服务期|服务期限|工期|交货期|"
        r"质量标准|联系方式)[：:\s]|"
        r"[一二三四五六七八九十]+、(?:供应商|投标人|申请人|获取|报名|响应)|$)"
    ),
    re.compile(
        r"(?:项目概况|项目基本概况介绍、用途|"
        r"简要技术要求、服务和安全要求)"
        r"[：:\s]*(.{2,600}?)"
        r"(?=(?:供应商|投标人|申请人|响应人).{0,12}?资格|"
        r"(?:采购数量|采购预算|预算金额|最高限价|服务期|服务期限|工期|交货期|"
        r"质量标准|联系方式)[：:\s]|"
        r"[一二三四五六七八九十]+、(?:供应商|投标人|申请人|获取|报名|响应)|$)"
    ),
]
PROJECT_NAME_PATTERNS = [
    re.compile(
        r"(?:项目名称|标项名称)[：:\s]*"
        r"(.{2,180}?)"
        r"(?=(?:项目编号|标项编号|采购方式|招标方式|数量|预算金额|"
        r"采购预算|最高限价|资金来源|[；。]|$))"
    ),
]
PARTY_END_RE = re.compile(
    r"\s*(?:统一社会信用代码|项目联系人|联\s*系\s*人|联系人|"
    r"联系地址|地\s*址|地址|联系电话|电\s*话|电话|"
    r"采购代理机构|招标代理机构|代理机构|"
    r"采购人|招标人|邮编|邮箱|$)"
)
BUYER_LABEL_RE = re.compile(
    r"(?:采购人|招标人|采购单位)\s*"
    r"(?:(?:信息)?\s*(?:名称|名\s*称|全称)\s*[：:]?|为\s*|[：:])\s*"
)
AGENCY_LABEL_RE = re.compile(
    r"(?:招标人委托的代理机构|采购代理机构|招标代理机构|代理机构)"
    r"\s*(?:(?:信息)?\s*(?:名称|名\s*称|全称)\s*[：:]?|为\s*|[：:])\s*"
)
ENTRUSTED_BUYER_RE = re.compile(
    r"受\s*(.{2,80}?)\s*(?:委托|（以下简称|\(以下简称)"
)
INVALID_PARTY_WORDS = (
    "指定地点",
    "不予受理",
    "公告期限",
    "联系方式",
    "联系人",
    "联系电话",
    "项目负责人",
    "签名",
    "采购范围",
    "响应单价",
    "投标文件",
    "信息 名称",
    "信息 名 称",
    "信息 联 系 人",
    "采购人的",
    "（如有）",
    "工作人员",
    "公告未载明",
)


def _plain_text(content: str) -> str:
    return SPACE_RE.sub(
        " ",
        html.unescape(TAG_RE.sub(" ", content or "")),
    ).strip()


def _fetch_json(
    url: str,
    retries: int = 2,
    timeout: int = 15,
) -> dict | None:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TenderDaily/1.0",
            "Accept": "application/json",
        },
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except HTTPError as error:
            if error.code == 404:
                return None
        except (URLError, OSError, TimeoutError, json.JSONDecodeError):
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


def _registration_period(text: str, publish_date: str) -> str:
    for pattern in REGISTRATION_PATTERNS:
        match = pattern.search(text)
        if match:
            start = normalize_date(match.group("start"), publish_date, False)
            end = normalize_date(match.group("end"), publish_date, False)
            return f"{start}至{end}"
    return ""


def _project_name(title: str, text: str) -> str:
    for pattern in PROJECT_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            value = clean_text(match.group(1)).strip("：:；;。 ")
            if value:
                return value
    return re.sub(
        r"(?:招标|采购|询比|磋商|谈判|遴选|征集|计划|更正|变更|答疑|澄清)"
        r"(?:公告|公示)?$",
        "",
        clean_text(title),
    ).strip()


def _project_content(text: str, fallback: str = "") -> str:
    for pattern in PROJECT_CONTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            value = clean_text(match.group(1)).strip("：:；;。 ")
            if (
                value
                and not value.startswith("详见")
                and value not in {"详见采购文件", "详见磋商文件", "详见招标文件"}
            ):
                return value
    return clean_text(fallback)


def _party_name(text: str, pattern: re.Pattern[str]) -> str:
    for match in pattern.finditer(text):
        candidate = text[match.end():match.end() + 120]
        if candidate.startswith(("委托", "联系人", "不接受", "按照")):
            continue
        end = PARTY_END_RE.search(candidate)
        if end:
            candidate = candidate[:end.start()]
        candidate = clean_text(candidate).strip("：:，,；;。（( ")
        if _valid_party_name(candidate):
            return candidate
    return ""


def _valid_party_name(value: str) -> bool:
    return (
        2 <= len(value) <= 80
        and not any(word in value for word in INVALID_PARTY_WORDS)
        and not re.search(r"[。；;]|(?:\d+\.)", value)
    )


def _parties(text: str, source: str) -> tuple[str, str]:
    buyer = _party_name(text, BUYER_LABEL_RE)
    if not buyer:
        entrusted = ENTRUSTED_BUYER_RE.search(text)
        if entrusted:
            candidate = clean_text(entrusted.group(1)).strip("：:，,；;。（( ")
            if _valid_party_name(candidate):
                buyer = candidate
    agency = clean_text(source) or _party_name(text, AGENCY_LABEL_RE)
    return buyer, agency


def _enrich_existing_item(item: dict) -> dict:
    url = item.get("url", "")
    match = DETAIL_ID_RE.search(url)
    if "ztb.guizhou.gov.cn" not in url or not match:
        return normalize_public_item(item)
    needs_content = (
        not item.get("project_content")
        or len(item.get("project_content", "")) > 400
        or item.get("project_content", "").startswith("详见")
    )
    needs_official_date = item.get("date_basis") != "official"
    needs_parties = not _valid_party_name(
        clean_text(item.get("buyer"))
    ) or not _valid_party_name(clean_text(item.get("agency")))
    if not (needs_content or needs_official_date or needs_parties):
        return normalize_public_item(item)
    data = _fetch_json(f"{DETAIL_API}/{match.group(1)}")
    if not data:
        return normalize_public_item(item)
    content = _plain_text(data.get("Content", ""))
    enriched = dict(item)
    official_publish_date = clean_text(data.get("PublishDate"))
    if official_publish_date:
        enriched["published_at"] = official_publish_date
        enriched["date_basis"] = "official"
    if needs_content and content:
        enriched["project_content"] = _project_content(
            content, item.get("summary", "")
        )
    registration_period = _registration_period(
        content, enriched.get("published_at", "")
    )
    if registration_period:
        enriched["registration_period"] = registration_period
    deadline = _deadline(content)
    if deadline:
        enriched["bid_deadline"] = deadline
    buyer, agency = _parties(content, data.get("Source", ""))
    if buyer:
        enriched["buyer"] = buyer
    elif needs_parties:
        enriched["buyer"] = ""
    enriched["agency"] = agency
    return normalize_public_item(enriched)


def collect(
    keywords: list[str],
    state_path: str | Path,
    existing_path: str | Path,
    max_scan: int = 800,
    stop_after_misses: int = 20,
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
        data = _fetch_json(
            f"{DETAIL_API}/{tender_id}",
            retries=0,
            timeout=4,
        )
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
        project_name = _project_name(title, content)
        project_content = _project_content(content)
        buyer, agency = _parties(content, data.get("Source", ""))
        matches = matched_tender_keywords(
            project_name,
            [project_content],
            keywords,
        )
        if not matches:
            continue
        publish_date = clean_text(data.get("PublishDate"))
        url = f"{BASE_URL}/trade/bulletin/?id={tender_id}"
        if url in seen_urls:
            continue
        new_items.append(
            normalize_public_item(
                {
                "published_at": publish_date,
                "date_basis": "official",
                "title": title,
                "url": url,
                "budget": _extract(MONEY_RE, content),
                "summary": project_content,
                "project_content": project_content,
                "location": "贵州省",
                "buyer": buyer,
                "agency": agency,
                "bid_deadline": _deadline(content),
                "registration_deadline": "",
                "registration_period": _registration_period(
                    content, publish_date
                ),
                "matched_keywords": matches,
                "source_name": "贵州省招标投标公共服务平台",
                }
            )
        )
        seen_urls.add(url)

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    cutoff = today - timedelta(days=45)
    merged = new_items + [
        _enrich_existing_item(item)
        for item in existing.get("items", [])
    ]
    kept = []
    for item in merged:
        if not item.get("url"):
            continue
        try:
            item_date = datetime.fromisoformat(item["published_at"][:10]).date()
        except (ValueError, TypeError, KeyError):
            item_date = today
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
            "new_today": sum(
                item.get("date_basis") == "official"
                and item.get("published_at", "")[:10] == today.isoformat()
                for item in kept
            ),
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
