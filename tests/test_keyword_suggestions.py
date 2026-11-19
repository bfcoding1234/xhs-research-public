from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.codex_process import CodexProcessCancelled
from xhs_research.db import Database
from xhs_research.keyword_generation import CodexKeywordProvider
from xhs_research.server import ResearchApplication, create_server


class NoopRunner:
    def cancel(self, _task_id):
        return None


class RecordingKeywordProvider:
    model = "fake-model"
    prompt_version = "keyword-test"

    def __init__(self):
        self.calls = []

    def generate(
        self,
        project,
        reference_keywords,
        existing_keywords,
        should_cancel=None,
    ):
        self.calls.append({
            "project": project,
            "reference_keywords": list(reference_keywords),
            "existing_keywords": list(existing_keywords),
        })
        return {
            "keywords": [{
                "keyword": "AI 需求分析",
                "category": "使用场景",
                "reason": "发现具体工作实践",
            }],
            "model": self.model,
            "prompt_version": self.prompt_version,
        }


class BlockingKeywordProvider(RecordingKeywordProvider):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def generate(
        self,
        project,
        reference_keywords,
        existing_keywords,
        should_cancel=None,
    ):
        self.started.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if should_cancel and should_cancel():
                raise CodexProcessCancelled("cancelled")
            time.sleep(0.01)
        raise AssertionError("keyword generation was not cancelled")


class KeywordSuggestionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.web = root / "dist"
        self.web.mkdir()
        (self.web / "index.html").write_text("<div>test</div>", encoding="utf-8")
        self.db = Database(root / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project(
            "AI 产品经理",
            "keyword",
            {},
            "研究 AI 对产品经理工作的影响",
        )
        self.db.add_project_keywords(
            self.project_id,
            ["产品经理转型"],
            source="manual",
        )
        self.db.add_project_keywords(
            self.project_id,
            ["AI 工作流"],
            source="ai_generated",
        )
        self.provider = RecordingKeywordProvider()
        settings = SimpleNamespace(
            max_workers=1,
            host="127.0.0.1",
            port=0,
            socai_bin="socai",
            codex_bin="codex",
            detail_ttl_days=30,
            author_ttl_days=7,
            max_author_notes=300,
            data_dir=root,
        )
        self.app = ResearchApplication(
            settings,
            self.db,
            NoopRunner(),
            self.web,
            keyword_provider=self.provider,
        )
        self.server = create_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.executor.shutdown(wait=True, cancel_futures=True)
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {} if payload is None else {"Content-Type": "application/json"}
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def wait_for_task(self, task_id, status="completed"):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            response_status, task = self.request("GET", f"/api/tasks/{task_id}")
            if response_status == 200 and task["status"] == status:
                return task
            time.sleep(0.02)
        self.fail(f"task {task_id} did not reach {status}")

    def test_generates_from_selected_sources_and_deduplicates_against_all_existing(self):
        status, result = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keyword-suggestions",
            {"reference_sources": ["manual"]},
        )

        self.assertEqual(status, 202)
        task = self.wait_for_task(result["id"])
        suggestions = task["result_json"]["keyword_suggestions"]
        self.assertEqual(suggestions["request_id"], result["id"])
        self.assertEqual(suggestions["reference_sources"], ["manual"])
        self.assertEqual(suggestions["keywords"][0]["keyword"], "AI 需求分析")
        self.assertEqual(self.provider.calls[0]["project"]["name"], "AI 产品经理")
        self.assertEqual(
            self.provider.calls[0]["project"]["description"],
            "研究 AI 对产品经理工作的影响",
        )
        self.assertEqual(
            self.provider.calls[0]["reference_keywords"],
            ["产品经理转型"],
        )
        self.assertCountEqual(
            self.provider.calls[0]["existing_keywords"],
            ["产品经理转型", "AI 工作流"],
        )
        self.assertEqual(
            len(self.db.list_project_keywords(self.project_id)),
            2,
            "generating suggestions must not persist candidates",
        )
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM tasks"), 1)
        self.assertEqual(task["input_json"]["keyword_suggestions"]["project"]["name"], "AI 产品经理")

    def test_health_and_source_validation_are_explicit(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ai_capabilities"]["keyword_suggestions"])

        status, body = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keyword-suggestions",
            {
                "reference_sources": ["posts"],
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("manual, ai_generated", body["error"])

        self.app.keyword_provider = None
        status, body = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keyword-suggestions",
            {
                "reference_sources": [],
            },
        )
        self.assertEqual(status, 503)
        self.assertIn("不可用", body["error"])

        status, keywords = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keywords",
            {"keywords": ["手工仍可添加"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(keywords[0]["source"], "manual")

    def test_keyword_source_accepts_ai_and_manual_wins_on_duplicate(self):
        status, keywords = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keywords",
            {"keywords": ["AI 候选"], "source": "ai_generated"},
        )
        self.assertEqual(status, 200)
        created = next(item for item in keywords if item["keyword"] == "AI 候选")
        self.assertEqual(created["source"], "ai_generated")

        status, keywords = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keywords",
            {"keywords": ["AI 候选"]},
        )
        self.assertEqual(status, 200)
        promoted = next(item for item in keywords if item["keyword"] == "AI 候选")
        self.assertEqual(promoted["source"], "manual")

        status, body = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keywords",
            {"keywords": ["非法来源"], "source": "unknown"},
        )
        self.assertEqual(status, 400)
        self.assertIn("manual, ai_generated", body["error"])

    def test_creation_returns_immediately_and_cancel_stops_active_generation(self):
        blocking = BlockingKeywordProvider()
        self.app.keyword_provider = blocking
        started = time.monotonic()
        status, receipt = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keyword-suggestions",
            {"reference_sources": ["manual", "ai_generated"]},
        )
        self.assertEqual(status, 202)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(blocking.started.wait(1))

        duplicate_status, duplicate = self.request(
            "POST",
            f"/api/projects/{self.project_id}/keyword-suggestions",
            {"reference_sources": ["manual"]},
        )
        self.assertEqual(duplicate_status, 409)
        self.assertIn("AI 关键词生成", duplicate["error"])

        cancel_status, cancelled = self.request(
            "POST",
            f"/api/tasks/{receipt['id']}/cancel",
            {},
        )
        self.assertEqual(cancel_status, 200)
        self.assertEqual(cancelled["status"], "cancelled")
        task = self.db.get_task(receipt["id"], include_cancelled=True)
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["current_phase"], "cancelled")


