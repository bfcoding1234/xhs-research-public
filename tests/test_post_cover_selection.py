from pathlib import Path
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from urllib.request import urlopen


import sys

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.server import ResearchApplication, create_server


class NoopRunner:
    def cancel(self, _task_id):
        return None


class PostCoverSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.author_id = self.db.upsert_author({
            "author_id": "author-cover-selection",
            "display_name": "封面测试作者",
        })
        self.cover_path = Path(self.temp_dir.name) / "cover.webp"
        self.cover_path.write_bytes(b"cover")
        self.detail_path = Path(self.temp_dir.name) / "detail.webp"
        self.detail_path.write_bytes(b"detail")

    def _create_post(self, note_id: str) -> int:
        return self.db.upsert_post({
            "note_id": note_id,
            "title": note_id,
            "author_id": "author-cover-selection",
            "cover_url": f"https://example.com/{note_id}-cover.webp",
            "cover_local_path": str(self.cover_path),
        })

    def test_lists_fall_back_to_cover_when_detail_image_is_missing(self):
        post_id = self._create_post("cover-only")

        global_post = self.db.list_posts_page(page=1, page_size=20)["items"][0]
        author_post = self.db.get_author(self.author_id)["posts"][0]

        self.assertEqual(global_post["id"], post_id)
        self.assertEqual(global_post["media_local_path"], str(self.cover_path))
        self.assertEqual(global_post["media_original_url"], "https://example.com/cover-only-cover.webp")
        self.assertEqual(author_post["media_local_path"], str(self.cover_path))

    def test_lists_prefer_local_detail_first_image_over_cover(self):
        post_id = self._create_post("local-detail")
        project_id = self.db.create_project("封面规则项目", "keyword", {})
        self.db.attach_post_to_project(project_id, post_id)
        self.db.upsert_media(post_id, {
            "url": "https://example.com/local-detail-first.webp",
            "local_path": str(self.detail_path),
        }, 0, "image")

        global_post = self.db.list_posts_page(page=1, page_size=20)["items"][0]
        project_post = self.db.list_project_posts_page(project_id, page=1, page_size=20)["items"][0]
        author_post = self.db.get_author(self.author_id)["posts"][0]

        for post in (global_post, project_post, author_post):
            self.assertEqual(post["media_local_path"], str(self.detail_path))
            self.assertEqual(post["media_original_url"], "https://example.com/local-detail-first.webp")

    def test_remote_detail_first_image_does_not_fall_back_to_local_cover(self):
        post_id = self._create_post("remote-detail")
        self.db.upsert_media(post_id, {
            "url": "https://example.com/remote-detail-first.webp",
        }, 0, "image")

        post = self.db.list_posts_page(page=1, page_size=20)["items"][0]

        self.assertEqual(post["media_local_path"], "")
        self.assertEqual(post["media_original_url"], "https://example.com/remote-detail-first.webp")


class PostCoverSelectionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.db = Database(root / "research.sqlite3")
        self.db.initialize()
        self.cover_path = root / "cover.webp"
        self.cover_path.write_bytes(b"cover")
        self.detail_path = root / "detail.webp"
        self.detail_path.write_bytes(b"detail")
        self.post_id = self.db.upsert_post({
            "note_id": "api-detail-first",
            "title": "接口详情首图",
            "cover_url": "https://example.com/api-cover.webp",
            "cover_local_path": str(self.cover_path),
        })
        settings = SimpleNamespace(
            data_dir=root,
            max_workers=1,
            host="127.0.0.1",
            port=0,
            max_author_notes=300,
        )
        self.app = ResearchApplication(settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
        self.server = create_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.executor.shutdown(wait=True, cancel_futures=True)

    def _post(self):
        with urlopen(f"{self.base}/api/posts?page=1&page_size=20") as response:
            return json.load(response)["items"][0]

    def test_api_keeps_remote_detail_first_image_ahead_of_local_cover(self):
        detail_url = "https://example.com/api-detail-first.webp"
        self.db.upsert_media(self.post_id, {"url": detail_url}, 0, "image")

        remote_only = self._post()

        self.assertEqual(remote_only["media_url"], "")
        self.assertEqual(remote_only["media_remote_url"], detail_url)

        self.db.upsert_media(self.post_id, {
            "url": detail_url,
            "local_path": str(self.detail_path),
        }, 0, "image")

        local_detail = self._post()

        self.assertEqual(local_detail["media_url"], "/media/detail.webp")
        self.assertEqual(local_detail["media_remote_url"], detail_url)


if __name__ == "__main__":
    unittest.main()
