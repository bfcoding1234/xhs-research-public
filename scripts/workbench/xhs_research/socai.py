from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional

from .collector import (
    CollectorError,
    DOWNLOAD_MEDIA,
    LIST_AUTHOR_POSTS,
    OCR_MEDIA,
    READ_AUTHOR_PROFILE,
    READ_AUTHOR_POST_DETAILS,
    READ_KEYWORD_POST_DETAILS,
    SEARCH_POSTS_BY_KEYWORD,
)


class SocaiError(CollectorError):
    def __init__(self, message: str, code: str = "socai_failed"):
        super().__init__(message)
        self.code = code


def classify_socai_error(message: str) -> str:
    """Map browser interruptions to states the task runner can recover from."""
    normalized = str(message or "").lower()
    if any(marker in normalized for marker in ("login_required", "website-login")):
        return "login_required"
    if any(marker in normalized for marker in (
        "verification_required", "captcha", "security verification", "security check",
        "验证码", "安全验证", "人机验证", "not_profile_page", "card_click_failed",
    )):
        return "verification_required"
    return "socai_failed"


def parse_count(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(",", "").replace("+", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|w|k)?", text)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2) in ("万", "w"):
        number *= 10000
    elif match.group(2) == "k":
        number *= 1000
    return int(round(number))


def _unwrap(raw: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw.get("data"), dict):
        data = dict(raw["data"])
        if raw.get("run_dir") and not data.get("run_dir"):
            data["run_dir"] = raw["run_dir"]
        return data
    return raw


def normalize_socai_result(raw: Dict[str, Any], mode: str, source_value: str) -> Dict[str, Any]:
    raw = _unwrap(raw)
    profile = dict(raw.get("profile") or {})
    if profile:
        profile = {
            **profile,
            "author_id": raw.get("author_id") or profile.get("author_id") or source_value,
            "display_name": profile.get("display_name") or profile.get("title", ""),
            "followers_count": parse_count(profile.get("followers")),
            "following_count": parse_count(profile.get("following")),
            "likes_collections_count": parse_count(profile.get("likes_and_collections")),
            "total_post_count": parse_count(
                profile.get("total_post_count")
                or profile.get("notes_count")
                or profile.get("note_count")
                or profile.get("post_count")
            ),
        }
    cards = profile.get("note_cards") if mode == "author" else raw.get("cards")
    cards = list(cards or [])
    normalized_cards = []
    for index, card in enumerate(cards):
        item = dict(card)
        item["likes_count"] = parse_count(item.get("likes"))
        item["source_type"] = mode
        item["source_value"] = source_value
        item["source_rank"] = int(item.get("position", index))
        item["detail_level"] = "card"
        normalized_cards.append(item)
    notes = []
    for entry in raw.get("notes") or []:
        entity = entry.get("entity") if isinstance(entry, dict) else None
        if not isinstance(entity, dict):
            continue
        item = dict(entity)
        item["likes_count"] = parse_count(item.get("likes"))
        item["favorites_count"] = parse_count(item.get("favorites"))
        item["comments_count"] = parse_count(item.get("comments_count"))
        item["detail_level"] = "media" if item.get("images") or item.get("video") else "detail"
        item["source_type"] = mode
        item["source_value"] = source_value
        item["_socai_ok"] = bool(entry.get("ok", True))
        item["_socai_error"] = entry.get("error", "")
        notes.append(item)
    artifact = raw.get("artifact") or {}
    return {
        "profile": profile,
        "cards": normalized_cards,
        "notes": notes,
        "artifact_path": artifact.get("path", "") if isinstance(artifact, dict) else "",
        "run_dir": raw.get("run_dir", ""),
        "raw": raw,
    }


def _execute(args, env, timeout, should_cancel=lambda: False):
    process = subprocess.Popen(args, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if should_cancel():
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise SocaiError("task cancelled", "cancelled")
            if time.monotonic() >= deadline:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    if process.returncode:
        message = (stderr or stdout).strip()
        code = classify_socai_error(message)
        raise SocaiError(message or f"socai exited with {process.returncode}", code)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SocaiError(f"invalid Socai JSON: {exc}: {stdout[-500:]}") from exc
    run_match = re.search(r"run_dir:\s*(.+)", stderr)
    if run_match and isinstance(payload, dict):
        payload.setdefault("run_dir", run_match.group(1).strip())
    if isinstance(payload, dict) and payload.get("ok") is False:
        serialized = json.dumps(payload, ensure_ascii=False)
        reason = str(payload.get("reason") or payload.get("error") or "Socai 返回失败状态")
        code = classify_socai_error(serialized)
        raise SocaiError(reason, code)
    artifact = payload.get("artifact") if isinstance(payload, dict) else None
    artifact_path = artifact.get("path") if isinstance(artifact, dict) else None
    if artifact_path and Path(artifact_path).is_file():
        try:
            full = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
            if isinstance(full, dict):
                for key in ("notes", "profile", "cards", "sampling", "media_manifest_path", "media_manifest_count"):
                    if key in full:
                        payload[key] = full[key]
        except (OSError, json.JSONDecodeError):
            pass
    return payload


class SocaiClient:
    provider_id = "socai"
    display_name = "Socai"
    capabilities = {
        SEARCH_POSTS_BY_KEYWORD,
        READ_AUTHOR_PROFILE,
        LIST_AUTHOR_POSTS,
        READ_KEYWORD_POST_DETAILS,
        READ_AUTHOR_POST_DETAILS,
        OCR_MEDIA,
        DOWNLOAD_MEDIA,
    }
    command_specs = (
        {
            "id": "socai.search_posts_by_keyword",
            "capability": SEARCH_POSTS_BY_KEYWORD,
            "method": "search_posts_by_keyword",
            "label": "Socai · 搜索帖子预览",
            "instruction": "socai xhs search {keyword} --num-notes {limit} --preview --pretty",
        },
        {
            "id": "socai.read_author_profile",
            "capability": READ_AUTHOR_PROFILE,
            "method": "read_author_profile",
            "label": "Socai · 作者基础信息",
            "instruction": "socai xhs author {author_id} --num-notes 1 --preview --pretty",
        },
        {
            "id": "socai.list_author_posts",
            "capability": LIST_AUTHOR_POSTS,
            "method": "list_author_posts",
            "label": "Socai · 用户主页帖子预览",
            "instruction": "socai xhs author {author_id} --num-notes {limit} --preview --pretty",
        },
        {
            "id": "socai.read_keyword_post_details",
            "capability": READ_KEYWORD_POST_DETAILS,
            "method": "read_keyword_post_details",
            "label": "Socai · 搜索并读取帖子详情",
            "instruction": "socai xhs search {keyword} --num-notes {limit} --num-comments 8 --download-media --ocr --pretty",
        },
        {
            "id": "socai.read_author_post_details",
            "capability": READ_AUTHOR_POST_DETAILS,
            "method": "read_author_post_details",
            "label": "Socai · 读取用户帖子详情",
            "instruction": "socai xhs author {author_id} --num-notes {limit} --num-comments 8 --download-media --ocr --pretty",
        },
    )

    def __init__(self, binary: str = "socai", data_dir: Optional[Path] = None,
                 executor: Callable = _execute, timeout: int = 1200):
        self.binary = binary
        self.data_dir = Path(data_dir) if data_dir else None
        self.executor = executor
        self.timeout = timeout
        self.local = threading.local()

    @contextmanager
    def cancellation_scope(self, should_cancel):
        previous = getattr(self.local, "should_cancel", None)
        self.local.should_cancel = should_cancel
        try:
            yield
        finally:
            self.local.should_cancel = previous

    def _run(self, args):
        env = os.environ.copy()
        if self.data_dir:
            env["SOCAI_RUNS_DIR"] = str(self.data_dir / "runs")
        should_cancel = getattr(self.local, "should_cancel", None) or (lambda: False)
        try:
            return self.executor([self.binary] + args, env, self.timeout, should_cancel)
        except TypeError as exc:
            if "positional" not in str(exc):
                raise
            return self.executor([self.binary] + args, env, self.timeout)

    def normalize_result(self, raw: Dict[str, Any], mode: str, source_value: str):
        return normalize_socai_result(raw, mode, source_value)

    def author_preview(self, author_id: str, limit: int, ocr: bool = False):
        args = ["xhs", "author", author_id, "--num-notes", str(limit), "--preview"]
        if ocr:
            args.append("--ocr")
        args.append("--pretty")
        return self._run(args)

    def read_author_profile(self, author_id: str):
        return self.author_preview(author_id, 1, ocr=False)

    def keyword_preview(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None, ocr: bool = False):
        args = ["xhs", "search", keyword, "--num-notes", str(limit), "--preview"]
        for key, value in (filters or {}).items():
            args.extend(["--filter", f"{key}={value}"])
        if ocr:
            args.append("--ocr")
        args.append("--pretty")
        return self._run(args)

    def author_deep(self, author_id: str, limit: int, ocr: bool = True, download_media: bool = True):
        args = ["xhs", "author", author_id, "--num-notes", str(limit), "--num-comments", "8"]
        if download_media:
            args.append("--download-media")
        if ocr:
            args.append("--ocr")
        args.append("--pretty")
        return self._run(args)

    def keyword_deep(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None,
                     ocr: bool = True, download_media: bool = True):
        args = ["xhs", "search", keyword, "--num-notes", str(limit), "--num-comments", "8"]
        for key, value in (filters or {}).items():
            args.extend(["--filter", f"{key}={value}"])
        if download_media:
            args.append("--download-media")
        if ocr:
            args.append("--ocr")
        args.append("--pretty")
        return self._run(args)

    # 原子能力入口；保留旧方法名以兼容历史调用方。
    search_posts_by_keyword = keyword_preview
    list_author_posts = author_preview
    read_keyword_post_details = keyword_deep
    read_author_post_details = author_deep
