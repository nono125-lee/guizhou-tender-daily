from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .digest import build_daily_digest
from .pipeline import bootstrap
from .repository import Repository


ROOT = Path(__file__).resolve().parents[2]


def _database_path() -> Path:
    private_dir = Path(os.getenv("TENDER_PRIVATE_DIR", ROOT / "data/private"))
    return private_dir / "tenders.sqlite3"


def command_bootstrap(args: argparse.Namespace) -> int:
    stats = bootstrap(
        args.sources,
        args.keywords,
        args.history,
        args.database,
        args.regions,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    repository = Repository(args.database)
    try:
        print(json.dumps(repository.counts(), ensure_ascii=False, indent=2))
    finally:
        repository.close()
    return 0


def command_digest(args: argparse.Namespace) -> int:
    repository = Repository(args.database)
    try:
        digest = build_daily_digest(repository, args.date, args.limit)
        print(json.dumps(digest, ensure_ascii=False, indent=2))
    finally:
        repository.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="标讯采集与推送 Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="导入信息源、关键词和历史标讯"
    )
    bootstrap_parser.add_argument("--sources", required=True)
    bootstrap_parser.add_argument("--keywords", required=True)
    bootstrap_parser.add_argument("--history", required=True)
    bootstrap_parser.add_argument(
        "--database", type=Path, default=_database_path()
    )
    bootstrap_parser.add_argument(
        "--regions", type=Path, default=ROOT / "config/regions.json"
    )
    bootstrap_parser.set_defaults(handler=command_bootstrap)

    status_parser = subparsers.add_parser("status", help="查看本地数据状态")
    status_parser.add_argument(
        "--database", type=Path, default=_database_path()
    )
    status_parser.set_defaults(handler=command_status)

    digest_parser = subparsers.add_parser("digest", help="生成指定日期的日报")
    digest_parser.add_argument("--date", help="YYYY-MM-DD；省略时使用最近采集日")
    digest_parser.add_argument("--limit", type=int, default=50)
    digest_parser.add_argument(
        "--database", type=Path, default=_database_path()
    )
    digest_parser.set_defaults(handler=command_digest)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
