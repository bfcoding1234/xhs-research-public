import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENTRY_PATH = SKILL_ROOT / "scripts" / "xhs_research.py"
WORKBENCH_ROOT = SKILL_ROOT / "scripts" / "workbench"


def load_entry():
    spec = importlib.util.spec_from_file_location("xhs_research_entry", ENTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AppRootTests(unittest.TestCase):
    def test_defaults_to_workbench_bundled_with_skill(self):
        entry = load_entry()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(entry.app_root(), WORKBENCH_ROOT)

    def test_valid_explicit_app_dir_overrides_bundled_workbench(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "xhs_research"
            package.mkdir()
            (package / "cli.py").write_text("", encoding="utf-8")
            with patch.dict(os.environ, {"XHS_RESEARCH_APP_DIR": str(root)}, clear=True):
                self.assertEqual(entry.app_root(), root)

    def test_invalid_explicit_app_dir_is_reported(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"
            with patch.dict(os.environ, {"XHS_RESEARCH_APP_DIR": str(missing)}, clear=True):
                with self.assertRaisesRegex(SystemExit, "XHS_RESEARCH_APP_DIR"):
                    entry.app_root()

    def test_bundled_workbench_exposes_cli(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WORKBENCH_ROOT)
        result = subprocess.run(
            [sys.executable, "-m", "xhs_research", "--help"],
            cwd=WORKBENCH_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("serve", result.stdout)


class DevelopmentIsolationTests(unittest.TestCase):
    def test_git_file_identifies_a_linked_worktree(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").write_text("gitdir: /tmp/example\n", encoding="utf-8")
            self.assertTrue(entry._is_linked_worktree(root))

    def test_git_directory_identifies_the_primary_worktree(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            self.assertFalse(entry._is_linked_worktree(root))

    def test_linked_development_worktree_defaults_to_an_isolated_runtime(self):
        entry = load_entry()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            entry, "_is_linked_worktree", return_value=True,
        ):
            entry.configure_development_defaults()
            self.assertEqual(os.environ["XHS_RESEARCH_PORT"], "4319")
            self.assertEqual(
                Path(os.environ["XHS_RESEARCH_DATA_DIR"]),
                Path.home() / "Documents/Codex/xhs-research-data-develop",
            )

    def test_primary_worktree_keeps_release_defaults(self):
        entry = load_entry()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            entry, "_is_linked_worktree", return_value=False,
        ):
            entry.configure_development_defaults()
            self.assertNotIn("XHS_RESEARCH_PORT", os.environ)
            self.assertNotIn("XHS_RESEARCH_DATA_DIR", os.environ)
            self.assertEqual(
                entry.configured_data_dir(),
                Path.home() / "Documents/Codex/xhs-research-data",
            )

    def test_explicit_development_configuration_is_not_overridden(self):
        entry = load_entry()
        with patch.dict(
            os.environ,
            {"XHS_RESEARCH_PORT": "4519", "XHS_RESEARCH_DATA_DIR": "/tmp/xhs-shared"},
            clear=True,
        ), patch.object(entry, "_is_linked_worktree", return_value=True):
            entry.configure_development_defaults()
            self.assertEqual(os.environ["XHS_RESEARCH_PORT"], "4519")
            self.assertEqual(os.environ["XHS_RESEARCH_DATA_DIR"], "/tmp/xhs-shared")

    def test_start_refuses_an_old_service_or_another_port_using_the_same_data(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"XHS_RESEARCH_PORT": "4320", "XHS_RESEARCH_DATA_DIR": temp_dir},
            clear=True,
        ), patch.object(entry, "configure_development_defaults"), patch.object(
            entry,
            "service_health",
            side_effect=lambda port=None: (
                None if port in (None, 4320)
                else {"status": "ok", "data_dir": temp_dir} if port == 4318
                else None
            ),
        ), self.assertRaisesRegex(SystemExit, "同一数据目录"):
            entry.start_service()

    def test_health_requires_current_contract_lock_and_matching_canonical_data(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"XHS_RESEARCH_DATA_DIR": temp_dir}, clear=True,
        ):
            self.assertFalse(entry.compatible_health({"status": "ok", "data_dir": temp_dir}))
            self.assertFalse(entry.compatible_health({
                "status": "ok", "api_contract": 2, "runtime_locking": False,
                "data_dir": temp_dir,
            }))
            self.assertTrue(entry.compatible_health({
                "status": "ok", "api_contract": 2, "runtime_locking": True,
                "data_dir": str(Path(temp_dir) / "."), "routing_mode": "capability",
            }))

    def test_health_requires_capability_routing_and_ignores_legacy_collector(self):
        entry = load_entry()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"XHS_RESEARCH_DATA_DIR": temp_dir, "XHS_RESEARCH_COLLECTOR": "xiaohongshu-cli"},
            clear=True,
        ):
            health = {
                "status": "ok", "api_contract": 2, "runtime_locking": True,
                "data_dir": temp_dir,
            }
            self.assertFalse(entry.compatible_health({**health, "collector": "socai"}))
            self.assertTrue(entry.compatible_health({
                **health, "collector": "socai", "routing_mode": "capability",
            }))


