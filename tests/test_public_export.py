import json
import tempfile
import unittest
from pathlib import Path

from tender_agent.importers import HistoricalTender
from tender_agent.public_export import (
    export_public_snapshot,
    normalize_date,
    normalize_public_item,
    source_name_for_url,
)
from tender_agent.repository import Repository
from tender_agent.collectors.guizhou_ztb import (
    _parties,
    _project_content,
    _project_name,
)


class PublicExportTests(unittest.TestCase):
    def test_public_dates_and_source_names_are_normalized(self):
        item = normalize_public_item(
            {
                "published_at": "2026-06-08",
                "bid_deadline": "06-10 18:00",
                "registration_deadline": "06-10 17:00",
                "url": "http://ztb.guizhou.gov.cn/trade/bulletin/?id=1",
                "summary": "广告制作具体内容",
            },
            {"ztb.guizhou.gov.cn": "贵州省招标投标公共服务平台"},
        )
        self.assertEqual(item["bid_deadline"], "2026-06-10 18:00")
        self.assertEqual(
            item["registration_period"], "2026-06-08至2026-06-10"
        )
        self.assertEqual(
            item["source_name"], "贵州省招标投标公共服务平台"
        )
        self.assertEqual(item["project_content"], "广告制作具体内容")
        self.assertEqual(item["date_basis"], "collected")

    def test_chinese_datetime_is_normalized(self):
        self.assertEqual(
            normalize_date("2026年6月10日18：00", "2026-06-08", True),
            "2026-06-10 18:00",
        )
        self.assertEqual(
            normalize_date('"05-15 18：00"', "2026-05-01", True),
            "2026-05-15 18:00",
        )

    def test_unknown_registration_period_stays_blank(self):
        item = normalize_public_item(
            {
                "published_at": "2026-06-08",
                "url": "https://example.com/tender",
            },
            {"example.com": "示例平台"},
        )
        self.assertEqual(item["registration_period"], "")

    def test_source_name_is_taken_from_exact_mapping(self):
        self.assertEqual(
            source_name_for_url(
                "https://cgjy.tobacco.com.cn/xbfw/1.jhtml",
                {"cgjy.tobacco.com.cn": "中烟电子采购平台"},
            ),
            "中烟电子采购平台",
        )

    def test_project_content_extracts_core_section(self):
        text = (
            "一、项目基本信息 采购主要内容：户外广告牌制作安装及维护。"
            "采购数量：24块 二、申请人的资格要求"
        )
        self.assertEqual(
            _project_content(text),
            "户外广告牌制作安装及维护",
        )

    def test_qualification_and_buyer_text_are_not_project_content(self):
        text = (
            "项目名称：高压配电设备维修更换项目。"
            "采购人：贵州广告文化有限公司。"
            "供应商资格要求：提供相关资质证书及标识材料。"
        )
        self.assertEqual(
            _project_name("高压配电设备维修更换项目采购公告", text),
            "高压配电设备维修更换项目",
        )
        self.assertEqual(_project_content(text), "")

    def test_buyer_and_agency_are_separated(self):
        buyer, agency = _parties(
            (
                "采购人名称：贵阳市商务局 项目联系人：王老师 "
                "采购代理机构名称：贵州新山水建设咨询（集团）有限公司 "
                "联系人：李老师"
            ),
            "贵州新山水建设咨询（集团）有限公司",
        )
        self.assertEqual(buyer, "贵阳市商务局")
        self.assertEqual(agency, "贵州新山水建设咨询（集团）有限公司")

    def test_contact_section_party_format_is_supported(self):
        buyer, agency = _parties(
            (
                "凡对本次采购提出询问，请按以下方式联系。"
                "1.采购人信息 名 称：贵州日报当代传媒有限责任公司 "
                "地 址：贵阳市乌当区。"
                "2.采购代理机构信息 名 称：新华招标有限公司 "
                "地 址：贵阳市云岩区。"
            ),
            "新华招标有限公司",
        )
        self.assertEqual(buyer, "贵州日报当代传媒有限责任公司")
        self.assertEqual(agency, "新华招标有限公司")

    def test_buyer_designated_place_is_not_a_party_name(self):
        buyer, agency = _parties(
            "服务地点：采购人指定地点。采购代理机构：大成工程咨询有限公司",
            "大成工程咨询有限公司",
        )
        self.assertEqual(buyer, "")
        self.assertEqual(agency, "大成工程咨询有限公司")

    def test_export_contains_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = Repository(root / "private.sqlite3")
            try:
                repository.upsert_tender(
                    HistoricalTender(
                        collected_at="2026-06-08",
                        title="贵阳广告项目",
                        url="http://ztb.guizhou.gov.cn/trade/bulletin/?id=1",
                        budget="10万元",
                        summary="广告制作",
                        location="贵阳",
                        registration_fee="",
                        registration_deadline="",
                        buyer="采购人",
                        contact="张老师",
                        phone="13800000000",
                        agency="",
                        bid_deadline="2026-06-10",
                        submission_channel="",
                        submission_method="",
                        submission_place="",
                    ),
                    ["广告"],
                    "included",
                )
                output = root / "latest.json"
                export_public_snapshot(repository, output)
                payload = json.loads(output.read_text(encoding="utf-8"))
                raw = output.read_text(encoding="utf-8")
                self.assertEqual(payload["items"][0]["title"], "贵阳广告项目")
                self.assertEqual(
                    payload["items"][0]["date_basis"], "collected"
                )
                self.assertNotIn("phone", raw)
                self.assertNotIn("contact", raw)
                self.assertNotIn("password", raw)
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
