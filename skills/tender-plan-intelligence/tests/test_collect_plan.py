from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from collect_plan import (
    RequestPacer,
    TIMEZONE,
    cached_detail,
    collect,
    empty_detail_cache,
    empty_state,
    merge_items,
    main,
    seed_detail_cache,
    select_run,
)


NOW = datetime(2026, 6, 30, 10, 0, tzinfo=TIMEZONE)


def args(**overrides):
    values = {
        "pub_date": "td",
        "keywords": "",
        "all_pages": False,
        "max_pages": None,
        "no_details": False,
        "workers": 4,
        "detail_cache_ttl_days": 30,
        "refresh_details": False,
        "mode": "daily",
        "rebuild": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def raw_listing(notice_id: str, published_at: str = "2026-06-30 09:00:00") -> dict:
    return {
        "Id": notice_id,
        "Title": f"{notice_id}项目招标计划",
        "PubDate": published_at,
        "RegionName": "贵阳市",
        "TenderName": "建设单位",
        "TenderAgencyName": "代理机构",
        "BTypeName": "招标计划",
        "IsTradeCenterPush": False,
    }


class RunSelectionTests(unittest.TestCase):
    def state_at(self, last_success: str, weekly: str, monthly: str) -> dict:
        return {
            **empty_state(),
            "last_success_at": last_success,
            "last_weekly_backfill_at": weekly,
            "last_monthly_backfill_at": monthly,
        }

    def test_bootstrap_and_manual_modes(self):
        self.assertEqual(select_run(empty_state(), None, NOW), ("bootstrap", "l3m"))
        self.assertEqual(select_run(empty_state(), "l10d", NOW), ("manual", "l10d"))

    def test_daily_and_catchup_windows(self):
        recent_backfill = "2026-06-29T08:00:00+08:00"
        same_day = self.state_at(
            "2026-06-30T08:00:00+08:00", recent_backfill, recent_backfill
        )
        yesterday = self.state_at(
            "2026-06-29T08:00:00+08:00", recent_backfill, recent_backfill
        )
        four_days = self.state_at(
            "2026-06-26T08:00:00+08:00", recent_backfill, recent_backfill
        )
        self.assertEqual(select_run(same_day, None, NOW), ("daily", "td"))
        self.assertEqual(select_run(yesterday, None, NOW), ("daily", "l3d"))
        self.assertEqual(select_run(four_days, None, NOW), ("catchup", "l10d"))

    def test_scheduled_backfill_chooses_widest_window(self):
        weekly_due = self.state_at(
            "2026-06-30T08:00:00+08:00",
            "2026-06-20T08:00:00+08:00",
            "2026-06-20T08:00:00+08:00",
        )
        monthly_due = self.state_at(
            "2026-06-30T08:00:00+08:00",
            "2026-06-29T08:00:00+08:00",
            "2026-05-20T08:00:00+08:00",
        )
        self.assertEqual(select_run(weekly_due, None, NOW), ("weekly", "l1m"))
        self.assertEqual(select_run(monthly_due, None, NOW), ("monthly", "l3m"))


class MergeAndCacheTests(unittest.TestCase):
    def test_incremental_merge_preserves_history_and_updates_same_id(self):
        existing = [
            {
                "source_notice_id": "old",
                "published_at": "2026-05-01 08:00:00",
                "fund_source": "财政资金",
            },
            {
                "source_notice_id": "same",
                "published_at": "2026-06-20 08:00:00",
                "fund_source": "企业自筹",
                "title": "旧标题",
            },
        ]
        window = [
            {
                "source_notice_id": "same",
                "published_at": "2026-06-20 08:00:00",
                "title": "新标题",
            },
            {"source_notice_id": "new", "published_at": "2026-06-30 09:00:00"},
        ]
        merged, pruned = merge_items(existing, window, NOW.date().replace(month=3))
        by_id = {item["source_notice_id"]: item for item in merged}
        self.assertEqual(set(by_id), {"old", "same", "new"})
        self.assertEqual(by_id["same"]["title"], "新标题")
        self.assertEqual(by_id["same"]["fund_source"], "企业自筹")
        self.assertEqual(pruned, 0)

    def test_existing_payload_seeds_fresh_cache(self):
        cache = empty_detail_cache()
        payload = {
            "updated_at": NOW.isoformat(),
            "items": [
                {
                    "source_notice_id": "plan-1",
                    "project_name": "项目一",
                    "fund_source": "财政资金",
                    "fund_source_tags": ["财政资金"],
                }
            ],
        }
        self.assertEqual(seed_detail_cache(cache, payload, NOW), 1)
        fields, fresh = cached_detail(cache, "plan-1", NOW, 30)
        self.assertTrue(fresh)
        self.assertEqual(fields["fund_source"], "财政资金")

    @patch("collect_plan.fetch_detail")
    @patch("collect_plan.fetch_page")
    def test_daily_cache_hit_does_not_shrink_existing_dataset(
        self, fetch_page_mock, fetch_detail_mock
    ):
        fetch_page_mock.return_value = {
            "totalPage": 1,
            "totalNum": 1,
            "data": [raw_listing("today")],
        }
        existing = {
            "items": [
                {
                    "source_notice_id": "history",
                    "published_at": "2026-05-01 08:00:00",
                    "fund_source": "财政资金",
                }
            ]
        }
        cache = {
            "schema_version": 1,
            "failures": {},
            "entries": {
                "today": {
                    "cached_at": NOW.isoformat(),
                    "fields": {
                        "project_name": "今日项目",
                        "fund_source": "财政资金",
                        "fund_source_tags": ["财政资金"],
                    },
                }
            },
        }
        payload, complete = collect(
            args(), existing, cache, NOW, RequestPacer(0)
        )
        self.assertTrue(complete)
        self.assertEqual(payload["stats"]["detail_cache_hits"], 1)
        self.assertEqual(payload["stats"]["total"], 2)
        fetch_detail_mock.assert_not_called()

    @patch("collect_plan.fetch_detail")
    @patch("collect_plan.fetch_page")
    def test_expired_cache_is_used_when_refresh_fails(
        self, fetch_page_mock, fetch_detail_mock
    ):
        fetch_page_mock.return_value = {
            "totalPage": 1,
            "totalNum": 1,
            "data": [raw_listing("plan-1")],
        }
        fetch_detail_mock.return_value = ("plan-1", None, "plan-1: TimeoutError")
        cache = {
            "schema_version": 1,
            "failures": {},
            "entries": {
                "plan-1": {
                    "cached_at": "2026-05-01T08:00:00+08:00",
                    "fields": {
                        "project_name": "项目一",
                        "fund_source": "财政资金",
                        "fund_source_tags": ["财政资金"],
                    },
                }
            },
        }
        payload, _ = collect(args(), {"items": []}, cache, NOW, RequestPacer(0))
        self.assertEqual(payload["stats"]["detail_fetch_failed"], 1)
        self.assertEqual(payload["stats"]["stale_cache_used"], 1)
        self.assertEqual(payload["items"][0]["fund_source"], "财政资金")


class MainWorkflowTests(unittest.TestCase):
    @patch("builtins.print")
    @patch("collect_plan.fetch_detail")
    @patch("collect_plan.fetch_page")
    def test_first_run_bootstraps_then_same_day_run_uses_cache(
        self, fetch_page_mock, fetch_detail_mock, _print_mock
    ):
        fetch_page_mock.return_value = {
            "totalPage": 1,
            "totalNum": 1,
            "data": [raw_listing("plan-1")],
        }
        fetch_detail_mock.return_value = (
            "plan-1",
            {
                "project_name": "项目一",
                "fund_source": "财政资金",
                "fund_source_tags": ["财政资金"],
            },
            None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            site_dir = project / "site/tender-plan"
            command = [
                "--site-dir",
                str(site_dir),
                "--no-construction-match",
                "--request-interval",
                "0",
            ]
            self.assertEqual(main(command), 0)
            runtime_dir = project / ".runtime/tender-plan"
            first_payload = json.loads(
                (site_dir / "data/latest.json").read_text(encoding="utf-8")
            )
            state = json.loads(
                (runtime_dir / "run-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(first_payload["stats"]["mode"], "bootstrap")
            self.assertTrue(state["last_success_at"])
            self.assertTrue((runtime_dir / "detail-cache.json").exists())

            self.assertEqual(main(command), 0)
            second_payload = json.loads(
                (site_dir / "data/latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(second_payload["stats"]["mode"], "daily")
            self.assertEqual(second_payload["stats"]["detail_cache_hits"], 1)
            self.assertEqual(second_payload["stats"]["detail_cache_misses"], 0)
            self.assertEqual(fetch_detail_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
