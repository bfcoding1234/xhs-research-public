from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.collector import CapabilityRegistry, DOWNLOAD_MEDIA, SEARCH_POSTS_BY_KEYWORD
from xhs_research.config import Settings
from xhs_research.envcheck import check_environment, installation_plan
from xhs_research.opencli import OpenCliClient, classify_opencli_error


class OpenCliClientTests(unittest.TestCase):
    def test_read_post_detail_uses_saved_note_url(self):
        calls = []

        def executor(args, _env, _timeout, _cancel):
            calls.append(args)
            return [
                {"field": "title", "value": "最新标题"},
                {"field": "content", "value": "完整正文"},
                {"field": "collects", "value": "8"},
            ]

        url = "https://www.xiaohongshu.com/explore/note-direct?xsec_token=saved-token"
        result = OpenCliClient("opencli", executor=executor).read_post_detail({
            "note_id": "note-direct",
            "note_url": url,
            "title": "旧标题",
        })

        self.assertEqual(result["notes"][0]["content"], "完整正文")
        self.assertEqual(result["notes"][0]["favorites_count"], 8)
        self.assertEqual(calls, [["opencli", "xiaohongshu", "note", url, "-f", "json"]])

    def test_keyword_preview_maps_opencli_search_rows(self):
        calls = []

        def executor(args, _env, _timeout, _cancel):
            calls.append(args)
            return [{
                "rank": 1,
                "title": "AI 产品笔记",
                "author": "研究员",
                "likes": "1.2万",
                "published_at": "2026-07-01",
                "url": "https://www.xiaohongshu.com/search_result/abc123?xsec_token=token",
                "author_url": "https://www.xiaohongshu.com/user/profile/author-1",
            }]

        client = OpenCliClient("/opt/opencli", executor=executor)
        result = client.keyword_preview("AI 产品经理", 3, {"sort": "最新", "publish_time": "一月内"})

        self.assertEqual(calls, [[
            "/opt/opencli", "xiaohongshu", "search", "AI 产品经理", "--limit", "3", "-f", "json",
        ]])
        self.assertEqual(result["cards"][0]["note_id"], "abc123")
        self.assertEqual(result["cards"][0]["author_id"], "author-1")
        self.assertEqual(result["cards"][0]["likes_count"], 12000)
        self.assertEqual(len(result["warnings"]), 2)

    def test_author_deep_reads_each_signed_note_url(self):
        calls = []

        def executor(args, _env, _timeout, _cancel):
            calls.append(args)
            if args[2] == "user":
                return [{
                    "id": "note-1",
                    "title": "主页帖子",
                    "likes": "20",
                    "url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=token",
                }]
            return [
                {"field": "title", "value": "完整标题"},
                {"field": "content", "value": "完整正文"},
                {"field": "likes", "value": "21"},
                {"field": "collects", "value": "5"},
                {"field": "comments", "value": "3"},
            ]

        result = OpenCliClient("opencli", executor=executor).author_deep("author-1", 1)

        self.assertEqual(result["profile"]["author_id"], "author-1")
        self.assertEqual(result["notes"][0]["content"], "完整正文")
        self.assertEqual(result["notes"][0]["favorites_count"], 5)
        self.assertEqual(calls[1][2:4], ["note", "https://www.xiaohongshu.com/explore/note-1?xsec_token=token"])

    def test_registry_exposes_opencli_commands_and_default_fallback(self):
        client = OpenCliClient("opencli", executor=lambda *_args: [])
        registry = CapabilityRegistry({"opencli": client})

        self.assertIn("opencli.download_media", registry.commands)
        self.assertEqual(registry.routes[DOWNLOAD_MEDIA], ["opencli.download_media"])
        self.assertEqual(registry.routes[SEARCH_POSTS_BY_KEYWORD], ["opencli.search_posts_by_keyword"])

    def test_opencli_exit_codes_are_classified(self):
        self.assertEqual(classify_opencli_error(77, ""), "login_required")
        self.assertEqual(classify_opencli_error(69, ""), "opencli_browser_unavailable")
        self.assertEqual(classify_opencli_error(75, ""), "opencli_timeout")

    def test_environment_accepts_opencli_and_offers_official_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(data_dir=Path(temp_dir))
            paths = {"opencli": "/opt/opencli", "chrome": "/opt/chrome"}
            result = check_environment(
                settings,
                resolver=lambda name: paths.get(name),
                version_reader=lambda path: "1.8.6" if path == "/opt/opencli" else "",
                port_probe=lambda *_args: True,
            )

        self.assertEqual(result["ready_collectors"], ["opencli"])
        self.assertTrue(result["ready_for_collection"])
        self.assertTrue(result["dependencies"]["opencli"]["requires_browser_bridge"])
        plan = installation_plan(missing=["opencli"])
        self.assertEqual(plan["commands"]["opencli"], "npm install -g @jackwener/opencli")
        self.assertIn("Browser Bridge", plan["notes"]["opencli"])


if __name__ == "__main__":
    unittest.main()
