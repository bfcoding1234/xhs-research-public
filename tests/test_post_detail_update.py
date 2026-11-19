from pathlib import Path
import tempfile
import threading
import unittest


import sys

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.collector import DOWNLOAD_MEDIA, READ_POST_DETAIL
from xhs_research.config import Settings
from xhs_research.db import Database
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication


class PostDetailCollector:
    provider_id = "xiaohongshu-cli"
    display_name = "帖子详情测试采集器"
    capabilities = {READ_POST_DETAIL}

    def __init__(self):
        self.calls = []

    def read_post_detail(self, post):
        self.calls.append(post["note_id"])
        card = {
            "note_id": post["note_id"],
            "title": post["title"],
            "url": post["note_url"],
            "author_id": post.get("external_author_id") or "",
            "author": post.get("author_name") or "",
            "source_type": "post",
            "source_value": post["note_id"],
            "source_rank": 0,
            "detail_level": "card",
            "cover_url": "https://sns-webpic-qc.xhscdn.com/test/cover.webp",
        }
        return {
            "profile": {},
            "cards": [card],
            "notes": [{
                **card,
                "content": f"{post['note_id']} 的完整正文",
                "favorites_count": 12,
                "comments_count": 3,
                "detail_level": "detail",
                "images": [{"index": 0, "url": card["cover_url"]}],
                "_collector_ok": True,
            }],
            "warnings": [],
        }

    @staticmethod
    def normalize_result(raw, _source_type, _source_value):
        return raw


class CoverDownloadingRunner(TaskRunner):
    def __init__(self, *args, cover_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.cover_path = cover_path

    def _download_cover(self, _note_id: str, url: str) -> str:
        return str(self.cover_path) if url else ""

    def _download_post_detail_image(self, _note_id: str, _media_index: int, url: str) -> str:
        return str(self.cover_path) if url else ""


class DownloadFallbackCollector(PostDetailCollector):
    provider_id = "opencli"
    capabilities = {READ_POST_DETAIL, DOWNLOAD_MEDIA}

    def read_post_detail(self, post):
        result = super().read_post_detail(post)
        for item in result["cards"] + result["notes"]:
            item.pop("cover_url", None)
            item.pop("images", None)
        return result

    @staticmethod
    def download_media(_note_url, output_dir):
        target = Path(output_dir) / "post" / "01.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF\x00\x00\x00\x00WEBPtest")
        return [{"status": "success"}]


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.completed = threading.Event()

    def run_post_detail_update(self, task_id, configuration):
        self.calls.append((task_id, configuration))
        self.completed.set()

    def cancel(self, _task_id):
        return None


class PostDetailUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.author_id = self.db.upsert_author({"author_id": "author-1", "display_name": "作者"})
        self.post_ids = [
            self.db.upsert_post({
                "note_id": f"note-{index}",
                "title": f"帖子 {index}",
                "author_id": "author-1",
                "url": f"https://www.xiaohongshu.com/explore/note-{index}?xsec_token=token-{index}",
                "detail_level": "card",
            })
            for index in range(1, 4)
        ]
        self.cover_path = Path(self.temp_dir.name) / "cover.webp"
        self.cover_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBPtest")

    def _runner(self, collector):
        return CoverDownloadingRunner(
            self.db,
            collectors={collector.provider_id: collector},
            cover_path=self.cover_path,
        )

    def test_candidate_selection_respects_scope_and_detail_target(self):
        project_id = self.db.create_project("项目", "keyword", {})
        self.db.attach_post_to_project(project_id, self.post_ids[1])
        self.db.attach_post_to_project(project_id, self.post_ids[2])
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE posts SET detail_level='detail',last_detail_fetched_at=? WHERE id=?",
                ("2099-01-01T00:00:00+00:00", self.post_ids[2]),
            )

        rows = self.db.select_post_detail_update_candidates(
            "project", project_id, "needs_update", 500, detail_ttl_days=30,
        )

        self.assertEqual([row["id"] for row in rows], [self.post_ids[1]])

    def test_selected_posts_are_updated_directly_in_one_task(self):
        posts = self.db.select_post_detail_update_candidates(
            "global", None, "all", 2, self.post_ids[:2], detail_ttl_days=30,
        )
        configuration = {
            "mode": "selected",
            "scope": "global",
            "target": "selected",
            "post_ids": self.post_ids[:2],
            "posts": posts,
            "batch_size": 2,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        }
        payload = {
            "operation": "post_detail_update",
            "mode": "keyword",
            "created_from": "test",
            "post_detail_update": configuration,
        }
        task_id = self.db.create_task(None, "keyword", "test", payload)
        collector = PostDetailCollector()

        self._runner(collector).run_post_detail_update(
            task_id, configuration,
        )

        task = self.db.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_json"]["success_count"], 2)
        self.assertEqual(collector.calls, ["note-1", "note-2"])
        updated = self.db.query(
            "SELECT note_id,content,detail_level,last_detail_fetched_at FROM posts WHERE id IN (?,?) ORDER BY id",
            self.post_ids[:2],
        )
        self.assertEqual([row["detail_level"] for row in updated], ["detail", "detail"])
        self.assertTrue(all(row["last_detail_fetched_at"] for row in updated))
        self.assertEqual(updated[0]["content"], "note-1 的完整正文")
        media = self.db.query(
            "SELECT media_type,local_path,download_status FROM media_assets WHERE post_id=? ORDER BY media_type",
            (self.post_ids[0],),
        )
        self.assertTrue(any(row["media_type"] == "cover" for row in media))
        body_image = next(row for row in media if row["media_type"] == "image")
        self.assertEqual(body_image["local_path"], str(self.cover_path))
        self.assertEqual(body_image["download_status"], "downloaded")

    def test_project_update_preserves_existing_keyword_author_source(self):
        project_id = self.db.create_project("项目", "keyword", {})
        post_id = self.post_ids[0]
        self.db.attach_post_to_project(project_id, post_id)
        self.db.attach_author_to_project(
            project_id,
            self.author_id,
            "keyword_post_author",
        )
        posts = self.db.select_post_detail_update_candidates(
            "project",
            project_id,
            "all",
            1,
            [post_id],
            detail_ttl_days=30,
        )
        configuration = {
            "mode": "selected",
            "scope": "project",
            "scope_id": project_id,
            "project_id": project_id,
            "target": "selected",
            "post_ids": [post_id],
            "posts": posts,
            "batch_size": 1,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        }
        payload = {
            "operation": "post_detail_update",
            "mode": "keyword",
            "project_id": project_id,
            "created_from": "test",
            "post_detail_update": configuration,
        }
        task_id = self.db.create_task(project_id, "keyword", "test", payload)
        collector = PostDetailCollector()

        self._runner(collector).run_post_detail_update(
            task_id,
            configuration,
        )

        relations = self.db.query(
            """SELECT relation_type FROM project_authors
               WHERE project_id=? AND author_id=? ORDER BY relation_type""",
            (project_id, self.author_id),
        )
        self.assertEqual(
            [row["relation_type"] for row in relations],
            ["keyword_post_author"],
        )

    def test_project_update_links_newly_discovered_post_author_once(self):
        project_id = self.db.create_project("项目", "keyword", {})
        post_id = self.post_ids[0]
        self.db.attach_post_to_project(project_id, post_id)
        posts = self.db.select_post_detail_update_candidates(
            "project",
            project_id,
            "all",
            1,
            [post_id],
            detail_ttl_days=30,
        )
        configuration = {
            "mode": "selected",
            "scope": "project",
            "scope_id": project_id,
            "project_id": project_id,
            "target": "selected",
            "post_ids": [post_id],
            "posts": posts,
            "batch_size": 1,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        }
        payload = {
            "operation": "post_detail_update",
            "mode": "keyword",
            "project_id": project_id,
            "created_from": "test",
            "post_detail_update": configuration,
        }
        task_id = self.db.create_task(project_id, "keyword", "test", payload)
        collector = PostDetailCollector()

        self._runner(collector).run_post_detail_update(
            task_id,
            configuration,
        )

        relations = self.db.query(
            """SELECT relation_type,first_task_id FROM project_authors
               WHERE project_id=? AND author_id=?""",
            (project_id, self.author_id),
        )
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["relation_type"], "post_author")
        self.assertEqual(relations[0]["first_task_id"], task_id)

    def test_detail_update_uses_media_download_capability_when_cover_url_is_missing(self):
        post_id = self.post_ids[0]
        posts = self.db.select_post_detail_update_candidates(
            "global", None, "all", 1, [post_id], detail_ttl_days=30,
        )
        configuration = {
            "mode": "selected",
            "scope": "global",
            "target": "selected",
            "post_ids": [post_id],
            "posts": posts,
            "batch_size": 1,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        }
        task_id = self.db.create_task(None, "keyword", "test", {
            "operation": "post_detail_update",
            "mode": "keyword",
            "created_from": "test",
            "post_detail_update": configuration,
        })
        collector = DownloadFallbackCollector()

        TaskRunner(self.db, collectors={collector.provider_id: collector}).run_post_detail_update(
            task_id, configuration,
        )

        task = self.db.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_json"]["success_count"], 1)
        media = self.db.query(
            "SELECT local_path FROM media_assets WHERE post_id=? AND media_type='cover'",
            (post_id,),
        )
        self.assertEqual(len(media), 1)
        self.assertTrue(TaskRunner._is_valid_image(Path(media[0]["local_path"])))

    def test_cleanup_removes_only_redundant_detail_update_provenance(self):
        project_id = self.db.create_project("项目", "keyword", {})
        task_id = self.db.create_task(
            project_id,
            "keyword",
            "test",
            {
                "operation": "post_detail_update",
                "mode": "keyword",
                "project_id": project_id,
                "created_from": "test",
            },
        )
        self.db.attach_author_to_project(
            project_id,
            self.author_id,
            "keyword_post_author",
        )
        self.db.attach_author_to_project(
            project_id,
            self.author_id,
            "post_author",
            task_id,
        )
        second_author_id = self.db.upsert_author({
            "author_id": "author-2",
            "display_name": "详情中新发现的作者",
        })
        self.db.attach_author_to_project(
            project_id,
            second_author_id,
            "post_author",
            task_id,
        )

        removed = self.db.remove_redundant_post_detail_author_relations()

        self.assertEqual(removed, 1)
        relations = self.db.query(
            """SELECT author_id,relation_type FROM project_authors
               WHERE project_id=? ORDER BY author_id,relation_type""",
            (project_id,),
        )
        self.assertEqual(
            [(row["author_id"], row["relation_type"]) for row in relations],
            [
                (self.author_id, "keyword_post_author"),
                (second_author_id, "post_author"),
            ],
        )

    def test_application_freezes_batch_candidates_when_task_is_created(self):
        runner = RecordingRunner()
        settings = Settings(data_dir=Path(self.temp_dir.name), host="127.0.0.1", port=4318)
        app = ResearchApplication(settings, self.db, runner, WORKBENCH_ROOT / "web")
        self.addCleanup(app.shutdown)

        receipt = app.create_post_detail_update_task("test", {
            "mode": "batch",
            "scope": "global",
            "target": "preview",
            "max_posts": 2,
            "batch_size": 2,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        })

        self.assertTrue(runner.completed.wait(1))
        task = self.db.get_task(receipt["id"])
        configuration = task["input_json"]["post_detail_update"]
        self.assertEqual(configuration["post_ids"], self.post_ids[:2])
        self.assertEqual([post["note_id"] for post in configuration["posts"]], ["note-1", "note-2"])
        self.assertEqual(runner.calls[0][1]["post_ids"], self.post_ids[:2])

    def test_application_creates_author_scoped_post_detail_update(self):
        runner = RecordingRunner()
        settings = Settings(data_dir=Path(self.temp_dir.name), host="127.0.0.1", port=4318)
        app = ResearchApplication(settings, self.db, runner, WORKBENCH_ROOT / "web")
        self.addCleanup(app.shutdown)

        receipt = app.create_post_detail_update_task("test", {
            "mode": "batch",
            "scope": "author",
            "scope_id": self.author_id,
            "target": "preview",
            "max_posts": 2,
            "batch_size": 2,
            "post_delay_min_seconds": 0,
            "post_delay_max_seconds": 0,
            "batch_delay_min_seconds": 0,
            "batch_delay_max_seconds": 0,
            "consecutive_failure_limit": 5,
        })

        self.assertTrue(runner.completed.wait(1))
        task = self.db.get_task(receipt["id"])
        self.assertEqual(task["author_id"], self.author_id)
        self.assertIsNone(task["project_id"])
        self.assertEqual(task["mode"], "author")
        self.assertEqual(task["input_json"]["post_detail_update"]["scope"], "author")
        self.assertEqual(task["input_json"]["post_detail_update"]["scope_id"], self.author_id)

    def test_application_uses_configured_post_detail_delay_defaults(self):
        self.db.set_app_settings({
            "post_delay_min_seconds": 3,
            "post_delay_max_seconds": 5,
            "batch_delay_min_seconds": 10,
            "batch_delay_max_seconds": 20,
        })
        runner = RecordingRunner()
        settings = Settings(data_dir=Path(self.temp_dir.name), host="127.0.0.1", port=4318)
        app = ResearchApplication(settings, self.db, runner, WORKBENCH_ROOT / "web")
        self.addCleanup(app.shutdown)

        receipt = app.create_post_detail_update_task("test", {
            "mode": "batch",
            "scope": "global",
            "target": "preview",
            "max_posts": 1,
            "batch_size": 1,
            "consecutive_failure_limit": 5,
        })

        self.assertTrue(runner.completed.wait(1))
        configuration = self.db.get_task(receipt["id"])["input_json"]["post_detail_update"]
        self.assertEqual(configuration["post_delay_min_seconds"], 3)
        self.assertEqual(configuration["post_delay_max_seconds"], 5)
        self.assertEqual(configuration["batch_delay_min_seconds"], 10)
        self.assertEqual(configuration["batch_delay_max_seconds"], 20)


if __name__ == "__main__":
    unittest.main()
