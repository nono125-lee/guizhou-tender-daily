#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_LOCAL_CONSTRUCTION_DATA = Path(
    "/Users/nonolee/Documents/标讯/site/construction/data/latest.json"
)
DEFAULT_REMOTE_CONSTRUCTION_DATA = (
    "https://nono125-lee.github.io/guizhou-tender-daily/"
    "construction/data/latest.json"
)
ULTRA_LONG_RE = re.compile(r"超长期(?:特别)?国债|特别国债")
PUNCTUATION_RE = re.compile(r"[\s\-—_·,，。:：;；()（）\[\]【】“”\"'、/\\]+")
TEXT_PUNCTUATION_RE = re.compile(r"[^\u4e00-\u9fff0-9a-z]+")
LOCATION_TOKEN_RE = re.compile(
    r"^([\u4e00-\u9fff]{2,12}?(?:自治县|新区|开发区|特区|县|市|区|州))"
)
DOCUMENT_REF_RE = re.compile(
    r"[\u4e00-\u9fffa-zA-Z]{1,24}[〔\[【（(]\d{4}[〕\]】）)][\u4e00-\u9fffA-Za-z0-9-]{1,20}号"
)
DOCUMENT_LEADING_RE = re.compile(
    r"^(?:(?:本)?项目)?(?:已经|已由|经|根据|依据|取得|由)+"
)
PACKAGE_SUFFIX_RE = re.compile(
    r"(?:第?[一二三四五六七八九十\d]+(?:标段|包|品目)|[一二三四五六七八九十\d]+标段).*$"
)
NOTICE_SUFFIXES = (
    "项目招标计划",
    "招标计划",
    "公开招标公告",
    "竞争性磋商公告",
    "竞争性谈判公告",
    "询比采购公告",
    "询价采购公告",
    "采购公告",
    "施工招标公告",
    "招标公告",
    "磋商公告",
    "谈判公告",
    "询价公告",
    "公告",
)
COMPANY_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "股份公司",
    "集团公司",
    "公司",
)


def normalize_project_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = PACKAGE_SUFFIX_RE.sub("", text)
    text = PUNCTUATION_RE.sub("", text)
    changed = True
    while changed:
        changed = False
        for suffix in NOTICE_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
    return text


def normalize_buyer(value: object) -> str:
    text = normalize_project_name(value)
    for suffix in COMPANY_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return TEXT_PUNCTUATION_RE.sub("", text)


def leading_location_token(value: object) -> str:
    match = LOCATION_TOKEN_RE.search(normalize_text(value))
    return match.group(1) if match else ""


def text_similarity(left: object, right: object) -> float:
    left_text = normalize_text(left)
    right_text = normalize_text(right)
    if len(left_text) < 20 or len(right_text) < 20:
        return 0.0
    left_pairs = {left_text[index : index + 2] for index in range(len(left_text) - 1)}
    right_pairs = {right_text[index : index + 2] for index in range(len(right_text) - 1)}
    if not left_pairs or not right_pairs:
        return 0.0
    dice = 2 * len(left_pairs & right_pairs) / (len(left_pairs) + len(right_pairs))
    sequence = SequenceMatcher(None, left_text, right_text).ratio()
    return max(dice, sequence)


def document_references(value: object) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return {
        normalize_text(DOCUMENT_LEADING_RE.sub("", match))
        for match in DOCUMENT_REF_RE.findall(text)
    }


def notice_match_text(notice: dict) -> str:
    values = [
        notice.get(field)
        for field in (
            "title",
            "project_name",
            "project_code",
            "fixed_asset_code",
            "investment_project_code",
            "approval",
            "project_content",
            "qualification_requirement",
        )
    ]
    values.extend(notice.get("approval_refs") or [])
    return " ".join(str(value or "") for value in values)


def is_ultra_long_plan(item: dict) -> bool:
    return "超长期" in item.get("fund_source_tags", []) or bool(
        ULTRA_LONG_RE.search(str(item.get("fund_source") or ""))
    )


def date_part(value: object) -> str:
    match = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", str(value or ""))
    if not match:
        return ""
    try:
        return date.fromisoformat(match.group(0)).isoformat()
    except ValueError:
        return ""


def same_buyer(plan: dict, notice: dict) -> bool:
    plan_buyer = normalize_buyer(plan.get("buyer"))
    notice_buyer = normalize_buyer(notice.get("buyer"))
    if not plan_buyer or not notice_buyer or notice_buyer == "公告未载明":
        return False
    return (
        plan_buyer == notice_buyer
        or plan_buyer in notice_buyer
        or notice_buyer in plan_buyer
    )


def notice_is_after_plan(plan: dict, notice: dict) -> bool:
    plan_date = date_part(plan.get("published_at"))
    notice_date = date_part(notice.get("published_at"))
    return not plan_date or not notice_date or notice_date >= plan_date


