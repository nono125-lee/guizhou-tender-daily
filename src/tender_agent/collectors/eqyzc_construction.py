from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit
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
    _source_api,
)


def _detail_url(source: dict, listing: dict) -> str:
    host = urlsplit(source["url"]).netloc
    return (
        f"https://{host}/#/trade-info-detail?"
        + urlencode(
            {
                "id": listing["id"],
                "noticeType": 1,
                "publishStatus": 1,
            }
        )
    )


def _release_iso(listing: dict) -> str:
    timestamp = listing.get("releaseTime")
    if not timestamp:
        return ""
    return datetime.fromtimestamp(
        int(timestamp) / 1000,
        PLATFORM_TIMEZONE,
    ).isoformat()


def _page_listings(
    source: dict,
    release_start: int,
    release_end: int,
    page_size: int = 100,
    max_pages: int | None = None,
):
    page_num = 1
    while max_pages is None or page_num <= max_pages:
        payload = _page_payload(page_num, page_size, release_start, release_end)
        payload["noticeType"] = ""
        if source.get("platform_id"):
            payload["platformIdList"] = [source["platform_id"]]
        else:
            payload.pop("platformIdList", None)
        response = _request_json(_source_api(source, "pageEs"), payload)
        listings = response.get("data", {}).get("list", [])
        if not listings:
            break
        yield from listings
        if len(listings) < page_size:
            break
        page_num += 1


def _qualification_text(detail: dict) -> str:
    return clean_text(
        " ".join(
            dict.fromkeys(
                value
                for value in (
                    clean_text(detail.get("qualificationRequirement")),
                    clean_text(detail.get("qualificationLevel")),
                )
                if value
            )
        )
    )


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
        cutoff = now.date() - timedelta(days=lookback_days)
        window_start = datetime.combine(
            cutoff,
            datetime.min.time(),
            PLATFORM_TIMEZONE,
        )
        mode = "legacy"
    else:
        window_start, mode = collection_window(source_state, now)
    release_start = int(
        window_start.astimezone(PLATFORM_TIMEZONE).timestamp() * 1000
    )
    release_end = int(now.timestamp() * 1000)
    results = {}
    skipped = skip_urls or set()
    eq_sources = [source for source in sources if source["collector"] == "eqyzc"]
    for source in eq_sources:
        discovered = list(_page_listings(source, release_start, release_end))
        if source_state is not None:
            discovered.extend(retry_listings(source_state))
        listings = {
            str(listing.get("id")): listing
            for listing in discovered
            if listing.get("id")
        }
        ordered = sorted(
            listings.values(),
            key=lambda item: (
                int(item.get("noticeType") or 0) != 1,
                int(item.get("releaseTime") or 0)
                if int(item.get("noticeType") or 0) != 1
                else 0,
            ),
        )
        for listing in ordered:
            notice_id = str(listing["id"])
            notice_type = int(listing.get("noticeType") or 0)
            release_at = _release_iso(listing)
            project_code = clean_text(listing.get("purchaseProjectCode"))
            if source_state is not None and not should_process(
                source_state, notice_id
            ):
                continue
            if notice_type not in {1, 2}:
                if source_state is not None:
                    record_processed(
                        source_state,
                        notice_id,
                        status="ignored_notice_type",
                        release_at=release_at,
                        project_code=project_code,
                    )
                continue
            if notice_type == 2:
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
                query = urlencode({"id": notice_id, "noticeType": 2})
                try:
                    detail_payload = _request_json(
                        f"{_source_api(source, 'getByTradeId')}?{query}"
                    )
                    detail = (
                        detail_payload.get("data", {}).get(
                            "biddingChangeNotice"
                        )
                        or {}
                    )
                    if not detail:
                        raise RuntimeError("黔云招采变更公告缺少详情")
                except RuntimeError as error:
                    if source_state is not None:
                        record_failure(
                            source_state, notice_id, listing, error, now
                        )
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
                patch = {
                    "url": target_url,
                    "_is_change": True,
                    "change_published_at": _datetime_text(
                        listing.get("releaseTime") or detail.get("releaseTime"),
                        False,
                    ),
                    "project_code": project_code,
                    "source_notice_id": notice_id,
                    "budget": _budget_text(
                        detail.get("reckonPrice"), detail.get("extMap")
                    ),
                    "project_content": clean_text(
                        detail.get("biddingScope")
                        or detail.get("projectOverview")
                    ),
                    "buyer": clean_text(detail.get("tendererName")),
                    "agency": clean_text(
                        detail.get("tenderAgencyName")
                        or detail.get("handleUnitName")
                    ),
                    "bid_deadline": _datetime_text(
                        detail.get("bidEndTime")
                        or detail.get("tenderDocSubmitEndTime"),
                        True,
                    ),
                    "registration_period": (
                        f"{registration_start}至{registration_end}"
                        if registration_start and registration_end
                        else ""
                    ),
                }
                results[f"change:{notice_id}"] = patch
                if source_state is not None:
                    source_state.setdefault("detail_fingerprints", {})[
                        notice_id
                    ] = detail_fingerprint(detail)
                    record_processed(
                        source_state,
                        notice_id,
                        status="change_applied",
                        release_at=release_at,
                        project_code=project_code,
                        url=target_url,
                    )
                continue

            url = _detail_url(source, listing)
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
            query = urlencode({"id": notice_id, "noticeType": 1})
            try:
                detail_payload = _request_json(
                    f"{_source_api(source, 'getByTradeId')}?{query}"
                )
            except RuntimeError as error:
                if source_state is not None:
                    record_failure(
                        source_state, notice_id, listing, error, now
                    )
                continue
            detail = detail_payload.get("data", {}).get("biddingNotice") or {}
            if not detail:
                error = RuntimeError("黔云招采公告缺少详情")
                if source_state is not None:
                    record_failure(
                        source_state, notice_id, listing, error, now
                    )
                continue
            title = clean_text(
                listing.get("businessName") or detail.get("businessName")
            )
            qualification = _qualification_text(detail)
            matches = qualification_matches(title, qualification, config)
            if not matches:
                if source_state is not None:
                    source_state.setdefault("detail_fingerprints", {})[
                        notice_id
                    ] = detail_fingerprint(detail)
                    record_processed(
                        source_state,
                        notice_id,
                        status="not_matched",
                        release_at=release_at,
                        project_code=project_code,
                        url=url,
                    )
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
                    "project_code": project_code,
                    "source_notice_id": notice_id,
                }
            )
            item["source_name"] = source["name"]
            results[url] = item
            if source_state is not None:
                source_state.setdefault("detail_fingerprints", {})[
                    notice_id
                ] = detail_fingerprint(detail)
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
