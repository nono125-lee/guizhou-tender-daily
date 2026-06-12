import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tender_agent import construction_site
from tender_agent.collectors import eqyzc_construction, ggzy_construction
from tender_agent.construction_incremental import (
    collection_window,
    empty_state,
    get_source_state,
    record_failure,
    record_processed,
    should_process,
)
from tender_agent.construction_rules import (
    qualification_matches,
    qualification_section,
    trim_qualification,
)


CONFIG = {
    "qualification_keywords": [
        "建筑工程施工总承包",
        "市政公用工程施工总承包",
        "施工劳务",
    ],
    "title_exclude_keywords": ["监理", "审计", "招标代理"],
}


class ConstructionRulesTests(unittest.TestCase):
    def test_incremental_window_uses_six_hour_overlap(self):
        now = datetime(2026, 6, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        source_state = {
            "last_success_at": "2026-06-12T07:00:00+08:00",
            "last_weekly_backfill_at": "2026-06-10T08:00:00+08:00",
            "last_monthly_backfill_at": "2026-06-01T08:00:00+08:00",
        }
        start, mode = collection_window(source_state, now)
        self.assertEqual(mode, "incremental")
        self.assertEqual(start.isoformat(), "2026-06-12T01:00:00+08:00")

    def test_processed_ids_skip_details_but_failures_retry(self):
        source_state = get_source_state(empty_state(), "source")
        record_processed(
            source_state,
            "100",
            status="not_matched",
            release_at="2026-06-12T07:00:00+08:00",
        )
        self.assertFalse(should_process(source_state, "100"))
        record_failure(
            source_state,
            "101",
            {"id": "101"},
            RuntimeError("timeout"),
            datetime(2026, 6, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertTrue(should_process(source_state, "101"))

    def test_only_qualification_section_is_extracted(self):
        text = (
            "二、项目概况：建筑工程施工总承包项目。"
            "三、投标人资格要求：具备市政公用工程施工总承包二级资质。"
            "四、招标文件获取：网上下载。"
        )
        qualification = qualification_section(text)
        self.assertIn("市政公用工程施工总承包", qualification)
        self.assertNotIn("项目概况", qualification)
        self.assertNotIn("网上下载", qualification)

    def test_qualification_section_stops_before_contact_section(self):
        text = (
            "二、申请人的资格要求：1.具备建筑工程施工总承包三级资质；"
            "2.项目经理具备注册建造师资格。"
            "七、对本次采购提出询问，请按以下方式联系："
            "联系人：张某，联系电话：123456。"
        )
        qualification = qualification_section(text)
        self.assertIn("建筑工程施工总承包", qualification)
        self.assertNotIn("联系人", qualification)
        self.assertNotIn("123456", qualification)

    def test_trim_existing_qualification_stops_at_file_section(self):
        qualification = trim_qualification(
            "具备建筑工程施工总承包三级资质。"
            "4、招标文件的获取 凡有意参加投标者请下载文件。"
            "5、投标文件的递交 截止时间为2026年7月1日。"
        )
        self.assertEqual(
            qualification,
            "具备建筑工程施工总承包三级资质",
        )

    def test_trim_handles_spaced_and_decimal_file_headings(self):
        self.assertEqual(
            trim_qualification(
                "供应商具备市政公用工程施工总承包二级资质。"
                "1. 6 获取《磋商文件》的时间、方式、金额等。"
            ),
            "供应商具备市政公用工程施工总承包二级资质",
        )
        self.assertEqual(
            trim_qualification(
                "具备建筑工程施工总承包三级资质。"
                "5.采购文件的获 取 供应商现场报名。"
            ),
            "具备建筑工程施工总承包三级资质",
        )

    def test_title_exclusions_override_qualification_match(self):
        matches = qualification_matches(
            "某道路工程施工监理招标公告",
            "具备市政公用工程施工总承包资质",
            CONFIG,
        )
        self.assertEqual(matches, [])

    def test_qualification_keyword_matches(self):
        self.assertEqual(
            qualification_matches(
                "某道路改造施工招标公告",
                "投标人须具备施工劳务资质",
                CONFIG,
            ),
            ["施工劳务"],
        )

    def test_eqyzc_other_requirements_are_not_qualification(self):
        qualification = eqyzc_construction._qualification_text(
            {
                "qualificationRequirement": "",
                "qualificationLevel": "",
                "otherRequirements": "须具备建筑工程施工总承包资质",
            }
        )
        self.assertEqual(qualification, "")

    @patch("tender_agent.collectors.eqyzc_construction._request_json")
    def test_eqyzc_list_paginates_past_first_page(self, request_json):
        request_json.side_effect = [
            {"data": {"list": [{"id": "1"}, {"id": "2"}]}},
            {"data": {"list": [{"id": "3"}]}},
        ]
        source = {
            "url": "https://example.e-qyzc.com/#/home",
            "platform_id": "platform",
        }
        listings = list(
            eqyzc_construction._page_listings(
                source, 1, 2, page_size=2, max_pages=5
            )
        )
        self.assertEqual([item["id"] for item in listings], ["1", "2", "3"])
        self.assertEqual(request_json.call_count, 2)

    @patch("tender_agent.collectors.ggzy_construction._request")
    def test_ggzy_list_paginates_past_first_page(self, request):
        request.side_effect = [
            json.dumps({"list": [{"id": "1"}, {"id": "2"}]}),
            json.dumps({"list": [{"id": "3"}]}),
        ]
        source = {"channel_id": "channel"}
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        listings = list(
            ggzy_construction._page_listings(
                source, now - timedelta(days=7), now, page_size=2, max_pages=5
            )
        )
        self.assertEqual([item["id"] for item in listings], ["1", "2", "3"])
        self.assertEqual(request.call_count, 2)

    def test_update_freezes_feedback_and_records_older_than_seven_days(self):
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        recent = (now.date() - timedelta(days=1)).isoformat()
        old = (now.date() - timedelta(days=8)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            latest = root / "latest.json"
            state = root / "state.json"
            collector_state = root / "collector-state.json"
            sources = root / "sources.json"
            rules = root / "rules.json"
            sources.write_text(
                json.dumps(
                    [
                        {
                            "id": "test-eqyzc",
                            "collector": "eqyzc",
                            "name": "测试来源",
                            "url": "https://example.com",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            previous_items = [
                {
                    "url": "https://example.com/old",
                    "title": "八日前项目",
                    "published_at": old,
                    "budget": "旧预算",
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
                {
                    "url": "https://example.com/confirmed",
                    "title": "已确认项目",
                    "published_at": recent,
                    "budget": "确认时预算",
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
                {
                    "url": "https://example.com/excluded",
                    "title": "已排除项目",
                    "published_at": recent,
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
            ]
            latest.write_text(
                json.dumps({"items": previous_items}), encoding="utf-8"
            )
            rules.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "items": {
                            "https://example.com/confirmed": {
                                "status": "confirmed",
                                "corrections": {},
                                "item_snapshot": previous_items[1],
                            },
                            "https://example.com/excluded": {
                                "status": "excluded",
                                "corrections": {},
                                "item_snapshot": previous_items[2],
                            },
                        },
                        "summary": {
                            "confirmed": 1,
                            "excluded": 1,
                            "corrected": 0,
                            "correction_fields": {},
                            "exclusion_reasons": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            collected = [
                {
                    "url": "https://example.com/old",
                    "title": "八日前项目",
                    "published_at": old,
                    "budget": "不应覆盖",
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
                {
                    "url": "https://example.com/confirmed",
                    "title": "已确认项目",
                    "published_at": recent,
                    "budget": "不应覆盖",
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
                {
                    "url": "https://example.com/current",
                    "title": "近期项目",
                    "published_at": recent,
                    "budget": "新预算",
                    "qualification_requirement": "具备建筑工程施工总承包三级资质",
                    "source_name": "测试来源",
                },
                {
                    "url": "https://example.com/current",
                    "_is_change": True,
                    "change_published_at": recent,
                    "source_notice_id": "change-1",
                    "budget": "",
                    "bid_deadline": "2026-06-20 10:00",
                },
            ]
            with (
                patch.object(construction_site, "LATEST", latest),
                patch.object(construction_site, "STATE", state),
                patch.object(
                    construction_site, "COLLECTOR_STATE", collector_state
                ),
                patch.object(construction_site, "SOURCES", sources),
                patch.object(construction_site, "FEEDBACK_RULES", rules),
                patch.object(construction_site, "collect_eqyzc", return_value=collected),
                patch.object(construction_site, "collect_ztb", return_value=[]),
            ):
                payload = construction_site.update()
            by_url = {item["url"]: item for item in payload["items"]}
            self.assertEqual(by_url["https://example.com/old"]["budget"], "旧预算")
            self.assertEqual(
                by_url["https://example.com/confirmed"]["budget"], "确认时预算"
            )
            self.assertNotIn("https://example.com/excluded", by_url)
            self.assertEqual(
                by_url["https://example.com/current"]["budget"], "新预算"
            )
            self.assertEqual(
                by_url["https://example.com/current"]["bid_deadline"],
                "2026-06-20 10:00",
            )
