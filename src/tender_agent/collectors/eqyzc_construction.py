from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from ..construction_rules import qualification_matches
from ..normalize import clean_text
from ..public_export import normalize_public_item
from .eqyzc import (
    DETAIL_API,
    LIST_API,
    PLATFORM_TIMEZONE,
    _budget_text,
    _datetime_text,
    _page_payload,
    _request_json,
)


def collect(config: dict, sources: list[dict], lookback_days: int = 3) -> list[dict]:
    cutoff = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(
        days=lookback_days
    )
    release_start = int(
        datetime.combine(cutoff, datetime.min.time(), PLATFORM_TIMEZONE).timestamp()
        * 1000
    )
    release_end = int(datetime.now(ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    results = {}
    eq_sources = [source for source in sources if source["collector"] == "eqyzc"]
    for source in eq_sources:
        payload = _page_payload(1, 100, release_start, release_end)
        payload["noticeType"] = ""
        payload["platformIdList"] = [source["platform_id"]]
        response = _request_json(LIST_API, payload)
        for listing in response.get("data", {}).get("list", []):
            if int(listing.get("noticeType") or 0) != 1:
                continue
            query = urlencode({"id": listing["id"], "noticeType": 1})
            try:
                detail_payload = _request_json(f"{DETAIL_API}?{query}")
            except RuntimeError:
                continue
            detail = detail_payload.get("data", {}).get("biddingNotice") or {}
            title = clean_text(
                listing.get("businessName") or detail.get("businessName")
            )
            qualification = clean_text(
                detail.get("qualificationRequirement")
                or detail.get("qualificationLevel")
                or detail.get("otherRequirements")
            )
            matches = qualification_matches(title, qualification, config)
            if not matches:
                continue
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
            host = urlsplit(source["url"]).netloc
            url = (
                f"https://{host}/#/trade-info-detail?"
                + urlencode(
                    {
                        "id": listing["id"],
                        "noticeType": 1,
                        "publishStatus": 1,
                    }
                )
            )
            item = normalize_public_item(
                {
                    "published_at": _datetime_text(
                        listing.get("releaseTime") or detail.get("releaseTime"),
                        False,
                    ),
                    "date_basis": "official",
                    "title": title,
                    "project_name": clean_text(detail.get("purchaseProjectName")),
                    "url": url,
                    "budget": _budget_text(
                        detail.get("reckonPrice"), detail.get("extMap")
                    ),
                    "project_content": clean_text(
                        detail.get("biddingScope")
                        or detail.get("projectOverview")
                    ),
                    "qualification_requirement": qualification,
                    "location": clean_text(detail.get("address")) or "贵州省",
                    "buyer": clean_text(detail.get("tendererName")),
                    "agency": clean_text(
                        detail.get("tenderAgencyName")
                        or detail.get("handleUnitName")
                    ),
                    "bid_deadline": _datetime_text(
                        detail.get("bidEndTime"), True
                    ),
                    "registration_period": (
                        f"{registration_start}至{registration_end}"
                        if registration_start and registration_end
                        else ""
                    ),
                    "matched_keywords": matches,
                    "source_name": source["name"],
                }
            )
            item["source_name"] = source["name"]
            results[url] = item
    return list(results.values())
