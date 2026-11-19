from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import random
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .ai_reporting import (
    build_ai_report_evidence,
    normalize_report_context_config,
    normalize_report_prompt_templates,
    report_context_detail,
    report_prompt_template_hash,
)
from .data_summary import build_author_data_summary, build_project_data_summary
from .codex_process import CodexProcessCancelled
from .collector import (
    CapabilityRegistry,
    CollectorError,
    LIST_AUTHOR_POSTS,
    READ_AUTHOR_PROFILE,
    READ_AUTHOR_POST_DETAILS,
    READ_KEYWORD_POST_DETAILS,
    READ_POST_COMMENTS,
    READ_POST_SUB_COMMENTS,
    READ_POST_DETAIL,
    DOWNLOAD_MEDIA,
    SEARCH_POSTS_BY_KEYWORD,
    SEARCH_USERS_BY_KEYWORD,
)
from .db import Database, utcnow
from .models import ResearchRequest
from .scoring import score_posts
from .socai import normalize_socai_result
from .report_presentation import (
    PRESENTATION_PROMPT_VERSION,
    generate_presentation_deck,
    normalize_presentation_configuration,
    render_presentation_html,
)
from .vision import DEFAULT_VISION_TIMEOUT_SECONDS, select_vision_candidates
from .vision_state import IMAGE_SCOPES, media_matches_scope, resolve_current_vision


