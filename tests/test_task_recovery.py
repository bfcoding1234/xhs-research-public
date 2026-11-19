from pathlib import Path
import json
import os
import socket
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database, utcnow
from xhs_research.cli import build_application
from xhs_research.config import Settings
from xhs_research.lifecycle_lock import acquire_file_lock, release_file_lock
from xhs_research.server import ResearchApplication, create_server


class RecoveryRunner:
    report_provider = object()

    def __init__(self, db):
        self.db = db
        self.condition = threading.Condition()
        self.calls = []
        self.author_vision_calls = []
        self.blocked_task_id = None
        self.release_blocked = threading.Event()

    def _record(self, task_type, task_id, project_id, configuration):
        self.db.update_task(task_id, status="running", current_phase=task_type, started_at=utcnow())
        with self.condition:
            self.calls.append((task_type, task_id, project_id, configuration))
            self.condition.notify_all()
        if task_id == self.blocked_task_id:
            self.release_blocked.wait(timeout=3)
        self.db.update_task(task_id, status="completed", current_phase="completed", finished_at=utcnow())

    def run(self, task_id, request):
        self._record("research", task_id, request.project_id, request.to_dict())

    def run_vision(self, task_id, project_id, configuration, author_id=None):
        if author_id is not None:
            self.author_vision_calls.append((task_id, author_id))
        self._record("vision", task_id, project_id, configuration)

    def run_ai_report(self, task_id, project_id, configuration):
        self._record("ai_report", task_id, project_id, configuration)

    def run_project_author_update(self, task_id, project_id, configuration):
        self._record("project_author_update", task_id, project_id, configuration)

    def cancel(self, task_id):
        return None

    def wait_for_calls(self, count, timeout=2):
        with self.condition:
            return self.condition.wait_for(lambda: len(self.calls) >= count, timeout=timeout)


class WaitingRunner:
    report_provider = object()

    def __init__(self, db):
        self.db = db
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(self, task_id, request):
        self.db.update_task(task_id, status="waiting_login", current_phase="waiting_login")
        self.started.set()
        self.stopped.wait(timeout=3)

    def cancel(self, task_id):
        self.stopped.set()


class TaskRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.runner = RecoveryRunner(self.db)
        self.settings = SimpleNamespace(
            research_workers=1,
            vision_workers=1,
            report_workers=1,
            host="127.0.0.1",
            port=4320,
            max_author_notes=300,
            data_dir=Path(self.temp_dir.name),
        )
        self.app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")

    def tearDown(self):
        self.runner.release_blocked.set()
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def _project(self, name):
        return self.db.create_project(name, "keyword", {})

    def _research_task(self, project_id, keyword, status="queued"):
        payload = {
            "mode": "keyword",
            "project_id": project_id,
            "created_from": "test",
            "source": {"keywords": [keyword]},
        }
        task_id = self.db.create_task(project_id, "keyword", "test", payload, task_type="research")
        self.db.update_task(task_id, status=status, current_phase=status)
        return task_id

    def _set_created_at(self, task_id, created_at):
        with self.db.connect() as conn:
            conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (created_at, task_id))

    def test_running_predecessor_is_failed_before_queued_task_is_resubmitted(self):
        project_id = self._project("服务中断项目")
        interrupted_id = self._research_task(project_id, "旧任务", status="running")
        queued_id = self._research_task(project_id, "待恢复任务")
        self._set_created_at(interrupted_id, "2026-07-11T01:00:00+00:00")
        self._set_created_at(queued_id, "2026-07-11T02:00:00+00:00")

        summary = self.app.recover_interrupted_tasks()

        self.assertTrue(self.runner.wait_for_calls(1))
        interrupted = self.db.get_task(interrupted_id)
        self.assertEqual(interrupted["status"], "failed")
        self.assertIn("服务中断", interrupted["error_message"])
        events = self.db.list_task_events(interrupted_id)
        self.assertEqual(events[-1]["phase"], "service_interrupted")
        self.assertEqual(events[-1]["event_type"], "interrupted")
        self.assertEqual(self.runner.calls[0][1], queued_id)
        self.assertEqual(summary["interrupted"], [interrupted_id])
        self.assertEqual(summary["resubmitted"], [queued_id])

    def test_waiting_login_tasks_resume_through_their_original_task_type(self):
        research_project = self._project("调研恢复")
        vision_project = self._project("读图恢复")
        report_project = self._project("报告恢复")
        research_id = self._research_task(research_project, "登录后恢复", status="waiting_login")
        vision_payload = {
            "operation": "vision",
            "mode": "keyword",
            "project_id": vision_project,
            "created_from": "test",
            "image_analysis": {"mode": "vision-all", "vision_batch_size": 3},
        }
        vision_id = self.db.create_task(
            vision_project, "keyword", "test", vision_payload, task_type="vision"
        )
        self.db.update_task(vision_id, status="waiting_login", current_phase="waiting_login")
        author_id = self.db.upsert_author({"author_id": "vision-recovery-author"})
        author_vision_payload = {
            "operation": "vision",
            "mode": "author",
            "author_id": author_id,
            "vision_scope": "author",
            "created_from": "test",
            "image_analysis": {"mode": "vision-all", "vision_batch_size": 4},
        }
        author_vision_id = self.db.create_task(
            None,
            "author",
            "test",
            author_vision_payload,
            task_type="vision",
            author_id=author_id,
        )
        self.db.update_task(
            author_vision_id, status="waiting_login", current_phase="waiting_login",
        )
        report_payload = {
            "operation": "ai_report",
            "mode": "keyword",
            "project_id": report_project,
            "created_from": "test",
            "report_generation": {"title": "恢复报告", "instructions": "保持原配置"},
        }
        report_id = self.db.create_task(
            report_project, "keyword", "test", report_payload, task_type="ai_report"
        )
        self.db.update_task(report_id, status="waiting_login", current_phase="waiting_login")
        bulk_project = self._project("批量作者恢复")
        bulk_payload = {
            "operation": "project_author_update",
            "mode": "author",
            "project_id": bulk_project,
            "created_from": "test",
            "source": {"author_ids": ["author-a"]},
            "author_update_bulk": {
                "target": "all",
                "scopes": ["basic_info"],
                "author_ids": ["author-a"],
                "batch_size": 10,
            },
        }
        bulk_id = self.db.create_task(
            bulk_project, "author", "test", bulk_payload, task_type="research"
        )
        self.db.update_task(bulk_id, status="waiting_login", current_phase="waiting_login")

        summary = self.app.recover_interrupted_tasks()

        self.assertTrue(self.runner.wait_for_calls(5))
        calls = {task_id: (task_type, project_id, configuration)
                 for task_type, task_id, project_id, configuration in self.runner.calls}
        self.assertEqual(calls[research_id][0], "research")
        self.assertEqual(calls[research_id][1], research_project)
        self.assertEqual(calls[research_id][2]["source"]["keywords"], ["登录后恢复"])
        self.assertEqual(calls[vision_id], (
            "vision", vision_project, {"mode": "vision-all", "vision_batch_size": 3}
        ))
        self.assertEqual(calls[author_vision_id], (
            "vision", None, {"mode": "vision-all", "vision_batch_size": 4}
        ))
        self.assertEqual(self.runner.author_vision_calls, [(author_vision_id, author_id)])
        self.assertEqual(calls[report_id], (
            "ai_report", report_project, {"title": "恢复报告", "instructions": "保持原配置"}
        ))
        self.assertEqual(calls[bulk_id], (
            "project_author_update", bulk_project, bulk_payload["author_update_bulk"]
        ))
        self.assertCountEqual(
            summary["resubmitted"],
            [research_id, vision_id, author_vision_id, report_id, bulk_id],
        )
        for task_id in (research_id, vision_id, author_vision_id, report_id, bulk_id):
            recovered = [event for event in self.db.list_task_events(task_id)
                         if event["phase"] == "service_recovered"]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["payload_json"]["previous_status"], "waiting_login")

    def test_queued_tasks_are_submitted_oldest_first_for_project_ordering(self):
        project_id = self._project("顺序恢复")
        oldest_id = self._research_task(project_id, "第一项")
        newest_id = self._research_task(project_id, "第二项")
        self._set_created_at(oldest_id, "2026-07-11T01:00:00+00:00")
        self._set_created_at(newest_id, "2026-07-11T02:00:00+00:00")
        self.runner.blocked_task_id = oldest_id

        self.app.recover_interrupted_tasks()

        self.assertTrue(self.runner.wait_for_calls(1))
        self.assertEqual([call[1] for call in self.runner.calls], [oldest_id])
        self.runner.release_blocked.set()
        self.assertTrue(self.runner.wait_for_calls(2))
        self.assertEqual([call[1] for call in self.runner.calls], [oldest_id, newest_id])

    def test_invalid_recovery_payload_fails_only_that_task(self):
        project_id = self._project("损坏任务")
        task_id = self.db.create_task(
            project_id,
            "keyword",
            "test",
            {"mode": "keyword", "project_id": project_id, "source": {"keywords": []}},
            task_type="research",
        )

        summary = self.app.recover_interrupted_tasks()

        task = self.db.get_task(task_id)
        self.assertEqual(task["status"], "failed")
        self.assertIn("恢复失败", task["error_message"])
        self.assertEqual(summary["recovery_failed"], [task_id])
        self.assertEqual(self.runner.calls, [])

    def test_recovery_submission_is_ordered_before_concurrent_new_task(self):
        project_id = self._project("恢复与新建排序")
        recovered_id = self._research_task(project_id, "恢复任务")
        original_submit = self.app._submit
        recovery_at_submit = threading.Event()
        release_recovery = threading.Event()

        def delayed_submit(executor, task_id, project_id_value, method, *args):
            if task_id == recovered_id:
                recovery_at_submit.set()
                self.assertTrue(release_recovery.wait(2))
            return original_submit(executor, task_id, project_id_value, method, *args)

        self.app._submit = delayed_submit
        receipts = []
        errors = []

        def recover():
            try:
                self.app.recover_interrupted_tasks()
            except Exception as exc:
                errors.append(exc)

        def create_new():
            try:
                receipts.append(self.app.create_task({
                    "mode": "keyword", "project_id": project_id,
                    "created_from": "web", "source": {"keywords": ["新任务"]},
                }))
            except Exception as exc:
                errors.append(exc)

        recovery_thread = threading.Thread(target=recover)
        create_thread = threading.Thread(target=create_new)
        try:
            recovery_thread.start()
            self.assertTrue(recovery_at_submit.wait(2))
            create_thread.start()
            self.assertEqual(
                self.db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id=?", (project_id,)),
                1,
            )
            release_recovery.set()
            recovery_thread.join(timeout=3)
            create_thread.join(timeout=3)
            self.assertTrue(self.runner.wait_for_calls(2))
        finally:
            release_recovery.set()
            self.app._submit = original_submit

        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 1)
        self.assertEqual([call[1] for call in self.runner.calls], [recovered_id, receipts[0]["id"]])


