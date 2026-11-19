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


class MyProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.settings = SimpleNamespace(
            host="127.0.0.1",
            port=4318,
            max_author_notes=300,
            max_keywords_per_task=5,
            max_authors_per_task=5,
        )
        self.app = ResearchApplication(
            self.settings,
            self.db,
            NoopRunner(),
            WORKBENCH_ROOT / "web",
        )

    def tearDown(self):
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def test_only_one_my_project_can_exist(self):
        first = self.db.create_project(
            "个人项目", "author", {"project_kind": "my_project"}
        )
        self.assertGreater(first, 0)

        with self.assertRaisesRegex(ValueError, "个人项目已经存在"):
            self.db.create_project(
                "另一个个人项目", "author", {"project_kind": "my_project"}
            )

        with self.assertRaisesRegex(ValueError, "固定为作者调研"):
            self.db.create_project(
                "错误类型", "keyword", {"project_kind": "my_project"}
            )

    def test_my_project_requires_author_mode_and_exactly_one_author(self):
        project_id = self.db.create_project(
            "个人项目", "author", {"project_kind": "my_project"}
        )
        accepted = self.app.create_task({
            "mode": "author",
            "project_id": project_id,
            "created_from": "test",
            "source": {"author_ids": ["author-one"]},
        })
        self.assertEqual(accepted["status"], "queued")

        with self.assertRaisesRegex(ValueError, "必须只包含一位作者"):
            self.app.create_task({
                "mode": "author",
                "project_id": project_id,
                "created_from": "test",
                "source": {"author_ids": ["author-one", "author-two"]},
            })
        with self.assertRaisesRegex(ValueError, "固定为作者调研"):
            self.app.create_task({
                "mode": "keyword",
                "project_id": project_id,
                "created_from": "test",
                "source": {"keywords": ["AI"]},
            })

    def test_initializes_me_from_an_existing_author_without_a_task(self):
        author_id = self.db.upsert_author({
            "author_id": "existing-author",
            "display_name": "已有作者",
        })

        result = self.app.setup_my_author({"author_id": author_id})

        self.assertEqual(result, {"author_id": author_id, "task": None})
        self.assertEqual(self.db.get_app_settings()["my_author_id"], author_id)
        self.assertEqual(self.db.list_tasks(), [])

    def test_initializes_me_from_a_new_author_and_starts_preview_scrape(self):
        self.db.set_app_settings({"default_discovery": 120})

        result = self.app.setup_my_author({"external_author_id": "new-author-id"})

        author = next(
            value for value in self.db.list_authors()
            if value["author_id"] == "new-author-id"
        )
        self.assertEqual(result["author_id"], author["id"])
        self.assertEqual(self.db.get_app_settings()["my_author_id"], author["id"])
        task = self.db.get_task(result["task"]["id"])
        self.assertIsNone(task["project_id"])
        self.assertEqual(task["input_json"]["limits"], {"discovery": 120, "deep": 0})
        self.assertEqual(
            task["input_json"]["author_update"]["scopes"],
            ["basic_info", "preview_posts"],
        )

        with self.assertRaisesRegex(ValueError, "后台配置修改"):
            self.app.setup_my_author({"author_id": author["id"]})

    def test_me_setup_requires_exactly_one_valid_source(self):
        author_id = self.db.upsert_author({"author_id": "existing-author"})

        with self.assertRaisesRegex(ValueError, "请选择已有作者"):
            self.app.setup_my_author({})
        with self.assertRaisesRegex(ValueError, "请选择已有作者"):
            self.app.setup_my_author({
                "author_id": author_id,
                "external_author_id": "another-author",
            })
        with self.assertRaisesRegex(ValueError, "stable author ID"):
            self.app.setup_my_author({"external_author_id": "不是作者ID"})
        with self.assertRaisesRegex(ValueError, "不要输入主页链接"):
            self.app.setup_my_author({
                "external_author_id": "https://www.xiaohongshu.com/user/profile/abc123",
            })
        self.assertNotIn("my_author_id", self.db.get_app_settings())


if __name__ == "__main__":
    unittest.main()
