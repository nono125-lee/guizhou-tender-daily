from __future__ import annotations

import json
from pathlib import Path

from .importers import load_historical_tenders, load_keywords, load_source_accounts
from .normalize import classify_region, matched_keywords
from .repository import Repository


def bootstrap(
    source_workbook: str | Path,
    keyword_file: str | Path,
    tender_workbook: str | Path,
    database: str | Path,
    region_config: str | Path,
) -> dict[str, int]:
    regions = json.loads(Path(region_config).read_text(encoding="utf-8"))
    keywords = load_keywords(keyword_file)
    accounts = load_source_accounts(source_workbook)
    tenders = load_historical_tenders(tender_workbook)
    repository = Repository(database)
    try:
        source_inserted = repository.import_sources(accounts)
        matched_count = 0
        excluded_count = 0
        for tender in tenders:
            searchable = " ".join([tender.title, tender.summary])
            matched = matched_keywords(searchable, keywords)
            region_status = classify_region(
                " ".join([tender.location, tender.title, tender.summary]),
                regions["include"],
                regions["exclude"],
            )
            if matched:
                matched_count += 1
            if region_status == "excluded":
                excluded_count += 1
            repository.upsert_tender(tender, matched, region_status)
        return {
            "source_rows_read": len(accounts),
            "source_rows_inserted": source_inserted,
            "historical_rows_read": len(tenders),
            "keyword_count": len(keywords),
            "keyword_matched_rows": matched_count,
            "excluded_region_rows": excluded_count,
            **repository.counts(),
        }
    finally:
        repository.close()

