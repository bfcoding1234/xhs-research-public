from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import ActiveTaskConflict, Database
from xhs_research.server import ResearchApplication, create_server


class NoopRunner:
    vision_provider = object()
    report_provider = object()

    def run_vision(self, *_args):
        return None

    def run_ai_report(self, *_args):
        return None

    def cancel(self, _task_id):
        return None

    def vision_status(self, _project_id):
        return {"provider_available": True, "pending_posts": 1}


class CompletingResearchRunner(NoopRunner):
    def __init__(self, db):
        self.db = db
        self.calls = []
        self.lock = threading.Lock()

    def run(self, task_id, request):
        with self.lock:
            self.calls.append(request.keywords[0])
        self.db.update_task(
            task_id, status="completed", current_phase="completed", finished_at="done",
        )


class ActiveEnrichmentAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db = Database(self.root / "research.sqlite3")
        self.db.initialize()
        self.settings = SimpleNamespace(
            data_dir=self.root, host="127.0.0.1", port=0,
            max_workers=1, max_author_notes=300,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _project(self, name):
        project_id = self.db.create_project(name, "keyword", {})
        post_id = self.db.upsert_post({"note_id": f"note-{name}", "title": name})
        self.db.attach_post_to_project(project_id, post_id)
        return project_id

    def test_parallel_requests_create_only_one_active_task_per_enrichment_type(self):
        for task_type in ("vision", "ai_report"):
            with self.subTest(task_type=task_type):
                project_id = self._project(task_type)
                app = ResearchApplication(self.settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
                app._submit = lambda *_args, **_kwargs: None
                original_list = self.db.list_tasks
                barrier = threading.Barrier(2)

                def synchronized_list(*args, **kwargs):
                    result = original_list(*args, **kwargs)
                    barrier.wait(timeout=2)
                    return result

                self.db.list_tasks = synchronized_list
                outcomes = []

                def create():
                    try:
                        if task_type == "vision":
                            outcomes.append(app.create_vision_task(project_id))
                        else:
                            outcomes.append(app.create_ai_report_task(project_id))
                    except Exception as exc:  # captured for cross-thread assertion
                        outcomes.append(exc)

                threads = [threading.Thread(target=create) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
                self.db.list_tasks = original_list
                app.executor.shutdown(wait=True, cancel_futures=True)

                self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
                self.assertEqual(sum(isinstance(value, ActiveTaskConflict) for value in outcomes), 1)
                active = self.db.query(
                    "SELECT * FROM tasks WHERE project_id=? AND task_type=? AND status='queued'",
                    (project_id, task_type),
                )
                self.assertEqual(len(active), 1)

    def test_http_duplicate_conflict_is_409(self):
        project_id = self._project("http-conflict")
        self.db.create_task(
            project_id, "keyword", "web",
            {"operation": "ai_report", "mode": "keyword", "project_id": project_id},
            task_type="ai_report",
        )
        app = ResearchApplication(self.settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/projects/{project_id}/ai-report",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
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
        self.assertIn("已有运行中的", payload["error"])

    def test_parallel_author_vision_requests_create_only_one_active_task(self):
        author_id = self.db.upsert_author({"author_id": "atomic-author"})
        app = ResearchApplication(self.settings, self.db, NoopRunner(), WORKBENCH_ROOT / "web")
        app._submit = lambda *_args, **_kwargs: None
        original_list = self.db.list_tasks
        barrier = threading.Barrier(2)

        def synchronized_list(*args, **kwargs):
            result = original_list(*args, **kwargs)
            barrier.wait(timeout=2)
            return result

        self.db.list_tasks = synchronized_list
        outcomes = []

        def create():
            try:
                outcomes.append(app.create_author_vision_task(author_id))
            except Exception as exc:
                outcomes.append(exc)

        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.db.list_tasks = original_list
        app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, ActiveTaskConflict) for value in outcomes), 1)
        active = self.db.query(
            """SELECT * FROM tasks WHERE project_id IS NULL AND author_id=?
               AND task_type='vision' AND status='queued'""",
            (author_id,),
        )
        self.assertEqual(len(active), 1)

    def test_initialize_resolves_legacy_duplicates_before_creating_unique_index(self):
        project_id = self._project("migration")
        with self.db.connect() as conn:
            conn.execute("DROP INDEX idx_tasks_one_active_enrichment")
        task_ids = [
            self.db.create_task(
                project_id, "keyword", "web",
                {"operation": "vision", "mode": "keyword", "project_id": project_id},
                task_type="vision",
            )
            for _ in range(2)
        ]

        self.db.initialize()

        tasks = [self.db.get_task(task_id, include_cancelled=True) for task_id in task_ids]
        self.assertEqual([task["status"] for task in tasks], ["queued", "failed"])
        indexes = {row["name"] for row in self.db.query("PRAGMA index_list(tasks)")}
        self.assertIn("idx_tasks_one_active_enrichment", indexes)
        events = self.db.list_task_events(task_ids[1])
        self.assertEqual(events[-1]["phase"], "migration_conflict")

    def test_parallel_research_creation_submits_in_database_creation_order(self):
        project_id = self._project("research-order")
        runner = CompletingResearchRunner(self.db)
        app = ResearchApplication(self.settings, self.db, runner, WORKBENCH_ROOT / "web")
        original_create = self.db.create_task
        first_inserted = threading.Event()
        release_first = threading.Event()

        def delayed_create(project_id_value, mode, created_from, payload, **kwargs):
            task_id = original_create(project_id_value, mode, created_from, payload, **kwargs)
            keyword = (payload.get("source") or {}).get("keywords", [""])[0]
            if keyword == "first":
                first_inserted.set()
                self.assertTrue(release_first.wait(2))
            return task_id

        self.db.create_task = delayed_create
        receipts = []
        errors = []
        second_attempted = threading.Event()

        def create(keyword):
            try:
                if keyword == "second":
                    second_attempted.set()
                receipts.append(app.create_task({
                    "mode": "keyword", "project_id": project_id,
                    "created_from": "web", "source": {"keywords": [keyword]},
                }))
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=create, args=("first",))
        second = threading.Thread(target=create, args=("second",))
        try:
            first.start()
            self.assertTrue(first_inserted.wait(2))
            second.start()
            self.assertTrue(second_attempted.wait(2))
            time.sleep(0.05)
            self.assertEqual(
                self.db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id=?", (project_id,)),
                1,
            )
            release_first.set()
            first.join(timeout=3)
            second.join(timeout=3)
            deadline = time.monotonic() + 2
            while len(runner.calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            app.executor.shutdown(wait=True, cancel_futures=True)
        finally:
            release_first.set()
            self.db.create_task = original_create

        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 2)
        self.assertEqual(runner.calls, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
