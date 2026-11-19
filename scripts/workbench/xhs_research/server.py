from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import mimetypes
import os
import socket
import stat
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .config import Settings, XIAOHONGSHU_COOKIE_SOURCES, is_loopback_host
from .ai_reporting import (
    default_report_prompt_templates,
    normalize_report_context_config,
    normalize_report_prompt_templates,
    report_context_detail,
    report_prompt_template_hash,
)
from .collector import CapabilityRegistry
from .db import ActiveTaskConflict, Database, ProjectDeleteConflict, ProjectReferenceConflict, utcnow
from .lifecycle_lock import FileLockUnavailable, acquire_file_lock, release_file_lock
from .models import ResearchRequest, normalize_author_source
from .release import DataReleaseService
from .codex_process import CodexProcessCancelled
from .keyword_generation import KeywordGenerationError
from .report_presentation import (
    PRESENTATION_PROMPT_VERSION,
    normalize_presentation_configuration,
)
from .vision import (
    DEFAULT_VISION_TIMEOUT_SECONDS,
    VISION_TIMEOUT_MAX_SECONDS,
    VISION_TIMEOUT_MIN_SECONDS,
    VISION_REASONING_EFFORTS,
    list_codex_image_models,
)


_RUNTIME_CLAIMS = set()
_RUNTIME_CLAIMS_LOCK = threading.Lock()