class CreateAuthorParserTests(unittest.TestCase):
    def test_create_author_accepts_repeated_profile_urls_without_image_options(self):
        entry = load_entry()
        args = entry.parser().parse_args([
            "create-author", "--name", "多作者项目",
            "--profile-url", "https://www.xiaohongshu.com/user/profile/a",
            "--profile-url", "https://www.xiaohongshu.com/user/profile/b",
        ])

        self.assertEqual(len(args.profile_url), 2)
        self.assertFalse(hasattr(args, "analysis"))
        self.assertFalse(hasattr(args, "vision_count"))


class InitialProjectCleanupTests(unittest.TestCase):
    def setUp(self):
        self.entry = load_entry()

    def test_failed_initial_task_removes_only_a_confirmed_empty_project(self):
        calls = []

        def fake_api(path, method="GET", payload=None, timeout=15):
            calls.append((path, method))
            if path == "/api/projects" and method == "POST":
                return {"id": 41, "name": "临时项目"}
            if path == "/api/tasks" and method == "POST":
                raise SystemExit("task rejected")
            if path == "/api/projects/41/tasks":
                return []
            if path == "/api/projects/41?require_empty=true" and method == "DELETE":
                return {"deleted_project_id": 41}
            raise AssertionError((path, method, payload))

        args = type("Args", (), {
            "name": "临时项目", "keyword": ["AI"], "sort": "综合",
            "publish_time": "半年内", "discovery": 50, "deep": 0,
        })()
        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(
            self.entry, "api", side_effect=fake_api,
        ), self.assertRaises(SystemExit):
            self.entry.create_project_and_task(args, "keyword")

        self.assertIn(("/api/projects/41?require_empty=true", "DELETE"), calls)

    def test_ambiguous_initial_task_response_never_deletes_a_project_with_a_task(self):
        deleted = []

        def fake_api(path, method="GET", payload=None, timeout=15):
            if path == "/api/projects" and method == "POST":
                return {"id": 42, "name": "保留项目"}
            if path == "/api/tasks" and method == "POST":
                raise SystemExit("response lost")
            if path == "/api/projects/42/tasks":
                return [{"id": "task-created"}]
            if method == "DELETE":
                deleted.append(path)
            return {}

        args = type("Args", (), {
            "name": "保留项目", "keyword": ["AI"], "sort": "综合",
            "publish_time": "半年内", "discovery": 50, "deep": 0,
        })()
        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(
            self.entry, "api", side_effect=fake_api,
        ), self.assertRaises(SystemExit):
            self.entry.create_project_and_task(args, "keyword")
        self.assertEqual(deleted, [])


