from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.collector import READ_POST_COMMENTS, READ_POST_SUB_COMMENTS
from xhs_research.db import ActiveTaskConflict, Database
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication, create_server
from xhs_research.xiaohongshu_cli import XiaohongshuCliClient


class CommentCollector:
    provider_id = "xiaohongshu-cli"
    display_name = "评论测试采集器"
    capabilities = {READ_POST_COMMENTS, READ_POST_SUB_COMMENTS}

    def __init__(self):
        self.calls = []
        self.sub_calls = []

    def read_post_comments(self, post, cursor=""):
        self.calls.append((post["note_id"], cursor))
        if not cursor:
            return {
                "comments": [
                    {
                        "id": "root-1",
                        "content": "一级评论 1",
                        "create_time": 1_700_000_000_000,
                        "like_count": 3,
                        "sub_comment_count": 2,
                        "sub_comment_has_more": True,
                        "sub_comment_cursor": "reply-page-2",
                        "user_info": {"user_id": "user-1", "nickname": "甲"},
                        "sub_comments": [
                            {
                                "id": "reply-1",
                                "content": "回复预览",
                                "user_info": {"user_id": "user-2", "nickname": "乙"},
                            }
                        ],
                    },
                    {"id": "root-2", "content": "一级评论 2", "sub_comments": []},
                ],
                "cursor": "page-2",
                "has_more": True,
                "xsec_token": "must-not-persist",
            }
        return {
            "comments": [{"id": "root-3", "content": "一级评论 3"}],
            "cursor": "",
            "has_more": False,
        }

    def read_post_sub_comments(self, note_id, comment_id, cursor=""):
        self.sub_calls.append((note_id, comment_id, cursor))
        return {
            "comments": [{
                "id": "reply-2",
                "content": "完整楼中楼回复",
                "user_info": {"user_id": "user-3", "nickname": "丙"},
            }],
            "cursor": "",
            "has_more": False,
        }


class PostCommentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db = Database(self.root / "research.sqlite3")
        self.db.initialize()
        self.post_id = self.db.upsert_post({
            "note_id": "100000000000000000000002",
            "title": "评论样本帖",
            "url": "https://www.xiaohongshu.com/explore/100000000000000000000002?xsec_token=secret",
            "comments_count": 99,
        })

    def _task(self, pages=2, **overrides):
        config = {
            "post_id": self.post_id,
            "collection_mode": "continue",
            "requested_pages": pages,
            "page_delay_min_seconds": 0,
            "page_delay_max_seconds": 0,
            "include_sub_comments": False,
            "sub_comment_page_limit": 20,
        }
        config.update(overrides)
        payload = {
            "operation": "post_comment_collection",
            "mode": "post",
            "post_comments": config,
        }
        task_id = self.db.create_task(
            None, "post", "test", payload,
            task_type="comments", post_id=self.post_id,
        )
        return task_id, config

    def test_two_pages_are_saved_as_one_task_snapshot(self):
        task_id, config = self._task()
        collector = CommentCollector()
        runner = TaskRunner(self.db, collectors={collector.provider_id: collector})

        runner.run_post_comment_collection(task_id, config)

        task = self.db.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress_current"], 2)
        self.assertEqual(task["result_json"]["root_comment_count"], 3)
        self.assertNotIn("xsec_token", str(task["result_json"]))
        self.assertEqual(collector.calls, [
            ("100000000000000000000002", ""),
            ("100000000000000000000002", "page-2"),
        ])
        result = self.db.list_post_comments(self.post_id)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["summary"]["reply_preview_count"], 1)
        self.assertEqual(result["items"][0]["reply_previews"][0]["content"], "回复预览")

    def test_continue_uses_the_saved_cursor_across_tasks(self):
        collector = CommentCollector()
        runner = TaskRunner(self.db, collectors={collector.provider_id: collector})
        first_task, first_config = self._task(1)

        runner.run_post_comment_collection(first_task, first_config)

        checkpoint = self.db.get_post_comment_checkpoint(self.post_id)
        self.assertEqual(checkpoint["status"], "active")
        self.assertEqual(checkpoint["completed_pages"], 1)
        self.assertEqual(checkpoint["next_cursor"], "page-2")

        second_task, second_config = self._task(1)
        runner.run_post_comment_collection(second_task, second_config)

        self.assertEqual(collector.calls[-1], ("100000000000000000000002", "page-2"))
        checkpoint = self.db.get_post_comment_checkpoint(self.post_id)
        self.assertEqual(checkpoint["status"], "exhausted")
        self.assertEqual(checkpoint["completed_pages"], 2)
        self.assertEqual(self.db.list_post_comments(self.post_id)["total"], 3)

    def test_refresh_preserves_a_valid_deep_checkpoint(self):
        collector = CommentCollector()
        runner = TaskRunner(self.db, collectors={collector.provider_id: collector})
        first_task, first_config = self._task(1)
        runner.run_post_comment_collection(first_task, first_config)
        before = self.db.get_post_comment_checkpoint(self.post_id)

        refresh_task, refresh_config = self._task(1, collection_mode="refresh")
        runner.run_post_comment_collection(refresh_task, refresh_config)

        after = self.db.get_post_comment_checkpoint(self.post_id)
        self.assertEqual(collector.calls[-1], ("100000000000000000000002", ""))
        self.assertEqual(after["next_cursor"], before["next_cursor"])
        self.assertEqual(after["completed_pages"], before["completed_pages"])

    def test_full_sub_comments_are_fetched_with_the_task_budget(self):
        task_id, config = self._task(
            1,
            include_sub_comments=True,
            sub_comment_page_limit=1,
        )
        collector = CommentCollector()
        runner = TaskRunner(self.db, collectors={collector.provider_id: collector})

        runner.run_post_comment_collection(task_id, config)

        self.assertEqual(collector.sub_calls, [(
            "100000000000000000000002", "root-1", "reply-page-2",
        )])
        result = self.db.list_post_comments(self.post_id)
        self.assertEqual(result["summary"]["reply_count"], 2)
        self.assertEqual(result["summary"]["reply_preview_count"], 0)
        self.assertEqual(
            [reply["content"] for reply in result["items"][0]["reply_previews"]],
            ["回复预览", "完整楼中楼回复"],
        )

    def test_only_one_active_comment_task_is_allowed_per_post(self):
        self._task(1)
        with self.assertRaisesRegex(ActiveTaskConflict, "已有运行中的评论采集任务"):
            self._task(1)

    def test_application_snapshot_excludes_note_url_and_auth_token(self):
        runner = SimpleNamespace(run_post_comment_collection=lambda *_args: None)
        app = ResearchApplication(
            SimpleNamespace(data_dir=self.root, host="127.0.0.1", port=0, max_workers=1),
            self.db,
            runner,
            WORKBENCH_ROOT / "web",
        )
        app._submit = lambda *_args, **_kwargs: None
        self.addCleanup(app.shutdown)

        receipt = app.create_post_comment_task(
            self.post_id, "test", {"requested_pages": 1},
        )

        task = self.db.get_task(receipt["id"])
        serialized = str(task["input_json"])
        self.assertNotIn("note_url", serialized)
        self.assertNotIn("xsec_token", serialized)
        self.assertEqual(task["post_id"], self.post_id)
        self.assertEqual(task["task_type"], "comments")
        self.assertEqual(task["input_json"]["post_comments"]["collection_mode"], "continue")
        self.assertEqual(task["input_json"]["post_comments"]["page_delay_min_seconds"], 1)
        self.assertEqual(task["input_json"]["post_comments"]["page_delay_max_seconds"], 2)

    def test_xiaohongshu_cli_uses_cursor_without_all_flag(self):
        client = XiaohongshuCliClient(cookie_source="chrome")
        calls = []
        client._run = lambda args: calls.append(args) or {"comments": [], "has_more": False}

        client.read_post_comments({"note_id": "note-1", "note_url": "https://example.test/note-1"}, "next")

        self.assertEqual(calls, [["comments", "https://example.test/note-1", "--cursor", "next"]])
        self.assertNotIn("--all", calls[0])

    def test_xiaohongshu_cli_reads_sub_comments_with_cursor(self):
        client = XiaohongshuCliClient(cookie_source="chrome")
        calls = []
        client._run = lambda args: calls.append(args) or {"comments": [], "has_more": False}

        client.read_post_sub_comments("note-1", "comment-1", "next")

        self.assertEqual(calls, [["sub-comments", "note-1", "comment-1", "--cursor", "next"]])

    def test_http_routes_create_task_and_return_comment_summary(self):
        runner = SimpleNamespace(run_post_comment_collection=lambda *_args: None)
        app = ResearchApplication(
            SimpleNamespace(data_dir=self.root, host="127.0.0.1", port=0, max_workers=1),
            self.db,
            runner,
            WORKBENCH_ROOT / "web",
        )
        app._submit = lambda *_args, **_kwargs: None
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(
                f"{base}/api/posts/{self.post_id}/comment-tasks",
                data=json.dumps({"configuration": {"requested_pages": 2}}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                receipt = json.loads(response.read())
                self.assertEqual(response.status, 202)
            with urlopen(f"{base}/api/posts/{self.post_id}/comments") as response:
                page = json.loads(response.read())
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.shutdown()
        self.assertEqual(self.db.get_task(receipt["id"])["task_type"], "comments")
        self.assertEqual(page["summary"]["active_task"]["id"], receipt["id"])


if __name__ == "__main__":
    unittest.main()
