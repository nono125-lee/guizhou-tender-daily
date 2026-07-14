from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from priority_match import build_priority_notices, match_plan_notice, merge_priority_notices


def plan(**overrides):
    item = {
        "source_notice_id": "plan-1",
        "title": "普安县县城供水管网改造工程项目招标计划",
        "project_name": "普安县县城供水管网改造工程",
        "published_at": "2026-04-25 11:50:26",
        "buyer": "普安县水利投资有限责任公司",
        "fund_source": "超长期特别国债",
        "fund_source_tags": ["超长期"],
        "fixed_asset_code": "2111-522323-04-01-342068",
        "approval": "普发改规划〔2024〕16号",
        "project_content": "改造县城供水管网并建设蓄水池、智慧水务系统及配套设施。",
        "url": "https://example.test/plan-1",
    }
    item.update(overrides)
    return item


def notice(**overrides):
    item = {
        "source_notice_id": "notice-1",
        "title": "普安县县城供水管网改造工程施工招标公告",
        "project_name": "普安县县城供水管网改造工程",
        "published_at": "2026-06-26",
        "buyer": "普安县水利投资有限责任公司",
        "url": "https://example.test/notice-1",
        "matched_keywords": ["市政公用工程施工总承包"],
        "project_content": "改造县城供水管网，建设蓄水池、智慧水务系统和相关配套设施。",
    }
    item.update(overrides)
    return item


class PriorityMatchTests(unittest.TestCase):
    def test_exact_project_name_and_buyer_matches(self):
        result = match_plan_notice(plan(), notice())
        self.assertIsNotNone(result)
        self.assertEqual(result["methods"], ["project_name", "buyer", "project_content"])
        self.assertEqual(result["confidence"], 1.0)
        self.assertFalse(result["review_required"])

    def test_notice_before_plan_is_rejected(self):
        result = match_plan_notice(plan(), notice(published_at="2026-04-01"))
        self.assertIsNone(result)

    def test_contained_name_can_match_without_same_buyer(self):
        variant = notice(
            project_name="普安县县城供水管网改造工程施工一标段",
            title="普安县县城供水管网改造工程施工一标段招标公告",
        )
        self.assertIsNotNone(match_plan_notice(plan(), variant))
        variant["buyer"] = "其他建设单位"
        result = match_plan_notice(plan(), variant)
        self.assertIsNotNone(result)
        self.assertIn("project_name", result["methods"])

    def test_buyer_name_alone_creates_review_candidate(self):
        result = match_plan_notice(
            plan(project_content=""),
            notice(
                project_name="完全不同的施工项目",
                title="完全不同的施工项目公告",
                project_content="",
            ),
        )
        self.assertEqual(result["methods"], ["buyer"])
        self.assertTrue(result["review_required"])
        self.assertIn("单项相似候选", result["review_note"])

    def test_fixed_asset_code_alone_matches(self):
        result = match_plan_notice(
            plan(buyer="甲单位", project_content=""),
            notice(
                project_name="其他项目",
                title="其他项目公告",
                buyer="乙单位",
                project_content="投资项目代码2111-522323-04-01-342068",
            ),
        )
        self.assertEqual(result["methods"], ["fixed_asset_code"])
        self.assertFalse(result["review_required"])

    def test_approval_reference_alone_matches(self):
        result = match_plan_notice(
            plan(buyer="甲单位", project_content=""),
            notice(
                project_name="其他项目",
                title="其他项目公告",
                buyer="乙单位",
                approval="普发改规划〔2024〕16号",
                project_content="",
            ),
        )
        self.assertEqual(result["methods"], ["approval"])
        self.assertFalse(result["review_required"])

    def test_similar_project_content_alone_creates_review_candidate(self):
        result = match_plan_notice(
            plan(buyer="甲单位"),
            notice(project_name="其他项目", title="其他项目公告", buyer="乙单位"),
        )
        self.assertEqual(result["methods"], ["project_content"])
        self.assertTrue(result["review_required"])
        self.assertGreaterEqual(result["similarities"]["project_content"], 0.42)

    def test_similar_names_with_conflicting_counties_do_not_match(self):
        result = match_plan_notice(
            plan(
                project_name="石阡县2026年高标准农田建设项目",
                title="石阡县2026年高标准农田建设项目招标计划",
                buyer="石阡县农业农村局",
                project_content="",
            ),
            notice(
                project_name="湄潭县2026年高标准农田建设项目",
                title="湄潭县2026年高标准农田建设项目招标公告",
                buyer="湄潭县农业农村局",
                project_content="",
            ),
        )
        self.assertIsNone(result)

    def test_unrelated_notice_is_not_matched(self):
        unrelated = notice(
            project_name="铜仁学院附属中学新建教学综合楼建设项目",
            title="铜仁学院附属中学新建教学综合楼建设项目采购公告",
            buyer="铜仁学院附属中学",
            project_content="新建教学楼、实验室和校园道路等教育配套设施。",
        )
        self.assertEqual(build_priority_notices([plan()], [unrelated]), [])

    def test_latest_plan_version_controls_ultra_long_status(self):
        older = plan(published_at="2026-04-25", fund_source_tags=["超长期"])
        newer = plan(
            source_notice_id="plan-2",
            published_at="2026-05-01",
            fund_source="企业自筹",
            fund_source_tags=["企业自筹"],
        )
        self.assertEqual(build_priority_notices([older, newer], [notice()]), [])

    def test_named_fund_sources_are_included_in_priority_matches(self):
        fund_sources = (
            "一般国债资金",
            "水利专项资金",
            "中央预算内投资",
            "省级财政资金",
        )
        for index, fund_source in enumerate(fund_sources, start=1):
            with self.subTest(fund_source=fund_source):
                candidate = plan(
                    source_notice_id=f"plan-{index}",
                    fund_source=fund_source,
                    fund_source_tags=[],
                )
                self.assertEqual(
                    len(build_priority_notices([candidate], [notice()])),
                    1,
                )

    def test_merge_adds_relation_and_stats_without_mutating_plan_items(self):
        original_plan = plan()
        payload = {"schema_version": 1, "items": [dict(original_plan)], "stats": {}}
        merge_priority_notices(
            payload,
            {"items": [notice()], "updated_at": "2026-06-30T06:00:00+08:00"},
            "fixture.json",
        )
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["stats"]["ultra_long_projects"], 1)
        self.assertEqual(payload["stats"]["priority_projects"], 1)
        self.assertEqual(payload["stats"]["priority_notices"], 1)
        self.assertNotIn("priority_notices", payload["items"][0])
        self.assertEqual(payload["priority_notices"][0]["plan"]["project_name"], original_plan["project_name"])

    def test_same_buyer_multiple_plans_are_kept_as_candidates(self):
        first = plan(
            source_notice_id="plan-a",
            project_name="甲项目",
            title="甲项目招标计划",
            project_content="",
        )
        second = plan(
            source_notice_id="plan-b",
            project_name="乙项目",
            title="乙项目招标计划",
            project_content="",
        )
        candidate_notice = notice(
            project_name="丙项目",
            title="丙项目公告",
            project_content="",
        )
        result = build_priority_notices([first, second], [candidate_notice])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["candidate_plans"]), 2)
        self.assertTrue(result[0]["match"]["review_required"])
        self.assertIn("2 个", result[0]["match"]["review_note"])


if __name__ == "__main__":
    unittest.main()
