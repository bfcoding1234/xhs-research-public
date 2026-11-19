from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.server import ResearchApplication


class NoopRunner:
    def run(self, task_id, request):
        return None


class SourceLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("来源数量限制", "mixed", {})
        self.settings = SimpleNamespace(
            host="127.0.0.1", port=4318, max_author_notes=300,
            max_keywords_per_task=5, max_authors_per_task=5,
        )
        self.app = ResearchApplication(self.settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")

    def tearDown(self):
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def test_rejects_source_counts_above_default_limit(self):
        with self.assertRaisesRegex(ValueError, "单次关键词上限 5"):
            self.app.create_task({
                "mode": "keyword", "project_id": self.project_id, "created_from": "test",
                "source": {"keywords": [f"关键词 {index}" for index in range(6)]},
            })
        with self.assertRaisesRegex(ValueError, "单次作者上限 5"):
            self.app.create_task({
                "mode": "author", "project_id": self.project_id, "created_from": "test",
                "source": {"author_ids": [f"author-{index}" for index in range(6)]},
            })

    def test_uses_configured_limits_and_deduplicates_keywords(self):
        self.db.set_app_settings({"max_keywords_per_task": 2, "max_authors_per_task": 2})
        with self.assertRaisesRegex(ValueError, "单次关键词上限 2"):
            self.app.create_task({
                "mode": "keyword", "project_id": self.project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理", "内容策略", "职业发展"]},
            })
        result = self.app.create_task({
            "mode": "keyword", "project_id": self.project_id, "created_from": "test",
            "source": {"keywords": ["AI 产品经理", "ai 产品经理", "内容策略"]},
        })
        task = self.db.get_task(result["id"])
        self.assertEqual(task["input_json"]["source"]["keywords"], ["AI 产品经理", "内容策略"])

    def test_author_post_limit_can_exceed_three_hundred(self):
        self.db.set_app_settings({"max_author_notes": 1200})
        result = self.app.create_task({
            "mode": "author", "project_id": self.project_id, "created_from": "test",
            "source": {"author_ids": ["author-one"]},
            "limits": {"discovery": 900, "deep": 600},
        })

        task = self.db.get_task(result["id"])
        self.assertEqual(task["input_json"]["limits"], {"discovery": 900, "deep": 600})


if __name__ == "__main__":
    unittest.main()
