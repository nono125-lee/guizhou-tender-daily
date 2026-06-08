from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .normalize import clean_text
from .xlsx_reader import find_sheet, read_xlsx


@dataclass(frozen=True)
class SourceAccount:
    source_no: str
    source_name: str
    url: str
    company: str
    login_identity: str
    username: str
    password: str
    notes: str


@dataclass(frozen=True)
class HistoricalTender:
    collected_at: str
    title: str
    url: str
    budget: str
    summary: str
    location: str
    registration_fee: str
    registration_deadline: str
    buyer: str
    contact: str
    phone: str
    agency: str
    bid_deadline: str
    submission_channel: str
    submission_method: str
    submission_place: str


def load_keywords(path: str | Path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    normalized = text.replace("\n", "、").replace(",", "、").replace("，", "、")
    return [item.strip() for item in normalized.split("、") if item.strip()]


def _excel_date_text(value: object | None) -> str:
    if isinstance(value, (int, float)) and 30000 <= value <= 80000:
        converted = datetime(1899, 12, 30) + timedelta(days=float(value))
        if converted.time() == datetime.min.time():
            return converted.strftime("%Y-%m-%d")
        return converted.strftime("%Y-%m-%d %H:%M")
    return clean_text(value)


def load_source_accounts(path: str | Path) -> list[SourceAccount]:
    sheet = find_sheet(read_xlsx(path), "平台账号")
    accounts: list[SourceAccount] = []
    current_no = current_name = current_url = ""
    for row in sheet.rows[1:]:
        padded = list(row) + [None] * (9 - len(row))
        if clean_text(padded[0]):
            current_no = clean_text(padded[0])
        if clean_text(padded[1]):
            current_name = clean_text(padded[1])
        if clean_text(padded[2]):
            current_url = clean_text(padded[2])
        if not any(clean_text(value) for value in padded[:9]):
            continue
        accounts.append(
            SourceAccount(
                source_no=current_no,
                source_name=current_name,
                url=current_url,
                company=clean_text(padded[3]),
                login_identity=clean_text(padded[4]),
                username=clean_text(padded[5]),
                password=clean_text(padded[6]),
                notes=" | ".join(
                    value
                    for value in [clean_text(padded[7]), clean_text(padded[8])]
                    if value
                ),
            )
        )
    return accounts


def _find_header_index(rows: list[list[object | None]]) -> int:
    for index, row in enumerate(rows):
        values = {clean_text(value) for value in row}
        if "项目名称" in values and "公告网址" in values:
            return index
    raise ValueError("Cannot find tender header row")


def load_historical_tenders(path: str | Path) -> list[HistoricalTender]:
    sheet = find_sheet(read_xlsx(path), "标讯信息表")
    header_index = _find_header_index(sheet.rows)
    tenders: list[HistoricalTender] = []
    for row in sheet.rows[header_index + 1 :]:
        padded = list(row) + [None] * (17 - len(row))
        if not clean_text(padded[2]):
            continue
        tenders.append(
            HistoricalTender(
                collected_at=_excel_date_text(padded[1]),
                title=clean_text(padded[2]),
                url=clean_text(padded[3]),
                budget=clean_text(padded[4]),
                summary=clean_text(padded[5]),
                location=clean_text(padded[6]),
                registration_fee=clean_text(padded[7]),
                registration_deadline=_excel_date_text(padded[8]),
                buyer=clean_text(padded[9]),
                contact=clean_text(padded[10]),
                phone=clean_text(padded[11]),
                agency=clean_text(padded[12]),
                bid_deadline=_excel_date_text(padded[13]),
                submission_channel=clean_text(padded[14]),
                submission_method=clean_text(padded[15]),
                submission_place=clean_text(padded[16]),
            )
        )
    return tenders
