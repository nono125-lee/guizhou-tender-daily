import unittest

from tender_agent.construction_rules import (
    qualification_matches,
    qualification_section,
)


CONFIG = {
    "qualification_keywords": [
        "建筑工程施工总承包",
        "市政公用工程施工总承包",
        "施工劳务",
    ],
    "title_exclude_keywords": ["监理", "审计", "招标代理"],
}


class ConstructionRulesTests(unittest.TestCase):
    def test_only_qualification_section_is_extracted(self):
        text = (
            "二、项目概况：建筑工程施工总承包项目。"
            "三、投标人资格要求：具备市政公用工程施工总承包二级资质。"
            "四、招标文件获取：网上下载。"
        )
        qualification = qualification_section(text)
        self.assertIn("市政公用工程施工总承包", qualification)
        self.assertNotIn("项目概况", qualification)

    def test_title_exclusions_override_qualification_match(self):
        matches = qualification_matches(
            "某道路工程施工监理招标公告",
            "具备市政公用工程施工总承包资质",
            CONFIG,
        )
        self.assertEqual(matches, [])

    def test_qualification_keyword_matches(self):
        self.assertEqual(
            qualification_matches(
                "某道路改造施工招标公告",
                "投标人须具备施工劳务资质",
                CONFIG,
            ),
            ["施工劳务"],
        )