class UpdateProjectTests(unittest.TestCase):
    def setUp(self):
        self.entry = load_entry()
        self.args = type("Args", (), {"project_id": 7, "source_task_id": None, "confirm": False})()
        self.latest = {
            "id": "task_latest",
            "task_type": "research",
            "created_at": "2026-07-11T10:00:00+00:00",
            "input_json": {"mode": "keyword", "source": {"keywords": ["AI 产品经理"]}},
        }

    def test_update_without_confirmation_only_returns_latest_configuration(self):
        calls = []

        def fake_api(path, method="GET", payload=None, timeout=15):
            calls.append((path, method, payload))
            if path == "/api/projects/7":
                return {"id": 7, "name": "示例项目"}
            if path == "/api/projects/7/tasks":
                return [self.latest]
            raise AssertionError(f"unexpected request: {path}")

        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(self.entry, "api", side_effect=fake_api):
            result = self.entry.update_project(self.args)

        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["configuration_source"]["task_id"], "task_latest")
        self.assertEqual(result["configuration"]["mode"], "keyword")
        self.assertEqual(result["configuration_summary"]["discovery"], 50)
        self.assertEqual(result["configuration_summary"]["deep"], 0)
        self.assertNotIn(("/api/projects/7/run", "POST", {}), calls)
        self.assertIn("--source-task-id task_latest --confirm", result["confirm_command"])

    def test_mixed_update_preview_summarizes_keyword_and_author_limits(self):
        self.latest["input_json"] = {
            "mode": "mixed", "topic": "AI 产品经理", "source": {
                "keywords": ["AI 产品经理博主"], "author_ids": ["author-a"],
                "filters": {"sort": "综合", "publish_time": "半年内"},
            },
            "keyword_limits": {"discovery": 12, "deep": 3},
            "author_limits": {"discovery": 60, "deep": 5},
        }

        def fake_api(path, method="GET", payload=None, timeout=15):
            if path == "/api/projects/7":
                return {"id": 7, "name": "综合示例项目"}
            if path == "/api/projects/7/tasks":
                return [self.latest]
            raise AssertionError(f"unexpected request: {path}")

        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(self.entry, "api", side_effect=fake_api):
            result = self.entry.update_project(self.args)

        summary = result["configuration_summary"]
        self.assertEqual(summary["keyword_discovery"], 12)
        self.assertEqual(summary["keyword_deep"], 3)
        self.assertEqual(summary["author_discovery"], 60)
        self.assertEqual(summary["author_deep"], 5)

    def test_update_after_confirmation_creates_task_from_latest_configuration(self):
        self.args.confirm = True
        self.args.source_task_id = "task_latest"

        def fake_api(path, method="GET", payload=None, timeout=15):
            if path == "/api/projects/7":
                return {"id": 7, "name": "示例项目"}
            if path == "/api/projects/7/tasks":
                return [self.latest]
            if path == "/api/projects/7/run" and method == "POST" and payload == {"source_task_id": "task_latest", "created_from": "codex"}:
                return {"id": "task_new", "status": "queued", "url": "http://example/tasks/task_new"}
            raise AssertionError(f"unexpected request: {path}")

        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(self.entry, "api", side_effect=fake_api):
            result = self.entry.update_project(self.args)

        self.assertFalse(result["confirmation_required"])
        self.assertEqual(result["task_id"], "task_new")
        self.assertEqual(result["configuration_source_task_id"], "task_latest")

    def test_update_confirmation_requires_the_reviewed_source_task(self):
        self.args.confirm = True
        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(
            self.entry,
            "api",
            side_effect=[{"id": 7, "name": "示例项目"}, [self.latest]],
        ):
            with self.assertRaisesRegex(SystemExit, "--source-task-id"):
                self.entry.update_project(self.args)

    def test_update_ignores_non_research_tasks(self):
        ai_report = {
            "id": "task_report",
            "task_type": "ai_report",
            "created_at": "2026-07-11T11:00:00+00:00",
            "input_json": {"operation": "ai_report", "mode": "keyword"},
        }

        def fake_api(path, method="GET", payload=None, timeout=15):
            if path == "/api/projects/7":
                return {"id": 7, "name": "示例项目"}
            if path == "/api/projects/7/tasks":
                return [ai_report, self.latest]
            raise AssertionError(f"unexpected request: {path}")

        with patch.object(self.entry, "is_healthy", return_value=True), patch.object(self.entry, "api", side_effect=fake_api):
            result = self.entry.update_project(self.args)

        self.assertEqual(result["configuration_source"]["task_id"], "task_latest")


class CancelTaskTests(unittest.TestCase):
    def test_cancel_command_calls_unified_service(self):
        entry = load_entry()
        args = type("Args", (), {"task_id": "task_stuck"})()
        with patch.object(entry, "is_healthy", return_value=True), patch.object(
            entry,
            "api",
            return_value={"id": "task_stuck", "status": "cancelled"},
        ) as api:
            result = entry.cancel_task(args)

        api.assert_called_once_with("/api/tasks/task_stuck/cancel", "POST", {})
        self.assertEqual(result["status"], "cancelled")


class EnhanceVisionTests(unittest.TestCase):
    def test_preview_returns_confirmation_without_creating_task(self):
        entry = load_entry()
        args = type("Args", (), {"project_id": 7, "confirm": False})()

        def fake_api(path, method="GET", payload=None, timeout=15):
            if path == "/api/projects/7":
                return {"id": 7, "name": "示例项目"}
            if path == "/api/projects/7/vision-status":
                return {"available_posts": 10, "analyzed_posts": 2, "pending_posts": 8, "provider_available": True}
            if path == "/api/settings":
                return {"vision_analysis_mode": "vision-selective", "vision_analysis_ratio": 0.2, "vision_analysis_count": 3, "vision_analysis_max_count": 30}
            raise AssertionError(f"unexpected request: {path}")

        with patch.object(entry, "is_healthy", return_value=True), patch.object(entry, "api", side_effect=fake_api):
            result = entry.enhance_vision(args)

        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["vision_status"]["pending_posts"], 8)
        self.assertEqual(result["configuration"]["vision_max_count"], 30)
        self.assertIn("enhance-vision --project-id 7 --confirm", result["confirm_command"])


if __name__ == "__main__":
    unittest.main()
