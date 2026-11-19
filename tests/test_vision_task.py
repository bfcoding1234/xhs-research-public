from pathlib import Path
import hashlib
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
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication, create_server


class CapturingRunner:
    def __init__(self):
        self.requests = []
        self.vision_requests = []

    def run(self, task_id, request):
        self.requests.append(request)

    def run_vision(self, task_id, project_id, configuration):
        self.vision_requests.append((task_id, project_id, configuration))

    def cancel(self, task_id):
        return None


class FakeVisionProvider:
    model = "fake-model"
    prompt_version = "test-v1"

    def __init__(self):
        self.batch_calls = []

    def cache_key(self, image_paths):
        digest = hashlib.sha256()
        for image_path in image_paths:
            digest.update(Path(image_path).read_bytes())
        return "cache:" + digest.hexdigest()

    def analyze(self, title, image_paths, schema_path):
        return {"cover_hook": title, "image_count": len(image_paths)}

    def analyze_batch(self, posts, schema_path):
        self.batch_calls.append([post["post_id"] for post in posts])
        return {
            post["post_id"]: {"cover_hook": post["title"], "image_count": len(post["image_paths"])}
            for post in posts
        }


class FakeOCRProvider:
    engine_name = "rapidocr"
    version = "test-v1"
    available = True

    def analyze(self, image_path):
        return f"文字：{Path(image_path).stem}"


class IndependentVisionTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("示例项目", "keyword", {})
        self.settings = SimpleNamespace(
            max_workers=1,
            host="127.0.0.1",
            port=4318,
            max_author_notes=300,
            data_dir=Path(self.temp_dir.name),
        )

    def _image(self, name, content=b"image"):
        path = Path(self.temp_dir.name) / "media" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        return path

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normal_research_task_is_forced_to_ocr_only(self):
        runner = CapturingRunner()
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            result = app.create_task({
                "mode": "keyword",
                "project_id": self.project_id,
                "created_from": "web",
                "source": {"keywords": ["AI"]},
                "image_analysis": {"mode": "vision-all", "vision_ratio": 1, "vision_count": 300},
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(len(runner.requests), 1)
        self.assertEqual(runner.requests[0].image_analysis, "ocr-only")
        self.assertEqual(runner.requests[0].vision_count, 0)

    def test_vision_task_only_analyzes_existing_unanalyzed_media(self):
        post_id = self.db.upsert_post({
            "note_id": "note-1",
            "author_id": "vision-author",
            "title": "封面标题",
            "note_type": "image",
        })
        self.db.attach_post_to_project(self.project_id, post_id)
        image = self._image("example-cover.jpg", b"example")
        self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"}, 0, "cover")
        self.db.set_app_settings({
            "vision_analysis_mode": "vision-all",
            "vision_analysis_ratio": 1,
            "vision_analysis_count": 10,
            "vision_analysis_max_count": 30,
        })
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, socai=None, vision_provider=provider)
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            before = runner.vision_status(self.project_id)
            result = app.create_vision_task(self.project_id)
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)
        after = runner.vision_status(self.project_id)

        task = self.db.get_task(result["id"])
        self.assertTrue(before["provider_available"])
        self.assertEqual(before["pending_posts"], 1)
        self.assertEqual(after["pending_posts"], 0)
        self.assertEqual(task["input_json"]["operation"], "vision")
        self.assertEqual(task["task_type"], "vision")
        self.assertEqual(task["input_json"]["image_analysis"]["image_scopes"], ["cover"])
        self.assertEqual(task["input_json"]["image_analysis"]["vision_max_count"], 30)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM vision_analyses"), 1)
        self.assertEqual(provider.batch_calls, [[post_id]])
        project_post = runner.project_posts(self.project_id)[0]
        self.assertEqual(project_post["has_vision_result"], 1)
        global_post = next(post for post in runner.posts() if post["id"] == post_id)
        self.assertEqual(global_post["has_vision_result"], 1)
        author_id = int(self.db.scalar("SELECT id FROM authors WHERE author_id=?", ("vision-author",)))
        self.assertEqual(runner.author(author_id)["posts"][0]["has_vision_result"], 1)

    def test_historical_vision_configuration_without_scope_uses_all_images(self):
        post_id = self.db.upsert_post({"note_id": "legacy-scope", "title": "历史任务"})
        self.db.attach_post_to_project(self.project_id, post_id)
        self.db.upsert_media(
            post_id,
            {"local_path": str(self._image("legacy-cover.jpg", b"legacy-cover"))},
            0,
            "cover",
        )
        self.db.upsert_media(
            post_id,
            {"local_path": str(self._image("legacy-detail.jpg", b"legacy-detail"))},
            0,
            "image",
        )
        task_id = self.db.create_task(
            self.project_id,
            "keyword",
            "test",
            {"operation": "vision", "image_analysis": {"mode": "vision-all"}},
            task_type="vision",
        )
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, vision_provider=provider)

        runner.run_vision(task_id, self.project_id, {"mode": "vision-all"})

        row = self.db.query("SELECT image_scope FROM vision_analyses WHERE post_id=?", (post_id,))[0]
        status = runner.vision_status(self.project_id)
        self.assertEqual(row["image_scope"], "all")
        self.assertEqual(provider.batch_calls, [[post_id]])
        self.assertEqual(status["vision_scopes"]["cover"]["pending_posts"], 0)
        self.assertEqual(status["vision_scopes"]["detail"]["pending_posts"], 0)

    def test_ocr_task_can_process_cover_and_detail_together(self):
        post_id = self.db.upsert_post({"note_id": "ocr-both", "title": "双范围 OCR"})
        self.db.attach_post_to_project(self.project_id, post_id)
        self.db.upsert_media(
            post_id,
            {"local_path": str(self._image("ocr-cover.jpg", b"cover"))},
            0,
            "cover",
        )
        self.db.upsert_media(
            post_id,
            {"local_path": str(self._image("ocr-poster.jpg", b"poster"))},
            0,
            "video_poster",
        )
        runner = TaskRunner(self.db, ocr_provider=FakeOCRProvider())
        app = ResearchApplication(self.settings, self.db, runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_vision_task(self.project_id, overrides={
                "processing_method": "ocr",
                "image_scopes": ["cover", "detail"],
                "mode": "vision-all",
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        media = self.db.query(
            "SELECT media_type,ocr_text FROM media_assets WHERE post_id=? ORDER BY media_type",
            (post_id,),
        )
        self.assertEqual({row["media_type"]: row["ocr_text"] for row in media}, {
            "cover": "文字：ocr-cover",
            "video_poster": "文字：ocr-poster",
        })
        task = self.db.get_task(result["id"])
        self.assertEqual(
            task["input_json"]["image_analysis"]["image_scopes"], ["cover", "detail"],
        )

    def test_http_creation_checks_the_selected_image_scope(self):
        post_id = self.db.upsert_post({"note_id": "scope-check", "title": "仅详情图"})
        self.db.attach_post_to_project(self.project_id, post_id)
        self.db.upsert_media(
            post_id,
            {"local_path": str(self._image("scope-detail.jpg", b"detail"))},
            0,
            "image",
        )
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, vision_provider=provider)
        app = ResearchApplication(self.settings, self.db, runner, WORKBENCH_ROOT / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_address[1]}/api/projects/{self.project_id}/vision"
        cover_request = Request(
            endpoint,
            data=json.dumps({"configuration": {"mode": "vision-all"}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        detail_request = Request(
            endpoint,
            data=json.dumps({
                "configuration": {"mode": "vision-all", "image_scopes": ["detail"]},
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.assertRaises(HTTPError) as rejected:
                urlopen(cover_request)
            with urlopen(detail_request) as response:
                accepted = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(rejected.exception.code, 400)
        self.assertEqual(self.db.get_task(accepted["id"])["status"], "completed")
        self.assertEqual(provider.batch_calls, [[post_id]])

    def test_ocr_task_writes_text_for_only_local_project_media(self):
        post_id = self.db.upsert_post({"note_id": "ocr-note", "title": "OCR 帖子"})
        self.db.attach_post_to_project(self.project_id, post_id)
        other_post_id = self.db.upsert_post({"note_id": "no-media-note", "title": "没有本地图片"})
        self.db.attach_post_to_project(self.project_id, other_post_id)
        image = self._image("ocr-media.jpg", b"ocr")
        self.db.upsert_media(post_id, {"local_path": str(image)}, 0, "image")
        runner = TaskRunner(self.db, ocr_provider=FakeOCRProvider())
        before = runner.vision_status(self.project_id)
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            result = app.create_vision_task(self.project_id, overrides={
                "processing_method": "ocr", "image_scopes": ["detail"], "mode": "vision-all",
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)
        media = self.db.query("SELECT ocr_text,ocr_engine,ocr_completed_at FROM media_assets WHERE post_id=?", (post_id,))[0]
        task = self.db.get_task(result["id"])
        self.assertEqual(media["ocr_text"], "文字：ocr-media")
        self.assertEqual(media["ocr_engine"], "rapidocr")
        self.assertTrue(media["ocr_completed_at"])
        self.assertEqual(task["input_json"]["image_analysis"]["processing_method"], "ocr")
        self.assertNotIn("vision_model", task["input_json"]["image_analysis"])
        self.assertNotIn("vision_reasoning_effort", task["input_json"]["image_analysis"])
        self.assertNotIn("vision_timeout_seconds", task["input_json"]["image_analysis"])
        self.assertEqual(runner.vision_status(self.project_id)["ocr_pending_posts"], 0)
        self.assertEqual(before["ocr_pending_posts"], 1)
        self.assertEqual(before["ocr_other_posts"], 1)

    def test_author_vision_task_only_processes_that_authors_posts(self):
        author_post_id = self.db.upsert_post({
            "note_id": "author-vision-note",
            "author_id": "author-vision",
            "title": "作者范围帖子",
            "note_type": "image",
        })
        other_post_id = self.db.upsert_post({
            "note_id": "other-author-note",
            "author_id": "other-author",
            "title": "其他作者帖子",
            "note_type": "image",
        })
        self.db.upsert_media(
            author_post_id,
            {"local_path": str(self._image("author-vision.jpg", b"author")), "ocr_text": "作者"},
            0,
            "cover",
        )
        self.db.upsert_media(
            other_post_id,
            {"local_path": str(self._image("other-author.jpg", b"other")), "ocr_text": "其他"},
            0,
            "cover",
        )
        author_id = int(self.db.scalar(
            "SELECT id FROM authors WHERE author_id=?", ("author-vision",),
        ))
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, socai=None, vision_provider=provider)
        app = ResearchApplication(
            self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web",
        )
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base}/api/authors/{author_id}/vision-status") as response:
                before = json.load(response)
            request = Request(
                f"{base}/api/authors/{author_id}/vision",
                data=json.dumps({
                    "created_from": "web",
                    "configuration": {"mode": "vision-all"},
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                result = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        self.assertEqual(before["pending_posts"], 1)
        self.assertEqual(runner.author_vision_status(author_id)["pending_posts"], 0)
        self.assertIsNone(task["project_id"])
        self.assertEqual(task["author_id"], author_id)
        self.assertEqual(task["input_json"]["vision_scope"], "author")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(provider.batch_calls, [[author_post_id]])
        self.assertEqual(
            self.db.scalar("SELECT COUNT(*) FROM vision_analyses WHERE post_id=?", (other_post_id,)),
            0,
        )

    def test_project_cannot_start_duplicate_active_vision_tasks(self):
        payload = {"operation": "vision", "mode": "keyword", "project_id": self.project_id}
        task_id = self.db.create_task(self.project_id, "keyword", "web", payload)
        self.assertEqual(self.db.get_task(task_id)["task_type"], "vision")
        self.db.update_task(task_id, status="running", current_phase="vision")
        runner = TaskRunner(self.db, socai=None, vision_provider=FakeVisionProvider())
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            with self.assertRaisesRegex(ValueError, "已有运行中的图片理解任务"):
                app.create_vision_task(self.project_id)
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

    def test_full_range_task_ignores_a_smaller_maximum_count(self):
        runner = TaskRunner(self.db, socai=None, vision_provider=FakeVisionProvider())
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            result = app.create_vision_task(self.project_id, overrides={
                "mode": "vision-all", "vision_ratio": 1, "vision_count": 10, "vision_max_count": 1,
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        self.assertEqual(task["input_json"]["image_analysis"]["mode"], "vision-all")

    def test_new_vision_task_freezes_backend_model_settings(self):
        self.db.set_app_settings({
            "vision_model": "vision-model",
            "vision_reasoning_effort": "high",
            "vision_timeout_seconds": 900,
        })
        runner = CapturingRunner()
        app = ResearchApplication(
            self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web",
        )
        try:
            result = app.create_vision_task(self.project_id, overrides={"mode": "vision-all"})
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        configuration = self.db.get_task(result["id"])["input_json"]["image_analysis"]
        self.assertEqual(configuration["vision_model"], "vision-model")
        self.assertEqual(configuration["vision_reasoning_effort"], "high")
        self.assertEqual(configuration["vision_timeout_seconds"], 900)
        self.assertEqual(runner.vision_requests[0][2], configuration)

    def test_http_retry_reuses_original_vision_configuration(self):
        original_configuration = {
            "mode": "vision-selective",
            "vision_ratio": 0.65,
            "vision_count": 17,
            "vision_max_count": 41,
            "vision_batch_size": 9,
            "only_unanalyzed": True,
        }
        original_id = self.db.create_task(
            self.project_id,
            "keyword",
            "web",
            {
                "operation": "vision",
                "mode": "keyword",
                "project_id": self.project_id,
                "created_from": "web",
                "image_analysis": original_configuration,
            },
            task_type="vision",
        )
        self.db.update_task(original_id, status="failed", current_phase="failed")
        self.db.set_app_settings({
            "vision_analysis_mode": "vision-all",
            "vision_analysis_ratio": 1,
            "vision_analysis_count": 300,
            "vision_analysis_max_count": 300,
            "vision_analysis_batch_size": 1,
        })
        runner = CapturingRunner()
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/tasks/{original_id}/retry",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request) as response:
                retried = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        retried_task = self.db.get_task(retried["id"])
        expected_configuration = {
            **original_configuration,
            "image_scopes": ["all"],
            "vision_model": "",
            "vision_reasoning_effort": "default",
            "vision_timeout_seconds": 600,
        }
        self.assertEqual(retried_task["input_json"]["image_analysis"], expected_configuration)
        self.assertEqual(runner.vision_requests[0][2], expected_configuration)

    def test_vision_task_groups_posts_by_configured_batch_size(self):
        for index in range(3):
            post_id = self.db.upsert_post({"note_id": f"batch-{index}", "title": f"封面 {index}", "note_type": "image"})
            self.db.attach_post_to_project(self.project_id, post_id)
            image = self._image(f"batch-{index}.jpg", f"image-{index}".encode())
            self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"}, 0, "cover")
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, socai=None, vision_provider=provider)
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        original_query = self.db.query
        vision_queries = []

        def track_vision_queries(sql, params=()):
            if "vision_analyses" in sql:
                vision_queries.append(sql)
            return original_query(sql, params)

        self.db.query = track_vision_queries
        try:
            app.create_vision_task(self.project_id, overrides={
                "mode": "vision-all", "vision_batch_size": 2,
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)
            self.db.query = original_query

        self.assertEqual([len(batch) for batch in provider.batch_calls], [2, 1])
        # Current per-project keys and reusable global analyses are each loaded
        # once; the count does not grow with candidate posts.
        self.assertEqual(len(vision_queries), 2)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM vision_analyses"), 3)

    def test_duplicate_image_cache_is_attached_to_every_post(self):
        post_ids = []
        shared = self._image("shared-cover.jpg", b"shared-image")
        for index in range(2):
            post_id = self.db.upsert_post({
                "note_id": f"duplicate-{index}",
                "title": f"重复封面 {index}",
                "note_type": "image",
            })
            post_ids.append(post_id)
            self.db.attach_post_to_project(self.project_id, post_id)
            self.db.upsert_media(
                post_id,
                {"local_path": str(shared), "ocr_text": "相同图片"},
                0,
                "cover",
            )
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, socai=None, vision_provider=provider)
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            app.create_vision_task(self.project_id, overrides={
                "mode": "vision-all", "image_scopes": ["cover", "detail"],
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(len(provider.batch_calls), 1)
        self.assertEqual(len(provider.batch_calls[0]), 1)
        self.assertIn(provider.batch_calls[0][0], post_ids)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM vision_analyses"), 2)
        self.assertEqual(runner.vision_status(self.project_id)["pending_posts"], 0)

    def test_changed_image_content_becomes_pending_for_the_current_cache_key(self):
        post_id = self.db.upsert_post({"note_id": "changed-image", "title": "变化封面"})
        self.db.attach_post_to_project(self.project_id, post_id)
        image = self._image("changed.jpg", b"first-version")
        self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"}, 0, "image")
        # Cover and image assets can legitimately share media_index=0. Current
        # cache identity must use the same id tie-breaker in project, report and
        # post-detail paths; ordering only by media_index lets SQLite reorder by
        # media_type through the UNIQUE index and falsely marks detail as stale.
        cover = self._image("changed-cover.jpg", b"second-media")
        self.db.upsert_media(
            post_id,
            {"local_path": str(cover), "ocr_text": "封面 OCR"},
            0,
            "cover",
        )
        provider = FakeVisionProvider()
        runner = TaskRunner(self.db, socai=None, vision_provider=provider)
        app = ResearchApplication(self.settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            app.create_vision_task(self.project_id, overrides={
                "mode": "vision-all", "image_scopes": ["cover", "detail"],
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(runner.vision_status(self.project_id)["pending_posts"], 0)
        self.assertEqual(runner.project_posts(self.project_id)[0]["has_vision_result"], 1)
        self.assertEqual(len(runner.get_post(post_id)["vision"]), 2)
        self.assertEqual(runner.ai_report_status(self.project_id)["vision_post_count"], 1)
        self.assertEqual(
            len(runner._capture_report_evidence(self.project_id)["posts"][0]["vision_results"]),
            2,
        )

        image.write_bytes(b"second-version")
        changed_status = runner.vision_status(self.project_id)
        self.assertEqual(changed_status["pending_posts"], 1)
        self.assertEqual(changed_status["vision_scopes"]["cover"]["pending_posts"], 0)
        self.assertEqual(changed_status["vision_scopes"]["detail"]["pending_posts"], 1)
        self.assertEqual(runner.project_posts(self.project_id)[0]["has_vision_result"], 1)
        self.assertEqual(len(runner.get_post(post_id)["vision"]), 1)
        self.assertEqual(runner.ai_report_status(self.project_id)["vision_post_count"], 1)
        self.assertEqual(
            len(runner._capture_report_evidence(self.project_id)["posts"][0]["vision_results"]),
            1,
        )

        providerless = TaskRunner(self.db, socai=None, vision_provider=None)
        self.assertEqual(providerless.vision_status(self.project_id)["analyzed_posts"], 0)
        self.assertEqual(providerless.project_posts(self.project_id)[0]["has_vision_result"], 0)
        self.assertEqual(providerless.get_post(post_id)["vision"], [])
        self.assertEqual(providerless.ai_report_status(self.project_id)["vision_post_count"], 0)

    def test_missing_or_outside_media_is_not_reported_as_available(self):
        post_id = self.db.upsert_post({"note_id": "missing-image", "title": "缺失封面"})
        self.db.attach_post_to_project(self.project_id, post_id)
        image = self._image("missing.jpg", b"gone")
        self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"}, 0, "cover")
        image.unlink()
        outside = Path(self.temp_dir.name).parent / "outside-vision.jpg"
        outside.write_bytes(b"outside")
        second = self.db.upsert_post({"note_id": "outside-image", "title": "越界封面"})
        self.db.attach_post_to_project(self.project_id, second)
        self.db.upsert_media(second, {"local_path": str(outside), "ocr_text": "OCR"})
        self.addCleanup(outside.unlink, missing_ok=True)

        runner = TaskRunner(self.db, socai=None, vision_provider=FakeVisionProvider())
        self.assertEqual(runner.vision_status(self.project_id)["available_posts"], 0)

    def test_http_post_detail_and_project_list_hide_stale_vision(self):
        post_id = self.db.upsert_post({"note_id": "http-stale", "title": "HTTP 过期结果"})
        self.db.attach_post_to_project(self.project_id, post_id)
        image = self._image("http-stale.jpg", b"first")
        self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"}, 0, "cover")
        runner = TaskRunner(self.db, socai=None, vision_provider=FakeVisionProvider())
        app = ResearchApplication(self.settings, self.db, runner, WORKBENCH_ROOT / "web")
        try:
            app.create_vision_task(self.project_id, overrides={"mode": "vision-all"})
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        image.write_bytes(b"second")
        self.db.upsert_media(post_id, {"local_path": str(image), "ocr_text": "OCR"})
        app = ResearchApplication(self.settings, self.db, runner, WORKBENCH_ROOT / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(
                f"{base}/api/projects/{self.project_id}/posts?page=1&page_size=20"
            ) as response:
                posts = json.load(response)["items"]
            with urlopen(f"{base}/api/posts/{post_id}") as response:
                detail = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(posts[0]["has_vision_result"], 0)
        self.assertEqual(detail["vision"], [])

    def test_initialize_migrates_global_cache_key_to_per_post_unique(self):
        first = self.db.upsert_post({"note_id": "migration-1", "title": "迁移一"})
        second = self.db.upsert_post({"note_id": "migration-2", "title": "迁移二"})
        with self.db.connect() as conn:
            conn.execute("DROP TABLE vision_analyses")
            conn.execute("""CREATE TABLE vision_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                cache_key TEXT NOT NULL UNIQUE,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                analyzed_at TEXT NOT NULL
            )""")
            conn.execute(
                """INSERT INTO vision_analyses(
                       post_id,cache_key,model,prompt_version,analysis_json,analyzed_at
                   ) VALUES(?,?,?,?,?,?)""",
                (first, "shared-cache", "model", "v1", "{}", "2026-01-01T00:00:00+00:00"),
            )

        self.db.initialize()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO vision_analyses(
                       post_id,cache_key,model,prompt_version,analysis_json,analyzed_at
                   ) VALUES(?,?,?,?,?,?)""",
                (second, "shared-cache", "model", "v1", "{}", "2026-01-01T00:00:01+00:00"),
            )

        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM vision_analyses"), 2)


if __name__ == "__main__":
    unittest.main()
