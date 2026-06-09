import unittest

from tender_agent.collectors.eqyzc import item_from_detail


class EqyzcCollectorTests(unittest.TestCase):
    def test_bidding_notice_is_normalized(self):
        listing = {
            "id": "1513535302085869569",
            "noticeType": 1,
            "publishStatus": 1,
            "businessName": "图文广告服务询比采购公告",
            "releaseTime": 1780890082000,
        }
        payload = {
            "data": {
                "biddingNotice": {
                    "businessName": "图文广告服务询比采购公告",
                    "releaseTime": 1780890082000,
                    "purchaseProjectName": "图文广告服务",
                    "projectOverview": "图文设计、广告制作、标识标牌安装",
                    "reckonPrice": 30300000,
                    "extMap": {"decimalNum": 2},
                    "address": "毕节市七星关区",
                    "tendererName": "贵州燃气集团毕节市燃气有限责任公司",
                    "tenderAgencyName": "贵州测试招标代理有限公司",
                    "tenderDocGetStartTime": 1780890082000,
                    "tenderDocGetEndTime": 1780990980000,
                    "bidEndTime": 1781250180000,
                }
            }
        }
        item = item_from_detail(
            listing,
            payload,
            ["图文", "广告", "标识", "标牌"],
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["published_at"], "2026-06-07")
        self.assertEqual(item["bid_deadline"], "2026-06-12 00:43")
        self.assertEqual(item["budget"], "30.3万元")
        self.assertEqual(
            item["registration_period"], "2026-06-07至2026-06-09"
        )
        self.assertEqual(
            item["source_name"], "黔云招采电子招标采购交易平台"
        )
        self.assertEqual(item["buyer"], "贵州燃气集团毕节市燃气有限责任公司")
        self.assertEqual(item["agency"], "贵州测试招标代理有限公司")
        self.assertEqual(
            item["project_content"],
            "图文设计、广告制作、标识标牌安装",
        )

    def test_project_name_is_not_used_as_project_content_fallback(self):
        item = item_from_detail(
            {
                "id": "3",
                "noticeType": 1,
                "publishStatus": 1,
                "businessName": "图文广告服务采购公告",
            },
            {
                "data": {
                    "biddingNotice": {
                        "businessName": "图文广告服务采购公告",
                        "purchaseProjectName": "图文广告服务",
                    }
                }
            },
            ["广告"],
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["project_content"], "")

    def test_non_matching_notice_is_ignored(self):
        item = item_from_detail(
            {"id": "1", "noticeType": 1, "publishStatus": 1},
            {
                "data": {
                    "biddingNotice": {
                        "businessName": "服务器采购公告",
                        "purchaseProjectName": "服务器采购",
                    }
                }
            },
            ["广告"],
        )
        self.assertIsNone(item)

    def test_buyer_name_is_not_used_for_keyword_matching(self):
        item = item_from_detail(
            {"id": "2", "noticeType": 1, "publishStatus": 1},
            {
                "data": {
                    "biddingNotice": {
                        "businessName": "设备维修采购公告",
                        "purchaseProjectName": "高压设备维修",
                        "projectOverview": "维修高压配电设备",
                        "tendererName": "贵州广告文化有限公司",
                    }
                }
            },
            ["广告", "文化"],
        )
        self.assertIsNone(item)


if __name__ == "__main__":
    unittest.main()
