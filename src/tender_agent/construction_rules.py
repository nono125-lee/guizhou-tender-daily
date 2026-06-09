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
    r"(?:投标人|供应商|申请人|响应人)?.{0,8}?"
    r"(?:资格要求|资质要求|特殊资格要求)\s*[：:]?"
)
QUALIFICATION_END_RE = re.compile(
    r"\s+(?:[四五六七八九十]|\d{1,2})\s*[、.]"
    r"\s*(?:招标|采购|文件|响应|投标|报名|联系方式|发布)"
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
        remainder = text[match.end():match.end() + 3000]
        end = QUALIFICATION_END_RE.search(remainder)
        value = clean_text(remainder[:end.start()] if end else remainder)
        if len(value) >= 8:
            candidates.append(value)
    return max(candidates, key=len, default="")


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
