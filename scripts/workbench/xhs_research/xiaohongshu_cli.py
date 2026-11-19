from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlencode, urlparse

from .collector import (
    CollectorError,
    LIST_AUTHOR_POSTS,
    READ_AUTHOR_PROFILE,
    READ_AUTHOR_POST_DETAILS,
    READ_KEYWORD_POST_DETAILS,
    READ_POST_COMMENTS,
    READ_POST_SUB_COMMENTS,
    READ_POST_DETAIL,
    SEARCH_POSTS_BY_KEYWORD,
    SEARCH_USERS_BY_KEYWORD,
)
from .socai import parse_count


SORT_MAP = {
    "综合": "general",
    "general": "general",
    "最新": "latest",
    "latest": "latest",
    "最热": "popular",
    "最多点赞": "popular",
    "popular": "popular",
}

_USER_SEARCH_PAGE_SCRIPT = r'''
import json
import sys
import time

from xhs_cli.client import XhsClient
from xhs_cli.cookies import get_cookies
from xhs_cli.error_codes import error_code_for_exception

keyword = sys.argv[1]
page = int(sys.argv[2])
page_size = int(sys.argv[3])
cookie_source = sys.argv[4]
try:
    _, cookies = get_cookies(cookie_source)
    with XhsClient(cookies) as client:
        data = client._creator_post("/web_api/sns/v1/search/user_info", {
            "keyword": keyword,
            "search_id": str(int(time.time() * 1000)),
            "page": {"page_size": page_size, "page": page},
        })
    print(json.dumps({"ok": True, "schema_version": "1", "data": data}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({
        "ok": False,
        "schema_version": "1",
        "error": {"code": error_code_for_exception(exc), "message": str(exc)},
    }, ensure_ascii=False))
    raise SystemExit(1)
'''


def _python_for_console_script(binary: str) -> str:
    resolved = Path(binary).expanduser()
    if not resolved.is_file():
        located = shutil.which(binary)
        resolved = Path(located) if located else resolved
    if resolved.is_file():
        try:
            with resolved.open("r", encoding="utf-8") as script:
                first_line = script.readline().strip()
        except (OSError, UnicodeDecodeError):
            first_line = ""
        if first_line.startswith("#!"):
            parts = shlex.split(first_line[2:].strip())
            if parts and Path(parts[0]).name == "env" and len(parts) > 1:
                return shutil.which(parts[1]) or parts[1]
            if parts:
                return parts[0]
        for name in ("python", "python3", "python.exe"):
            candidate = resolved.parent / name
            if candidate.is_file():
                return str(candidate)
    raise CollectorError(
        "无法定位 xiaohongshu-cli 的 Python 运行时，不能继续翻页搜索用户",
        "xiaohongshu_cli_runtime",
    )


def classify_xhs_error(payload: Any, fallback: str = "xiaohongshu_cli_failed") -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip().lower()
            if code in ("not_authenticated", "session_expired"):
                return "login_required"
            if code in ("verification_required", "captcha_required"):
                return "verification_required"
            if code:
                return code
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload or "")
    normalized = text.lower()
    if any(marker in normalized for marker in (
        "not_authenticated", "session expired", "need login", "未登录",
        "guest or incomplete profile", "session appears invalid",
    )):
        return "login_required"
    if any(marker in normalized for marker in ("verification_required", "captcha", "验证码", "安全验证")):
        return "verification_required"
    return fallback


def _error_message(payload: Any, stderr: str = "") -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "xiaohongshu-cli 返回失败状态")
        if error:
            return str(error)
    return str(stderr or "").strip() or "xiaohongshu-cli 返回失败状态"


def _execute(args, env, timeout, should_cancel=lambda: False):
    try:
        process = subprocess.Popen(args, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise CollectorError(str(exc), "xiaohongshu_cli_failed") from exc
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
                    f"xiaohongshu-cli 调用超时（{timeout} 秒）：{(stderr or stdout)[-500:]}",
                    "xiaohongshu_cli_timeout",
                )
    try:
        payload = json.loads((stdout or "").strip())
    except json.JSONDecodeError as exc:
        message = (stderr or stdout or "").strip()
        raise CollectorError(
            f"xiaohongshu-cli 未返回有效 JSON：{message[-500:]}",
            classify_xhs_error(message),
        ) from exc
    if process.returncode or not isinstance(payload, dict) or payload.get("ok") is False:
        raise CollectorError(
            _error_message(payload, stderr),
            classify_xhs_error(payload if isinstance(payload, dict) else stderr),
        )
    if payload.get("ok") is not True or str(payload.get("schema_version") or "") != "1":
        raise CollectorError("xiaohongshu-cli 返回了不受支持的结构化输出版本", "xiaohongshu_cli_schema")
    return payload.get("data")


