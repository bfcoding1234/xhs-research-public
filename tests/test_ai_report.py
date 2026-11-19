from pathlib import Path
import json
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.ai_reporting import (
    CodexReportError,
    CodexReportProvider,
    build_ai_report_evidence,
    build_report_chunks,
    default_report_prompt_templates,
    normalize_report_context_config,
    normalize_report_prompt_templates,
    report_context_detail,
    report_post_selection_count,
    report_prompt_template_hash,
    render_report_prompt_template,
)
from xhs_research.runner import TaskRunner
from xhs_research.server import ResearchApplication, create_server
from xhs_research.report_presentation import (
    normalize_presentation_configuration,
    render_presentation_html,
    validate_presentation_deck,
)


class ReportDataModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("报告项目", "keyword", {})
        self.task_id = self.db.create_task(self.project_id, "keyword", "test", {"mode": "keyword"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_report(self, generator_type):
        task_id = self.db.create_task(
            self.project_id, "keyword", "test", {"mode": "keyword"},
            task_type="ai_report" if generator_type == "llm" else "research",
        )
        return self.db.create_report(
            self.project_id,
            task_id,
            "keyword",
            "测试报告",
            "# 内容",
            {"post_count": 2},
            generator_type=generator_type,
            model="fake-model" if generator_type == "llm" else "",
            prompt_version="report-v1" if generator_type == "llm" else "",
            evidence_snapshot={"post_ids": [1, 2]},
            generation_config={"instructions": "关注视觉"},
        )

    def test_report_versions_increment_independently_by_generator_type(self):
        self.create_report("template")
        self.create_report("llm")
        self.create_report("template")
        self.create_report("llm")

        reports = self.db.list_reports(self.project_id)
        versions = {
            kind: [report["generator_version"] for report in reversed(reports) if report["generator_type"] == kind]
            for kind in ("template", "llm")
        }
        self.assertEqual(versions, {"template": [1, 2], "llm": [1, 2]})
        llm = next(report for report in reports if report["generator_type"] == "llm")
        self.assertEqual(llm["model"], "fake-model")
        self.assertEqual(llm["prompt_version"], "report-v1")
        self.assertEqual(llm["evidence_snapshot_json"], {"post_ids": [1, 2]})
        self.assertEqual(llm["generation_config_json"], {"instructions": "关注视觉"})

    def test_report_task_reserves_and_completes_the_same_project_version(self):
        task_id = self.db.create_task(
            self.project_id,
            "keyword",
            "test",
            {"operation": "ai_report", "mode": "keyword", "project_id": self.project_id},
            task_type="ai_report",
            _report_placeholder={
                "title": "生成中的项目报告",
                "generation_config": {"context_detail": "standard"},
            },
        )

        pending = self.db.list_reports(self.project_id)[0]
        self.assertEqual(pending["status"], "generating")
        self.assertEqual(pending["title"], "生成中的项目报告")
        self.assertEqual(pending["generator_version"], 1)
        self.assertIsNone(self.db.get_project(self.project_id)["latest_report_id"])

        report_id = self.db.create_report(
            self.project_id,
            task_id,
            "keyword",
            "已完成的项目报告",
            "# 完成正文",
            {"post_count": 2},
            generator_type="llm",
        )

        completed = self.db.list_reports(self.project_id)
        self.assertEqual(len(completed), 1)
        self.assertEqual(report_id, pending["id"])
        self.assertEqual(completed[0]["id"], pending["id"])
        self.assertEqual(completed[0]["status"], "completed")
        self.assertEqual(completed[0]["content_markdown"], "# 完成正文")
        self.assertEqual(self.db.get_project(self.project_id)["latest_report_id"], pending["id"])

    def test_failed_report_task_removes_the_reserved_project_version(self):
        task_id = self.db.create_task(
            self.project_id,
            "keyword",
            "test",
            {"operation": "ai_report", "mode": "keyword", "project_id": self.project_id},
            task_type="ai_report",
            _report_placeholder={"title": "即将失败的报告"},
        )
        self.assertEqual(self.db.list_reports(self.project_id)[0]["status"], "generating")

        self.assertTrue(self.db.fail_report_task(task_id, "生成失败"))

        self.assertEqual(self.db.list_reports(self.project_id), [])
        self.assertEqual(self.db.get_task(task_id)["status"], "failed")

    def test_initialize_migrates_an_existing_reports_table(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript((WORKBENCH_ROOT / "xhs_research" / "schema.sql").read_text(encoding="utf-8"))
            conn.execute("ALTER TABLE reports RENAME TO reports_current")
            conn.execute(
                """CREATE TABLE reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, task_id TEXT NOT NULL,
                version INTEGER NOT NULL, report_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'completed',
                title TEXT NOT NULL, summary_json TEXT NOT NULL DEFAULT '{}', content_markdown TEXT NOT NULL,
                evidence_post_count INTEGER NOT NULL DEFAULT 0, evidence_author_count INTEGER NOT NULL DEFAULT 0,
                generated_at TEXT NOT NULL, UNIQUE(project_id, version))"""
            )
            conn.execute("DROP TABLE reports_current")

        legacy = Database(legacy_path)
        legacy.initialize()
        columns = {row["name"] for row in legacy.query("PRAGMA table_info(reports)")}
        self.assertTrue({"generator_type", "generator_version", "model", "prompt_version", "evidence_snapshot_json", "generation_config_json"} <= columns)

    def test_report_commit_and_cancel_are_atomic_for_template_and_llm(self):
        for generator_type in ("template", "llm"):
            with self.subTest(generator_type=generator_type):
                task_id = self.db.create_task(
                    self.project_id, "keyword", "test", {"mode": "keyword"},
                    task_type="ai_report" if generator_type == "llm" else "research",
                )
                self.db.update_task(task_id, status="running", current_phase="report")
                begin_cancel = threading.Event()
                cancel_attempted = threading.Event()
                cancel_finished = threading.Event()
                cancel_results = []

                def cancel():
                    self.assertTrue(begin_cancel.wait(2))
                    cancel_attempted.set()
                    cancel_results.append(self.db.cancel_task(task_id))
                    cancel_finished.set()

                thread = threading.Thread(target=cancel)
                thread.start()

                def after_task_check():
                    begin_cancel.set()
                    self.assertTrue(cancel_attempted.wait(2))
                    time.sleep(0.05)
                    self.assertFalse(cancel_finished.is_set())

                report_id = self.db.create_report(
                    self.project_id, task_id, "keyword", "原子报告", "内容", {},
                    generator_type=generator_type,
                    _after_task_check=after_task_check,
                )
                thread.join(timeout=2)

                self.assertIsNotNone(report_id)
                self.assertEqual(cancel_results, [False])
                self.assertEqual(self.db.get_task(task_id)["status"], "completed")
                completed_events = [
                    event for event in self.db.list_task_events(task_id)
                    if event["phase"] == "completed"
                ]
                self.assertEqual(len(completed_events), 1)


class ReportEvidenceTests(unittest.TestCase):
    def test_builds_bounded_traceable_evidence_from_posts_and_authors(self):
        posts = [{
            "id": index,
            "note_id": f"note-{index}",
            "title": f"标题 {index}",
            "content": "正文" * 1000,
            "author_name": "作者",
            "note_type": "image",
            "note_url": f"https://example.com/{index}",
            "likes_count": index,
            "favorites_count": index // 2,
            "comments_count": index // 3,
            "popularity_percentile": index / 100,
            "popularity_level": "高热" if index >= 90 else "一般",
            "ocr_text": "封面文字" * 300,
            "vision_results": [{"visual_style": "简洁", "reusable_patterns": ["大标题"]}],
        } for index in range(1, 101)]
        authors = [{"id": 7, "author_id": "author-7", "display_name": "作者", "bio": "简介" * 500, "followers_count": 1000}]

        evidence, snapshot = build_ai_report_evidence({"id": 3, "name": "示例项目", "research_type": "keyword"}, posts, authors)

        self.assertEqual(evidence["project"]["name"], "示例项目")
        self.assertEqual(evidence["statistics"]["post_count"], 100)
        self.assertEqual(len(evidence["posts"]), 80)
        self.assertEqual(evidence["posts"][0]["post_id"], 100)
        self.assertLessEqual(len(evidence["posts"][0]["content"]), 503)
        self.assertLessEqual(len(evidence["posts"][0]["ocr_text"]), 503)
        self.assertEqual(snapshot["post_ids"], list(range(1, 101)))
        self.assertEqual(snapshot["author_ids"], [7])
        self.assertEqual(snapshot["selected_post_ids"][0], 100)
        self.assertEqual(snapshot["ocr_post_count"], 100)
        self.assertEqual(snapshot["vision_post_count"], 100)

    def test_context_detail_controls_selected_evidence_and_rich_text(self):
        posts = [{
            "id": index,
            "note_id": f"note-{index}",
            "content": "正文" * 1000,
            "ocr_text": "封面文字" * 1000,
            "vision_results": [{"cover_hook": "钩子"}],
        } for index in range(1, 101)]
        authors = [{"id": index, "display_name": f"作者 {index}"} for index in range(1, 51)]

        brief, brief_snapshot = build_ai_report_evidence(
            {"id": 3, "name": "示例项目"}, posts, authors, context_detail="brief",
        )
        detailed, detailed_snapshot = build_ai_report_evidence(
            {"id": 3, "name": "示例项目"}, posts, authors, context_detail="detailed",
        )

        self.assertEqual(brief["report_context"]["detail"], "brief")
        self.assertEqual(len(brief["posts"]), 25)
        self.assertEqual(brief["posts"][0]["ocr_text"], "")
        self.assertEqual(brief["posts"][0]["vision_analysis"], "")
        self.assertEqual(brief_snapshot["context_label"], "概览")
        self.assertEqual(len(detailed["posts"]), 100)
        self.assertGreater(len(detailed["posts"][0]["content"]), len(brief["posts"][0]["content"]))
        self.assertEqual(detailed_snapshot["context_detail"], "detailed")
        with self.assertRaisesRegex(ValueError, "context_detail"):
            report_context_detail("unknown")

    def test_explicit_context_uses_dynamic_post_percentages_and_selected_sections(self):
        posts = [{
            "id": index,
            "note_id": f"note-{index}",
            "title": f"标题 {index}",
            "content": f"正文 {index}",
            "author_name": "作者",
            "note_type": "image",
            "publish_date": "2026-08-01",
            "likes_count": index,
            "ocr_text": f"OCR {index}",
            "vision_results": [{"summary": f"理解 {index}"}],
            "popularity_percentile": index / 101,
        } for index in range(1, 102)]
        authors = [{"id": 7, "display_name": "作者"}]
        context = {
            "authors": {"enabled": False},
            "posts": {
                "enabled": True,
                "selection_mode": "representative",
                "sections": ["basic", "content", "ocr"],
            },
        }

        evidence, snapshot = build_ai_report_evidence(
            {"id": 3, "name": "精确设置项目"}, posts, authors, context_config=context,
        )

        self.assertEqual(report_post_selection_count(101, "representative"), 20)
        self.assertEqual(report_post_selection_count(101, "expanded"), 51)
        self.assertEqual(report_post_selection_count(101, "all"), 101)
        self.assertEqual(len(evidence["posts"]), 20)
        self.assertEqual(evidence["authors"], [])
        self.assertIn("publish_date", evidence["posts"][0])
        self.assertIn("content", evidence["posts"][0])
        self.assertIn("ocr_text", evidence["posts"][0])
        self.assertNotIn("vision_analysis", evidence["posts"][0])
        self.assertEqual(snapshot["evidence_post_count"], 20)
        self.assertEqual(snapshot["context_config"], context)

    def test_explicit_context_requires_a_source_and_supports_author_only(self):
        with self.assertRaisesRegex(ValueError, "至少需要开启一项"):
            normalize_report_context_config({
                "authors": {"enabled": False},
                "posts": {"enabled": False, "selection_mode": "all", "sections": []},
            })

        evidence, snapshot = build_ai_report_evidence(
            {"id": 3, "name": "作者证据项目"},
            [{"id": 1, "title": "不会进入上下文"}],
            [{"id": 7, "display_name": "作者"}],
            context_config={
                "authors": {"enabled": True},
                "posts": {"enabled": False, "selection_mode": "all", "sections": []},
            },
        )
        self.assertEqual(evidence["posts"], [])
        self.assertEqual([author["author_id"] for author in evidence["authors"]], [7])
        self.assertEqual(snapshot["evidence_post_count"], 0)
        self.assertEqual(snapshot["evidence_author_count"], 1)

    def test_evidence_selection_keeps_high_performers_and_broad_strata(self):
        posts = []
        for index in range(1, 101):
            posts.append({
                "id": index,
                "note_id": f"note-{index}",
                "author_name": "头部作者" if index > 70 else f"作者-{index % 8}",
                "external_author_id": "head" if index > 70 else f"author-{index % 8}",
                "sources": "热词" if index > 70 else f"来源-{index % 5}",
                "note_type": "video" if index % 7 == 0 else "image",
                "publish_date": f"2026-{(index % 6) + 1:02d}-01",
                "likes_count": index,
                "popularity_percentile": index / 100,
                "content": "正文" if index % 3 == 0 else "",
                "ocr_text": "封面" if index % 4 == 0 else "",
            })

        evidence, snapshot = build_ai_report_evidence(
            {"id": 3, "name": "分层项目"}, posts, [], context_detail="brief",
        )

        selected = evidence["posts"]
        self.assertEqual(selected[0]["post_id"], 100)
        self.assertGreater(len({post["author_name"] for post in selected}), 2)
        self.assertTrue(any(float(post["popularity_percentile"] or 0) < 0.3 for post in selected))
        self.assertEqual(snapshot["selection"]["strategy"], "stratified-v1")

    def test_report_chunks_obey_serialized_character_budget(self):
        evidence = {
            "project": {"id": 3, "name": "项目"},
            "report_context": {"detail": "standard"},
            "statistics": {"post_count": 8},
            "authors": [],
            "posts": [
                {"post_id": index, "title": f"标题 {index}", "content": "正文" * 600}
                for index in range(1, 9)
            ],
        }
        chunks = build_report_chunks(evidence, char_budget=3000)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(
            [post["post_id"] for chunk in chunks for post in chunk["posts"]],
            list(range(1, 9)),
        )

    def test_provider_generates_directly_from_author_only_evidence(self):
        class AuthorOnlyProvider(CodexReportProvider):
            def _invoke(self, prompt, output_root, suffix, timeout, schema, should_cancel):
                self.assert_no_post_reference = "\"posts\":[]" in prompt
                return (
                    "# 作者报告\n\n## 数据与方法\n仅使用作者资料。\n\n"
                    "## 作者与内容定位\n定位明确。\n\n## 高表现内容规律\n无帖子证据。\n\n"
                    "## 标题与选题规律\n无帖子证据。\n\n## 视觉表达规律\n无帖子证据。\n\n"
                    "## 可执行建议\n补充帖子样本。\n\n## 局限与置信度\n当前仅有作者资料，"
                    "无法验证具体内容表现，所有判断都需要在取得帖子样本后重新检查。"
                    "建议后续补充不同时间、不同互动水平和不同内容类型的帖子，再验证作者定位、"
                    "选题规律、视觉表达与表现之间是否存在稳定关系。本报告不对缺失证据作推断，"
                    "也不把作者资料中的自我描述直接视为真实内容效果。",
                    {"attempts": 1},
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = AuthorOnlyProvider(work_dir=Path(temp_dir), retries=0)
            content = provider.generate(
                {"id": 3, "name": "作者项目"},
                {
                    "project": {"id": 3, "name": "作者项目"},
                    "report_context": {"label": "精确设置"},
                    "statistics": {"post_count": 0, "author_count": 1},
                    "authors": [{"author_id": 7, "display_name": "作者"}],
                    "posts": [],
                },
            )

        self.assertIn("数据与方法", content)
        self.assertTrue(provider.assert_no_post_reference)

    def test_report_chunk_cache_persists_structured_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("缓存项目", "keyword", {})
            task_id = db.create_task(
                project_id, "keyword", "test",
                {"operation": "ai_report", "mode": "keyword", "project_id": project_id},
                task_type="ai_report",
            )
            result = {"covered_post_ids": [1], "themes": ["主题"]}
            db.save_report_chunk(
                task_id, 0, "cache-key", 1200, "completed", result,
                {"attempts": 1, "elapsed_seconds": 2.5}, "",
            )
            self.assertEqual(db.get_cached_report_chunk("cache-key"), result)
            row = db.list_report_chunks(task_id)[0]
            self.assertEqual(row["result_json"], result)
            self.assertEqual(row["diagnostics_json"]["attempts"], 1)

    def test_invalid_chunk_citations_are_repaired_and_diagnostics_are_saved(self):
        class RepairingProvider(CodexReportProvider):
            def __init__(self, work_dir):
                super().__init__(work_dir=work_dir, retries=0)
                self.calls = []

            def _invoke(self, prompt, output_root, suffix, timeout, schema, should_cancel):
                self.calls.append({"prompt": prompt, "suffix": suffix})
                cited_id = 1 if suffix.endswith("-repair") else 999
                return json.dumps({
                    "covered_post_ids": [1],
                    "themes": ["主题"],
                    "content_patterns": [],
                    "visual_patterns": [],
                    "high_performance_patterns": [],
                    "claims": [{
                        "claim": "结论",
                        "supporting_post_ids": [cited_id],
                        "confidence": "medium",
                    }],
                    "counterexamples": [],
                    "data_gaps": [],
                }), {"attempts": 1, "suffix": suffix}

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = RepairingProvider(Path(temp_dir))
            saved = []
            chunk = {"posts": [{"post_id": 1, "title": "标题"}]}
            templates = default_report_prompt_templates()
            result, diagnostics = provider._summarize_chunk(
                {"name": "项目"}, chunk, 2, "", templates,
                report_prompt_template_hash(templates), Path(temp_dir), None,
                cache_save=lambda *args: saved.append(args),
            )

        self.assertEqual(result["claims"][0]["supporting_post_ids"], [1])
        self.assertEqual([call["suffix"] for call in provider.calls], ["chunk-2", "chunk-2-repair"])
        self.assertIn("允许使用的帖子 ID：[1]", provider.calls[1]["prompt"])
        self.assertEqual(diagnostics["validation"]["invalid_post_ids"], [999])
        self.assertTrue(diagnostics["repair_succeeded"])
        self.assertEqual(saved[-1][3], "completed")
        self.assertEqual(saved[-1][4], result)

    def test_failed_chunk_repair_preserves_invalid_results_and_ids(self):
        class FailingRepairProvider(CodexReportProvider):
            def __init__(self, work_dir):
                super().__init__(work_dir=work_dir, retries=0)

            def _invoke(self, prompt, output_root, suffix, timeout, schema, should_cancel):
                cited_id = 998 if suffix.endswith("-repair") else 999
                return json.dumps({
                    "covered_post_ids": [1],
                    "themes": [],
                    "content_patterns": [],
                    "visual_patterns": [],
                    "high_performance_patterns": [],
                    "claims": [{
                        "claim": "越界结论",
                        "supporting_post_ids": [cited_id],
                        "confidence": "low",
                    }],
                    "counterexamples": [],
                    "data_gaps": [],
                }), {"attempts": 1, "suffix": suffix}

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = FailingRepairProvider(Path(temp_dir))
            saved = []
            templates = default_report_prompt_templates()
            with self.assertRaisesRegex(CodexReportError, "证据快照以外"):
                provider._summarize_chunk(
                    {"name": "项目"}, {"posts": [{"post_id": 1}]}, 0,
                    "", templates, report_prompt_template_hash(templates), Path(temp_dir), None,
                    cache_save=lambda *args: saved.append(args),
                )

        self.assertEqual(saved[-1][3], "failed")
        self.assertEqual(saved[-1][4]["claims"][0]["supporting_post_ids"], [999])
        diagnostics = saved[-1][5]
        self.assertEqual(diagnostics["validation"]["invalid_post_ids"], [999])
        self.assertEqual(diagnostics["repair_validation"]["invalid_post_ids"], [998])
        self.assertEqual(
            diagnostics["repair"]["invalid_result"]["claims"][0]["supporting_post_ids"],
            [998],
        )

    def test_invalid_cached_chunk_is_regenerated_instead_of_failing(self):
        class FreshProvider(CodexReportProvider):
            def __init__(self, work_dir):
                super().__init__(work_dir=work_dir, retries=0)
                self.calls = 0

            def _invoke(self, prompt, output_root, suffix, timeout, schema, should_cancel):
                self.calls += 1
                return json.dumps({
                    "covered_post_ids": [1],
                    "themes": [],
                    "content_patterns": [],
                    "visual_patterns": [],
                    "high_performance_patterns": [],
                    "claims": [],
                    "counterexamples": [],
                    "data_gaps": [],
                }), {"attempts": 1}

        invalid_cache = {
            "covered_post_ids": [1],
            "claims": [{"supporting_post_ids": [999]}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = FreshProvider(Path(temp_dir))
            templates = default_report_prompt_templates()
            result, diagnostics = provider._summarize_chunk(
                {"name": "项目"}, {"posts": [{"post_id": 1}]}, 0,
                "", templates, report_prompt_template_hash(templates), Path(temp_dir), None,
                cache_get=lambda _key: invalid_cache,
            )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["covered_post_ids"], [1])
        self.assertEqual(
            diagnostics["rejected_cache_validation"]["invalid_post_ids"],
            [999],
        )

    def test_configurable_report_prompts_render_once_and_isolate_chunk_cache(self):
        templates = normalize_report_prompt_templates({
            "chunk": (
                "批次 {{subject_name}}｜{{user_instructions}}｜{{allowed_post_ids}}\n"
                "{{evidence_json}}"
            ),
            "final": (
                "最终 {{scope_label}}｜{{subject_name}}｜{{report_title}}｜{{context_label}}｜"
                "{{user_instructions}}\n{{evidence_json}}"
            ),
        }, require_both=True)
        template_hash = report_prompt_template_hash(templates)
        provider = CodexReportProvider(retries=0)
        chunk = {"posts": [{"post_id": 1, "title": "保留 {{report_title}} 原文"}]}

        rendered = render_report_prompt_template("chunk", templates["chunk"], {
            "subject_name": "项目",
            "allowed_post_ids": [1],
            "user_instructions": "关注转化",
            "evidence_json": json.dumps(chunk, ensure_ascii=False),
        })

        self.assertIn("批次 项目｜关注转化｜[1]", rendered)
        self.assertIn("保留 {{report_title}} 原文", rendered)
        self.assertNotEqual(
            provider._chunk_cache_key(chunk, template_hash, "关注转化"),
            provider._chunk_cache_key(chunk, template_hash, "关注视觉"),
        )

    def test_pipeline_runs_chunks_with_bounded_parallelism_and_reuses_cache(self):
        class StubProvider(CodexReportProvider):
            def __init__(self, work_dir):
                super().__init__(
                    binary="codex",
                    work_dir=work_dir,
                    chunk_char_budget=2600,
                    max_concurrency=2,
                    retries=0,
                )
                self.lock = threading.Lock()
                self.active = 0
                self.max_active = 0
                self.chunk_calls = 0
                self.final_calls = 0

            def _invoke(self, prompt, output_root, suffix, timeout, schema, should_cancel):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.05)
                    if schema is not None:
                        self.chunk_calls += 1
                        ids = sorted({int(value) for value in re.findall(r'"post_id":(\d+)', prompt)})
                        result = {
                            "covered_post_ids": ids,
                            "themes": ["主题"],
                            "content_patterns": ["内容模式"],
                            "visual_patterns": [],
                            "high_performance_patterns": ["高表现模式"],
                            "claims": [{
                                "claim": "存在稳定模式",
                                "supporting_post_ids": ids[:2],
                                "confidence": "medium",
                            }],
                            "counterexamples": [],
                            "data_gaps": [],
                        }
                        return json.dumps(result, ensure_ascii=False), {"attempts": 1}
                    self.final_calls += 1
                    return (
                        "# 大模型报告\n\n"
                        "## 数据与方法\n基于全量统计与分层样本完成分析，并引用 [帖子 #1]。\n\n"
                        "## 作者与内容定位\n定位清晰。\n\n"
                        "## 高表现内容规律\n证据表明存在稳定规律。\n\n"
                        "## 标题与选题规律\n标题强调具体收益。\n\n"
                        "## 视觉表达规律\n当前视觉证据有限。\n\n"
                        "## 可执行建议\n持续验证代表性选题，并保留反例。\n\n"
                        "## 局限与置信度\n样本为分层选择，结论置信度中等。"
                        "报告只依据任务启动时的数据快照，不能代表平台全部内容，"
                        "后续应结合新增样本复核趋势，并持续检查低热度反例。\n",
                        {"attempts": 1},
                    )
                finally:
                    with self.lock:
                        self.active -= 1

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = StubProvider(Path(temp_dir))
            evidence = {
                "project": {"id": 3, "name": "项目"},
                "report_context": {"detail": "standard", "label": "标准"},
                "statistics": {"post_count": 8},
                "authors": [],
                "posts": [
                    {"post_id": index, "title": f"标题 {index}", "content": "正文" * 700}
                    for index in range(1, 9)
                ],
            }
            cache = {}
            progress = []

            def save(cache_key, _index, _chars, status, result, _diagnostics, _error):
                if status == "completed":
                    cache[cache_key] = result

            first = provider.generate(
                {"id": 3, "name": "项目"}, evidence,
                on_progress=progress.append,
                cache_get=cache.get,
                cache_save=save,
            )
            first_chunk_calls = provider.chunk_calls
            second = provider.generate(
                {"id": 3, "name": "项目"}, evidence,
                cache_get=cache.get,
                cache_save=save,
            )

            self.assertIn("数据与方法", first)
            self.assertEqual(second, first)
            self.assertGreater(first_chunk_calls, 1)
            self.assertEqual(provider.chunk_calls, first_chunk_calls)
            self.assertEqual(provider.max_active, 2)
            self.assertEqual(progress[-1]["stage"], "completed")

    def test_database_report_capture_excludes_concurrent_vision_commits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "research.sqlite3")
            db.initialize()
            project_id = db.create_project("原子快照", "keyword", {})
            post_id = db.upsert_post({"note_id": "snapshot-note", "title": "快照帖子"})
            db.attach_post_to_project(project_id, post_id)
            image = Path(temp_dir) / "media" / "snapshot.jpg"
            image.parent.mkdir()
            image.write_bytes(b"snapshot-image")
            db.upsert_media(post_id, {"local_path": str(image)}, 0, "image")
            begin_write = threading.Event()
            write_finished = threading.Event()
            errors = []

            def writer():
                try:
                    self.assertTrue(begin_write.wait(2))
                    with db.connect() as conn:
                        conn.execute(
                            """INSERT INTO vision_analyses(
                                   post_id,cache_key,model,prompt_version,analysis_json,analyzed_at
                               ) VALUES(?,?,?,?,?,?)""",
                            (
                                post_id, "late-cache", "model", "v1",
                                json.dumps({"cover_hook": "late"}),
                                "2026-07-11T00:00:00+00:00",
                            ),
                        )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    write_finished.set()

            thread = threading.Thread(target=writer)
            thread.start()

            def after_snapshot_started():
                begin_write.set()
                self.assertTrue(write_finished.wait(2))

            captured = db.capture_report_evidence(
                project_id,
                _after_snapshot_started=after_snapshot_started,
                vision_model="model",
                vision_prompt_version="v1",
                vision_cache_key=lambda _paths: "late-cache",
            )
            thread.join(timeout=2)
            self.assertEqual(errors, [])
            self.assertEqual(captured["posts"][0]["vision_results"], [])
            self.assertTrue(captured["captured_at"])
            self.assertEqual(
                db.capture_report_evidence(
                    project_id,
                    vision_model="model",
                    vision_prompt_version="v1",
                    vision_cache_key=lambda _paths: "late-cache",
                )["posts"][0]["vision_results"],
                [{"cover_hook": "late"}],
            )
            self.assertEqual(
                db.capture_report_evidence(project_id)["posts"][0]["vision_results"],
                [],
            )


class ReportPresentationRenderingTests(unittest.TestCase):
    @staticmethod
    def deck(page_count=6, malicious=False):
        slides = []
        for index in range(page_count):
            slide_type = "title" if index == 0 else "closing" if index == page_count - 1 else "bullets"
            slides.append({
                "type": slide_type,
                "eyebrow": "研究报告",
                "title": "<script>alert('xss')</script>" if malicious and index == 1 else f"页面 {index + 1}",
                "subtitle": "",
                "body": "结论正文",
                "bullets": [],
                "metrics": [],
                "columns": [],
                "source_refs": [],
            })
        return {"title": "安全演示稿", "subtitle": "", "slides": slides}

    def test_normalizes_configuration_and_enforces_page_mode(self):
        self.assertEqual(normalize_presentation_configuration(), {
            "title": "", "page_mode": "standard", "instructions": "",
        })
        with self.assertRaisesRegex(ValueError, "页数"):
            normalize_presentation_configuration({"page_mode": "unlimited"})
        with self.assertRaisesRegex(ValueError, "6～8"):
            validate_presentation_deck(self.deck(5), "concise")

    def test_html_renderer_escapes_model_content_and_stays_self_contained(self):
        deck = validate_presentation_deck(self.deck(malicious=True), "concise")
        html = render_presentation_html(deck)

        self.assertNotIn("<script>alert('xss')</script>", html)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html)
        self.assertNotIn("https://", html)
        self.assertIn('aria-label="幻灯片导航"', html)
        self.assertIn("@media print", html)


class FakeReportProvider:
    model = "fake-report-model"
    prompt_version = "report-test-v1"

    def __init__(self):
        self.calls = []
        self.presentation_calls = []

    def generate(self, project, evidence, instructions="", prompt_templates=None):
        self.calls.append({
            "project": project,
            "evidence": evidence,
            "instructions": instructions,
            "prompt_templates": prompt_templates,
        })
        return "# 大模型报告\n\n结论引用 [帖子 #1]。\n"

    def generate_presentation(self, report, configuration, should_cancel=None):
        self.presentation_calls.append({
            "report": report,
            "configuration": configuration,
            "cancelled": should_cancel() if should_cancel else False,
        })
        page_count = {"concise": 6, "standard": 9, "complete": 13}[configuration["page_mode"]]
        slides = []
        for index in range(page_count):
            slide_type = "title" if index == 0 else "closing" if index == page_count - 1 else "bullets"
            slides.append({
                "type": slide_type,
                "eyebrow": "研究报告",
                "title": configuration["title"] if index == 0 else f"结论 {index}",
                "subtitle": "",
                "body": "从源报告提炼的内容",
                "bullets": ["只使用源报告事实"],
                "metrics": [],
                "columns": [],
                "source_refs": ["帖子 #1"],
            })
        return {"title": configuration["title"], "subtitle": "", "slides": slides}, {"fake": True}


class AiReportTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("大模型报告项目", "keyword", {})
        self.post_id = self.db.upsert_post({
            "note_id": "note-1", "title": "高表现标题", "note_type": "image",
            "likes_count": 100, "favorites_count": 20, "comments_count": 10,
        })
        self.db.attach_post_to_project(self.project_id, self.post_id)
        self.provider = FakeReportProvider()
        self.runner = TaskRunner(self.db, socai=None, report_provider=self.provider)
        self.settings = SimpleNamespace(max_workers=1, host="127.0.0.1", port=4318, max_author_notes=300)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_manual_ai_report_task_saves_version_and_evidence_snapshot(self):
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_ai_report_task(self.project_id, "web", {
                "title": "选题与视觉机会报告", "instructions": "重点分析选题", "context_detail": "detailed"
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        report = self.db.list_reports(self.project_id)[0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["input_json"]["operation"], "ai_report")
        self.assertEqual(task["task_type"], "ai_report")
        self.assertEqual(report["generator_type"], "llm")
        self.assertEqual(report["generator_version"], 1)
        self.assertEqual(report["model"], "fake-report-model")
        self.assertEqual(report["prompt_version"], "report-test-v1")
        self.assertEqual(report["title"], "选题与视觉机会报告")
        self.assertEqual(report["evidence_snapshot_json"]["post_ids"], [self.post_id])
        prompt_templates = default_report_prompt_templates()
        self.assertEqual(report["generation_config_json"], {
            "title": "选题与视觉机会报告",
            "instructions": "重点分析选题",
            "sources": ["current_detail"],
            "context_detail": "detailed",
            "prompt_templates": prompt_templates,
            "prompt_template_hash": report_prompt_template_hash(prompt_templates),
            "pipeline": {"strategy": "stratified-map-reduce-v1", "chunk_count": 1},
        })
        self.assertEqual(task["input_json"]["report_generation"]["title"], "选题与视觉机会报告")
        self.assertEqual(task["input_json"]["report_generation"]["context_detail"], "detailed")
        self.assertEqual(task["input_json"]["report_generation"]["prompt_templates"], prompt_templates)
        self.assertEqual(self.provider.calls[0]["instructions"], "重点分析选题")
        self.assertEqual(self.provider.calls[0]["prompt_templates"], prompt_templates)
        self.assertEqual(self.provider.calls[0]["evidence"]["report_context"]["detail"], "detailed")

    def test_report_task_snapshots_configured_prompt_templates(self):
        templates = {
            "chunk": "专项分批 {{allowed_post_ids}}\n{{evidence_json}}",
            "final": "专项报告 {{user_instructions}}\n{{evidence_json}}",
        }
        self.db.set_app_settings({"report_prompt_templates": templates})
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_ai_report_task(self.project_id, "web", {
                "instructions": "关注转化",
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        report = self.db.list_reports(self.project_id)[0]
        expected_hash = report_prompt_template_hash(templates)
        self.assertEqual(task["input_json"]["report_generation"]["prompt_templates"], templates)
        self.assertEqual(task["input_json"]["report_generation"]["prompt_template_hash"], expected_hash)
        self.assertEqual(report["generation_config_json"]["prompt_templates"], templates)
        self.assertEqual(report["generation_config_json"]["prompt_template_hash"], expected_hash)
        self.assertEqual(
            task["input_json"]["report_generation"]["context_config"],
            {
                "authors": {"enabled": True},
                "posts": {
                    "enabled": True,
                    "selection_mode": "representative",
                    "sections": ["basic", "content", "ocr"],
                },
            },
        )
        self.assertEqual(report["evidence_post_count"], 1)
        self.assertEqual(self.provider.calls[0]["prompt_templates"], templates)

    def test_report_can_combine_a_frozen_data_summary_with_current_details(self):
        summary = self.runner.create_project_data_summary(self.project_id)
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_ai_report_task(self.project_id, "web", {
                "sources": ["data_summary", "current_detail"],
                "data_summary_report_id": summary["id"],
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        report = next(item for item in self.db.list_reports(self.project_id) if item["generator_type"] == "llm")
        evidence = self.provider.calls[0]["evidence"]
        self.assertEqual(task["input_json"]["report_generation"]["sources"], ["data_summary", "current_detail"])
        self.assertEqual(
            task["input_json"]["report_generation"]["data_summary_snapshot"]["report_id"],
            summary["id"],
        )
        self.assertEqual(evidence["data_summary"]["report_id"], summary["id"])
        self.assertEqual(evidence["posts"][0]["post_id"], self.post_id)
        self.assertEqual(
            evidence["source_policy"]["data_summary_role"],
            "统计数字、趋势和分布的唯一权威口径",
        )
        self.assertIn("不得重新计算", evidence["source_policy"]["current_detail_role"])
        self.assertTrue(evidence["source_policy"]["timestamps_are_independent"])
        self.assertEqual(report["generation_config_json"]["sources"], ["data_summary", "current_detail"])
        self.assertEqual(report["generation_config_json"]["data_summary"]["report_id"], summary["id"])

    def test_report_can_use_only_a_selected_data_summary(self):
        summary = self.runner.create_project_data_summary(self.project_id)
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_ai_report_task(self.project_id, "web", {
                "sources": ["data_summary"],
                "data_summary_report_id": summary["id"],
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        report = next(item for item in self.db.list_reports(self.project_id) if item["task_id"] == result["id"])
        evidence = self.provider.calls[0]["evidence"]
        self.assertEqual(evidence["posts"], [])
        self.assertEqual(evidence["authors"], [])
        self.assertEqual(report["evidence_post_count"], 1)
        self.assertEqual(report["generation_config_json"]["sources"], ["data_summary"])

    def test_completed_llm_report_can_generate_and_serve_a_safe_html_presentation(self):
        source_task_id = self.db.create_task(
            self.project_id,
            "keyword",
            "test",
            {"operation": "ai_report", "project_id": self.project_id},
            task_type="ai_report",
        )
        report_id = self.db.create_report(
            self.project_id,
            source_task_id,
            "keyword",
            "源大模型报告",
            "# 报告正文\n\n<script>alert('source')</script>\n\n引用 [帖子 #1]。",
            {"post_count": 1},
            generator_type="llm",
            model="fake-report-model",
        )
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_report_presentation_task(
                project_id=self.project_id,
                report_id=report_id,
                configuration={"title": "洞察演示稿", "page_mode": "concise"},
            )
            app.executor.shutdown(wait=True, cancel_futures=True)
            presentation = self.db.list_report_presentations(project_report_id=report_id)[0]
            server = create_server("127.0.0.1", 0, app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base_url}/api/report-presentations/{presentation['id']}/html") as response:
                    html = response.read().decode("utf-8")
                    content_security_policy = response.headers["Content-Security-Policy"]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(self.db.get_task(result["id"])["status"], "completed")
        self.assertEqual(presentation["status"], "completed")
        self.assertEqual(presentation["slide_count"], 6)
        self.assertEqual(self.provider.presentation_calls[0]["report"]["id"], report_id)
        self.assertIn("default-src 'none'", content_security_policy)
        self.assertIn("<!doctype html>", html)
        self.assertNotIn("<script>alert('source')</script>", html)

    def test_rejects_a_duplicate_active_ai_report_task(self):
        active_id = self.db.create_task(
            self.project_id, "keyword", "web",
            {"operation": "ai_report", "mode": "keyword", "project_id": self.project_id},
        )
        self.db.update_task(active_id, status="running", current_phase="report_generation")
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            with self.assertRaisesRegex(ValueError, "已有运行中的大模型报告任务"):
                app.create_ai_report_task(self.project_id)
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

    def test_http_endpoint_exposes_status_and_creates_ai_report_task(self):
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/projects/{self.project_id}/report-status") as response:
                status = json.load(response)
            request = Request(
                f"{base_url}/api/projects/{self.project_id}/ai-report",
                data=json.dumps({"configuration": {
                    "title": "作者定位专项报告", "instructions": "关注作者定位"
                }}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                task = json.load(response)
            app.executor.shutdown(wait=True, cancel_futures=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(status["post_count"], 1)
        self.assertTrue(status["provider_available"])
        self.assertEqual(self.db.get_task(task["id"])["status"], "completed")
        self.assertEqual(self.db.list_reports(self.project_id)[0]["generator_type"], "llm")
        self.assertEqual(self.db.list_reports(self.project_id)[0]["title"], "作者定位专项报告")


class AuthorReportTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.author_id = self.db.upsert_author({
            "author_id": "author-report-subject",
            "display_name": "报告作者",
            "bio": "专注 AI 产品内容",
            "followers_count": 1200,
        })
        self.post_id = self.db.upsert_post({
            "note_id": "author-report-note",
            "author_id": "author-report-subject",
            "author": "报告作者",
            "title": "作者代表帖子",
            "note_type": "image",
            "likes_count": 88,
        })
        self.provider = FakeReportProvider()
        self.runner = TaskRunner(self.db, socai=None, report_provider=self.provider)
        self.settings = SimpleNamespace(
            max_workers=1,
            host="127.0.0.1",
            port=4318,
            max_author_notes=300,
            data_dir=Path(self.temp_dir.name),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_author_report_uses_all_known_author_posts_and_owns_versions(self):
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_author_ai_report_task(self.author_id, "web", {
                "title": "作者定位报告",
                "instructions": "重点分析作者定位",
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        report = self.db.list_author_reports(self.author_id)[0]
        self.assertIsNone(task["project_id"])
        self.assertEqual(task["author_id"], self.author_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(report["project_id"], None)
        self.assertEqual(report["author_id"], self.author_id)
        self.assertEqual(report["title"], "作者定位报告")
        self.assertEqual(report["evidence_snapshot_json"]["scope"], "author")
        self.assertEqual(report["evidence_snapshot_json"]["post_ids"], [self.post_id])
        self.assertIn("author", self.provider.calls[0]["evidence"])
        self.assertNotIn("project", self.provider.calls[0]["evidence"])

    def test_author_only_source_allows_a_report_without_posts(self):
        author_id = self.db.upsert_author({
            "author_id": "profile-only-author",
            "display_name": "只有资料的作者",
            "bio": "尚未采集帖子",
        })
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_author_ai_report_task(author_id, "web", {
                "context_config": {
                    "authors": {"enabled": True},
                    "posts": {"enabled": False, "selection_mode": "all", "sections": []},
                },
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        task = self.db.get_task(result["id"])
        report = self.db.list_author_reports(author_id)[0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(report["evidence_post_count"], 0)
        self.assertEqual(report["evidence_author_count"], 1)
        self.assertEqual(self.provider.calls[-1]["evidence"]["posts"], [])
        self.assertEqual(len(self.provider.calls[-1]["evidence"]["authors"]), 1)

    def test_author_report_can_combine_its_data_summary_and_current_details(self):
        summary = self.runner.create_author_data_summary(self.author_id)
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        try:
            result = app.create_author_ai_report_task(self.author_id, "web", {
                "sources": ["data_summary", "current_detail"],
                "data_summary_report_id": summary["id"],
            })
        finally:
            app.executor.shutdown(wait=True, cancel_futures=True)

        report = next(
            item for item in self.db.list_author_reports(self.author_id)
            if item["task_id"] == result["id"]
        )
        evidence = self.provider.calls[-1]["evidence"]
        self.assertEqual(evidence["data_summary"]["report_id"], summary["id"])
        self.assertEqual(evidence["posts"][0]["post_id"], self.post_id)
        self.assertEqual(report["generation_config_json"]["sources"], [
            "data_summary", "current_detail",
        ])

    def test_author_report_reservation_is_removed_when_the_task_fails(self):
        task_id = self.db.create_task(
            None,
            "author",
            "test",
            {
                "operation": "ai_report",
                "mode": "author",
                "author_id": self.author_id,
                "report_scope": "author",
            },
            task_type="ai_report",
            author_id=self.author_id,
            _report_placeholder={
                "title": "生成中的作者报告",
                "generation_config": {"context_detail": "standard"},
            },
        )
        pending = self.db.list_author_reports(self.author_id)[0]
        self.assertEqual(pending["status"], "generating")
        self.assertEqual(pending["generator_version"], 1)

        self.assertTrue(self.db.fail_report_task(task_id, "作者报告生成失败"))

        self.assertEqual(self.db.list_author_reports(self.author_id), [])
        self.assertEqual(self.db.get_task(task_id)["status"], "failed")

    def test_author_report_status_and_http_endpoints(self):
        app = ResearchApplication(self.settings, self.db, self.runner, WORKBENCH_ROOT / "web")
        server = create_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/authors/{self.author_id}/report-status") as response:
                status = json.load(response)
            request = Request(
                f"{base_url}/api/authors/{self.author_id}/ai-report",
                data=json.dumps({"configuration": {"title": "HTTP 作者报告"}}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                task = json.load(response)
            app.executor.shutdown(wait=True, cancel_futures=True)
            with urlopen(f"{base_url}/api/authors/{self.author_id}/reports") as response:
                reports = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(status["post_count"], 1)
        self.assertEqual(status["author_count"], 1)
        self.assertTrue(status["provider_available"])
        self.assertEqual(self.db.get_task(task["id"])["status"], "completed")
        self.assertEqual(reports[0]["title"], "HTTP 作者报告")

    def test_author_cannot_start_duplicate_active_report_tasks(self):
        payload = {
            "operation": "ai_report",
            "mode": "author",
            "author_id": self.author_id,
            "report_scope": "author",
        }
        self.db.create_task(
            None, "author", "web", payload,
            task_type="ai_report", author_id=self.author_id,
        )
        with self.assertRaisesRegex(ValueError, "作者已有运行中的大模型报告任务"):
            self.db.create_task(
                None, "author", "web", payload,
                task_type="ai_report", author_id=self.author_id,
            )


if __name__ == "__main__":
    unittest.main()
