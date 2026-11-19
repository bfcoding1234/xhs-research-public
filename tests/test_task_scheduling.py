from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database, utcnow
from xhs_research.server import ResearchApplication


class SchedulingRunner:
    report_provider = object()

    def __init__(self, db):
        self.db = db
        self.started = {"research": {}, "vision": {}, "report": {}}
        self.release = {"research": {}, "vision": {}, "report": {}}

    def _execute(self, kind, task_id, project_id):
        self.db.update_task(task_id, status="running", current_phase=kind, started_at=utcnow())
        self.started[kind].setdefault(project_id, threading.Event()).set()
        self.release[kind].setdefault(project_id, threading.Event()).wait(timeout=3)
        self.db.update_task(task_id, status="completed", current_phase="completed", finished_at=utcnow())

    def run(self, task_id, request):
        self._execute("research", task_id, request.project_id)

    def run_vision(self, task_id, project_id, configuration):
        self._execute("vision", task_id, project_id)

    def run_ai_report(self, task_id, project_id, configuration):
        self._execute("report", task_id, project_id)

    def cancel(self, task_id):
        return None


class TaskSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_one = self.db.create_project("项目一", "keyword", {})
        self.project_two = self.db.create_project("项目二", "keyword", {})
        for project_id in (self.project_one, self.project_two):
            post_id = self.db.upsert_post({"note_id": f"note-{project_id}", "title": "测试帖子"})
            self.db.attach_post_to_project(project_id, post_id)
        self.runner = SchedulingRunner(self.db)
        self.settings = SimpleNamespace(
            research_workers=1, vision_workers=1, report_workers=1,
            host="127.0.0.1", port=4318, max_author_notes=300,
        )
        self.app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")

    def tearDown(self):
        for group in self.runner.release.values():
            for event in group.values():
                event.set()
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def _research(self, project_id, keyword):
        return self.app.create_task({
            "mode": "keyword", "project_id": project_id, "created_from": "test",
            "source": {"keywords": [keyword]},
        })

    def test_different_projects_can_run_research_and_vision_in_parallel(self):
        self.app.create_vision_task(self.project_one, "web", {"mode": "vision-all"})
        self.assertTrue(self.runner.started["vision"].setdefault(self.project_one, threading.Event()).wait(1))

        self._research(self.project_two, "并行关键词")
        self.assertTrue(self.runner.started["research"].setdefault(self.project_two, threading.Event()).wait(1))

    def test_same_project_report_and_vision_can_run_in_parallel(self):
        self.app.create_vision_task(self.project_one, "web", {"mode": "vision-all"})
        self.assertTrue(self.runner.started["vision"].setdefault(self.project_one, threading.Event()).wait(1))
        report = self.app.create_ai_report_task(self.project_one)

        report_started = self.runner.started["report"].setdefault(self.project_one, threading.Event())
        self.assertTrue(report_started.wait(1))
        self.assertEqual(self.db.get_task(report["id"])["status"], "running")

    def test_same_project_report_still_waits_for_research(self):
        self._research(self.project_one, "更新项目数据")
        self.assertTrue(self.runner.started["research"].setdefault(self.project_one, threading.Event()).wait(1))
        report = self.app.create_ai_report_task(self.project_one)

        report_started = self.runner.started["report"].setdefault(self.project_one, threading.Event())
        self.assertFalse(report_started.wait(0.15))
        self.assertEqual(self.db.get_task(report["id"])["status"], "queued")

        self.runner.release["research"].setdefault(self.project_one, threading.Event()).set()
        self.assertTrue(report_started.wait(1))

    def test_socai_research_tasks_remain_globally_serial(self):
        self._research(self.project_one, "关键词一")
        self.assertTrue(self.runner.started["research"].setdefault(self.project_one, threading.Event()).wait(1))
        second = self._research(self.project_two, "关键词二")

        second_started = self.runner.started["research"].setdefault(self.project_two, threading.Event())
        self.assertFalse(second_started.wait(0.15))
        self.assertEqual(self.db.get_task(second["id"])["status"], "queued")

        self.runner.release["research"].setdefault(self.project_one, threading.Event()).set()
        self.assertTrue(second_started.wait(1))


if __name__ == "__main__":
    unittest.main()
