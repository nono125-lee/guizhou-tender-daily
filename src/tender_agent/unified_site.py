from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .priority_watch import build_watchlist_matches, load_watchlist


ROOT = Path(__file__).resolve().parents[2]
TIMEZONE = ZoneInfo("Asia/Shanghai")
SITE_ROOT = ROOT / "site"
UNIFIED_SITE = SITE_ROOT / "opportunities"
UNIFIED_ASSETS = (
    ROOT
    / "skills"
    / "guizhou-construction-opportunity-intelligence"
    / "assets"
    / "site"
)
CONSTRUCTION_DATA = SITE_ROOT / "construction" / "data" / "latest.json"
INDUSTRY_DATA = SITE_ROOT / "data" / "latest.json"
PLAN_SITE = SITE_ROOT / "tender-plan"
PLAN_DATA = PLAN_SITE / "data" / "latest.json"
PLAN_SCRIPT = (
    ROOT / "skills" / "tender-plan-intelligence" / "scripts" / "collect_plan.py"
)
PLAN_STATE = ROOT / ".runtime" / "tender-plan"
PRIORITY_PROJECTS = ROOT / "config" / "priority_projects.json"


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {"items": [], "warnings": [f"缺少数据文件：{path}"]}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "items": [],
            "warnings": [f"数据文件读取异常 {path.name}：{type(error).__name__}"],
        }
    return value if isinstance(value, dict) else {"items": [], "warnings": []}


def run_command(command: list[str], label: str) -> dict:
    started = datetime.now(TIMEZONE)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    completed = datetime.now(TIMEZONE)
    if process.stdout:
        print(process.stdout.rstrip())
    if process.stderr:
        print(process.stderr.rstrip(), file=sys.stderr)
    return {
        "label": label,
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 2),
    }


def collect_construction() -> dict:
    return run_command(
        [sys.executable, "-m", "tender_agent.construction_site"],
        "施工标讯粗筛",
    )


def collect_industries() -> dict:
    return run_command(
        [sys.executable, "-m", "tender_agent.site", "update"],
        "图文广告与园林绿化",
    )


def collect_plans() -> dict:
    return run_command(
        [
            sys.executable,
            str(PLAN_SCRIPT),
            "--site-dir",
            str(PLAN_SITE),
            "--state-dir",
            str(PLAN_STATE),
            "--construction-data",
            str(CONSTRUCTION_DATA),
        ],
        "招标计划与重点资金关联",
    )


def run_tests() -> dict:
    construction = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        "施工标讯测试",
    )
    plans = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "skills/tender-plan-intelligence/tests",
            "-q",
        ],
        "招标计划测试",
    )
    unified = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests_unified",
            "-q",
        ],
        "统一工作台测试",
    )
    return {
        "ok": construction["ok"] and plans["ok"] and unified["ok"],
        "suites": [construction, plans, unified],
    }


def copy_assets() -> None:
    for relative in ("index.html", "assets/style.css", "assets/app.js"):
        source = UNIFIED_ASSETS / relative
        target = UNIFIED_SITE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def dataset_summary(payload: dict, url: str) -> dict:
    return {
        "url": url,
        "updated_at": payload.get("updated_at"),
        "coverage": payload.get("coverage"),
        "stats": payload.get("stats", {}),
        "warning_count": len(payload.get("warnings", [])),
        "warnings": payload.get("warnings", [])[:20],
    }


