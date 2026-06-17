import unittest

from tender_agent.collectors import asgq, plap
from tender_agent.collectors.eqyzc import item_from_detail


CONSTRUCTION_CONFIG = {
    "qualification_keywords": ["建筑工程施工总承包", "施工劳务"],
    "title_exclude_keywords": ["监理", "审计", "招标代理"],
}


class MultiSourceCollectorTests(unittest.TestCase):
    def test_eqyzc_item_uses_source_host_and_name(self):
        item = item_from_detail(
            {
                "id": "1516742508126011392",
                "noticeType": 1,
                "publishStatus": 1,
                "businessName": "宣传物料制作采购公告",
                "releaseTime": 1781665200000,
            },
            {
                "data": {
                    "biddingNotice": {
                        "businessName": "宣传物料制作采购公告",
                        "purchaseProjectName": "宣传物料制作",
                        "biddingScope": "宣传展板、标识标牌制作。",
                        "releaseTime": 1781665200000,
                    }
                }
            },
            ["宣传", "标识"],
            {
                "name": "云农商电子招采平台",
                "url": "https://gzyc.ynhtbank.com/#/home",
            },
        )
        self.assertIsNotNone(item)
        self.assertIn("gzyc.ynhtbank.com", item["url"])
        self.assertEqual(item["source_name"], "云农商电子招采平台")

    def test_asgq_graphic_and_construction_filters_are_separate(self):
        record = {
            "title": "贵州测试项目采购公告",
            "content": (
                "一、项目基本信息 项目名称：贵州测试项目。"
                "采购内容：宣传展板制作。"
                "二、申请人的资格要求：具备建筑工程施工总承包三级资质。"
            ),
            "webdate": "2026-06-17 10:00:00",
            "linkurl": "/jyxx/002002/002002001/20260617/test.html",
            "infoid": "test",
        }
        graphic = asgq.graphic_item(record, ["宣传", "展板"])
        construction = asgq.construction_item(record, CONSTRUCTION_CONFIG)
        self.assertIsNotNone(graphic)
        self.assertIsNotNone(construction)
        self.assertEqual(graphic["project_content"], "宣传展板制作")
        self.assertIn("建筑工程施工总承包", construction["matched_keywords"])

    def test_plap_graphic_and_construction_filters_are_separate(self):
        record = {
            "title": "贵州楼房消防改造项目招标公告",
            "content": (
                "一、询价内容 项目名称：楼房消防改造项目。"
                "采购内容：消防标识标牌制作安装。"
                "二、报价供应商资格条件：具有建筑工程施工总承包资质。"
            ),
            "noticeTime": "2026-06-17 15:48:29",
            "pageurl": "/freecms-glht/site/juncai/ggxx/info/2026/test.html",
            "noticeId": "test",
            "regionName": "贵州省",
        }
        graphic = plap.graphic_item(record, ["标识", "标牌"])
        construction = plap.construction_item(record, CONSTRUCTION_CONFIG)
        self.assertIsNotNone(graphic)
        self.assertIsNotNone(construction)
        self.assertEqual(graphic["source_name"], "军队采购网")
        self.assertIn("建筑工程施工总承包", construction["matched_keywords"])


if __name__ == "__main__":
    unittest.main()
