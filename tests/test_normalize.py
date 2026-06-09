import unittest

from tender_agent.normalize import (
    canonical_url,
    classify_region,
    matched_keywords,
    matched_tender_keywords,
    tender_fingerprint,
)


class NormalizeTests(unittest.TestCase):
    def test_canonical_url_removes_tracking_and_fragment(self):
        self.assertEqual(
            canonical_url("HTTPS://Example.com/a/?utm_source=x&id=2#top"),
            "https://example.com/a?id=2",
        )

    def test_url_based_fingerprint_deduplicates_tracking_variants(self):
        first = tender_fingerprint("项目甲", "https://a.test/p?id=1&utm_source=x")
        second = tender_fingerprint("另一个标题", "https://a.test/p?id=1")
        self.assertEqual(first, second)

    def test_keyword_and_region_matching(self):
        self.assertEqual(
            matched_keywords("贵州省广告标识牌制作", ["广告", "印刷", "标识"]),
            ["广告", "标识"],
        )
        self.assertEqual(
            classify_region("贵阳市观山湖区", ["贵州", "贵阳"], ["重庆"]),
            "included",
        )
        self.assertEqual(
            classify_region("重庆市荣誉墙", ["贵州", "贵阳"], ["重庆"]),
            "excluded",
        )

    def test_tender_keywords_only_use_allowed_fields(self):
        self.assertEqual(
            matched_tender_keywords(
                "高压配电设备维修项目",
                ["更换配电柜及电缆"],
                ["广告", "证书"],
            ),
            [],
        )
        self.assertEqual(
            matched_tender_keywords(
                "户外广告制作项目",
                [],
                ["广告", "证书"],
            ),
            ["广告"],
        )
        self.assertEqual(
            matched_tender_keywords(
                "校园设施维修项目",
                ["采购范围：制作安装导视标牌"],
                ["导视", "标牌", "证书"],
            ),
            ["导视", "标牌"],
        )


if __name__ == "__main__":
    unittest.main()
