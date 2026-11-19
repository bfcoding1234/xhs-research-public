from pathlib import Path
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.collector import LIST_AUTHOR_POSTS, READ_AUTHOR_POST_DETAILS, READ_AUTHOR_PROFILE
from xhs_research.config import Settings
from xhs_research.db import Database
from xhs_research.models import ResearchRequest
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication


class AuthorUpdateCollector:
    provider_id = "xiaohongshu-cli"
    display_name = "作者更新测试采集器"
    capabilities = {READ_AUTHOR_PROFILE, LIST_AUTHOR_POSTS, READ_AUTHOR_POST_DETAILS}

    def __init__(self):
        self.calls = []

    def read_author_profile(self, author_id):
        self.calls.append((READ_AUTHOR_PROFILE, author_id))
        return {
            "profile": {
                "author_id": author_id,
                "display_name": "更新后的作者",
                "bio": "更新后的简介",
                "followers_count": 12345,
            },
            "cards": [],
            "notes": [],
            "warnings": [],
        }

    def list_author_posts(self, author_id, limit, ocr):
        self.calls.append((LIST_AUTHOR_POSTS, author_id, limit, ocr))
        cards = [{
            "note_id": "preview-note",
            "title": "预览帖子",
            "author_id": author_id,
            "author": "预览返回的作者名",
            "source_type": "author",
            "source_value": author_id,
            "source_rank": 0,
            "detail_level": "card",
            "likes_count": 66,
        }]
        return {
            "profile": {"author_id": author_id, "display_name": "预览返回的作者名"},
            "cards": cards[:limit],
            "notes": [],
            "warnings": [],
        }

    def read_author_post_details(self, author_id, limit, ocr, download_media):
        self.calls.append((READ_AUTHOR_POST_DETAILS, author_id, limit, ocr, download_media))
        cards = [{
            "note_id": "detail-note",
            "title": "作者帖子",
            "author_id": author_id,
            "author": "详情返回的作者名",
            "source_type": "author",
            "source_value": author_id,
            "source_rank": 0,
            "detail_level": "card",
        }]
        notes = [{
            **cards[0],
            "content": "完整正文",
            "likes_count": 88,
            "detail_level": "detail",
        }]
        return {
            "profile": {"author_id": author_id, "display_name": "详情返回的作者名"},
            "cards": cards[:limit],
            "notes": notes[:limit],
            "warnings": [],
        }

    @staticmethod
    def normalize_result(raw, _source_type, _source_value):
        return raw


class RoutedPreviewCollector:
    capabilities = {LIST_AUTHOR_POSTS}

    def __init__(self, provider_id, result_count):
        self.provider_id = provider_id
        self.display_name = provider_id
        self.result_count = result_count
        self.calls = []

    def list_author_posts(self, author_id, limit, ocr):
        self.calls.append((author_id, limit, ocr))
        cards = [{
            "note_id": f"{self.provider_id}-{index}",
            "title": f"帖子 {index}",
            "author_id": author_id,
            "source_type": "author",
            "source_value": author_id,
            "source_rank": index,
            "detail_level": "card",
        } for index in range(min(limit, self.result_count))]
        return {"profile": {"author_id": author_id}, "cards": cards, "notes": [], "warnings": []}

    @staticmethod
    def normalize_result(raw, _source_type, _source_value):
        return raw


class RecordingBulkAuthorRunner:
    def __init__(self):
        self.calls = []
        self.completed = threading.Event()

    def run_project_author_update(self, task_id, project_id, configuration):
        self.calls.append((task_id, project_id, configuration))
        self.completed.set()

    def cancel(self, _task_id):
        return None