def match_plan_notice(plan: dict, notice: dict) -> dict | None:
    if not notice_is_after_plan(plan, notice):
        return None

    plan_name = normalize_project_name(plan.get("project_name") or plan.get("title"))
    notice_name = normalize_project_name(notice.get("project_name") or notice.get("title"))
    if not plan_name or not notice_name:
        return None

    fixed_asset_code = normalize_text(plan.get("fixed_asset_code"))
    notice_text = notice_match_text(notice)
    normalized_notice_text = normalize_text(notice_text)
    buyer_matches = same_buyer(plan, notice)
    name_ratio = SequenceMatcher(None, plan_name, notice_name).ratio()
    shorter = min(len(plan_name), len(notice_name))
    length_ratio = shorter / max(len(plan_name), len(notice_name))
    contained = shorter >= 8 and (plan_name in notice_name or notice_name in plan_name)
    plan_location = leading_location_token(plan_name)
    notice_location = leading_location_token(notice_name)
    location_conflict = bool(
        plan_location and notice_location and plan_location != notice_location
    )
    content_ratio = text_similarity(
        plan.get("project_content"), notice.get("project_content")
    )
    plan_approval_refs = document_references(plan.get("approval"))
    notice_approval_refs = document_references(notice_text)
    shared_approval_refs = sorted(plan_approval_refs & notice_approval_refs)
    plan_approval = normalize_text(plan.get("approval"))
    notice_approval = normalize_text(notice.get("approval"))
    approval_text_match = bool(
        len(plan_approval) >= 8
        and notice_approval
        and (plan_approval in notice_approval or notice_approval in plan_approval)
    )

    criteria: list[tuple[str, float, str]] = []
    if fixed_asset_code and fixed_asset_code in normalized_notice_text:
        criteria.append(
            (
                "fixed_asset_code",
                1.0,
                f"投资项目代码一致：{plan.get('fixed_asset_code')}",
            )
        )
    if shared_approval_refs:
        criteria.append(
            (
                "approval",
                0.99,
                f"批复文件编号一致：{'、'.join(shared_approval_refs)}",
            )
        )
    elif approval_text_match:
        criteria.append(("approval", 0.97, "批复文件名称或文号一致"))
    if plan_name == notice_name:
        criteria.append(("project_name", 0.98, "标准化项目名称完全一致（100%）"))
    elif not location_conflict and contained and length_ratio >= 0.55:
        criteria.append(
            (
                "project_name",
                round(0.82 + 0.12 * length_ratio, 3),
                f"项目名称为包含关系，长度重合度 {length_ratio:.1%}",
            )
        )
    elif not location_conflict and name_ratio >= 0.78:
        criteria.append(
            (
                "project_name",
                round(name_ratio, 3),
                f"项目名称相似度 {name_ratio:.1%}",
            )
        )
    if buyer_matches:
        criteria.append(
            (
                "buyer",
                0.72,
                f"招标人/采购人名称一致：{notice.get('buyer')}",
            )
        )
    if content_ratio >= 0.42:
        criteria.append(
            (
                "project_content",
                round(0.7 + 0.25 * content_ratio, 3),
                f"项目建设内容相似度 {content_ratio:.1%}",
            )
        )
    if not criteria:
        return None

    methods = [criterion[0] for criterion in criteria]
    confidence = min(1.0, max(criterion[1] for criterion in criteria) + 0.03 * (len(criteria) - 1))
    strong_methods = {"fixed_asset_code", "approval"}
    high_confidence = bool(strong_methods & set(methods)) or "project_name" in methods and (
        plan_name == notice_name or len(criteria) >= 2
    )
    review_required = not high_confidence
    review_note = (
        "存在强标识或多项证据，可优先核对原公告。"
        if not review_required
        else "当前为单项相似候选，需人工核对是否为同一项目。"
    )
    similarities = {
        "project_name": round(name_ratio, 3),
        "project_content": round(content_ratio, 3),
        "buyer_equal": buyer_matches,
        "fixed_asset_code_equal": "fixed_asset_code" in methods,
        "approval_equal": "approval" in methods,
        "location_conflict": location_conflict,
    }
    evidence = [criterion[2] for criterion in criteria]
    if location_conflict:
        evidence.append(
            f"项目名称地域存在差异：{plan_location} / {notice_location}，名称相似项未计入"
        )
    return {
        "method": "+".join(methods),
        "methods": methods,
        "confidence": round(confidence, 3),
        "match_level": "high" if not review_required else "candidate",
        "review_required": review_required,
        "review_note": review_note,
        "evidence": evidence,
        "similarities": similarities,
    }


def project_group_key(item: dict) -> str:
    return normalize_project_name(item.get("project_name") or item.get("title")) or (
        f"notice:{item.get('source_notice_id') or item.get('url') or ''}"
    )


