import unittest

from tender_agent.site import (
    _apply_keyword_rules,
    _fill_party_placeholders,
    _mark_new_items,
    _remove_excluded_notices,
)


class SiteFilterTests(unittest.TestCase):
    def test_confirmed_false_positive_is_removed(self):
        payload = {
            "items": [
                {
                    "title": (
                        "六盘水师范学院高压配电设备维修更换项目"
                        "（三次）采购公告"
                    )
                },
                {"title": "贵阳市户外广告制作项目采购公告"},
            ]
        }
        _remove_excluded_notices(payload)
        self.assertEqual(
            [item["title"] for item in payload["items"]],
            ["贵阳市户外广告制作项目采购公告"],
        )

    def test_only_project_fields_are_used_for_final_filter(self):
        payload = {
            "items": [
                {
                    "title": "高压配电设备维修项目采购公告",
                    "project_content": "维修高压配电设备",
                    "buyer": "贵州广告文化有限公司",
                    "matched_keywords": ["广告", "文化", "证书"],
                },
                {
                    "title": "校园设施维修项目采购公告",
                    "project_content": "采购范围：制作安装导视标牌",
                    "buyer": "采购人",
                    "matched_keywords": [],
                },
            ]
        }
        _apply_keyword_rules(payload, ["广告", "文化", "导视", "标牌", "证书"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(
            payload["items"][0]["matched_keywords"],
            ["导视", "标牌"],
        )

    def test_only_new_urls_are_marked_new(self):
        previous = {
            "items": [
                {
                    "url": "https://example.com/old",
                    "published_at": "2026-06-09",
                }
            ]
        }
        payload = {
            "updated_at": "2026-06-10T07:00:00+08:00",
            "items": [
                {
                    "url": "https://example.com/old",
                    "published_at": "2026-06-09",
                },
                {
                    "url": "https://example.com/new",
                    "published_at": "2026-06-10",
                },
            ],
        }
        _mark_new_items(payload, previous)
        self.assertFalse(payload["items"][0]["is_new"])
        self.assertTrue(payload["items"][1]["is_new"])
        self.assertEqual(payload["items"][1]["new_on_date"], "2026-06-10")

    def test_missing_parties_receive_visible_placeholders(self):
        payload = {"items": [{"buyer": "", "agency": None}]}
        _fill_party_placeholders(payload)
        self.assertEqual(payload["items"][0]["buyer"], "公告未载明")
        self.assertEqual(payload["items"][0]["agency"], "公告未载明")


if __name__ == "__main__":
    unittest.main()
