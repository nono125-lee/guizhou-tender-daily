from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[，。、“”‘’：；（）()【】\[\]\-_/\\]+")


def clean_text(value: object | None) -> str:
    if value is None:
        return ""
    return SPACE_RE.sub(" ", str(value)).strip()


def canonical_url(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    parts = urlsplit(url)
    removable = {"utm_source", "utm_medium", "utm_campaign", "from", "spm"}
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in removable
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def normalized_title(title: str) -> str:
    return PUNCT_RE.sub("", clean_text(title)).lower()


def tender_fingerprint(
    title: str,
    url: str = "",
    buyer: str = "",
    deadline: str = "",
) -> str:
    canonical = canonical_url(url)
    if canonical:
        payload = f"url:{canonical}"
    else:
        payload = "|".join(
            [
                normalized_title(title),
                clean_text(buyer).lower(),
                clean_text(deadline).lower(),
            ]
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    folded = clean_text(text).lower()
    return [keyword for keyword in keywords if keyword.lower() in folded]


def matched_tender_keywords(
    project_name: str,
    content_fields: list[str],
    keywords: list[str],
) -> list[str]:
    """Match only the project name and explicitly allowed project-content fields."""
    searchable = " ".join(
        [clean_text(project_name)]
        + [clean_text(value) for value in content_fields if clean_text(value)]
    )
    return matched_keywords(searchable, keywords)


def classify_region(text: str, include: list[str], exclude: list[str]) -> str:
    folded = clean_text(text)
    if any(name in folded for name in exclude):
        return "excluded"
    if any(name in folded for name in include):
        return "included"
    return "review"
