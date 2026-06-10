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
    _deadline,
    _parties,
    _project_content,
    _project_name,
    _registration_period,
)


class PublicExportTests(unittest.TestCase):
    def test_public_dates_and_source_names_are_normalized(self):
        item = normalize_public_item(
            {
                "published_at": "2026-06-08",
                "bid_deadline": "2026-06-10 18:00",
                "registration_deadline": "2026-06-10 17:00",
                "url": "http://ztb.guizhou.gov.cn/trade/bulletin/?id=1",
                "summary": "广告制作具体内容",
                "project_content": "广告制作具体内容",
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
        # Partial dates (no year) are kept as-is — no guessing
        self.assertEqual(
            normalize_date('"05-15 18：00"', "2026-05-01", True),
            "05-15 18：00",
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
            "一、项目基本信息 采购内容：户外广告牌制作安装及维护。"
            "采购数量：24块 二、申请人的资格要求"
        )
        self.assertEqual(
            _project_content(text),
            "户外广告牌制作安装及维护",
        )

    def test_similar_headings_are_not_project_content(self):
        for heading in (
            "采购需求",
            "项目主要内容",
            "简要技术要求",
            "项目基本概况介绍",
        ):
            with self.subTest(heading=heading):
                self.assertEqual(
                    _project_content(f"{heading}：户外广告牌制作安装。"),
                    "",
                )

    def test_specific_content_is_preferred_inside_project_overview(self):
        text = (
            "一、项目概况与采购范围：1.项目名称：宣传服务。"
            "2.项目编号：A01。3.采购内容：宣传册设计印刷。"
            "4.服务期：一年。二、供应商资格要求"
        )
        self.assertEqual(_project_content(text), "宣传册设计印刷")

    def test_specific_content_stops_before_next_numbered_item(self):
        text = (
            "采购内容：制作灯杆道旗及户外写真。"
            "2.质保期：一年。3.服务地点：采购人指定地点。"
        )
        self.assertEqual(_project_content(text), "制作灯杆道旗及户外写真")

    def test_procurement_content_with_requirements_suffix_is_allowed(self):
        text = (
            "3.采购内容及要求："
            "3.1采购内容、工作内容及框架合作模式：安全物资采购及配套服务。"
            "3.2质量要求：符合国家标准。"
        )
        self.assertEqual(
            _project_content(text),
            "安全物资采购及配套服务",
        )

    def test_spaced_deadline_and_file_period_are_normalized(self):
        text = (
            "采购文件获取时间：2026年 6 月 9 日至 2026年 6 月 16 日 23:59。"
            "递交响应文件的截止日期和开标时间为 202 6 年 6 月 22 日 14 时 00 分。"
        )
        self.assertEqual(
            _registration_period(text, "2026-06-09"),
            "2026-06-09至2026-06-16",
        )
        self.assertEqual(_deadline(text), "2026年6月22日14时00分")

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
