import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tender_agent.collectors import tobacco


class TobaccoCollectorTests(unittest.TestCase):
    def test_detail_is_normalized_from_allowed_sections(self):
        html = """
        <div class="service_title">
          <h2>贵州省烟草专卖局宣传物料采购项目-竞争谈判公告</h2>
          <span>发布时间：2026-06-16 18:36:52</span>
          <p>项目名称: 贵州省烟草专卖局宣传物料采购项目</p>
          <p>二、项目概况和招标范围</p>
          <p>采购内容与范围：宣传册、展板、标识标牌制作。</p>
          <p>三、供应商资格要求</p>
          <p>递交截止时间：2026年06月29日09时30分00秒</p>
          <p>采购人：贵州省烟草专卖局（公司）</p>
          <p>采购代理机构：贵州测试代理有限公司</p>
        </div>
        """

        item = tobacco.item_from_detail(
            {
                "url": "https://cgjy.tobacco.com.cn/jzfwzb/42052.jhtml",
                "title": "贵州省烟草专卖局宣传物料采购项目-竞争谈判公告",
                "published_at": "2026-06-16",
            },
            html,
            ["宣传", "展板", "标识"],
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["published_at"], "2026-06-16")
        self.assertEqual(item["bid_deadline"], "2026-06-29 09:30")
        self.assertEqual(item["buyer"], "贵州省烟草专卖局（公司）")
        self.assertEqual(item["agency"], "贵州测试代理有限公司")
        self.assertEqual(
            item["project_content"],
            "宣传册、展板、标识标牌制作",
        )
        self.assertEqual(item["source_name"], "中烟电子采购平台")

    def test_buyer_keyword_and_footer_region_do_not_cause_match(self):
        html = """
        <div class="service_title">
          <h2>电子设备采购项目-询价公告</h2>
          <span>发布时间：2026-06-16 16:09:17</span>
          <p>项目名称: 电子设备采购项目</p>
          <p>采购内容与范围：普通电子设备。</p>
          <p>采购人：贵州广告文化有限公司</p>
        </div>
        <div class="copyright_title">贵州 中烟电子采购平台</div>
        """

        item = tobacco.item_from_detail(
            {
                "url": "https://cgjy.tobacco.com.cn/xjhw/41939.jhtml",
                "title": "电子设备采购项目-询价公告",
                "published_at": "2026-06-16",
            },
            html,
            ["广告", "文化"],
        )

        self.assertIsNone(item)

    @patch("tender_agent.collectors.tobacco._fetch_text")
    def test_collection_paginates_and_skips_processed_nonmatches(self, fetch):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        list_page = f"""
        <a href="/jzfwzb/10001.jhtml" style="flex: 1">
          <span class="span_hover" title="贵州设备采购项目-询价公告"></span>
          <i>{today}</i>
        </a>
        """
        detail = f"""
        <div class="service_title">
          <h2>贵州设备采购项目-询价公告</h2>
          <span>发布时间：{today} 09:00:00</span>
          <p>项目名称: 贵州设备采购项目</p>
          <p>采购内容与范围：普通设备。</p>
        </div>
        """

        def response(url, **kwargs):
            if url.endswith("/zbNotice/index.jhtml"):
                return list_page
            if "/zbNotice/index_2.jhtml" in url:
                return ""
            if "/competition/" in url:
                return ""
            return detail

        fetch.side_effect = response
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            first = tobacco.collect(["广告"], [], state, max_pages=2)
            first_call_count = fetch.call_count
            second = tobacco.collect(["广告"], [], state, max_pages=2)

            self.assertEqual(first, [])
            self.assertEqual(second, [])
            self.assertEqual(first_call_count, 4)
            self.assertEqual(fetch.call_count, 7)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["processed"]), 1)


if __name__ == "__main__":
    unittest.main()
