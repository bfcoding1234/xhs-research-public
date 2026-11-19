from pathlib import Path
from http.client import HTTPConnection
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.server import ResearchApplication, _handler_factory, create_server


class FakeRunner:
    def cancel(self, task_id):
        return None


class DisconnectingWriter:
    def write(self, _body):
        raise BrokenPipeError("client disconnected")


class StaticFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.web = root / "dist"
        self.web.mkdir()
        (self.web / "index.html").write_text(
            '<!doctype html><div id="root"></div>', encoding="utf-8"
        )
        (self.web / "umi.12345678.js").write_text("console.log('ok')", encoding="utf-8")
        self.db = Database(root / "research.sqlite3")
        self.db.initialize()
        (root / "media").mkdir()
        settings = SimpleNamespace(
            max_workers=1,
            host="127.0.0.1",
            port=0,
            max_author_notes=300,
            socai_bin="socai",
            codex_bin="codex",
            detail_ttl_days=30,
            author_ttl_days=7,
            data_dir=root,
        )
        self.app = ResearchApplication(settings, self.db, FakeRunner(), self.web)
        self.server = create_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def test_index_is_never_cached(self):
        with urlopen(self.base_url + "/") as response:
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertIn('id="root"', response.read().decode())

    def test_hashed_bundles_are_cached_immutably(self):
        with urlopen(self.base_url + "/umi.12345678.js") as response:
            self.assertIn("immutable", response.headers["Cache-Control"])
            self.assertEqual(response.read().decode(), "console.log('ok')")

    def test_missing_asset_is_a_real_404_instead_of_index_html(self):
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base_url + "/missing.js")
        self.assertEqual(raised.exception.code, 404)

    def test_extensionless_route_falls_back_to_the_app_shell(self):
        with urlopen(self.base_url + "/projects/7") as response:
            self.assertIn('id="root"', response.read().decode())

    def test_unknown_api_route_is_json_404_instead_of_app_shell(self):
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base_url + "/api/does-not-exist")
        self.assertEqual(raised.exception.code, 404)
        self.assertIn("application/json", raised.exception.headers["Content-Type"])

    def test_client_disconnect_during_response_does_not_escape_handler(self):
        handler_class = _handler_factory(self.app)
        handler = handler_class.__new__(handler_class)
        handler.wfile = DisconnectingWriter()
        handler.close_connection = False
        handler.send_response = lambda _status: None
        handler.send_header = lambda _key, _value: None
        handler.end_headers = lambda: None

        handler._json(200, {"status": "ok"})

        self.assertTrue(handler.close_connection)

    def test_registered_media_file_can_be_served(self):
        media = Path(self.temp_dir.name) / "media" / "registered.png"
        body = b"\x89PNG\r\n\x1a\nregistered evidence"
        media.write_bytes(body)
        post_id = self.db.upsert_post({"note_id": "registered-note", "title": "测试帖子"})
        self.db.upsert_media(post_id, {"local_path": str(media)}, 0, "cover")

        with urlopen(self.base_url + "/media/media/registered.png") as response:
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertEqual(response.read(), body)

    def test_rebases_stale_media_path_when_the_file_exists_in_current_data_root(self):
        legacy_dir = tempfile.TemporaryDirectory()
        self.addCleanup(legacy_dir.cleanup)
        legacy_cover = Path(legacy_dir.name) / "media" / "covers" / "recovered.png"
        legacy_cover.parent.mkdir(parents=True)
        legacy_cover.write_bytes(b"old snapshot copy")
        current_cover = Path(self.temp_dir.name) / "media" / "covers" / "recovered.png"
        current_cover.parent.mkdir(parents=True)
        body = b"\x89PNG\r\n\x1a\nrecovered cover"
        current_cover.write_bytes(body)
        post_id = self.db.upsert_post({
            "note_id": "rebased-cover-note",
            "title": "恢复封面",
            "cover_local_path": str(legacy_cover),
        })

        repaired = self.db.rebase_local_media_paths(Path(self.temp_dir.name))

        self.assertEqual(repaired, 1)
        self.assertEqual(
            self.db.get_post(post_id)["cover_local_path"],
            str(current_cover.resolve()),
        )
        with urlopen(self.base_url + "/media/media/covers/recovered.png") as response:
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertEqual(response.read(), body)

    def test_media_route_never_exposes_database_or_unregistered_files(self):
        secret = Path(self.temp_dir.name) / "service.log"
        secret.write_text("private runtime log", encoding="utf-8")
        unregistered = Path(self.temp_dir.name) / "media" / "unregistered.txt"
        unregistered.write_text("private media scratch", encoding="utf-8")

        for path in ("/media/research.sqlite3", "/media/service.log", "/media/media/unregistered.txt"):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(self.base_url + path)
                self.assertIn(raised.exception.code, (403, 404))

    def test_sensitive_or_non_media_file_is_rejected_even_when_registered(self):
        post_id = self.db.upsert_post({"note_id": "sensitive-note", "title": "敏感路径"})
        secret = Path(self.temp_dir.name) / "service.log"
        secret.write_bytes(b"\x89PNG\r\n\x1a\nlooks-like-image")
        scratch = Path(self.temp_dir.name) / "media" / "scratch.txt"
        scratch.write_text("plain text", encoding="utf-8")
        self.db.upsert_media(post_id, {"local_path": str(self.db.path)}, 0, "image")
        self.db.upsert_media(post_id, {"local_path": str(secret)}, 1, "image")
        self.db.upsert_media(post_id, {"local_path": str(scratch)}, 2, "image")

        for path in ("/media/research.sqlite3", "/media/service.log", "/media/media/scratch.txt"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as raised:
                urlopen(self.base_url + path)
            self.assertEqual(raised.exception.code, 404)

    def test_security_headers_are_present_on_static_and_api_responses(self):
        for path in ("/", "/api/health"):
            with self.subTest(path=path), urlopen(self.base_url + path) as response:
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_cross_origin_untrusted_host_and_non_json_posts_are_rejected(self):
        payload = b'{"name":"blocked","research_type":"keyword"}'
        cases = [
            ({"Content-Type": "application/json", "Origin": "https://attacker.example"}, 403),
            ({"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403),
            ({"Content-Type": "text/plain"}, 415),
            ({"Content-Type": "application/json", "Host": "attacker.example"}, 403),
        ]
        for headers, expected in cases:
            request = Request(self.base_url + "/api/projects", data=payload, method="POST", headers=headers)
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as raised:
                urlopen(request)
            self.assertEqual(raised.exception.code, expected)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM projects"), 0)

    def test_loopback_origin_and_cli_without_origin_remain_supported(self):
        for index, origin in enumerate((None, "http://localhost:8000")):
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            request = Request(
                self.base_url + "/api/projects",
                data=(f'{{"name":"allowed-{index}","research_type":"keyword"}}').encode(),
                method="POST",
                headers=headers,
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 201)

    def test_project_name_and_description_can_be_updated_without_changing_identity(self):
        project_id = self.db.create_project(
            "原项目名称",
            "keyword",
            {"scope": "kept"},
            "原项目说明",
        )
        before = self.db.get_project(project_id)
        request = Request(
            self.base_url + f"/api/projects/{project_id}",
            data=json.dumps({
                "name": "  新项目名称  ",
                "description": "  新项目说明  ",
            }).encode(),
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request) as response:
            updated = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(updated["name"], "新项目名称")
        self.assertEqual(updated["description"], "新项目说明")
        self.assertEqual(updated["slug"], before["slug"])
        self.assertEqual(updated["research_type"], "keyword")
        self.assertEqual(updated["config_json"], {"scope": "kept"})
        self.assertNotEqual(updated["updated_at"], before["updated_at"])

    def test_project_update_validates_fields_and_missing_project(self):
        project_id = self.db.create_project("保留名称", "keyword", {}, "保留说明")
        cases = [
            (project_id, {"name": " ", "description": ""}, 400),
            (project_id, {"name": "x" * 81, "description": ""}, 400),
            (project_id, {"name": "有效名称", "description": "x" * 2001}, 400),
            (999999, {"name": "有效名称", "description": ""}, 404),
        ]

        for target_id, payload, expected in cases:
            request = Request(
                self.base_url + f"/api/projects/{target_id}",
                data=json.dumps(payload).encode(),
                method="PATCH",
                headers={"Content-Type": "application/json"},
            )
            with self.subTest(target_id=target_id, payload=payload), self.assertRaises(HTTPError) as raised:
                urlopen(request)
            self.assertEqual(raised.exception.code, expected)

        current = self.db.get_project(project_id)
        self.assertEqual(current["name"], "保留名称")
        self.assertEqual(current["description"], "保留说明")

    def test_json_array_is_a_400_and_internal_errors_do_not_leak(self):
        request = Request(
            self.base_url + "/api/projects", data=b"[]", method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)

        original = self.db.create_project
        self.db.create_project = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("secret /private/database/path")
        )
        self.addCleanup(setattr, self.db, "create_project", original)
        request = Request(
            self.base_url + "/api/projects",
            data=b'{"name":"internal","research_type":"keyword"}', method="POST",
            headers={"Content-Type": "application/json"},
        )
        with patch("xhs_research.server.traceback.print_exc"), self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 500)
        self.assertNotIn("secret", raised.exception.read().decode())

    def test_nested_overflowing_json_number_is_rejected_before_storage(self):
        request = Request(
            self.base_url + "/api/projects",
            data=b'{"name":"overflow","research_type":"keyword","config":{"nested":[1e400]}}',
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM projects"), 0)

    def test_json_body_over_two_million_bytes_is_rejected_before_reading(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=2)
        try:
            connection.putrequest("POST", "/api/projects")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "2000001")
            connection.endheaders()
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()

        self.assertEqual(response.status, 413)

    def test_invalid_author_and_nullable_numeric_parameters_are_400(self):
        project_id = self.db.create_project("输入契约", "author", {})
        requests = [
            Request(
                self.base_url + "/api/tasks",
                data=json.dumps({
                    "mode": "author", "project_id": project_id, "created_from": "web",
                    "source": {"profile_urls": ["https://example.com/user/profile/author-a"]},
                }).encode(),
                method="POST", headers={"Content-Type": "application/json"},
            ),
            Request(
                self.base_url + "/api/settings",
                data=b'{"vision_analysis_ratio":null}', method="POST",
                headers={"Content-Type": "application/json"},
            ),
        ]
        for request in requests:
            with self.subTest(url=request.full_url), self.assertRaises(HTTPError) as raised:
                urlopen(request)
            self.assertEqual(raised.exception.code, 400)

    def test_non_loopback_listener_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_server("0.0.0.0", 0, self.app)


if __name__ == "__main__":
    unittest.main()