class BuildApplicationRecoveryTests(unittest.TestCase):
    def test_recovery_runs_only_after_server_bind_and_runtime_claim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "web" / "dist").mkdir(parents=True)
            (root / "web" / "dist" / "index.html").write_text("ok", encoding="utf-8")
            settings = Settings(
                data_dir=root / "data",
                socai_bin="definitely-missing-socai",
                codex_bin="definitely-missing-codex",
            )
            with patch("xhs_research.cli.APP_ROOT", root), patch.object(
                ResearchApplication,
                "recover_interrupted_tasks",
                return_value={"interrupted": [], "resubmitted": [], "recovery_failed": []},
            ) as recover, patch.object(Database, "initialize", autospec=True) as initialize:
                with patch.object(
                    Database,
                    "rebase_local_media_paths",
                    autospec=True,
                    return_value=0,
                ) as rebase:
                    app = build_application(settings, enable_vision=False)
                    initialize.assert_not_called()
                    rebase.assert_not_called()
                    recover.assert_not_called()
                    server = create_server("127.0.0.1", 0, app, claim_runtime=True)
                    rebase.assert_called_once_with(app.db, app.settings.data_dir)
            try:
                initialize.assert_called_once_with(app.db)
                recover.assert_called_once_with()
            finally:
                server.server_close()
                app.shutdown()


