from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors.guizhou_ztb import collect
from .collectors.eqyzc import collect as collect_eqyzc
from .collectors.zunyi_bus import collect as collect_zunyi_bus
from .importers import load_keywords
from .normalize import matched_tender_keywords
from .public_export import (
    export_public_snapshot,
    load_source_names,
    normalize_public_item,
)
from .repository import Repository


ROOT = Path(__file__).resolve().parents[2]


def _excluded_titles() -> set[str]:
    path = ROOT / "config/excluded_notices.json"
    if not path.exists():
        return set()
    return {
        str(title).strip()
        for title in json.loads(path.read_text(encoding="utf-8"))
        if str(title).strip()
    }


def _remove_excluded_notices(payload: dict) -> None:
    excluded = _excluded_titles()
    if not excluded:
        return
    payload["items"] = [
        item
        for item in payload.get("items", [])
        if item.get("title", "").strip() not in excluded
    ]


def _apply_keyword_rules(payload: dict, keywords: list[str]) -> None:
    kept = []
    for item in payload.get("items", []):
        matches = matched_tender_keywords(
            item.get("project_name") or item.get("title", ""),
            [
                item.get("project_content", ""),
                item.get("procurement_content", ""),
                item.get("bidding_scope", ""),
                item.get("project_overview", ""),
            ],
            keywords,
        )
        if not matches:
            continue
        item["matched_keywords"] = matches
        kept.append(item)
    payload["items"] = kept


def _merge_verified_notices(payload: dict) -> None:
    source_names = load_source_names()
    path = ROOT / "config/verified_notices.json"
    verified = json.loads(path.read_text(encoding="utf-8"))
    by_url = {item.get("url", ""): item for item in payload.get("items", [])}
    for raw_item in verified:
        item = normalize_public_item(raw_item, source_names)
        by_url[item["url"]] = {**by_url.get(item["url"], {}), **item}
    payload["items"] = list(by_url.values())


def _refresh_payload(payload: dict) -> None:
    payload["items"].sort(
        key=lambda item: (
            item.get("published_at", ""),
            item.get("url", ""),
        ),
        reverse=True,
    )
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    payload["stats"]["total"] = len(payload["items"])
    payload["stats"]["new_today"] = sum(
        item.get("date_basis") == "official"
        and item.get("published_at", "")[:10] == today
        for item in payload["items"]
    )
    payload["stats"]["sources"] = len(
        {item["source_name"] for item in payload["items"]}
    )


def seed(args: argparse.Namespace) -> int:
    repository = Repository(args.database)
    try:
        payload = export_public_snapshot(repository, args.output, args.limit)
    finally:
        repository.close()
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


def update(args: argparse.Namespace) -> int:
    keywords = load_keywords(args.keywords)
    payload = collect(
        keywords,
        args.state,
        args.output,
        args.max_scan,
    )
    _merge_verified_notices(payload)
    try:
        new_items = collect_eqyzc(
            keywords,
            payload.get("items", []),
        )
        if new_items:
            by_url = {
                item.get("url", ""): item
                for item in payload.get("items", [])
            }
            for item in new_items:
                by_url[item["url"]] = item
            payload["items"] = list(by_url.values())
    except Exception as error:
        payload.setdefault("warnings", []).append(
            f"黔云招采采集异常：{type(error).__name__}"
        )
    try:
        new_items = collect_zunyi_bus(
            keywords,
            payload.get("items", []),
        )
        if new_items:
            payload["items"] = new_items + payload["items"]
    except Exception as error:
        payload.setdefault("warnings", []).append(
            f"遵义公交官网采集异常：{type(error).__name__}"
        )
    _remove_excluded_notices(payload)
    _apply_keyword_rules(payload, keywords)
    _refresh_payload(payload)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


def normalize(args: argparse.Namespace) -> int:
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    source_names = load_source_names(args.source_names)
    payload["items"] = [
        normalize_public_item(item, source_names)
        for item in payload.get("items", [])
        if item.get("url")
    ]
    payload["stats"]["total"] = len(payload["items"])
    payload["stats"]["sources"] = len(
        {item["source_name"] for item in payload["items"]}
    )
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub Pages 标讯日报")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument(
        "--database", type=Path, default=ROOT / "data/private/tenders.sqlite3"
    )
    seed_parser.add_argument(
        "--output", type=Path, default=ROOT / "site/data/latest.json"
    )
    seed_parser.add_argument("--limit", type=int, default=200)
    seed_parser.set_defaults(handler=seed)

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument(
        "--keywords",
        type=Path,
        default=ROOT / "config/industries/graphic-advertising.json",
    )
    update_parser.add_argument(
        "--state", type=Path, default=ROOT / "site/data/state.json"
    )
    update_parser.add_argument(
        "--output", type=Path, default=ROOT / "site/data/latest.json"
    )
    update_parser.add_argument("--max-scan", type=int, default=800)
    update_parser.set_defaults(handler=update)

    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument(
        "--input", type=Path, default=ROOT / "site/data/latest.json"
    )
    normalize_parser.add_argument(
        "--output", type=Path, default=ROOT / "site/data/latest.json"
    )
    normalize_parser.add_argument(
        "--source-names",
        type=Path,
        default=ROOT / "config/source_names.json",
    )
    normalize_parser.set_defaults(handler=normalize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "update" and args.keywords.suffix == ".json":
        config = json.loads(args.keywords.read_text(encoding="utf-8"))
        temp = ROOT / ".keywords.runtime.txt"
        temp.write_text("、".join(config["keywords"]), encoding="utf-8")
        args.keywords = temp
        try:
            return args.handler(args)
        finally:
            temp.unlink(missing_ok=True)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
