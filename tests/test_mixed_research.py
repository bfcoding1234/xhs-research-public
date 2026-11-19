from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.collector import CollectorError, SEARCH_USERS_BY_KEYWORD
from xhs_research.models import ResearchRequest
from xhs_research.runner import TaskRunner
from xhs_research.socai import SocaiError


class FakeSocai:
    def __init__(self):
        self.calls = []

    def keyword_preview(self, keyword, limit, filters, ocr):
        self.calls.append(("keyword_preview", keyword, limit, filters, ocr))
        return {"cards": [{
            "note_id": "keyword-note", "title": "关键词帖子", "author_id": "post-author",
            "author": "帖子作者", "likes": "10", "position": 0,
        }]}

    def author_preview(self, author_id, limit, ocr):
        self.calls.append(("author_preview", author_id, limit, ocr))
        return {"author_id": author_id, "profile": {
            "author_id": author_id, "display_name": "选定作者",
            "note_cards": [{
                "note_id": "author-note", "title": "作者帖子", "author_id": author_id,
                "author": "选定作者", "likes": "20", "position": 0,
            }],
        }}


class LoginThenSuccessSocai(FakeSocai):
    def keyword_preview(self, keyword, limit, filters, ocr):
        self.calls.append(("keyword_preview", keyword, limit, filters, ocr))
        if len(self.calls) == 1:
            raise SocaiError("请在小红书页面完成登录", "login_required")
        return {"cards": [{
            "note_id": "resumed-note", "title": "恢复后的帖子", "author_id": "post-author",
            "author": "帖子作者", "likes": "10", "position": 0,
        }]}


class AlwaysLoginSocai(FakeSocai):
    def __init__(self):
        super().__init__()
        self.called = threading.Event()

    def keyword_preview(self, keyword, limit, filters, ocr):
        self.called.set()
        raise SocaiError("请在小红书页面完成登录", "login_required")


class ManualVerificationSocai(FakeSocai):
    def __init__(self):
        super().__init__()
        self.blocked = threading.Event()
        self.verified = False

    def keyword_preview(self, keyword, limit, filters, ocr):
        self.calls.append(("keyword_preview", keyword, limit, filters, ocr))
        if not self.verified:
            self.blocked.set()
            raise SocaiError("not_profile_page", "verification_required")
        return {"cards": [{
            "note_id": "verified-note", "title": "验证后恢复的帖子", "author_id": "post-author",
            "author": "帖子作者", "likes": "10", "position": 0,
        }]}


class RepeatedManualChallengeCollector(FakeSocai):
    provider_id = "socai"
    display_name = "Socai"

    def __init__(self):
        super().__init__()
        self.first_call = threading.Event()
        self.second_call = threading.Event()

    def keyword_preview(self, keyword, limit, filters, ocr):
        self.calls.append(("keyword_preview", keyword, limit, filters, ocr))
        if len(self.calls) == 1:
            self.first_call.set()
        else:
            self.second_call.set()
        raise SocaiError("请完成人工验证", "verification_required")


class PolicyChangingSocai(FakeSocai):
    def __init__(self, db):
        super().__init__()
        self.db = db

    def keyword_preview(self, keyword, limit, filters, ocr):
        # Simulate a user saving settings while this task is already running.
        self.db.set_app_settings({"detail_ttl_days": 0, "author_ttl_days": 0})
        return super().keyword_preview(keyword, limit, filters, ocr)


class NamedCollector:
    def __init__(self, provider_id, cards=None, error=None):
        self.provider_id = provider_id
        self.display_name = provider_id
        self.cards = cards or []
        self.error = error
        self.calls = []

    def keyword_preview(self, keyword, limit, filters, ocr):
        self.calls.append(("keyword_preview", keyword, limit))
        if self.error:
            raise self.error
        return {"cards": self.cards[:limit]}

    def keyword_deep(self, keyword, limit, filters, ocr, download_media):
        self.calls.append(("keyword_deep", keyword, limit))
        if self.error:
            raise self.error
        return {"notes": [
            {"ok": True, "entity": {**card, "content": f"{self.provider_id} 详情"}}
            for card in self.cards[:limit]
        ]}


