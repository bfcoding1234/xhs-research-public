from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.ai_reporting import (
    default_report_prompt_templates,
    report_prompt_template_hash,
)
from xhs_research.collector import CapabilityRegistry, SEARCH_POSTS_BY_KEYWORD
from xhs_research.server import ResearchApplication, create_server
from xhs_research.socai import SocaiClient
from xhs_research.xiaohongshu_cli import XiaohongshuCliClient


class FakeRunner:
    def __init__(self):
        self.collectors = {
            "socai": SocaiClient("socai"),
            "xiaohongshu-cli": XiaohongshuCliClient("xhs"),
        }
        self.capability_registry = CapabilityRegistry(self.collectors)

    def cancel(self, task_id):
        return None


class SettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db = Database(root / "research.sqlite3")
        self.db.initialize()
        settings = SimpleNamespace(
            max_workers=1,
            host="127.0.0.1",
            port=0,
            collector="xiaohongshu-cli",
            collector_bin="/opt/tools/xhs",
            socai_bin="socai",
            xiaohongshu_cli_bin="/opt/tools/xhs",
            codex_bin="codex",
            data_dir=root,
            detail_ttl_days=7,
            author_ttl_days=7,
            max_author_notes=300,
            max_keywords_per_task=5,
            max_authors_per_task=5,
            research_workers=1,
            vision_workers=1,
            report_workers=1,
        )
        self.app = ResearchApplication(settings, self.db, FakeRunner(), root / "dist")
        self.server = create_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/settings"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def post(self, payload):
        request = Request(
            self.url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            return json.load(response)

    def assert_invalid_defaults(self, payload):
        request = Request(
            self.url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        body = json.loads(raised.exception.read())
        self.assertEqual(raised.exception.code, 400)
        self.assertIn("深度分析数量不能大于发现数量", body["error"])

    def test_rejects_partial_discovery_update_below_stored_deep_default(self):
        self.db.set_app_settings({"default_discovery": 50, "default_deep": 20})

        self.assert_invalid_defaults({"default_discovery": 10})

        self.assertEqual(self.db.get_app_settings()["default_discovery"], 50)

    def test_rejects_partial_deep_update_above_stored_discovery_default(self):
        self.db.set_app_settings({"default_discovery": 40, "default_deep": 10})

        self.assert_invalid_defaults({"default_deep": 41})

        self.assertEqual(self.db.get_app_settings()["default_deep"], 10)

    def test_accepts_valid_combined_default_update(self):
        values = self.post({"default_discovery": 25, "default_deep": 25})

        self.assertEqual(values["default_discovery"], 25)
        self.assertEqual(values["default_deep"], 25)

    def test_exposes_and_updates_keyword_author_default_limit(self):
        with urlopen(self.url) as response:
            initial = json.load(response)
        self.assertEqual(initial["default_keyword_author_limit"], 500)

        values = self.post({"default_keyword_author_limit": 720})
        self.assertEqual(values["default_keyword_author_limit"], 720)
        self.assertEqual(self.db.get_app_settings()["default_keyword_author_limit"], 720)

    def test_exposes_codex_image_models_and_updates_vision_processing_settings(self):
        models = [{
            "id": "vision-model",
            "label": "Vision Model",
            "default_reasoning_effort": "medium",
            "reasoning_efforts": ["low", "medium", "high"],
        }]
        with patch("xhs_research.server.list_codex_image_models", return_value=models):
            with urlopen(f"{self.url}/vision-models") as response:
                catalog = json.load(response)
            with urlopen(self.url) as response:
                initial = json.load(response)
            updated = self.post({
                "vision_model": "vision-model",
                "vision_reasoning_effort": "high",
                "vision_timeout_seconds": 900,
            })

        self.assertEqual(catalog, {"available": True, "models": models, "error": ""})
        self.assertEqual(initial["vision_model"], "")
        self.assertEqual(initial["vision_reasoning_effort"], "default")
        self.assertEqual(initial["vision_timeout_seconds"], 600)
        self.assertEqual(updated["vision_model"], "vision-model")
        self.assertEqual(updated["vision_reasoning_effort"], "high")
        self.assertEqual(updated["vision_timeout_seconds"], 900)

    def test_rejects_invalid_vision_model_effort_and_timeout_atomically(self):
        models = [{
            "id": "vision-model",
            "label": "Vision Model",
            "default_reasoning_effort": "medium",
            "reasoning_efforts": ["low", "medium", "high"],
        }]
        invalid_values = [
            {"vision_model": "missing-model"},
            {"vision_model": "vision-model", "vision_reasoning_effort": "ultra"},
            {"vision_timeout_seconds": 30},
            {"vision_model": "", "vision_reasoning_effort": "high"},
        ]
        with patch("xhs_research.server.list_codex_image_models", return_value=models):
            for values in invalid_values:
                with self.subTest(values=values):
                    request = Request(
                        self.url,
                        data=json.dumps(values).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(request)
                    self.assertEqual(raised.exception.code, 400)
        self.assertNotIn("vision_model", self.db.get_app_settings())

    def test_model_catalog_failure_returns_a_diagnostic_payload(self):
        with patch(
            "xhs_research.server.list_codex_image_models",
            side_effect=RuntimeError("catalog unavailable"),
        ):
            with urlopen(f"{self.url}/vision-models") as response:
                value = json.load(response)

        self.assertEqual(value, {
            "available": False,
            "models": [],
            "error": "catalog unavailable",
        })

    def test_exposes_validates_and_updates_post_detail_delay_defaults(self):
        with urlopen(self.url) as response:
            initial = json.load(response)
        self.assertEqual(
            {
                key: initial[key]
                for key in (
                    "post_delay_min_seconds",
                    "post_delay_max_seconds",
                    "batch_delay_min_seconds",
                    "batch_delay_max_seconds",
                )
            },
            {
                "post_delay_min_seconds": 1,
                "post_delay_max_seconds": 3,
                "batch_delay_min_seconds": 2,
                "batch_delay_max_seconds": 5,
            },
        )

        values = self.post({
            "post_delay_min_seconds": 4,
            "post_delay_max_seconds": 6,
            "batch_delay_min_seconds": 12,
            "batch_delay_max_seconds": 24,
        })
        self.assertEqual(values["post_delay_min_seconds"], 4)
        self.assertEqual(values["batch_delay_max_seconds"], 24)

        request = Request(
            self.url,
            data=json.dumps({
                "post_delay_min_seconds": 7,
                "post_delay_max_seconds": 6,
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)
        self.assertIn("帖子间隔最短秒数不能大于最长秒数", json.loads(
            raised.exception.read()
        )["error"])

    def test_exposes_and_updates_xiaohongshu_cookie_source(self):
        with urlopen(self.url) as response:
            initial = json.load(response)
        self.assertEqual(initial["xiaohongshu_cookie_source"], "auto")

        values = self.post({"xiaohongshu_cookie_source": "chrome"})
        self.assertEqual(values["xiaohongshu_cookie_source"], "chrome")
        self.assertEqual(self.db.get_app_settings()["xiaohongshu_cookie_source"], "chrome")

    def test_accepts_research_limits_above_three_hundred(self):
        values = self.post({
            "default_discovery": 1200,
            "default_deep": 900,
            "max_author_notes": 1500,
        })

        self.assertEqual(values["default_discovery"], 1200)
        self.assertEqual(values["default_deep"], 900)
        self.assertEqual(values["max_author_notes"], 1500)

    def test_exposes_and_updates_report_prompt_templates(self):
        with urlopen(self.url) as response:
            initial = json.load(response)
        defaults = default_report_prompt_templates()
        self.assertEqual(initial["report_prompt_templates"], defaults)
        self.assertEqual(initial["report_prompt_defaults"], defaults)
        self.assertEqual(
            initial["report_prompt_template_hash"],
            report_prompt_template_hash(defaults),
        )

        templates = {
            "chunk": "自定义分批 {{allowed_post_ids}}\n{{evidence_json}}",
            "final": "自定义最终 {{user_instructions}}\n{{evidence_json}}",
        }
        updated = self.post({"report_prompt_templates": templates})

        self.assertEqual(updated["report_prompt_templates"], templates)
        self.assertEqual(
            updated["report_prompt_template_hash"],
            report_prompt_template_hash(templates),
        )
        self.assertEqual(self.db.get_app_settings()["report_prompt_templates"], templates)

    def test_rejects_invalid_report_prompt_templates_atomically(self):
        defaults = default_report_prompt_templates()
        self.db.set_app_settings({"report_prompt_templates": defaults})
        invalid_values = [
            {"chunk": "{{evidence_json}}", "final": defaults["final"]},
            {"chunk": defaults["chunk"], "final": "{{unknown}}\n{{evidence_json}}"},
        ]
        for templates in invalid_values:
            with self.subTest(templates=templates):
                request = Request(
                    self.url,
                    data=json.dumps({"report_prompt_templates": templates}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request)
                self.assertEqual(raised.exception.code, 400)
                self.assertEqual(self.db.get_app_settings()["report_prompt_templates"], defaults)

    def test_my_author_must_reference_an_existing_author(self):
        author_id = self.db.upsert_author({
            "author_id": "my-author",
            "display_name": "我的作者",
        })

        values = self.post({"my_author_id": author_id})
        self.assertEqual(values["my_author_id"], author_id)
        self.assertEqual(self.db.get_app_settings()["my_author_id"], author_id)

        request = Request(
            self.url,
            data=json.dumps({"my_author_id": author_id + 999}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)
        self.assertIn("选择的作者不存在", json.loads(raised.exception.read())["error"])
        self.assertEqual(self.db.get_app_settings()["my_author_id"], author_id)

        cleared = self.post({"my_author_id": None})
        self.assertIsNone(cleared["my_author_id"])

    def test_does_not_expose_unknown_legacy_settings(self):
        self.db.set_app_settings({"my_profile_url": "https://example.com/legacy"})

        with urlopen(self.url) as response:
            values = json.load(response)

        self.assertNotIn("my_profile_url", values)

    def test_exposes_and_updates_capability_command_routing(self):
        with urlopen(self.url) as response:
            values = json.load(response)

        self.assertNotIn("collector", values)
        self.assertNotIn("collector_bin", values)
        self.assertEqual(values["routing_mode"], "capability")
        self.assertIn("search_users_by_keyword", [
            route["capability"] for route in values["capability_routes"]
        ])
        self.assertIn("xiaohongshu-cli.search_users_by_keyword", [
            command["id"] for command in values["collector_commands"]
        ])

        updated = self.post({
            "capability_routes": {
                SEARCH_POSTS_BY_KEYWORD: [
                    "xiaohongshu-cli.search_posts_by_keyword",
                    "socai.search_posts_by_keyword",
                ],
            },
        })
        route = next(
            route for route in updated["capability_routes"]
            if route["capability"] == SEARCH_POSTS_BY_KEYWORD
        )
        self.assertEqual(route["commands"], [
            "xiaohongshu-cli.search_posts_by_keyword",
            "socai.search_posts_by_keyword",
        ])
        self.assertEqual(
            self.db.get_app_settings()["capability_routes"][SEARCH_POSTS_BY_KEYWORD][0],
            "xiaohongshu-cli.search_posts_by_keyword",
        )

    def test_rejects_command_mapped_to_wrong_capability(self):
        request = Request(
            self.url,
            data=json.dumps({
                "capability_routes": {
                    SEARCH_POSTS_BY_KEYWORD: ["xiaohongshu-cli.search_users_by_keyword"],
                },
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)
        self.assertIn("does not support", json.loads(raised.exception.read())["error"])


if __name__ == "__main__":
    unittest.main()