class ApiProblem(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = int(status)
        self.message = message


def _finite_float(value: Any, field_name: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _integer(value: Any, field_name: str) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _selected_image_scope_pending(
    status: Dict[str, Any], configuration: Dict[str, Any], processing_method: str,
) -> int:
    raw = configuration.get("image_scopes", ["cover"])
    if not isinstance(raw, list) or not raw:
        return 0
    scopes = list(dict.fromkeys(str(value) for value in raw))
    if scopes == ["all"]:
        key = "ocr_pending_posts" if processing_method == "ocr" else "pending_posts"
        return int(status.get(key) or 0)
    values = status.get("ocr_scopes" if processing_method == "ocr" else "vision_scopes") or {}
    return sum(int((values.get(scope) or {}).get("pending_posts") or 0) for scope in scopes)


def _require_finite_json(value: Any, path: str = "$"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must contain only finite numbers")
    if isinstance(value, dict):
        for key, item in value.items():
            _require_finite_json(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_finite_json(item, f"{path}[{index}]")


def _normalize_report_generation_context(values: Dict[str, Any]) -> Dict[str, Any]:
    if "context_config" in values:
        return {"context_config": normalize_report_context_config(values["context_config"])}
    if "context_detail" in values:
        return {"context_detail": report_context_detail(values["context_detail"])}
    return {"context_config": normalize_report_context_config()}


def _normalize_report_sources(values: Dict[str, Any]) -> list:
    raw = values.get("sources")
    if raw is None:
        return ["current_detail"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("大模型报告至少选择一项数据来源")
    sources = list(dict.fromkeys(str(value).strip() for value in raw))
    unknown = sorted(set(sources) - {"data_summary", "current_detail"})
    if unknown:
        raise ValueError(f"大模型报告包含未知数据来源：{', '.join(unknown)}")
    return sources


def _report_summary_snapshot(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = report.get("summary_json") if isinstance(report.get("summary_json"), dict) else {}
    canonical = json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "report_id": int(report["id"]),
        "version": int(report.get("generator_version") or report.get("version") or 0),
        "title": str(report.get("title") or "数据摘要"),
        "generated_at": str(report.get("generated_at") or ""),
        "summary_json": summary,
        "evidence_snapshot_json": report.get("evidence_snapshot_json") or {},
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _authority_hostname(value: str) -> str:
    try:
        parsed = urlparse("//" + str(value or "").strip())
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return ""
        # Accessing port also rejects malformed authorities such as :abc.
        parsed.port
        return (parsed.hostname or "").lower()
    except ValueError:
        return ""


def _trusted_loopback_origin(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and is_loopback_host(parsed.hostname or "")
    except ValueError:
        return False


def _media_content_type(target: Path) -> str:
    try:
        if not stat.S_ISREG(target.stat().st_mode):
            return ""
        with target.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return ""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
            return "image/heic"
        return "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"\x00\x00\x01\xba") or head.startswith(b"\x00\x00\x01\xb3"):
        return "video/mpeg"
    return ""


class ExecutorGroup:
    def __init__(self, *executors):
        self.executors = executors

    def shutdown(self, wait=True, cancel_futures=False):
        for executor in self.executors:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)


def build_rerun_payload(source_task: Dict[str, Any], payload: Dict[str, Any], project_id: int) -> Dict[str, Any]:
    rerun = dict(source_task["input_json"])
    rerun.pop("collector", None)  # 历史任务兼容读取，但重跑时改用原子能力路由。
    configuration = payload.get("configuration")
    if configuration is not None:
        if not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        for key in ("source", "limits", "keyword_limits", "author_limits", "user_limits"):
            if key in configuration:
                if not isinstance(configuration[key], dict):
                    raise ValueError(f"configuration.{key} must be an object")
                rerun[key] = configuration[key]
        if "force_refresh" in configuration:
            rerun["force_refresh"] = bool(configuration["force_refresh"])
        if "topic" in configuration:
            rerun["topic"] = str(configuration["topic"] or "").strip()[:500]
    rerun["project_id"] = project_id
    rerun["created_from"] = "codex" if payload.get("created_from") == "codex" else "web"
    rerun["image_analysis"] = {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0}
    return rerun


class ResearchApplication:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        runner,
        web_dir: Path,
        keyword_provider=None,
    ):
        self.settings = settings
        self.db = db
        self.runner = runner
        self.web_dir = Path(web_dir).resolve()
        legacy_workers = max(1, int(getattr(settings, "max_workers", 1)))
        self.research_executor = ThreadPoolExecutor(
            max_workers=max(1, int(getattr(settings, "research_workers", legacy_workers))),
            thread_name_prefix="xhs-research-collector",
        )
        self.vision_executor = ThreadPoolExecutor(
            max_workers=max(1, int(getattr(settings, "vision_workers", 1))),
            thread_name_prefix="xhs-research-vision",
        )
        self.report_executor = ThreadPoolExecutor(
            max_workers=max(1, int(getattr(settings, "report_workers", 1))),
            thread_name_prefix="xhs-research-report",
        )
        self.keyword_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="xhs-research-keywords",
        )

        self.executor = ExecutorGroup(
            self.research_executor,
            self.vision_executor,
            self.report_executor,
            self.keyword_executor,
        )
        self.futures = {}
        self.futures_lock = threading.Lock()
        self.task_action_lock = threading.RLock()
        self.project_order = threading.Condition()
        self.recovery_lock = threading.Lock()
        self.submission_lock = threading.RLock()
        self.my_author_setup_lock = threading.Lock()
        self.recovery_result = None
        self.shutdown_event = threading.Event()
        self.lifecycle_lock = threading.Lock()
        self.shutdown_started = False
        self.runtime_lock_handle = None
        self.runtime_lock_key = None
        self.media_path_repair_count = 0
        self.invalid_search_card_cleanup_count = 0
        # Some API-unit tests supply a minimal settings object.  The database
        # location remains the authoritative fallback for this local-only tool.
        self.data_release = DataReleaseService(getattr(settings, "data_dir", self.db.path.parent))
        self.keyword_provider = keyword_provider

    def report_prompt_templates(self) -> Dict[str, str]:
        stored = self.db.get_app_settings().get("report_prompt_templates")
        try:
            return normalize_report_prompt_templates(stored, require_both=stored is not None)
        except ValueError:
            return default_report_prompt_templates()

    def acquire_runtime_lock(self):
        data_dir = Path(self.settings.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        lock_path = data_dir / ".workbench.lock"
        key = str(data_dir)
        with self.lifecycle_lock:
            if self.shutdown_started:
                raise RuntimeError("服务正在关闭，无法取得数据目录所有权")
            if self.runtime_lock_handle is not None:
                return
            with _RUNTIME_CLAIMS_LOCK:
                if key in _RUNTIME_CLAIMS:
                    raise RuntimeError(f"数据目录已由另一个工作台服务占用：{data_dir}")
                handle = lock_path.open("a+", encoding="utf-8")
                try:
                    acquire_file_lock(handle)
                except FileLockUnavailable as exc:
                    handle.seek(0)
                    owner = handle.read().strip()
                    handle.close()
                    detail = f"（{owner}）" if owner else ""
                    raise RuntimeError(
                        f"数据目录已由另一个工作台服务占用：{data_dir}{detail}"
                    ) from exc
                try:
                    handle.seek(0)
                    handle.truncate()
                    handle.write(f"pid={os.getpid()} port={self.settings.port}\n")
                    handle.flush()
                except Exception:
                    try:
                        release_file_lock(handle)
                    finally:
                        handle.close()
                    raise
                _RUNTIME_CLAIMS.add(key)
                self.runtime_lock_handle = handle
                self.runtime_lock_key = key

    def release_runtime_lock(self):
        with self.lifecycle_lock:
            handle = self.runtime_lock_handle
            key = self.runtime_lock_key
            self.runtime_lock_handle = None
            self.runtime_lock_key = None
        try:
            if handle is not None:
                try:
                    release_file_lock(handle)
                finally:
                    handle.close()
        finally:
            if key is not None:
                with _RUNTIME_CLAIMS_LOCK:
                    _RUNTIME_CLAIMS.discard(key)

    def shutdown(self):
        with self.lifecycle_lock:
            if self.shutdown_started:
                return
            self.shutdown_started = True
        self.signal_shutdown()
        try:
            self.executor.shutdown(wait=True, cancel_futures=True)
        finally:
            self.release_runtime_lock()

    def signal_shutdown(self):
        """Signal workers and blocking providers without releasing ownership yet."""
        self.shutdown_event.set()
        with self.futures_lock:
            task_ids = list(self.futures)
        for task_id in task_ids:
            try:
                self.runner.cancel(task_id)
            except Exception:
                pass
        with self.project_order:
            self.project_order.notify_all()

    @staticmethod
    def _keyword_reference_sources(value: Any) -> list:
        if not isinstance(value, list):
            raise ValueError("reference_sources must be an array")
        allowed = {"manual", "ai_generated"}
        sources = []
        for item in value:
            source = str(item or "").strip()
            if source not in allowed:
                raise ValueError(
                    "reference_sources must contain only: manual, ai_generated"
                )
            if source in sources:
                raise ValueError("reference_sources must not contain duplicates")
            sources.append(source)
        return sources

    def create_keyword_suggestions_task(
        self,
        project_id: int,
        reference_sources: Any,
        created_from: str = "web",
    ) -> Dict[str, Any]:
        if self.keyword_provider is None:
            raise ApiProblem(503, "AI 关键词生成功能当前不可用")
        project = self.db.get_project(project_id)
        if not project:
            raise KeyError("project not found")
        if created_from not in ("web", "codex", "test"):
            raise ValueError("created_from must be web, codex or test")
        sources = self._keyword_reference_sources(reference_sources)
        all_keywords = self.db.list_project_keywords(project_id)
        project_snapshot = {
            "name": str(project.get("name") or ""),
            "description": str(project.get("description") or ""),
        }
        keyword_snapshot = [
            {"keyword": str(item["keyword"]), "source": str(item["source"])}
            for item in all_keywords
        ]
        reference_keywords = [
            item["keyword"]
            for source in sources
            for item in keyword_snapshot
            if item["source"] == source
        ]
        payload = {
            "operation": "keyword_suggestions",
            "mode": project["research_type"],
            "project_id": int(project_id),
            "created_from": created_from,
            "topic": f"AI 生成关键词：{project_snapshot['name']}",
            "keyword_suggestions": {
                "reference_sources": sources,
                "project": project_snapshot,
                "reference_keywords": reference_keywords,
                "existing_keywords": [item["keyword"] for item in keyword_snapshot],
            },
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id,
                project["research_type"],
                created_from,
                payload,
                task_type="keyword_suggestions",
            )
            self._submit(
                self.keyword_executor,
                task_id,
                project_id,
                self.run_keyword_suggestions,
                task_id,
                payload["keyword_suggestions"],
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def run_keyword_suggestions(self, task_id: str, configuration: Dict[str, Any]):
        if not isinstance(configuration, dict):
            raise ValueError("关键词生成配置不是有效对象")
        project = configuration.get("project")
        reference_keywords = configuration.get("reference_keywords")
        existing_keywords = configuration.get("existing_keywords")
        sources = configuration.get("reference_sources")
        if not isinstance(project, dict) or not isinstance(reference_keywords, list) or not isinstance(existing_keywords, list):
            raise ValueError("关键词生成任务缺少快照")
        if not isinstance(sources, list):
            raise ValueError("关键词生成任务缺少参考来源")
        if self.keyword_provider is None:
            raise KeywordGenerationError("AI 关键词生成功能当前不可用")
        if self.shutdown_event.is_set() or self.db.is_task_cancelled(task_id):
            return
        self.db.update_task(
            task_id,
            status="running",
            current_phase="keyword_generation",
            progress_current=0,
            progress_total=1,
            error_message="",
            started_at=utcnow(),
            finished_at=None,
        )
        self.db.append_task_event(
            task_id,
            "keyword_generation",
            "started",
            {"message": "正在根据项目快照生成候选关键词"},
        )
        try:
            result = self.keyword_provider.generate(
                project,
                [str(value) for value in reference_keywords],
                [str(value) for value in existing_keywords],
                should_cancel=lambda: self.shutdown_event.is_set() or self.db.is_task_cancelled(task_id),
            )
            if self.shutdown_event.is_set() or self.db.is_task_cancelled(task_id):
                return
            response = {
                "request_id": task_id,
                "reference_sources": sources,
                **result,
            }
            self.db.update_task(
                task_id,
                status="completed",
                current_phase="completed",
                progress_current=1,
                progress_total=1,
                result_json={"keyword_suggestions": response},
                finished_at=utcnow(),
            )
            self.db.append_task_event(
                task_id,
                "completed",
                "completed",
                {"message": f"已生成 {len(result.get('keywords') or [])} 个候选关键词"},
            )
        except CodexProcessCancelled:
            if not self.db.is_task_cancelled(task_id) and not self.shutdown_event.is_set():
                self.db.update_task(
                    task_id,
                    status="cancelled",
                    current_phase="cancelled",
                    error_message="",
                    finished_at=utcnow(),
                )
                self.db.append_task_event(
                    task_id,
                    "cancelled",
                    "cancelled",
                    {"message": "AI 关键词生成已取消"},
                )
        except Exception as exc:
            if not self.db.is_task_cancelled(task_id):
                message = str(exc) or "AI 关键词生成失败"
                self.db.update_task(
                    task_id,
                    status="failed",
                    current_phase="failed",
                    error_message=message,
                    finished_at=utcnow(),
                )
                self.db.append_task_event(
                    task_id,
                    "failed",
                    "error",
                    {"message": message},
                )
        finally:
            with self.project_order:
                self.project_order.notify_all()

    def _run_in_project_order(self, task_id: str, project_id: Optional[int], method, *args):
        with self.project_order:
            while self.db.has_active_task_predecessor(task_id, project_id):
                if self.shutdown_event.is_set() or self.db.is_task_cancelled(task_id):
                    return None
                self.project_order.wait(timeout=0.25)
        if self.shutdown_event.is_set():
            return None
        try:
            return method(*args)
        finally:
            with self.project_order:
                self.project_order.notify_all()

    def _submit(self, executor, task_id: str, project_id: Optional[int], method, *args):
        future = executor.submit(self._run_in_project_order, task_id, project_id, method, *args)
        with self.futures_lock:
            self.futures[task_id] = future
        future.add_done_callback(lambda _future, value=task_id: self._forget_future(value))
        return future

    def _recovery_invocation(self, task: Dict[str, Any]):
        payload = task.get("input_json")
        if not isinstance(payload, dict):
            raise ValueError("任务输入不是有效对象")
        task_id = str(task["id"])
        project_id = int(task["project_id"]) if task.get("project_id") is not None else None
        task_type = task.get("task_type") or "research"
        if task_type == "research":
            if payload.get("operation") == "post_detail_update":
                configuration = payload.get("post_detail_update") or {}
                if not isinstance(configuration, dict):
                    raise ValueError("帖子详情更新配置不是有效对象")
                return self.research_executor, self.runner.run_post_detail_update, (
                    task_id, configuration,
                )
            if payload.get("operation") == "project_author_update":
                if project_id is None:
                    raise ValueError("项目作者批量更新任务缺少关联项目")
                configuration = payload.get("author_update_bulk") or {}
                if not isinstance(configuration, dict):
                    raise ValueError("项目作者批量更新配置不是有效对象")
                return self.research_executor, self.runner.run_project_author_update, (
                    task_id, project_id, configuration,
                )
            request = ResearchRequest.from_dict(payload)
            if request.project_id != project_id:
                raise ValueError("任务输入中的项目与任务记录不一致")
            return self.research_executor, self.runner.run, (task_id, request)
        if task_type == "vision":
            configuration = payload.get("image_analysis") or {}
            if not isinstance(configuration, dict):
                raise ValueError("图片理解配置不是有效对象")
            author_id = int(task["author_id"]) if task.get("author_id") is not None else None
            if (project_id is None) == (author_id is None):
                raise ValueError("图片理解任务必须且只能关联一个项目或作者")
            runner = self.runner.run_ocr if configuration.get("processing_method") == "ocr" else self.runner.run_vision
            if author_id is not None:
                return self.vision_executor, runner, (task_id, None, configuration, author_id)
            return self.vision_executor, runner, (task_id, project_id, configuration)
        if task_type == "ai_report":
            if payload.get("operation") == "html_presentation":
                configuration = payload.get("presentation_generation") or {}
                if not isinstance(configuration, dict):
                    raise ValueError("HTML 演示稿配置不是有效对象")
                return self.report_executor, self.runner.run_report_presentation, (
                    task_id, configuration,
                )
            configuration = payload.get("report_generation") or {}
            if not isinstance(configuration, dict):
                raise ValueError("报告生成配置不是有效对象")
            author_id = int(task["author_id"]) if task.get("author_id") is not None else None
            if project_id is not None:
                return self.report_executor, self.runner.run_ai_report, (task_id, project_id, configuration)
            if author_id is not None:
                return self.report_executor, self.runner.run_author_ai_report, (task_id, author_id, configuration)
            raise ValueError("报告任务缺少关联项目或作者")
        if task_type == "keyword_suggestions":
            if project_id is None:
                raise ValueError("关键词生成任务缺少关联项目")
            configuration = payload.get("keyword_suggestions") or {}
            if not isinstance(configuration, dict):
                raise ValueError("关键词生成配置不是有效对象")
            return self.keyword_executor, self.run_keyword_suggestions, (task_id, configuration)
        if task_type == "comments":
            configuration = payload.get("post_comments") or {}
            if not isinstance(configuration, dict):
                raise ValueError("评论采集配置不是有效对象")
            post_id = int(task["post_id"]) if task.get("post_id") is not None else None
            if post_id is None or int(configuration.get("post_id") or 0) != post_id:
                raise ValueError("评论采集任务缺少关联帖子")
            return self.research_executor, self.runner.run_post_comment_collection, (
                task_id, configuration,
            )
        raise ValueError(f"不支持恢复任务类型：{task_type}")

    def recover_interrupted_tasks(self):
        """Reconcile persisted active tasks once when a service process starts."""
        with self.recovery_lock, self.submission_lock:
            if self.recovery_result is not None:
                return {key: list(value) for key, value in self.recovery_result.items()}

            active_tasks = self.db.query(
                "SELECT * FROM tasks WHERE status IN ('queued','running','waiting_login') "
                "ORDER BY created_at ASC,id ASC"
            )
            result = {"interrupted": [], "resubmitted": [], "recovery_failed": []}

            # A running row belonged to the previous process. Retrying it from the
            # beginning could duplicate external work, so remove it as a predecessor
            # before any queued work is submitted and leave retrying to the user.
            for task in active_tasks:
                if task["status"] != "running":
                    continue
                message = (
                    "服务中断：任务在上一进程中仍处于运行状态。为避免重复执行，系统未自动重跑；"
                    "请在任务详情中手动重试。"
                )
                payload = {
                    "message": message,
                    "previous_phase": task.get("current_phase") or "running",
                    "retry": "manual",
                }
                if task.get("task_type") == "ai_report":
                    self.db.fail_report_task(
                        task["id"], message,
                        phase="failed",
                        event_phase="service_interrupted",
                        event_type="interrupted",
                        event_payload=payload,
                    )
                else:
                    self.db.update_task(
                        task["id"],
                        status="failed",
                        current_phase="failed",
                        error_message=message,
                        finished_at=utcnow(),
                    )
                    self.db.append_task_event(
                        task["id"], "service_interrupted", "interrupted", payload,
                    )
                result["interrupted"].append(task["id"])

            with self.project_order:
                self.project_order.notify_all()

            # The query order is the same topological order used by
            # has_active_task_predecessor. Submitting in that order prevents a newer
            # task from occupying a single-worker executor while waiting for an older
            # task that is still queued behind it.
            for task in active_tasks:
                if task["status"] not in ("queued", "waiting_login"):
                    continue
                try:
                    executor, method, args = self._recovery_invocation(task)
                    self.db.update_task(
                        task["id"],
                        status="queued",
                        current_phase="queued",
                        progress_current=0,
                        progress_total=0,
                        warning_count=0,
                        error_message="",
                        result_json={},
                        started_at=None,
                        finished_at=None,
                    )
                    self.db.append_task_event(
                        task["id"],
                        "service_recovered",
                        "resubmitted",
                        {
                            "message": "服务已重启，任务已按原配置重新进入队列",
                            "previous_status": task["status"],
                            "task_type": task.get("task_type") or "research",
                        },
                    )
                    project_id = (
                        int(task["project_id"])
                        if task.get("project_id") is not None
                        else None
                    )
                    self._submit(executor, task["id"], project_id, method, *args)
                    result["resubmitted"].append(task["id"])
                except Exception as exc:
                    message = f"服务重启后恢复失败：{exc}"
                    payload = {
                        "message": message,
                        "task_type": task.get("task_type") or "research",
                    }
                    if task.get("task_type") == "ai_report":
                        self.db.fail_report_task(
                            task["id"], message,
                            phase="failed",
                            event_phase="recovery_failed",
                            event_type="error",
                            event_payload=payload,
                        )
                    else:
                        self.db.update_task(
                            task["id"],
                            status="failed",
                            current_phase="failed",
                            error_message=message,
                            finished_at=utcnow(),
                        )
                        self.db.append_task_event(
                            task["id"], "recovery_failed", "error", payload,
                        )
                    result["recovery_failed"].append(task["id"])
                    with self.project_order:
                        self.project_order.notify_all()

            self.recovery_result = result
            return {key: list(value) for key, value in result.items()}

    def create_task(self, payload: Dict[str, Any]):
        payload = dict(payload)
        payload.pop("collector", None)  # 不再允许新任务绑定采集引擎。
        payload["image_analysis"] = {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0}
        raw_project_id = payload.get("project_id")
        project_id = None
        project = None
        if raw_project_id not in (None, ""):
            project_id = _integer(raw_project_id, "project_id")
            if project_id <= 0:
                raise ValueError("project_id must be a positive integer")
            project = self.db.get_project(project_id)
            if not project:
                raise KeyError("project not found")
        request = ResearchRequest.from_dict(payload)
        project_config = (project or {}).get("config_json") or {}
        if project is not None and isinstance(project_config, dict) and project_config.get("project_kind") == "my_project":
            if request.mode != "author" or len(request.author_ids) != 1 or request.user_keywords:
                raise ValueError("个人项目固定为作者调研，且必须只包含一位作者")
        policies = self.db.get_app_settings()
        try:
            max_keywords = max(1, min(int(policies.get("max_keywords_per_task", getattr(self.settings, "max_keywords_per_task", 5))), 20))
            max_authors = max(1, min(int(policies.get("max_authors_per_task", getattr(self.settings, "max_authors_per_task", 5))), 20))
        except (TypeError, ValueError):
            max_keywords = max_authors = 5
        if len(request.keywords) > max_keywords:
            raise ValueError(f"本次关键词数量为 {len(request.keywords)}，超过后台配置的单次关键词上限 {max_keywords}")
        if len(request.user_keywords) > max_keywords:
            raise ValueError(f"本次用户关键词数量为 {len(request.user_keywords)}，超过后台配置的单次关键词上限 {max_keywords}")
        if len(request.author_ids) > max_authors:
            raise ValueError(f"本次作者数量为 {len(request.author_ids)}，超过后台配置的单次作者上限 {max_authors}")
        if request.mode in ("author", "mixed"):
            remaining_author_slots = max_authors - len(request.author_ids)
            if request.user_keywords and remaining_author_slots <= 0:
                raise ValueError("已指定作者数量达到单次作者上限，无法再按关键词发现用户")
            if request.user_keywords and request.user_discovery_limit > remaining_author_slots:
                adjusted = request.to_dict()
                adjusted["user_limits"]["discovery"] = remaining_author_slots
                request = ResearchRequest.from_dict(adjusted)
        if request.mode in ("author", "mixed"):
            max_notes = max(1, int(policies.get("max_author_notes", self.settings.max_author_notes)))
            requested_author_limit = request.discovery_limit if request.mode == "author" else request.author_discovery_limit
            if requested_author_limit > max_notes:
                adjusted = request.to_dict()
                target = adjusted["limits"] if request.mode == "author" else adjusted["author_limits"]
                target["discovery"] = max_notes
                target["deep"] = min(target["deep"], max_notes)
                request = ResearchRequest.from_dict(adjusted)
        task_author_id = None
        if request.project_id is None and request.author_update_scopes and len(request.author_ids) == 1:
            row = self.db.query(
                "SELECT id FROM authors WHERE author_id=?", (request.author_ids[0],),
            )
            task_author_id = int(row[0]["id"]) if row else None
        with self.submission_lock:
            task_id = self.db.create_task(
                request.project_id, request.mode, request.created_from,
                request.to_dict(), task_type="research", author_id=task_author_id,
            )
            self._submit(
                self.research_executor, task_id, request.project_id,
                self.runner.run, task_id, request,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_project_author_update_task(
        self,
        project_id: int,
        created_from: str = "web",
        configuration: Dict[str, Any] = None,
    ):
        project = self.db.get_project(project_id)
        if not project:
            raise KeyError("project not found")
        if created_from not in ("web", "codex", "test"):
            raise ValueError("created_from must be web, codex or test")
        values = configuration or {}
        if not isinstance(values, dict):
            raise ValueError("configuration must be an object")
        allowed_scopes = {"basic_info", "preview_posts", "detailed_posts"}
        scopes = []
        for scope in values.get("scopes") or []:
            scope = str(scope or "").strip()
            if scope not in allowed_scopes:
                raise ValueError("configuration.scopes contains an invalid scope")
            if scope not in scopes:
                scopes.append(scope)
        if not scopes:
            raise ValueError("请至少选择一个更新范围")
        target = str(values.get("target") or "basic_unupdated").strip()
        if target not in ("basic_unupdated", "posts_unupdated", "all"):
            raise ValueError("configuration.target is invalid")
        max_authors = max(1, min(_integer(values.get("max_authors", 100), "configuration.max_authors"), 500))
        batch_size = max(1, min(_integer(values.get("batch_size", 10), "configuration.batch_size"), 50))
        consecutive_failure_limit = max(1, min(_integer(values.get("consecutive_failure_limit", 5), "configuration.consecutive_failure_limit"), 20))
        settings = self.db.get_app_settings()
        max_notes = max(1, int(settings.get("max_author_notes", self.settings.max_author_notes)))
        preview_limit = max(1, min(_integer(values.get("preview_limit", 20), "configuration.preview_limit"), max_notes))
        detail_limit = max(1, min(_integer(values.get("detail_limit", 5), "configuration.detail_limit"), max_notes))

        def finite_delay(key: str, fallback: float) -> float:
            try:
                return max(0.0, float(values.get(key, fallback)))
            except (TypeError, ValueError):
                raise ValueError(f"configuration.{key} must be a number")

        author_delay_min = finite_delay("author_delay_min_seconds", 1)
        author_delay_max = max(author_delay_min, finite_delay("author_delay_max_seconds", 3))
        batch_delay_min = finite_delay("batch_delay_min_seconds", 2)
        batch_delay_max = max(batch_delay_min, finite_delay("batch_delay_max_seconds", 5))
        candidates = self.db.list_project_authors(project_id)
        if target == "basic_unupdated":
            candidates = [author for author in candidates if not author.get("last_profile_fetched_at")]
        elif target == "posts_unupdated":
            candidates = [
                author for author in candidates
                if int(author.get("project_post_count") or 0) == 0
                and int(author.get("stored_post_count") or author.get("post_count") or 0) == 0
            ]
        selected = candidates[:max_authors]
        if not selected:
            raise ValueError("没有符合条件的作者需要更新")
        author_ids = [str(author["author_id"]) for author in selected if str(author.get("author_id") or "").strip()]
        if not author_ids:
            raise ValueError("符合条件的作者缺少可更新的作者 ID")
        bulk = {
            "target": target,
            "scopes": scopes,
            "author_ids": author_ids,
            "batch_size": batch_size,
            "max_authors": max_authors,
            "preview_limit": preview_limit,
            "detail_limit": detail_limit,
            "author_delay_min_seconds": author_delay_min,
            "author_delay_max_seconds": author_delay_max,
            "batch_delay_min_seconds": batch_delay_min,
            "batch_delay_max_seconds": batch_delay_max,
            "consecutive_failure_limit": consecutive_failure_limit,
        }
        payload = {
            "operation": "project_author_update",
            "mode": "author",
            "project_id": project_id,
            "created_from": created_from,
            "topic": f"批量更新项目作者：{project['name']}",
            "source": {"author_ids": author_ids, "keywords": [], "user_keywords": [], "filters": {}},
            "limits": {"discovery": preview_limit, "deep": detail_limit if "detailed_posts" in scopes else 0},
            "keyword_limits": {"discovery": 1, "deep": 0},
            "author_limits": {"discovery": preview_limit, "deep": detail_limit if "detailed_posts" in scopes else 0},
            "user_limits": {"discovery": 1},
            "image_analysis": {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0},
            "force_refresh": True,
            "author_update_bulk": bulk,
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id, "author", created_from, payload, task_type="research",
            )
            self._submit(
                self.research_executor,
                task_id,
                project_id,
                self.runner.run_project_author_update,
                task_id,
                project_id,
                bulk,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_post_detail_update_task(
        self,
        created_from: str = "web",
        configuration: Dict[str, Any] = None,
    ):
        if created_from not in ("web", "codex", "test"):
            raise ValueError("created_from must be web, codex or test")
        values = configuration or {}
        if not isinstance(values, dict):
            raise ValueError("configuration must be an object")
        mode = str(values.get("mode") or "batch").strip()
        if mode not in ("selected", "batch"):
            raise ValueError("configuration.mode must be selected or batch")
        scope = str(values.get("scope") or "global").strip()
        if scope not in ("global", "project", "author"):
            raise ValueError("configuration.scope must be global, project or author")
        scope_id = None
        if scope != "global":
            scope_id = _integer(values.get("scope_id"), "configuration.scope_id")
            if scope_id <= 0:
                raise ValueError("configuration.scope_id must be a positive integer")
        target = "selected" if mode == "selected" else str(values.get("target") or "needs_update").strip()
        if target not in ("selected", "needs_update", "preview", "all"):
            raise ValueError("configuration.target is invalid")
        max_posts = max(1, min(_integer(values.get("max_posts", 300), "configuration.max_posts"), 500))
        batch_size = max(1, min(_integer(values.get("batch_size", 10), "configuration.batch_size"), 50))
        consecutive_failure_limit = max(
            1,
            min(_integer(values.get("consecutive_failure_limit", 5), "configuration.consecutive_failure_limit"), 20),
        )

        def finite_delay(key: str, fallback: float) -> float:
            try:
                return min(3600.0, max(0.0, _finite_float(values.get(key, fallback), f"configuration.{key}")))
            except ValueError:
                raise

        settings = self.db.get_app_settings()
        post_delay_min = finite_delay(
            "post_delay_min_seconds",
            settings.get("post_delay_min_seconds", 1),
        )
        post_delay_max = max(
            post_delay_min,
            finite_delay(
                "post_delay_max_seconds",
                settings.get("post_delay_max_seconds", 3),
            ),
        )
        batch_delay_min = finite_delay(
            "batch_delay_min_seconds",
            settings.get("batch_delay_min_seconds", 2),
        )
        batch_delay_max = max(
            batch_delay_min,
            finite_delay(
                "batch_delay_max_seconds",
                settings.get("batch_delay_max_seconds", 5),
            ),
        )
        post_ids = values.get("post_ids") or []
        if not isinstance(post_ids, list):
            raise ValueError("configuration.post_ids must be an array")
        normalized_ids = list(dict.fromkeys(_integer(value, "configuration.post_ids[]") for value in post_ids))
        if mode == "selected":
            if not normalized_ids:
                raise ValueError("请至少选择一篇帖子")
            if len(normalized_ids) > 500:
                raise ValueError("单个任务最多更新 500 篇帖子")
            max_posts = len(normalized_ids)
        else:
            normalized_ids = []

        detail_ttl_days = max(1, int(settings.get("detail_ttl_days", self.settings.detail_ttl_days)))
        candidates = self.db.select_post_detail_update_candidates(
            scope,
            scope_id,
            "all" if mode == "selected" else target,
            max_posts,
            normalized_ids,
            detail_ttl_days,
        )
        if not candidates:
            raise ValueError("当前范围没有符合条件的帖子需要更新")
        snapshot_keys = (
            "id", "note_id", "note_url", "title", "note_type", "cover_url", "likes_count",
            "favorites_count", "comments_count", "publish_date", "detail_level", "author_name",
            "external_author_id",
        )
        posts = [{key: post.get(key) for key in snapshot_keys} for post in candidates]
        project_id = scope_id if scope == "project" else None
        author_id = scope_id if scope == "author" else None
        bulk = {
            "mode": mode,
            "scope": scope,
            "scope_id": scope_id,
            "target": target,
            "post_ids": [int(post["id"]) for post in posts],
            "posts": posts,
            "project_id": project_id,
            "max_posts": max_posts,
            "batch_size": batch_size,
            "post_delay_min_seconds": post_delay_min,
            "post_delay_max_seconds": post_delay_max,
            "batch_delay_min_seconds": batch_delay_min,
            "batch_delay_max_seconds": batch_delay_max,
            "consecutive_failure_limit": consecutive_failure_limit,
            "detail_ttl_days": detail_ttl_days,
        }
        task_mode = "author" if scope == "author" else "keyword"
        payload = {
            "operation": "post_detail_update",
            "mode": task_mode,
            "project_id": project_id,
            "created_from": created_from,
            "topic": "更新指定帖子详情" if mode == "selected" else "批量更新帖子详情",
            "post_detail_update": bulk,
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id, task_mode, created_from, payload, task_type="research",
                author_id=author_id,
            )
            self._submit(
                self.research_executor,
                task_id,
                project_id,
                self.runner.run_post_detail_update,
                task_id,
                bulk,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_post_comment_task(
        self,
        post_id: int,
        created_from: str = "web",
        configuration: Dict[str, Any] = None,
    ):
        if created_from not in ("web", "codex", "test"):
            raise ValueError("created_from must be web, codex or test")
        post_id = _integer(post_id, "post_id")
        if post_id <= 0:
            raise ValueError("post_id must be a positive integer")
        post = self.db.get_post(post_id)
        if not post:
            raise KeyError("post not found")
        values = configuration or {}
        if not isinstance(values, dict):
            raise ValueError("configuration must be an object")
        requested_pages = _integer(values.get("requested_pages", 1), "configuration.requested_pages")
        if requested_pages < 1 or requested_pages > 20:
            raise ValueError("评论采集页数必须在 1 到 20 页之间")
        collection_mode = str(values.get("collection_mode") or "continue").strip()
        if collection_mode not in ("continue", "refresh"):
            raise ValueError("评论采集方式必须是 continue 或 refresh")
        checkpoint = self.db.get_post_comment_checkpoint(post_id)
        checkpoint_status = str((checkpoint or {}).get("status") or "")
        if collection_mode == "continue" and checkpoint_status == "exhausted":
            raise ValueError("该帖已补充到平台当前末页，请选择“重新更新”")
        if collection_mode == "continue" and checkpoint_status == "invalid":
            raise ValueError("上次续传位置已失效，请选择“重新更新”重建")
        delay_min = _finite_float(
            values.get("page_delay_min_seconds", 1),
            "configuration.page_delay_min_seconds",
        )
        delay_max = _finite_float(
            values.get("page_delay_max_seconds", 2),
            "configuration.page_delay_max_seconds",
        )
        if delay_min < 1 or delay_max > 60 or delay_min > delay_max:
            raise ValueError("随机等待时间必须在 1 到 60 秒之间，且最短时间不能大于最长时间")
        include_sub_comments = values.get("include_sub_comments", False)
        if not isinstance(include_sub_comments, bool):
            raise ValueError("抓取楼中楼必须是布尔值")
        sub_comment_page_limit = _integer(
            values.get("sub_comment_page_limit", 20),
            "configuration.sub_comment_page_limit",
        )
        if sub_comment_page_limit < 1 or sub_comment_page_limit > 100:
            raise ValueError("楼中楼请求页数预算必须在 1 到 100 页之间")
        comment_config = {
            "post_id": post_id,
            "collection_mode": collection_mode,
            "requested_pages": requested_pages,
            "page_delay_min_seconds": delay_min,
            "page_delay_max_seconds": delay_max,
            "include_sub_comments": include_sub_comments,
            "sub_comment_page_limit": sub_comment_page_limit,
        }
        payload = {
            "operation": "post_comment_collection",
            "mode": "post",
            "created_from": created_from,
            "topic": f"补充评论：{str(post.get('title') or post.get('note_id') or '')}",
            "post_snapshot": {
                "id": post_id,
                "note_id": str(post.get("note_id") or ""),
                "title": str(post.get("title") or ""),
            },
            "post_comments": comment_config,
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                None, "post", created_from, payload,
                task_type="comments", post_id=post_id,
            )
            self._submit(
                self.research_executor, task_id, None,
                self.runner.run_post_comment_collection, task_id, comment_config,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def setup_my_author(self, payload: Dict[str, Any]):
        """Initialize the global “me” author once, optionally starting a scrape."""
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        existing_value = payload.get("author_id")
        external_value = payload.get("external_author_id")
        has_existing = existing_value not in (None, "")
        has_external = external_value not in (None, "")
        if has_existing == has_external:
            raise ValueError("请选择已有作者，或输入一个新的作者 ID")

        with self.my_author_setup_lock:
            configured = self.db.get_app_settings().get("my_author_id")
            if configured not in (None, ""):
                raise ValueError("个人作者已经设置，请到后台配置修改")

            if has_existing:
                author_id = _integer(existing_value, "author_id")
                if author_id <= 0 or not self.db.get_author(author_id):
                    raise ValueError("选择的作者不存在")
                self.db.set_app_settings({"my_author_id": author_id})
                return {"author_id": author_id, "task": None}

            external_text = str(external_value).strip()
            external_author_id = normalize_author_source(external_text)
            if external_author_id != external_text:
                raise ValueError("请输入稳定作者 ID，不要输入主页链接")
            author_id = self.db.upsert_author({"author_id": external_author_id})
            self.db.set_app_settings({"my_author_id": author_id})
            policies = self.db.get_app_settings()
            try:
                discovery = max(1, int(policies.get("default_discovery", 50)))
            except (TypeError, ValueError):
                discovery = 50
            try:
                task = self.create_task({
                    "mode": "author",
                    "created_from": "web",
                    "topic": f"初始化我的作者：{external_author_id}",
                    "source": {"author_ids": [external_author_id]},
                    "limits": {"discovery": discovery, "deep": 0},
                    "keyword_limits": {"discovery": discovery, "deep": 0},
                    "author_limits": {"discovery": discovery, "deep": 0},
                    "force_refresh": True,
                    "author_update": {"scopes": ["basic_info", "preview_posts"]},
                })
            except Exception:
                self.db.set_app_settings({"my_author_id": None})
                raise
            return {"author_id": author_id, "task": task}

    def _vision_configuration(
        self,
        overrides: Dict[str, Any] = None,
        preserve_processing_settings: bool = False,
    ):
        settings = self.db.get_app_settings()
        mode = settings.get("vision_analysis_mode", settings.get("default_analysis", "vision-selective"))
        if mode not in ("vision-selective", "vision-all"):
            mode = "vision-selective"
        configuration = {
            "mode": mode,
            "image_scopes": ["cover"],
            "vision_ratio": max(0.0, min(_finite_float(settings.get("vision_analysis_ratio", settings.get("default_vision_ratio", 0.2)), "vision_analysis_ratio"), 1.0)),
            "vision_count": max(1, min(_integer(settings.get("vision_analysis_count", settings.get("default_vision_count", 10)), "vision_analysis_count"), 300)),
            "vision_max_count": max(1, min(_integer(settings.get("vision_analysis_max_count", 30), "vision_analysis_max_count"), 300)),
            "vision_batch_size": max(1, min(_integer(settings.get("vision_analysis_batch_size", 5), "vision_analysis_batch_size"), 20)),
            "vision_model": str(settings.get("vision_model") or "").strip(),
            "vision_reasoning_effort": str(
                settings.get("vision_reasoning_effort") or "default"
            ),
            "vision_timeout_seconds": max(
                VISION_TIMEOUT_MIN_SECONDS,
                min(
                    _integer(
                        settings.get("vision_timeout_seconds", DEFAULT_VISION_TIMEOUT_SECONDS),
                        "vision_timeout_seconds",
                    ),
                    VISION_TIMEOUT_MAX_SECONDS,
                ),
            ),
            "only_unanalyzed": True,
        }
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise ValueError("configuration must be an object")
            processing_method = str(overrides.get("processing_method", "vision"))
            if processing_method not in ("vision", "ocr"):
                raise ValueError("configuration.processing_method is invalid")
            mode = overrides.get("mode", configuration["mode"])
            if mode not in ("vision-selective", "vision-all"):
                raise ValueError("configuration.mode is invalid")
            raw_image_scopes = overrides.get("image_scopes", configuration["image_scopes"])
            if not isinstance(raw_image_scopes, list) or not raw_image_scopes:
                raise ValueError("configuration.image_scopes must select at least one image range")
            image_scopes = list(dict.fromkeys(str(value) for value in raw_image_scopes))
            if any(value not in ("cover", "detail", "all") for value in image_scopes):
                raise ValueError("configuration.image_scopes is invalid")
            if "all" in image_scopes and len(image_scopes) != 1:
                raise ValueError("legacy all image scope cannot be combined")
            configuration.update({
                "mode": mode,
                "image_scopes": image_scopes,
                "vision_ratio": max(0.0, min(_finite_float(overrides.get("vision_ratio", configuration["vision_ratio"]), "configuration.vision_ratio"), 1.0)),
                "vision_count": max(1, min(_integer(overrides.get("vision_count", configuration["vision_count"]), "configuration.vision_count"), 300)),
                "vision_max_count": max(1, min(_integer(overrides.get("vision_max_count", configuration["vision_max_count"]), "configuration.vision_max_count"), 300)),
                "vision_batch_size": max(1, min(_integer(overrides.get("vision_batch_size", configuration["vision_batch_size"]), "configuration.vision_batch_size"), 20)),
            })
            if "processing_method" in overrides:
                configuration["processing_method"] = processing_method
            if preserve_processing_settings:
                frozen_model = str(overrides.get("vision_model") or "").strip()
                frozen_effort = str(
                    overrides.get("vision_reasoning_effort") or "default"
                )
                if len(frozen_model) > 200 or any(
                    character.isspace() for character in frozen_model
                ):
                    raise ValueError("configuration.vision_model is invalid")
                if frozen_effort not in VISION_REASONING_EFFORTS:
                    raise ValueError("configuration.vision_reasoning_effort is invalid")
                configuration.update({
                    "vision_model": frozen_model,
                    "vision_reasoning_effort": frozen_effort,
                    "vision_timeout_seconds": max(
                        VISION_TIMEOUT_MIN_SECONDS,
                        min(
                            _integer(
                                overrides.get(
                                    "vision_timeout_seconds",
                                    DEFAULT_VISION_TIMEOUT_SECONDS,
                                ),
                                "configuration.vision_timeout_seconds",
                            ),
                            VISION_TIMEOUT_MAX_SECONDS,
                        ),
                    ),
                })
        if configuration["mode"] == "vision-selective" and configuration["vision_max_count"] < configuration["vision_count"]:
            raise ValueError("最高处理数量不能小于最低处理数量")
        if configuration.get("processing_method") == "ocr":
            configuration.pop("vision_model", None)
            configuration.pop("vision_reasoning_effort", None)
            configuration.pop("vision_timeout_seconds", None)
        return configuration

    def create_vision_task(
        self,
        project_id: int,
        created_from: str = "web",
        overrides: Dict[str, Any] = None,
        preserve_processing_settings: bool = False,
    ):
        project = self.db.get_project(project_id)
        if not project:
            raise KeyError("project not found")
        if created_from not in ("web", "codex"):
            raise ValueError("created_from must be web or codex")
        active = [task for task in self.db.list_tasks(project_id)
                  if task["status"] in ("queued", "running", "waiting_login") and task["task_type"] == "vision"]
        if active:
            raise ActiveTaskConflict("项目已有运行中的图片理解任务")
        configuration = self._vision_configuration(overrides, preserve_processing_settings)
        payload = {
            "operation": "vision",
            "mode": project["research_type"],
            "project_id": project_id,
            "vision_scope": "project",
            "created_from": "codex" if created_from == "codex" else "web",
            "image_analysis": configuration,
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id, project["research_type"], payload["created_from"],
                payload, task_type="vision",
            )
            method = self.runner.run_ocr if configuration.get("processing_method") == "ocr" else self.runner.run_vision
            self._submit(
                self.vision_executor, task_id, project_id, method,
                task_id, project_id, configuration,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_author_vision_task(
        self,
        author_id: int,
        created_from: str = "web",
        overrides: Dict[str, Any] = None,
        preserve_processing_settings: bool = False,
    ):
        author = self.db.get_author(author_id)
        if not author:
            raise KeyError("author not found")
        if created_from not in ("web", "codex"):
            raise ValueError("created_from must be web or codex")
        active = [
            task for task in self.db.list_tasks()
            if task.get("project_id") is None
            and task.get("author_id") == author_id
            and task["status"] in ("queued", "running", "waiting_login")
            and task["task_type"] == "vision"
        ]
        if active:
            raise ActiveTaskConflict("作者已有运行中的图片理解任务")
        configuration = self._vision_configuration(overrides, preserve_processing_settings)
        payload = {
            "operation": "vision",
            "mode": "author",
            "author_id": author_id,
            "vision_scope": "author",
            "created_from": "codex" if created_from == "codex" else "web",
            "image_analysis": configuration,
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                None,
                "author",
                payload["created_from"],
                payload,
                task_type="vision",
                author_id=author_id,
            )
            method = self.runner.run_ocr if configuration.get("processing_method") == "ocr" else self.runner.run_vision
            self._submit(
                self.vision_executor,
                task_id,
                None,
                method,
                task_id,
                None,
                configuration,
                author_id,
            )
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_ai_report_task(self, project_id: int, created_from: str = "web", configuration: Dict[str, Any] = None):
        project = self.db.get_project(project_id)
        if not project:
            raise KeyError("project not found")
        if created_from not in ("web", "codex"):
            raise ValueError("created_from must be web or codex")
        if self.runner.report_provider is None:
            raise ValueError("Codex 大模型报告能力当前不可用")
        active = [
            task for task in self.db.list_tasks(project_id)
            if task["status"] in ("queued", "running", "waiting_login")
            and task["task_type"] == "ai_report"
        ]
        if active:
            raise ActiveTaskConflict("项目已有运行中的大模型报告任务")
        if configuration is not None and not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        values = configuration or {}
        sources = _normalize_report_sources(values)
        generation_context = (
            _normalize_report_generation_context(values) if "current_detail" in sources else {}
        )
        summary_snapshot = None
        if "data_summary" in sources:
            summary_id = _integer(values.get("data_summary_report_id"), "data_summary_report_id")
            summary_report = self.db.get_project_report(project_id, summary_id)
            if not summary_report or summary_report.get("generator_type") != "template" \
                    or summary_report.get("report_type") != "data_summary" \
                    or summary_report.get("status") not in ("completed", "partial"):
                raise ValueError("所选项目数据摘要不存在或尚未完成")
            summary_snapshot = _report_summary_snapshot(summary_report)
        if "current_detail" in sources:
            context_config = generation_context.get("context_config")
            posts_enabled = context_config is None or context_config["posts"]["enabled"]
            authors_enabled = bool(context_config and context_config["authors"]["enabled"])
            if not (
                (posts_enabled and int(project.get("post_count") or 0) > 0)
                or (authors_enabled and int(project.get("author_count") or 0) > 0)
            ):
                raise ValueError("当前项目没有所选明细来源可用于生成报告")
        prompt_templates = (
            normalize_report_prompt_templates(values["prompt_templates"], require_both=True)
            if "prompt_templates" in values else self.report_prompt_templates()
        )
        prompt_template_hash = report_prompt_template_hash(prompt_templates)
        report_title = str(values.get("title") or f"{project['name']} 大模型报告").strip()[:200]
        if not report_title:
            report_title = f"{project['name']} 大模型报告"
        payload = {
            "operation": "ai_report", "mode": project["research_type"], "project_id": project_id,
            "created_from": "codex" if created_from == "codex" else "web",
            "report_generation": {
                "title": report_title,
                "instructions": str(values.get("instructions") or "").strip()[:1000],
                "sources": sources,
                **({"data_summary_snapshot": summary_snapshot} if summary_snapshot else {}),
                **generation_context,
                "prompt_templates": prompt_templates,
                "prompt_template_hash": prompt_template_hash,
            },
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id, project["research_type"], payload["created_from"],
                payload, task_type="ai_report",
                _report_placeholder={
                    "title": report_title,
                    "generation_config": payload["report_generation"],
                },
            )
            try:
                self._submit(
                    self.report_executor, task_id, project_id, self.runner.run_ai_report,
                    task_id, project_id, payload["report_generation"],
                )
            except Exception as exc:
                self.db.fail_report_task(
                    task_id, f"报告任务提交失败：{exc}",
                    phase="failed",
                    event_phase="submission_failed",
                    event_payload={"message": f"报告任务提交失败：{exc}"},
                )
                raise
        return {"id": task_id, "status": "queued", "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}"}

    def create_author_ai_report_task(self, author_id: int, created_from: str = "web", configuration: Dict[str, Any] = None):
        author = self.db.get_author(author_id)
        if not author:
            raise KeyError("author not found")
        if created_from not in ("web", "codex"):
            raise ValueError("created_from must be web or codex")
        if self.runner.report_provider is None:
            raise ValueError("Codex 大模型报告能力当前不可用")
        active = self.db.query(
            """SELECT id FROM tasks WHERE project_id IS NULL AND author_id=? AND task_type='ai_report'
               AND status IN ('queued','running','waiting_login')""",
            (author_id,),
        )
        if active:
            raise ActiveTaskConflict("作者已有运行中的大模型报告任务")
        if configuration is not None and not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        values = configuration or {}
        sources = _normalize_report_sources(values)
        generation_context = (
            _normalize_report_generation_context(values) if "current_detail" in sources else {}
        )
        summary_snapshot = None
        if "data_summary" in sources:
            summary_id = _integer(values.get("data_summary_report_id"), "data_summary_report_id")
            summary_report = self.db.get_author_report(author_id, summary_id)
            if not summary_report or summary_report.get("generator_type") != "template" \
                    or summary_report.get("report_type") != "data_summary" \
                    or summary_report.get("status") not in ("completed", "partial"):
                raise ValueError("所选作者数据摘要不存在或尚未完成")
            summary_snapshot = _report_summary_snapshot(summary_report)
        if "current_detail" in sources:
            context_config = generation_context.get("context_config")
            posts_enabled = context_config is None or context_config["posts"]["enabled"]
            authors_enabled = bool(context_config and context_config["authors"]["enabled"])
            if not (authors_enabled or (posts_enabled and bool(author.get("posts")))):
                raise ValueError("当前作者没有所选明细来源可用于生成报告")
        prompt_templates = (
            normalize_report_prompt_templates(values["prompt_templates"], require_both=True)
            if "prompt_templates" in values else self.report_prompt_templates()
        )
        prompt_template_hash = report_prompt_template_hash(prompt_templates)
        author_name = author.get("display_name") or author.get("author_id") or f"作者 {author_id}"
        report_title = str(values.get("title") or f"{author_name} 大模型报告").strip()[:200]
        if not report_title:
            report_title = f"{author_name} 大模型报告"
        payload = {
            "operation": "ai_report",
            "mode": "author",
            "author_id": author_id,
            "report_scope": "author",
            "created_from": "codex" if created_from == "codex" else "web",
            "report_generation": {
                "title": report_title,
                "instructions": str(values.get("instructions") or "").strip()[:1000],
                "sources": sources,
                **({"data_summary_snapshot": summary_snapshot} if summary_snapshot else {}),
                **generation_context,
                "prompt_templates": prompt_templates,
                "prompt_template_hash": prompt_template_hash,
            },
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                None, "author", payload["created_from"], payload,
                task_type="ai_report", author_id=author_id,
                _report_placeholder={
                    "title": report_title,
                    "generation_config": payload["report_generation"],
                },
            )
            try:
                self._submit(
                    self.report_executor, task_id, None, self.runner.run_author_ai_report,
                    task_id, author_id, payload["report_generation"],
                )
            except Exception as exc:
                self.db.fail_report_task(
                    task_id, f"作者报告任务提交失败：{exc}",
                    phase="failed",
                    event_phase="submission_failed",
                    event_payload={"message": f"作者报告任务提交失败：{exc}"},
                )
                raise
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def create_report_presentation_task(
        self,
        *,
        project_id: Optional[int] = None,
        author_id: Optional[int] = None,
        report_id: int,
        created_from: str = "web",
        configuration: Optional[Dict[str, Any]] = None,
    ):
        if (project_id is None) == (author_id is None):
            raise ValueError("演示稿必须且只能关联一个项目或作者")
        if created_from not in ("web", "codex"):
            raise ValueError("created_from must be web or codex")
        if self.runner.report_provider is None:
            raise ValueError("Codex HTML 演示稿能力当前不可用")
        report = (
            self.db.get_project_report(int(project_id), report_id)
            if project_id is not None
            else self.db.get_author_report(int(author_id), report_id)
        )
        if (
            not report
            or report.get("generator_type") != "llm"
            or report.get("status") not in ("completed", "partial")
            or not str(report.get("content_markdown") or "").strip()
        ):
            raise ValueError("只有已完成且有正文的大模型报告可以制作 HTML 演示稿")
        values = normalize_presentation_configuration(configuration)
        title = values["title"] or f"{report['title']} 演示稿"
        values["title"] = title[:200]
        content = str(report["content_markdown"])
        source_report = {
            "id": int(report["id"]),
            "version": int(report.get("generator_version") or report.get("version") or 0),
            "title": str(report.get("title") or "大模型报告"),
            "generated_at": str(report.get("generated_at") or ""),
            "content_markdown": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        payload = {
            "operation": "html_presentation",
            "mode": "author" if author_id is not None else str(report.get("report_type") or "keyword"),
            "project_id": project_id,
            "author_id": author_id,
            "report_scope": "author" if author_id is not None else "project",
            "created_from": "codex" if created_from == "codex" else "web",
            "presentation_generation": {
                **values,
                "source_report": source_report,
                "prompt_version": PRESENTATION_PROMPT_VERSION,
            },
        }
        placeholder = {
            "project_report_id": report_id if project_id is not None else None,
            "author_report_id": report_id if author_id is not None else None,
            "title": values["title"],
            "page_mode": values["page_mode"],
            "generation_config": {
                **values,
                "source_report_id": report_id,
                "source_report_version": source_report["version"],
                "source_report_sha256": source_report["sha256"],
                "prompt_version": PRESENTATION_PROMPT_VERSION,
            },
        }
        with self.submission_lock:
            task_id = self.db.create_task(
                project_id,
                payload["mode"],
                payload["created_from"],
                payload,
                task_type="ai_report",
                author_id=author_id,
                _presentation_placeholder=placeholder,
            )
            try:
                self._submit(
                    self.report_executor,
                    task_id,
                    project_id,
                    self.runner.run_report_presentation,
                    task_id,
                    payload["presentation_generation"],
                )
            except Exception as exc:
                self.db.fail_report_task(
                    task_id,
                    f"HTML 演示稿任务提交失败：{exc}",
                    phase="failed",
                    event_phase="submission_failed",
                    event_payload={"message": f"HTML 演示稿任务提交失败：{exc}"},
                )
                raise
        return {
            "id": task_id,
            "status": "queued",
            "url": f"http://{self.settings.host}:{self.settings.port}/#/tasks/{task_id}",
        }

    def _forget_future(self, task_id: str):
        with self.futures_lock:
            self.futures.pop(task_id, None)

    def cancel_task(self, task_id: str):
        with self.task_action_lock:
            task = self.db.get_task(task_id, include_cancelled=True)
            if not task:
                raise KeyError("task not found")
            if task["status"] == "cancelled":
                return {"id": task_id, "status": "cancelled"}
            if task["status"] not in ("queued", "running", "waiting_login"):
                raise ValueError(f"task with status {task['status']} cannot be cancelled")
            if not self.db.cancel_task(task_id):
                raise ValueError("task cannot be cancelled")
            with self.futures_lock:
                future = self.futures.get(task_id)
            stopped_before_start = future.cancel() if future else task["status"] != "running"
            if not stopped_before_start:
                self.runner.cancel(task_id)
            with self.project_order:
                self.project_order.notify_all()
            return {"id": task_id, "status": "cancelled"}

    def resume_task(self, task_id: str):
        with self.task_action_lock:
            task = self.db.get_task(task_id, include_cancelled=True)
            if not task:
                raise KeyError("task not found")
            if task["status"] != "waiting_login":
                raise ActiveTaskConflict(f"task with status {task['status']} cannot be resumed")
            self.db.append_task_event(
                task_id,
                "manual_resume_requested",
                "resuming",
                {"message": "人工验证已完成，正在继续原任务"},
            )
            self.runner.resume(task_id)
            return {"id": task_id, "status": "resuming"}


def _handler_factory(app: ResearchApplication):
    def media_url(local_path: str):
        if not local_path:
            return ""
        try:
            target = Path(local_path).resolve()
            relative = target.relative_to(app.settings.data_dir.resolve())
            return "/media/" + "/".join(relative.parts)
        except ValueError:
            return ""

    def decorate_post(value):
        value = dict(value)
        selected_local_path = (
            value.get("media_local_path")
            if "media_original_url" in value
            else value.get("media_local_path") or value.get("cover_local_path")
        )
        value["media_url"] = media_url(selected_local_path or "")
        value["media_remote_url"] = value.get("media_original_url") or value.get("cover_url") or ""
        for item in value.get("media") or []:
            item["local_url"] = media_url(item.get("local_path", ""))
        return value

    def decorate_author(value):
        value = dict(value)
        value["avatar_local_url"] = media_url(value.get("avatar_local_path") or "")
        if value.get("posts"):
            value["posts"] = [decorate_post(post) for post in value["posts"]]
        return value

    def configured_binary_available(value: str) -> bool:
        candidate = Path(str(value or "")).expanduser()
        return candidate.is_file() or bool(shutil.which(str(value or "")))

    def collector_options():
        socai_available = configured_binary_available(app.settings.socai_bin)
        xhs_binary = getattr(app.settings, "xiaohongshu_cli_bin", "xhs")
        xhs_available = configured_binary_available(xhs_binary)
        metadata = {
            "socai": {"label": "Socai", "binary": app.settings.socai_bin, "available": socai_available},
            "xiaohongshu-cli": {"label": "xiaohongshu-cli", "binary": xhs_binary, "available": xhs_available},
            "opencli": {
                "label": "OpenCLI",
                "binary": getattr(app.settings, "opencli_bin", "opencli"),
                "available": configured_binary_available(getattr(app.settings, "opencli_bin", "opencli")),
            },
        }
        values = []
        providers = getattr(app.runner, "collectors", {})
        for provider_id, provider in providers.items():
            item = metadata.get(provider_id, {
                "label": getattr(provider, "display_name", provider_id),
                "binary": "",
                "available": True,
            })
            values.append({
                "id": provider_id,
                **item,
                "capabilities": sorted(app.runner.capability_registry.provider_capabilities(provider)),
            })
        return values

    def configured_capability_registry():
        providers = getattr(app.runner, "collectors", {})
        stored_routes = app.db.get_app_settings().get("capability_routes")
        return CapabilityRegistry(providers, routes=stored_routes)

    def capability_routes():
        return configured_capability_registry().describe_routes()

    def collector_commands():
        provider_availability = {
            value["id"]: bool(value["available"])
            for value in collector_options()
        }
        return [
            {
                **value,
                "available": provider_availability.get(value["provider_id"], False),
            }
            for value in configured_capability_registry().describe_commands()
        ]

    def vision_models():
        return list_codex_image_models(app.settings.codex_bin)

    def vision_models_response():
        try:
            return {"available": True, "models": vision_models(), "error": ""}
        except RuntimeError as exc:
            return {"available": False, "models": [], "error": str(exc)}

    def validate_vision_processing_settings(values: Dict[str, Any], current: Dict[str, Any]):
        processing_keys = {
            "vision_model", "vision_reasoning_effort", "vision_timeout_seconds",
        }
        if processing_keys.isdisjoint(values):
            return
        if "vision_model" in values:
            model = str(values["vision_model"] or "").strip()
            if len(model) > 200 or any(character.isspace() for character in model):
                raise ValueError("图片理解模型无效")
            values["vision_model"] = model
        if "vision_reasoning_effort" in values:
            effort = str(values["vision_reasoning_effort"] or "default").strip()
            if effort not in VISION_REASONING_EFFORTS:
                raise ValueError("图片理解推理强度无效")
            values["vision_reasoning_effort"] = effort
        if "vision_timeout_seconds" in values:
            timeout = _integer(values["vision_timeout_seconds"], "vision_timeout_seconds")
            if not VISION_TIMEOUT_MIN_SECONDS <= timeout <= VISION_TIMEOUT_MAX_SECONDS:
                raise ValueError(
                    f"图片理解调用超时必须在 {VISION_TIMEOUT_MIN_SECONDS}～"
                    f"{VISION_TIMEOUT_MAX_SECONDS} 秒之间"
                )
            values["vision_timeout_seconds"] = timeout

        model = str(values.get("vision_model", current["vision_model"]) or "")
        effort = str(
            values.get("vision_reasoning_effort", current["vision_reasoning_effort"])
            or "default"
        )
        if not model:
            if effort != "default":
                raise ValueError("跟随 Codex 默认模型时，推理强度必须使用模型默认值")
            return
        try:
            model_values = vision_models()
        except RuntimeError as exc:
            raise ValueError(f"当前无法验证图片理解模型：{exc}") from exc
        selected = next((item for item in model_values if item["id"] == model), None)
        if selected is None:
            raise ValueError("所选模型当前不在 Codex 图片模型目录中")
        if effort != "default" and effort not in selected["reasoning_efforts"]:
            raise ValueError("所选推理强度不受当前模型支持")

    def settings_values():
        stored = app.db.get_app_settings()
        prompt_templates = app.report_prompt_templates()
        values = {
            "host": app.settings.host, "port": app.settings.port,
            "collectors": collector_options(),
            "collector_commands": collector_commands(),
            "routing_mode": "capability",
            "capability_routes": capability_routes(),
            "socai_bin": app.settings.socai_bin,
            "xiaohongshu_cli_bin": getattr(app.settings, "xiaohongshu_cli_bin", "xhs"),
            "xiaohongshu_cookie_source": getattr(app.settings, "xiaohongshu_cookie_source", "auto"),
            "opencli_bin": getattr(app.settings, "opencli_bin", "opencli"),
            "codex_bin": app.settings.codex_bin,
            "data_dir": str(app.settings.data_dir), "detail_ttl_days": app.settings.detail_ttl_days,
            "author_ttl_days": app.settings.author_ttl_days, "max_author_notes": app.settings.max_author_notes,
            "max_keywords_per_task": int(getattr(app.settings, "max_keywords_per_task", 5)),
            "max_authors_per_task": int(getattr(app.settings, "max_authors_per_task", 5)),
            "default_keyword_author_limit": 500,
            "research_workers": int(getattr(app.settings, "research_workers", 1)),
            "vision_workers": int(getattr(app.settings, "vision_workers", 1)),
            "report_workers": int(getattr(app.settings, "report_workers", 1)),
            "my_author_id": None,
            "default_discovery": 50, "default_deep": 0,
            "vision_analysis_mode": "vision-selective", "vision_analysis_ratio": 0.2,
            "vision_analysis_count": 10, "vision_analysis_max_count": 30,
            "vision_analysis_batch_size": 5,
            "vision_model": "", "vision_reasoning_effort": "default",
            "vision_timeout_seconds": DEFAULT_VISION_TIMEOUT_SECONDS,
            "post_delay_min_seconds": 1, "post_delay_max_seconds": 3,
            "batch_delay_min_seconds": 2, "batch_delay_max_seconds": 5,
            "report_prompt_templates": prompt_templates,
            "report_prompt_defaults": default_report_prompt_templates(),
            "report_prompt_template_hash": report_prompt_template_hash(prompt_templates),
        }
        runtime_only = {
            "collectors", "collector_commands", "capability_routes", "routing_mode",
            "report_prompt_templates", "report_prompt_defaults", "report_prompt_template_hash",
        }
        values.update({
            key: value for key, value in stored.items()
            if key in values and key not in runtime_only
        })
        legacy = {
            "vision_analysis_mode": "default_analysis",
            "vision_analysis_ratio": "default_vision_ratio",
            "vision_analysis_count": "default_vision_count",
        }
        for current, old in legacy.items():
            if current not in stored and old in stored:
                values[current] = stored[old]
        if values["vision_analysis_mode"] not in ("vision-selective", "vision-all"):
            values["vision_analysis_mode"] = "vision-selective"
        values["vision_model"] = str(values.get("vision_model") or "").strip()
        values["vision_reasoning_effort"] = str(
            values.get("vision_reasoning_effort") or "default"
        )
        try:
            values["vision_timeout_seconds"] = max(
                VISION_TIMEOUT_MIN_SECONDS,
                min(int(values["vision_timeout_seconds"]), VISION_TIMEOUT_MAX_SECONDS),
            )
        except (TypeError, ValueError):
            values["vision_timeout_seconds"] = DEFAULT_VISION_TIMEOUT_SECONDS
        return values

    class Handler(BaseHTTPRequestHandler):
        server_version = "XhsResearch/0.1"

        def log_message(self, format, *args):
            return

        def _json(self, status: int, payload: Any):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._send_body(status, "application/json; charset=utf-8", body, "no-store")

        def _send_body(self, status: int, content_type: str, body: bytes, cache_control: str = "",
                       extra_headers: Optional[Dict[str, str]] = None):
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                if cache_control:
                    self.send_header("Cache-Control", cache_control)
                for key, value in (extra_headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _error(self, status: int, message: str):
            self._json(status, {"error": message})

        def _handle_exception(self, exc: Exception):
            if isinstance(exc, ApiProblem):
                return self._error(exc.status, exc.message)
            if isinstance(exc, ActiveTaskConflict):
                return self._error(409, str(exc))
            if isinstance(exc, ProjectDeleteConflict):
                return self._error(409, str(exc))
            if isinstance(exc, ProjectReferenceConflict):
                return self._json(409, exc.payload)
            if isinstance(exc, KeyError):
                return self._error(404, str(exc).strip("'\""))
            if isinstance(exc, (ValueError, json.JSONDecodeError)):
                return self._error(400, str(exc))
            traceback.print_exc(file=sys.stderr)
            return self._error(500, "internal server error")

        def _validate_request_context(self, mutating: bool = False):
            hostname = _authority_hostname(self.headers.get("Host", ""))
            if not hostname or not is_loopback_host(hostname):
                raise ApiProblem(403, "untrusted Host header")
            if mutating:
                if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
                    raise ApiProblem(403, "cross-site request is not allowed")
                origin = self.headers.get("Origin")
                if origin and not _trusted_loopback_origin(origin):
                    raise ApiProblem(403, "cross-origin request is not allowed")

        def _body(self):
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                raise ApiProblem(415, "Content-Type must be application/json")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError) as exc:
                raise ApiProblem(400, "invalid Content-Length") from exc
            if size < 0:
                raise ApiProblem(400, "invalid Content-Length")
            if size > 2_000_000:
                raise ApiProblem(413, "request body too large")
            try:
                payload = json.loads(
                    self.rfile.read(size) or b"{}",
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"invalid JSON number: {value}")
                    ),
                )
            except UnicodeDecodeError as exc:
                raise ValueError("request body must be UTF-8 JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            _require_finite_json(payload)
            return payload

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                self._validate_request_context()
                if path == "/api/health":
                    return self._json(200, {
                        "status": "ok",
                        "version": "0.2.0",
                        "api_contract": 2,
                        "runtime_locking": app.runtime_lock_handle is not None,
                        "data_dir": str(app.settings.data_dir),
                        "repaired_media_paths_on_start": app.media_path_repair_count,
                        "removed_invalid_search_cards_on_start": app.invalid_search_card_cleanup_count,
                        "routing_mode": "capability",
                        "capability_routes": capability_routes(),
                        "collectors": [
                            value["id"] for value in collector_options() if value["available"]
                        ],
                        "ai_capabilities": {
                            "keyword_suggestions": app.keyword_provider is not None,
                        },
                    })
                if path == "/api/projects":
                    return self._json(200, app.db.list_projects())
                if path == "/api/posts":
                    query = parse_qs(parsed.query)
                    if "page" not in query or "page_size" not in query:
                        return self._error(400, "page and page_size are required")
                    page_loader = getattr(app.runner, "posts_page", app.db.list_posts_page)
                    exclude_project_id = (query.get("exclude_project_id") or [None])[0]
                    page = page_loader(
                        page=_integer((query.get("page") or [1])[0], "page"),
                        page_size=_integer((query.get("page_size") or [20])[0], "page_size"),
                        query=(query.get("query") or [""])[0],
                        note_type=(query.get("type") or ["all"])[0],
                        detail=(query.get("detail") or ["all"])[0],
                        ocr=(query.get("ocr") or ["all"])[0],
                        vision=(query.get("vision") or ["all"])[0],
                        sort=(query.get("sort") or ["default"])[0],
                        exclude_project_id=(
                            None
                            if exclude_project_id in (None, "")
                            else _integer(exclude_project_id, "exclude_project_id")
                        ),
                    )
                    page["items"] = [decorate_post(value) for value in page["items"]]
                    return self._json(200, page)
                if path == "/api/authors":
                    return self._json(200, [decorate_author(value) for value in app.db.list_authors()])
                match = re.fullmatch(r"/api/projects/(\d+)", path)
                if match:
                    project = app.db.get_project(int(match.group(1)))
                    return self._json(200, project) if project else self._error(404, "project not found")
                match = re.fullmatch(r"/api/projects/(\d+)/post-coverage", path)
                if match:
                    project_id = int(match.group(1))
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    return self._json(200, app.db.project_post_coverage(project_id))
                match = re.fullmatch(r"/api/projects/(\d+)/(posts|authors|reports|tasks)", path)
                if match:
                    project_id = int(match.group(1))
                    kind = match.group(2)
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    query = parse_qs(parsed.query)
                    if kind == "posts":
                        if "page" not in query or "page_size" not in query:
                            return self._error(400, "page and page_size are required")
                        page_loader = getattr(
                            app.runner, "project_posts_page", app.db.list_project_posts_page
                        )
                        page = page_loader(
                            project_id,
                            page=_integer((query.get("page") or [1])[0], "page"),
                            page_size=_integer((query.get("page_size") or [20])[0], "page_size"),
                            query=(query.get("query") or [""])[0],
                            note_type=(query.get("type") or ["all"])[0],
                            detail=(query.get("detail") or ["all"])[0],
                            ocr=(query.get("ocr") or ["all"])[0],
                            vision=(query.get("vision") or ["all"])[0],
                            media_storage=(query.get("media_storage") or ["all"])[0],
                            popularity=(query.get("popularity") or ["all"])[0],
                            sort=(query.get("sort") or ["default"])[0],
                        )
                        page["items"] = [decorate_post(value) for value in page["items"]]
                        return self._json(200, page)
                    values = {
                        "posts": getattr(app.runner, "project_posts", app.db.list_project_posts),
                        "authors": app.db.list_project_authors,
                        "reports": app.db.list_reports,
                        "tasks": app.db.list_tasks,
                    }[kind](project_id)
                    if kind == "authors":
                        values = [decorate_author(value) for value in values]
                    return self._json(200, values)
                match = re.fullmatch(r"/api/projects/(\d+)/reference-ids", path)
                if match:
                    project_id = int(match.group(1))
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    return self._json(200, app.db.project_reference_ids(project_id))
                match = re.fullmatch(r"/api/projects/(\d+)/keywords", path)
                if match:
                    project_id = int(match.group(1))
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    return self._json(200, app.db.list_project_keywords(project_id))
                match = re.fullmatch(r"/api/projects/(\d+)/vision-status", path)
                if match:
                    project_id = int(match.group(1))
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    return self._json(200, app.runner.vision_status(project_id))
                match = re.fullmatch(r"/api/projects/(\d+)/report-status", path)
                if match:
                    project_id = int(match.group(1))
                    if not app.db.get_project(project_id):
                        return self._error(404, "project not found")
                    return self._json(200, app.runner.ai_report_status(project_id))
                match = re.fullmatch(r"/api/authors/(\d+)/vision-status", path)
                if match:
                    author_id = int(match.group(1))
                    if not app.db.get_author(author_id):
                        return self._error(404, "author not found")
                    return self._json(200, app.runner.author_vision_status(author_id))
                match = re.fullmatch(r"/api/posts/(\d+)", path)
                if match:
                    post = getattr(app.runner, "get_post", app.db.get_post)(int(match.group(1)))
                    if post:
                        post = decorate_post(post)
                    return self._json(200, post) if post else self._error(404, "post not found")
                match = re.fullmatch(r"/api/posts/(\d+)/comments", path)
                if match:
                    query = parse_qs(parsed.query)
                    result = app.db.list_post_comments(
                        int(match.group(1)),
                        page=_integer((query.get("page") or [1])[0], "page"),
                        page_size=_integer((query.get("page_size") or [20])[0], "page_size"),
                    )
                    return self._json(200, result) if result is not None else self._error(404, "post not found")
                match = re.fullmatch(r"/api/authors/(\d+)", path)
                if match:
                    author = getattr(app.runner, "author", app.db.get_author)(int(match.group(1)))
                    if author:
                        author = decorate_author(author)
                    return self._json(200, author) if author else self._error(404, "author not found")
                match = re.fullmatch(r"/api/authors/(\d+)/reports", path)
                if match:
                    author_id = int(match.group(1))
                    if not app.db.get_author(author_id):
                        return self._error(404, "author not found")
                    return self._json(200, app.db.list_author_reports(author_id))
                match = re.fullmatch(r"/api/authors/(\d+)/report-status", path)
                if match:
                    author_id = int(match.group(1))
                    if not app.db.get_author(author_id):
                        return self._error(404, "author not found")
                    return self._json(200, app.runner.author_ai_report_status(author_id))
                match = re.fullmatch(r"/api/projects/(\d+)/reports/(\d+)/presentations", path)
                if match:
                    project_id, report_id = int(match.group(1)), int(match.group(2))
                    report = app.db.get_project_report(project_id, report_id)
                    if not report:
                        return self._error(404, "report not found")
                    return self._json(
                        200,
                        app.db.list_report_presentations(project_report_id=report_id),
                    )
                match = re.fullmatch(r"/api/authors/(\d+)/reports/(\d+)/presentations", path)
                if match:
                    author_id, report_id = int(match.group(1)), int(match.group(2))
                    report = app.db.get_author_report(author_id, report_id)
                    if not report:
                        return self._error(404, "report not found")
                    return self._json(
                        200,
                        app.db.list_report_presentations(author_report_id=report_id),
                    )
                match = re.fullmatch(r"/api/report-presentations/(\d+)/html", path)
                if match:
                    presentation = app.db.get_report_presentation(int(match.group(1)))
                    if not presentation or presentation.get("status") != "completed":
                        return self._error(404, "presentation not found")
                    body = str(presentation.get("html_content") or "").encode("utf-8")
                    if not body:
                        return self._error(404, "presentation HTML not found")
                    download = (parse_qs(parsed.query).get("download") or ["0"])[0] == "1"
                    disposition = "attachment" if download else "inline"
                    return self._send_body(
                        200,
                        "text/html; charset=utf-8",
                        body,
                        "private, no-store",
                        {
                            "Content-Security-Policy": (
                                "default-src 'none'; style-src 'unsafe-inline'; "
                                "script-src 'unsafe-inline'; img-src data:; "
                                "connect-src 'none'; font-src 'none'; object-src 'none'; "
                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                            ),
                            "Content-Disposition": (
                                f'{disposition}; filename="report-presentation-{presentation["id"]}.html"'
                            ),
                        },
                    )
                if path == "/api/tasks":
                    return self._json(200, app.db.list_tasks())
                if path == "/api/stats":
                    return self._json(200, app.db.get_stats())
                if path == "/api/data-release/preview":
                    return self._json(200, app.data_release.preview())
                if path == "/api/data-releases":
                    return self._json(200, app.data_release.list_releases())
                match = re.fullmatch(r"/api/tasks/([^/]+)", path)
                if match:
                    task = app.db.get_task(match.group(1))
                    return self._json(200, task) if task else self._error(404, "task not found")
                match = re.fullmatch(r"/api/tasks/([^/]+)/events", path)
                if match:
                    after = int((parse_qs(parsed.query).get("after") or [0])[0])
                    return self._json(200, app.db.list_task_events(match.group(1), after))
                if path == "/api/settings/vision-models":
                    return self._json(200, vision_models_response())
                if path == "/api/settings":
                    return self._json(200, settings_values())
                if path.startswith("/media/"):
                    return self._serve_media(path[len("/media/"):])
                if path.startswith("/api/"):
                    return self._error(404, "api route not found")
                return self._serve_static(path)
            except Exception as exc:
                return self._handle_exception(exc)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                self._validate_request_context(mutating=True)
                payload = self._body()
                if path == "/api/projects":
                    name = str(payload.get("name", "")).strip()
                    research_type = str(payload.get("research_type", "")).strip()
                    if not name or research_type not in ("author", "keyword", "mixed"):
                        raise ValueError("name and valid research_type are required")
                    if len(name) > 200:
                        raise ValueError("name must not exceed 200 characters")
                    config = payload.get("config") or {}
                    if not isinstance(config, dict):
                        raise ValueError("config must be an object")
                    description = str(payload.get("description") or "").strip()
                    if len(description) > 2000:
                        raise ValueError("description must not exceed 2000 characters")
                    project_id = app.db.create_project(name, research_type, config, description)
                    return self._json(201, app.db.get_project(project_id))
                if path == "/api/tasks":
                    return self._json(202, app.create_task(payload))
                if path == "/api/me/setup":
                    return self._json(201, app.setup_my_author(payload))
                match = re.fullmatch(r"/api/projects/(\d+)/references", path)
                if match:
                    post_ids = payload.get("post_ids") or []
                    author_ids = payload.get("author_ids") or []
                    if not isinstance(post_ids, list):
                        raise ValueError("post_ids must be an array")
                    if not isinstance(author_ids, list):
                        raise ValueError("author_ids must be an array")
                    return self._json(200, app.db.attach_project_references(
                        int(match.group(1)),
                        [_integer(value, "post_ids[]") for value in post_ids],
                        [_integer(value, "author_ids[]") for value in author_ids],
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/keywords", path)
                if match:
                    keywords = payload.get("keywords") or []
                    if not isinstance(keywords, list):
                        raise ValueError("keywords must be an array")
                    return self._json(200, app.db.add_project_keywords(
                        int(match.group(1)),
                        keywords,
                        source=payload.get("source", "manual"),
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/keyword-suggestions", path)
                if match:
                    return self._json(202, app.create_keyword_suggestions_task(
                        int(match.group(1)),
                        payload.get("reference_sources"),
                    ))
                match = re.fullmatch(r"/api/tasks/([^/]+)/cancel", path)
                if match:
                    return self._json(200, app.cancel_task(match.group(1)))
                match = re.fullmatch(r"/api/tasks/([^/]+)/resume", path)
                if match:
                    return self._json(200, app.resume_task(match.group(1)))
                if path == "/api/settings":
                    allowed = {"default_discovery", "default_deep", "vision_analysis_mode", "vision_analysis_ratio", "vision_analysis_count", "vision_analysis_max_count", "vision_analysis_batch_size", "vision_model", "vision_reasoning_effort", "vision_timeout_seconds",
                               "detail_ttl_days", "author_ttl_days", "max_author_notes", "max_keywords_per_task", "max_authors_per_task", "default_keyword_author_limit", "my_author_id", "capability_routes", "report_prompt_templates", "xiaohongshu_cookie_source",
                               "post_delay_min_seconds", "post_delay_max_seconds", "batch_delay_min_seconds", "batch_delay_max_seconds"}
                    values = {key: value for key, value in payload.items() if key in allowed}
                    if "report_prompt_templates" in values:
                        values["report_prompt_templates"] = normalize_report_prompt_templates(
                            values["report_prompt_templates"], require_both=True,
                        )
                    if "capability_routes" in values:
                        raw_routes = values["capability_routes"]
                        if isinstance(raw_routes, list):
                            route_mapping = {}
                            for route in raw_routes:
                                if not isinstance(route, dict):
                                    raise ValueError("capability_routes entries must be objects")
                                capability = str(route.get("capability") or "").strip()
                                if not capability:
                                    raise ValueError("capability_routes capability is required")
                                route_mapping[capability] = route.get("commands")
                        elif isinstance(raw_routes, dict):
                            route_mapping = raw_routes
                        else:
                            raise ValueError("capability_routes must be an object or array")
                        values["capability_routes"] = configured_capability_registry().validate_routes(
                            route_mapping,
                        )
                    if values.get("vision_analysis_mode", "vision-selective") not in ("vision-selective", "vision-all"):
                        raise ValueError("vision_analysis_mode is invalid")
                    if "default_discovery" in values:
                        values["default_discovery"] = max(1, _integer(values["default_discovery"], "default_discovery"))
                    if "default_deep" in values:
                        values["default_deep"] = max(0, _integer(values["default_deep"], "default_deep"))
                    current_settings = settings_values()
                    validate_vision_processing_settings(values, current_settings)
                    effective_discovery = int(values.get("default_discovery", current_settings["default_discovery"]))
                    effective_deep = int(values.get("default_deep", current_settings["default_deep"]))
                    if effective_deep > effective_discovery:
                        raise ValueError("深度分析数量不能大于发现数量")
                    if "vision_analysis_ratio" in values:
                        values["vision_analysis_ratio"] = max(0.0, min(_finite_float(values["vision_analysis_ratio"], "vision_analysis_ratio"), 1.0))
                    if "vision_analysis_count" in values:
                        values["vision_analysis_count"] = max(1, min(_integer(values["vision_analysis_count"], "vision_analysis_count"), 300))
                    if "vision_analysis_max_count" in values:
                        values["vision_analysis_max_count"] = max(1, min(_integer(values["vision_analysis_max_count"], "vision_analysis_max_count"), 300))
                    if "vision_analysis_batch_size" in values:
                        values["vision_analysis_batch_size"] = max(1, min(_integer(values["vision_analysis_batch_size"], "vision_analysis_batch_size"), 20))
                    effective_min = values.get("vision_analysis_count", app.db.get_app_settings().get("vision_analysis_count", 10))
                    effective_max = values.get("vision_analysis_max_count", app.db.get_app_settings().get("vision_analysis_max_count", 30))
                    effective_mode = values.get("vision_analysis_mode", app.db.get_app_settings().get("vision_analysis_mode", "vision-selective"))
                    if effective_mode == "vision-selective" and int(effective_max) < int(effective_min):
                        raise ValueError("最高处理数量不能小于最低处理数量")
                    if "detail_ttl_days" in values:
                        values["detail_ttl_days"] = max(1, min(_integer(values["detail_ttl_days"], "detail_ttl_days"), 365))
                    if "author_ttl_days" in values:
                        values["author_ttl_days"] = max(1, min(_integer(values["author_ttl_days"], "author_ttl_days"), 365))
                    if "max_author_notes" in values:
                        values["max_author_notes"] = max(1, _integer(values["max_author_notes"], "max_author_notes"))
                    for key in (
                        "post_delay_min_seconds",
                        "post_delay_max_seconds",
                        "batch_delay_min_seconds",
                        "batch_delay_max_seconds",
                    ):
                        if key in values:
                            values[key] = min(3600.0, max(0.0, _finite_float(values[key], key)))
                    delay_settings = {**current_settings, **values}
                    if (
                        float(delay_settings["post_delay_min_seconds"])
                        > float(delay_settings["post_delay_max_seconds"])
                    ):
                        raise ValueError("帖子间隔最短秒数不能大于最长秒数")
                    if (
                        float(delay_settings["batch_delay_min_seconds"])
                        > float(delay_settings["batch_delay_max_seconds"])
                    ):
                        raise ValueError("批次间隔最短秒数不能大于最长秒数")
                    if "max_keywords_per_task" in values:
                        values["max_keywords_per_task"] = max(1, min(_integer(values["max_keywords_per_task"], "max_keywords_per_task"), 20))
                    if "max_authors_per_task" in values:
                        values["max_authors_per_task"] = max(1, min(_integer(values["max_authors_per_task"], "max_authors_per_task"), 20))
                    if "default_keyword_author_limit" in values:
                        values["default_keyword_author_limit"] = max(1, _integer(values["default_keyword_author_limit"], "default_keyword_author_limit"))
                    if "xiaohongshu_cookie_source" in values:
                        source = str(values["xiaohongshu_cookie_source"] or "auto").strip().lower()
                        if source not in XIAOHONGSHU_COOKIE_SOURCES:
                            raise ValueError("xiaohongshu_cookie_source is invalid")
                        values["xiaohongshu_cookie_source"] = source
                    if "my_author_id" in values:
                        if values["my_author_id"] in (None, ""):
                            values["my_author_id"] = None
                        else:
                            my_author_id = _integer(values["my_author_id"], "my_author_id")
                            if my_author_id <= 0 or not app.db.get_author(my_author_id):
                                raise ValueError("选择的作者不存在")
                            values["my_author_id"] = my_author_id
                    app.db.set_app_settings(values)
                    return self._json(200, settings_values())
                if path == "/api/data-release/publish":
                    if payload.get("confirm") is not True:
                        raise ValueError("需要确认后才能发布到线上")
                    return self._json(200, app.data_release.publish())
                match = re.fullmatch(r"/api/projects/(\d+)/run", path)
                if match:
                    project_id = int(match.group(1))
                    tasks = [task for task in app.db.list_tasks(project_id) if task["task_type"] == "research"]
                    if not tasks:
                        return self._error(400, "project has no previous task configuration")
                    source_task_id = str(payload.get("source_task_id", "")).strip()
                    source_task = tasks[0]
                    if source_task_id:
                        source_task = next((task for task in tasks if task["id"] == source_task_id), None)
                        if not source_task:
                            return self._error(400, "confirmed source task does not belong to project")
                    rerun = build_rerun_payload(source_task, payload, project_id)
                    if payload.get("force_refresh") is not None:
                        rerun["force_refresh"] = bool(payload["force_refresh"])
                    return self._json(202, app.create_task(rerun))
                match = re.fullmatch(r"/api/projects/(\d+)/author-updates", path)
                if match:
                    return self._json(202, app.create_project_author_update_task(
                        int(match.group(1)),
                        payload.get("created_from", "web"),
                        payload.get("configuration"),
                    ))
                if path == "/api/post-detail-updates":
                    return self._json(202, app.create_post_detail_update_task(
                        payload.get("created_from", "web"),
                        payload.get("configuration"),
                    ))
                match = re.fullmatch(r"/api/posts/(\d+)/comment-tasks", path)
                if match:
                    return self._json(202, app.create_post_comment_task(
                        int(match.group(1)),
                        payload.get("created_from", "web"),
                        payload.get("configuration") or {
                            "requested_pages": payload.get("requested_pages", 1),
                        },
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/vision", path)
                if match:
                    project_id = int(match.group(1))
                    status = app.runner.vision_status(project_id)
                    configuration = payload.get("configuration") or {}
                    processing_method = str(configuration.get("processing_method", "vision"))
                    if processing_method == "ocr":
                        if not status.get("ocr_provider_available"):
                            return self._error(400, "RapidOCR 图片识字能力当前不可用，请先安装依赖")
                        if not _selected_image_scope_pending(status, configuration, processing_method):
                            return self._error(400, "项目没有待补充 OCR 的本地图片")
                    else:
                        if not status["provider_available"]:
                            return self._error(400, "Codex 图片理解能力当前不可用，请先检查后台配置")
                        if not _selected_image_scope_pending(status, configuration, processing_method):
                            return self._error(400, "项目没有待补充理解的本地图片")
                    return self._json(202, app.create_vision_task(project_id, payload.get("created_from", "web"), payload.get("configuration")))
                match = re.fullmatch(r"/api/authors/(\d+)/vision", path)
                if match:
                    author_id = int(match.group(1))
                    if not app.db.get_author(author_id):
                        return self._error(404, "author not found")
                    status = app.runner.author_vision_status(author_id)
                    configuration = payload.get("configuration") or {}
                    processing_method = str(configuration.get("processing_method", "vision"))
                    if processing_method == "ocr":
                        if not status.get("ocr_provider_available"):
                            return self._error(400, "RapidOCR 图片识字能力当前不可用，请先安装依赖")
                        if not _selected_image_scope_pending(status, configuration, processing_method):
                            return self._error(400, "作者没有待补充 OCR 的本地图片")
                    else:
                        if not status["provider_available"]:
                            return self._error(400, "Codex 图片理解能力当前不可用，请先检查后台配置")
                        if not _selected_image_scope_pending(status, configuration, processing_method):
                            return self._error(400, "作者没有待补充理解的本地图片")
                    return self._json(202, app.create_author_vision_task(
                        author_id,
                        payload.get("created_from", "web"),
                        payload.get("configuration"),
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/ai-report", path)
                if match:
                    return self._json(202, app.create_ai_report_task(
                        int(match.group(1)), payload.get("created_from", "web"), payload.get("configuration")
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/data-summary", path)
                if match:
                    return self._json(
                        201, app.runner.create_project_data_summary(int(match.group(1)))
                    )
                match = re.fullmatch(r"/api/authors/(\d+)/ai-report", path)
                if match:
                    return self._json(202, app.create_author_ai_report_task(
                        int(match.group(1)), payload.get("created_from", "web"), payload.get("configuration")
                    ))
                match = re.fullmatch(r"/api/authors/(\d+)/data-summary", path)
                if match:
                    return self._json(
                        201, app.runner.create_author_data_summary(int(match.group(1)))
                    )
                match = re.fullmatch(r"/api/projects/(\d+)/reports/(\d+)/presentations", path)
                if match:
                    return self._json(202, app.create_report_presentation_task(
                        project_id=int(match.group(1)),
                        report_id=int(match.group(2)),
                        created_from=payload.get("created_from", "web"),
                        configuration=payload.get("configuration"),
                    ))
                match = re.fullmatch(r"/api/authors/(\d+)/reports/(\d+)/presentations", path)
                if match:
                    return self._json(202, app.create_report_presentation_task(
                        author_id=int(match.group(1)),
                        report_id=int(match.group(2)),
                        created_from=payload.get("created_from", "web"),
                        configuration=payload.get("configuration"),
                    ))
                match = re.fullmatch(r"/api/tasks/([^/]+)/retry", path)
                if match:
                    task = app.db.get_task(match.group(1))
                    if not task:
                        return self._error(404, "task not found")
                    if task["status"] not in ("failed", "partial"):
                        raise ActiveTaskConflict(
                            f"task with status {task['status']} cannot be retried"
                        )
                    payload = dict(task["input_json"])
                    if task["task_type"] == "keyword_suggestions":
                        configuration = payload.get("keyword_suggestions") or {}
                        return self._json(202, app.create_keyword_suggestions_task(
                            int(task["project_id"]),
                            configuration.get("reference_sources"),
                            "web",
                        ))
                    if task["task_type"] == "comments":
                        configuration = payload.get("post_comments") or {}
                        return self._json(202, app.create_post_comment_task(
                            int(task["post_id"]), "web", configuration,
                        ))
                    if task["task_type"] == "vision":
                        image_analysis = dict(payload.get("image_analysis") or {})
                        if "image_scopes" not in image_analysis:
                            image_analysis["image_scopes"] = ["all"]
                        if task.get("author_id") is not None and task.get("project_id") is None:
                            return self._json(202, app.create_author_vision_task(
                                int(task["author_id"]), "web", image_analysis,
                                preserve_processing_settings=True,
                            ))
                        return self._json(202, app.create_vision_task(
                            task["project_id"], "web", image_analysis,
                            preserve_processing_settings=True,
                        ))
                    if task["task_type"] == "ai_report":
                        if payload.get("operation") == "html_presentation":
                            previous = payload.get("presentation_generation") or {}
                            source = previous.get("source_report") or {}
                            presentation_config = {
                                key: previous.get(key)
                                for key in ("title", "page_mode", "instructions")
                            }
                            return self._json(202, app.create_report_presentation_task(
                                project_id=task.get("project_id"),
                                author_id=(
                                    int(task["author_id"])
                                    if task.get("author_id") is not None else None
                                ),
                                report_id=int(source.get("id") or 0),
                                created_from="web",
                                configuration=presentation_config,
                            ))
                        if task.get("author_id") is not None and task.get("project_id") is None:
                            return self._json(202, app.create_author_ai_report_task(
                                int(task["author_id"]), "web", payload.get("report_generation")
                            ))
                        return self._json(202, app.create_ai_report_task(
                            task["project_id"], "web", payload.get("report_generation")
                        ))
                    if payload.get("operation") == "project_author_update":
                        return self._json(202, app.create_project_author_update_task(
                            task["project_id"], "web", payload.get("author_update_bulk")
                        ))
                    if payload.get("operation") == "post_detail_update":
                        previous = dict(payload.get("post_detail_update") or {})
                        previous["mode"] = "selected"
                        previous["post_ids"] = list(previous.get("post_ids") or [])
                        return self._json(202, app.create_post_detail_update_task("web", previous))
                    payload["created_from"] = "web"
                    return self._json(202, app.create_task(payload))
                return self._error(404, "not found")
            except Exception as exc:
                return self._handle_exception(exc)

        def do_PATCH(self):
            path = urlparse(self.path).path
            try:
                self._validate_request_context(mutating=True)
                match = re.fullmatch(r"/api/projects/(\d+)", path)
                if not match:
                    return self._error(404, "not found")
                payload = self._body()
                name = str(payload.get("name", "")).strip()
                description = str(payload.get("description") or "").strip()
                if not name:
                    raise ValueError("name is required")
                if len(name) > 80:
                    raise ValueError("name must not exceed 80 characters")
                if len(description) > 2000:
                    raise ValueError("description must not exceed 2000 characters")
                project_id = int(match.group(1))
                if not app.db.update_project(project_id, name, description):
                    return self._error(404, "project not found")
                return self._json(200, app.db.get_project(project_id))
            except Exception as exc:
                return self._handle_exception(exc)

        def do_DELETE(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                self._validate_request_context(mutating=True)
                match = re.fullmatch(r"/api/keyword-suggestions/([A-Za-z0-9_-]+)", path)
                if match:
                    task = app.db.get_task(match.group(1), include_cancelled=True)
                    if not task or task.get("task_type") != "keyword_suggestions":
                        raise KeyError("keyword suggestion task not found")
                    return self._json(
                        200,
                        app.cancel_task(match.group(1)),
                    )
                match = re.fullmatch(r"/api/projects/(\d+)/references", path)
                if match:
                    payload = self._body()
                    post_ids = payload.get("post_ids") or []
                    author_ids = payload.get("author_ids") or []
                    if not isinstance(post_ids, list):
                        raise ValueError("post_ids must be an array")
                    if not isinstance(author_ids, list):
                        raise ValueError("author_ids must be an array")
                    return self._json(200, app.db.detach_project_references(
                        int(match.group(1)),
                        [_integer(value, "post_ids[]") for value in post_ids],
                        [_integer(value, "author_ids[]") for value in author_ids],
                        bool(payload.get("confirm_remove_author_posts")),
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)/keywords", path)
                if match:
                    payload = self._body()
                    keyword_ids = payload.get("keyword_ids") or []
                    if not isinstance(keyword_ids, list):
                        raise ValueError("keyword_ids must be an array")
                    return self._json(200, app.db.remove_project_keywords(
                        int(match.group(1)),
                        [_integer(value, "keyword_ids[]") for value in keyword_ids],
                    ))
                match = re.fullmatch(r"/api/projects/(\d+)", path)
                if not match:
                    return self._error(404, "not found")
                project_id = int(match.group(1))
                require_empty = (parse_qs(parsed.query).get("require_empty") or [""])[0].lower() in ("1", "true")
                deleted = app.db.delete_project(project_id, require_empty=require_empty)
                return self._json(200, deleted) if deleted else self._error(404, "project not found")
            except Exception as exc:
                return self._handle_exception(exc)

        def _serve_media(self, relative: str):
            root = app.settings.data_dir.resolve()
            raw_target = Path(app.settings.data_dir) / unquote(relative)
            target = raw_target.resolve()
            try:
                target.relative_to(root)
            except ValueError:
                return self._error(403, "forbidden")
            if not target.is_file():
                return self._error(404, "media not found")
            relative_target = target.relative_to(root)
            lowered_parts = [part.lower() for part in relative_target.parts]
            lowered_name = target.name.lower()
            protected_names = {
                "research.sqlite3", "research.sqlite3-wal", "research.sqlite3-shm",
                ".workbench.lock", "service.log",
            }
            if (
                lowered_name in protected_names
                or lowered_name.endswith((".sqlite", ".sqlite3", ".db", ".log", "-wal", "-shm"))
                or any(
                    part == ".socai" or part.endswith("-tmp")
                    for part in lowered_parts
                )
            ):
                return self._error(404, "media not found")
            registered = app.db.scalar(
                """SELECT 1 FROM (
                       SELECT local_path FROM media_assets
                       UNION ALL SELECT cover_local_path FROM posts
                       UNION ALL SELECT avatar_local_path FROM authors
                   ) WHERE local_path IN (?,?) LIMIT 1""",
                (str(target), str(raw_target)),
            )
            if not registered:
                return self._error(404, "media not found")
            content_type = _media_content_type(target)
            if not content_type or not content_type.startswith(("image/", "video/")):
                return self._error(404, "media not found")
            return self._serve_file(target, content_type=content_type)

        def _serve_static(self, path: str):
            relative = path.lstrip("/") or "index.html"
            target = (app.web_dir / relative).resolve()
            try:
                target.relative_to(app.web_dir)
            except ValueError:
                return self._error(403, "forbidden")
            if not target.is_file() and (relative.startswith("assets/") or Path(relative).suffix):
                return self._error(404, "static asset not found")
            if not target.is_file():
                target = app.web_dir / "index.html"
            if not target.is_file():
                return self._error(404, "web UI not found")
            return self._serve_file(target)

        def _serve_file(self, target: Path, content_type: str = ""):
            body = target.read_bytes()
            content_type = content_type or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            cache_control = ""
            if target.name == "index.html":
                cache_control = "no-cache, no-store, must-revalidate"
            elif target.parent.name == "assets" or re.search(r"\.[0-9a-f]{8,}\.", target.name):
                cache_control = "public, max-age=31536000, immutable"
            self._send_body(
                200,
                content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""),
                body,
                cache_control,
            )

    return Handler


def create_server(host: str, port: int, app: ResearchApplication, claim_runtime: bool = False):
    if not is_loopback_host(host):
        raise ValueError("XHS_RESEARCH_HOST must be a loopback address")
    class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer performs a reverse-DNS lookup here. A loopback-only
            # service does not need it, and DNS outages must not delay startup.
            TCPServer.server_bind(self)
            self.server_name = str(self.server_address[0])
            self.server_port = int(self.server_address[1])

    server_class = LoopbackThreadingHTTPServer
    try:
        if ":" in host and socket.inet_pton(socket.AF_INET6, host.strip("[]")):
            class IPv6ThreadingHTTPServer(LoopbackThreadingHTTPServer):
                address_family = socket.AF_INET6
            server_class = IPv6ThreadingHTTPServer
    except OSError:
        pass
    server = server_class((host.strip("[]"), port), _handler_factory(app))
    if claim_runtime:
        try:
            app.acquire_runtime_lock()
            app.invalid_search_card_cleanup_count = app.db.initialize()
            app.media_path_repair_count = app.db.rebase_local_media_paths(app.settings.data_dir)
            app.recover_interrupted_tasks()
        except Exception:
            server.server_close()
            app.shutdown()
            raise
    return server
