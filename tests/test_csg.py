import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tender_agent.collectors import csg


class CsgCollectorTests(unittest.TestCase):
    def test_detail_is_normalized_from_allowed_sections(self):
        html = """
        <h1 class="s-title">贵州电网公司党建宣传阵地建设服务采购公告</h1>
        <div class="s-date">发布时间： 2026-06-16 18:17:47</div>
        <p>1.采购条件 采购人为贵州电网有限责任公司</p>
        <p>2.项目概况和采购范围</p>
        <p>2.1项目概述：建设党员活动阵地。</p>
        <p>2.2采购范围：宣传展板、党建书屋标识、横幅、海报制作安装。</p>
        <p>3.供应商资格要求</p>
        <p>投标文件递交截止时间：2026年06月29日09时30分00秒</p>
        <p>采购代理机构：南方电网供应链集团有限公司</p>
        <li class="Top10">下一篇</li>
        """

        item = csg.item_from_detail(
            {
                "url": "https://www.bidding.csg.cn/fzbgg/1200433187.jhtml",
                "title": "贵州电网公司党建宣传阵地建设服务采购公告",
                "buyer": "贵州电网公司",
                "published_at": "2026-06-16",
            },
            html,
            ["宣传", "党建", "标识", "横幅", "海报"],
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["published_at"], "2026-06-16")
        self.assertEqual(item["bid_deadline"], "2026-06-29 09:30")
        self.assertEqual(item["buyer"], "贵州电网有限责任公司")
        self.assertEqual(item["agency"], "南方电网供应链集团有限公司")
        self.assertIn("宣传展板", item["project_content"])
        self.assertEqual(
            item["source_name"], "中国南方电网供应链统一服务平台"
        )

    def test_non_guizhou_detail_is_excluded_even_when_content_matches(self):
        html = """
        <h1 class="s-title">党员活动阵地建设服务项目采购公告</h1>
        <div class="s-date">发布时间： 2026-06-16 18:17:47</div>
        <p>1.采购条件 采购人为南方电网产业发展集团有限责任公司</p>
        <p>2.项目概况和采购范围</p>
        <p>采购范围：宣传展板、横幅、海报制作。</p>
        <p>3.供应商资格要求</p>
        """

        item = csg.item_from_detail(
            {
                "url": "https://www.bidding.csg.cn/fzbgg/1200433187.jhtml",
                "title": "党员活动阵地建设服务项目采购公告",
                "buyer": "南方电网产业投资集团有限责任公司",
                "published_at": "2026-06-16",
            },
            html,
            ["宣传", "横幅", "海报"],
        )

        self.assertIsNone(item)

    @patch("tender_agent.collectors.csg._fetch_text")
    def test_collection_paginates_and_skips_processed_nonmatches(self, fetch):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        list_page = f"""
        <li>
          <span class="Right">
            <span class="Black14 Gray">{today}</span>
          </span>
          <a class="Blue">贵州电网公司</a>
          <a href="/fzbgg/1200000001.jhtml" target="_blank">
            贵州电网公司普通设备采购公告
          </a>
        </li>
        """
        detail = f"""
        <h1 class="s-title">贵州电网公司普通设备采购公告</h1>
        <div class="s-date">发布时间： {today} 09:00:00</div>
        <p>1.采购条件 采购人为贵州电网有限责任公司</p>
        <p>2.项目概况和采购范围</p>
        <p>采购范围：普通设备。</p>
        <p>3.供应商资格要求</p>
        """

        def response(url, **kwargs):
            if url.endswith("/fzbgg/index.jhtml"):
                return list_page
            if "/fzbgg/index_2.jhtml" in url:
                return ""
            if url.endswith("/zbgg/index.jhtml") or url.endswith("/lxcggg/index.jhtml"):
                return ""
            return detail

        fetch.side_effect = response
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            first = csg.collect(["广告"], [], state, max_pages=2)
            first_call_count = fetch.call_count
            second = csg.collect(["广告"], [], state, max_pages=2)

            self.assertEqual(first, [])
            self.assertEqual(second, [])
            self.assertEqual(first_call_count, 5)
            self.assertEqual(fetch.call_count, 9)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["processed"]), 1)


if __name__ == "__main__":
    unittest.main()
