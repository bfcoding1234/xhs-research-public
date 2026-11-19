import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.ai_reporting import CodexReportError, CodexReportProvider
from xhs_research.codex_process import CodexProcessCancelled, run_codex_process
from xhs_research.keyword_generation import CodexKeywordProvider, KeywordGenerationError
from xhs_research.vision import CodexVisionProvider


class CodexProviderProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.binary = self.root / "fake-codex"
        self.binary.write_text(
            "#!/bin/sh\n"
            "printf '%s' \"$$\" > \"$FAKE_CODEX_PID_FILE\"\n"
            "sleep 30\n",
            encoding="utf-8",
        )
        self.binary.chmod(0o755)
        self.image = self.root / "image.jpg"
        self.image.write_bytes(b"fake image")
        self.vision_schema = WORKBENCH_ROOT / "xhs_research" / "vision-schema.json"
        self.vision_batch_schema = WORKBENCH_ROOT / "xhs_research" / "vision-batch-schema.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def providers(self, timeout):
        return {
            "vision": CodexVisionProvider(self.binary, work_dir=self.root, timeout=timeout),
            "vision_batch": CodexVisionProvider(self.binary, work_dir=self.root, timeout=timeout),
            "report": CodexReportProvider(self.binary, work_dir=self.root, timeout=timeout),
            "keyword": CodexKeywordProvider(self.binary, work_dir=self.root, timeout=timeout),
        }

    def invoke(self, name, provider, should_cancel=None):
        if name == "vision":
            return provider.analyze("标题", [str(self.image)], self.vision_schema, should_cancel=should_cancel)
        if name == "vision_batch":
            return provider.analyze_batch(
                [{"post_id": 1, "title": "标题", "image_paths": [str(self.image)]}],
                self.vision_batch_schema,
                should_cancel=should_cancel,
            )
        if name == "report":
            return provider.generate(
                {"id": 7, "name": "项目"},
                {
                    "report_context": {"label": "概览"},
                    "statistics": {"post_count": 1},
                    "authors": [],
                    "posts": [{"post_id": 1, "title": "标题"}],
                },
                should_cancel=should_cancel,
            )
        if name == "keyword":
            return provider.generate(
                {"id": 7, "name": "项目", "description": "说明"},
                ["参考词"],
                ["已有词"],
                should_cancel=should_cancel,
            )
        raise AssertionError(f"Unknown provider: {name}")

    def assert_process_gone(self, pid_file):
        pid = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"Codex process {pid} was left running")

    def assert_no_provider_output(self):
        self.assertEqual(list(self.root.glob("vision-*.json")), [])
        self.assertEqual(list(self.root.glob("ai-report-*.md")), [])
        self.assertEqual(list(self.root.glob("report-*.out")), [])
        self.assertEqual(list(self.root.glob("keywords-*.json")), [])

    def test_all_providers_cancel_running_codex_process_and_remove_output(self):
        for name, provider in self.providers(timeout=5).items():
            with self.subTest(provider=name):
                pid_file = self.root / f"{name}-cancel.pid"
                with patch.dict(os.environ, {"FAKE_CODEX_PID_FILE": str(pid_file)}):
                    with self.assertRaises(CodexProcessCancelled):
                        self.invoke(name, provider, should_cancel=pid_file.exists)
                self.assertTrue(pid_file.exists())
                self.assert_process_gone(pid_file)
                self.assert_no_provider_output()

    def test_all_providers_timeout_and_do_not_leave_codex_process_or_output(self):
        for name, provider in self.providers(timeout=3).items():
            with self.subTest(provider=name):
                pid_file = self.root / f"{name}-timeout.pid"
                with patch.dict(os.environ, {"FAKE_CODEX_PID_FILE": str(pid_file)}):
                    expected = (
                        CodexReportError
                        if name == "report"
                        else (KeywordGenerationError if name == "keyword" else subprocess.TimeoutExpired)
                    )
                    with self.assertRaises(expected):
                        self.invoke(name, provider)
                self.assertTrue(pid_file.exists())
                self.assert_process_gone(pid_file)
                self.assert_no_provider_output()

    def test_timeout_escalates_from_terminate_to_kill_for_an_unresponsive_process(self):
        pid_file = self.root / "ignore-term.pid"
        code = (
            "import os, signal, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "open(sys.argv[1], 'w').write(str(os.getpid())); "
            "time.sleep(30)"
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            run_codex_process(
                [sys.executable, "-c", code, str(pid_file)],
                "",
                timeout=0.2,
                poll_interval=0.02,
                terminate_grace=0.05,
            )

        self.assertTrue(pid_file.exists())
        self.assert_process_gone(pid_file)


if __name__ == "__main__":
    unittest.main()
