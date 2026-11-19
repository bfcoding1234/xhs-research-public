from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database, ProjectDeleteConflict
from xhs_research.server import ResearchApplication, create_server


class NoopRunner:
    def run(self, *_args):
        return None

    def cancel(self, _task_id):
        return None


class ProjectDeleteAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _project(self, name):
        return self.db.create_project(name, "keyword", {})

    def test_deleting_project_detaches_completed_task_instead_of_deleting_it(self):
        project_id = self._project("detach-task")
        task_id = self.db.create_task(
            project_id,
            "keyword",
            "test",
            {"mode": "keyword", "project_id": project_id},
        )
        self.db.update_task(
            task_id,
            status="completed",
            current_phase="completed",
        )

        result = self.db.delete_project(project_id)

        self.assertEqual(result["detached_tasks"], 1)
        self.assertEqual(result["deleted_tasks"], 0)
        self.assertIsNone(self.db.get_project(project_id))
        self.assertIsNone(self.db.get_task(task_id)["project_id"])

    def test_task_insert_wins_then_atomic_delete_rejects_active_project(self):
        project_id = self._project("task-wins")
        task_inserted = threading.Event()
        release_task = threading.Event()
        task_ids = []
        delete_errors = []

        def after_insert():
            task_inserted.set()
            self.assertTrue(release_task.wait(2))

        def create():
            task_ids.append(self.db.create_task(
                project_id, "keyword", "test",
                {"mode": "keyword", "project_id": project_id},
                _after_insert=after_insert,
            ))

        def delete():
            try:
                self.db.delete_project(project_id)
            except Exception as exc:
                delete_errors.append(exc)

        creator = threading.Thread(target=create)
        deleter = threading.Thread(target=delete)
        creator.start()
        self.assertTrue(task_inserted.wait(2))
        deleter.start()
        release_task.set()
        creator.join(timeout=3)
        deleter.join(timeout=3)

        self.assertEqual(len(task_ids), 1)
        self.assertEqual(len(delete_errors), 1)
        self.assertIsInstance(delete_errors[0], ProjectDeleteConflict)
        self.assertIsNotNone(self.db.get_project(project_id))
        self.assertIsNotNone(self.db.get_task(task_ids[0]))

    def test_delete_wins_then_task_insert_fails_without_orphan_submission(self):
        project_id = self._project("delete-wins")
        delete_guarded = threading.Event()
        release_delete = threading.Event()
        task_errors = []

        def after_guard():
            delete_guarded.set()
            self.assertTrue(release_delete.wait(2))

        def delete():
            self.db.delete_project(project_id, _after_guard=after_guard)

        def create():
            try:
                self.db.create_task(
                    project_id, "keyword", "test",
                    {"mode": "keyword", "project_id": project_id},
                )
            except Exception as exc:
                task_errors.append(exc)

        deleter = threading.Thread(target=delete)
        creator = threading.Thread(target=create)
        deleter.start()
        self.assertTrue(delete_guarded.wait(2))
        creator.start()
        release_delete.set()
        deleter.join(timeout=3)
        creator.join(timeout=3)

        self.assertEqual(len(task_errors), 1)
        self.assertIsInstance(task_errors[0], KeyError)
        self.assertIsNone(self.db.get_project(project_id))
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id=?", (project_id,)), 0)

    def test_application_does_not_submit_when_project_disappears_after_precheck(self):
        project_id = self._project("no-submit")
        settings = SimpleNamespace(
            data_dir=Path(self.temp_dir.name), max_workers=1,
            host="127.0.0.1", port=0, max_author_notes=300,
        )
        app = ResearchApplication(settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
        original_get = self.db.get_project
        deleted = False

        def get_then_delete(value):
            nonlocal deleted
            project = original_get(value)
            if project and not deleted:
                deleted = True
                self.db.delete_project(value)
            return project

        try:
            with patch.object(self.db, "get_project", side_effect=get_then_delete), \
                    patch.object(app, "_submit") as submit:
                with self.assertRaises(KeyError):
                    app.create_task({
                        "mode": "keyword", "project_id": project_id,
                        "created_from": "web", "source": {"keywords": ["race"]},
                    })
                submit.assert_not_called()
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

    def test_concurrent_http_post_wins_and_delete_returns_409(self):
        project_id = self._project("http-task-wins")
        settings = SimpleNamespace(
            data_dir=Path(self.temp_dir.name), max_workers=1,
            host="127.0.0.1", port=0, max_author_notes=300,
        )
        app = ResearchApplication(settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
        original_create = self.db.create_task
        task_inserted = threading.Event()
        release_task = threading.Event()

        def delayed_create(project_id_value, mode, created_from, payload, **kwargs):
            def after_insert():
                task_inserted.set()
                self.assertTrue(release_task.wait(2))

            return original_create(
                project_id_value, mode, created_from, payload,
                _after_insert=after_insert, **kwargs,
            )

        self.db.create_task = delayed_create
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        post_results = []
        delete_results = []

        def post_task():
            request = Request(
                base + "/api/tasks",
                data=json.dumps({
                    "mode": "keyword", "project_id": project_id,
                    "created_from": "web", "source": {"keywords": ["race"]},
                }).encode(),
                method="POST", headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                post_results.append((response.status, json.load(response)))

        def delete_project():
            request = Request(base + f"/api/projects/{project_id}", method="DELETE")
            try:
                urlopen(request)
            except HTTPError as exc:
                delete_results.append((exc.code, json.loads(exc.read())))

        poster = threading.Thread(target=post_task)
        deleter = threading.Thread(target=delete_project)
        try:
            poster.start()
            self.assertTrue(task_inserted.wait(2))
            deleter.start()
            release_task.set()
            poster.join(timeout=3)
            deleter.join(timeout=3)
        finally:
            release_task.set()
            self.db.create_task = original_create
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(post_results[0][0], 202)
        self.assertEqual(delete_results[0][0], 409)
        self.assertIsNotNone(self.db.get_project(project_id))
        self.assertIsNotNone(self.db.get_task(post_results[0][1]["id"]))


if __name__ == "__main__":
    unittest.main()