def latest_ultra_long_plans(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(project_group_key(item), []).append(item)

    latest: list[dict] = []
    for versions in groups.values():
        versions.sort(
            key=lambda item: (
                str(item.get("published_at") or ""),
                str(item.get("source_notice_id") or ""),
            ),
            reverse=True,
        )
        if not is_ultra_long_plan(versions[0]):
            continue
        selected = dict(versions[0])
        selected["plan_version_count"] = len(versions)
        latest.append(selected)
    return latest


def public_notice_fields(notice: dict) -> dict:
    fields = (
        "published_at",
        "title",
        "project_name",
        "url",
        "budget",
        "project_content",
        "fixed_asset_code",
        "investment_project_code",
        "approval",
        "approval_refs",
        "buyer",
        "agency",
        "bid_deadline",
        "source_name",
        "project_code",
        "source_notice_id",
        "matched_keywords",
        "location",
        "is_new",
    )
    return {field: notice.get(field) for field in fields}


def public_plan_fields(plan: dict) -> dict:
    fields = (
        "published_at",
        "title",
        "project_name",
        "url",
        "buyer",
        "budget",
        "fund_source",
        "fund_source_tags",
        "fixed_asset_code",
        "approval",
        "project_content",
        "project_location",
        "source_notice_id",
        "plan_version_count",
    )
    return {field: plan.get(field) for field in fields}


def build_priority_notices(plan_items: list[dict], notice_items: list[dict]) -> list[dict]:
    plans = latest_ultra_long_plans(plan_items)
    matches: list[dict] = []

    for notice in notice_items:
        candidates: list[tuple[float, dict, dict]] = []
        for plan in plans:
            match = match_plan_notice(plan, notice)
            if not match:
                continue
            confidence = float(match["confidence"])
            candidates.append((confidence, plan, match))
        if not candidates:
            continue

        candidates.sort(
            key=lambda candidate: (
                candidate[0],
                str(candidate[1].get("published_at") or ""),
            ),
            reverse=True,
        )
        best_confidence = candidates[0][0]
        selected = [
            candidate
            for candidate in candidates
            if candidate[0] >= best_confidence - 0.03
        ]
        _, plan, match = selected[0]
        candidate_plans = [
            {
                "plan_project_key": project_group_key(candidate_plan),
                "plan": public_plan_fields(candidate_plan),
                "match": candidate_match,
            }
            for _, candidate_plan, candidate_match in selected
        ]
        if len(candidate_plans) > 1:
            match = dict(match)
            match["review_required"] = True
            match["match_level"] = "candidate"
            match["review_note"] = (
                f"该施工公告对应 {len(candidate_plans)} 个相近的超长期计划候选，需人工确认。"
            )
        matches.append(
            {
                "plan_project_key": project_group_key(plan),
                "plan": public_plan_fields(plan),
                "candidate_plans": candidate_plans,
                "notice": public_notice_fields(notice),
                "match": match,
            }
        )

    matches.sort(
        key=lambda item: (
            str(item["notice"].get("published_at") or ""),
            str(item["notice"].get("source_notice_id") or ""),
        ),
        reverse=True,
    )
    return matches


def merge_priority_notices(
    plan_payload: dict,
    construction_payload: dict,
    construction_source: str,
) -> dict:
    matches = build_priority_notices(
        plan_payload.get("items", []), construction_payload.get("items", [])
    )
    ultra_long_total = len(latest_ultra_long_plans(plan_payload.get("items", [])))
    plan_payload["schema_version"] = max(int(plan_payload.get("schema_version") or 1), 3)
    public_construction_source = (
        construction_source
        if construction_source.startswith(("http://", "https://"))
        else "site/construction/data/latest.json"
    )
    plan_payload["construction_feed"] = {
        "source": public_construction_source,
        "updated_at": construction_payload.get("updated_at"),
        "coverage": construction_payload.get("coverage"),
        "warnings": construction_payload.get("warnings", [])[:20],
        "stats": construction_payload.get("stats", {}),
    }
    plan_payload["priority_notices"] = matches
    stats = plan_payload.setdefault("stats", {})
    stats["ultra_long_projects"] = ultra_long_total
    stats["priority_notices"] = len(matches)
    stats["priority_projects"] = len(
        {
            candidate["plan_project_key"]
            for item in matches
            for candidate in item.get("candidate_plans", [])
        }
    )
    stats["priority_new_today"] = sum(
        1 for item in matches if item["notice"].get("is_new")
    )
    return plan_payload


def resolve_construction_source(value: str) -> str:
    if value != "auto":
        return value
    if DEFAULT_LOCAL_CONSTRUCTION_DATA.exists():
        return str(DEFAULT_LOCAL_CONSTRUCTION_DATA)
    return DEFAULT_REMOTE_CONSTRUCTION_DATA


def load_json_source(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        request = Request(
            source,
            headers={"User-Agent": "Mozilla/5.0 TenderPlanPriority/1.0"},
        )
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match construction notices to ultra-long bond tender plans."
    )
    parser.add_argument("--plan-data", type=Path, required=True)
    parser.add_argument("--construction-data", default="auto")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = resolve_construction_source(args.construction_data)
    plan_payload = load_json_source(str(args.plan_data))
    construction_payload = load_json_source(source)
    merge_priority_notices(plan_payload, construction_payload, source)
    output = args.output or args.plan_data
    write_json(output, plan_payload)
    print(
        json.dumps(
            {
                "ultra_long_projects": plan_payload["stats"]["ultra_long_projects"],
                "priority_projects": plan_payload["stats"]["priority_projects"],
                "priority_notices": plan_payload["stats"]["priority_notices"],
                "construction_source": source,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
