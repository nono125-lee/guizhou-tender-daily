from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConstructionDocumentReviewUiTests(unittest.TestCase):
    def test_construction_page_uses_document_review_wording(self):
        html = (ROOT / "site/construction/index.html").read_text(encoding="utf-8")
        script = (ROOT / "site/construction/assets/app.js").read_text(encoding="utf-8")

        self.assertNotIn("重点项目", html)
        self.assertNotIn("重点项目", script)
        self.assertIn("查阅文件", html)
        self.assertIn("TENDER_DOCUMENT_REVIEW_JSON", script)
        self.assertIn("construction-tender-document-review", script)

    def test_existing_browser_marks_are_preserved(self):
        script = (ROOT / "site/construction/assets/app.js").read_text(encoding="utf-8")

        self.assertIn(
            'const KEY_STORAGE = "construction-tender-key-projects-v1";',
            script,
        )


if __name__ == "__main__":
    unittest.main()
