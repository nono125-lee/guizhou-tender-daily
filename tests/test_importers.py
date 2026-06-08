import unittest
from pathlib import Path

from tender_agent.importers import (
    _excel_date_text,
    load_historical_tenders,
    load_keywords,
    load_source_accounts,
)


INPUT_DIR = Path("/Users/nonolee/Desktop/共享win")


@unittest.skipUnless(INPUT_DIR.exists(), "用户附件目录不存在")
class ImporterTests(unittest.TestCase):
    def test_excel_serial_date_is_normalized(self):
        self.assertEqual(_excel_date_text(46043), "2026-01-21")

    def test_user_inputs_are_readable(self):
        keywords = load_keywords(INPUT_DIR / "02图文广告行业关键词库.txt")
        accounts = load_source_accounts(INPUT_DIR / "01信息源库.xlsx")
        tenders = load_historical_tenders(INPUT_DIR / "03标讯信息表.xlsx")
        self.assertGreaterEqual(len(keywords), 40)
        self.assertGreaterEqual(len(accounts), 100)
        self.assertGreaterEqual(len(tenders), 500)
        self.assertTrue(accounts[0].source_name)
        self.assertTrue(tenders[0].title)
        self.assertTrue(all(not item.collected_at.isdigit() for item in tenders))


if __name__ == "__main__":
    unittest.main()
