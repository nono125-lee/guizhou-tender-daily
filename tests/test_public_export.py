import json
import tempfile
import unittest
from pathlib import Path

from tender_agent.importers import HistoricalTender
from tender_agent.public_export import export_public_snapshot
from tender_agent.repository import Repository


class PublicExportTests(unittest.TestCase):
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
                self.assertNotIn("phone", raw)
                self.assertNotIn("contact", raw)
                self.assertNotIn("password", raw)
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
