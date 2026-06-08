import tempfile
import unittest
from pathlib import Path

from tender_agent.digest import build_daily_digest
from tender_agent.importers import HistoricalTender
from tender_agent.repository import Repository


class DigestTests(unittest.TestCase):
    def test_digest_only_includes_matching_guizhou_tenders(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "test.sqlite3")
            try:
                base = dict(
                    collected_at="2026-06-08",
                    url="https://example.test/1",
                    budget="10万",
                    summary="广告制作",
                    location="贵阳",
                    registration_fee="",
                    registration_deadline="",
                    buyer="采购人",
                    contact="",
                    phone="",
                    agency="",
                    bid_deadline="2026-06-10",
                    submission_channel="线上",
                    submission_method="电子",
                    submission_place="",
                )
                repository.upsert_tender(
                    HistoricalTender(title="广告项目", **base),
                    ["广告"],
                    "included",
                )
                repository.upsert_tender(
                    HistoricalTender(
                        title="重庆广告项目",
                        **{**base, "url": "https://example.test/2", "location": "重庆"},
                    ),
                    ["广告"],
                    "excluded",
                )
                digest = build_daily_digest(repository, "2026-06-08")
                self.assertEqual(digest["total"], 1)
                self.assertEqual(digest["items"][0]["title"], "广告项目")
                self.assertEqual(repository.latest_collection_date(), "2026-06-08")
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
