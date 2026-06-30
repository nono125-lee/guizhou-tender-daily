from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tender_agent import unified_site


class UnifiedSiteTests(unittest.TestCase):
    def test_build_writes_manifest_matches_status_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            construction_data = root / "site/construction/data/latest.json"
            plan_data = root / "site/tender-plan/data/latest.json"
            assets = root / "skill-assets"
            unified = root / "site/opportunities"
            construction_data.parent.mkdir(parents=True)
            plan_data.parent.mkdir(parents=True)
            (assets / "assets").mkdir(parents=True)
            (assets / "index.html").write_text("<title>统一页面</title>", encoding="utf-8")
            (assets / "assets/style.css").write_text("body{}", encoding="utf-8")
            (assets / "assets/app.js").write_text("console.log('ok')", encoding="utf-8")
            construction_data.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-06-30T08:00:00+08:00",
                        "coverage": "施工",
                        "stats": {"total": 2},
                        "warnings": [],
                        "items": [{"title": "A"}, {"title": "B"}],
                    }
                ),
                encoding="utf-8",
            )
            plan_data.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-06-30T08:10:00+08:00",
                        "coverage": "计划",
                        "stats": {"total": 3, "ultra_long_projects": 1, "priority_projects": 1},
                        "warnings": [],
                        "items": [{"title": "P"}],
                        "priority_notices": [{"notice": {"title": "N"}}],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(unified_site, "CONSTRUCTION_DATA", construction_data),
                patch.object(unified_site, "PLAN_DATA", plan_data),
                patch.object(unified_site, "UNIFIED_ASSETS", assets),
                patch.object(unified_site, "UNIFIED_SITE", unified),
            ):
                result = unified_site.build_unified_site()

            manifest = json.loads((unified / "data/manifest.json").read_text())
            matches = json.loads((unified / "data/matches.json").read_text())
            self.assertEqual(result["summary"]["construction_items"], 2)
            self.assertEqual(manifest["summary"]["ultra_long_projects"], 1)
            self.assertEqual(matches["stats"]["total"], 1)
            self.assertTrue((unified / "assets/app.js").exists())

    def test_page_has_requested_views_and_business_filters(self):
        skill = (
            Path(__file__).resolve().parents[1]
            / "skills/guizhou-construction-opportunity-intelligence/assets/site"
        )
        html = (skill / "index.html").read_text(encoding="utf-8")
        app = (skill / "assets/app.js").read_text(encoding="utf-8")
        for view in ("queue", "construction", "plans", "matches", "status"):
            self.assertIn(f'data-view="{view}"', html)
        self.assertIn("近 7 天待处理", html)
        self.assertIn("<h1>标讯雷达</h1>", html)
        for control in (
            "construction-region",
            "construction-date-range",
            "construction-source",
            "construction-reg-date",
            "construction-cutoff-date",
            "construction-qualification",
            "plan-prefecture",
            "plan-district",
            "plan-date-range",
            "plan-planned-month",
            "fund-strip",
        ):
            self.assertIn(f'id="{control}"', html)
        self.assertNotIn('id="review-filter"', html)
        self.assertIn("guizhou-construction-opportunity-review-v1", app)
        self.assertIn("candidate_plans", app)
        self.assertIn("groupedPlans", app)
        self.assertIn('"政府投资"', app)
        self.assertNotIn("groupedUltraPlans", app)


if __name__ == "__main__":
    unittest.main()
