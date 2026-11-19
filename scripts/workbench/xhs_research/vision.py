import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional
import uuid

from .codex_process import run_codex_process


DEFAULT_VISION_TIMEOUT_SECONDS = 600
VISION_TIMEOUT_MIN_SECONDS = 60
VISION_TIMEOUT_MAX_SECONDS = 3600
VISION_REASONING_EFFORTS = ("default", "low", "medium", "high", "xhigh", "max", "ultra")


def list_codex_image_models(binary: str, timeout: float = 5.0) -> List[Dict[str, Any]]:
    try:
        result = subprocess.run(
            [str(binary), "debug", "models"],
            capture_output=True,
            text=True,
            timeout=max(1.0, min(float(timeout), 30.0)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"无法读取 Codex 模型目录：{exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or "Codex 模型目录读取失败")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Codex 模型目录返回格式无效") from exc
    models = []
    for value in payload.get("models") or []:
        if not isinstance(value, dict):
            continue
        modalities = [str(item) for item in value.get("input_modalities") or []]
        if "image" not in modalities or value.get("visibility") not in (None, "list"):
            continue
        model_id = str(value.get("slug") or "").strip()
        if not model_id:
            continue
        efforts = []
        for item in value.get("supported_reasoning_levels") or []:
            effort = str((item or {}).get("effort") or "").strip()
            if effort and effort not in efforts:
                efforts.append(effort)
        models.append({
            "id": model_id,
            "label": str(value.get("display_name") or model_id),
            "default_reasoning_effort": str(
                value.get("default_reasoning_level") or "default"
            ),
            "reasoning_efforts": efforts,
        })
    return models


def image_scope_prompt(image_scope: str) -> str:
    if image_scope == "cover":
        return "输入只包含封面图，重点判断封面钩子、首屏吸引力和封面信息表达。"
    if image_scope == "detail":
        return "输入只包含详情图片，不要把详情图描述成封面；封面钩子字段请明确写为未分析封面。"
    return "输入包含封面和详情图片，请综合判断封面钩子及整组视觉表达。"


def select_vision_candidates(posts: List[Dict[str, Any]], ratio: float = 0.2, count: int = 10,
                             max_count: int = 30):
    target = min(len(posts), max_count, max(count, int(math.ceil(len(posts) * ratio))))
    if target <= 0:
        return []
    selected = []
    used = set()

    def add(post, reason):
        post_id = post["post_id"]
        if post_id in used or len(selected) >= target:
            return
        used.add(post_id)
        selected.append({**post, "reason": reason})

    weights = [("high_engagement", 0.5), ("low_ocr", 0.2), ("representative", 0.2), ("exploratory", 0.1)]
    quotas = {name: int(math.floor(target * weight)) for name, weight in weights}
    remaining = target - sum(quotas.values())
    fractional = sorted(weights, key=lambda item: (-(target * item[1] - math.floor(target * item[1])), weights.index(item)))
    for name, _ in fractional[:remaining]:
        quotas[name] += 1

    ranked = sorted(posts, key=lambda p: p.get("popularity_percentile") or 0, reverse=True)
    low_ocr = [post for post in ranked if not str(post.get("ocr_text") or "").strip()]
    represented, seen_groups = [], set()
    for post in ranked:
        key = (post.get("author_id"), post.get("note_type"))
        if key not in seen_groups:
            seen_groups.add(key)
            represented.append(post)
    exploratory = list(reversed(ranked))
    pools = {
        "high_engagement": ranked,
        "low_ocr": low_ocr,
        "representative": represented,
        "exploratory": exploratory,
    }
    for reason, _ in weights:
        added = 0
        for post in pools[reason]:
            before = len(selected)
            add(post, reason)
            if len(selected) > before:
                added += 1
            if added >= quotas[reason]:
                break
    for post in ranked:
        add(post, "exploratory")
    return selected


class CodexVisionProvider:
    supports_persisted_current_state = True

    def __init__(self, binary: str = "codex", model: Optional[str] = None, prompt_version: str = "v1",
                 work_dir: Optional[Path] = None, timeout: float = DEFAULT_VISION_TIMEOUT_SECONDS,
                 reasoning_effort: str = "default"):
        self.binary = binary
        self.model = model
        self.prompt_version = prompt_version
        self.work_dir = Path(work_dir) if work_dir else None
        self.timeout = timeout
        self.reasoning_effort = str(reasoning_effort or "default")
        if self.reasoning_effort not in VISION_REASONING_EFFORTS:
            raise ValueError("图片理解推理强度无效")

    def configured(self, model: str = "", reasoning_effort: str = "default",
                   timeout: float = DEFAULT_VISION_TIMEOUT_SECONDS):
        return CodexVisionProvider(
            self.binary,
            model=str(model or "").strip() or None,
            prompt_version=self.prompt_version,
            work_dir=self.work_dir,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        )

    @property
    def persisted_model_identity(self) -> str:
        model = self.model or "default"
        if self.reasoning_effort == "default":
            return model
        return f"{model}::reasoning={self.reasoning_effort}"

    def _command(self, schema_path: Path, output: Path) -> List[str]:
        args = [
            self.binary, "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "--output-schema", str(schema_path),
            "-o", str(output),
        ]
        if self.model:
            args.extend(["--model", self.model])
        if self.reasoning_effort != "default":
            args.extend([
                "--config", f'model_reasoning_effort="{self.reasoning_effort}"',
            ])
        return args

    def cache_key(self, image_paths: List[str], image_scope: str = "all"):
        digest = hashlib.sha256(b"xhs-vision-cache-v2\0")
        digest.update(str(image_scope or "all").encode("utf-8"))
        digest.update(b"\0")
        for value in image_paths:
            path = Path(value)
            content = path.read_bytes() if path.exists() else value.encode("utf-8")
            digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
            digest.update(b"\0")
        digest.update(self.prompt_version.encode("utf-8"))
        digest.update(b"\0")
        digest.update((self.model or "default").encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.reasoning_effort.encode("utf-8"))
        return digest.hexdigest()

    def analyze(self, title: str, image_paths: List[str], schema_path: Path,
                image_scope: str = "all",
                should_cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        if not image_paths:
            raise ValueError("vision analysis requires local images")
        output_root = self.work_dir or schema_path.parent
        output_root.mkdir(parents=True, exist_ok=True)
        output = output_root / (
            f"vision-{self.cache_key(image_paths, image_scope)[:12]}-{uuid.uuid4().hex}.json"
        )
        prompt = (
            f"分析这篇小红书帖子的视觉表达。标题：{title}。{image_scope_prompt(image_scope)}"
            "只输出符合 schema 的 JSON，判断封面钩子、视觉风格、版式、信息密度、可信度信号、情绪、适合人群、可复用模式和问题。"
        )
        args = self._command(schema_path, output)
        for path in image_paths:
            args.extend(["-i", path])
        output.unlink(missing_ok=True)
        try:
            result = run_codex_process(args, prompt, self.timeout, should_cancel=should_cancel)
            if result.returncode:
                raise RuntimeError((result.stderr or "").strip() or "Codex vision failed")
            return json.loads(output.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)

    def analyze_batch(self, posts: List[Dict[str, Any]], schema_path: Path,
                      should_cancel: Optional[Callable[[], bool]] = None) -> Dict[int, Dict[str, Any]]:
        if not posts:
            return {}
        output_root = self.work_dir or schema_path.parent
        output_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        image_paths = []
        prompt_rows = []
        image_index = 1
        for post in posts:
            paths = post.get("image_paths") or []
            if not paths:
                raise ValueError("vision batch requires local images")
            digest.update(str(post["post_id"]).encode("utf-8"))
            image_scope = str(post.get("image_scope") or "all")
            digest.update(self.cache_key(paths, image_scope).encode("utf-8"))
            indexes = list(range(image_index, image_index + len(paths)))
            image_index += len(paths)
            image_paths.extend(paths)
            prompt_rows.append(
                f"- 帖子 ID：{post['post_id']}；标题：{post.get('title') or '无标题'}；"
                f"图片范围：{image_scope}；{image_scope_prompt(image_scope)}"
                f"对应输入图片：{','.join(map(str, indexes))}。"
            )
        output = output_root / (
            f"vision-batch-{digest.hexdigest()[:12]}-{uuid.uuid4().hex}.json"
        )
        prompt = (
            "按输入顺序分析以下多篇小红书帖子的视觉表达；每篇的图片范围以任务行标注为准。"
            "只能用该帖对应的输入图片，不要混用不同帖子的图片。"
            "返回 results 数组，每条必须保留给定 post_id，并在 analysis 中判断封面钩子、视觉风格、版式、"
            "信息密度、可信度信号、情绪、适合人群、可复用模式和问题。\n"
            + "\n".join(prompt_rows)
        )
        args = self._command(schema_path, output)
        for path in image_paths:
            args.extend(["-i", path])
        output.unlink(missing_ok=True)
        try:
            result = run_codex_process(args, prompt, self.timeout, should_cancel=should_cancel)
            if result.returncode:
                raise RuntimeError((result.stderr or "").strip() or "Codex vision batch failed")
            value = json.loads(output.read_text(encoding="utf-8"))
            results = {}
            for item in value.get("results") or []:
                try:
                    results[int(item["post_id"])] = item["analysis"]
                except (KeyError, TypeError, ValueError):
                    continue
            return results
        finally:
            output.unlink(missing_ok=True)
