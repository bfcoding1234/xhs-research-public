import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.collector import CollectorError
from xhs_research.config import Settings, load_settings
from xhs_research.envcheck import check_environment, installation_plan
from xhs_research.xiaohongshu_cli import XiaohongshuCliClient, _execute


class FakeExecutor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def __call__(self, command, env, timeout, should_cancel=lambda: False):
        self.commands.append((command, env, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CollectorConfigurationTests(unittest.TestCase):
    def test_environment_selects_xiaohongshu_cli_and_binary(self):
        with patch.dict(os.environ, {
            "XHS_RESEARCH_COLLECTOR": "xiaohongshu-cli",
            "XIAOHONGSHU_CLI_BIN": "/opt/tools/xhs",
        }, clear=True):
            settings = load_settings()

        self.assertEqual(settings.collector, "xiaohongshu-cli")
        self.assertEqual(settings.collector_bin, "/opt/tools/xhs")

    def test_short_xhs_alias_is_normalized(self):
        self.assertEqual(Settings(collector="xhs").collector, "xiaohongshu-cli")

    def test_unknown_collector_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "XHS_RESEARCH_COLLECTOR"):
            Settings(collector="unknown")

    def test_environment_check_accepts_any_available_provider_for_capability_routing(self):
        settings = Settings(data_dir=ROOT, collector="xiaohongshu-cli")
        paths = {
            "socai": None,
            "xiaohongshu-cli": "/opt/xhs",
            "codex": None,
            "chrome": "/opt/chrome",
        }
        result = check_environment(
            settings,
            resolver=paths.get,
            version_reader=lambda path: "xhs, version 0.6.4" if path == "/opt/xhs" else "",
            port_probe=lambda host, port: True,
        )

        self.assertTrue(result["ready_for_collection"])
        self.assertFalse(result["dependencies"]["socai"]["required"])
        self.assertFalse(result["dependencies"]["xiaohongshu-cli"]["required"])
        self.assertEqual(result["routing_mode"], "capability")

    def test_auto_environment_is_ready_when_at_least_one_provider_is_available(self):
        settings = Settings(data_dir=ROOT, collector="auto")
        paths = {
            "socai": None,
            "xiaohongshu-cli": "/opt/xhs",
            "codex": None,
            "chrome": "/opt/chrome",
        }
        result = check_environment(
            settings,
            resolver=paths.get,
            version_reader=lambda path: "xhs, version 0.6.4" if path == "/opt/xhs" else "",
            port_probe=lambda host, port: True,
        )

        self.assertTrue(result["ready_for_collection"])
        self.assertEqual(result["ready_collectors"], ["xiaohongshu-cli"])
        self.assertFalse(result["dependencies"]["socai"]["required"])
        self.assertFalse(result["dependencies"]["xiaohongshu-cli"]["required"])

    def test_installation_plan_uses_official_package_name(self):
        plan = installation_plan(missing=["xiaohongshu-cli"])
        self.assertIn("xiaohongshu-cli", plan["commands"]["xiaohongshu-cli"])


class XiaohongshuCliClientTests(unittest.TestCase):
    def test_read_post_detail_uses_saved_note_id_and_security_token(self):
        executor = FakeExecutor([{
            "items": [{
                "id": "note-direct",
                "note_card": {
                    "title": "直接读取的帖子",
                    "desc": "完整正文",
                    "interact_info": {"liked_count": "9", "collected_count": "2", "comment_count": "1"},
                },
            }],
        }])
        client = XiaohongshuCliClient("xhs", executor=executor)

        result = client.read_post_detail({
            "note_id": "note-direct",
            "note_url": "https://www.xiaohongshu.com/explore/note-direct?xsec_token=saved-token&xsec_source=pc_feed",
            "title": "旧标题",
        })

        self.assertEqual(result["notes"][0]["content"], "完整正文")
        self.assertEqual(executor.commands[0][0], [
            "xhs", "--cookie-source", "auto", "read", "note-direct", "--xsec-token", "saved-token", "--json",
        ])

    def test_search_users_maps_profiles_and_applies_limit(self):
        executor = FakeExecutor([{
            "user_info_dtos": [
                {
                    "user_base_dto": {
                        "user_id": "author-1", "red_id": "red-1",
                        "user_nickname": "AI 产品经理", "desc": "分享 AI 产品实践",
                        "image": {"url_default": "https://example.com/avatar-1.jpg"},
                    },
                    "fans_total": "1.2万",
                },
                {"user_base_dto": {"user_id": "author-2", "user_nickname": "第二位"}},
            ],
        }])
        client = XiaohongshuCliClient("/opt/xhs", executor=executor)

        result = client.search_users_by_keyword("AI 产品经理", 1)

        self.assertEqual(len(result["profiles"]), 1)
        self.assertEqual(result["profiles"][0]["author_id"], "author-1")
        self.assertEqual(result["profiles"][0]["followers_count"], 12000)
        self.assertEqual(result["profiles"][0]["discovery_keyword"], "AI 产品经理")
        self.assertEqual(executor.commands[0][0], [
            "/opt/xhs", "--cookie-source", "auto", "search-user", "AI 产品经理", "--json",
        ])

    def test_search_users_fetches_additional_pages_and_deduplicates(self):
        def entries(start, end):
            return [
                {"user_base_dto": {"user_id": f"author-{index}", "user_nickname": f"作者 {index}"}}
                for index in range(start, end)
            ]

        executor = FakeExecutor([
            {"user_info_dtos": entries(1, 21)},
            {"user_info_dtos": entries(20, 40)},
        ])
        client = XiaohongshuCliClient(sys.executable, executor=executor)

        result = client.search_users_by_keyword("AI 产品经理", 30)

        self.assertEqual(len(result["profiles"]), 30)
        self.assertEqual(result["profiles"][0]["author_id"], "author-1")
        self.assertEqual(result["profiles"][-1]["author_id"], "author-30")
        self.assertEqual(len({profile["author_id"] for profile in result["profiles"]}), 30)
        self.assertEqual(executor.commands[0][0], [
            sys.executable, "--cookie-source", "auto", "search-user", "AI 产品经理", "--json",
        ])
        second_command = executor.commands[1][0]
        self.assertEqual(second_command[0], sys.executable)
        self.assertEqual(second_command[-4:], ["AI 产品经理", "2", "20", "auto"])

    def test_keyword_preview_maps_search_envelope_to_collector_cards(self):
        executor = FakeExecutor([{
            "items": [{
                "id": "note-1",
                "xsec_token": "token-1",
                "note_card": {
                    "display_title": "AI 产品经理的一天",
                    "type": "normal",
                    "user": {"user_id": "author-1", "nickname": "测试作者"},
                    "interact_info": {"liked_count": "1.2万"},
                    "cover": {"url_default": "https://sns-webpic-qc.xhscdn.com/cover.webp"},
                },
            }],
            "has_more": False,
        }])
        client = XiaohongshuCliClient("/opt/xhs", executor=executor)

        raw = client.keyword_preview(
            "AI 产品经理", 10, {"sort": "最热", "publish_time": "一周内"}, True,
        )
        result = client.normalize_result(raw, "keyword", "AI 产品经理")

        self.assertEqual(result["cards"][0]["note_id"], "note-1")
        self.assertEqual(result["cards"][0]["likes_count"], 12000)
        self.assertEqual(result["cards"][0]["source_type"], "keyword")
        self.assertIn("xsec_token=token-1", result["cards"][0]["url"])
        self.assertIn("暂不支持发布时间筛选", result["warnings"][0])
        command, env, _ = executor.commands[0]
        self.assertEqual(command, [
            "/opt/xhs", "--cookie-source", "auto", "search", "AI 产品经理", "--sort", "popular", "--page", "1", "--json",
        ])
        self.assertEqual(env["OUTPUT"], "json")

    def test_keyword_preview_skips_hot_queries_and_keeps_fetching_real_notes(self):
        executor = FakeExecutor([
            {
                "items": [{
                    "id": "00000000-0000-4000-8000-000000000001#1700000000000",
                    "model_type": "hot_query",
                    "hot_query": {"title": "相关搜索"},
                    "xsec_token": "not-a-note-token",
                }],
                "has_more": True,
            },
            {
                "items": [{
                    "id": "100000000000000000000003",
                    "model_type": "note",
                    "xsec_token": "note-token",
                    "note_card": {
                        "display_title": "真实帖子",
                        "type": "normal",
                        "user": {"user_id": "author-1", "nickname": "测试作者"},
                    },
                }],
                "has_more": False,
            },
        ])
        client = XiaohongshuCliClient("/opt/xhs", executor=executor)

        result = client.keyword_preview("Workbody工作台", 1)

        self.assertEqual([card["note_id"] for card in result["cards"]], [
            "100000000000000000000003",
        ])
        self.assertEqual(len(executor.commands), 2)

    def test_card_rejects_url_delimiters_even_without_a_model_type(self):
        client = XiaohongshuCliClient("/opt/xhs", executor=FakeExecutor([]))

        self.assertIsNone(client._card({
            "id": "00000000-0000-4000-8000-000000000001#1700000000000",
            "note_card": {"display_title": "不是帖子"},
        }))

    def test_author_deep_combines_profile_posts_and_details(self):
        executor = FakeExecutor([
            {
                "basic_info": {
                    "user_id": "author-1", "red_id": "red-1", "nickname": "测试作者",
                    "desc": "简介", "ip_location": "上海",
                },
                "interactions": [
                    {"type": "fans", "count": "2.5万"},
                    {"type": "follows", "count": "88"},
                    {"type": "interaction", "count": "10万"},
                    {"type": "notes", "count": "1000"},
                ],
            },
            {
                "notes": [{
                    "note_id": "note-2",
                    "display_title": "作者帖子",
                    "user": {"user_id": "author-1", "nickname": "测试作者"},
                    "interact_info": {"liked_count": "30"},
                }],
                "has_more": False,
                "cursor": "",
            },
            {
                "items": [{
                    "id": "note-2",
                    "note_card": {
                        "title": "作者帖子",
                        "desc": "完整正文",
                        "user": {"user_id": "author-1", "nickname": "测试作者"},
                        "interact_info": {
                            "liked_count": "30", "collected_count": "6", "comment_count": "4",
                        },
                        "image_list": [{"url_default": "https://sns-webpic-qc.xhscdn.com/2.webp"}],
                    },
                }],
            },
        ])
        client = XiaohongshuCliClient("xhs", executor=executor)

        result = client.normalize_result(client.author_deep("author-1", 5), "author", "author-1")

        self.assertEqual(result["profile"]["display_name"], "测试作者")
        self.assertEqual(result["profile"]["followers_count"], 25000)
        self.assertEqual(result["profile"]["total_post_count"], 1000)
        self.assertEqual(result["notes"][0]["content"], "完整正文")
        self.assertEqual(result["notes"][0]["favorites_count"], 6)
        self.assertEqual(result["notes"][0]["comments_count"], 4)
        self.assertEqual(result["notes"][0]["images"][0]["url"], "https://sns-webpic-qc.xhscdn.com/2.webp")

    def test_read_author_profile_does_not_request_posts(self):
        executor = FakeExecutor([{
            "basic_info": {
                "user_id": "author-1",
                "red_id": "red-1",
                "nickname": "更新后的作者",
                "desc": "新简介",
            },
            "interactions": [{"type": "fans", "count": "1.2万"}],
        }])
        client = XiaohongshuCliClient("xhs", executor=executor)

        result = client.read_author_profile("author-1")

        self.assertEqual(result["profile"]["display_name"], "更新后的作者")
        self.assertEqual(result["profile"]["followers_count"], 12000)
        self.assertEqual(result["cards"], [])
        self.assertEqual(executor.commands[0][0], [
            "xhs", "--cookie-source", "auto", "user", "author-1", "--json",
        ])

    def test_task_scope_refreshes_and_requires_a_non_guest_login(self):
        executor = FakeExecutor([
            {"authenticated": True, "user": {"guest": False, "nickname": "已登录用户"}},
            {"basic_info": {"user_id": "author-1", "nickname": "更新后的作者"}},
        ])
        client = XiaohongshuCliClient("xhs", executor=executor, cookie_source="chrome")

        with client.cancellation_scope(lambda: False):
            result = client.read_author_profile("author-1")

        self.assertEqual(result["profile"]["display_name"], "更新后的作者")
        self.assertEqual(executor.commands[0][0], [
            "xhs", "--cookie-source", "chrome", "login", "--json",
        ])
        self.assertEqual(executor.commands[1][0], [
            "xhs", "--cookie-source", "chrome", "user", "author-1", "--json",
        ])
        self.assertEqual(client.consume_login_verification(), {
            "provider": "xiaohongshu-cli", "cookie_source": "chrome",
        })

    def test_task_scope_rejects_guest_login_without_calling_the_data_command(self):
        executor = FakeExecutor([
            {"authenticated": True, "user": {"guest": True, "nickname": "Unknown"}},
        ])
        client = XiaohongshuCliClient("xhs", executor=executor)

        with self.assertRaisesRegex(CollectorError, "登录态无效") as raised:
            with client.cancellation_scope(lambda: False):
                client.read_author_profile("author-1")

        self.assertEqual(raised.exception.code, "login_required")
        self.assertEqual(len(executor.commands), 1)

    def test_non_auth_detail_error_becomes_partial_note(self):
        executor = FakeExecutor([
            {"items": [{"id": "note-3", "note_card": {"title": "帖子"}}], "has_more": False},
            CollectorError("详情接口失败", "api_error"),
        ])
        client = XiaohongshuCliClient("xhs", executor=executor)

        result = client.normalize_result(client.keyword_deep("测试", 1), "keyword", "测试")

        self.assertFalse(result["notes"][0]["_collector_ok"])
        self.assertEqual(result["notes"][0]["_collector_error"], "详情接口失败")

    def test_auth_error_remains_recoverable(self):
        payload = {
            "ok": False,
            "schema_version": "1",
            "error": {"code": "not_authenticated", "message": "need login"},
        }
        command = [
            sys.executable,
            "-c",
            "import json,sys; print(json.dumps(" + repr(payload) + ")); raise SystemExit(1)",
        ]

        with self.assertRaises(CollectorError) as raised:
            _execute(command, os.environ.copy(), 30)

        self.assertEqual(raised.exception.code, "login_required")

    def test_execute_requires_stable_schema_envelope(self):
        command = [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'ok': True, 'schema_version': '2', 'data': {}}))",
        ]

        with self.assertRaises(CollectorError) as raised:
            _execute(command, os.environ.copy(), 30)

        self.assertEqual(raised.exception.code, "xiaohongshu_cli_schema")


if __name__ == "__main__":
    unittest.main()
