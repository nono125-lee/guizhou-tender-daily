from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..construction_rules import plain_text, qualification_matches, qualification_section
from ..normalize import clean_text
from ..public_export import normalize_public_item
from .guizhou_ztb import _deadline, _parties, _project_content, _registration_period


LIST_API = "https://ggzy.guizhou.gov.cn/tradeInfo/es/list"
MONEY_RE = re.compile(
    r"(?:合同估算价|预算金额|采购预算|最高限价|项目总投资)[为：:\s]*"
    r"([¥￥]?\s?[\d,.]+\s*(?:万元|元))"
)


def _request(url: str, payload: dict | None = None) -> str:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 TenderConstruction/1.0",
            "Content-Type": "application/json;charset=UTF-8",
        },
    )
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def collect(config: dict, sources: list[dict], lookback_days: int = 3) -> list[dict]:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    start = now - timedelta(days=lookback_days)
    results = {}
    for source in [item for item in sources if item["collector"] == "ggzy"]:
        payload = {
            "channelId": source["channel_id"],
            "pageNum": 1,
            "pageSize": 100,
            "startTime": start.strftime("%Y-%m-%d 00:00:00"),
            "endTime": now.strftime("%Y-%m-%d 23:59:59"),
        }
        listings = json.loads(_request(LIST_API, payload)).get("list", [])
        for listing in listings:
            announcement = clean_text(listing.get("announcement"))
            if "公告" not in announcement or any(
                word in announcement for word in ("变更", "结果", "证明", "计划")
            ):
                continue
            url = listing.get("apiUrl", "")
            html_text = _request(url)
            text = plain_text(html_text)
            title = clean_text(listing.get("docTitle"))
            qualification = qualification_section(text)
            matches = qualification_matches(title, qualification, config)
            if not matches:
                continue
            buyer, agency = _parties(text, "")
            date_value = datetime.fromtimestamp(
                int(listing["docRelTime"]) / 1000,
                ZoneInfo("Asia/Shanghai"),
            ).date().isoformat()
            budget = ""
            money = MONEY_RE.search(text)
            if money:
                budget = clean_text(money.group(1))
            item = normalize_public_item(
                {
                    "published_at": date_value,
                    "date_basis": "official",
                    "title": title,
                    "project_name": title,
                    "url": url,
                    "budget": budget,
                    "project_content": _project_content(text),
                    "qualification_requirement": qualification,
                    "location": clean_text(listing.get("docSourceName"))
                    or "贵州省",
                    "buyer": buyer,
                    "agency": agency,
                    "bid_deadline": _deadline(text),
                    "registration_period": _registration_period(text, date_value),
                    "matched_keywords": matches,
                    "source_name": source["name"],
                }
            )
            item["source_name"] = source["name"]
            results[url] = item
    return list(results.values())
