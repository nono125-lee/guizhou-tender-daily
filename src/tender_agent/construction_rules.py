from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .normalize import clean_text


ROOT = Path(__file__).resolve().parents[2]
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
QUALIFICATION_LABEL_RE = re.compile(
    r"(?:第?[一二三四五六七八九十百]+[章节部分]\s*)?"
    r"(?:[一二三四五六七八九十百]+|\d{1,2})?\s*[、.．)]?\s*"
    r"(?:投标人|供应商|申请人|响应人)?.{0,8}?"
    r"(?:资格要求|资格条件|资质要求|特殊资格要求)\s*[：:]?"
)
QUALIFICATION_END_RE = re.compile(
    r"(?:"
    r"(?:^|[\s。；;])(?:第?[一二三四五六七八九十百]+[章节部分]|"
    r"[一二三四五六七八九十百]+\s*[、.．])\s*"
    r"|"
    r"(?:^|[\s。；;])"
    r"(?:(?:[一二三四五六七八九十百]+|\d{1,2}(?:\s*[.．]\s*\d{1,2})?)"
    r"\s*[、.．)]?\s*)?"
    r"(?:(?:招标|采购|磋商|谈判)?文件(?:的)?获\s*取|"
    r"获取\s*[《“\"]?(?:招标|采购|磋商|谈判)?文件|"
    r"(?:投标|响应)文件(?:的)?(?:递交|提交)|"
    r"(?:递交|提交)(?:投标|响应|响应性)文件|"
    r"(?:投标|响应)文件提交|"
    r"开标(?:时间|地点)?|开启(?:时间|地点)?|"
    r"公告期限|其他补充事宜|发布公告的媒介|"
    r"联系方式|对本次(?:招标|采购)提出询问|"
    r"凡对本次(?:招标|采购)提出询问)"
    r"\s*[：:]?"
    r")"
)
FIXED_ASSET_CODE_RE = re.compile(r"(?<!\d)\d{4}-\d{6}-\d{2}-\d{2}-\d{6}(?!\d)")
APPROVAL_REFERENCE_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z]{1,24}[〔\[【（(]\d{4}[〕\]】）)][\u4e00-\u9fffA-Za-z0-9-]{1,20}号"
)
APPROVAL_LEADING_RE = re.compile(
    r"^(?:(?:本)?项目)?(?:已经|已由|经|根据|依据|取得|由)+"
)


def load_config(path: Path | None = None) -> dict:
    target = path or ROOT / "config/industries/construction.json"
    return json.loads(target.read_text(encoding="utf-8"))


def plain_text(value: str) -> str:
    return SPACE_RE.sub(
        " ",
        html.unescape(TAG_RE.sub(" ", value or "")),
    ).strip()


def qualification_section(text: str) -> str:
    text = plain_text(text)
    candidates = []
    for match in QUALIFICATION_LABEL_RE.finditer(text):
        remainder = text[match.end():match.end() + 6000]
        value = trim_qualification(remainder)
        if len(value) >= 8:
            candidates.append(value)
    return max(candidates, key=len, default="")


def trim_qualification(text: str) -> str:
    text = plain_text(text)
    end = QUALIFICATION_END_RE.search(text)
    return clean_text(text[:end.start()] if end else text)


def project_match_fields(text: str) -> dict:
    """Extract only explicit public identifiers used for cross-notice matching."""
    value = plain_text(text)
    fixed_asset_codes = list(dict.fromkeys(FIXED_ASSET_CODE_RE.findall(value)))
    approval_refs = [
        APPROVAL_LEADING_RE.sub("", reference)
        for reference in APPROVAL_REFERENCE_RE.findall(value)
    ]
    approval_refs = list(dict.fromkeys(reference for reference in approval_refs if reference))
    return {
        "fixed_asset_code": fixed_asset_codes[0] if fixed_asset_codes else "",
        "approval_refs": approval_refs,
    }


def qualification_matches(
    title: str,
    qualification: str,
    config: dict,
) -> list[str]:
    if any(word in clean_text(title) for word in config["title_exclude_keywords"]):
        return []
    text = clean_text(qualification).lower()
    return [
        keyword
        for keyword in config["qualification_keywords"]
        if keyword.lower() in text
    ]