class AuthorUpdateTests(unittest.TestCase):
    def run_update(self, scopes):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = Database(Path(temp_dir.name) / "research.sqlite3")
        db.initialize()
        db.upsert_author({
            "author_id": "author-a",
            "display_name": "原作者",
            "bio": "原简介",
            "followers_count": 10,
        })
        request = ResearchRequest.from_dict({
            "mode": "author",
            "created_from": "test",
            "source": {"author_ids": ["author-a"]},
            "limits": {"discovery": 7, "deep": 7},
            "author_update": {"scopes": scopes},
            "force_refresh": True,
        })
        task_id = db.create_task(None, "author", "test", request.to_dict())
        collector = AuthorUpdateCollector()

        TaskRunner(db, collectors={collector.provider_id: collector}).run(task_id, request)

        return db, task_id, collector

    def test_basic_info_update_does_not_collect_posts(self):
        db, task_id, collector = self.run_update(["basic_info"])

        author = db.query("SELECT * FROM authors WHERE author_id='author-a'")[0]
        self.assertEqual(author["display_name"], "更新后的作者")
        self.assertEqual(author["followers_count"], 12345)
        self.assertEqual(db.list_task_posts(task_id), [])
        self.assertEqual(collector.calls, [(READ_AUTHOR_PROFILE, "author-a")])
        self.assertEqual(db.get_task(task_id)["result_json"]["author_update_scopes"], ["basic_info"])

    def test_detailed_posts_update_does_not_overwrite_basic_profile(self):
        db, task_id, collector = self.run_update(["detailed_posts"])

        author = db.query("SELECT * FROM authors WHERE author_id='author-a'")[0]
        post = db.list_task_posts(task_id)[0]
        self.assertEqual(author["display_name"], "原作者")
        self.assertEqual(author["bio"], "原简介")
        self.assertEqual(post["content"], "完整正文")
        self.assertEqual(post["detail_level"], "detail")
        self.assertEqual(collector.calls, [(READ_AUTHOR_POST_DETAILS, "author-a", 7, True, True)])

    def test_preview_posts_update_batches_cards_without_opening_details(self):
        db, task_id, collector = self.run_update(["preview_posts"])

        author = db.query("SELECT * FROM authors WHERE author_id='author-a'")[0]
        post = db.list_task_posts(task_id)[0]
        self.assertEqual(author["display_name"], "原作者")
        self.assertEqual(post["title"], "预览帖子")
        self.assertEqual(post["detail_level"], "card")
        self.assertEqual(collector.calls, [(LIST_AUTHOR_POSTS, "author-a", 7, True)])

    def test_all_scopes_execute_their_atomic_capabilities(self):
        db, task_id, collector = self.run_update(["basic_info", "preview_posts", "detailed_posts"])

        self.assertEqual(
            [call[0] for call in collector.calls],
            [READ_AUTHOR_PROFILE, LIST_AUTHOR_POSTS, READ_AUTHOR_POST_DETAILS],
        )
        self.assertEqual(db.get_task(task_id)["status"], "completed")
        self.assertEqual(db.get_task(task_id)["result_json"]["post_count"], 2)

    def test_large_preview_promotes_paginated_provider_from_current_route(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = Database(Path(temp_dir.name) / "research.sqlite3")
        db.initialize()
        db.upsert_author({"author_id": "author-a", "display_name": "原作者"})
        request = ResearchRequest.from_dict({
            "mode": "author",
            "created_from": "test",
            "source": {"author_ids": ["author-a"]},
            "limits": {"discovery": 50, "deep": 0},
            "author_update": {"scopes": ["preview_posts"]},
            "force_refresh": True,
        })
        task_id = db.create_task(None, "author", "test", request.to_dict())
        socai = RoutedPreviewCollector("socai", 30)
        xhs = RoutedPreviewCollector("xiaohongshu-cli", 49)

        TaskRunner(
            db,
            collectors={"socai": socai, "xiaohongshu-cli": xhs},
        ).run(task_id, request)

        task = db.get_task(task_id)
        usage = task["result_json"]["capability_usage"][LIST_AUTHOR_POSTS]
        self.assertEqual(socai.calls, [])
        self.assertEqual(xhs.calls, [("author-a", 50, True)])
        self.assertEqual(task["result_json"]["post_count"], 49)
        self.assertEqual(usage["selected_provider"], "xiaohongshu-cli")
        route = next(
            item for item in task["result_json"]["capability_routes"]
            if item["capability"] == LIST_AUTHOR_POSTS
        )
        self.assertEqual(route["commands"][0], "xiaohongshu-cli.list_author_posts")
        adjusted = [
            event for event in db.list_task_events(task_id)
            if event["event_type"] == "route_adjusted"
        ]
        self.assertEqual(len(adjusted), 1)

    def test_project_author_bulk_update_runs_many_authors_in_one_task(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = Database(Path(temp_dir.name) / "research.sqlite3")
        db.initialize()
        project_id = db.create_project("批量作者项目", "author", {})
        for author_id in ("author-a", "author-b", "author-c"):
            author_pk = db.upsert_author({"author_id": author_id, "display_name": author_id})
            db.attach_author_to_project(project_id, author_pk, "manual")
        author_ids = ["author-a", "author-b", "author-c"]
        payload = {
            "operation": "project_author_update",
            "mode": "author",
            "project_id": project_id,
            "created_from": "test",
            "source": {"author_ids": author_ids},
            "author_update_bulk": {
                "target": "all",
                "scopes": ["basic_info", "preview_posts"],
                "author_ids": author_ids,
                "batch_size": 2,
                "max_authors": 3,
                "preview_limit": 1,
                "detail_limit": 1,
                "author_delay_min_seconds": 0,
                "author_delay_max_seconds": 0,
                "batch_delay_min_seconds": 0,
                "batch_delay_max_seconds": 0,
                "consecutive_failure_limit": 5,
            },
        }
        task_id = db.create_task(project_id, "author", "test", payload)
        collector = AuthorUpdateCollector()

        TaskRunner(db, collectors={collector.provider_id: collector}).run_project_author_update(
            task_id,
            project_id,
            payload["author_update_bulk"],
        )

        task = db.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress_current"], 3)
        self.assertEqual(task["progress_total"], 3)
        self.assertEqual(task["result_json"]["completed_count"], 3)
        self.assertEqual(task["result_json"]["failed_count"], 0)
        self.assertEqual(
            [call[0] for call in collector.calls],
            [
                READ_AUTHOR_PROFILE,
                LIST_AUTHOR_POSTS,
                READ_AUTHOR_PROFILE,
                LIST_AUTHOR_POSTS,
                READ_AUTHOR_PROFILE,
                LIST_AUTHOR_POSTS,
            ],
        )
        self.assertEqual(len(db.list_project_authors(project_id)), 3)
        summary_report = db.list_reports(project_id)[0]
        self.assertEqual(summary_report["summary_json"]["schema_version"], 6)
        self.assertEqual(summary_report["generation_config_json"]["operation"], "project_author_update")

    def test_project_author_bulk_update_uses_short_delay_defaults(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = Database(Path(temp_dir.name) / "research.sqlite3")
        db.initialize()
        project_id = db.create_project("批量作者项目", "author", {})
        author_pk = db.upsert_author({"author_id": "author-a", "display_name": "作者甲"})
        db.attach_author_to_project(project_id, author_pk, "manual")
        runner = RecordingBulkAuthorRunner()
        settings = Settings(data_dir=Path(temp_dir.name), host="127.0.0.1", port=4318)
        app = ResearchApplication(settings, db, runner, WORKBENCH_ROOT / "web")
        self.addCleanup(app.shutdown)

        receipt = app.create_project_author_update_task(project_id, "test", {
            "target": "all",
            "scopes": ["basic_info"],
            "batch_size": 10,
            "max_authors": 100,
            "preview_limit": 20,
            "detail_limit": 5,
            "consecutive_failure_limit": 5,
        })

        self.assertTrue(runner.completed.wait(1))
        configuration = db.get_task(receipt["id"])["input_json"]["author_update_bulk"]
        self.assertEqual(configuration["author_delay_min_seconds"], 1)
        self.assertEqual(configuration["author_delay_max_seconds"], 3)
        self.assertEqual(configuration["batch_delay_min_seconds"], 2)
        self.assertEqual(configuration["batch_delay_max_seconds"], 5)


if __name__ == "__main__":
    unittest.main()