class CodexKeywordProviderTests(unittest.TestCase):
    def test_provider_uses_only_project_and_keyword_context_and_filters_existing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            provider = CodexKeywordProvider("codex", work_dir=root, timeout=5)
            captured = {}

            def fake_run(args, prompt, timeout, should_cancel=None):
                captured["args"] = args
                captured["prompt"] = prompt
                captured["timeout"] = timeout
                output = Path(args[args.index("-o") + 1])
                output.write_text(
                    json.dumps({
                        "keywords": [
                            {
                                "keyword": "已有 AI 词",
                                "category": "重复",
                                "reason": "应该被过滤",
                            },
                            {
                                "keyword": "AI 需求分析",
                                "category": "使用场景",
                                "reason": "发现具体工作实践",
                            },
                        ],
                    }),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch(
                "xhs_research.keyword_generation.run_codex_process",
                side_effect=fake_run,
            ):
                result = provider.generate(
                    {
                        "name": "AI 产品经理",
                        "description": "研究工作方式变化",
                    },
                    ["手工种子"],
                    ["手工种子", "已有 AI 词"],
                )

            self.assertEqual(
                result["keywords"],
                [{
                    "keyword": "AI 需求分析",
                    "category": "使用场景",
                    "reason": "发现具体工作实践",
                }],
            )
            self.assertIn("项目名称：AI 产品经理", captured["prompt"])
            self.assertIn("项目说明：研究工作方式变化", captured["prompt"])
            self.assertIn('用户选择的参考关键词：["手工种子"]', captured["prompt"])
            self.assertIn('项目全部已有关键词（仅用于排除重复）：["手工种子", "已有 AI 词"]', captured["prompt"])
            self.assertNotIn("帖子证据", captured["prompt"])
            self.assertIn("--output-schema", captured["args"])
            self.assertEqual(list(root.glob("keywords-*.json")), [])

    def test_provider_keeps_all_selected_and_existing_keywords_beyond_one_hundred(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            provider = CodexKeywordProvider("codex", work_dir=root, timeout=5)
            captured = {}

            def fake_run(args, prompt, timeout, should_cancel=None):
                captured["prompt"] = prompt
                output = Path(args[args.index("-o") + 1])
                output.write_text(
                    json.dumps({
                        "keywords": [{
                            "keyword": "已有关键词 119",
                            "category": "重复",
                            "reason": "应被全部已有关键词去重",
                        }],
                    }),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args, 0, "", "")

            references = [f"参考关键词 {index}" for index in range(120)]
            existing = [f"已有关键词 {index}" for index in range(120)]
            with patch(
                "xhs_research.keyword_generation.run_codex_process",
                side_effect=fake_run,
            ):
                result = provider.generate(
                    {"name": "大规模关键词项目", "description": ""},
                    references,
                    existing,
                )

            self.assertIn("参考关键词 119", captured["prompt"])
            self.assertIn("已有关键词 119", captured["prompt"])
            self.assertEqual(result["keywords"], [])


if __name__ == "__main__":
    unittest.main()