class UserSearchCollector:
    provider_id = "xiaohongshu-cli"
    display_name = "xiaohongshu-cli"
    capabilities = {SEARCH_USERS_BY_KEYWORD}

    def __init__(self):
        self.calls = []

    def search_users_by_keyword(self, keyword, limit):
        self.calls.append((keyword, limit))
        return {"profiles": [{
            "author_id": "discovered-author",
            "display_name": "发现的作者",
            "profile_url": "https://www.xiaohongshu.com/user/profile/discovered-author",
        }]}


class MixedResearchTests(unittest.TestCase):
    def test_independent_task_collects_global_entities_without_creating_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            request = ResearchRequest.from_dict({
                "mode": "keyword",
                "created_from": "test",
                "source": {"keywords": ["独立采集"]},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(None, "keyword", "test", request.to_dict())
            collector = NamedCollector("socai", cards=[{
                "note_id": "independent-note",
                "title": "独立任务帖子",
                "author_id": "independent-author",
                "author": "独立作者",
                "likes": "12",
            }])

            TaskRunner(db, collectors={"socai": collector}).run(task_id, request)

            task = db.get_task(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertIsNone(task["project_id"])
            self.assertEqual(task["result_json"]["post_count"], 1)
            self.assertEqual(task["result_json"]["author_count"], 1)
            self.assertEqual([post["note_id"] for post in db.list_task_posts(task_id)], [
                "independent-note",
            ])
            self.assertEqual(len(db.list_posts()), 1)
            self.assertEqual(len(db.list_authors()), 1)
            self.assertEqual(db.list_projects(), [])
            self.assertEqual(db.scalar("SELECT COUNT(*) FROM reports"), 0)

    def test_capability_router_uses_first_success_and_falls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("自动协同", "keyword", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "collector": "auto",
                "created_from": "test", "source": {"keywords": ["AI"]},
                "limits": {"discovery": 3, "deep": 1},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = NamedCollector("socai", cards=[
                {"note_id": "shared", "title": "短标题", "author_id": "author-a", "likes": "10"},
                {"note_id": "socai-only", "title": "Socai 帖子", "author_id": "author-a", "likes": "2"},
            ])
            xhs = NamedCollector("xiaohongshu-cli", cards=[
                {"note_id": "shared", "title": "更完整的共享标题", "author_id": "author-a", "likes": "12"},
                {"note_id": "xhs-only", "title": "XHS 帖子", "author_id": "author-b", "likes": "3"},
            ])

            TaskRunner(db, collectors={"socai": socai, "xiaohongshu-cli": xhs}).run(task_id, request)

            task = db.get_task(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual({post["note_id"] for post in db.list_project_posts(project_id)}, {
                "shared", "socai-only",
            })
            self.assertEqual(task["result_json"]["routing_mode"], "capability")
            self.assertEqual(task["result_json"]["collector_usage"]["socai"]["calls"], 2)
            self.assertEqual(xhs.calls, [])

            fallback_project_id = db.create_project("自动降级", "keyword", {}, "主题")
            fallback_request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": fallback_project_id, "collector": "auto",
                "created_from": "test", "source": {"keywords": ["AI"]},
                "limits": {"discovery": 1, "deep": 0},
            })
            fallback_task_id = db.create_task(
                fallback_project_id, "keyword", "test", fallback_request.to_dict(),
            )
            broken = NamedCollector("socai", error=CollectorError("暂不可用", "provider_down"))
            TaskRunner(db, collectors={"socai": broken, "xiaohongshu-cli": xhs}).run(
                fallback_task_id, fallback_request,
            )
            fallback_task = db.get_task(fallback_task_id)
            self.assertEqual(fallback_task["status"], "completed")
            self.assertEqual(fallback_task["result_json"]["collector_usage"]["socai"]["failures"], 1)
            self.assertEqual(fallback_task["result_json"]["capability_usage"]["search_posts_by_keyword"]["selected_provider"], "xiaohongshu-cli")

    def test_author_task_rejects_user_keyword_discovery(self):
        with self.assertRaisesRegex(ValueError, "does not support user keyword"):
            ResearchRequest.from_dict({
                "mode": "author", "created_from": "test",
                "source": {"author_ids": ["author-a"], "user_keywords": ["AI 产品经理"]},
            })

    def test_keyword_task_can_collect_related_users_without_collecting_their_posts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("关键词帖子和作者", "keyword", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "keyword",
                "project_id": project_id,
                "created_from": "test",
                "source": {
                    "keywords": ["AI 产品经理"],
                    "user_keywords": ["AI 产品经理"],
                },
                "user_limits": {"discovery": 1},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = FakeSocai()
            xhs = UserSearchCollector()

            TaskRunner(db, collectors={"socai": socai, "xiaohongshu-cli": xhs}).run(
                task_id,
                request,
            )

            task = db.get_task(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(xhs.calls, [("AI 产品经理", 1)])
            self.assertEqual(
                socai.calls,
                [("keyword_preview", "AI 产品经理", 1, {}, True)],
            )
            authors = {author["author_id"]: author for author in db.list_project_authors(project_id)}
            self.assertIn("discovered-author", authors)
            self.assertIn("task_added", authors["discovered-author"]["relation_type"])
            usage = task["result_json"]["capability_usage"]
            self.assertIn("search_users_by_keyword", usage)
            self.assertIn("search_posts_by_keyword", usage)
            self.assertNotIn("list_author_posts", usage)

    def test_author_source_posts_stay_global_while_keyword_post_authors_join_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("关联范围", "mixed", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "mixed", "project_id": project_id, "topic": "主题",
                "created_from": "test",
                "source": {"keywords": ["AI"], "author_ids": ["chosen-author"]},
                "keyword_limits": {"discovery": 1, "deep": 0},
                "author_limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "mixed", "test", request.to_dict())

            TaskRunner(db, collectors={"socai": FakeSocai()}).run(task_id, request)

            self.assertEqual(
                {post["note_id"] for post in db.list_project_posts(project_id)},
                {"keyword-note"},
            )
            authors = {author["author_id"]: author for author in db.list_project_authors(project_id)}
            self.assertIn("keyword_post_author", authors["post-author"]["relation_type"])
            self.assertIn("task_added", authors["chosen-author"]["relation_type"])
            self.assertIn("author-note", {post["note_id"] for post in db.list_posts()})

    def test_keyword_task_can_collect_only_related_users(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("只采关键词作者", "keyword", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "keyword",
                "project_id": project_id,
                "created_from": "test",
                "source": {"user_keywords": ["AI 产品经理"]},
                "user_limits": {"discovery": 80},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = FakeSocai()
            xhs = UserSearchCollector()

            TaskRunner(db, collectors={"socai": socai, "xiaohongshu-cli": xhs}).run(
                task_id,
                request,
            )

            task = db.get_task(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(xhs.calls, [("AI 产品经理", 80)])
            self.assertEqual(socai.calls, [])
            self.assertEqual(db.list_project_posts(project_id), [])
            authors = {author["author_id"] for author in db.list_project_authors(project_id)}
            self.assertIn("discovered-author", authors)
            usage = task["result_json"]["capability_usage"]
            self.assertIn("search_users_by_keyword", usage)
            self.assertNotIn("search_posts_by_keyword", usage)
            self.assertNotIn("list_author_posts", usage)

    def test_task_snapshots_persisted_collector_command_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            db.set_app_settings({
                "capability_routes": {
                    "search_posts_by_keyword": [
                        "xiaohongshu-cli.search_posts_by_keyword",
                        "socai.search_posts_by_keyword",
                    ],
                },
            })
            project_id = db.create_project("自定义指令顺序", "keyword", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI"]},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = NamedCollector("socai", cards=[{"note_id": "socai", "title": "Socai"}])
            xhs = NamedCollector("xiaohongshu-cli", cards=[{"note_id": "xhs", "title": "XHS"}])

            TaskRunner(db, collectors={"socai": socai, "xiaohongshu-cli": xhs}).run(task_id, request)

            task = db.get_task(task_id)
            usage = task["result_json"]["capability_usage"]["search_posts_by_keyword"]
            self.assertEqual(usage["selected_provider"], "xiaohongshu-cli")
            self.assertEqual(
                usage["selected_command"],
                "xiaohongshu-cli.search_posts_by_keyword",
            )
            self.assertEqual(socai.calls, [])
            route = next(
                route for route in task["result_json"]["capability_routes"]
                if route["capability"] == "search_posts_by_keyword"
            )
            self.assertEqual(route["commands"][0], "xiaohongshu-cli.search_posts_by_keyword")

    def test_refresh_policy_is_snapshotted_once_when_task_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            db.set_app_settings({"detail_ttl_days": 31, "author_ttl_days": 11})
            project_id = db.create_project("策略快照", "mixed", {}, "主题")
            request = ResearchRequest.from_dict({
                "mode": "mixed", "project_id": project_id, "topic": "主题",
                "created_from": "test",
                "source": {"keywords": ["关键词"], "author_ids": ["author-a"]},
                "keyword_limits": {"discovery": 1, "deep": 1},
                "author_limits": {"discovery": 1, "deep": 1},
            })
            task_id = db.create_task(project_id, "mixed", "test", request.to_dict())
            socai = PolicyChangingSocai(db)

            with patch.object(db, "author_profile_is_fresh", return_value=True) as author_fresh, \
                    patch.object(db, "post_details_are_fresh", return_value=True) as details_fresh:
                TaskRunner(db, socai).run(task_id, request)

            self.assertEqual(author_fresh.call_args.args, ("author-a", 11))
            self.assertEqual([call.args[1] for call in details_fresh.call_args_list], [31, 31])
            self.assertEqual(db.get_app_settings()["detail_ttl_days"], 0)
            self.assertEqual(db.get_task(task_id)["status"], "completed")

    def test_login_required_waits_and_automatically_resumes_same_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("登录恢复项目", "keyword", {})
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理"]},
                "limits": {"discovery": 10, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = LoginThenSuccessSocai()

            TaskRunner(db, socai, login_retry_interval=0).run(task_id, request)

            task = db.get_task(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(len(socai.calls), 2)
            events = db.list_task_events(task_id)
            self.assertIn("waiting_login", [event["phase"] for event in events])
            self.assertIn("login_resumed", [event["phase"] for event in events])

    def test_waiting_login_retry_loop_can_be_cancelled_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("等待登录项目", "keyword", {})
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理"]},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = AlwaysLoginSocai()
            runner = TaskRunner(db, socai, login_retry_interval=60)
            thread = threading.Thread(target=runner.run, args=(task_id, request), daemon=True)
            thread.start()
            self.assertTrue(socai.called.wait(1))
            deadline = time.monotonic() + 1
            while db.get_task(task_id)["status"] != "waiting_login" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(db.get_task(task_id)["status"], "waiting_login")

            self.assertTrue(db.cancel_task(task_id))
            runner.cancel(task_id)
            thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(db.get_task(task_id, include_cancelled=True)["status"], "cancelled")

    def test_manual_verification_resumes_the_same_task_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("人工验证项目", "keyword", {})
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理"]},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            socai = ManualVerificationSocai()
            fallback = NamedCollector("xiaohongshu-cli", cards=[{
                "note_id": "should-not-fallback", "title": "首选能力已恢复",
            }])
            runner = TaskRunner(
                db,
                collectors={"socai": socai, "xiaohongshu-cli": fallback},
                login_retry_interval=60,
            )
            thread = threading.Thread(target=runner.run, args=(task_id, request), daemon=True)
            thread.start()
            self.assertTrue(socai.blocked.wait(1))
            deadline = time.monotonic() + 1
            while db.get_task(task_id)["status"] != "waiting_login" and time.monotonic() < deadline:
                time.sleep(0.01)

            socai.verified = True
            runner.resume(task_id)
            thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(db.get_task(task_id)["status"], "completed")
            self.assertEqual(len(socai.calls), 2)
            self.assertEqual(fallback.calls, [])
            phases = [event["phase"] for event in db.list_task_events(task_id)]
            self.assertIn("login_resumed", phases)

    def test_human_challenge_blocks_fallback_until_manual_retry_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("人工优先降级项目", "keyword", {})
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理"]},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            primary = RepeatedManualChallengeCollector()
            fallback = NamedCollector("xiaohongshu-cli", cards=[{
                "note_id": "fallback-note", "title": "降级后的帖子",
                "author_id": "fallback-author", "author": "降级作者",
            }])
            runner = TaskRunner(
                db,
                collectors={"socai": primary, "xiaohongshu-cli": fallback},
                login_retry_interval=60,
            )
            thread = threading.Thread(target=runner.run, args=(task_id, request), daemon=True)
            thread.start()

            self.assertTrue(primary.first_call.wait(1))
            deadline = time.monotonic() + 1
            while db.get_task(task_id)["status"] != "waiting_login" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(db.get_task(task_id)["status"], "waiting_login")
            self.assertEqual(fallback.calls, [])

            runner.resume(task_id)
            thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(db.get_task(task_id)["status"], "completed")
            self.assertEqual(len(primary.calls), 2)
            self.assertEqual(len(fallback.calls), 1)
            events = db.list_task_events(task_id)
            manual_failure = next(
                event for event in events
                if event["event_type"] == "provider_failed"
                and event["payload_json"].get("after_human_intervention")
            )
            self.assertEqual(manual_failure["payload_json"]["collector"], "socai")
            fallback_event = next(
                event for event in events
                if event["event_type"] == "provider_fallback"
            )
            self.assertEqual(fallback_event["payload_json"]["trigger"], "human_retry_failed")

    def test_automatic_probe_stays_waiting_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("自动检测等待项目", "keyword", {})
            request = ResearchRequest.from_dict({
                "mode": "keyword", "project_id": project_id, "created_from": "test",
                "source": {"keywords": ["AI 产品经理"]},
                "limits": {"discovery": 1, "deep": 0},
            })
            task_id = db.create_task(project_id, "keyword", "test", request.to_dict())
            primary = RepeatedManualChallengeCollector()
            fallback = NamedCollector("xiaohongshu-cli", cards=[{
                "note_id": "unexpected-fallback", "title": "不应提前降级",
            }])
            runner = TaskRunner(
                db,
                collectors={"socai": primary, "xiaohongshu-cli": fallback},
                login_retry_interval=0.01,
            )
            thread = threading.Thread(target=runner.run, args=(task_id, request), daemon=True)
            thread.start()

            self.assertTrue(primary.second_call.wait(1))
            self.assertEqual(db.get_task(task_id)["status"], "waiting_login")
            self.assertEqual(fallback.calls, [])

            self.assertTrue(db.cancel_task(task_id))
            runner.cancel(task_id)
            thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(db.get_task(task_id, include_cancelled=True)["status"], "cancelled")

    def test_project_authors_include_hot_content_signals_for_follow_up_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("综合项目", "mixed", {}, "AI 产品经理")
            author_id = db.upsert_author({"author_id": "author-hot", "display_name": "热门作者", "followers_count": 1000, "likes_collections_count": 5000})
            db.attach_author_to_project(project_id, author_id, "keyword")
            post_id = db.upsert_post({"note_id": "hot-note", "author_id": "author-hot", "author": "热门作者", "likes_count": 200})
            db.attach_post_to_project(project_id, post_id)
            db.save_project_scores(project_id, {"scores": {str(post_id): {"score": 1, "percentile": 0.92, "level": "高热"}}, "method": "test"})

            author = db.list_project_authors(project_id)[0]
            self.assertEqual(author["hot_post_count"], 1)
            self.assertEqual(author["peak_popularity_percentile"], 0.92)

    def test_mixed_task_executes_each_confirmed_source_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("综合项目", "mixed", {}, "AI 产品经理")
            request = ResearchRequest.from_dict({
                "mode": "mixed", "project_id": project_id, "topic": "AI 产品经理",
                "created_from": "test",
                "source": {"keywords": ["AI 产品经理"], "author_ids": ["author-a"],
                           "filters": {"sort": "综合", "publish_time": "半年内"}},
                "keyword_limits": {"discovery": 12, "deep": 0},
                "author_limits": {"discovery": 34, "deep": 0},
            })
            task_id = db.create_task(project_id, "mixed", "test", request.to_dict())
            socai = FakeSocai()

            TaskRunner(db, socai).run(task_id, request)

            self.assertEqual(socai.calls, [
                ("keyword_preview", "AI 产品经理", 12, {"sort": "综合", "publish_time": "半年内"}, True),
                ("author_preview", "author-a", 34, True),
            ])
            self.assertEqual(db.get_task(task_id)["status"], "completed")
            self.assertEqual(len(db.list_project_posts(project_id)), 1)
            selected = [author for author in db.list_project_authors(project_id) if author["author_id"] == "author-a"][0]
            self.assertIn("task_added", selected["relation_type"])
            sources = db.query("SELECT DISTINCT source_type,source_value FROM task_posts WHERE task_id=? ORDER BY source_type", (task_id,))
            self.assertEqual([(row["source_type"], row["source_value"]) for row in sources], [
                ("author", "author-a"), ("keyword", "AI 产品经理")
            ])
            generated_report = db.list_reports(project_id)[0]
            self.assertEqual(generated_report["report_type"], "data_summary")
            self.assertEqual(generated_report["summary_json"]["schema_version"], 6)
            self.assertEqual(generated_report["content_markdown"], "")
            self.assertEqual(generated_report["generation_config_json"], {
                "trigger": "automatic",
                "operation": "research",
                "task_type": "research",
            })
            snapshot = generated_report["evidence_snapshot_json"]
            self.assertTrue(snapshot["captured_at"])
            self.assertEqual(snapshot["post_count"], 1)
            self.assertIn("ocr_post_count", snapshot)
            self.assertIn("vision_post_count", snapshot)
            self.assertEqual(sorted(snapshot["post_ids"]), sorted(
                post["id"] for post in db.list_project_posts(project_id)
            ))

    def test_author_task_reuses_known_posts_when_profile_scan_is_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            for index in range(3):
                db.upsert_post({
                    "note_id": f"cached-note-{index}",
                    "author_id": "author-a",
                    "author": "选定作者",
                    "title": f"历史帖子 {index}",
                })
            project_id = db.create_project("作者项目", "author", {})
            request = ResearchRequest.from_dict({
                "mode": "author", "project_id": project_id, "created_from": "test",
                "source": {"author_ids": ["author-a"]},
                "limits": {"discovery": 10, "deep": 0},
            })
            task_id = db.create_task(project_id, "author", "test", request.to_dict())

            TaskRunner(db, FakeSocai()).run(task_id, request)

            posts = db.list_project_posts(project_id)
            self.assertEqual(posts, [])
            events = db.list_task_events(task_id)
            discovery_message = [
                event["payload_json"]["message"]
                for event in events
                if event["phase"] == "discovery" and event["payload_json"].get("current") == 1
            ][0]
            self.assertNotIn("当前共", discovery_message)

    def test_known_author_post_reuse_respects_discovery_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            for index in range(5):
                db.upsert_post({
                    "note_id": f"cached-note-{index}",
                    "author_id": "author-a",
                    "author": "选定作者",
                })
            project_id = db.create_project("作者项目", "author", {})

            count = db.attach_known_author_posts(project_id, "author-a", 2)

            self.assertEqual(count, 2)
            self.assertEqual(len(db.list_project_posts(project_id)), 2)


if __name__ == "__main__":
    unittest.main()