def build_unified_site(run_status: dict | None = None) -> dict:
    industries = read_json(INDUSTRY_DATA)
    construction = read_json(CONSTRUCTION_DATA)
    plans = read_json(PLAN_DATA)
    watchlist = load_watchlist(PRIORITY_PROJECTS)
    watched_matches = build_watchlist_matches(
        watchlist,
        plans.get("items", []),
        [industries, construction],
    )
    matches = list(watched_matches)
    identities = {
        (
            item.get("notice", {}).get("url"),
            item.get("plan_project_key"),
        )
        for item in matches
    }
    for item in plans.get("priority_notices", []):
        identity = (
            item.get("notice", {}).get("url"),
            item.get("plan_project_key"),
        )
        if identity not in identities:
            matches.append(item)
            identities.add(identity)
    construction_items = construction.get("items", [])
    construction_by_url = {
        item.get("url"): item for item in construction_items if item.get("url")
    }
    construction_by_notice_id = {
        str(item.get("source_notice_id")): item
        for item in construction_items
        if item.get("source_notice_id")
    }
    for match in matches:
        notice = dict(match.get("notice") or {})
        authoritative = construction_by_url.get(notice.get("url"))
        if authoritative is None and notice.get("source_notice_id"):
            authoritative = construction_by_notice_id.get(
                str(notice.get("source_notice_id"))
            )
        if authoritative:
            for field in ("registration_period", "qualification_requirement"):
                if not notice.get(field) and authoritative.get(field):
                    notice[field] = authoritative[field]
            match["notice"] = notice
    matches.sort(
        key=lambda item: str(item.get("notice", {}).get("published_at") or ""),
        reverse=True,
    )
    now = datetime.now(TIMEZONE).isoformat()
    status = run_status or {
        "started_at": now,
        "completed_at": now,
        "collection": {},
        "tests": {"ok": None, "suites": []},
    }
    status["completed_at"] = now
    status["datasets"] = {
        "industries": dataset_summary(industries, "../data/latest.json"),
        "construction": dataset_summary(
            construction, "../construction/data/latest.json"
        ),
        "tender_plans": dataset_summary(plans, "../tender-plan/data/latest.json"),
    }
    status["summary"] = {
        "graphic_items": sum(
            "graphic-advertising" in item.get("industry_categories", [])
            for item in industries.get("items", [])
        ),
        "landscaping_items": sum(
            "landscaping" in item.get("industry_categories", [])
            for item in industries.get("items", [])
        ),
        "construction_items": len(construction.get("items", [])),
        "plan_notices": len(plans.get("items", [])),
        "ultra_long_projects": plans.get("stats", {}).get(
            "ultra_long_projects", 0
        ),
        "priority_notices": len(matches),
        "priority_projects": len(
            {item.get("plan_project_key") for item in matches if item.get("plan_project_key")}
        ),
        "watched_projects": len(watchlist.get("projects", [])),
        "watched_notices": len(watched_matches),
    }
    matches_payload = {
        "schema_version": 1,
        "updated_at": plans.get("updated_at"),
        "available_sources": sorted(
            {
                str(item.get("source_name")).strip()
                for item in construction_items
                if str(item.get("source_name") or "").strip()
            }
        ),
        "items": matches,
        "stats": {
            "total": len(matches),
            "projects": status["summary"]["priority_projects"],
        },
    }
    manifest = {
        "schema_version": 1,
        "updated_at": now,
        "datasets": {
            "industries": "../data/latest.json",
            "construction": "../construction/data/latest.json",
            "tender_plans": "../tender-plan/data/latest.json",
            "matches": "./data/matches.json",
            "status": "./data/run-status.json",
        },
        "summary": status["summary"],
    }
    copy_assets()
    atomic_write_json(UNIFIED_SITE / "data" / "matches.json", matches_payload)
    atomic_write_json(UNIFIED_SITE / "data" / "run-status.json", status)
    atomic_write_json(UNIFIED_SITE / "data" / "manifest.json", manifest)
    return status


def git_output(arguments: list[str]) -> str:
    process = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, capture_output=True
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "git 命令失败")
    return process.stdout.rstrip()


def publish_gh_pages(split_sha: str) -> str:
    try:
        git_output(["push", "origin", f"{split_sha}:gh-pages", "--force"])
        return "pushed"
    except RuntimeError:
        git_output(["fetch", "origin", "gh-pages"])
        if git_output(["rev-parse", "origin/gh-pages"]) == split_sha:
            return "already_current"
        raise


def publish_site() -> dict:
    status_lines = git_output(["status", "--porcelain"]).splitlines()
    non_site_changes = [
        line for line in status_lines if line and not line[3:].startswith("site/")
    ]
    if non_site_changes:
        raise RuntimeError("存在未提交的非 site 改动，先完成代码提交后再自动发布")
    if not git_output(["status", "--porcelain", "--", "site"]):
        return {"published": False, "reason": "site 无变化"}

    date_text = datetime.now(TIMEZONE).date().isoformat()
    git_output(["add", "site"])
    git_output(["commit", "-m", f"update: 统一施工机会数据 - {date_text}"])
    git_output(["push", "origin", "main"])
    split_sha = git_output(["subtree", "split", "--prefix=site", "main"])
    gh_pages = publish_gh_pages(split_sha)
    return {
        "published": True,
        "commit": git_output(["rev-parse", "HEAD"]),
        "site_commit": split_sha,
        "gh_pages": gh_pages,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run construction screening, tender plans, matching and one-page build."
    )
    parser.add_argument("command", choices=["update", "build"], nargs="?", default="update")
    parser.add_argument("--skip-construction", action="store_true")
    parser.add_argument("--skip-industries", action="store_true")
    parser.add_argument("--skip-plan", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--publish", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    started = datetime.now(TIMEZONE)
    status: dict = {
        "started_at": started.isoformat(),
        "collection": {},
        "tests": {"ok": None, "suites": []},
    }

    if args.command == "update":
        if not args.skip_industries:
            status["collection"]["industries"] = collect_industries()
        if not args.skip_construction:
            status["collection"]["construction"] = collect_construction()
        if not args.skip_plan:
            status["collection"]["tender_plans"] = collect_plans()
        if not args.skip_tests:
            status["tests"] = run_tests()

    status["publish"] = {"requested": args.publish}
    build_unified_site(status)
    failed_collections = [
        result
        for result in status["collection"].values()
        if result and not result.get("ok")
    ]
    if failed_collections or status["tests"].get("ok") is False:
        print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if args.publish:
        publish_result = publish_site()
        print(json.dumps({"publish": publish_result}, ensure_ascii=False))
    print(json.dumps(status.get("summary", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
