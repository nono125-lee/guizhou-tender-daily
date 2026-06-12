from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..construction_incremental import (
    collection_window,
    complete_source,
    detail_fingerprint,
    record_failure,
    record_processed,
    record_project,
    retry_listings,
    should_process,
)
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


def collect(
    config: dict,
    sources: list[dict],
    lookback_days: int = 7,
    skip_urls: set[str] | None = None,
    source_state: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if source_state is None:
        start = now - timedelta(days=lookback_days)
        mode = "legacy"
    else:
        start, mode = collection_window(source_state, now)
    results = {}
    skipped = skip_urls or set()
    for source in [item for item in sources if item["collector"] == "ggzy"]:
        discovered = list(_page_listings(source, start, now))
        if source_state is not None:
            discovered.extend(retry_listings(source_state))
        listings = {
            str(listing.get("metaDataId") or listing.get("id")): listing
            for listing in discovered
            if listing.get("metaDataId") or listing.get("id")
        }
        ordered = sorted(
            listings.values(),
            key=lambda item: (
                any(
                    word in clean_text(item.get("announcement"))
                    for word in ("变更", "澄清", "答疑")
                ),
                int(item.get("docRelTime") or 0)
                if any(
                    word in clean_text(item.get("announcement"))
                    for word in ("变更", "澄清", "答疑")
                )
                else 0,
            ),
        )
        for listing in ordered:
            notice_id = str(listing.get("metaDataId") or listing.get("id"))
            announcement = clean_text(listing.get("announcement"))
            project_code = clean_text(listing.get("tenderProjectCode"))
            release_at = ""
            if listing.get("docRelTime"):
                release_at = datetime.fromtimestamp(
                    int(listing["docRelTime"]) / 1000,
                    ZoneInfo("Asia/Shanghai"),
                ).isoformat()
            if source_state is not None and not should_process(
                source_state, notice_id
            ):
                continue
            url = listing.get("apiUrl", "")
            is_change = any(
                word in announcement for word in ("变更", "澄清", "答疑")
            )
            is_original = (
                "公告" in announcement
                and not is_change
                and not any(
                    word in announcement
                    for word in ("结果", "证明", "计划")
                )
            )
            if not is_original and not is_change:
                if source_state is not None:
                    record_processed(
                        source_state,
                        notice_id,
                        status="ignored_notice_type",
                        release_at=release_at,
                        project_code=project_code,
                        url=url,
                    )
                continue
            if is_change:
                project = (
                    source_state.get("projects", {}).get(project_code)
                    if source_state is not None
                    else None
                )
                if not project:
                    if source_state is not None:
                        record_processed(
                            source_state,
                            notice_id,
                            status="unlinked_change",
                            release_at=release_at,
                            project_code=project_code,
                            url=url,
                        )
                    continue
                target_url = project.get("url", "")
                if target_url in skipped:
                    if source_state is not None:
                        record_processed(
                            source_state,
                            notice_id,
                            status="frozen",
                            release_at=release_at,
                            project_code=project_code,
                            url=target_url,
                        )
                    continue
                try:
                    html_text = _request(url)
                except Exception as error:
                    if source_state is not None:
                        record_failure(
                            source_state, notice_id, listing, error, now
                        )
                    continue
                text = plain_text(html_text)
                results[f"change:{notice_id}"] = {
                    "url": target_url,
                    "_is_change": True,
                    "change_published_at": release_at[:10],
                    "project_code": project_code,
                    "source_notice_id": notice_id,
                    "bid_deadline": _deadline(text),
                    "registration_period": _registration_period(
                        text, release_at[:10]
                    ),
                }
                if source_state is not None:
                    source_state.setdefault("detail_fingerprints", {})[
                        notice_id
                    ] = detail_fingerprint(text)
                    record_processed(
                        source_state,
                        notice_id,
                        status="change_applied",
                        release_at=release_at,
                        project_code=project_code,
                        url=target_url,
                    )
                continue

            if not url:
                if source_state is not None:
                    record_processed(
                        source_state,
                        notice_id,
                        status="missing_url",
                        release_at=release_at,
                        project_code=project_code,
                    )
                continue
            if url in skipped:
                if source_state is not None:
                    record_project(
                        source_state,
                        project_code,
                        url=url,
                        notice_id=notice_id,
                    )
                    record_processed(
                        source_state,
                        notice_id,
                        status="frozen",
                        release_at=release_at,
                        project_code=project_code,
                        url=url,
                    )
                continue
            try:
                html_text = _request(url)
            except Exception as error:
                if source_state is not None:
                    record_failure(
                        source_state, notice_id, listing, error, now
                    )
                continue
            text = plain_text(html_text)
            title = clean_text(listing.get("docTitle"))
            qualification = qualification_section(text)
            matches = qualification_matches(title, qualification, config)
            if not matches:
                if source_state is not None:
                    source_state.setdefault("detail_fingerprints", {})[
                        notice_id
                    ] = detail_fingerprint(text)
                    record_processed(
                        source_state,
                        notice_id,
                        status="not_matched",
                        release_at=release_at,
                        project_code=project_code,
                        url=url,
                    )
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
                    "project_code": project_code,
                    "source_notice_id": notice_id,
                }
            )
            item["source_name"] = source["name"]
            results[url] = item
            if source_state is not None:
                source_state.setdefault("detail_fingerprints", {})[
                    notice_id
                ] = detail_fingerprint(text)
                record_project(
                    source_state,
                    project_code,
                    url=url,
                    notice_id=notice_id,
                )
                record_processed(
                    source_state,
                    notice_id,
                    status="matched",
                    release_at=release_at,
                    project_code=project_code,
                    url=url,
                )
        if source_state is not None:
            complete_source(source_state, now, mode)
    return list(results.values())
