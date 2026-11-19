from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from .collector import (
    CollectorError,
    DOWNLOAD_MEDIA,
    LIST_AUTHOR_POSTS,
    READ_AUTHOR_POST_DETAILS,
    READ_KEYWORD_POST_DETAILS,
    READ_POST_DETAIL,
    SEARCH_POSTS_BY_KEYWORD,
)
from .socai import parse_count


def classify_opencli_error(returncode: int, message: str) -> str:
    normalized = str(message or "").lower()
    if returncode == 77 or any(value in normalized for value in (
        "auth_required", "authentication required", "requires login", "登录",
    )):
        return "login_required"
    if any(value in normalized for value in ("security_block", "captcha", "安全限制", "验证码")):
        return "verification_required"
    if returncode == 69:
        return "opencli_browser_unavailable"
    if returncode == 75:
        return "opencli_timeout"
    if returncode == 78:
        return "opencli_config_error"
    return "opencli_failed"


def _execute(args, env, timeout, should_cancel=lambda: False):
    try:
        process = subprocess.Popen(args, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise CollectorError(str(exc), "opencli_failed") from exc
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
                raise CollectorError("task cancelled", "cancelled")
            if time.monotonic() >= deadline:
                process.kill()
                stdout, stderr = process.communicate()
                raise CollectorError(
                    f"OpenCLI 调用超时（{timeout} 秒）：{(stderr or stdout)[-500:]}",
                    "opencli_timeout",
                )
    if process.returncode == 66:
        return []
    if process.returncode:
        message = (stderr or stdout or "").strip()
        raise CollectorError(
            message or f"OpenCLI exited with {process.returncode}",
            classify_opencli_error(process.returncode, message),
        )
    try:
        payload = json.loads((stdout or "").strip() or "[]")
    except json.JSONDecodeError as exc:
        message = (stderr or stdout or "").strip()
        raise CollectorError(f"OpenCLI 未返回有效 JSON：{message[-500:]}", "opencli_invalid_json") from exc
    if isinstance(payload, dict):
        for key in ("data", "result", "items", "rows"):
            if isinstance(payload.get(key), (dict, list)):
                return payload[key]
    return payload


def _note_id(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"/(?:search_result|explore|note)/([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else ""


def _author_id(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"/user/profile/([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else ""


class OpenCliClient:
    """把 OpenCLI 的小红书浏览器适配器转换为工作台采集契约。"""

    provider_id = "opencli"
    display_name = "OpenCLI"
    capabilities = {
        SEARCH_POSTS_BY_KEYWORD,
        LIST_AUTHOR_POSTS,
        READ_KEYWORD_POST_DETAILS,
        READ_AUTHOR_POST_DETAILS,
        DOWNLOAD_MEDIA,
    }
    command_specs = (
        {
            "id": "opencli.search_posts_by_keyword",
            "capability": SEARCH_POSTS_BY_KEYWORD,
            "method": "search_posts_by_keyword",
            "label": "OpenCLI · 搜索帖子",
            "instruction": "opencli xiaohongshu search {keyword} --limit {limit} -f json",
        },
        {
            "id": "opencli.list_author_posts",
            "capability": LIST_AUTHOR_POSTS,
            "method": "list_author_posts",
            "label": "OpenCLI · 用户主页帖子",
            "instruction": "opencli xiaohongshu user {author_id} --limit {limit} -f json",
        },
        {
            "id": "opencli.read_keyword_post_details",
            "capability": READ_KEYWORD_POST_DETAILS,
            "method": "read_keyword_post_details",
            "label": "OpenCLI · 搜索并逐篇读取详情",
            "instruction": "opencli xiaohongshu search {keyword} --limit {limit} -f json + opencli xiaohongshu note {url} -f json",
        },
        {
            "id": "opencli.read_author_post_details",
            "capability": READ_AUTHOR_POST_DETAILS,
            "method": "read_author_post_details",
            "label": "OpenCLI · 用户帖子并逐篇读取详情",
            "instruction": "opencli xiaohongshu user {author_id} --limit {limit} -f json + opencli xiaohongshu note {url} -f json",
        },
        {
            "id": "opencli.read_post_detail",
            "capability": READ_POST_DETAIL,
            "method": "read_post_detail",
            "label": "OpenCLI · 读取指定帖子详情",
            "instruction": "opencli xiaohongshu note {url} -f json",
        },
        {
            "id": "opencli.download_media",
            "capability": DOWNLOAD_MEDIA,
            "method": "download_media",
            "label": "OpenCLI · 下载帖子媒体",
            "instruction": "opencli xiaohongshu download {url} --output {output_dir} -f json",
        },
    )

    def __init__(self, binary: str = "opencli", data_dir=None, executor: Callable = _execute, timeout: int = 300):
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
        should_cancel = getattr(self.local, "should_cancel", None) or (lambda: False)
        command = [self.binary, "xiaohongshu"] + list(args) + ["-f", "json"]
        try:
            return self.executor(command, env, self.timeout, should_cancel)
        except TypeError as exc:
            if "positional" not in str(exc):
                raise
            return self.executor(command, env, self.timeout)

    def normalize_result(self, raw: Dict[str, Any], mode: str, source_value: str):
        value = dict(raw or {})
        for index, card in enumerate(value.get("cards") or []):
            card["source_type"] = mode
            card["source_value"] = source_value
            card["source_rank"] = index
            card.setdefault("detail_level", "card")
        for note in value.get("notes") or []:
            note["source_type"] = mode
            note["source_value"] = source_value
        value.setdefault("profile", {})
        value.setdefault("warnings", [])
        return value

    def _card(self, raw: Any, fallback_author_id: str = "") -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        url = str(raw.get("url") or raw.get("note_url") or "")
        note_id = str(raw.get("id") or raw.get("note_id") or _note_id(url))
        if not note_id:
            return None
        author_url = str(raw.get("author_url") or "")
        author_id = str(raw.get("author_id") or _author_id(author_url) or fallback_author_id)
        return {
            "note_id": note_id,
            "title": str(raw.get("title") or ""),
            "author_id": author_id,
            "author": str(raw.get("author") or ""),
            "author_url": author_url or (
                f"https://www.xiaohongshu.com/user/profile/{author_id}" if author_id else ""
            ),
            "url": url,
            "type": str(raw.get("type") or ""),
            "likes_count": parse_count(raw.get("likes")),
            "publish_date": str(raw.get("published_at") or ""),
            "detail_level": "card",
        }

    def _cards(self, rows: Any, limit: int, fallback_author_id: str = "") -> List[Dict[str, Any]]:
        rows = rows if isinstance(rows, list) else []
        values = []
        seen = set()
        for raw in rows:
            card = self._card(raw, fallback_author_id)
            if not card or card["note_id"] in seen:
                continue
            seen.add(card["note_id"])
            values.append(card)
            if len(values) >= limit:
                break
        return values

    @staticmethod
    def _warning(keyword: str, filters: Optional[Dict[str, str]]) -> List[str]:
        filters = filters or {}
        warnings = []
        sort = str(filters.get("sort") or "综合")
        publish_time = str(filters.get("publish_time") or "不限")
        if sort not in ("", "综合"):
            warnings.append(f"OpenCLI 暂不支持搜索排序；关键词“{keyword}”未应用“{sort}”排序。")
        if publish_time not in ("", "不限"):
            warnings.append(f"OpenCLI 暂不支持发布时间筛选；关键词“{keyword}”未应用“{publish_time}”。")
        return warnings

    def _read_cards(self, cards: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        notes = []
        for card in cards[:limit]:
            url = str(card.get("url") or "")
            if not url:
                notes.append({**card, "_collector_ok": False, "_collector_error": "OpenCLI 搜索结果缺少帖子 URL"})
                continue
            try:
                rows = self._run(["note", url])
                fields = {
                    str(row.get("field") or ""): row.get("value")
                    for row in (rows if isinstance(rows, list) else [])
                    if isinstance(row, dict)
                }
                notes.append({
                    **card,
                    "title": str(fields.get("title") or card.get("title") or ""),
                    "author": str(fields.get("author") or card.get("author") or ""),
                    "content": str(fields.get("content") or ""),
                    "likes_count": parse_count(fields.get("likes")),
                    "favorites_count": parse_count(fields.get("collects")),
                    "comments_count": parse_count(fields.get("comments")),
                    "tags": str(fields.get("tags") or ""),
                    "detail_level": "detail",
                    "_collector_ok": True,
                    "_collector_error": "",
                })
            except CollectorError as exc:
                if exc.code in ("cancelled", "login_required", "verification_required"):
                    raise
                notes.append({**card, "_collector_ok": False, "_collector_error": str(exc)})
        return notes

    def read_post_detail(self, post: Dict[str, Any]):
        note_id = str(post.get("note_id") or "").strip()
        note_url = str(post.get("note_url") or post.get("url") or "").strip()
        if not note_id or not note_url:
            raise CollectorError("帖子缺少 note_id 或原文地址", "post_source_missing")
        card = {
            "note_id": note_id,
            "title": str(post.get("title") or ""),
            "author_id": str(post.get("external_author_id") or ""),
            "author": str(post.get("author_name") or ""),
            "url": note_url,
            "type": str(post.get("note_type") or post.get("type") or ""),
            "likes_count": post.get("likes_count"),
            "favorites_count": post.get("favorites_count"),
            "comments_count": post.get("comments_count"),
            "publish_date": str(post.get("publish_date") or ""),
            "detail_level": str(post.get("detail_level") or "card"),
        }
        notes = self._read_cards([card], 1)
        if not notes or not notes[0].get("_collector_ok", True):
            raise CollectorError(
                str((notes[0] if notes else {}).get("_collector_error") or "帖子详情读取失败"),
                "post_detail_failed",
            )
        return {"profile": {}, "cards": [card], "notes": notes, "warnings": []}

    def keyword_preview(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None, ocr: bool = False):
        cards = self._cards(self._run(["search", keyword, "--limit", str(limit)]), limit)
        return {"profile": {}, "cards": cards, "notes": [], "warnings": self._warning(keyword, filters)}

    def author_preview(self, author_id: str, limit: int, ocr: bool = False):
        cards = self._cards(
            self._run(["user", author_id, "--limit", str(limit)]),
            limit,
            fallback_author_id=author_id,
        )
        return {
            "profile": {
                "author_id": author_id,
                "profile_url": f"https://www.xiaohongshu.com/user/profile/{author_id}",
            },
            "cards": cards,
            "notes": [],
            "warnings": [],
        }

    def keyword_deep(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None,
                     ocr: bool = True, download_media: bool = True):
        result = self.keyword_preview(keyword, limit, filters, ocr=False)
        result["notes"] = self._read_cards(result["cards"], limit)
        return result

    def author_deep(self, author_id: str, limit: int, ocr: bool = True, download_media: bool = True):
        result = self.author_preview(author_id, limit, ocr=False)
        result["notes"] = self._read_cards(result["cards"], limit)
        return result

    def download_media(self, note_url: str, output_dir: str = ""):
        target = output_dir or str((self.data_dir or Path.cwd()) / "media" / "opencli")
        return self._run(["download", note_url, "--output", target])

    search_posts_by_keyword = keyword_preview
    list_author_posts = author_preview
    read_keyword_post_details = keyword_deep
    read_author_post_details = author_deep
