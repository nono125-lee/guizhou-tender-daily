from __future__ import annotations

import argparse
from pathlib import Path

from .feedback import ROOT, ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="处理施工标讯人工反馈")
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument(
        "--rules",
        type=Path,
        default=ROOT / "config/construction_feedback_rules.json",
    )
    parser.add_argument(
        "--latest",
        type=Path,
        default=ROOT / "site/construction/data/latest.json",
    )
    parser.add_argument(
        "--public-state",
        type=Path,
        default=ROOT / "site/construction/data/feedback-state.json",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=ROOT / ".construction-feedback-result.md",
    )
    return ingest(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
