from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collectors.guizhou_ztb import collect
from .importers import load_keywords
from .public_export import (
    export_public_snapshot,
    load_source_names,
    normalize_public_item,
)
from .repository import Repository


ROOT = Path(__file__).resolve().parents[2]


def seed(args: argparse.Namespace) -> int:
    repository = Repository(args.database)
    try:
        payload = export_public_snapshot(repository, args.output, args.limit)
    finally:
        repository.close()
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


def update(args: argparse.Namespace) -> int:
    payload = collect(
        load_keywords(args.keywords),
        args.state,
        args.output,
        args.max_scan,
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