class RuntimeLifecycleTests(unittest.TestCase):
    def _settings(self, root):
        return SimpleNamespace(
            research_workers=1,
            vision_workers=1,
            report_workers=1,
            host="127.0.0.1",
            port=0,
            max_author_notes=300,
            data_dir=root,
        )

    def test_second_service_cannot_claim_the_same_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = Database(root / "research.sqlite3")
            db.initialize()
            first = ResearchApplication(
                self._settings(root), db, RecoveryRunner(db), WORKBENCH_ROOT / "web"
            )
            second = ResearchApplication(
                self._settings(root), db, RecoveryRunner(db), WORKBENCH_ROOT / "web"
            )
            first_server = create_server("127.0.0.1", 0, first, claim_runtime=True)
            try:
                probe = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import sys; "
                            "sys.path.insert(0,sys.argv[2]); "
                            "from xhs_research.lifecycle_lock import "
                            "FileLockUnavailable,acquire_file_lock; "
                            "handle=open(sys.argv[1],'a+'); "
                            "\ntry: acquire_file_lock(handle)"
                            "\nexcept FileLockUnavailable: raise SystemExit(0)"
                            "\nraise SystemExit(2)"
                        ),
                        str(root / ".workbench.lock"),
                        str(WORKBENCH_ROOT),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(probe.returncode, 0, probe.stderr)
                with patch.object(second.db, "initialize", wraps=second.db.initialize) as initialize:
                    with self.assertRaisesRegex(RuntimeError, "数据目录"):
                        create_server("127.0.0.1", 0, second, claim_runtime=True)
                    initialize.assert_not_called()
            finally:
                first_server.server_close()
                first.shutdown()

            third = ResearchApplication(
                self._settings(root), db, RecoveryRunner(db), WORKBENCH_ROOT / "web"
            )
            third_server = create_server("127.0.0.1", 0, third, claim_runtime=True)
            third_server.server_close()
            third.shutdown()

    def test_shutdown_signals_a_running_waiting_task_and_joins_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = Database(root / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("关闭测试", "keyword", {})
            runner = WaitingRunner(db)
            app = ResearchApplication(
                self._settings(root), db, runner, WORKBENCH_ROOT / "web"
            )
            app.create_task({
                "mode": "keyword",
                "project_id": project_id,
                "created_from": "test",
                "source": {"keywords": ["等待登录"]},
            })
            self.assertTrue(runner.started.wait(1))

            app.shutdown()

            self.assertTrue(runner.stopped.is_set())

    def test_sigterm_exits_cleanly_and_releases_the_runtime_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(WORKBENCH_ROOT),
                "XHS_RESEARCH_DATA_DIR": str(root),
                "XHS_RESEARCH_HOST": "127.0.0.1",
                "XHS_RESEARCH_PORT": str(port),
                "SOCAI_BIN": "definitely-missing-socai",
                "CODEX_BIN": "definitely-missing-codex",
            })
            process = subprocess.Popen(
                [sys.executable, "-m", "xhs_research", "serve", "--no-open", "--ocr-only"],
                cwd=WORKBENCH_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                health = None
                while time.monotonic() < deadline:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.2) as response:
                            health = json.load(response)
                            break
                    except OSError:
                        time.sleep(0.05)
                self.assertIsNotNone(health, process.stderr.read() if process.poll() is not None else "")
                process.terminate()
                returncode = process.wait(timeout=5)
                self.assertEqual(returncode, 0, process.stderr.read())

                with (root / ".workbench.lock").open("a+") as handle:
                    acquire_file_lock(handle)
                    release_file_lock(handle)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
