from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "workbench"))

from xhs_research.db import Database
from xhs_research.release import DataReleaseService


class DataReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.source_dir = root / "xhs-research-data-develop"
        self.target_dir = root / "xhs-research-data"
        self.source = Database(self.source_dir / "research.sqlite3")
        self.target = Database(self.target_dir / "research.sqlite3")
        self.source.initialize()
        self.target.initialize()
        self.release = DataReleaseService(self.source_dir, stable_data_dir=self.target_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_publishes_primary_entities_media_and_completed_tasks(self):
        media = self.source_dir / "media" / "covers" / "sample.png"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"\x89PNG\r\n\x1a\nrelease sample")
        author = self.source.upsert_author({"author_id": "author-1", "display_name": "开发作者"})
        post = self.source.upsert_post({
            "note_id": "note-1", "author_id": "author-1", "title": "开发帖子",
            "cover_local_path": str(media), "detail_level": "detailed",
        })
        self.source.upsert_media(post, {"local_path": str(media), "url": "https://example.com/image"}, 0, "image")
        project = self.source.create_project("开发项目", "keyword", {}, "发布测试")
        self.source.attach_post_to_project(project, post)
        self.source.attach_author_to_project(project, author, "manual")
        task = self.source.create_task(project, "keyword", "web", {"topic": "发布测试"})
        self.source.update_task(task, status="completed", current_phase="completed")
        self.source.record_task_post(task, post, "keyword", "发布", 1)

        preview = self.release.preview()
        self.assertTrue(preview["can_publish"])
        result = self.release.publish()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.target.scalar("SELECT COUNT(*) FROM authors"), 1)
        self.assertEqual(self.target.scalar("SELECT COUNT(*) FROM posts"), 1)
        self.assertEqual(self.target.scalar("SELECT COUNT(*) FROM projects"), 1)
        self.assertEqual(self.target.scalar("SELECT COUNT(*) FROM tasks WHERE id=?", (task,)), 1)
        target_media = self.target.scalar("SELECT local_path FROM media_assets LIMIT 1")
        self.assertTrue(Path(target_media).is_file())
        self.assertTrue(str(target_media).startswith(str(self.target_dir.resolve())))
        self.assertEqual(len(self.release.list_releases()), 1)

    def test_refuses_when_either_side_has_an_active_task(self):
        task = self.source.create_task(None, "keyword", "web", {"topic": "运行中"})
        preview = self.release.preview()

        self.assertFalse(preview["can_publish"])
        self.assertEqual(preview["source_active_tasks"][0]["id"], task)
        with self.assertRaisesRegex(ValueError, "活跃任务"):
            self.release.publish()