def configured_image_scopes(configuration: Dict[str, Any]) -> List[str]:
    raw = configuration.get("image_scopes")
    if raw is None:
        return ["all"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("图片范围至少选择一项")
    scopes = list(dict.fromkeys(str(value) for value in raw))
    if any(value not in (*IMAGE_SCOPES, "all") for value in scopes):
        raise ValueError("图片范围无效")
    return scopes


def provider_vision_cache_key(provider, image_paths: List[str], image_scope: str) -> str:
    parameters = inspect.signature(provider.cache_key).parameters
    if "image_scope" in parameters:
        return str(provider.cache_key(image_paths, image_scope))
    cache_key = str(provider.cache_key(image_paths))
    return cache_key if image_scope == "all" else f"{cache_key}:{image_scope}"


def provider_vision_model_identity(provider) -> str:
    return str(
        getattr(provider, "persisted_model_identity", None)
        or getattr(provider, "model", None)
        or "default"
    )


class TaskCancelled(RuntimeError):
    pass


class _HumanInterventionRetryFailed(RuntimeError):
    """Preserve the provider error while telling the router a human retry already ran."""

    def __init__(self, error: Exception):
        super().__init__(str(error))
        self.error = error


class TaskRunner:
    def __init__(self, db: Database, socai=None, vision_provider=None, ocr_provider=None, report_provider=None,
                 vision_schema: Optional[Path] = None, detail_ttl_days: int = 30,
                 author_ttl_days: int = 7, login_retry_interval: float = 15.0,
                 collector=None, collectors=None, default_collector: str = ""):
        self.db = db
        legacy_collector = collector if collector is not None else socai
        if collectors is not None:
            self.collectors = dict(collectors)
        elif legacy_collector is not None:
            provider_id = str(getattr(legacy_collector, "provider_id", "socai"))
            self.collectors = {provider_id: legacy_collector}
        else:
            self.collectors = {}
        self.default_collector = default_collector or (
            next(iter(self.collectors)) if self.collectors else "socai"
        )
        self.collector = self.collectors.get(self.default_collector) or legacy_collector
        self.socai = self.collectors.get("socai") or self.collector  # 兼容已有测试和第三方调用方。
        self.capability_registry = CapabilityRegistry(self.collectors)
        self.vision_provider = vision_provider
        self.ocr_provider = ocr_provider
        self.report_provider = report_provider
        self.vision_schema = vision_schema or Path(__file__).with_name("vision-schema.json")
        self.vision_batch_schema = Path(__file__).with_name("vision-batch-schema.json")
        self.detail_ttl_days = detail_ttl_days
        self.author_ttl_days = author_ttl_days
        self.login_retry_interval = max(0.0, float(login_retry_interval))
        self.cancel_events = {}
        self.wake_events = {}
        self.cancel_lock = threading.Lock()

    def _vision_provider_for(self, configuration: Optional[Dict[str, Any]] = None):
        provider = self.vision_provider
        configure = getattr(provider, "configured", None)
        if provider is None or not callable(configure):
            return provider
        values = self.db.get_app_settings() if configuration is None else configuration
        return configure(
            model=str(values.get("vision_model") or ""),
            reasoning_effort=str(values.get("vision_reasoning_effort") or "default"),
            timeout=float(values.get("vision_timeout_seconds", DEFAULT_VISION_TIMEOUT_SECONDS)),
        )

    def _ocr_provider_for(self, configuration: Optional[Dict[str, Any]] = None):
        return self.ocr_provider

    @staticmethod
    def _provider_available(provider) -> bool:
        return bool(provider and getattr(provider, "available", True))

    def cancel(self, task_id: str):
        with self.cancel_lock:
            event = self.cancel_events.setdefault(task_id, threading.Event())
            event.set()
            self.wake_events.setdefault(task_id, threading.Event()).set()

    def resume(self, task_id: str):
        """Wake an interrupted collector call after a person completes verification."""
        with self.cancel_lock:
            self.wake_events.setdefault(task_id, threading.Event()).set()

    def _cancel_event(self, task_id: str):
        with self.cancel_lock:
            return self.cancel_events.setdefault(task_id, threading.Event())

    def _wake_event(self, task_id: str):
        with self.cancel_lock:
            return self.wake_events.setdefault(task_id, threading.Event())

    def _clear_task_signals(self, task_id: str):
        with self.cancel_lock:
            self.cancel_events.pop(task_id, None)
            self.wake_events.pop(task_id, None)

    def _is_cancelled(self, task_id: str) -> bool:
        return self._cancel_event(task_id).is_set() or self.db.is_task_cancelled(task_id)

    def _ensure_active(self, task_id: str):
        if self._is_cancelled(task_id):
            raise TaskCancelled(task_id)

    def _collector_call(self, task_id: str, collector, method, *args, wait_for_login: bool = True):
        resume_phase = None
        manual_resume_retry = False
        while True:
            self._ensure_active(task_id)
            cancellation_scope = getattr(collector, "cancellation_scope", None)
            try:
                if cancellation_scope:
                    with cancellation_scope(lambda: self._is_cancelled(task_id)):
                        result = method(*args)
                else:
                    result = method(*args)
            except Exception as raw_exc:
                if isinstance(raw_exc, TaskCancelled):
                    raise
                if self._is_cancelled(task_id):
                    raise TaskCancelled(task_id) from raw_exc
                if resume_phase is not None and manual_resume_retry:
                    raise _HumanInterventionRetryFailed(raw_exc) from raw_exc
                if not isinstance(raw_exc, CollectorError) or raw_exc.code not in (
                    "login_required", "verification_required",
                ):
                    if resume_phase is not None:
                        self.db.update_task(
                            task_id,
                            status="running",
                            current_phase=resume_phase,
                            error_message="",
                            finished_at=None,
                        )
                    raise
                if not wait_for_login:
                    raise
                if resume_phase is None:
                    task = self.db.get_task(task_id, include_cancelled=True) or {}
                    resume_phase = task.get("current_phase") or "discovery"
                    self.db.update_task(
                        task_id,
                        status="waiting_login",
                        current_phase="waiting_login",
                        error_message=str(raw_exc),
                        finished_at=None,
                    )
                    self.db.append_task_event(
                        task_id,
                        "waiting_login",
                        "waiting",
                        {
                            "message": f"需要为 {getattr(collector, 'display_name', '采集 CLI')} 完成人工登录或验证；完成后可立即继续任务",
                            "code": raw_exc.code,
                            "retry_interval_seconds": self.login_retry_interval,
                        },
                    )
                wake_event = self._wake_event(task_id)
                manual_resume_retry = wake_event.wait(self.login_retry_interval)
                wake_event.clear()
                self._ensure_active(task_id)
                if manual_resume_retry:
                    self.db.update_task(
                        task_id,
                        status="running",
                        current_phase=resume_phase,
                        error_message="",
                        finished_at=None,
                    )
                continue

            consume_login_verification = getattr(collector, "consume_login_verification", None)
            if consume_login_verification:
                verification = consume_login_verification()
                if verification:
                    self.db.append_task_event(
                        task_id,
                        "login_verified",
                        "success",
                        {
                            "message": "已验证小红书非访客登录态",
                            "provider": verification.get("provider"),
                            "cookie_source": verification.get("cookie_source"),
                        },
                    )

            self._ensure_active(task_id)
            if resume_phase is not None:
                self.db.update_task(
                    task_id,
                    status="running",
                    current_phase=resume_phase,
                    error_message="",
                    finished_at=None,
                )
                self.db.append_task_event(
                    task_id,
                    "login_resumed",
                    "resumed",
                    {"message": "人工登录或验证已通过，任务继续执行", "resume_phase": resume_phase},
                )
            return result

    def _normalize_collector_result(self, collector, raw, source_type: str, source_value: str):
        normalizer = getattr(collector, "normalize_result", None)
        if normalizer:
            return normalizer(raw, source_type, source_value)
        return normalize_socai_result(raw, source_type, source_value)

    def _route_capability(self, task_id: str, capability: str, args: tuple, source: str,
                          source_type: str, collector_usage: Dict[str, Dict[str, int]],
                          capability_usage: Dict[str, Dict[str, Any]],
                          capability_registry: Optional[CapabilityRegistry] = None):
        registry = capability_registry or self.capability_registry
        candidates = registry.command_candidates(capability)
        if not candidates:
            raise CollectorError(f"当前没有提供方支持原子能力：{capability}", "collector_capability_unavailable")
        failures = []
        capability_stats = capability_usage.setdefault(capability, {
            "attempts": 0, "successes": 0, "failures": 0, "providers": {},
        })
        for candidate_index, (command, collector, method) in enumerate(candidates):
            provider_id = command.provider_id
            provider_stats = collector_usage.setdefault(provider_id, {"calls": 0, "successes": 0, "failures": 0})
            provider_capability_stats = capability_stats["providers"].setdefault(
                provider_id, {"attempts": 0, "successes": 0, "failures": 0},
            )
            provider_stats["calls"] += 1
            capability_stats["attempts"] += 1
            provider_capability_stats["attempts"] += 1
            after_human_intervention = False
            if not callable(method):
                exc = CollectorError(
                    f"{getattr(collector, 'display_name', provider_id)} 未实现能力 {capability}",
                    "collector_capability_unavailable",
                )
            else:
                try:
                    raw = self._collector_call(
                        task_id,
                        collector,
                        method,
                        *args,
                        wait_for_login=True,
                    )
                    provider_stats["successes"] += 1
                    capability_stats["successes"] += 1
                    provider_capability_stats["successes"] += 1
                    capability_stats["selected_provider"] = provider_id
                    capability_stats["selected_command"] = command.id
                    self.db.append_task_event(task_id, "capability_router", "provider_completed", {
                        "message": f"{command.label} 已完成 {capability}：{source}",
                        "collector": provider_id,
                        "capability": capability,
                        "command": command.id,
                        "instruction": command.instruction,
                        "source_type": source_type,
                        "source": source,
                    })
                    return provider_id, collector, raw
                except TaskCancelled:
                    raise
                except _HumanInterventionRetryFailed as retry_exc:
                    after_human_intervention = True
                    raw_exc = retry_exc.error
                    exc = raw_exc if isinstance(raw_exc, CollectorError) else CollectorError(
                        str(raw_exc), f"{provider_id.replace('-', '_')}_failed",
                    )
                except Exception as raw_exc:
                    exc = raw_exc if isinstance(raw_exc, CollectorError) else CollectorError(
                        str(raw_exc), f"{provider_id.replace('-', '_')}_failed",
                    )
            provider_stats["failures"] += 1
            capability_stats["failures"] += 1
            provider_capability_stats["failures"] += 1
            failures.append((provider_id, collector, exc, method, command))
            self.db.append_task_event(task_id, "capability_router", "provider_failed", {
                "message": (
                    f"人工处理后，{getattr(collector, 'display_name', provider_id)} 重试仍未完成 {capability}：{exc}"
                    if after_human_intervention
                    else f"{getattr(collector, 'display_name', provider_id)} 未完成 {capability}：{exc}"
                ),
                "collector": provider_id,
                "capability": capability,
                "command": command.id,
                "instruction": command.instruction,
                "source_type": source_type,
                "source": source,
                "code": exc.code,
                "after_human_intervention": after_human_intervention,
            })
            if after_human_intervention and candidate_index + 1 < len(candidates):
                next_command = candidates[candidate_index + 1][0]
                self.db.append_task_event(task_id, "capability_router", "provider_fallback", {
                    "message": f"人工处理后重试仍失败，{capability} 将降级为 {next_command.label}",
                    "capability": capability,
                    "source_type": source_type,
                    "source": source,
                    "from_command": command.id,
                    "to_command": next_command.id,
                    "trigger": "human_retry_failed",
                })
        detail = "；".join(
            f"{provider_id}: {exc}"
            for provider_id, _collector, exc, _method, _command in failures
        )
        raise CollectorError(f"没有提供方完成 {capability}（{source}）：{detail}", "all_collectors_failed")

    def _collect_source(self, task_id: str, stage: str, source: str, source_type: str,
                        limit: int, filters: Dict[str, str],
                        collector_usage: Dict[str, Dict[str, int]],
                        capability_usage: Dict[str, Dict[str, Any]],
                        capability_registry: Optional[CapabilityRegistry] = None):
        if source_type == "author":
            capability = LIST_AUTHOR_POSTS if stage == "preview" else READ_AUTHOR_POST_DETAILS
            args = (source, limit, True) if stage == "preview" else (source, limit, True, True)
        else:
            capability = SEARCH_POSTS_BY_KEYWORD if stage == "preview" else READ_KEYWORD_POST_DETAILS
            args = (source, limit, filters, True) if stage == "preview" else (source, limit, filters, True, True)
        provider_id, collector, raw = self._route_capability(
            task_id, capability, args, source, source_type, collector_usage, capability_usage,
            capability_registry,
        )
        normalized = self._normalize_collector_result(collector, raw, source_type, source)
        for kind in ("cards", "notes"):
            for item in normalized.get(kind) or []:
                item["_collector_id"] = provider_id
                item["_collector_ids"] = [provider_id]
        return normalized

    @staticmethod
    def _extend_warnings(target: List[str], values):
        for value in values or []:
            message = str(value or "").strip()
            if message and message not in target:
                target.append(message)

    def _policy_snapshot(self) -> Dict[str, int]:
        """Read mutable refresh settings once when a research task starts."""
        settings = self.db.get_app_settings()

        def integer(key: str, fallback: int) -> int:
            try:
                return int(settings.get(key, fallback))
            except (TypeError, ValueError):
                return fallback

        return {
            "detail_ttl_days": integer("detail_ttl_days", self.detail_ttl_days),
            "author_ttl_days": integer("author_ttl_days", self.author_ttl_days),
            "max_author_notes": max(1, integer("max_author_notes", 300)),
        }

    def _capability_registry_snapshot(self) -> CapabilityRegistry:
        """在任务开始时固定本次业务能力到采集指令的映射。"""
        stored = self.db.get_app_settings().get("capability_routes")
        return CapabilityRegistry(self.collectors, routes=stored)

    def _paginated_author_preview_registry(
        self,
        registry: CapabilityRegistry,
    ) -> CapabilityRegistry:
        """批量更新作者帖子时，优先使用当前路由内支持分页的提供方。"""
        routes = {
            capability: list(commands)
            for capability, commands in registry.routes.items()
        }
        commands = routes.get(LIST_AUTHOR_POSTS, [])
        paginated = [
            command_id
            for command_id in commands
            if registry.commands.get(command_id)
            and registry.commands[command_id].provider_id == "xiaohongshu-cli"
        ]
        if not paginated or commands[:len(paginated)] == paginated:
            return registry
        routes[LIST_AUTHOR_POSTS] = paginated + [
            command_id for command_id in commands if command_id not in paginated
        ]
        return CapabilityRegistry(self.collectors, routes=routes)

    def _provider_call(self, task_id: str, method, *args):
        try:
            return method(*args, should_cancel=lambda: self._is_cancelled(task_id))
        except TypeError as exc:
            # Keep lightweight test/custom providers compatible while every
            # bundled Codex provider supports the cancellation callback.
            if "should_cancel" not in str(exc):
                raise
            return method(*args)
        except CodexProcessCancelled as exc:
            raise TaskCancelled(task_id) from exc

    def _report_provider_call(self, task_id: str, project: Dict[str, Any],
                              evidence: Dict[str, Any], instructions: str,
                              prompt_templates: Dict[str, str]):
        method = self.report_provider.generate
        pipeline_metadata: Dict[str, Any] = {}
        progress_lock = threading.Lock()

        def on_progress(payload: Dict[str, Any]):
            with progress_lock:
                self._ensure_active(task_id)
                current = max(0, int(payload.get("current") or 0))
                total = max(0, int(payload.get("total") or 0))
                self.db.update_task(
                    task_id,
                    status="running",
                    current_phase="report_generation",
                    progress_current=current,
                    progress_total=total,
                )
                event = {
                    "message": str(payload.get("message") or "正在生成大模型报告"),
                    "current": current,
                    "total": total,
                    "stage": payload.get("stage"),
                    "chunk_count": payload.get("chunk_count"),
                    "cache_hits": payload.get("cache_hits", 0),
                }
                self.db.append_task_event(task_id, "report_generation", "progress", event)
                for key in ("chunk_count", "cache_hits", "input_chars", "final_input_chars", "final_diagnostics", "prompt_template_hash"):
                    if key in payload:
                        pipeline_metadata[key] = payload[key]

        def cache_save(cache_key: str, chunk_index: int, input_chars: int, status: str,
                       result=None, diagnostics=None, error_message: str = ""):
            self.db.save_report_chunk(
                task_id,
                chunk_index,
                cache_key,
                input_chars,
                status,
                result,
                diagnostics,
                error_message,
            )

        kwargs = {}
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "should_cancel" in parameters:
            kwargs["should_cancel"] = lambda: self._is_cancelled(task_id)
        if "on_progress" in parameters:
            kwargs["on_progress"] = on_progress
        if "cache_get" in parameters:
            kwargs["cache_get"] = self.db.get_cached_report_chunk
        if "cache_save" in parameters:
            kwargs["cache_save"] = cache_save
        if "prompt_templates" in parameters:
            kwargs["prompt_templates"] = prompt_templates
        try:
            content = method(project, evidence, instructions, **kwargs)
        except CodexProcessCancelled as exc:
            raise TaskCancelled(task_id) from exc
        return content, pipeline_metadata

    def _phase(self, task_id: str, phase: str, current: int = 0, total: int = 0, message: str = ""):
        self._ensure_active(task_id)
        self.db.update_task(task_id, status="running", current_phase=phase, progress_current=current, progress_total=total)
        self.db.append_task_event(task_id, phase, "progress", {"current": current, "total": total, "message": message})

    def _ingest_profile(self, project_id: Optional[int], task_id: str, profile: Dict[str, Any],
                        relation="discovered", author_ttl_days: Optional[int] = None,
                        force_refresh: bool = False):
        if not profile or not profile.get("author_id"):
            return None
        author_id = str(profile["author_id"])
        ttl_days = self.author_ttl_days if author_ttl_days is None else int(author_ttl_days)
        fresh = not force_refresh and self.db.author_profile_is_fresh(author_id, ttl_days)
        data = ({
            "author_id": author_id,
            "display_name": profile.get("display_name", ""),
            "profile_url": profile.get("profile_url", ""),
        } if fresh else profile)
        author_pk = self.db.upsert_author(data)
        if project_id is not None:
            self.db.attach_author_to_project(project_id, author_pk, relation, task_id)
        if not fresh:
            self.db.mark_author_profile_fetched(author_pk)
        return author_pk

    def _run_author_update(self, task_id: str, request: ResearchRequest,
                           warnings: List[str], collector_usage: Dict[str, Dict[str, int]],
                           capability_usage: Dict[str, Dict[str, Any]],
                           capability_registry: CapabilityRegistry,
                           runtime_policy: Dict[str, int]):
        author_id = request.author_ids[0]
        scopes = set(request.author_update_scopes)
        if "preview_posts" in scopes and request.discovery_limit > 30:
            paginated_registry = self._paginated_author_preview_registry(capability_registry)
            if paginated_registry is not capability_registry:
                capability_registry = paginated_registry
                self.db.append_task_event(task_id, "capability_router", "route_adjusted", {
                    "message": "批量预览超过 30 篇，已优先使用支持主页分页的采集指令",
                    "capability": LIST_AUTHOR_POSTS,
                    "requested_limit": request.discovery_limit,
                    "commands": capability_registry.routes.get(LIST_AUTHOR_POSTS, []),
                })
        if "basic_info" in scopes:
            self._phase(task_id, "author_profile", 0, 1, "开始更新作者基础信息")
            provider_id, collector, raw = self._route_capability(
                task_id,
                READ_AUTHOR_PROFILE,
                (author_id,),
                author_id,
                "author",
                collector_usage,
                capability_usage,
                capability_registry,
            )
            normalized = self._normalize_collector_result(collector, raw, "author", author_id)
            self._extend_warnings(warnings, normalized.get("warnings"))
            self._ingest_profile(
                None,
                task_id,
                normalized.get("profile") or {"author_id": author_id},
                "author_update",
                runtime_policy["author_ttl_days"],
                force_refresh=True,
            )
            capability_usage[READ_AUTHOR_PROFILE]["selected_provider"] = provider_id
            self._phase(task_id, "author_profile", 1, 1, "作者基础信息已更新")

        if "preview_posts" in scopes:
            self._phase(task_id, "preview", 0, 1, "开始批量更新帖子基础信息")
            normalized = self._collect_source(
                task_id,
                "preview",
                author_id,
                "author",
                request.discovery_limit,
                request.filters,
                collector_usage,
                capability_usage,
                capability_registry,
            )
            self._extend_warnings(warnings, normalized.get("warnings"))
            # 帖子更新与作者资料更新是独立操作；帖子里的署名不覆盖作者主数据。
            cards = [{**item, "author": "", "author_url": ""} for item in normalized.get("cards") or []]
            self._ingest_cards(request.project_id, task_id, cards, attach_to_project=False)
            self._phase(task_id, "preview", 1, 1, "帖子基础信息已批量更新")

        if "detailed_posts" in scopes:
            self._phase(task_id, "deep_scan", 0, 1, "开始补足作者帖子详情")
            normalized = self._collect_source(
                task_id,
                "deep",
                author_id,
                "author",
                request.deep_limit,
                request.filters,
                collector_usage,
                capability_usage,
                capability_registry,
            )
            self._extend_warnings(warnings, normalized.get("warnings"))
            # 帖子详情与作者资料是独立操作；帖子里的署名不覆盖作者主数据。
            cards = [{**item, "author": "", "author_url": ""} for item in normalized.get("cards") or []]
            notes = [{**item, "author": "", "author_url": ""} for item in normalized.get("notes") or []]
            self._ingest_cards(request.project_id, task_id, cards, attach_to_project=False)
            warnings.extend(self._ingest_notes(request.project_id, task_id, notes, attach_to_project=False))
            self._phase(task_id, "deep_scan", 1, 1, "作者帖子详情已补足")

        posts = self.db.list_task_posts(task_id)
        summary = {
            "post_count": len(posts),
            "author_count": 1,
            "author_update_scopes": request.author_update_scopes,
            "warning_count": len(warnings),
            "routing_mode": "capability",
            "collector_usage": collector_usage,
            "capability_usage": capability_usage,
            "capability_routes": capability_registry.describe_routes(),
        }
        status = "partial" if warnings else "completed"
        self._ensure_active(task_id)
        task = self.db.get_task(task_id, include_cancelled=True) or {}
        summary_author_id = int(task["author_id"]) if task.get("author_id") is not None else None
        if summary_author_id is not None:
            self._complete_task_with_data_summary(
                task_id,
                author_id=summary_author_id,
                status=status,
                result=summary,
                warnings=warnings,
                operation="author_update",
                task_type="research",
            )
        else:
            self.db.update_task(
                task_id,
                status=status,
                current_phase="completed",
                progress_current=1,
                progress_total=1,
                warning_count=len(warnings),
                error_message="",
                result_json=summary,
                finished_at=utcnow(),
            )
            self.db.append_task_event(task_id, "completed", status, {"summary": summary, "warnings": warnings})

    def _author_update_step(
        self,
        task_id: str,
        project_id: Optional[int],
        author_id: str,
        scopes: set,
        preview_limit: int,
        detail_limit: int,
        warnings: List[str],
        collector_usage: Dict[str, Dict[str, int]],
        capability_usage: Dict[str, Dict[str, Any]],
        capability_registry: CapabilityRegistry,
        runtime_policy: Dict[str, int],
    ):
        if "preview_posts" in scopes and preview_limit > 30:
            paginated_registry = self._paginated_author_preview_registry(capability_registry)
            if paginated_registry is not capability_registry:
                capability_registry = paginated_registry
                self.db.append_task_event(task_id, "capability_router", "route_adjusted", {
                    "message": "批量预览超过 30 篇，已优先使用支持主页分页的采集指令",
                    "capability": LIST_AUTHOR_POSTS,
                    "requested_limit": preview_limit,
                    "commands": capability_registry.routes.get(LIST_AUTHOR_POSTS, []),
                    "author_id": author_id,
                })

        if "basic_info" in scopes:
            provider_id, collector, raw = self._route_capability(
                task_id,
                READ_AUTHOR_PROFILE,
                (author_id,),
                author_id,
                "author",
                collector_usage,
                capability_usage,
                capability_registry,
            )
            normalized = self._normalize_collector_result(collector, raw, "author", author_id)
            self._extend_warnings(warnings, normalized.get("warnings"))
            self._ingest_profile(
                None,
                task_id,
                normalized.get("profile") or {"author_id": author_id},
                "author_update",
                runtime_policy["author_ttl_days"],
                force_refresh=True,
            )
            capability_usage[READ_AUTHOR_PROFILE]["selected_provider"] = provider_id

        if "preview_posts" in scopes:
            normalized = self._collect_source(
                task_id,
                "preview",
                author_id,
                "author",
                preview_limit,
                {},
                collector_usage,
                capability_usage,
                capability_registry,
            )
            self._extend_warnings(warnings, normalized.get("warnings"))
            cards = [{**item, "author": "", "author_url": ""} for item in normalized.get("cards") or []]
            self._ingest_cards(project_id, task_id, cards, attach_to_project=False)

        if "detailed_posts" in scopes:
            normalized = self._collect_source(
                task_id,
                "deep",
                author_id,
                "author",
                detail_limit,
                {},
                collector_usage,
                capability_usage,
                capability_registry,
            )
            self._extend_warnings(warnings, normalized.get("warnings"))
            cards = [{**item, "author": "", "author_url": ""} for item in normalized.get("cards") or []]
            notes = [{**item, "author": "", "author_url": ""} for item in normalized.get("notes") or []]
            self._ingest_cards(project_id, task_id, cards, attach_to_project=False)
            warnings.extend(self._ingest_notes(project_id, task_id, notes, attach_to_project=False))

    def _task_progress_state(self, task_id: str) -> Dict[str, Any]:
        task = self.db.get_task(task_id, include_cancelled=True) or {}
        result = task.get("result_json") if isinstance(task.get("result_json"), dict) else {}
        return dict(result or {})

    def _save_bulk_author_update_state(
        self,
        task_id: str,
        state: Dict[str, Any],
        status: str = "running",
        phase: str = "bulk_author_update",
        error_message: str = "",
        finished: bool = False,
    ):
        self.db.update_task(
            task_id,
            status=status,
            current_phase=phase,
            progress_current=int(state.get("completed_count") or 0),
            progress_total=int(state.get("total_count") or 0),
            warning_count=int(state.get("warning_count") or 0),
            error_message=error_message,
            result_json=state,
            finished_at=utcnow() if finished else None,
        )

    def _wait_bulk_delay(self, task_id: str, seconds: float):
        if seconds <= 0:
            return
        deadline = time.monotonic() + seconds
        while True:
            self._ensure_active(task_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._cancel_event(task_id).wait(min(remaining, 1.0)):
                self._ensure_active(task_id)

    @staticmethod
    def _delay_seconds(config: Dict[str, Any], minimum_key: str, maximum_key: str) -> float:
        minimum = max(0.0, float(config.get(minimum_key, 0) or 0))
        maximum = max(minimum, float(config.get(maximum_key, minimum) or minimum))
        return random.uniform(minimum, maximum) if maximum > minimum else minimum

    def run_project_author_update(self, task_id: str, project_id: int, configuration: Dict[str, Any]):
        collector_usage: Dict[str, Dict[str, int]] = {}
        capability_usage: Dict[str, Dict[str, Any]] = {}
        warnings: List[str] = []
        try:
            self._ensure_active(task_id)
            if not self.collectors:
                raise CollectorError("当前没有可用的数据采集提供方", "collector_unavailable")
            runtime_policy = self._policy_snapshot()
            capability_registry = self._capability_registry_snapshot()
            scopes = set(configuration.get("scopes") or [])
            allowed_scopes = {"basic_info", "preview_posts", "detailed_posts"}
            scopes = {scope for scope in scopes if scope in allowed_scopes}
            if not scopes:
                raise ValueError("批量作者更新需要至少选择一个更新范围")
            preview_limit = max(1, min(int(configuration.get("preview_limit") or 20), runtime_policy["max_author_notes"]))
            detail_limit = max(1, min(int(configuration.get("detail_limit") or 5), runtime_policy["max_author_notes"]))
            batch_size = max(1, min(int(configuration.get("batch_size") or 10), 50))
            consecutive_failure_limit = max(1, int(configuration.get("consecutive_failure_limit") or 5))
            author_ids = [
                str(author_id).strip()
                for author_id in (configuration.get("author_ids") or [])
                if str(author_id).strip()
            ]
            if not author_ids:
                raise ValueError("批量作者更新没有可处理的作者")

            previous = self._task_progress_state(task_id)
            completed_author_ids = set(previous.get("completed_author_ids") or [])
            failures = list(previous.get("failures") or [])
            skipped = len(completed_author_ids)
            state: Dict[str, Any] = {
                **previous,
                "operation": "project_author_update",
                "project_id": project_id,
                "scopes": sorted(scopes),
                "target": configuration.get("target") or "selected",
                "author_ids": author_ids,
                "total_count": len(author_ids),
                "completed_author_ids": sorted(completed_author_ids),
                "failures": failures,
                "failed_count": len(failures),
                "success_count": max(0, len(completed_author_ids) - len(failures)),
                "completed_count": len(completed_author_ids),
                "batch_size": batch_size,
                "warning_count": len(warnings),
                "capability_usage": capability_usage,
            }
            self._save_bulk_author_update_state(task_id, state)
            self.db.append_task_event(task_id, "bulk_author_update", "started", {
                "message": f"开始批量更新 {len(author_ids)} 位作者",
                "total_count": len(author_ids),
                "skipped_count": skipped,
                "scopes": sorted(scopes),
            })

            consecutive_failures = 0
            for index, author_id in enumerate(author_ids, 1):
                if author_id in completed_author_ids:
                    continue
                batch_index = ((index - 1) // batch_size) + 1
                state.update({
                    "current_author_id": author_id,
                    "current_index": index,
                    "current_batch": batch_index,
                    "completed_count": len(completed_author_ids),
                    "failed_count": len(failures),
                    "success_count": max(0, len(completed_author_ids) - len(failures)),
                    "warning_count": len(warnings),
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                })
                self._save_bulk_author_update_state(task_id, state)
                self.db.append_task_event(task_id, "bulk_author_update", "author_started", {
                    "message": f"开始更新作者 {author_id}",
                    "author_id": author_id,
                    "index": index,
                    "total": len(author_ids),
                    "batch": batch_index,
                })
                try:
                    self._author_update_step(
                        task_id,
                        project_id,
                        author_id,
                        scopes,
                        preview_limit,
                        detail_limit,
                        warnings,
                        collector_usage,
                        capability_usage,
                        capability_registry,
                        runtime_policy,
                    )
                    consecutive_failures = 0
                    self.db.append_task_event(task_id, "bulk_author_update", "author_completed", {
                        "message": f"作者 {author_id} 已更新",
                        "author_id": author_id,
                        "index": index,
                        "total": len(author_ids),
                        "batch": batch_index,
                    })
                except TaskCancelled:
                    raise
                except Exception as exc:
                    consecutive_failures += 1
                    failures.append({"author_id": author_id, "message": str(exc)})
                    self.db.append_task_event(task_id, "bulk_author_update", "author_failed", {
                        "message": f"作者 {author_id} 更新失败：{exc}",
                        "author_id": author_id,
                        "index": index,
                        "total": len(author_ids),
                        "batch": batch_index,
                    })
                completed_author_ids.add(author_id)
                state.update({
                    "completed_author_ids": sorted(completed_author_ids),
                    "failures": failures,
                    "completed_count": len(completed_author_ids),
                    "failed_count": len(failures),
                    "success_count": max(0, len(completed_author_ids) - len(failures)),
                    "warning_count": len(warnings),
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                })
                self._save_bulk_author_update_state(task_id, state)
                if consecutive_failures >= consecutive_failure_limit:
                    state["stopped_reason"] = f"连续 {consecutive_failures} 位作者更新失败，已停止后续批次"
                    break
                if len(completed_author_ids) >= len(author_ids):
                    break
                is_batch_end = index % batch_size == 0
                delay = self._delay_seconds(
                    configuration,
                    "batch_delay_min_seconds" if is_batch_end else "author_delay_min_seconds",
                    "batch_delay_max_seconds" if is_batch_end else "author_delay_max_seconds",
                )
                if delay > 0:
                    self.db.append_task_event(task_id, "bulk_author_update", "throttling", {
                        "message": f"安全间隔 {delay:.1f} 秒后继续",
                        "seconds": round(delay, 1),
                        "scope": "batch" if is_batch_end else "author",
                    })
                    self._wait_bulk_delay(task_id, delay)

            state.pop("current_author_id", None)
            state["collector_usage"] = collector_usage
            state["capability_usage"] = capability_usage
            state["capability_routes"] = capability_registry.describe_routes()
            state["warning_count"] = len(warnings)
            status = "partial" if failures or warnings or state.get("stopped_reason") else "completed"
            if int(state.get("success_count") or 0) > 0:
                self._complete_task_with_data_summary(
                    task_id,
                    project_id=project_id,
                    status=status,
                    result=state,
                    warnings=warnings,
                    operation="project_author_update",
                    task_type="research",
                )
            else:
                self._save_bulk_author_update_state(
                    task_id,
                    state,
                    status=status,
                    phase="completed",
                    error_message=str(state.get("stopped_reason") or ""),
                    finished=True,
                )
                self.db.append_task_event(task_id, "completed", status, {
                    "summary": state,
                    "warnings": warnings,
                })
        except TaskCancelled:
            return
        except Exception as exc:
            if self._is_cancelled(task_id):
                return
            self.db.update_task(
                task_id,
                status="failed",
                current_phase="failed",
                error_message=str(exc),
                finished_at=utcnow(),
            )
            self.db.append_task_event(task_id, "failed", "error", {"message": str(exc)})
        finally:
            self._clear_task_signals(task_id)

    def run_post_detail_update(self, task_id: str, configuration: Dict[str, Any]):
        collector_usage: Dict[str, Dict[str, int]] = {}
        capability_usage: Dict[str, Dict[str, Any]] = {}
        warnings: List[str] = []
        try:
            self._ensure_active(task_id)
            if not self.collectors:
                raise CollectorError("当前没有可用的数据采集提供方", "collector_unavailable")
            capability_registry = self._capability_registry_snapshot()
            posts = [dict(post) for post in (configuration.get("posts") or []) if isinstance(post, dict)]
            if not posts:
                raise ValueError("帖子详情更新没有可处理的帖子")
            batch_size = max(1, min(int(configuration.get("batch_size") or 10), 50))
            consecutive_failure_limit = max(1, min(int(configuration.get("consecutive_failure_limit") or 5), 20))
            project_id = configuration.get("project_id")
            project_id = int(project_id) if project_id not in (None, "") else None

            previous = self._task_progress_state(task_id)
            completed_post_ids = {int(value) for value in (previous.get("completed_post_ids") or [])}
            failures = list(previous.get("failures") or [])
            state: Dict[str, Any] = {
                **previous,
                "operation": "post_detail_update",
                "mode": configuration.get("mode") or "batch",
                "scope": configuration.get("scope") or "global",
                "scope_id": configuration.get("scope_id"),
                "target": configuration.get("target") or "selected",
                "post_ids": [int(post["id"]) for post in posts],
                "total_count": len(posts),
                "completed_post_ids": sorted(completed_post_ids),
                "failures": failures,
                "failed_count": len(failures),
                "success_count": max(0, len(completed_post_ids) - len(failures)),
                "completed_count": len(completed_post_ids),
                "batch_size": batch_size,
                "warning_count": len(warnings),
                "collector_usage": collector_usage,
                "capability_usage": capability_usage,
            }
            self._save_bulk_author_update_state(task_id, state, phase="post_detail_update")
            self.db.append_task_event(task_id, "post_detail_update", "started", {
                "message": f"开始更新 {len(posts)} 篇帖子详情",
                "total_count": len(posts),
                "skipped_count": len(completed_post_ids),
                "scope": state["scope"],
                "target": state["target"],
            })

            consecutive_failures = 0
            for index, post in enumerate(posts, 1):
                post_id = int(post["id"])
                if post_id in completed_post_ids:
                    continue
                note_id = str(post.get("note_id") or post_id)
                batch_index = ((index - 1) // batch_size) + 1
                state.update({
                    "current_post_id": post_id,
                    "current_note_id": note_id,
                    "current_index": index,
                    "current_batch": batch_index,
                    "completed_count": len(completed_post_ids),
                    "failed_count": len(failures),
                    "success_count": max(0, len(completed_post_ids) - len(failures)),
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                })
                self._save_bulk_author_update_state(task_id, state, phase="post_detail_update")
                self.db.append_task_event(task_id, "post_detail_update", "post_started", {
                    "message": f"开始更新帖子 {note_id}",
                    "post_id": post_id,
                    "note_id": note_id,
                    "index": index,
                    "total": len(posts),
                    "batch": batch_index,
                })
                try:
                    provider_id, collector, raw = self._route_capability(
                        task_id,
                        READ_POST_DETAIL,
                        (post,),
                        note_id,
                        "post",
                        collector_usage,
                        capability_usage,
                        capability_registry,
                    )
                    normalized = self._normalize_collector_result(collector, raw, "post", note_id)
                    cards = normalized.get("cards") or []
                    notes = normalized.get("notes") or []
                    if not notes:
                        raise CollectorError("采集指令未返回帖子详情", "post_detail_empty")
                    cover_url, cover_local_path = self._prepare_post_detail_cover(
                        task_id,
                        post,
                        cards,
                        notes,
                        collector_usage,
                        capability_usage,
                        capability_registry,
                    )
                    for item in cards + notes:
                        item["cover_local_path"] = cover_local_path
                        if cover_url:
                            item["cover_url"] = cover_url
                    self._download_post_detail_images(task_id, notes)
                    for item in cards + notes:
                        item["_collector_id"] = provider_id
                        item["_collector_ids"] = [provider_id]
                    # These are frozen existing targets. Refresh their data without
                    # fabricating a new project-author provenance row.
                    self._ingest_cards(project_id, task_id, cards, attach_to_project=False)
                    ingest_warnings = self._ingest_notes(
                        project_id,
                        task_id,
                        notes,
                        attach_to_project=False,
                    )
                    if project_id is not None:
                        # A previously author-less project post may gain its author
                        # during detail refresh; preserve coverage only when no
                        # project-author relationship exists yet.
                        self.db.attach_project_post_author_if_unrelated(
                            project_id,
                            post_id,
                            task_id,
                        )
                    if ingest_warnings:
                        raise CollectorError("；".join(ingest_warnings), "post_detail_failed")
                    consecutive_failures = 0
                    self.db.append_task_event(task_id, "post_detail_update", "post_completed", {
                        "message": f"帖子 {note_id} 详情已更新",
                        "post_id": post_id,
                        "note_id": note_id,
                        "index": index,
                        "total": len(posts),
                        "batch": batch_index,
                        "collector": provider_id,
                    })
                except TaskCancelled:
                    raise
                except Exception as exc:
                    consecutive_failures += 1
                    failures.append({"post_id": post_id, "note_id": note_id, "message": str(exc)})
                    self.db.append_task_event(task_id, "post_detail_update", "post_failed", {
                        "message": f"帖子 {note_id} 更新失败：{exc}",
                        "post_id": post_id,
                        "note_id": note_id,
                        "index": index,
                        "total": len(posts),
                        "batch": batch_index,
                    })
                completed_post_ids.add(post_id)
                state.update({
                    "completed_post_ids": sorted(completed_post_ids),
                    "failures": failures,
                    "completed_count": len(completed_post_ids),
                    "failed_count": len(failures),
                    "success_count": max(0, len(completed_post_ids) - len(failures)),
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                })
                self._save_bulk_author_update_state(task_id, state, phase="post_detail_update")
                if consecutive_failures >= consecutive_failure_limit:
                    state["stopped_reason"] = f"连续 {consecutive_failures} 篇帖子更新失败，已停止后续批次"
                    break
                if len(completed_post_ids) >= len(posts):
                    break
                is_batch_end = index % batch_size == 0
                delay = self._delay_seconds(
                    configuration,
                    "batch_delay_min_seconds" if is_batch_end else "post_delay_min_seconds",
                    "batch_delay_max_seconds" if is_batch_end else "post_delay_max_seconds",
                )
                if delay > 0:
                    self.db.append_task_event(task_id, "post_detail_update", "throttling", {
                        "message": f"安全间隔 {delay:.1f} 秒后继续",
                        "seconds": round(delay, 1),
                        "scope": "batch" if is_batch_end else "post",
                    })
                    self._wait_bulk_delay(task_id, delay)

            state.pop("current_post_id", None)
            state.pop("current_note_id", None)
            state["collector_usage"] = collector_usage
            state["capability_usage"] = capability_usage
            state["capability_routes"] = capability_registry.describe_routes()
            state["warning_count"] = len(warnings)
            status = "partial" if failures or warnings or state.get("stopped_reason") else "completed"
            summary_project_id = project_id
            summary_author_id = (
                int(state.get("scope_id"))
                if summary_project_id is None and state.get("scope") == "author" and state.get("scope_id") is not None
                else None
            )
            if int(state.get("success_count") or 0) > 0 and (
                summary_project_id is not None or summary_author_id is not None
            ):
                self._complete_task_with_data_summary(
                    task_id,
                    project_id=summary_project_id,
                    author_id=summary_author_id,
                    status=status,
                    result=state,
                    warnings=warnings,
                    operation="post_detail_update",
                    task_type="research",
                )
            else:
                self._save_bulk_author_update_state(
                    task_id,
                    state,
                    status=status,
                    phase="completed",
                    error_message=str(state.get("stopped_reason") or ""),
                    finished=True,
                )
                self.db.append_task_event(task_id, "completed", status, {
                    "summary": state,
                    "warnings": warnings,
                })
        except TaskCancelled:
            return
        except Exception as exc:
            if self._is_cancelled(task_id):
                return
            self.db.update_task(
                task_id,
                status="failed",
                current_phase="failed",
                error_message=str(exc),
                finished_at=utcnow(),
            )
            self.db.append_task_event(task_id, "failed", "error", {"message": str(exc)})
        finally:
            self._clear_task_signals(task_id)

    @staticmethod
    def _comment_timestamp(value: Any) -> str:
        if value in (None, ""):
            return ""
        try:
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return str(value)

    @classmethod
    def _normalize_comment_page(
        cls, raw: Dict[str, Any], *, embedded_replies_are_previews: bool = True,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for root_rank, source in enumerate(raw.get("comments") or []):
            if not isinstance(source, dict):
                continue
            root_id = str(source.get("id") or source.get("comment_id") or "").strip()
            if not root_id:
                continue
            user = source.get("user_info") if isinstance(source.get("user_info"), dict) else {}
            avatar = user.get("image") or user.get("avatar") or user.get("avatar_url") or ""
            normalized.append({
                "comment_id": root_id,
                "root_comment_id": root_id,
                "parent_comment_id": "",
                "comment_type": "root",
                "page_rank": root_rank * 1000,
                "author_user_id": user.get("user_id") or user.get("id") or "",
                "author_name": user.get("nickname") or user.get("name") or "",
                "author_avatar_url": avatar,
                "content": source.get("content") or "",
                "likes_count": source.get("like_count") or 0,
                "published_at": cls._comment_timestamp(source.get("create_time")),
                "ip_location": source.get("ip_location") or "",
                "platform_reply_count": source.get("sub_comment_count") or 0,
                "status": source.get("status"),
                "is_invalid": source.get("invalid") or False,
            })
            for reply_rank, reply in enumerate(source.get("sub_comments") or [], 1):
                if not isinstance(reply, dict):
                    continue
                reply_id = str(reply.get("id") or reply.get("comment_id") or "").strip()
                if not reply_id:
                    continue
                reply_user = reply.get("user_info") if isinstance(reply.get("user_info"), dict) else {}
                reply_avatar = (
                    reply_user.get("image") or reply_user.get("avatar")
                    or reply_user.get("avatar_url") or ""
                )
                normalized.append({
                    "comment_id": reply_id,
                    "root_comment_id": root_id,
                    "parent_comment_id": str(reply.get("target_comment_id") or root_id),
                    "comment_type": "reply_preview",
                    "is_reply_preview": embedded_replies_are_previews,
                    "page_rank": root_rank * 1000 + reply_rank,
                    "author_user_id": reply_user.get("user_id") or reply_user.get("id") or "",
                    "author_name": reply_user.get("nickname") or reply_user.get("name") or "",
                    "author_avatar_url": reply_avatar,
                    "content": reply.get("content") or "",
                    "likes_count": reply.get("like_count") or 0,
                    "published_at": cls._comment_timestamp(reply.get("create_time")),
                    "ip_location": reply.get("ip_location") or "",
                    "platform_reply_count": reply.get("sub_comment_count") or 0,
                    "status": reply.get("status"),
                    "is_invalid": reply.get("invalid") or False,
                })
        return normalized

    @classmethod
    def _normalize_sub_comment_page(
        cls,
        raw: Dict[str, Any],
        root_comment_id: str,
        root_rank: int,
        sub_page_number: int,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        values = raw.get("comments") or raw.get("sub_comments") or []
        for reply_rank, reply in enumerate(values, 1):
            if not isinstance(reply, dict):
                continue
            reply_id = str(reply.get("id") or reply.get("comment_id") or "").strip()
            if not reply_id:
                continue
            user = reply.get("user_info") if isinstance(reply.get("user_info"), dict) else {}
            normalized.append({
                "comment_id": reply_id,
                "root_comment_id": root_comment_id,
                "parent_comment_id": str(reply.get("target_comment_id") or root_comment_id),
                "comment_type": "reply_preview",
                "is_reply_preview": False,
                "page_rank": root_rank * 1_000_000 + sub_page_number * 1000 + reply_rank,
                "author_user_id": user.get("user_id") or user.get("id") or "",
                "author_name": user.get("nickname") or user.get("name") or "",
                "author_avatar_url": (
                    user.get("image") or user.get("avatar") or user.get("avatar_url") or ""
                ),
                "content": reply.get("content") or "",
                "likes_count": reply.get("like_count") or 0,
                "published_at": cls._comment_timestamp(reply.get("create_time")),
                "ip_location": reply.get("ip_location") or "",
                "platform_reply_count": reply.get("sub_comment_count") or 0,
                "status": reply.get("status"),
                "is_invalid": reply.get("invalid") or False,
            })
        return normalized

    @staticmethod
    def _comment_page_roots_with_more_replies(raw: Dict[str, Any]):
        values = []
        for root_rank, source in enumerate(raw.get("comments") or []):
            if not isinstance(source, dict):
                continue
            root_id = str(source.get("id") or source.get("comment_id") or "").strip()
            if not root_id:
                continue
            previews = [value for value in source.get("sub_comments") or [] if isinstance(value, dict)]
            reply_count = max(0, int(source.get("sub_comment_count") or 0))
            has_more = bool(source.get("sub_comment_has_more")) or reply_count > len(previews)
            if has_more:
                values.append((
                    root_rank,
                    root_id,
                    str(source.get("sub_comment_cursor") or ""),
                ))
        return values

    @staticmethod
    def _deduplicate_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        values: Dict[str, Dict[str, Any]] = {}
        for comment in comments:
            comment_id = str(comment.get("comment_id") or "")
            if comment_id:
                values[comment_id] = comment
        return list(values.values())

    def run_post_comment_collection(self, task_id: str, configuration: Dict[str, Any]):
        collector_usage: Dict[str, Dict[str, int]] = {}
        capability_usage: Dict[str, Dict[str, Any]] = {}
        completed_pages = 0
        root_count = 0
        reply_preview_count = 0
        reply_count = 0
        sub_comment_pages = 0
        sub_comments_truncated = False
        external_request_count = 0
        has_more = False
        state: Dict[str, Any] = {}
        try:
            self._ensure_active(task_id)
            if not self.collectors:
                raise CollectorError("当前没有可用的数据采集提供方", "collector_unavailable")
            post_id = int(configuration.get("post_id") or 0)
            requested_pages = max(1, min(20, int(configuration.get("requested_pages") or 1)))
            collection_mode = str(configuration.get("collection_mode") or "continue")
            if collection_mode not in ("continue", "refresh"):
                raise ValueError("评论采集方式无效")
            include_sub_comments = bool(configuration.get("include_sub_comments", False))
            sub_comment_page_limit = max(
                1, min(100, int(configuration.get("sub_comment_page_limit") or 20)),
            )
            post = self.db.get_post(post_id)
            if not post:
                raise ValueError("帖子不存在")
            note_id = str(post.get("note_id") or "").strip()
            if not note_id:
                raise ValueError("帖子缺少小红书帖子 ID")
            checkpoint = self.db.get_post_comment_checkpoint(post_id)
            checkpoint_status = str((checkpoint or {}).get("status") or "")
            if collection_mode == "continue" and checkpoint_status == "exhausted":
                raise ValueError("该帖已补充到平台当前末页，请选择“重新更新”")
            if collection_mode == "continue" and checkpoint_status == "invalid":
                raise ValueError("上次续传位置已失效，请选择“重新更新”重建")
            rebuild_checkpoint = collection_mode == "refresh" and checkpoint_status in ("", "invalid")
            advance_checkpoint = collection_mode == "continue" or rebuild_checkpoint
            cursor = (
                str((checkpoint or {}).get("next_cursor") or "")
                if collection_mode == "continue" else ""
            )
            registry = self._capability_registry_snapshot()
            state = {
                "operation": "post_comment_collection",
                "post_id": post_id,
                "note_id": note_id,
                "post_title": str(post.get("title") or ""),
                "collection_mode": collection_mode,
                "requested_pages": requested_pages,
                "completed_pages": 0,
                "root_comment_count": 0,
                "reply_preview_count": 0,
                "reply_count": 0,
                "include_sub_comments": include_sub_comments,
                "sub_comment_page_limit": sub_comment_page_limit,
                "sub_comment_pages": 0,
                "sub_comments_truncated": False,
                "external_request_count": 0,
                "checkpoint_start_status": checkpoint_status or "new",
                "checkpoint_rebuilt": rebuild_checkpoint,
                "has_more": False,
                "collector_usage": collector_usage,
                "capability_usage": capability_usage,
                "capability_routes": registry.describe_routes(),
            }
            self.db.update_task(
                task_id, status="running", current_phase="collecting_comments",
                progress_current=0, progress_total=requested_pages, result_json=state,
                started_at=utcnow(), error_message="",
            )
            self.db.append_task_event(task_id, "collecting_comments", "started", {
                "message": (
                    f"开始{'继续补充' if collection_mode == 'continue' else '重新更新'}"
                    f"帖子 {note_id} 的评论，最多 {requested_pages} 页"
                ),
                "post_id": post_id,
                "note_id": note_id,
                "requested_pages": requested_pages,
                "collection_mode": collection_mode,
                "include_sub_comments": include_sub_comments,
            })

            def wait_before_request():
                nonlocal external_request_count
                if external_request_count:
                    delay = self._delay_seconds(
                        configuration, "page_delay_min_seconds", "page_delay_max_seconds",
                    )
                    if delay > 0:
                        self.db.append_task_event(task_id, "collecting_comments", "throttling", {
                            "message": f"安全间隔 {delay:.1f} 秒后继续请求",
                            "seconds": round(delay, 1),
                        })
                        self._wait_bulk_delay(task_id, delay)
                external_request_count += 1

            for page_number in range(1, requested_pages + 1):
                self._ensure_active(task_id)
                wait_before_request()
                _, _, raw = self._route_capability(
                    task_id, READ_POST_COMMENTS, (post, cursor), note_id, "post",
                    collector_usage, capability_usage, registry,
                )
                if not isinstance(raw, dict):
                    raise CollectorError("评论接口返回格式无效", "invalid_response")
                next_cursor = str(raw.get("cursor") or "")
                has_more = bool(raw.get("has_more")) and bool(next_cursor)
                if cursor and has_more and next_cursor == cursor:
                    if collection_mode == "continue":
                        self.db.mark_post_comment_checkpoint_invalid(
                            post_id, task_id, "平台返回的 cursor 未推进",
                        )
                    raise CollectorError(
                        "平台返回的续传位置未推进，已停止以避免重复请求",
                        "cursor_invalid",
                    )
                comments = self._normalize_comment_page(
                    raw, embedded_replies_are_previews=not include_sub_comments,
                )
                roots_with_more = self._comment_page_roots_with_more_replies(raw)
                if include_sub_comments:
                    for root_index, (root_rank, root_id, sub_cursor) in enumerate(roots_with_more):
                        sub_page_number = 0
                        sub_has_more = True
                        while sub_has_more and sub_comment_pages < sub_comment_page_limit:
                            self._ensure_active(task_id)
                            wait_before_request()
                            _, _, sub_raw = self._route_capability(
                                task_id,
                                READ_POST_SUB_COMMENTS,
                                (note_id, root_id, sub_cursor),
                                note_id,
                                "post",
                                collector_usage,
                                capability_usage,
                                registry,
                            )
                            if not isinstance(sub_raw, dict):
                                raise CollectorError(
                                    "楼中楼接口返回格式无效", "invalid_response",
                                )
                            sub_page_number += 1
                            sub_comment_pages += 1
                            comments.extend(self._normalize_sub_comment_page(
                                sub_raw, root_id, root_rank, sub_page_number,
                            ))
                            next_sub_cursor = str(sub_raw.get("cursor") or "")
                            sub_has_more = bool(sub_raw.get("has_more")) and bool(next_sub_cursor)
                            if sub_has_more and next_sub_cursor == sub_cursor:
                                sub_comments_truncated = True
                                sub_has_more = False
                            sub_cursor = next_sub_cursor
                        if sub_has_more or (
                            sub_comment_pages >= sub_comment_page_limit
                            and root_index < len(roots_with_more) - 1
                        ):
                            sub_comments_truncated = True
                            break
                comments = self._deduplicate_comments(comments)
                saved = self.db.save_post_comment_page(
                    task_id,
                    post_id,
                    page_number,
                    comments,
                    advance_checkpoint=advance_checkpoint,
                    reset_checkpoint=rebuild_checkpoint and page_number == 1,
                    next_cursor=next_cursor,
                    has_more=has_more,
                )
                completed_pages = page_number
                root_count += int(saved["root_count"])
                reply_preview_count += int(saved["reply_preview_count"])
                reply_count += int(saved["reply_count"])
                state.update({
                    "completed_pages": completed_pages,
                    "root_comment_count": root_count,
                    "reply_preview_count": reply_preview_count,
                    "reply_count": reply_count,
                    "sub_comment_pages": sub_comment_pages,
                    "sub_comments_truncated": sub_comments_truncated,
                    "external_request_count": external_request_count,
                    "has_more": has_more,
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                })
                self.db.update_task(
                    task_id, status="running", current_phase="collecting_comments",
                    progress_current=completed_pages, progress_total=requested_pages,
                    result_json=state,
                )
                self.db.append_task_event(task_id, "collecting_comments", "page_completed", {
                    "message": f"第 {page_number} 页评论已保存",
                    "page": page_number,
                    "root_comment_count": int(saved["root_count"]),
                    "reply_preview_count": int(saved["reply_preview_count"]),
                    "reply_count": int(saved["reply_count"]),
                    "sub_comment_pages": sub_comment_pages,
                    "has_more": has_more,
                })
                if not has_more or page_number >= requested_pages:
                    break
                cursor = next_cursor
            self.db.mark_post_comments_fetched(post_id)
            state["has_more"] = has_more
            self.db.update_task(
                task_id, status="completed", current_phase="completed",
                progress_current=completed_pages, progress_total=requested_pages,
                result_json=state, finished_at=utcnow(), error_message="",
            )
            self.db.append_task_event(task_id, "completed", "completed", {
                "message": (
                    f"评论采集完成，共保存 {root_count} 条一级评论、"
                    f"{reply_preview_count + reply_count} 条回复"
                ),
                "summary": state,
            })
        except TaskCancelled:
            return
        except Exception as exc:
            if self._is_cancelled(task_id):
                return
            status = "partial" if completed_pages > 0 else "failed"
            if completed_pages > 0 and configuration.get("post_id"):
                self.db.mark_post_comments_fetched(int(configuration["post_id"]))
            state.update({
                "completed_pages": completed_pages,
                "root_comment_count": root_count,
                "reply_preview_count": reply_preview_count,
                "reply_count": reply_count,
                "sub_comment_pages": sub_comment_pages,
                "sub_comments_truncated": sub_comments_truncated,
                "external_request_count": external_request_count,
                "has_more": has_more,
                "collector_usage": collector_usage,
                "capability_usage": capability_usage,
            })
            self.db.update_task(
                task_id, status=status, current_phase=status,
                progress_current=completed_pages,
                progress_total=max(1, int(configuration.get("requested_pages") or 1)),
                result_json=state, error_message=str(exc), finished_at=utcnow(),
            )
            self.db.append_task_event(task_id, status, "error", {
                "message": str(exc), "completed_pages": completed_pages,
            })
        finally:
            self._clear_task_signals(task_id)

    def _ingest_cards(
        self,
        project_id: Optional[int],
        task_id: str,
        cards: List[Dict[str, Any]],
        *,
        attach_to_project: bool = True,
        author_relation: str = "post_author",
    ):
        for card in cards:
            self._ensure_active(task_id)
            card = dict(card)
            local_cover = self._download_cover(card.get("note_id", ""), card.get("cover_url", ""))
            if local_cover:
                card["cover_local_path"] = local_cover
            post_pk = self.db.upsert_post(card)
            if project_id is not None and attach_to_project:
                self.db.attach_post_to_project(project_id, post_pk, task_id)
            if card.get("author_id"):
                author_pk = self.db.upsert_author({"author_id": card["author_id"], "display_name": card.get("author", ""), "profile_url": card.get("author_url", "")})
                if project_id is not None and attach_to_project:
                    self.db.attach_author_to_project(project_id, author_pk, author_relation, task_id)
            self.db.record_task_post(task_id, post_pk, card["source_type"], card["source_value"], card["source_rank"])
            if card.get("cover_url"):
                self.db.upsert_media(post_pk, {
                    "url": card["cover_url"], "local_path": local_cover,
                    "ocr_text": card.get("ocr_text", ""), "ocr_engine": card.get("ocr_engine", ""),
                }, 0, "cover")

    def _download_cover(self, note_id: str, url: str) -> str:
        if not note_id or not url or "xhscdn.com" not in (urlparse(url).hostname or ""):
            return ""
        target = self.db.path.parent / "media" / "covers" / f"{note_id}.webp"
        return self._download_remote_image(url, target)

    def _download_remote_image(self, url: str, target: Path) -> str:
        if "xhscdn.com" not in (urlparse(url).hostname or ""):
            return ""
        if self._is_valid_image(target):
            return str(target)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"})
            with urlopen(request, timeout=30) as response:
                body = response.read(15_000_001)
            if not body or len(body) > 15_000_000:
                return ""
            target.write_bytes(body)
            if self._is_valid_image(target):
                return str(target)
            target.unlink(missing_ok=True)
            return ""
        except Exception:
            target.unlink(missing_ok=True)
            return ""

    def _download_post_detail_image(self, note_id: str, media_index: int, url: str) -> str:
        if not note_id or not url:
            return ""
        # Keep provider-controlled note IDs out of the filesystem path while
        # retaining stable paths across detail refreshes.
        note_key = hashlib.sha256(note_id.encode("utf-8")).hexdigest()[:24]
        target = self.db.path.parent / "media" / "images" / note_key / f"{media_index}.webp"
        return self._download_remote_image(url, target)

    def _download_post_detail_images(self, task_id: str, notes: List[Dict[str, Any]]):
        """Save each returned detail image locally; its original URL remains the fallback."""
        for note in notes:
            note_id = str(note.get("note_id") or "").strip()
            images = note.get("images") if isinstance(note.get("images"), list) else []
            local_images = []
            for fallback_index, raw_media in enumerate(images):
                self._ensure_active(task_id)
                if not isinstance(raw_media, dict):
                    continue
                media = dict(raw_media)
                try:
                    media_index = int(media.get("index", fallback_index))
                except (TypeError, ValueError):
                    media_index = fallback_index
                media["index"] = media_index
                url = str(media.get("url") or "").strip()
                local_path = self._download_post_detail_image(note_id, media_index, url)
                if local_path:
                    media["local_path"] = local_path
                local_images.append(media)
            note["images"] = local_images

    @staticmethod
    def _is_valid_image(path: Path) -> bool:
        try:
            if not path.is_file():
                return False
            head = path.read_bytes()[:64]
        except OSError:
            return False
        if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")):
            return True
        if head.startswith((b"II*\x00", b"MM\x00*")):
            return True
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return True
        if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (
            b"avif", b"avis", b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1",
        ):
            return True
        return False

    @staticmethod
    def _cover_url_from_post_detail(post: Dict[str, Any], cards, notes) -> str:
        for item in list(notes or []) + list(cards or []) + [post]:
            cover_url = str(item.get("cover_url") or "").strip()
            if cover_url:
                return cover_url
            images = item.get("images") if isinstance(item.get("images"), list) else []
            for image in images:
                if isinstance(image, dict) and str(image.get("url") or "").strip():
                    return str(image["url"]).strip()
        return ""

    def _download_cover_with_capability(
        self,
        task_id: str,
        post: Dict[str, Any],
        collector_usage: Dict[str, Dict[str, int]],
        capability_usage: Dict[str, Dict[str, Any]],
        capability_registry: CapabilityRegistry,
    ) -> str:
        note_id = str(post.get("note_id") or "").strip()
        note_url = str(post.get("note_url") or post.get("url") or "").strip()
        if not note_id or not note_url:
            return ""
        temp_root = self.db.path.parent / "media" / ".cover-download-tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{note_id}-", dir=temp_root) as output_dir:
            self._route_capability(
                task_id,
                DOWNLOAD_MEDIA,
                (note_url, output_dir),
                note_id,
                "post",
                collector_usage,
                capability_usage,
                capability_registry,
            )
            source = next(
                (
                    path for path in sorted(Path(output_dir).rglob("*"))
                    if self._is_valid_image(path)
                ),
                None,
            )
            if source is None:
                return ""
            target = self.db.path.parent / "media" / "covers" / f"{note_id}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if self._is_valid_image(target):
                return str(target)
            target.unlink(missing_ok=True)
            return ""

    def _prepare_post_detail_cover(
        self,
        task_id: str,
        post: Dict[str, Any],
        cards,
        notes,
        collector_usage: Dict[str, Dict[str, int]],
        capability_usage: Dict[str, Dict[str, Any]],
        capability_registry: CapabilityRegistry,
    ) -> tuple[str, str]:
        note_id = str(post.get("note_id") or "").strip()
        cover_url = self._cover_url_from_post_detail(post, cards, notes)
        local_path = self._download_cover(note_id, cover_url)
        if not local_path:
            try:
                local_path = self._download_cover_with_capability(
                    task_id,
                    post,
                    collector_usage,
                    capability_usage,
                    capability_registry,
                )
            except CollectorError:
                local_path = ""
        if not local_path:
            raise CollectorError(
                "帖子详情已返回，但封面图未能下载到本地",
                "post_cover_download_failed",
            )
        return cover_url, local_path

    def _ingest_notes(
        self,
        project_id: Optional[int],
        task_id: str,
        notes: List[Dict[str, Any]],
        *,
        attach_to_project: bool = True,
    ):
        warnings = []
        for note in notes:
            self._ensure_active(task_id)
            ok = note.get("_collector_ok", note.get("_socai_ok", True))
            if not ok:
                warnings.append(f"帖子 {note.get('note_id','未知')} 详情读取失败：{note.get('_collector_error') or note.get('_socai_error') or '采集 CLI 未返回详情'}")
            note["content_hash"] = hashlib.sha256(str(note.get("content", "")).encode("utf-8")).hexdigest()
            post_pk = self.db.upsert_post(note)
            if project_id is not None and attach_to_project:
                self.db.attach_post_to_project(project_id, post_pk, task_id)
            cover_local_path = str(note.get("cover_local_path") or "")
            if cover_local_path:
                self.db.upsert_media(post_pk, {
                    "url": str(note.get("cover_url") or ""),
                    "local_path": cover_local_path,
                }, 0, "cover")
            for index, media in enumerate(note.get("images") or []):
                self.db.upsert_media(post_pk, media, int(media.get("index", index)), "image")
            video = note.get("video")
            if isinstance(video, dict) and video:
                poster = {"url": video.get("poster_url", ""), "local_path": video.get("poster_local_path", ""), "ocr_text": video.get("poster_ocr", "")}
                self.db.upsert_media(post_pk, poster, 0, "video_poster")
            if ok:
                self.db.mark_post_detail_fetched(post_pk)
        return warnings

    def _vision_inputs(
        self,
        project_id: Optional[int],
        posts: Optional[List[Dict[str, Any]]] = None,
        author_id: Optional[int] = None,
        provider=None,
        image_scope: str = "all",
    ):
        if (project_id is None) == (author_id is None):
            raise ValueError("图片理解范围必须且只能指定一个项目或作者")
        values = []
        if author_id is not None:
            author = self.db.get_author(author_id)
            if not author:
                raise KeyError("author not found")
            posts = posts if posts is not None else author.get("posts") or []
            media_rows = self.db.list_author_media_for_vision(author_id)
        else:
            posts = posts if posts is not None else self.db.list_project_posts(project_id)
            media_rows = self.db.list_project_media_for_vision(project_id)
        provider = provider if provider is not None else self._vision_provider_for()
        cache_rows = []
        cache_key_fn = None
        if provider:
            model = provider_vision_model_identity(provider)
            prompt_version = provider.prompt_version
            cache_rows = (
                self.db.list_author_vision_cache(author_id, model, prompt_version)
                if author_id is not None
                else self.db.list_project_vision_cache(project_id, model, prompt_version)
            )
            cache_key_fn = lambda paths: provider_vision_cache_key(
                provider, paths, image_scope,
            )
        states = resolve_current_vision(
            media_rows, cache_rows, self.db.path.parent, cache_key_fn,
            image_scope,
        )
        if provider and image_scope in IMAGE_SCOPES:
            legacy_states = resolve_current_vision(
                media_rows,
                cache_rows,
                self.db.path.parent,
                lambda paths: provider_vision_cache_key(provider, paths, "all"),
                "all",
            )
            for post_id, state in states.items():
                legacy = legacy_states.get(post_id) or {}
                if not state.get("analyzed") and legacy.get("analyzed"):
                    state["analyzed"] = True
                    state["vision_results"] = legacy.get("vision_results") or []
                    state["vision_rows"] = legacy.get("vision_rows") or []

        for post in posts:
            state = states.get(int(post["id"]))
            if not state:
                continue
            values.append({
                "post_id": post["id"], "title": post["title"], "author_id": post.get("external_author_id"),
                "note_type": post["note_type"], "popularity_percentile": post.get("popularity_percentile"),
                "ocr_text": "\n".join(item.get("ocr_text") or "" for item in state["media"]),
                "image_paths": state["image_paths"], "cache_key": state["cache_key"],
                "image_scope": image_scope,
                "analyzed": state["analyzed"], "vision_results": state["vision_results"],
                "vision_rows": state["vision_rows"],
            })
        return values

    def project_posts(self, project_id: int):
        posts = self.db.list_project_posts(project_id)
        provider = self._vision_provider_for()
        current = {}
        for image_scope in (*IMAGE_SCOPES, "all"):
            for value in self._vision_inputs(
                project_id, posts, provider=provider, image_scope=image_scope,
            ):
                if value["analyzed"]:
                    current[int(value["post_id"])] = value
        for post in posts:
            post["has_vision_result"] = int(bool(current.get(int(post["id"]), {}).get("analyzed")))
        return posts

    def project_posts_page(self, project_id: int, **options):
        provider = self._vision_provider_for()
        if provider and getattr(
            provider, "supports_persisted_current_state", False
        ):
            options = {
                **options,
                "vision_model": provider_vision_model_identity(provider),
                "vision_prompt_version": provider.prompt_version,
            }
        return self.db.list_project_posts_page(project_id, **options)

    def posts_page(self, **options):
        provider = self._vision_provider_for()
        if provider and getattr(
            provider, "supports_persisted_current_state", False
        ):
            options = {
                **options,
                "vision_model": provider_vision_model_identity(provider),
                "vision_prompt_version": provider.prompt_version,
            }
        return self.db.list_posts_page(**options)

    def _apply_vision_status(self, posts, media_rows, cache_rows, provider=None):
        provider = provider if provider is not None else self._vision_provider_for()
        states_by_scope = {}
        for image_scope in (*IMAGE_SCOPES, "all"):
            cache_key_fn = (
                (lambda paths, scope=image_scope: provider_vision_cache_key(
                    provider, paths, scope,
                )) if provider else None
            )
            states_by_scope[image_scope] = resolve_current_vision(
                media_rows,
                cache_rows if provider else [],
                self.db.path.parent,
                cache_key_fn,
                image_scope,
            )
        for post in posts:
            post_id = int(post["id"])
            post["has_vision_result"] = int(any(
                (states_by_scope[scope].get(post_id) or {}).get("analyzed")
                for scope in states_by_scope
            ))
        return posts

    def posts(self):
        posts = self.db.list_posts()
        provider = self._vision_provider_for()
        cache_rows = []
        if provider:
            cache_rows = self.db.list_global_vision_cache(
                provider_vision_model_identity(provider),
                provider.prompt_version,
            )
        return self._apply_vision_status(
            posts,
            self.db.list_global_media_for_vision(),
            cache_rows,
            provider,
        )

    def author(self, author_id: int):
        author = self.db.get_author(author_id)
        if not author:
            return None
        provider = self._vision_provider_for()
        cache_rows = []
        if provider:
            cache_rows = self.db.list_author_vision_cache(
                author_id,
                provider_vision_model_identity(provider),
                provider.prompt_version,
            )
        self._apply_vision_status(
            author.get("posts") or [],
            self.db.list_author_media_for_vision(author_id),
            cache_rows,
            provider,
        )
        return author

    def get_post(self, post_id: int):
        post = self.db.get_post(post_id)
        if not post:
            return None
        provider = self._vision_provider_for()
        cache_rows = []
        if provider:
            cache_rows = self.db.list_post_vision_cache(
                post_id,
                provider_vision_model_identity(provider),
                provider.prompt_version,
            )
        vision_rows_by_scope = {}
        for image_scope in (*IMAGE_SCOPES, "all"):
            cache_key_fn = (
                (lambda paths, scope=image_scope: provider_vision_cache_key(
                    provider, paths, scope,
                )) if provider else None
            )
            states = resolve_current_vision(
                post.get("media") or [], cache_rows, self.db.path.parent,
                cache_key_fn, image_scope,
            )
            vision_rows_by_scope[image_scope] = (
                (states.get(post_id) or {}).get("vision_rows") or []
            )
        scoped_rows = [
            row
            for image_scope in IMAGE_SCOPES
            for row in vision_rows_by_scope[image_scope]
        ]
        post["vision"] = scoped_rows or vision_rows_by_scope["all"]
        post["has_vision_result"] = int(bool(post["vision"]))
        return post

    def _capture_report_evidence(self, project_id: int):
        provider = self._vision_provider_for()
        kwargs = {}
        if provider:
            kwargs = {
                "vision_model": provider_vision_model_identity(provider),
                "vision_prompt_version": provider.prompt_version,
                "vision_cache_key": lambda paths, image_scope="all": provider_vision_cache_key(
                    provider, paths, image_scope,
                ),
            }
        return self.db.capture_report_evidence(project_id, **kwargs)

    def _capture_author_report_evidence(self, author_id: int):
        provider = self._vision_provider_for()
        kwargs = {}
        if provider:
            kwargs = {
                "vision_model": provider_vision_model_identity(provider),
                "vision_prompt_version": provider.prompt_version,
                "vision_cache_key": lambda paths, image_scope="all": provider_vision_cache_key(
                    provider, paths, image_scope,
                ),
            }
        return self.db.capture_author_report_evidence(author_id, **kwargs)

    def _vision_counts(self, project_id: Optional[int], author_id: Optional[int], provider,
                       image_scope: str):
        values = self._vision_inputs(
            project_id, author_id=author_id, provider=provider, image_scope=image_scope,
        )
        analyzed = sum(bool(value["analyzed"]) for value in values)
        available_images = sum(len(value["image_paths"]) for value in values)
        analyzed_images = sum(
            len(value["image_paths"]) for value in values if value["analyzed"]
        )
        return {
            "available_posts": len(values),
            "analyzed_posts": analyzed,
            "pending_posts": len(values) - analyzed,
            "available_images": available_images,
            "analyzed_images": analyzed_images,
            "pending_images": max(0, available_images - analyzed_images),
        }

    def _vision_aggregate_counts(self, project_id: Optional[int], author_id: Optional[int], provider):
        by_post: Dict[int, List[Dict[str, Any]]] = {}
        for image_scope in IMAGE_SCOPES:
            for value in self._vision_inputs(
                project_id, author_id=author_id, provider=provider, image_scope=image_scope,
            ):
                by_post.setdefault(int(value["post_id"]), []).append(value)
        available_images = sum(
            len(value["image_paths"]) for values in by_post.values() for value in values
        )
        analyzed_images = sum(
            len(value["image_paths"])
            for values in by_post.values()
            for value in values
            if value["analyzed"]
        )
        analyzed_posts = sum(
            bool(values) and all(value["analyzed"] for value in values)
            for values in by_post.values()
        )
        return {
            "available_posts": len(by_post),
            "analyzed_posts": analyzed_posts,
            "pending_posts": max(0, len(by_post) - analyzed_posts),
            "available_images": available_images,
            "analyzed_images": analyzed_images,
            "pending_images": max(0, available_images - analyzed_images),
        }

    def vision_status(self, project_id: Optional[int], author_id: Optional[int] = None):
        vision_provider = self._vision_provider_for()
        vision_scopes = {
            image_scope: self._vision_counts(
                project_id, author_id, vision_provider, image_scope,
            )
            for image_scope in IMAGE_SCOPES
        }
        vision_counts = self._vision_aggregate_counts(project_id, author_id, vision_provider)
        ocr_provider = self._ocr_provider_for()
        ocr_scopes = {
            image_scope: self._ocr_status_for(
                project_id, author_id, ocr_provider, image_scope,
            )
            for image_scope in IMAGE_SCOPES
        }
        ocr_counts = self._ocr_status_for(project_id, author_id, ocr_provider, "all")
        return {
            "provider_available": self._provider_available(vision_provider),
            "available_posts": vision_counts["available_posts"],
            "analyzed_posts": vision_counts["analyzed_posts"],
            "pending_posts": vision_counts["pending_posts"],
            "vision_scopes": vision_scopes,
            "ocr_provider_available": self._provider_available(ocr_provider),
            "ocr_available_posts": ocr_counts["available_posts"],
            "ocr_processed_posts": ocr_counts["processed_posts"],
            "ocr_pending_posts": ocr_counts["pending_posts"],
            "ocr_other_posts": ocr_counts["other_posts"],
            "ocr_scopes": ocr_scopes,
        }

    def author_vision_status(self, author_id: int):
        return self.vision_status(None, author_id)

    def _ocr_inputs(self, project_id: Optional[int], author_id: Optional[int] = None,
                    provider=None, image_scope: str = "all"):
        if (project_id is None) == (author_id is None):
            raise ValueError("OCR 范围必须且只能指定一个项目或作者")
        root = self.db.path.parent.resolve()
        grouped: Dict[int, Dict[str, Any]] = {}
        media_rows = (
            self.db.list_author_media_for_ocr(author_id)
            if author_id is not None
            else self.db.list_project_media_for_ocr(project_id)
        )
        provider = provider if provider is not None else self._ocr_provider_for()
        expected_engine = str(getattr(provider, "engine_name", "") or "")
        expected_version = str(getattr(provider, "version", "") or "")
        for media in media_rows:
            if not media_matches_scope(media.get("media_type"), image_scope):
                continue
            path = Path(str(media.get("local_path") or "")).expanduser()
            try:
                path = path.resolve()
                path.relative_to(root)
            except (OSError, ValueError):
                continue
            if not path.is_file():
                continue
            post_id = int(media["post_id"])
            value = grouped.setdefault(post_id, {
                "post_id": post_id,
                "image_scope": image_scope,
                "media": [],
                "completed": True,
            })
            completed = bool(media.get("ocr_completed_at")) and (
                str(media.get("ocr_engine") or "") == expected_engine
                and str(media.get("ocr_version") or "") == expected_version
            )
            value["media"].append({"id": int(media["id"]), "path": path, "completed": completed})
            value["completed"] = value["completed"] and completed
        return list(grouped.values())

    def _ocr_status_for(self, project_id: Optional[int], author_id: Optional[int], provider,
                        image_scope: str = "all"):
        values = self._ocr_inputs(project_id, author_id, provider, image_scope)
        completed = sum(1 for value in values if value["completed"])
        available_images = sum(len(value["media"]) for value in values)
        completed_images = sum(
            sum(bool(media["completed"]) for media in value["media"]) for value in values
        )
        scope_posts = int(self.db.scalar(
            "SELECT COUNT(*) FROM posts WHERE author_id=?" if author_id is not None
            else "SELECT COUNT(*) FROM project_posts WHERE project_id=?",
            (author_id if author_id is not None else project_id,),
        ) or 0)
        return {
            "available_posts": len(values),
            "processed_posts": completed,
            "pending_posts": max(0, len(values) - completed),
            "other_posts": max(0, scope_posts - len(values)),
            "available_images": available_images,
            "processed_images": completed_images,
            "pending_images": max(0, available_images - completed_images),
        }

    def ocr_status(self, project_id: Optional[int], author_id: Optional[int] = None):
        provider = self._ocr_provider_for()
        values = self._ocr_status_for(project_id, author_id, provider)
        return {
            "ocr_provider_available": self._provider_available(provider),
            "ocr_available_posts": values["available_posts"],
            "ocr_processed_posts": values["processed_posts"],
            "ocr_pending_posts": values["pending_posts"],
            "ocr_other_posts": values["other_posts"],
        }

    def _report_posts(self, project_id: int):
        return self._capture_report_evidence(project_id)["posts"]

    def ai_report_status(self, project_id: int):
        provider = self._vision_provider_for()
        if provider is None or getattr(
            provider, "supports_persisted_current_state", False
        ):
            counts = self.db.project_status_counts(
                project_id,
                provider_vision_model_identity(provider) if provider else "",
                provider.prompt_version if provider else "",
            ) or {}
            return {
                "provider_available": self.report_provider is not None,
                "post_count": int(counts.get("post_count") or 0),
                "author_count": int(counts.get("author_count") or 0),
                "ocr_post_count": int(counts.get("ocr_post_count") or 0),
                "vision_post_count": int(counts.get("vision_post_count") or 0),
            }
        captured = self._capture_report_evidence(project_id)
        posts = captured["posts"]
        authors = captured["authors"]
        return {
            "provider_available": self.report_provider is not None,
            "post_count": len(posts),
            "author_count": len(authors),
            "ocr_post_count": sum(bool(post.get("ocr_text")) for post in posts),
            "vision_post_count": sum(bool(post.get("vision_results")) for post in posts),
        }

    def author_ai_report_status(self, author_id: int):
        captured = self._capture_author_report_evidence(author_id)
        posts = captured["posts"]
        return {
            "provider_available": self.report_provider is not None,
            "post_count": len(posts),
            "author_count": 1,
            "ocr_post_count": sum(bool(post.get("has_ocr_result")) for post in posts),
            "vision_post_count": sum(bool(post.get("vision_results")) for post in posts),
        }

    def create_project_data_summary(self, project_id: int):
        captured = self._capture_report_evidence(project_id)
        summary = build_project_data_summary(captured)
        report_id = self.db.create_data_summary(
            project_id=project_id,
            summary=summary,
            generation_config={"trigger": "manual"},
            evidence_snapshot=self._data_summary_evidence_snapshot(captured),
        )
        reports = self.db.list_reports(project_id)
        return next(report for report in reports if int(report["id"]) == report_id)

    def create_author_data_summary(self, author_id: int):
        captured = self._capture_author_report_evidence(author_id)
        summary = build_author_data_summary(captured)
        summary["core"]["report_count"] = int(summary["core"].get("report_count") or 0) + 1
        report_id = self.db.create_data_summary(
            author_id=author_id,
            summary=summary,
            generation_config={"trigger": "manual"},
            evidence_snapshot=self._data_summary_evidence_snapshot(captured),
        )
        reports = self.db.list_author_reports(author_id)
        return next(report for report in reports if int(report["id"]) == report_id)

    @staticmethod
    def _data_summary_evidence_snapshot(captured: Dict[str, Any]) -> Dict[str, Any]:
        posts = list(captured.get("posts") or [])
        authors = list(captured.get("authors") or [])
        return {
            "captured_at": captured.get("captured_at"),
            "post_ids": [post["id"] for post in posts],
            "author_ids": [author["id"] for author in authors],
            "selected_post_ids": [post["id"] for post in posts],
            "selected_author_ids": [author["id"] for author in authors],
            "post_count": len(posts),
            "author_count": len(authors),
            "ocr_post_count": sum(bool(post.get("has_ocr_result")) for post in posts),
            "vision_post_count": sum(bool(post.get("has_vision_result")) for post in posts),
            "interaction_detail_count": sum(
                post.get("favorites_count") is not None
                and post.get("comments_count") is not None
                for post in posts
            ),
        }

    def _complete_task_with_data_summary(
        self,
        task_id: str,
        *,
        project_id: Optional[int] = None,
        author_id: Optional[int] = None,
        status: str,
        result: Dict[str, Any],
        warnings: List[str],
        operation: str,
        task_type: str,
    ) -> int:
        if (project_id is None) == (author_id is None):
            raise ValueError("automatic data summary requires exactly one project or author")
        if project_id is not None:
            captured = self._capture_report_evidence(project_id)
            summary = build_project_data_summary(captured)
        else:
            captured = self._capture_author_report_evidence(int(author_id))
            summary = build_author_data_summary(captured)
            summary["core"]["report_count"] = int(summary["core"].get("report_count") or 0) + 1
        return self.db.create_data_summary(
            project_id=project_id,
            author_id=author_id,
            summary=summary,
            task_id=task_id,
            task_status=status,
            task_result=result,
            task_warning_count=len(warnings),
            completion_event={"summary": result, "warnings": warnings},
            generation_config={
                "trigger": "automatic",
                "operation": operation,
                "task_type": task_type,
            },
            evidence_snapshot=self._data_summary_evidence_snapshot(captured),
        )

    @staticmethod
    def _report_evidence_for_sources(
        subject: Dict[str, Any],
        posts: List[Dict[str, Any]],
        authors: List[Dict[str, Any]],
        captured_at: str,
        configuration: Dict[str, Any],
    ):
        raw_sources = configuration.get("sources")
        sources = ["current_detail"] if raw_sources is None else list(dict.fromkeys(raw_sources))
        if not sources or any(value not in ("data_summary", "current_detail") for value in sources):
            raise ValueError("大模型报告数据来源无效")
        context_config = None
        context_detail = None
        if "current_detail" in sources:
            context_config = (
                normalize_report_context_config(configuration["context_config"])
                if "context_config" in configuration else None
            )
            context_detail = (
                report_context_detail(configuration.get("context_detail"))
                if context_config is None else None
            )
            evidence, snapshot = build_ai_report_evidence(
                subject,
                posts,
                authors,
                context_detail=context_detail or "standard",
                context_config=context_config,
            )
            snapshot["captured_at"] = captured_at
            snapshot["current_detail_captured_at"] = captured_at
        else:
            scope_key = "author" if subject.get("report_scope") == "author" else "project"
            evidence = {
                "report_context": {
                    "version": 3,
                    "label": "数据摘要",
                    "description": "使用选中的历史数据摘要作为固定统计口径。",
                },
                scope_key: {
                    "id": subject.get("id"),
                    "name": subject.get("name", ""),
                    "research_type": subject.get("research_type", ""),
                    "description": subject.get("description", ""),
                },
                "authors": [],
                "posts": [],
            }
            snapshot = {
                "captured_at": "",
                "post_ids": [],
                "author_ids": [],
                "selected_post_ids": [],
                "selected_author_ids": [],
                "post_count": 0,
                "author_count": 0,
                "evidence_post_count": 0,
                "evidence_author_count": 0,
                "ocr_post_count": 0,
                "vision_post_count": 0,
            }
        if "data_summary" in sources:
            summary_snapshot = configuration.get("data_summary_snapshot")
            if not isinstance(summary_snapshot, dict) or not isinstance(
                summary_snapshot.get("summary_json"), dict
            ):
                raise ValueError("所选数据摘要快照无效")
            summary_evidence = (
                summary_snapshot.get("evidence_snapshot_json")
                if isinstance(summary_snapshot.get("evidence_snapshot_json"), dict) else {}
            )
            evidence["data_summary"] = {
                "report_id": summary_snapshot.get("report_id"),
                "version": summary_snapshot.get("version"),
                "title": summary_snapshot.get("title"),
                "generated_at": summary_snapshot.get("generated_at"),
                "sha256": summary_snapshot.get("sha256"),
                "summary": summary_snapshot["summary_json"],
            }
            snapshot["data_summary"] = {
                key: summary_snapshot.get(key)
                for key in ("report_id", "version", "title", "generated_at", "sha256")
            }
            if "current_detail" not in sources:
                snapshot.update({
                    "captured_at": str(summary_snapshot.get("generated_at") or ""),
                    "post_count": int(summary_evidence.get("post_count") or 0),
                    "author_count": int(summary_evidence.get("author_count") or 0),
                    "evidence_post_count": int(summary_evidence.get("post_count") or 0),
                    "evidence_author_count": int(summary_evidence.get("author_count") or 0),
                    "ocr_post_count": int(summary_evidence.get("ocr_post_count") or 0),
                    "vision_post_count": int(summary_evidence.get("vision_post_count") or 0),
                })
        evidence["source_policy"] = {
            "sources": sources,
            "data_summary_role": (
                "统计数字、趋势和分布的唯一权威口径" if "data_summary" in sources else "未启用"
            ),
            "current_detail_role": (
                "案例、原文与定性证据；不得重新计算或覆盖数据摘要指标"
                if "current_detail" in sources and "data_summary" in sources
                else ("当前明细统计与案例" if "current_detail" in sources else "未启用")
            ),
            "timestamps_are_independent": len(sources) > 1,
        }
        snapshot["sources"] = sources
        return evidence, snapshot, context_config, context_detail

    def run_ai_report(self, task_id: str, project_id: int, configuration: Dict[str, Any]):
        try:
            self._ensure_active(task_id)
            if self.report_provider is None:
                raise RuntimeError("Codex 大模型报告能力当前不可用")
            self.db.update_task(task_id, status="running", current_phase="report_generation", started_at=utcnow())
            self.db.append_task_event(task_id, "report_generation", "progress", {"message": "正在整理项目证据"})
            captured = self._capture_report_evidence(project_id)
            project = captured["project"]
            posts = captured["posts"]
            authors = captured["authors"]
            evidence, snapshot, context_config, context_detail = self._report_evidence_for_sources(
                project, posts, authors, captured["captured_at"], configuration,
            )
            if not evidence.get("posts") and not evidence.get("authors") and not evidence.get("data_summary"):
                raise RuntimeError("当前项目没有所选来源可用于生成报告")
            self._ensure_active(task_id)
            self.db.append_task_event(task_id, "report_generation", "progress", {"message": "正在生成大模型报告"})
            report_title = str(configuration.get("title") or f"{project['name']} 大模型报告").strip()[:200]
            if not report_title:
                report_title = f"{project['name']} 大模型报告"
            instructions = str(configuration.get("instructions") or "").strip()[:1000]
            prompt_templates = normalize_report_prompt_templates(configuration.get("prompt_templates"))
            template_hash = report_prompt_template_hash(prompt_templates)
            report_project = {**project, "report_title": report_title}
            content, pipeline_metadata = self._report_provider_call(
                task_id, report_project, evidence, instructions, prompt_templates,
            )
            snapshot["pipeline"] = pipeline_metadata
            self._ensure_active(task_id)
            summary = {
                "post_count": int(snapshot.get("evidence_post_count", len(posts))),
                "author_count": int(snapshot.get("evidence_author_count", len(authors))),
                "ocr_post_count": snapshot["ocr_post_count"],
                "vision_post_count": snapshot["vision_post_count"],
            }
            generation_context = {"sources": snapshot["sources"]}
            if "current_detail" in snapshot["sources"]:
                generation_context.update(
                    {"context_config": context_config}
                    if context_config is not None else {"context_detail": context_detail}
                )
            if snapshot.get("data_summary"):
                generation_context["data_summary"] = snapshot["data_summary"]
            report_id = self.db.create_report(
                project_id, task_id, project["research_type"], report_title, content, summary,
                generator_type="llm", model=self.report_provider.model or "default",
                prompt_version=self.report_provider.prompt_version, evidence_snapshot=snapshot,
                generation_config={
                    "title": report_title,
                    "instructions": instructions,
                    **generation_context,
                    "prompt_templates": prompt_templates,
                    "prompt_template_hash": template_hash,
                    "pipeline": {
                        "strategy": "configurable-map-reduce-v2" if context_config is not None else "stratified-map-reduce-v1",
                        "chunk_count": pipeline_metadata.get("chunk_count", 1),
                    },
                }, evidence_post_count=summary["post_count"],
                evidence_author_count=summary["author_count"],
                completion_event={"message": "大模型报告已生成", "summary": summary},
            )
            if report_id is None:
                self._ensure_active(task_id)
                raise RuntimeError("task is no longer active at report commit")
        except TaskCancelled:
            return
        except Exception as exc:
            if not self._is_cancelled(task_id):
                self.db.fail_report_task(
                    task_id,
                    str(exc),
                    event_payload={
                        "message": str(exc),
                        "diagnostics": getattr(exc, "diagnostics", {}),
                    },
                )
        finally:
            self._clear_task_signals(task_id)

    def run_author_ai_report(self, task_id: str, author_id: int, configuration: Dict[str, Any]):
        try:
            self._ensure_active(task_id)
            if self.report_provider is None:
                raise RuntimeError("Codex 大模型报告能力当前不可用")
            self.db.update_task(task_id, status="running", current_phase="report_generation", started_at=utcnow())
            self.db.append_task_event(task_id, "report_generation", "progress", {"message": "正在整理作者证据"})
            captured = self._capture_author_report_evidence(author_id)
            subject = captured["project"]
            posts = captured["posts"]
            authors = captured["authors"]
            evidence, snapshot, context_config, context_detail = self._report_evidence_for_sources(
                subject, posts, authors, captured["captured_at"], configuration,
            )
            if not evidence.get("posts") and not evidence.get("authors") and not evidence.get("data_summary"):
                raise RuntimeError("当前作者没有所选来源可用于生成报告")
            snapshot["scope"] = "author"
            snapshot["subject_author_id"] = author_id
            self._ensure_active(task_id)
            self.db.append_task_event(task_id, "report_generation", "progress", {"message": "正在生成作者大模型报告"})
            default_title = f"{subject['name']} 大模型报告"
            report_title = str(configuration.get("title") or default_title).strip()[:200] or default_title
            instructions = str(configuration.get("instructions") or "").strip()[:1000]
            prompt_templates = normalize_report_prompt_templates(configuration.get("prompt_templates"))
            template_hash = report_prompt_template_hash(prompt_templates)
            report_subject = {**subject, "report_title": report_title}
            content, pipeline_metadata = self._report_provider_call(
                task_id, report_subject, evidence, instructions, prompt_templates,
            )
            snapshot["pipeline"] = pipeline_metadata
            self._ensure_active(task_id)
            summary = {
                "post_count": int(snapshot.get("evidence_post_count", len(posts))),
                "author_count": int(snapshot.get("evidence_author_count", 1)),
                "ocr_post_count": snapshot["ocr_post_count"],
                "vision_post_count": snapshot["vision_post_count"],
            }
            generation_context = {"sources": snapshot["sources"]}
            if "current_detail" in snapshot["sources"]:
                generation_context.update(
                    {"context_config": context_config}
                    if context_config is not None else {"context_detail": context_detail}
                )
            if snapshot.get("data_summary"):
                generation_context["data_summary"] = snapshot["data_summary"]
            report_id = self.db.create_author_report(
                author_id, task_id, report_title, content, summary,
                model=self.report_provider.model or "default",
                prompt_version=self.report_provider.prompt_version,
                evidence_snapshot=snapshot,
                generation_config={
                    "title": report_title,
                    "instructions": instructions,
                    **generation_context,
                    "prompt_templates": prompt_templates,
                    "prompt_template_hash": template_hash,
                    "pipeline": {
                        "strategy": "configurable-map-reduce-v2" if context_config is not None else "stratified-map-reduce-v1",
                        "chunk_count": pipeline_metadata.get("chunk_count", 1),
                    },
                },
                evidence_post_count=summary["post_count"], evidence_author_count=summary["author_count"],
                completion_event={"message": "作者大模型报告已生成", "summary": summary},
            )
            if report_id is None:
                self._ensure_active(task_id)
                raise RuntimeError("task is no longer active at author report commit")
        except TaskCancelled:
            return
        except Exception as exc:
            if not self._is_cancelled(task_id):
                self.db.fail_report_task(
                    task_id,
                    str(exc),
                    event_payload={
                        "message": str(exc),
                        "diagnostics": getattr(exc, "diagnostics", {}),
                    },
                )
        finally:
            self._clear_task_signals(task_id)

    def run_report_presentation(self, task_id: str, configuration: Dict[str, Any]):
        try:
            self._ensure_active(task_id)
            if self.report_provider is None:
                raise RuntimeError("Codex HTML 演示稿能力当前不可用")
            presentation_id = int(configuration.get("presentation_id") or 0)
            source_report = configuration.get("source_report")
            if presentation_id <= 0 or not isinstance(source_report, dict):
                raise ValueError("HTML 演示稿任务缺少冻结的源报告或产物占位")
            values = normalize_presentation_configuration({
                "title": configuration.get("title"),
                "page_mode": configuration.get("page_mode"),
                "instructions": configuration.get("instructions"),
            })
            self.db.update_task(
                task_id,
                status="running",
                current_phase="presentation_generation",
                started_at=utcnow(),
            )
            self.db.append_task_event(
                task_id,
                "presentation_generation",
                "progress",
                {"message": "正在规划 HTML 演示稿", "current": 0, "total": 2},
            )
            deck, diagnostics = generate_presentation_deck(
                self.report_provider,
                source_report,
                values,
                should_cancel=lambda: self._is_cancelled(task_id),
            )
            self._ensure_active(task_id)
            self.db.update_task(
                task_id,
                current_phase="presentation_rendering",
                progress_current=1,
                progress_total=2,
            )
            self.db.append_task_event(
                task_id,
                "presentation_rendering",
                "progress",
                {"message": "正在渲染安全的自包含 HTML", "current": 1, "total": 2},
            )
            html_content = render_presentation_html(deck)
            generation_config = {
                **values,
                "source_report_id": source_report.get("id"),
                "source_report_version": source_report.get("version"),
                "source_report_sha256": source_report.get("sha256"),
                "prompt_version": PRESENTATION_PROMPT_VERSION,
            }
            self._ensure_active(task_id)
            completed = self.db.complete_report_presentation(
                task_id,
                presentation_id,
                deck,
                html_content,
                model=getattr(self.report_provider, "model", None) or "default",
                prompt_version=PRESENTATION_PROMPT_VERSION,
                generation_config=generation_config,
                diagnostics=diagnostics,
            )
            if not completed:
                self._ensure_active(task_id)
                raise RuntimeError("task is no longer active at presentation commit")
        except TaskCancelled:
            return
        except CodexProcessCancelled:
            return
        except Exception as exc:
            if not self._is_cancelled(task_id):
                self.db.fail_report_task(
                    task_id,
                    str(exc),
                    event_payload={
                        "message": str(exc),
                        "diagnostics": getattr(exc, "diagnostics", {}),
                    },
                )
        finally:
            self._clear_task_signals(task_id)

    def run_vision(
        self,
        task_id: str,
        project_id: Optional[int],
        configuration: Dict[str, Any],
        author_id: Optional[int] = None,
    ):
        warnings: List[str] = []
        try:
            self._ensure_active(task_id)
            self.db.update_task(task_id, status="running", current_phase="preparing_vision", started_at=utcnow())
            provider = self._vision_provider_for(configuration)
            if provider is None or not self._provider_available(provider):
                raise RuntimeError("所选图片理解 Provider 当前不可用")
            image_scopes = configured_image_scopes(configuration)
            mode = configuration.get("mode", "vision-selective")
            candidates = []
            for image_scope in image_scopes:
                pending = [
                    value for value in self._vision_inputs(
                        project_id,
                        author_id=author_id,
                        provider=provider,
                        image_scope=image_scope,
                    )
                    if not value["analyzed"]
                ]
                selected = pending if mode == "vision-all" else select_vision_candidates(
                    pending,
                    float(configuration.get("vision_ratio", 0.2)),
                    int(configuration.get("vision_count", 10)),
                    int(configuration.get("vision_max_count", 30)),
                )
                candidates.extend(selected)
            if not candidates:
                self.db.update_task(task_id, status="completed", current_phase="completed", progress_current=0,
                                    progress_total=0, result_json={"analyzed_posts": 0}, finished_at=utcnow())
                self.db.append_task_event(task_id, "completed", "completed", {"message": "没有待补充理解的图片"})
                return
            model = provider_vision_model_identity(provider)
            prompt_version = provider.prompt_version
            for candidate in candidates:
                candidate["cache_key"] = candidate.get("cache_key") or provider_vision_cache_key(
                    provider, candidate["image_paths"], candidate["image_scope"],
                )
            cached_analyses = self.db.get_vision_analysis_cache(
                (candidate["cache_key"] for candidate in candidates), model, prompt_version,
            )
            self._phase(task_id, "vision", 0, len(candidates), "开始补充图片理解")
            completed = 0
            processed = 0
            batch_size = max(1, min(int(configuration.get("vision_batch_size", 5)), 20))
            for image_scope in image_scopes:
                scope_candidates = [
                    candidate for candidate in candidates
                    if candidate["image_scope"] == image_scope
                ]
                for start in range(0, len(scope_candidates), batch_size):
                    self._ensure_active(task_id)
                    batch = scope_candidates[start:start + batch_size]
                    unresolved = []
                    try:
                        pending_by_cache = {}
                        for candidate in batch:
                            cached = cached_analyses.get(candidate["cache_key"])
                            if cached is not None:
                                self.db.save_current_vision_analysis(
                                    candidate["post_id"], candidate["cache_key"], model,
                                    prompt_version, cached, image_scope,
                                )
                                completed += 1
                            else:
                                pending_by_cache.setdefault(candidate["cache_key"], []).append(candidate)
                                unresolved.append(candidate)
                        representatives = [values[0] for values in pending_by_cache.values()]
                        results = (
                            self._provider_call(
                                task_id, provider.analyze_batch,
                                representatives, self.vision_batch_schema,
                            ) if representatives else {}
                        )
                        for cache_key, matching_candidates in pending_by_cache.items():
                            analysis = results.get(matching_candidates[0]["post_id"])
                            if analysis is None:
                                warnings.extend(
                                    f"帖子 {candidate['post_id']} {image_scope} 图片理解未返回结果"
                                    for candidate in matching_candidates
                                )
                                continue
                            for candidate in matching_candidates:
                                self._ensure_active(task_id)
                                self.db.save_current_vision_analysis(
                                    candidate["post_id"], cache_key, model, prompt_version,
                                    analysis, image_scope,
                                )
                                completed += 1
                            cached_analyses[cache_key] = analysis
                    except Exception as exc:
                        warnings.extend(
                            f"帖子 {candidate['post_id']} {image_scope} 图片理解失败：{exc}"
                            for candidate in unresolved or batch
                        )
                    processed += len(batch)
                    self._phase(
                        task_id, "vision", processed, len(candidates),
                        f"已完成 {image_scope} 第 {start // batch_size + 1} 批，共 {len(batch)} 篇",
                    )
            status = "partial" if warnings else "completed"
            summary = {
                "analyzed_posts": completed,
                "selected_posts": len(candidates),
                "selected_image_scopes": image_scopes,
                "warning_count": len(warnings),
            }
            if completed > 0:
                self._complete_task_with_data_summary(
                    task_id,
                    project_id=project_id,
                    author_id=author_id,
                    status=status,
                    result=summary,
                    warnings=warnings,
                    operation="vision",
                    task_type="vision",
                )
            else:
                self.db.update_task(task_id, status=status, current_phase="completed", progress_current=len(candidates),
                                    progress_total=len(candidates), warning_count=len(warnings), result_json=summary,
                                    finished_at=utcnow())
                self.db.append_task_event(task_id, "completed", status, {"summary": summary, "warnings": warnings})
        except TaskCancelled:
            return
        except Exception as exc:
            if not self._is_cancelled(task_id):
                self.db.update_task(task_id, status="failed", current_phase="failed", error_message=str(exc), finished_at=utcnow())
                self.db.append_task_event(task_id, "failed", "error", {"message": str(exc)})
        finally:
            self._clear_task_signals(task_id)

    def run_ocr(
        self,
        task_id: str,
        project_id: Optional[int],
        configuration: Dict[str, Any],
        author_id: Optional[int] = None,
    ):
        warnings: List[str] = []
        try:
            self._ensure_active(task_id)
            self.db.update_task(task_id, status="running", current_phase="preparing_ocr", started_at=utcnow())
            provider = self._ocr_provider_for(configuration)
            if provider is None or not self._provider_available(provider):
                raise RuntimeError("所选 OCR Provider 当前不可用")
            image_scopes = configured_image_scopes(configuration)
            candidates = []
            for image_scope in image_scopes:
                pending = [
                    value for value in self._ocr_inputs(
                        project_id, author_id, provider, image_scope,
                    )
                    if not value["completed"]
                ]
                if configuration.get("mode") == "vision-all":
                    selected = pending
                else:
                    selected = select_vision_candidates(
                        [
                            {
                                **value,
                                "title": "",
                                "author_id": "",
                                "note_type": "image",
                                "popularity_percentile": 0,
                                "ocr_text": "",
                            }
                            for value in pending
                        ],
                        float(configuration.get("vision_ratio", 0.2)),
                        int(configuration.get("vision_count", 10)),
                        int(configuration.get("vision_max_count", 30)),
                    )
                candidates.extend(selected)
            if not candidates:
                self.db.update_task(task_id, status="completed", current_phase="completed", progress_current=0,
                                    progress_total=0, result_json={"ocr_posts": 0}, finished_at=utcnow())
                self.db.append_task_event(task_id, "ocr", "completed", {"message": "没有待补充 OCR 的本地图片"})
                return
            self._phase(task_id, "ocr", 0, len(candidates), "开始补充图片 OCR")
            completed = 0
            for index, candidate in enumerate(candidates, 1):
                self._ensure_active(task_id)
                try:
                    for media in candidate["media"]:
                        if media["completed"]:
                            continue
                        text = self._provider_call(task_id, provider.analyze, media["path"])
                        self.db.save_media_ocr(
                            media["id"], text, provider.engine_name,
                            getattr(provider, "version", ""),
                        )
                    completed += 1
                except Exception as exc:
                    warnings.append(
                        f"帖子 {candidate['post_id']} {candidate['image_scope']} OCR 失败：{exc}"
                    )
                self._phase(task_id, "ocr", index, len(candidates), f"已完成 {index}/{len(candidates)} 篇")
            status = "partial" if warnings else "completed"
            summary = {
                "ocr_posts": completed,
                "selected_posts": len(candidates),
                "selected_image_scopes": image_scopes,
                "warning_count": len(warnings),
            }
            if completed > 0:
                self._complete_task_with_data_summary(
                    task_id,
                    project_id=project_id,
                    author_id=author_id,
                    status=status,
                    result=summary,
                    warnings=warnings,
                    operation="ocr",
                    task_type="vision",
                )
            else:
                self.db.update_task(task_id, status=status, current_phase="completed", progress_current=len(candidates),
                                    progress_total=len(candidates), warning_count=len(warnings), result_json=summary,
                                    finished_at=utcnow())
                self.db.append_task_event(task_id, "completed", status, {"summary": summary, "warnings": warnings})
        except TaskCancelled:
            return
        except Exception as exc:
            if not self._is_cancelled(task_id):
                self.db.update_task(task_id, status="failed", current_phase="failed", error_message=str(exc), finished_at=utcnow())
                self.db.append_task_event(task_id, "failed", "error", {"message": str(exc)})
        finally:
            self._clear_task_signals(task_id)

    def run(self, task_id: str, request: ResearchRequest):
        warnings: List[str] = []
        collector_usage: Dict[str, Dict[str, int]] = {}
        capability_usage: Dict[str, Dict[str, Any]] = {}
        try:
            self._ensure_active(task_id)
            if not self.collectors:
                raise CollectorError("当前没有可用的数据采集提供方", "collector_unavailable")
            runtime_policy = self._policy_snapshot()
            capability_registry = self._capability_registry_snapshot()
            self.db.update_task(task_id, status="running", current_phase="starting", started_at=utcnow())

            if request.author_update_scopes:
                self._run_author_update(
                    task_id,
                    request,
                    warnings,
                    collector_usage,
                    capability_usage,
                    capability_registry,
                    runtime_policy,
                )
                return

            author_ids = list(request.author_ids)
            author_collection_scopes = set(request.author_collection_scopes)
            keyword_discovered_author_ids = set()
            if request.user_keywords:
                self._phase(task_id, "user_discovery", 0, len(request.user_keywords), "开始按关键词发现用户")
                remaining = request.user_discovery_limit
                for index, keyword in enumerate(request.user_keywords, 1):
                    if remaining <= 0:
                        break
                    _provider_id, _collector, raw = self._route_capability(
                        task_id,
                        SEARCH_USERS_BY_KEYWORD,
                        (keyword, remaining),
                        keyword,
                        "user_keyword",
                        collector_usage,
                        capability_usage,
                        capability_registry,
                    )
                    self._extend_warnings(warnings, (raw or {}).get("warnings"))
                    for profile in (raw or {}).get("profiles") or []:
                        author_id = str(profile.get("author_id") or "")
                        if not author_id or author_id in author_ids:
                            continue
                        self._ingest_profile(
                            request.project_id,
                            task_id,
                            profile,
                            "task_added",
                            runtime_policy["author_ttl_days"],
                        )
                        author_ids.append(author_id)
                        keyword_discovered_author_ids.add(author_id)
                        remaining -= 1
                        if remaining <= 0:
                            break
                    self._phase(
                        task_id,
                        "user_discovery",
                        index,
                        len(request.user_keywords),
                        f"已完成用户关键词 {keyword}，当前发现 {len(author_ids) - len(request.author_ids)} 位用户",
                    )

            if request.mode == "mixed":
                sources = ([
                    (keyword, "keyword", request.keyword_discovery_limit, request.keyword_deep_limit)
                    for keyword in request.keywords
                ] + [
                    (author_id, "author", request.author_discovery_limit, request.author_deep_limit)
                    for author_id in author_ids
                ])
            elif request.mode == "author":
                if request.author_collection_explicit and "basic_info" in author_collection_scopes:
                    self._phase(task_id, "author_profile", 0, len(author_ids), "开始采集作者基础信息")
                    for index, author_id in enumerate(author_ids, 1):
                        provider_id, collector, raw = self._route_capability(
                            task_id,
                            READ_AUTHOR_PROFILE,
                            (author_id,),
                            author_id,
                            "author",
                            collector_usage,
                            capability_usage,
                            capability_registry,
                        )
                        normalized = self._normalize_collector_result(collector, raw, "author", author_id)
                        self._extend_warnings(warnings, normalized.get("warnings"))
                        self._ingest_profile(
                            request.project_id,
                            task_id,
                            normalized.get("profile") or {"author_id": author_id},
                            "task_added",
                            runtime_policy["author_ttl_days"],
                            force_refresh=request.force_refresh,
                        )
                        capability_usage[READ_AUTHOR_PROFILE]["selected_provider"] = provider_id
                        self._phase(task_id, "author_profile", index, len(author_ids), f"已完成 {author_id}")
                sources = (
                    [(author_id, "author", request.discovery_limit, request.deep_limit)
                     for author_id in author_ids]
                    if not request.author_collection_explicit or "posts" in author_collection_scopes else []
                )
            else:
                sources = [(keyword, "keyword", request.discovery_limit, request.deep_limit)
                           for keyword in request.keywords]
            discovered = {}
            self._phase(task_id, "discovery", 0, len(sources), "开始发现帖子")
            for index, (source, source_type, discovery_limit, _) in enumerate(sources, 1):
                normalized = self._collect_source(
                    task_id, "preview", source, source_type,
                    discovery_limit, request.filters, collector_usage, capability_usage,
                    capability_registry,
                )
                self._extend_warnings(warnings, normalized.get("warnings"))
                relation = "task_added" if source_type == "author" else None
                if (
                    source_type != "author"
                    or not request.author_collection_explicit
                    or "basic_info" in author_collection_scopes
                ):
                    self._ingest_profile(
                        request.project_id if relation else None,
                        task_id,
                        normalized["profile"],
                        relation,
                        runtime_policy["author_ttl_days"],
                    )
                elif request.project_id is not None:
                    # 仅采集帖子时仍建立项目与明确作者的关联，但不读取或覆盖基础资料。
                    self._ingest_profile(
                        request.project_id,
                        task_id,
                        {"author_id": source},
                        relation,
                        runtime_policy["author_ttl_days"],
                    )
                self._ingest_cards(
                    request.project_id,
                    task_id,
                    normalized["cards"],
                    attach_to_project=source_type == "keyword",
                    author_relation="keyword_post_author",
                )
                known_count = 0
                discovered[(source_type, source)] = normalized["cards"]
                message = f"已完成 {source}"
                if known_count > len(normalized["cards"]):
                    message += f"，并复用本地已有帖子，当前共 {known_count} 篇"
                self._phase(task_id, "discovery", index, len(sources), message)

            deep_sources = [item for item in sources if item[3]]
            if deep_sources:
                self._phase(task_id, "deep_scan", 0, len(deep_sources), "开始深度读取")
                for index, (source, source_type, _, deep_limit) in enumerate(deep_sources, 1):
                    expected = [card.get("note_id") for card in discovered.get((source_type, source), [])[:deep_limit]]
                    detail_ttl_days = runtime_policy["detail_ttl_days"]
                    if (not request.force_refresh and self.db.post_details_are_fresh(expected, detail_ttl_days)):
                        self._phase(task_id, "deep_scan", index, len(deep_sources), f"{source} 的详情缓存仍有效，已跳过")
                        continue
                    normalized = self._collect_source(
                        task_id, "deep", source, source_type,
                        deep_limit, request.filters, collector_usage, capability_usage,
                        capability_registry,
                    )
                    self._extend_warnings(warnings, normalized.get("warnings"))
                    warnings.extend(self._ingest_notes(request.project_id, task_id, normalized["notes"]))
                    self._phase(task_id, "deep_scan", index, len(deep_sources), f"已完成 {source}")

            if request.project_id is None:
                posts = self.db.list_task_posts(task_id)
                authors = self.db.list_task_authors(task_id)
                collected_author_ids = {
                    str(author.get("author_id") or "") for author in authors
                } | keyword_discovered_author_ids
                collected_author_ids.discard("")
                scoring = score_posts([{**post, "post_id": post["id"]} for post in posts])
                summary = {
                    "post_count": len(posts),
                    "author_count": len(collected_author_ids),
                    "keyword_discovered_author_count": len(keyword_discovered_author_ids),
                    "scoring_method": scoring["method"],
                    "warning_count": len(warnings),
                    "routing_mode": "capability",
                    "collector_usage": collector_usage,
                    "capability_usage": capability_usage,
                    "capability_routes": capability_registry.describe_routes(),
                }
                status = "partial" if warnings else "completed"
                self._ensure_active(task_id)
                self.db.update_task(
                    task_id,
                    status=status,
                    current_phase="completed",
                    progress_current=1,
                    progress_total=1,
                    warning_count=len(warnings),
                    error_message="",
                    result_json=summary,
                    finished_at=utcnow(),
                )
                self.db.append_task_event(
                    task_id,
                    "completed",
                    status,
                    {"summary": summary, "warnings": warnings},
                )
                return

            posts = self.db.list_project_posts(request.project_id)
            scoring_input = [{**post, "post_id": post["id"]} for post in posts]
            scoring = score_posts(scoring_input)
            self.db.save_project_scores(request.project_id, scoring)
            posts = self.db.list_project_posts(request.project_id)

            captured = self._capture_report_evidence(request.project_id)
            authors = captured["authors"]
            posts = captured["posts"]
            project = captured["project"]
            self._ensure_active(task_id)
            task_summary = {
                "post_count": len(posts),
                "author_count": len(authors),
                "scoring_method": scoring["method"],
                "warning_count": len(warnings),
                "routing_mode": "capability",
                "collector_usage": collector_usage,
                "capability_usage": capability_usage,
                "capability_routes": capability_registry.describe_routes(),
            }
            data_summary = build_project_data_summary(captured)
            status = "partial" if warnings else "completed"
            report_id = self.db.create_data_summary(
                project_id=request.project_id,
                summary=data_summary,
                task_id=task_id,
                task_status=status,
                task_result=task_summary,
                task_warning_count=len(warnings),
                completion_event={"summary": task_summary, "warnings": warnings},
                generation_config={
                    "trigger": "automatic",
                    "operation": "research",
                    "task_type": "research",
                },
                evidence_snapshot=self._data_summary_evidence_snapshot(captured),
            )
        except TaskCancelled:
            return
        except CollectorError as exc:
            if exc.code == "cancelled" or self._is_cancelled(task_id):
                return
            status = "waiting_login" if exc.code == "login_required" else "failed"
            self.db.update_task(task_id, status=status, current_phase=status, error_message=str(exc), finished_at=utcnow())
            self.db.append_task_event(task_id, status, "error", {"message": str(exc), "code": exc.code})
        except Exception as exc:
            if self._is_cancelled(task_id):
                return
            self.db.update_task(task_id, status="failed", current_phase="failed", error_message=str(exc), finished_at=utcnow())
            self.db.append_task_event(task_id, "failed", "error", {"message": str(exc)})
        finally:
            self._clear_task_signals(task_id)
