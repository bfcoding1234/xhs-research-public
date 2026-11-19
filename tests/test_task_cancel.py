from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.codex_process import CodexProcessCancelled
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication, create_server


class FakeRunner:
    def __init__(self):
        self.cancelled = []
        self.resumed = []

    def run(self, task_id, request):
        return None

    def cancel(self, task_id):
        self.cancelled.append(task_id)

    def resume(self, task_id):
        self.resumed.append(task_id)


class FakeFuture:
    def __init__(self, cancel_result=True):
        self.cancel_calls = 0
        self.cancel_result = cancel_result

    def cancel(self):
        self.cancel_calls += 1
        return self.cancel_result


class BlockingReportProvider:
    model = "fake"
    prompt_version = "v1"

    def __init__(self):
        self.started = threading.Event()

    def generate(self, _project, _evidence, _instructions="", should_cancel=None):
        self.started.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if should_cancel and should_cancel():
                raise CodexProcessCancelled("cancelled")
            time.sleep(0.01)
        return "# too late"


class TaskCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("哈杜 AI", "author", {})
        payload = {
            "mode": "author",
            "project_id": self.project_id,
            "created_from": "test",
            "source": {"author_id": "author-a"},
        }
        self.completed_id = self.db.create_task(self.project_id, "author", "test", payload)
        self.db.update_task(self.completed_id, status="completed", current_phase="completed")
        time.sleep(0.002)
        self.stuck_id = self.db.create_task(self.project_id, "author", "test", payload)
        self.db.update_task(self.stuck_id, status="waiting_login", current_phase="waiting_login")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cancelled_task_is_persisted_but_hidden_from_reads_and_project_status(self):
        self.assertTrue(self.db.cancel_task(self.stuck_id))

        self.assertIsNone(self.db.get_task(self.stuck_id))
        hidden = self.db.get_task(self.stuck_id, include_cancelled=True)
        self.assertEqual(hidden["status"], "cancelled")
        self.assertEqual(hidden["current_phase"], "cancelled")
        self.assertEqual([task["id"] for task in self.db.list_tasks(self.project_id)], [self.completed_id])
        self.assertEqual(self.db.list_projects()[0]["latest_task_status"], "completed")
        self.assertEqual(self.db.get_stats()["tasks"], 1)

    def test_application_cancel_signals_runner_and_queued_future(self):
        self.db.update_task(self.stuck_id, status="running", current_phase="discovery")
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        future = FakeFuture(cancel_result=False)
        app.futures[self.stuck_id] = future
        try:
            result = app.cancel_task(self.stuck_id)
        finally:
            app.executor.shutdown(wait=False, cancel_futures=True)

        self.assertEqual(result, {"id": self.stuck_id, "status": "cancelled"})
        self.assertEqual(runner.cancelled, [self.stuck_id])
        self.assertEqual(future.cancel_calls, 1)
        self.assertIsNone(self.db.get_task(self.stuck_id))

    def test_waiting_login_cancel_does_not_create_a_stale_runner_signal(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            result = app.cancel_task(self.stuck_id)
        finally:
            app.executor.shutdown(wait=False, cancel_futures=True)

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(runner.cancelled, [])

    def test_waiting_login_task_can_request_same_task_resume(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            result = app.resume_task(self.stuck_id)
        finally:
            app.executor.shutdown(wait=False, cancel_futures=True)

        self.assertEqual(result, {"id": self.stuck_id, "status": "resuming"})
        self.assertEqual(runner.resumed, [self.stuck_id])
        events = self.db.list_task_events(self.stuck_id)
        self.assertEqual(events[-1]["phase"], "manual_resume_requested")

    def test_resume_endpoint_wakes_waiting_login_task(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/tasks/{self.stuck_id}/resume",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request) as response:
                payload = json.loads(response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(payload, {"id": self.stuck_id, "status": "resuming"})
        self.assertEqual(runner.resumed, [self.stuck_id])

    def test_resume_endpoint_rejects_non_waiting_task_as_conflict(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/tasks/{self.completed_id}/resume",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(request)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(raised.exception.code, 409)
        self.assertEqual(runner.resumed, [])

    def test_resume_and_cancel_actions_cannot_interleave_after_status_read(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        resume_read = threading.Event()
        release_resume = threading.Event()
        cancel_finished = threading.Event()
        original_get_task = self.db.get_task
        results = {}

        def blocking_get_task(task_id, include_cancelled=False):
            value = original_get_task(task_id, include_cancelled=include_cancelled)
            if threading.current_thread().name == "resume-action":
                resume_read.set()
                self.assertTrue(release_resume.wait(1))
            return value

        def run_resume():
            results["resume"] = app.resume_task(self.stuck_id)

        def run_cancel():
            results["cancel"] = app.cancel_task(self.stuck_id)
            cancel_finished.set()

        try:
            with patch.object(self.db, "get_task", side_effect=blocking_get_task):
                resume_thread = threading.Thread(target=run_resume, name="resume-action")
                cancel_thread = threading.Thread(target=run_cancel, name="cancel-action")
                resume_thread.start()
                self.assertTrue(resume_read.wait(1))
                cancel_thread.start()
                self.assertFalse(cancel_finished.wait(0.05))
                release_resume.set()
                resume_thread.join(timeout=1)
                cancel_thread.join(timeout=1)
        finally:
            app.executor.shutdown(wait=False, cancel_futures=True)

        self.assertEqual(results["resume"]["status"], "resuming")
        self.assertEqual(results["cancel"]["status"], "cancelled")
        phases = [event["phase"] for event in self.db.list_task_events(self.stuck_id)]
        self.assertEqual(phases[-2:], ["manual_resume_requested", "cancelled"])

    def test_completed_task_cannot_be_cancelled(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        try:
            with self.assertRaisesRegex(ValueError, "cannot be cancelled"):
                app.cancel_task(self.completed_id)
        finally:
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_completed_or_active_task_cannot_be_retried(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for task_id in (self.completed_id, self.stuck_id):
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/tasks/{task_id}/retry",
                    data=b"{}", method="POST", headers={"Content-Type": "application/json"},
                )
                with self.subTest(task_id=task_id), self.assertRaises(HTTPError) as raised:
                    urlopen(request)
                self.assertEqual(raised.exception.code, 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

    def test_project_with_waiting_login_task_cannot_be_deleted(self):
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/projects/{self.project_id}",
            method="DELETE",
        )
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(request)
            payload = json.loads(raised.exception.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(raised.exception.code, 409)
        self.assertIn("active task", payload["error"])
        self.assertIsNotNone(self.db.get_project(self.project_id))

    def test_empty_project_cleanup_refuses_project_with_any_task(self):
        self.assertTrue(self.db.cancel_task(self.stuck_id))
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/projects/{self.project_id}?require_empty=true",
            method="DELETE",
        )
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(request)
            payload = json.loads(raised.exception.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(raised.exception.code, 409)
        self.assertIn("has tasks", payload["error"])
        self.assertIsNotNone(self.db.get_project(self.project_id))

    def test_empty_project_cleanup_returns_deletion_summary(self):
        empty_project_id = self.db.create_project("临时项目", "keyword", {})
        runner = FakeRunner()
        settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/projects/{empty_project_id}?require_empty=true",
            method="DELETE",
        )
        try:
            with urlopen(request) as response:
                payload = json.loads(response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(payload["deleted_project_id"], empty_project_id)
        self.assertEqual(payload["name"], "临时项目")
        self.assertEqual(payload["deleted_tasks"], 0)
        self.assertTrue(payload["global_entities_preserved"])
        self.assertIsNone(self.db.get_project(empty_project_id))

    def test_cancelled_task_cannot_create_a_late_report(self):
        self.assertTrue(self.db.cancel_task(self.stuck_id))

        report_id = self.db.create_report(
            self.project_id,
            self.stuck_id,
            "author",
            "不应生成的报告",
            "内容",
            {},
        )

        self.assertIsNone(report_id)
        self.assertEqual(self.db.list_reports(self.project_id), [])
        self.assertIsNone(self.db.get_project(self.project_id)["latest_report_id"])

    def test_running_codex_report_is_cancelled_and_shutdown_is_bounded(self):
        self.db.cancel_task(self.stuck_id)
        provider = BlockingReportProvider()
        runner = TaskRunner(self.db, socai=None, report_provider=provider)
        settings = SimpleNamespace(
            data_dir=Path(self.temp_dir.name), max_workers=1,
            host="127.0.0.1", port=4318, max_author_notes=300,
        )
        post_id = self.db.upsert_post({"note_id": "report-input", "title": "报告输入"})
        self.db.attach_post_to_project(self.project_id, post_id)
        app = ResearchApplication(settings, self.db, runner, ROOT / "scripts" / "workbench" / "web")
        receipt = app.create_ai_report_task(self.project_id)
        self.assertTrue(provider.started.wait(1))
        pending = self.db.list_reports(self.project_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "generating")

        started = time.monotonic()
        app.cancel_task(receipt["id"])
        app.shutdown()

        self.assertLess(time.monotonic() - started, 1)
        task = self.db.get_task(receipt["id"], include_cancelled=True)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(self.db.list_reports(self.project_id), [])


if __name__ == "__main__":
    unittest.main()
