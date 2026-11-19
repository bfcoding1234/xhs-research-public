from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database


class InvalidSearchCardCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialize_removes_only_empty_hot_query_placeholders_and_cascades_relations(self):
        project_id = self.db.create_project("清理测试", "keyword", {})
        task_id = self.db.create_task(
            project_id,
            "keyword",
            "test",
            {"source": {"keywords": ["Workbody工作台"]}},
        )
        invalid_note_id = "d37df0a7-0696-4188-8c36-12451430c756#1785472796991"
        invalid_post_id = self.db.upsert_post({
            "note_id": invalid_note_id,
            "url": f"https://www.xiaohongshu.com/explore/{invalid_note_id}",
        })
        self.db.attach_post_to_project(project_id, invalid_post_id, task_id)
        self.db.record_task_post(
            task_id,
            invalid_post_id,
            "keyword",
            "Workbody工作台",
            6,
        )
        self.db.upsert_media(invalid_post_id, {"url": ""}, 0, "cover")
        preserved_post_id = self.db.upsert_post({
            "note_id": "a997146f-5f72-45f7-86e4-c3b6e401889c#1785418362524",
            "title": "有内容的记录必须保留",
        })

        removed = self.db.initialize()

        self.assertEqual(removed, 1)
        self.assertIsNone(self.db.get_post(invalid_post_id))
        self.assertIsNotNone(self.db.get_post(preserved_post_id))
        self.assertEqual(
            self.db.scalar("SELECT COUNT(*) FROM project_posts WHERE post_id=?", (invalid_post_id,)),
            0,
        )
        self.assertEqual(
            self.db.scalar("SELECT COUNT(*) FROM task_posts WHERE post_id=?", (invalid_post_id,)),
            0,
        )
        self.assertEqual(
            self.db.scalar("SELECT COUNT(*) FROM media_assets WHERE post_id=?", (invalid_post_id,)),
            0,
        )


if __name__ == "__main__":
    unittest.main()
