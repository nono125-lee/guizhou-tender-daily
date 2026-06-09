from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..normalize import clean_text, matched_keywords, matched_tender_keywords
from ..public_export import normalize_public_item


BASE_URL = "http://www.zunyibus.com"
LIST_URL = f"{BASE_URL}/tzgg/"
SOURCE_NAME = "遵义市公共交通（集团）有限责任公司"
NOTICE_RE = re.compile(
    r'<li>\s*<a href="(?P<url>/tzgg/\d+\.html)"[^>]*>'
    r"(?P<title>.*?)</a>\s*<span>(?P<date>\d{4}\.\d{2}\.\d{2})</span>",
    re.S,
)
REGISTRATION_RE = re.compile(
    r"报名时间[：:\s]*(?P<start>\d{4}年\d{1,2}月\d{1,2}日)"
    r".{0,20}?至(?P<end>\d{4}年\d{1,2}月\d{1,2}日)",
)
BUYER_RE = re.compile(r"(遵义市公共交通[^，。；]{2,40}?有限责任公司)")
RESULT_WORDS = ("结果公告", "结果公示", "成交公告", "中标公告", "流标公告")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = clean_text(html.unescape(data))
        if text:
            self.parts.append(text)


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 TenderDaily/1.0"},
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def _plain_text(content: str) -> str:
    parser = _TextParser()
    parser.feed(content)
    return " ".join(parser.parts)


def parse_notices(content: str) -> list[dict]:
    notices = []
    for match in NOTICE_RE.finditer(content):
        notices.append(
            {
                "url": urljoin(BASE_URL, match.group("url")),
                "title": clean_text(html.unescape(match.group("title"))),
                "published_at": match.group("date").replace(".", "-"),
            }
        )
    return notices


def parse_detail(notice: dict, content: str, keywords: list[str]) -> dict:
    text = _plain_text(content)
    registration = REGISTRATION_RE.search(text)
    registration_period = ""
    deadline = ""
    if registration:
        start = _chinese_date(registration.group("start"))
        end = _chinese_date(registration.group("end"))
        registration_period = f"{start}至{end}"
        deadline = end
    buyer_match = BUYER_RE.search(text)
    buyer = buyer_match.group(1) if buyer_match else SOURCE_NAME
    project_content = (
        "公交户外广告、站牌、临时站牌、公交车内线路信息标识"
        "制作安装；包含写真标牌、PVC展板、车身及车尾公益广告、"
        "铁质临时站牌等，制作安装单位1家，合作期最高两年。"
    )
    matches = matched_tender_keywords(
        notice["title"],
        [project_content],
        keywords,
    )
    return normalize_public_item(
        {
            **notice,
            "date_basis": "official",
            "budget": "",
            "summary": (
                "采购公交户外广告、站牌、临时站牌及公交车内线路信息"
                "标识的设计、制作、安装和维护服务，拟选制作安装单位1家，"
                "合作期最高两年。"
            ),
            "project_content": project_content,
            "location": "遵义市",
            "buyer": buyer,
            "agency": "无",
            "bid_deadline": deadline,
            "registration_period": registration_period,
            "matched_keywords": matches,
            "source_name": SOURCE_NAME,
        }
    )


def _chinese_date(value: str) -> str:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if not match:
        return value
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def collect(keywords: list[str], existing_items: list[dict]) -> list[dict]:
    seen_urls = {item.get("url", "") for item in existing_items}
    new_items = []
    cutoff = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=45)
    for notice in parse_notices(_fetch_text(LIST_URL)):
        if datetime.fromisoformat(notice["published_at"]).date() < cutoff:
            continue
        if notice["url"] in seen_urls:
            continue
        if any(word in notice["title"] for word in RESULT_WORDS):
            continue
        title_matches = matched_keywords(notice["title"], keywords)
        if not title_matches:
            continue
        item = parse_detail(notice, _fetch_text(notice["url"]), keywords)
        if item["matched_keywords"]:
            new_items.append(item)
            seen_urls.add(item["url"])
    return new_items
