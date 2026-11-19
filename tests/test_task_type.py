import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database


class TaskTypeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "research.sqlite3"
        self.db = Database(self.path)
        self.db.initialize()
        self.project_id = self.db.create_project("任务类型项目", "keyword", {})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_task_persists_structured_type(self):
        research_id = self.db.create_task(
            self.project_id, "keyword", "test", {"mode": "keyword"}, task_type="research"
        )
        vision_id = self.db.create_task(
            self.project_id, "keyword", "test", {"operation": "vision"}, task_type="vision"
        )
        report_id = self.db.create_task(
            self.project_id, "keyword", "test", {"operation": "ai_report"}, task_type="ai_report"
        )

        self.assertEqual(self.db.get_task(research_id)["task_type"], "research")
        self.assertEqual(self.db.get_task(vision_id)["task_type"], "vision")
        self.assertEqual(self.db.get_task(report_id)["task_type"], "ai_report")

    def test_initialize_backfills_task_type_for_legacy_rows(self):
        self.db.create_task(self.project_id, "keyword", "test", {"mode": "keyword"})
        self.db.create_task(self.project_id, "keyword", "test", {"operation": "vision"})
        self.db.create_task(self.project_id, "keyword", "test", {"operation": "ai_report"})

        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """CREATE TABLE tasks_legacy (
                id TEXT PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                mode TEXT NOT NULL CHECK (mode IN ('author','keyword','mixed')),
                created_from TEXT NOT NULL CHECK (created_from IN ('codex','web','test')),
                input_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                current_phase TEXT NOT NULL DEFAULT 'queued',
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
                )"""
            )
            legacy_columns = (
                "id,project_id,mode,created_from,input_json,status,current_phase,progress_current,"
                "progress_total,warning_count,error_message,result_json,created_at,started_at,finished_at"
            )
            conn.execute(f"INSERT INTO tasks_legacy({legacy_columns}) SELECT {legacy_columns} FROM tasks")
            conn.execute("DROP TABLE tasks")
            conn.execute("ALTER TABLE tasks_legacy RENAME TO tasks")

        self.db.initialize()
        tasks = self.db.list_tasks(self.project_id)
        types_by_operation = {
            (task["input_json"].get("operation") or "research"): task["task_type"] for task in tasks
        }
        self.assertEqual(types_by_operation, {
            "research": "research",
            "vision": "vision",
            "ai_report": "ai_report",
        })

    def test_initialize_repairs_an_incomplete_existing_backfill(self):
        vision_id = self.db.create_task(
            self.project_id, "keyword", "test", {"operation": "vision"}, task_type="vision"
        )
        with self.db.connect() as conn:
            conn.execute("UPDATE tasks SET task_type='research' WHERE id=?", (vision_id,))

        self.db.initialize()

        self.assertEqual(self.db.get_task(vision_id)["task_type"], "vision")


if __name__ == "__main__":
    unittest.main()
