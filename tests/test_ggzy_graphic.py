import json
import unittest
from pathlib import Path

from tender_agent.collectors.ggzy_graphic import item_from_listing


ROOT = Path(__file__).resolve().parents[1]


class GgzyGraphicCollectorTests(unittest.TestCase):
    def test_all_three_shared_industry_channels_are_configured(self):
        sources = json.loads(
            (ROOT / "config/graphic_sources.json").read_text(encoding="utf-8")
        )
        ggzy_sources = {
            source["id"]: source
            for source in sources
            if source.get("collector") == "ggzy"
        }
        self.assertEqual(
            ggzy_sources,
            {
                "ggzy-gcjs": {
                    "id": "ggzy-gcjs",
                    "name": "贵州省公共资源交易云-工程建设",
                    "url": "https://ggzy.guizhou.gov.cn/xxfw/gcjs/",
                    "collector": "ggzy",
                    "channel_id": "5904475",
                },
                "ggzy-zfcg": {
                    "id": "ggzy-zfcg",
                    "name": "贵州省公共资源交易云-政府采购",
                    "url": "https://ggzy.guizhou.gov.cn/xxfw/zfcg/",
                    "collector": "ggzy",
                    "channel_id": "5904543",
                },
                "ggzy-qttzjy": {
                    "id": "ggzy-qttzjy",
                    "name": "贵州省公共资源交易云-其他交易",
                    "url": "https://ggzy.guizhou.gov.cn/xxfw/qttzjy/",
                    "collector": "ggzy",
                    "channel_id": "5904479",
                },
            },
        )

    def test_public_item_keeps_channel_specific_source_name(self):
        source = {
            "name": "贵州省公共资源交易云-政府采购",
            "channel_id": "5904543",
        }
        listing = {
            "docTitle": "公园绿化及广告标牌制作项目采购公告",
            "announcement": "采购公告",
            "docRelTime": 1784217600000,
            "docSourceName": "贵州省",
            "apiUrl": "https://ggzy.guizhou.gov.cn/tradeInfo/detailHtml?metaId=1",
        }

        item = item_from_listing(
            source,
            listing,
            "采购内容：公园绿化及广告标牌制作。二、申请人的资格要求：无。",
            ["广告", "标牌", "公园", "绿化"],
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["source_name"], source["name"])
        self.assertEqual(item["matched_keywords"], ["广告", "标牌", "公园", "绿化"])


if __name__ == "__main__":
    unittest.main()
