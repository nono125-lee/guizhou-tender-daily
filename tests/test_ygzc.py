import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tender_agent.collectors import ygzc


class YgzcCollectorTests(unittest.TestCase):
    def test_detail_is_normalized_and_only_allowed_content_is_matched(self):
        item = ygzc.item_from_detail(
            {
                "id": "notice-1",
                "title": "品牌宣传物料制作采购公告",
                "pubtime": "2026-06-14 09:00:00",
            },
            {
                "data": {
                    "title": "品牌宣传物料制作采购公告",
                    "time": "2026-06-14 09:00:00",
                    "fields": [
                        {"name": "项目名称", "value": "品牌宣传物料制作"},
                        {"name": "项目预算", "value": "20000"},
                    ],
                    "content": (
                        "<p>采购内容：宣传册、标识标牌及展板制作。</p>"
                        "<p>获取采购文件时间：2026年6月14日至"
                        "2026年6月16日。</p>"
                        "<p>采购人：贵阳测试有限公司</p>"
                        "<p>采购代理机构：贵州测试代理有限公司</p>"
                    ),
                    "timeSummary": {
                        "bidEndTime": "2026-06-17 10:00:00",
                    },
                }
            },
            ["宣传", "标识", "展板"],
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["published_at"], "2026-06-14")
        self.assertEqual(item["budget"], "2万元")
        self.assertEqual(item["bid_deadline"], "2026-06-17 10:00")
        self.assertEqual(
            item["registration_period"], "2026-06-14至2026-06-16"
        )
        self.assertEqual(item["buyer"], "贵阳测试有限公司")
        self.assertEqual(item["agency"], "贵州测试代理有限公司")
        self.assertEqual(
            item["project_content"], "宣传册、标识标牌及展板制作"
        )
        self.assertEqual(
            item["source_name"],
            "贵阳市公共资源交易国有企业招标采购平台",
        )

    def test_buyer_keyword_does_not_cause_match(self):
        item = ygzc.item_from_detail(
            {"id": "notice-2", "title": "设备维修采购公告"},
            {
                "data": {
                    "title": "设备维修采购公告",
                    "fields": [
                        {"name": "项目名称", "value": "设备维修"},
                    ],
                    "content": (
                        "<p>采购内容：高压设备维修。</p>"
                        "<p>采购人：贵州广告文化有限公司</p>"
                    ),
                }
            },
            ["广告", "文化"],
        )
        self.assertIsNone(item)

    @patch("tender_agent.collectors.ygzc._request_json")
    def test_collection_paginates_and_skips_processed_nonmatches(self, request):
        listings = [
            {
                "id": f"notice-{index}",
                "title": f"设备采购公告{index}",
                "pubtime": "2026-06-14 09:00:00",
            }
            for index in range(101)
        ]

        def response(url, params=None, **kwargs):
            if url == ygzc.LIST_API:
                page = params["page"]
                start = (page - 1) * 100
                return {
                    "code": 0,
                    "data": {
                        "total": 101,
                        "data": listings[start:start + 100],
                    },
                }
            notice_id = url.rsplit("/", 1)[-1]
            return {
                "code": 0,
                "data": {
                    "title": next(
                        row["title"] for row in listings
                        if row["id"] == notice_id
                    ),
                    "time": "2026-06-14 09:00:00",
                    "fields": [
                        {"name": "项目名称", "value": "设备采购"},
                    ],
                    "content": "<p>采购内容：普通设备。</p>",
                },
            }

        request.side_effect = response
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            first = ygzc.collect(["广告"], [], state)
            first_call_count = request.call_count
            second = ygzc.collect(["广告"], [], state)

            self.assertEqual(first, [])
            self.assertEqual(second, [])
            self.assertEqual(first_call_count, 103)
            self.assertEqual(request.call_count, 105)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["processed"]), 101)


if __name__ == "__main__":
    unittest.main()
