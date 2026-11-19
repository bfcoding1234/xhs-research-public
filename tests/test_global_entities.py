from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.server import ResearchApplication, create_server


class NoopRunner:
    def cancel(self, _task_id):
        return None


class GlobalEntityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.root = root
        self.db = Database(root / "research.sqlite3")
        self.db.initialize()
        self.author_id = self.db.upsert_author({
            "author_id": "author-global",
            "display_name": "全局作者",
            "followers_count": 1200,
            "total_post_count": 1000,
        })
        self.post_id = self.db.upsert_post({
            "note_id": "note-global",
            "title": "全局帖子",
            "author_id": "author-global",
            "likes_count": 88,
        })
        self.project_id = self.db.create_project("引用项目", "keyword", {})
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
        self.temp_dir.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return response.status, json.load(response)

    def post(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            return response.status, json.load(response)

    def delete(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            method="DELETE",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_lists_global_posts_and_authors_with_counts(self):
        status, page = self.get("/api/posts?page=1&page_size=20")
        self.assertEqual(status, 200)
        self.assertEqual(page["total"], 1)
        posts = page["items"]
        self.assertEqual(posts[0]["id"], self.post_id)
        self.assertEqual(posts[0]["author_name"], "全局作者")
        self.assertEqual(posts[0]["project_count"], 0)

        status, authors = self.get("/api/authors")
        self.assertEqual(status, 200)
        self.assertEqual(authors[0]["id"], self.author_id)
        self.assertEqual(authors[0]["post_count"], 1)
        self.assertEqual(authors[0]["stored_post_count"], 1)
        self.assertEqual(authors[0]["total_post_count"], 1000)
        self.assertEqual(authors[0]["project_count"], 0)

    def test_global_post_page_filters_out_existing_project_references(self):
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        _, page = self.get(
            f"/api/posts?page=1&page_size=20&exclude_project_id={self.project_id}"
        )

        self.assertEqual(page["total"], 0)
        self.assertEqual(page["items"], [])

    def test_post_pages_report_and_filter_complete_ocr_state(self):
        _, other = self.get("/api/posts?page=1&page_size=20&ocr=other")
        self.assertEqual(other["items"][0]["ocr_status"], "other")

        first_image = self.root / "first.png"
        second_image = self.root / "second.png"
        first_image.write_bytes(b"first")
        second_image.write_bytes(b"second")
        self.db.upsert_media(self.post_id, {"local_path": str(first_image)}, 0)
        self.db.upsert_media(self.post_id, {"local_path": str(second_image)}, 1)
        media = self.db.query(
            "SELECT id FROM media_assets WHERE post_id=? ORDER BY media_index",
            (self.post_id,),
        )
        self.db.save_media_ocr(media[0]["id"], "", "test-ocr")
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        _, unfinished = self.get("/api/posts?page=1&page_size=20&ocr=pending")
        _, finished = self.get("/api/posts?page=1&page_size=20&ocr=completed")
        _, project_unfinished = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&ocr=pending"
        )
        _, author = self.get(f"/api/authors/{self.author_id}")

        self.assertEqual(unfinished["items"][0]["has_ocr_result"], 0)
        self.assertEqual(unfinished["items"][0]["ocr_status"], "pending")
        self.assertEqual(finished["items"], [])
        self.assertEqual(project_unfinished["items"][0]["has_ocr_result"], 0)
        self.assertEqual(author["posts"][0]["has_ocr_result"], 0)

        self.db.save_media_ocr(media[1]["id"], "识别结果", "test-ocr")
        _, finished = self.get("/api/posts?page=1&page_size=20&ocr=completed")
        _, project_finished = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&ocr=completed"
        )
        _, author = self.get(f"/api/authors/{self.author_id}")

        self.assertEqual(finished["items"][0]["has_ocr_result"], 1)
        self.assertEqual(finished["items"][0]["ocr_status"], "completed")
        self.assertEqual(project_finished["items"][0]["has_ocr_result"], 1)
        self.assertEqual(author["posts"][0]["has_ocr_result"], 1)

    def test_project_post_coverage_reports_detail_and_ocr_gaps(self):
        first_image = self.root / "first.png"
        second_image = self.root / "second.png"
        first_image.write_bytes(b"first")
        second_image.write_bytes(b"second")
        self.db.upsert_media(self.post_id, {"local_path": str(first_image)}, 0)
        self.db.upsert_media(self.post_id, {"local_path": str(second_image)}, 1)
        media = self.db.query(
            "SELECT id FROM media_assets WHERE post_id=? ORDER BY media_index",
            (self.post_id,),
        )
        self.db.save_media_ocr(media[0]["id"], "", "test-ocr")
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        status, coverage = self.get(f"/api/projects/{self.project_id}/post-coverage")

        self.assertEqual(status, 200)
        self.assertEqual(coverage, {
            "total": 1,
            "detailed": 0,
            "preview": 1,
            "ocr_available": 1,
            "ocr_completed": 0,
            "ocr_pending": 1,
            "ocr_other": 0,
        })

        self.db.save_media_ocr(media[1]["id"], "识别结果", "test-ocr")
        _, coverage = self.get(f"/api/projects/{self.project_id}/post-coverage")
        self.assertEqual(coverage["ocr_completed"], 1)
        self.assertEqual(coverage["ocr_pending"], 0)

    def test_project_and_author_posts_report_and_filter_media_storage_status(self):
        self.db.upsert_media(
            self.post_id,
            {"url": "https://example.com/remote.webp"},
            0,
            "image",
        )
        local_post_id = self.db.upsert_post({
            "note_id": "note-local-media",
            "title": "本地正文图片",
            "author_id": "author-global",
        })
        local_image = self.root / "local-body.webp"
        local_image.write_bytes(b"local-image")
        self.db.upsert_media(
            local_post_id,
            {
                "url": "https://example.com/local.webp",
                "local_path": str(local_image),
            },
            0,
            "image",
        )
        no_media_post_id = self.db.upsert_post({
            "note_id": "note-no-body-media",
            "title": "无正文图片",
            "author_id": "author-global",
        })
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id, local_post_id, no_media_post_id]},
        )

        _, remote = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&media_storage=remote"
        )
        _, local = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&media_storage=local"
        )
        _, none = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&media_storage=none"
        )
        _, author = self.get(f"/api/authors/{self.author_id}")

        self.assertEqual([post["id"] for post in remote["items"]], [self.post_id])
        self.assertEqual([post["id"] for post in local["items"]], [local_post_id])
        self.assertEqual([post["id"] for post in none["items"]], [no_media_post_id])
        self.assertEqual(
            {post["id"]: post["media_storage_status"] for post in author["posts"]},
            {
                self.post_id: "remote",
                local_post_id: "local",
                no_media_post_id: "none",
            },
        )

    def test_attaches_existing_post_and_its_author_to_project_idempotently(self):
        status, result = self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["added_post_count"], 1)
        self.assertEqual(result["added_author_count"], 1)

        _, post = self.get(f"/api/posts/{self.post_id}")
        self.assertEqual([project["id"] for project in post["projects"]], [self.project_id])
        _, author = self.get(f"/api/authors/{self.author_id}")
        self.assertEqual(author["post_count"], 1)
        self.assertEqual(author["stored_post_count"], 1)
        self.assertEqual(author["total_post_count"], 1000)
        self.assertEqual(author["projects"][0]["relation_type"], "post_author")

        _, repeated = self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )
        self.assertEqual(repeated["added_post_count"], 0)
        self.assertEqual(repeated["added_author_count"], 0)

        _, project = self.get(f"/api/projects/{self.project_id}")
        self.assertEqual(project["post_count"], 1)
        self.assertEqual(project["author_count"], 1)
        self.assertEqual(project["report_count"], 0)

        _, page = self.get(
            f"/api/projects/{self.project_id}/posts?page=1&page_size=20&query=%E5%85%A8%E5%B1%80"
        )
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], self.post_id)
        self.assertEqual(page["items"][0]["content"], "")
        _, clamped = self.get(
            f"/api/projects/{self.project_id}/posts?page=99&page_size=20"
        )
        self.assertEqual(clamped["page"], 1)

        _, reference_ids = self.get(f"/api/projects/{self.project_id}/reference-ids")
        self.assertEqual(reference_ids["post_ids"], [self.post_id])
        self.assertEqual(reference_ids["author_ids"], [self.author_id])

    def test_project_post_api_returns_author_followers_and_sortable_attention_score(self):
        self.db.upsert_post({
            "note_id": "note-global",
            "title": "全局帖子",
            "author_id": "author-global",
            "likes_count": 88,
            "favorites_count": 12,
            "comments_count": 5,
        })
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        status, page = self.get(
            f"/api/projects/{self.project_id}/posts"
            "?page=1&page_size=20&sort=attention_desc"
        )

        self.assertEqual(status, 200)
        self.assertEqual(page["items"][0]["author_followers_count"], 1200)
        self.assertEqual(page["items"][0]["attention_score"], 100)

    def test_attaches_existing_author_without_copying_all_posts(self):
        second_project = self.db.create_project("作者引用项目", "author", {})

        _, result = self.post(
            f"/api/projects/{second_project}/references",
            {"author_ids": [self.author_id]},
        )

        self.assertEqual(result["added_author_count"], 1)
        self.assertEqual(self.db.list_project_posts(second_project), [])
        authors = self.db.list_project_authors(second_project)
        self.assertEqual(authors[0]["relation_type"], "manual")

    def test_maintains_project_keywords_without_creating_global_entities(self):
        status, keywords = self.post(
            f"/api/projects/{self.project_id}/keywords",
            {"keywords": ["AI 产品经理", "AI 产品经理", "职业发展"]},
        )

        self.assertEqual(status, 200)
        self.assertEqual([value["keyword"] for value in keywords], ["职业发展", "AI 产品经理"])
        _, project = self.get(f"/api/projects/{self.project_id}")
        self.assertEqual(project["keyword_count"], 2)

        status, keywords = self.delete(
            f"/api/projects/{self.project_id}/keywords",
            {"keyword_ids": [keywords[0]["id"]]},
        )
        self.assertEqual(status, 200)
        self.assertEqual([value["keyword"] for value in keywords], ["AI 产品经理"])

    def test_detaches_project_post_and_cleans_automatic_author_relation(self):
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        status, result = self.delete(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["removed_post_count"], 1)
        self.assertEqual(result["removed_author_count"], 1)
        self.assertEqual(self.db.list_project_posts(self.project_id), [])
        self.assertEqual(self.db.list_project_authors(self.project_id), [])
        _, post = self.get(f"/api/posts/{self.post_id}")
        self.assertEqual(post["project_count"], 0)

    def test_detaching_author_with_project_posts_requires_confirmation(self):
        self.post(
            f"/api/projects/{self.project_id}/references",
            {"post_ids": [self.post_id]},
        )

        status, conflict = self.delete(
            f"/api/projects/{self.project_id}/references",
            {"author_ids": [self.author_id]},
        )

        self.assertEqual(status, 409)
        self.assertEqual(conflict["code"], "author_has_project_posts")
        self.assertEqual(conflict["total_post_count"], 1)
        self.assertEqual(conflict["authors"][0]["project_post_count"], 1)

        status, result = self.delete(
            f"/api/projects/{self.project_id}/references",
            {"author_ids": [self.author_id], "confirm_remove_author_posts": True},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["removed_post_count"], 1)
        self.assertEqual(result["removed_author_count"], 1)
        self.assertEqual(self.db.list_project_posts(self.project_id), [])
        self.assertEqual(self.db.list_project_authors(self.project_id), [])

        _, post = self.get(f"/api/posts/{self.post_id}")
        self.assertEqual(post["id"], self.post_id)
        _, author = self.get(f"/api/authors/{self.author_id}")
        self.assertEqual(author["id"], self.author_id)


if __name__ == "__main__":
    unittest.main()
