import tempfile
import unittest
from pathlib import Path

from tender_agent.priority_watch import add_project, build_watchlist_matches, load_watchlist


class PriorityWatchTests(unittest.TestCase):
    def test_add_project_persists_and_updates_by_normalized_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "priority.json"
            add_project("贵州某公园绿化项目", "超长期特别国债", path)
            add_project("贵州某公园绿化项目 招标计划", "财政资金", path)
            payload = load_watchlist(path)

        self.assertEqual(len(payload["projects"]), 1)
        self.assertEqual(payload["projects"][0]["fund_source"], "财政资金")

    def test_user_watched_project_matches_all_notice_feeds(self):
        watchlist = {
            "projects": [
                {"project_name": "贵州某公园绿化项目", "fund_source": "超长期特别国债"}
            ]
        }
        plans = [
            {
                "project_name": "贵州某公园绿化项目",
                "published_at": "2026-07-01",
                "url": "https://example.com/plan",
            }
        ]
        notices = [
            {
                "items": [
                    {
                        "project_name": "贵州某公园绿化项目施工招标公告",
                        "published_at": "2026-07-03",
                        "url": "https://example.com/notice",
                        "industry_categories": ["landscaping"],
                    }
                ]
            }
        ]
        matches = build_watchlist_matches(watchlist, plans, notices)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["priority_source"], "user_watchlist")
        self.assertEqual(matches[0]["plan"]["fund_source"], "超长期特别国债")
        self.assertEqual(matches[0]["match"]["match_level"], "important")


if __name__ == "__main__":
    unittest.main()
