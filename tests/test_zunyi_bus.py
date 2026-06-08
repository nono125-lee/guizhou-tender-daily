import unittest

from tender_agent.collectors.zunyi_bus import parse_detail, parse_notices


class ZunyiBusCollectorTests(unittest.TestCase):
    def test_notice_list_and_detail_are_parsed(self):
        listing = """
        <li>
          <a href="/tzgg/2250.html">公交户外广告及信息标识采购公告</a>
          <span>2026.06.08</span>
        </li>
        """
        notices = parse_notices(listing)
        self.assertEqual(len(notices), 1)
        detail = parse_detail(
            notices[0],
            """
            <p>遵义市公共交通能源有限责任公司现采购公交户外广告、
            站牌和标识制作安装。</p>
            <p>报名时间：2026年6月8日起至2026年6月15日止。</p>
            """,
            ["广告", "标识"],
        )
        self.assertEqual(detail["published_at"], "2026-06-08")
        self.assertEqual(
            detail["registration_period"], "2026-06-08至2026-06-15"
        )
        self.assertEqual(detail["bid_deadline"], "2026-06-15")
        self.assertEqual(
            detail["source_name"],
            "遵义市公共交通（集团）有限责任公司",
        )


if __name__ == "__main__":
    unittest.main()
