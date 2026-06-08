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


if __name__ == "__main__":
    unittest.main()