def _image_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("url_default", "url_pre", "url", "master_url", "original"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    info_list = value.get("info_list")
    if isinstance(info_list, list):
        for item in info_list:
            candidate = _image_url(item)
            if candidate:
                return candidate
    return ""


def _note_url(note_id: str, token: str = "", source: str = "pc_feed") -> str:
    if not note_id:
        return ""
    query = urlencode({"xsec_token": token, "xsec_source": source}) if token else ""
    return f"https://www.xiaohongshu.com/explore/{note_id}" + (f"?{query}" if query else "")


def _date_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if number > 10_000_000_000:
        number /= 1000
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return str(value)


class XiaohongshuCliClient:
    """把 xiaohongshu-cli 的命令与 envelope 适配为工作台采集契约。"""

    provider_id = "xiaohongshu-cli"
    display_name = "xiaohongshu-cli"
    capabilities = {
        SEARCH_POSTS_BY_KEYWORD,
        SEARCH_USERS_BY_KEYWORD,
        READ_AUTHOR_PROFILE,
        LIST_AUTHOR_POSTS,
        READ_KEYWORD_POST_DETAILS,
        READ_AUTHOR_POST_DETAILS,
        READ_POST_COMMENTS,
        READ_POST_SUB_COMMENTS,
    }
    command_specs = (
        {
            "id": "xiaohongshu-cli.search_posts_by_keyword",
            "capability": SEARCH_POSTS_BY_KEYWORD,
            "method": "search_posts_by_keyword",
            "label": "xiaohongshu-cli · 搜索帖子",
            "instruction": "xhs search-note {keyword} --sort general --json",
        },
        {
            "id": "xiaohongshu-cli.search_users_by_keyword",
            "capability": SEARCH_USERS_BY_KEYWORD,
            "method": "search_users_by_keyword",
            "label": "xiaohongshu-cli · 搜索用户",
            "instruction": "xhs search-user {keyword} --json + 分页用户搜索",
        },
        {
            "id": "xiaohongshu-cli.read_author_profile",
            "capability": READ_AUTHOR_PROFILE,
            "method": "read_author_profile",
            "label": "xiaohongshu-cli · 作者基础信息",
            "instruction": "xhs user {author_id} --json",
        },
        {
            "id": "xiaohongshu-cli.list_author_posts",
            "capability": LIST_AUTHOR_POSTS,
            "method": "list_author_posts",
            "label": "xiaohongshu-cli · 用户主页帖子",
            "instruction": "xhs user {author_id} --json + xhs homefeed --json",
        },
        {
            "id": "xiaohongshu-cli.read_keyword_post_details",
            "capability": READ_KEYWORD_POST_DETAILS,
            "method": "read_keyword_post_details",
            "label": "xiaohongshu-cli · 搜索并逐篇读取详情",
            "instruction": "xhs search-note {keyword} --json + xhs read {note_id} --json",
        },
        {
            "id": "xiaohongshu-cli.read_author_post_details",
            "capability": READ_AUTHOR_POST_DETAILS,
            "method": "read_author_post_details",
            "label": "xiaohongshu-cli · 用户帖子并逐篇读取详情",
            "instruction": "xhs user {author_id} --json + xhs homefeed --json + xhs read {note_id} --json",
        },
        {
            "id": "xiaohongshu-cli.read_post_detail",
            "capability": READ_POST_DETAIL,
            "method": "read_post_detail",
            "label": "xiaohongshu-cli · 读取指定帖子详情",
            "instruction": "xhs read {note_id} --json",
        },
        {
            "id": "xiaohongshu-cli.read_post_comments",
            "capability": READ_POST_COMMENTS,
            "method": "read_post_comments",
            "label": "xiaohongshu-cli · 读取指定帖子评论",
            "instruction": "xhs comments {note_id_or_url} [--cursor {cursor}] --json",
        },
        {
            "id": "xiaohongshu-cli.read_post_sub_comments",
            "capability": READ_POST_SUB_COMMENTS,
            "method": "read_post_sub_comments",
            "label": "xiaohongshu-cli · 读取指定评论楼中楼",
            "instruction": "xhs sub-comments {note_id} {comment_id} [--cursor {cursor}] --json",
        },
    )

    def __init__(
        self,
        binary: str = "xhs",
        data_dir=None,
        executor: Callable = _execute,
        timeout: int = 300,
        cookie_source: Union[str, Callable[[], str]] = "auto",
    ):
        self.binary = binary
        self.data_dir = data_dir
        self.executor = executor
        self.timeout = timeout
        self.cookie_source = cookie_source
        self.local = threading.local()

    @contextmanager
    def cancellation_scope(self, should_cancel):
        previous = getattr(self.local, "should_cancel", None)
        self.local.should_cancel = should_cancel
        self.local.login_verification = None
        try:
            self._ensure_authenticated()
            yield
        finally:
            self.local.should_cancel = previous

    def consume_login_verification(self) -> Optional[Dict[str, str]]:
        value = getattr(self.local, "login_verification", None)
        self.local.login_verification = None
        return dict(value) if isinstance(value, dict) else None

    def _cookie_source(self) -> str:
        value = self.cookie_source() if callable(self.cookie_source) else self.cookie_source
        return str(value or "auto").strip().lower() or "auto"

    def _execute_command(self, args, cookie_source: str):
        env = os.environ.copy()
        env["OUTPUT"] = "json"
        should_cancel = getattr(self.local, "should_cancel", None) or (lambda: False)
        command = [self.binary, "--cookie-source", cookie_source] + list(args) + ["--json"]
        try:
            return self.executor(command, env, self.timeout, should_cancel)
        except TypeError as exc:
            if "positional" not in str(exc):
                raise
            return self.executor(command, env, self.timeout)

    def _ensure_authenticated(self):
        cookie_source = self._cookie_source()
        result = self._execute_command(["login"], cookie_source)
        user = result.get("user") if isinstance(result, dict) else None
        nickname = str((user or {}).get("nickname") or "").strip()
        if (
            not isinstance(result, dict)
            or result.get("authenticated") is not True
            or not isinstance(user, dict)
            or bool(user.get("guest"))
            or not nickname
            or nickname == "Unknown"
        ):
            raise CollectorError(
                "小红书登录态无效（访客或信息不完整）；请在所选浏览器登录后继续任务",
                "login_required",
            )
        self.local.login_verification = {
            "provider": self.provider_id,
            "cookie_source": cookie_source,
        }

    def _run(self, args):
        return self._execute_command(args, self._cookie_source())

    def _run_user_search_page(self, keyword: str, page: int, page_size: int = 20):
        if page == 1:
            return self._run(["search-user", keyword])
        env = os.environ.copy()
        env["OUTPUT"] = "json"
        should_cancel = getattr(self.local, "should_cancel", None) or (lambda: False)
        command = [
            _python_for_console_script(self.binary),
            "-c",
            _USER_SEARCH_PAGE_SCRIPT,
            keyword,
            str(page),
            str(page_size),
            self._cookie_source(),
        ]
        try:
            return self.executor(command, env, self.timeout, should_cancel)
        except TypeError as exc:
            if "positional" not in str(exc):
                raise
            return self.executor(command, env, self.timeout)

    def normalize_result(self, raw: Dict[str, Any], mode: str, source_value: str):
        value = dict(raw or {})
        cards = []
        for index, card in enumerate(value.get("cards") or []):
            item = dict(card)
            item["source_type"] = mode
            item["source_value"] = source_value
            item["source_rank"] = index
            item.setdefault("detail_level", "card")
            cards.append(item)
        notes = []
        for note in value.get("notes") or []:
            item = dict(note)
            item["source_type"] = mode
            item["source_value"] = source_value
            notes.append(item)
        value["cards"] = cards
        value["notes"] = notes
        value.setdefault("profile", {})
        value.setdefault("warnings", [])
        return value

    def _profile(self, author_id: str, raw: Any) -> Dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        basic = raw.get("basic_info") if isinstance(raw.get("basic_info"), dict) else raw
        interactions = raw.get("interactions") if isinstance(raw.get("interactions"), list) else []
        stats = {str(item.get("type") or item.get("name") or ""): item.get("count") for item in interactions if isinstance(item, dict)}
        return {
            "author_id": str(basic.get("user_id") or raw.get("user_id") or author_id),
            "xhs_id": str(basic.get("red_id") or raw.get("red_id") or ""),
            "display_name": str(basic.get("nickname") or basic.get("nick_name") or raw.get("nickname") or ""),
            "profile_url": f"https://www.xiaohongshu.com/user/profile/{author_id}",
            "bio": str(basic.get("desc") or raw.get("desc") or ""),
            "ip_location": str(basic.get("ip_location") or raw.get("ip_location") or ""),
            "followers_count": parse_count(stats.get("fans") or stats.get("粉丝") or basic.get("fans")),
            "following_count": parse_count(stats.get("follows") or stats.get("关注") or basic.get("follows")),
            "likes_collections_count": parse_count(stats.get("interaction") or stats.get("获赞与收藏") or basic.get("interaction")),
            "total_post_count": parse_count(
                stats.get("notes")
                or stats.get("posts")
                or stats.get("笔记")
                or stats.get("作品")
                or basic.get("total_post_count")
                or basic.get("notes_count")
                or basic.get("note_count")
                or basic.get("post_count")
                or raw.get("total_post_count")
                or raw.get("notes_count")
                or raw.get("note_count")
                or raw.get("post_count")
            ),
            "avatar_url": _image_url(basic.get("images") or basic.get("imageb") or basic.get("avatar")),
        }

    def _card(self, raw: Any, fallback_author_id: str = "", xsec_source: str = "pc_feed") -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        model_type = str(raw.get("model_type") or "").strip()
        note_card = raw.get("note_card")
        if model_type and model_type != "note":
            return None
        if model_type == "note" and not isinstance(note_card, dict):
            return None
        note = note_card if isinstance(note_card, dict) else raw
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        interact = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else {}
        note_id = str(raw.get("id") or note.get("note_id") or note.get("id") or "")
        if not note_id or any(marker in note_id for marker in ("#", "?", "/", "\\")):
            return None
        token = str(raw.get("xsec_token") or note.get("xsec_token") or "")
        images = note.get("image_list") if isinstance(note.get("image_list"), list) else []
        cover_url = _image_url(note.get("cover")) or (_image_url(images[0]) if images else "")
        author_id = str(user.get("user_id") or user.get("id") or note.get("user_id") or fallback_author_id)
        return {
            "note_id": note_id,
            "title": str(note.get("title") or note.get("display_title") or ""),
            "author_id": author_id,
            "author": str(user.get("nickname") or user.get("nick_name") or note.get("nickname") or ""),
            "author_url": f"https://www.xiaohongshu.com/user/profile/{author_id}" if author_id else "",
            "type": str(note.get("type") or note.get("note_type") or ""),
            "url": _note_url(note_id, token, xsec_source),
            "cover_url": cover_url,
            "likes_count": parse_count(interact.get("liked_count") or note.get("liked_count")),
            "favorites_count": parse_count(interact.get("collected_count") or note.get("collected_count")),
            "comments_count": parse_count(interact.get("comment_count") or note.get("comment_count")),
            "publish_date": _date_text(note.get("time") or note.get("publish_time") or note.get("last_update_time")),
            "_xsec_token": token,
            "_xsec_source": xsec_source,
            "detail_level": "card",
        }

    def _detail(self, card: Dict[str, Any], raw: Any) -> Dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        items = raw.get("items") if isinstance(raw.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        note = first.get("note_card") if isinstance(first.get("note_card"), dict) else first
        if not isinstance(note, dict) or not note:
            raise CollectorError("xiaohongshu-cli 未返回帖子详情", "xiaohongshu_cli_empty_detail")
        merged = self._card(
            {**first, "id": first.get("id") or card.get("note_id"), "xsec_token": card.get("_xsec_token", "")},
            fallback_author_id=str(card.get("author_id") or ""),
            xsec_source=str(card.get("_xsec_source") or "pc_feed"),
        ) or dict(card)
        images = []
        for index, image in enumerate(note.get("image_list") or []):
            url = _image_url(image)
            if url:
                images.append({"index": index, "url": url})
        merged.update({
            "content": str(note.get("desc") or note.get("content") or ""),
            "images": images,
            "cover_url": merged.get("cover_url") or (images[0]["url"] if images else ""),
            "detail_level": "media" if images else "detail",
            "_collector_ok": True,
            "_collector_error": "",
        })
        return merged

    def _search_cards(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None):
        filters = filters or {}
        sort = SORT_MAP.get(str(filters.get("sort") or "综合"), "general")
        cards = []
        seen = set()
        max_pages = max(1, math.ceil(max(1, limit) / 20) + 1)
        for page in range(1, max_pages + 1):
            data = self._run(["search", keyword, "--sort", sort, "--page", str(page)])
            data = data if isinstance(data, dict) else {}
            for raw in data.get("items") or []:
                card = self._card(raw, xsec_source="pc_search")
                if not card or card["note_id"] in seen:
                    continue
                seen.add(card["note_id"])
                cards.append(card)
                if len(cards) >= limit:
                    break
            if len(cards) >= limit or not data.get("has_more"):
                break
        warnings = []
        publish_time = str(filters.get("publish_time") or "不限")
        if publish_time not in ("", "不限"):
            warnings.append(
                f"xiaohongshu-cli 暂不支持发布时间筛选；关键词“{keyword}”已保留排序条件，但未应用“{publish_time}”。"
            )
        return cards[:limit], warnings

    def _author_cards(self, author_id: str, limit: int):
        cards = []
        seen = set()
        cursor = ""
        max_pages = max(1, math.ceil(max(1, limit) / 20) + 1)
        for _ in range(max_pages):
            args = ["user-posts", author_id]
            if cursor:
                args.extend(["--cursor", cursor])
            data = self._run(args)
            data = data if isinstance(data, dict) else {}
            notes = data.get("notes") or data.get("note_list") or []
            added = 0
            for raw in notes:
                card = self._card(raw, fallback_author_id=author_id)
                if not card or card["note_id"] in seen:
                    continue
                seen.add(card["note_id"])
                cards.append(card)
                added += 1
                if len(cards) >= limit:
                    break
            next_cursor = str(data.get("cursor") or "")
            if len(cards) >= limit or not data.get("has_more") or not added or next_cursor == cursor:
                break
            cursor = next_cursor
        return cards[:limit]

    def _read_cards(self, cards: List[Dict[str, Any]], limit: int):
        notes = []
        for card in cards[:limit]:
            args = ["read", str(card["note_id"])]
            if card.get("_xsec_token"):
                args.extend(["--xsec-token", str(card["_xsec_token"])])
            try:
                notes.append(self._detail(card, self._run(args)))
            except CollectorError as exc:
                if exc.code in ("cancelled", "login_required", "verification_required"):
                    raise
                notes.append({
                    **card,
                    "_collector_ok": False,
                    "_collector_error": str(exc),
                })
        return notes

    def read_post_detail(self, post: Dict[str, Any]):
        note_id = str(post.get("note_id") or "").strip()
        if not note_id:
            raise CollectorError("帖子缺少 note_id", "post_source_missing")
        note_url = str(post.get("note_url") or post.get("url") or "")
        query = parse_qs(urlparse(note_url).query)
        token = str((query.get("xsec_token") or [""])[0])
        card = {
            "note_id": note_id,
            "title": str(post.get("title") or ""),
            "author_id": str(post.get("external_author_id") or ""),
            "author": str(post.get("author_name") or ""),
            "url": note_url or _note_url(note_id),
            "type": str(post.get("note_type") or post.get("type") or ""),
            "cover_url": str(post.get("cover_url") or ""),
            "likes_count": post.get("likes_count"),
            "favorites_count": post.get("favorites_count"),
            "comments_count": post.get("comments_count"),
            "publish_date": str(post.get("publish_date") or ""),
            "detail_level": str(post.get("detail_level") or "card"),
            "_xsec_token": token,
            "_xsec_source": str((query.get("xsec_source") or ["pc_feed"])[0]),
        }
        notes = self._read_cards([card], 1)
        if not notes or not notes[0].get("_collector_ok", True):
            raise CollectorError(
                str((notes[0] if notes else {}).get("_collector_error") or "帖子详情读取失败"),
                "post_detail_failed",
            )
        return {"profile": {}, "cards": [card], "notes": notes, "warnings": []}

    def read_post_comments(self, post: Dict[str, Any], cursor: str = ""):
        note_id = str(post.get("note_id") or "").strip()
        if not note_id:
            raise CollectorError("帖子缺少 note_id", "post_source_missing")
        target = str(post.get("note_url") or post.get("url") or "").strip() or note_id
        args = ["comments", target]
        if cursor:
            args.extend(["--cursor", str(cursor)])
        value = self._run(args)
        if not isinstance(value, dict):
            raise CollectorError("评论接口返回格式无效", "invalid_response")
        return value

    def read_post_sub_comments(self, note_id: str, comment_id: str, cursor: str = ""):
        note_id = str(note_id or "").strip()
        comment_id = str(comment_id or "").strip()
        if not note_id or not comment_id:
            raise CollectorError("楼中楼抓取缺少帖子或评论 ID", "post_source_missing")
        args = ["sub-comments", note_id, comment_id]
        if cursor:
            args.extend(["--cursor", str(cursor)])
        value = self._run(args)
        if not isinstance(value, dict):
            raise CollectorError("楼中楼接口返回格式无效", "invalid_response")
        return value

    def author_preview(self, author_id: str, limit: int, ocr: bool = False):
        profile = self._profile(author_id, self._run(["user", author_id]))
        return {"profile": profile, "cards": self._author_cards(author_id, limit), "notes": [], "warnings": []}

    def read_author_profile(self, author_id: str):
        profile = self._profile(author_id, self._run(["user", author_id]))
        return {"profile": profile, "cards": [], "notes": [], "warnings": []}

    def keyword_preview(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None, ocr: bool = False):
        cards, warnings = self._search_cards(keyword, limit, filters)
        return {"profile": {}, "cards": cards, "notes": [], "warnings": warnings}

    def search_users_by_keyword(self, keyword: str, limit: int):
        profiles = []
        seen = set()
        page_size = 20
        max_pages = max(1, math.ceil(max(1, limit) / page_size) + 2)
        for page in range(1, max_pages + 1):
            data = self._run_user_search_page(keyword, page, page_size)
            data = data if isinstance(data, dict) else {}
            entries = data.get("user_info_dtos") or []
            added = 0
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                base = entry.get("user_base_dto") if isinstance(entry.get("user_base_dto"), dict) else {}
                author_id = str(base.get("user_id") or "")
                if not author_id or author_id in seen:
                    continue
                seen.add(author_id)
                profiles.append({
                    "author_id": author_id,
                    "xhs_id": str(base.get("red_id") or ""),
                    "display_name": str(base.get("user_nickname") or ""),
                    "profile_url": f"https://www.xiaohongshu.com/user/profile/{author_id}",
                    "bio": str(base.get("desc") or ""),
                    "followers_count": parse_count(entry.get("fans_total")),
                    "avatar_url": _image_url(base.get("image_size_large") or base.get("image")),
                    "discovery_keyword": keyword,
                })
                added += 1
                if len(profiles) >= limit:
                    break
            if len(profiles) >= limit or len(entries) < page_size or not added:
                break
        return {"profiles": profiles, "warnings": []}

    def author_deep(self, author_id: str, limit: int, ocr: bool = True, download_media: bool = True):
        result = self.author_preview(author_id, limit, ocr=False)
        result["notes"] = self._read_cards(result["cards"], limit)
        return result

    def keyword_deep(self, keyword: str, limit: int, filters: Optional[Dict[str, str]] = None,
                     ocr: bool = True, download_media: bool = True):
        result = self.keyword_preview(keyword, limit, filters, ocr=False)
        result["notes"] = self._read_cards(result["cards"], limit)
        return result

    # 原子能力入口；保留旧方法名以兼容历史调用方。
    search_posts_by_keyword = keyword_preview
    list_author_posts = author_preview
    read_keyword_post_details = keyword_deep
    read_author_post_details = author_deep
