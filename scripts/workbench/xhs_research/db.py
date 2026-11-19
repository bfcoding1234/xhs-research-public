from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from .attention import FOLLOWER_SMOOTHING_MIN, INTERACTION_SMOOTHING_MIN
from .vision_state import IMAGE_SCOPES, media_matches_scope, resolve_current_vision


_INVALID_SEARCH_CARD_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}#[0-9]{13}$"
)

_POST_OCR_COMPLETE_SQL = """(
    EXISTS(
        SELECT 1 FROM media_assets ocr_media
        WHERE ocr_media.post_id=p.id AND ocr_media.local_path!=''
    )
    AND NOT EXISTS(
        SELECT 1 FROM media_assets ocr_media
        WHERE ocr_media.post_id=p.id AND ocr_media.local_path!=''
          AND ocr_media.ocr_completed_at IS NULL
    )
)"""

_POST_OCR_PENDING_SQL = """(
    EXISTS(
        SELECT 1 FROM media_assets ocr_media
        WHERE ocr_media.post_id=p.id AND ocr_media.local_path!=''
    )
    AND EXISTS(
        SELECT 1 FROM media_assets ocr_media
        WHERE ocr_media.post_id=p.id AND ocr_media.local_path!=''
          AND ocr_media.ocr_completed_at IS NULL
    )
)"""

_POST_OCR_STATUS_SQL = f"""CASE
    WHEN {_POST_OCR_COMPLETE_SQL} THEN 'completed'
    WHEN {_POST_OCR_PENDING_SQL} THEN 'pending'
    ELSE 'other'
END"""

_POST_MEDIA_STORAGE_STATUS_SQL = """CASE
    WHEN EXISTS(
        SELECT 1 FROM media_assets storage_media
        WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
          AND storage_media.original_url!='' AND storage_media.local_path=''
    ) THEN 'remote'
    WHEN EXISTS(
        SELECT 1 FROM media_assets storage_media
        WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
          AND storage_media.local_path!=''
    ) THEN 'local'
    ELSE 'none'
END"""

_POST_LIST_MEDIA_LOCAL_PATH_SQL = """CASE
    WHEN EXISTS(
        SELECT 1 FROM media_assets list_detail_media
        WHERE list_detail_media.post_id=p.id AND list_detail_media.media_type='image'
          AND (list_detail_media.local_path!='' OR list_detail_media.original_url!='')
    ) THEN COALESCE((
        SELECT list_detail_media.local_path FROM media_assets list_detail_media
        WHERE list_detail_media.post_id=p.id AND list_detail_media.media_type='image'
          AND (list_detail_media.local_path!='' OR list_detail_media.original_url!='')
        ORDER BY list_detail_media.media_index,list_detail_media.id LIMIT 1
    ), '')
    ELSE COALESCE(NULLIF(p.cover_local_path, ''), (
        SELECT list_cover_media.local_path FROM media_assets list_cover_media
        WHERE list_cover_media.post_id=p.id AND list_cover_media.media_type='cover'
          AND list_cover_media.local_path!=''
        ORDER BY list_cover_media.media_index,list_cover_media.id LIMIT 1
    ), '')
END"""

_POST_LIST_MEDIA_ORIGINAL_URL_SQL = """CASE
    WHEN EXISTS(
        SELECT 1 FROM media_assets list_detail_media
        WHERE list_detail_media.post_id=p.id AND list_detail_media.media_type='image'
          AND (list_detail_media.local_path!='' OR list_detail_media.original_url!='')
    ) THEN COALESCE((
        SELECT list_detail_media.original_url FROM media_assets list_detail_media
        WHERE list_detail_media.post_id=p.id AND list_detail_media.media_type='image'
          AND (list_detail_media.local_path!='' OR list_detail_media.original_url!='')
        ORDER BY list_detail_media.media_index,list_detail_media.id LIMIT 1
    ), '')
    ELSE COALESCE(NULLIF(p.cover_url, ''), (
        SELECT list_cover_media.original_url FROM media_assets list_cover_media
        WHERE list_cover_media.post_id=p.id AND list_cover_media.media_type='cover'
          AND list_cover_media.original_url!=''
        ORDER BY list_cover_media.media_index,list_cover_media.id LIMIT 1
    ), '')
END"""


def _post_ocr_filter_sql(value: str) -> str:
    if value in ("completed", "yes"):
        return _POST_OCR_COMPLETE_SQL
    if value == "pending":
        return _POST_OCR_PENDING_SQL
    if value == "other":
        return f"(NOT {_POST_OCR_COMPLETE_SQL} AND NOT {_POST_OCR_PENDING_SQL})"
    if value == "no":
        return f"NOT {_POST_OCR_COMPLETE_SQL}"
    return ""


def _post_media_storage_filter_sql(value: str) -> str:
    if value == "remote":
        return """EXISTS(
            SELECT 1 FROM media_assets storage_media
            WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
              AND storage_media.original_url!='' AND storage_media.local_path=''
        )"""
    if value == "local":
        return """EXISTS(
            SELECT 1 FROM media_assets storage_media
            WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
              AND storage_media.local_path!=''
        ) AND NOT EXISTS(
            SELECT 1 FROM media_assets storage_media
            WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
              AND storage_media.original_url!='' AND storage_media.local_path=''
        )"""
    if value == "none":
        return """NOT EXISTS(
            SELECT 1 FROM media_assets storage_media
            WHERE storage_media.post_id=p.id AND storage_media.media_type='image'
        )"""
    return ""


def _current_vision_by_scope(media_rows, vision_rows, data_root, cache_key_fn):
    result = {}
    for image_scope in (*IMAGE_SCOPES, "all"):
        scoped_cache_key = None
        if cache_key_fn is not None:
            def scoped_cache_key(paths, scope=image_scope):
                try:
                    return cache_key_fn(paths, scope)
                except TypeError:
                    return cache_key_fn(paths) if scope == "all" else ""
        result[image_scope] = resolve_current_vision(
            media_rows, vision_rows, data_root, scoped_cache_key, image_scope,
        )
    return result


class ActiveTaskConflict(ValueError):
    """Raised when an atomic active-task uniqueness reservation is occupied."""


class ProjectDeleteConflict(ValueError):
    """Raised when an atomic project deletion guard rejects the operation."""


class ProjectReferenceConflict(ValueError):
    """Raised when removing project references requires explicit confirmation."""

    def __init__(self, message: str, payload: Dict[str, Any]):
        super().__init__(message)
        self.payload = payload


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return value or f"project-{uuid.uuid4().hex[:8]}"


def _normalize_project_keyword(value: Any) -> tuple[str, str]:
    keyword = re.sub(r"\s+", " ", str(value or "").strip())
    if not keyword:
        raise ValueError("keyword must not be empty")
    if len(keyword) > 120:
        raise ValueError("keyword must not exceed 120 characters")
    return keyword, keyword.casefold()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_profile_url(value: str, author_id: str) -> str:
    value = str(value or "")
    match = re.search(r"https?://(?:www\.)?xiaohongshu\.com/user/profile/([^/?#]+)", value)
    if match:
        return f"https://www.xiaohongshu.com/user/profile/{match.group(1)}"
    return value or (f"https://www.xiaohongshu.com/user/profile/{author_id}" if author_id else "")


def _vision_cache_key_v2(hashes: Sequence[str], model: str, prompt_version: str) -> str:
    digest = hashlib.sha256(b"xhs-vision-cache-v2\0")
    for value in hashes:
        digest.update(str(value).encode("ascii"))
        digest.update(b"\0")
    digest.update(prompt_version.encode("utf-8"))
    digest.update(b"\0")
    digest.update(model.encode("utf-8"))
    return digest.hexdigest()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def rebase_local_media_paths(self, data_dir: Path) -> int:
        """Repair stale absolute media paths when the same file exists in this data root."""
        root = Path(data_dir).expanduser().resolve()
        repaired = 0
        fields = (
            ("posts", "cover_local_path"),
            ("authors", "avatar_local_path"),
            ("media_assets", "local_path"),
        )
        with self.connect() as conn:
            for table, column in fields:
                rows = conn.execute(
                    f"SELECT id,{column} AS local_path FROM {table} WHERE {column}!=''"
                ).fetchall()
                for row in rows:
                    stored = Path(str(row["local_path"])).expanduser()
                    if not stored.is_absolute():
                        continue
                    resolved = stored.resolve()
                    try:
                        resolved.relative_to(root)
                        continue
                    except ValueError:
                        pass
                    parts = resolved.parts
                    candidate = None
                    for index in reversed([
                        offset for offset, part in enumerate(parts) if part == "media"
                    ]):
                        rebased = (root / Path(*parts[index:])).resolve()
                        try:
                            rebased.relative_to(root)
                        except ValueError:
                            continue
                        if rebased.is_file():
                            candidate = rebased
                            break
                    if candidate is None:
                        continue
                    changed = conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=? AND {column}=?",
                        (str(candidate), int(row["id"]), str(row["local_path"])),
                    ).rowcount
                    repaired += int(changed or 0)
        return repaired

    def remove_invalid_search_cards(self) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,note_id FROM posts
                   WHERE author_id IS NULL
                     AND COALESCE(title,'')=''
                     AND COALESCE(content,'')=''
                     AND COALESCE(note_type,'')=''
                     AND COALESCE(cover_url,'')=''
                     AND COALESCE(cover_local_path,'')=''
                     AND likes_count IS NULL
                     AND favorites_count IS NULL
                     AND comments_count IS NULL"""
            ).fetchall()
            invalid_ids = [
                int(row["id"])
                for row in rows
                if _INVALID_SEARCH_CARD_ID_RE.fullmatch(str(row["note_id"] or ""))
            ]
            if not invalid_ids:
                return 0
            placeholders = ",".join("?" for _ in invalid_ids)
            deleted = conn.execute(
                f"DELETE FROM posts WHERE id IN ({placeholders})",
                invalid_ids,
            )
            return int(deleted.rowcount or 0)

    def remove_redundant_post_detail_author_relations(self) -> int:
        """Remove provenance rows that detail refreshes added beside an existing source."""
        post_detail_task_ids = []
        with self.connect() as conn:
            for row in conn.execute("SELECT id,input_json FROM tasks").fetchall():
                try:
                    payload = json.loads(row["input_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict) and payload.get("operation") == "post_detail_update":
                    post_detail_task_ids.append(str(row["id"]))
            if not post_detail_task_ids:
                return 0
            placeholders = ",".join("?" for _ in post_detail_task_ids)
            deleted = conn.execute(
                f"""DELETE FROM project_authors
                    WHERE relation_type='post_author'
                      AND first_task_id IN ({placeholders})
                      AND EXISTS (
                          SELECT 1 FROM project_authors AS existing
                          WHERE existing.project_id=project_authors.project_id
                            AND existing.author_id=project_authors.author_id
                            AND existing.relation_type!='post_author'
                      )""",
                post_detail_task_ids,
            )
            return int(deleted.rowcount or 0)

    def initialize(self) -> int:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(schema)
            # Drop before legacy backfills so a previously installed index cannot
            # reject rows that still need task_type reconciliation.
            conn.execute("DROP INDEX IF EXISTS idx_tasks_one_active_enrichment")
            conn.execute("DROP INDEX IF EXISTS idx_tasks_one_active_author_report")
            conn.execute("DROP INDEX IF EXISTS idx_tasks_one_active_author_enrichment")
            conn.execute("DROP INDEX IF EXISTS idx_tasks_one_active_post_comments")
            post_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()
            }
            if "last_comments_fetched_at" not in post_columns:
                conn.execute("ALTER TABLE posts ADD COLUMN last_comments_fetched_at TEXT")
            comment_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(post_comments)").fetchall()
            }
            if "is_reply_preview" not in comment_columns:
                conn.execute(
                    "ALTER TABLE post_comments ADD COLUMN is_reply_preview INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "UPDATE post_comments SET is_reply_preview=1 WHERE comment_type='reply_preview'"
                )
            task_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
            ).fetchone()["sql"]
            task_info = conn.execute("PRAGMA table_info(tasks)").fetchall()
            old_task_columns = {row["name"] for row in task_info}
            project_column = next(row for row in task_info if row["name"] == "project_id")
            project_fk = next(
                (row for row in conn.execute("PRAGMA foreign_key_list(tasks)").fetchall()
                 if row["from"] == "project_id"),
                None,
            )
            needs_task_rebuild = (
                "'mixed'" not in task_sql
                or "'keyword_suggestions'" not in task_sql
                or "'comments'" not in task_sql
                or "'post'" not in task_sql
                or "post_id" not in old_task_columns
                or bool(project_column["notnull"])
                or project_fk is None
                or str(project_fk["on_delete"]).upper() != "SET NULL"
            )
            if needs_task_rebuild:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("""CREATE TABLE tasks_relational (
                    id TEXT PRIMARY KEY,
                    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL,
                    post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL,
                    task_type TEXT NOT NULL DEFAULT 'research' CHECK (task_type IN ('research','vision','ai_report','keyword_suggestions','comments')),
                    mode TEXT NOT NULL CHECK (mode IN ('author','keyword','mixed','post')),
                    created_from TEXT NOT NULL CHECK (created_from IN ('codex','web','test')),
                    input_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    current_phase TEXT NOT NULL DEFAULT 'queued',
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )""")
                task_type_expr = "task_type" if "task_type" in old_task_columns else "'research'"
                author_id_expr = "author_id" if "author_id" in old_task_columns else "NULL"
                post_id_expr = "post_id" if "post_id" in old_task_columns else "NULL"
                conn.execute(f"""INSERT INTO tasks_relational(
                    id,project_id,author_id,post_id,task_type,mode,created_from,input_json,status,current_phase,
                    progress_current,progress_total,warning_count,error_message,result_json,
                    created_at,started_at,finished_at
                ) SELECT id,project_id,{author_id_expr},{post_id_expr},{task_type_expr},mode,created_from,input_json,status,current_phase,
                    progress_current,progress_total,warning_count,error_message,result_json,
                    created_at,started_at,finished_at FROM tasks""")
                conn.execute("DROP TABLE tasks")
                conn.execute("ALTER TABLE tasks_relational RENAME TO tasks")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, created_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_author ON tasks(author_id, created_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_post ON tasks(post_id, created_at DESC)")
                conn.execute("PRAGMA foreign_keys=ON")
            task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "author_id" not in task_columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL")
            if "post_id" not in task_columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_author ON tasks(author_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_post ON tasks(post_id, created_at DESC)")
            task_type_was_missing = "task_type" not in task_columns
            if task_type_was_missing:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'research' "
                    "CHECK (task_type IN ('research','vision','ai_report','keyword_suggestions','comments'))"
                )
            for row in conn.execute("SELECT id,input_json,task_type FROM tasks").fetchall():
                try:
                    operation = json.loads(row["input_json"] or "{}").get("operation")
                except (AttributeError, TypeError, json.JSONDecodeError):
                    operation = None
                if operation in ("vision", "ai_report", "keyword_suggestions") and row["task_type"] != operation:
                    conn.execute("UPDATE tasks SET task_type=? WHERE id=?", (operation, row["id"]))
            duplicate_groups = conn.execute(
                """SELECT project_id,task_type FROM tasks
                   WHERE task_type IN ('vision','ai_report','keyword_suggestions')
                     AND status IN ('queued','running','waiting_login')
                   GROUP BY project_id,task_type HAVING COUNT(*)>1"""
            ).fetchall()
            for group in duplicate_groups:
                rows = conn.execute(
                    """SELECT id FROM tasks WHERE project_id=? AND task_type=?
                         AND status IN ('queued','running','waiting_login')
                       ORDER BY created_at ASC,id ASC""",
                    (group["project_id"], group["task_type"]),
                ).fetchall()
                for duplicate in rows[1:]:
                    message = "数据库升级时发现重复活跃增强任务；已保留最早任务，请手动重试本任务。"
                    conn.execute(
                        """UPDATE tasks SET status='failed',current_phase='failed',
                           error_message=?,finished_at=? WHERE id=?""",
                        (message, utcnow(), duplicate["id"]),
                    )
                    conn.execute(
                        """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
                           VALUES(?,?,?,?,?)""",
                        (
                            duplicate["id"], "migration_conflict", "error",
                            _json({"message": message, "reason": "duplicate_active_task"}), utcnow(),
                        ),
                    )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_one_active_enrichment
                   ON tasks(project_id,task_type)
                   WHERE task_type IN ('vision','ai_report','keyword_suggestions')
                     AND status IN ('queued','running','waiting_login')"""
            )
            duplicate_author_enrichments = conn.execute(
                """SELECT author_id,task_type FROM tasks
                   WHERE project_id IS NULL AND author_id IS NOT NULL
                     AND task_type IN ('vision','ai_report')
                     AND status IN ('queued','running','waiting_login')
                   GROUP BY author_id,task_type HAVING COUNT(*)>1"""
            ).fetchall()
            for group in duplicate_author_enrichments:
                rows = conn.execute(
                    """SELECT id FROM tasks WHERE project_id IS NULL AND author_id=?
                         AND task_type=? AND status IN ('queued','running','waiting_login')
                       ORDER BY created_at ASC,id ASC""",
                    (group["author_id"], group["task_type"]),
                ).fetchall()
                for duplicate in rows[1:]:
                    label = "图片理解" if group["task_type"] == "vision" else "大模型报告"
                    message = f"数据库升级时发现重复活跃作者{label}任务；已保留最早任务，请手动重试本任务。"
                    conn.execute(
                        """UPDATE tasks SET status='failed',current_phase='failed',
                           error_message=?,finished_at=? WHERE id=?""",
                        (message, utcnow(), duplicate["id"]),
                    )
                    conn.execute(
                        """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
                           VALUES(?,?,?,?,?)""",
                        (
                            duplicate["id"], "migration_conflict", "error",
                            _json({"message": message, "reason": "duplicate_active_author_enrichment"}), utcnow(),
                        ),
                    )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_one_active_author_enrichment
                   ON tasks(author_id,task_type)
                   WHERE project_id IS NULL AND author_id IS NOT NULL
                     AND task_type IN ('vision','ai_report')
                     AND status IN ('queued','running','waiting_login')"""
            )
            duplicate_comment_tasks = conn.execute(
                """SELECT post_id FROM tasks
                   WHERE post_id IS NOT NULL AND task_type='comments'
                     AND status IN ('queued','running','waiting_login')
                   GROUP BY post_id HAVING COUNT(*)>1"""
            ).fetchall()
            for group in duplicate_comment_tasks:
                rows = conn.execute(
                    """SELECT id FROM tasks WHERE post_id=? AND task_type='comments'
                         AND status IN ('queued','running','waiting_login')
                       ORDER BY created_at ASC,id ASC""",
                    (group["post_id"],),
                ).fetchall()
                for duplicate in rows[1:]:
                    message = "数据库升级时发现同一帖子存在重复活跃评论采集任务；已保留最早任务。"
                    conn.execute(
                        """UPDATE tasks SET status='failed',current_phase='failed',
                           error_message=?,finished_at=? WHERE id=?""",
                        (message, utcnow(), duplicate["id"]),
                    )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_one_active_post_comments
                   ON tasks(post_id,task_type)
                   WHERE post_id IS NOT NULL AND task_type='comments'
                     AND status IN ('queued','running','waiting_login')"""
            )
            vision_indexes = conn.execute("PRAGMA index_list(vision_analyses)").fetchall()
            cache_key_globally_unique = any(
                bool(index["unique"])
                and [
                    column["name"]
                    for column in conn.execute(
                        f'PRAGMA index_info("{index["name"]}")'
                    ).fetchall()
                ] == ["cache_key"]
                for index in vision_indexes
            )
            if cache_key_globally_unique:
                conn.execute("""CREATE TABLE vision_analyses_per_post (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    cache_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    UNIQUE(post_id, cache_key)
                )""")
                conn.execute("""INSERT INTO vision_analyses_per_post(
                    id,post_id,cache_key,model,prompt_version,analysis_json,analyzed_at
                ) SELECT id,post_id,cache_key,model,prompt_version,analysis_json,analyzed_at
                  FROM vision_analyses""")
                conn.execute("DROP TABLE vision_analyses")
                conn.execute("ALTER TABLE vision_analyses_per_post RENAME TO vision_analyses")
            vision_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(vision_analyses)").fetchall()
            }
            if "is_current" not in vision_columns:
                conn.execute(
                    "ALTER TABLE vision_analyses ADD COLUMN is_current INTEGER NOT NULL DEFAULT 0"
                )
            if "image_scope" not in vision_columns:
                conn.execute(
                    "ALTER TABLE vision_analyses ADD COLUMN image_scope TEXT NOT NULL DEFAULT 'all'"
                )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vision_cache_key ON vision_analyses(cache_key)")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_vision_current_scope
                   ON vision_analyses(post_id,model,prompt_version,image_scope,is_current)"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_posts_post_task ON task_posts(post_id,task_id)"
            )
            media_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(media_assets)").fetchall()
            }
            if "file_size_bytes" not in media_columns:
                conn.execute(
                    "ALTER TABLE media_assets ADD COLUMN file_size_bytes INTEGER NOT NULL DEFAULT 0"
                )
            if "ocr_completed_at" not in media_columns:
                conn.execute("ALTER TABLE media_assets ADD COLUMN ocr_completed_at TEXT")
                conn.execute(
                    "UPDATE media_assets SET ocr_completed_at=updated_at WHERE ocr_text!=''"
                )
            media_rows = conn.execute(
                """SELECT id,post_id,media_index,local_path,sha256,file_size_bytes FROM media_assets
                   WHERE local_path!='' ORDER BY post_id,media_index,id"""
            ).fetchall()
            media_by_post = {}
            for row in media_rows:
                path = Path(str(row["local_path"] or "")).expanduser()
                file_size_bytes = int(row["file_size_bytes"] or 0)
                if file_size_bytes <= 0:
                    try:
                        if not path.is_file():
                            continue
                        file_size_bytes = int(path.stat().st_size)
                    except OSError:
                        continue
                    conn.execute(
                        "UPDATE media_assets SET file_size_bytes=? WHERE id=?",
                        (file_size_bytes, int(row["id"])),
                    )
                sha256 = str(row["sha256"] or "")
                if not sha256:
                    try:
                        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                    except OSError:
                        continue
                    conn.execute(
                        "UPDATE media_assets SET sha256=? WHERE id=?",
                        (sha256, int(row["id"])),
                    )
                media_by_post.setdefault(int(row["post_id"]), []).append((path, sha256))
            for row in conn.execute(
                "SELECT id,post_id,cache_key,model,prompt_version FROM vision_analyses"
            ).fetchall():
                media = media_by_post.get(int(row["post_id"])) or []
                if not media:
                    continue
                model = str(row["model"] or "default")
                prompt_version = str(row["prompt_version"] or "v1")
                new_key = _vision_cache_key_v2(
                    [sha256 for _path, sha256 in media], model, prompt_version
                )
                current_key = str(row["cache_key"] or "")
                matches = current_key == new_key
                if not matches:
                    try:
                        legacy = hashlib.sha256()
                        for path, _sha256 in media:
                            legacy.update(path.read_bytes())
                        legacy.update(prompt_version.encode("utf-8"))
                        legacy.update(model.encode("utf-8"))
                        matches = current_key == legacy.hexdigest()
                    except OSError:
                        matches = False
                if not matches:
                    continue
                try:
                    conn.execute(
                        "UPDATE vision_analyses SET cache_key=?,is_current=1 WHERE id=?",
                        (new_key, int(row["id"])),
                    )
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE vision_analyses SET is_current=1 WHERE post_id=? AND cache_key=?",
                        (int(row["post_id"]), new_key),
                    )
            author_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(authors)").fetchall()
            }
            if "total_post_count" not in author_columns:
                conn.execute("ALTER TABLE authors ADD COLUMN total_post_count INTEGER")
            report_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
            generator_version_was_missing = "generator_version" not in report_columns
            report_migrations = {
                "generator_type": "TEXT NOT NULL DEFAULT 'template'",
                "generator_version": "INTEGER NOT NULL DEFAULT 1",
                "model": "TEXT DEFAULT ''",
                "prompt_version": "TEXT DEFAULT ''",
                "evidence_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "generation_config_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, definition in report_migrations.items():
                if column not in report_columns:
                    conn.execute(f"ALTER TABLE reports ADD COLUMN {column} {definition}")
            conn.execute("UPDATE reports SET generator_type='template' WHERE generator_type IS NULL OR generator_type='' ")
            if generator_version_was_missing:
                conn.execute("UPDATE reports SET generator_version=version WHERE generator_type='template'")
            report_task_column = next(
                row for row in conn.execute("PRAGMA table_info(reports)").fetchall()
                if row["name"] == "task_id"
            )
            if report_task_column["notnull"]:
                conn.execute("DROP TABLE IF EXISTS reports_nullable_task")
                conn.execute("""CREATE TABLE reports_nullable_task (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    report_type TEXT NOT NULL,
                    generator_type TEXT NOT NULL DEFAULT 'template',
                    generator_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'completed',
                    title TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    content_markdown TEXT NOT NULL,
                    evidence_post_count INTEGER NOT NULL DEFAULT 0,
                    evidence_author_count INTEGER NOT NULL DEFAULT 0,
                    model TEXT DEFAULT '',
                    prompt_version TEXT DEFAULT '',
                    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    generation_config_json TEXT NOT NULL DEFAULT '{}',
                    generated_at TEXT NOT NULL,
                    UNIQUE(project_id, version)
                )""")
                conn.execute("""INSERT INTO reports_nullable_task(
                    id,project_id,task_id,version,report_type,generator_type,generator_version,
                    status,title,summary_json,content_markdown,evidence_post_count,evidence_author_count,
                    model,prompt_version,evidence_snapshot_json,generation_config_json,generated_at
                ) SELECT id,project_id,task_id,version,report_type,generator_type,generator_version,
                    status,title,summary_json,content_markdown,evidence_post_count,evidence_author_count,
                    model,prompt_version,evidence_snapshot_json,generation_config_json,generated_at
                    FROM reports""")
                conn.execute("DROP TABLE reports")
                conn.execute("ALTER TABLE reports_nullable_task RENAME TO reports")
            author_report_task_column = next(
                row for row in conn.execute("PRAGMA table_info(author_reports)").fetchall()
                if row["name"] == "task_id"
            )
            if author_report_task_column["notnull"]:
                conn.execute("DROP TABLE IF EXISTS author_reports_nullable_task")
                conn.execute("""CREATE TABLE author_reports_nullable_task (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    report_type TEXT NOT NULL DEFAULT 'author',
                    generator_type TEXT NOT NULL DEFAULT 'llm',
                    generator_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'completed',
                    title TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    content_markdown TEXT NOT NULL,
                    evidence_post_count INTEGER NOT NULL DEFAULT 0,
                    evidence_author_count INTEGER NOT NULL DEFAULT 1,
                    model TEXT DEFAULT '',
                    prompt_version TEXT DEFAULT '',
                    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    generation_config_json TEXT NOT NULL DEFAULT '{}',
                    generated_at TEXT NOT NULL,
                    UNIQUE(author_id, version)
                )""")
                conn.execute("""INSERT INTO author_reports_nullable_task(
                    id,author_id,task_id,version,report_type,generator_type,generator_version,
                    status,title,summary_json,content_markdown,evidence_post_count,evidence_author_count,
                    model,prompt_version,evidence_snapshot_json,generation_config_json,generated_at
                ) SELECT id,author_id,task_id,version,report_type,generator_type,generator_version,
                    status,title,summary_json,content_markdown,evidence_post_count,evidence_author_count,
                    model,prompt_version,evidence_snapshot_json,generation_config_json,generated_at
                    FROM author_reports""")
                conn.execute("DROP TABLE author_reports")
                conn.execute("ALTER TABLE author_reports_nullable_task RENAME TO author_reports")
            for row in conn.execute("SELECT id,author_id,profile_url FROM authors").fetchall():
                canonical = _canonical_profile_url(row["profile_url"], row["author_id"])
                if canonical != row["profile_url"]:
                    conn.execute("UPDATE authors SET profile_url=?,updated_at=? WHERE id=?", (canonical, utcnow(), row["id"]))
        self.remove_redundant_post_detail_author_relations()
        return self.remove_invalid_search_cards()

    def scalar(self, sql: str, params: Sequence[Any] = ()):
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return None if row is None else row[0]

    def create_project(self, name: str, research_type: str, config: Dict[str, Any], description: str = "") -> int:
        if config.get("project_kind") == "my_project" and research_type != "author":
            raise ValueError("个人项目固定为作者调研")
        now = utcnow()
        base = _slug(name)
        slug = base
        suffix = 2
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if config.get("project_kind") == "my_project":
                for row in conn.execute("SELECT config_json FROM projects").fetchall():
                    try:
                        existing_config = json.loads(row["config_json"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(existing_config, dict) and existing_config.get("project_kind") == "my_project":
                        raise ValueError("个人项目已经存在")
            while conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
                slug = f"{base}-{suffix}"
                suffix += 1
            cur = conn.execute(
                "INSERT INTO projects(name,slug,description,research_type,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (name, slug, description, research_type, _json(config), now, now),
            )
            return int(cur.lastrowid)

    def update_project(self, project_id: int, name: str, description: str = "") -> bool:
        with self.connect() as conn:
            updated = conn.execute(
                "UPDATE projects SET name=?,description=?,updated_at=? WHERE id=?",
                (name, description, utcnow(), project_id),
            )
            return updated.rowcount == 1

    def upsert_author(self, data: Dict[str, Any]) -> int:
        now = utcnow()
        external_id = str(data["author_id"]).strip()
        fields = {
            "xhs_id": data.get("xhs_id", ""),
            "display_name": data.get("display_name") or data.get("author", ""),
            "profile_url": _canonical_profile_url(data.get("profile_url") or data.get("author_url", ""), external_id),
            "bio": data.get("bio", ""),
            "ip_location": data.get("ip_location", ""),
            "followers_count": data.get("followers_count"),
            "following_count": data.get("following_count"),
            "likes_collections_count": data.get("likes_collections_count"),
            "total_post_count": data.get("total_post_count"),
            "avatar_url": data.get("avatar_url", ""),
        }
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM authors WHERE author_id=?", (external_id,)).fetchone()
            if row:
                assignments = []
                values = []
                for key, value in fields.items():
                    if value not in (None, ""):
                        assignments.append(f"{key}=?")
                        values.append(value)
                assignments.extend(["last_seen_at=?", "updated_at=?"])
                values.extend([now, now, external_id])
                conn.execute(f"UPDATE authors SET {','.join(assignments)} WHERE author_id=?", values)
                return int(row["id"])
            cur = conn.execute(
                """INSERT INTO authors(author_id,xhs_id,display_name,profile_url,bio,ip_location,
                   followers_count,following_count,likes_collections_count,total_post_count,avatar_url,
                   first_seen_at,last_seen_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (external_id, fields["xhs_id"], fields["display_name"], fields["profile_url"], fields["bio"],
                 fields["ip_location"], fields["followers_count"], fields["following_count"],
                 fields["likes_collections_count"], fields["total_post_count"], fields["avatar_url"],
                 now, now, now),
            )
            return int(cur.lastrowid)

    def upsert_post(self, data: Dict[str, Any]) -> int:
        now = utcnow()
        note_id = str(data["note_id"]).strip()
        author_pk = None
        external_author_id = data.get("author_id")
        if external_author_id:
            author_pk = self.upsert_author({
                "author_id": external_author_id,
                "display_name": data.get("author", ""),
                "profile_url": data.get("author_url", ""),
            })
        fields = {
            "author_id": author_pk,
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "note_type": data.get("type") or data.get("note_type", ""),
            "note_url": data.get("url") or data.get("link", ""),
            "cover_url": data.get("cover_url", ""),
            "cover_local_path": data.get("cover_local_path", ""),
            "publish_date": data.get("date") or data.get("publish_date", ""),
            "likes_count": data.get("likes_count"),
            "favorites_count": data.get("favorites_count"),
            "comments_count": data.get("comments_count"),
            "detail_level": data.get("detail_level", "card"),
            "content_hash": data.get("content_hash", ""),
            "status": data.get("status", "active"),
        }
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM posts WHERE note_id=?", (note_id,)).fetchone()
            if row:
                assignments = []
                values = []
                for key, value in fields.items():
                    if key == "detail_level" and value == "card":
                        continue
                    if value not in (None, ""):
                        assignments.append(f"{key}=?")
                        values.append(value)
                assignments.extend(["last_seen_at=?", "updated_at=?"])
                values.extend([now, now, note_id])
                conn.execute(f"UPDATE posts SET {','.join(assignments)} WHERE note_id=?", values)
                return int(row["id"])
            columns = list(fields)
            cur = conn.execute(
                f"INSERT INTO posts(note_id,{','.join(columns)},first_seen_at,last_seen_at,updated_at) VALUES({','.join(['?']*(len(columns)+4))})",
                [note_id] + [fields[c] for c in columns] + [now, now, now],
            )
            return int(cur.lastrowid)

    def attach_post_to_project(self, project_id: int, post_id: int, task_id: Optional[str] = None):
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO project_posts(project_id,post_id,first_task_id,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(project_id,post_id) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (project_id, post_id, task_id, now, now),
            )

    def attach_known_author_posts(
        self,
        project_id: int,
        external_author_id: str,
        limit: int,
        task_id: Optional[str] = None,
    ) -> int:
        """Reuse locally known posts when an author page scan returns only a partial grid."""
        if not str(external_author_id or "").strip() or int(limit) <= 0:
            return 0
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO project_posts(project_id,post_id,first_task_id,first_seen_at,last_seen_at)
                   SELECT ?,p.id,?,?,? FROM posts p
                   JOIN authors a ON a.id=p.author_id
                   WHERE a.author_id=? AND COALESCE(p.status,'active')='active'
                   ORDER BY p.last_seen_at DESC,p.id DESC LIMIT ?
                   ON CONFLICT(project_id,post_id) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (project_id, task_id, now, now, str(external_author_id).strip(), int(limit)),
            )
            return int(conn.execute(
                """SELECT COUNT(*) FROM project_posts pp
                   JOIN posts p ON p.id=pp.post_id JOIN authors a ON a.id=p.author_id
                   WHERE pp.project_id=? AND a.author_id=?""",
                (project_id, str(external_author_id).strip()),
            ).fetchone()[0])

    def attach_author_to_project(self, project_id: int, author_id: int, relation_type: str, task_id: Optional[str] = None):
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO project_authors(project_id,author_id,relation_type,first_task_id,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,author_id,relation_type) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (project_id, author_id, relation_type, task_id, now, now),
            )

    def attach_project_post_author_if_unrelated(
        self,
        project_id: int,
        post_id: int,
        task_id: Optional[str] = None,
    ) -> bool:
        """Keep project-author coverage when a detail refresh discovers a post author."""
        now = utcnow()
        with self.connect() as conn:
            inserted = conn.execute(
                """INSERT INTO project_authors(
                       project_id,author_id,relation_type,first_task_id,first_seen_at,last_seen_at
                   )
                   SELECT ?,p.author_id,'post_author',?,?,?
                   FROM project_posts pp JOIN posts p ON p.id=pp.post_id
                   WHERE pp.project_id=? AND pp.post_id=? AND p.author_id IS NOT NULL
                     AND NOT EXISTS (
                         SELECT 1 FROM project_authors pa
                         WHERE pa.project_id=? AND pa.author_id=p.author_id
                     )
                   ON CONFLICT(project_id,author_id,relation_type) DO NOTHING""",
                (project_id, task_id, now, now, project_id, post_id, project_id),
            )
            return bool(inserted.rowcount)

    def record_task_post(self, task_id: str, post_id: int, source_type: str, source_value: str, source_rank: int):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO task_posts(task_id,post_id,source_type,source_value,source_rank,discovered_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(task_id,post_id,source_type,source_value)
                   DO UPDATE SET source_rank=excluded.source_rank""",
                (task_id, post_id, source_type, source_value, source_rank, utcnow()),
            )

    def upsert_media(self, post_id: int, media: Dict[str, Any], media_index: int = 0, media_type: str = "image"):
        now = utcnow()
        local_path = media.get("local_path", "")
        sha256 = str(media.get("sha256") or "")
        file_size_bytes = 0
        if local_path:
            try:
                file_size_bytes = int(Path(local_path).stat().st_size)
            except OSError:
                file_size_bytes = 0
        if local_path and not sha256:
            try:
                sha256 = hashlib.sha256(Path(local_path).read_bytes()).hexdigest()
            except OSError:
                sha256 = ""
        status = "downloaded" if local_path else ("failed" if media.get("download_error") else "remote")
        with self.connect() as conn:
            existing = conn.execute(
                """SELECT local_path,sha256 FROM media_assets
                   WHERE post_id=? AND media_index=? AND media_type=?""",
                (post_id, media_index, media_type),
            ).fetchone()
            conn.execute(
                """INSERT INTO media_assets(post_id,media_index,media_type,original_url,local_path,sha256,
                   file_size_bytes,ocr_text,ocr_engine,ocr_version,ocr_completed_at,download_status,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(post_id,media_index,media_type) DO UPDATE SET
                   original_url=excluded.original_url,
                   local_path=CASE WHEN excluded.local_path!='' THEN excluded.local_path ELSE media_assets.local_path END,
                   sha256=CASE WHEN excluded.sha256!='' THEN excluded.sha256 ELSE media_assets.sha256 END,
                   file_size_bytes=CASE WHEN excluded.local_path!='' THEN excluded.file_size_bytes ELSE media_assets.file_size_bytes END,
                   ocr_text=CASE WHEN excluded.ocr_text!='' THEN excluded.ocr_text ELSE media_assets.ocr_text END,
                   ocr_engine=CASE WHEN excluded.ocr_text!='' THEN excluded.ocr_engine ELSE media_assets.ocr_engine END,
                   ocr_version=CASE WHEN excluded.ocr_text!='' THEN excluded.ocr_version ELSE media_assets.ocr_version END,
                   ocr_completed_at=CASE WHEN excluded.ocr_text!='' THEN excluded.ocr_completed_at ELSE media_assets.ocr_completed_at END,
                   download_status=excluded.download_status,updated_at=excluded.updated_at""",
                (post_id, media_index, media_type, media.get("url", ""), local_path, sha256, file_size_bytes,
                 media.get("ocr_text", ""), media.get("ocr_engine", "socai-ppocr"), media.get("ocr_version", ""),
                 now if media.get("ocr_text", "") else None, status, now),
            )
            media_changed = bool(
                existing
                and local_path
                and (
                    str(existing["local_path"] or "") != str(local_path)
                    or (sha256 and str(existing["sha256"] or "") != sha256)
                )
            )
            if media_changed:
                image_scope = "cover" if media_type == "cover" else "detail"
                conn.execute(
                    """UPDATE vision_analyses SET is_current=0
                       WHERE post_id=? AND image_scope IN (?, 'all')""",
                    (post_id, image_scope),
                )

    def save_media_ocr(self, media_id: int, text: str, engine: str, version: str = ""):
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """UPDATE media_assets
                   SET ocr_text=?,ocr_engine=?,ocr_version=?,ocr_completed_at=?,updated_at=?
                   WHERE id=?""",
                (str(text or ""), str(engine or ""), str(version or ""), now, now, int(media_id)),
            )

    def mark_post_detail_fetched(self, post_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE posts SET last_detail_fetched_at=?,updated_at=? WHERE id=?", (utcnow(), utcnow(), post_id))

    def mark_author_profile_fetched(self, author_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE authors SET last_profile_fetched_at=?,updated_at=? WHERE id=?", (utcnow(), utcnow(), author_id))

    def author_profile_is_fresh(self, external_author_id: str, ttl_days: int) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        return bool(self.scalar(
            "SELECT 1 FROM authors WHERE author_id=? AND last_profile_fetched_at>=?",
            (external_author_id, cutoff),
        ))

    def post_details_are_fresh(self, note_ids, ttl_days: int) -> bool:
        note_ids = [str(value) for value in note_ids if value]
        if not note_ids:
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        placeholders = ",".join("?" for _ in note_ids)
        count = self.scalar(
            f"SELECT COUNT(*) FROM posts WHERE note_id IN ({placeholders}) AND last_detail_fetched_at>=?",
            note_ids + [cutoff],
        )
        return int(count or 0) == len(set(note_ids))

    def save_project_scores(self, project_id: int, scoring: Dict[str, Any]):
        now = utcnow()
        with self.connect() as conn:
            for post_id, value in scoring.get("scores", {}).items():
                conn.execute(
                    """UPDATE project_posts SET popularity_score=?,popularity_percentile=?,popularity_level=?,
                       popularity_method=?,score_version=?,scored_at=? WHERE project_id=? AND post_id=?""",
                    (value["score"], value["percentile"], value["level"], scoring["method"], "v1", now, project_id, int(post_id)),
                )

    @staticmethod
    def _insert_pending_report(conn, *, task_id: str, project_id: Optional[int],
                               author_id: Optional[int], mode: str,
                               placeholder: Dict[str, Any]):
        now = utcnow()
        title = str(placeholder.get("title") or "大模型报告").strip()[:200] or "大模型报告"
        generation_config = placeholder.get("generation_config") or {}
        if project_id is not None:
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM reports WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            generator_version = conn.execute(
                "SELECT COALESCE(MAX(generator_version),0)+1 FROM reports "
                "WHERE project_id=? AND generator_type='llm'",
                (project_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO reports(
                       project_id,task_id,version,report_type,generator_type,generator_version,
                       status,title,summary_json,content_markdown,evidence_post_count,
                       evidence_author_count,model,prompt_version,evidence_snapshot_json,
                       generation_config_json,generated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id, task_id, version, mode, "llm", generator_version,
                    "generating", title, _json({}), "", 0, 0, "", "", _json({}),
                    _json(generation_config), now,
                ),
            )
            return
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM author_reports WHERE author_id=?",
            (author_id,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO author_reports(
                   author_id,task_id,version,report_type,generator_type,generator_version,
                   status,title,summary_json,content_markdown,evidence_post_count,
                   evidence_author_count,model,prompt_version,evidence_snapshot_json,
                   generation_config_json,generated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                author_id, task_id, version, "author", "llm", version,
                "generating", title, _json({}), "", 0, 1, "", "", _json({}),
                _json(generation_config), now,
            ),
        )

    @staticmethod
    def _insert_pending_presentation(conn, *, task_id: str, project_id: Optional[int],
                                     author_id: Optional[int], placeholder: Dict[str, Any]) -> int:
        project_report_id = placeholder.get("project_report_id")
        author_report_id = placeholder.get("author_report_id")
        if (project_report_id is None) == (author_report_id is None):
            raise ValueError("presentation placeholder requires exactly one source report")
        title = str(placeholder.get("title") or "HTML 演示稿").strip()[:200] or "HTML 演示稿"
        page_mode = str(placeholder.get("page_mode") or "standard")
        if page_mode not in ("concise", "standard", "complete"):
            raise ValueError("invalid presentation page mode")
        if project_report_id is not None:
            source = conn.execute(
                """SELECT id FROM reports WHERE id=? AND project_id=? AND generator_type='llm'
                     AND status IN ('completed','partial') AND content_markdown!=''""",
                (int(project_report_id), project_id),
            ).fetchone()
            if not source or project_id is None or author_id is not None:
                raise ValueError("project presentation source report is unavailable")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM report_presentations WHERE project_report_id=?",
                (int(project_report_id),),
            ).fetchone()[0]
        else:
            source = conn.execute(
                """SELECT id FROM author_reports WHERE id=? AND author_id=? AND generator_type='llm'
                     AND status IN ('completed','partial') AND content_markdown!=''""",
                (int(author_report_id), author_id),
            ).fetchone()
            if not source or author_id is None or project_id is not None:
                raise ValueError("author presentation source report is unavailable")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM report_presentations WHERE author_report_id=?",
                (int(author_report_id),),
            ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO report_presentations(
                   project_report_id,author_report_id,task_id,version,status,title,page_mode,
                   slides_json,html_content,generation_config_json,generated_at
               ) VALUES(?,?,?,?, 'generating',?,?, '{}','',?,?)""",
            (
                int(project_report_id) if project_report_id is not None else None,
                int(author_report_id) if author_report_id is not None else None,
                task_id, int(version), title, page_mode,
                _json(placeholder.get("generation_config") or {}), utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def create_task(self, project_id: Optional[int], mode: str, created_from: str, payload: Dict[str, Any],
                    task_type: Optional[str] = None, author_id: Optional[int] = None,
                    post_id: Optional[int] = None,
                    _after_insert: Optional[Callable[[], None]] = None,
                    _report_placeholder: Optional[Dict[str, Any]] = None,
                    _presentation_placeholder: Optional[Dict[str, Any]] = None) -> str:
        task_type = task_type or {
            "vision": "vision", "ai_report": "ai_report", "keyword_suggestions": "keyword_suggestions"
        }.get(payload.get("operation"), "research")
        if task_type not in ("research", "vision", "ai_report", "keyword_suggestions", "comments"):
            raise ValueError("invalid task_type")
        if task_type == "comments":
            if post_id is None or project_id is not None or author_id is not None or mode != "post":
                raise ValueError("comment tasks require exactly one post")
        elif post_id is not None:
            raise ValueError("post_id is only supported for comment tasks")
        if task_type == "vision" and (project_id is None) == (author_id is None):
            raise ValueError("vision tasks require exactly one project or author")
        if task_type == "keyword_suggestions" and project_id is None:
            raise ValueError("keyword suggestion tasks require a project")
        if task_type == "ai_report" and (project_id is None) == (author_id is None):
            raise ValueError("ai_report tasks require exactly one project or author")
        if task_type == "research" and author_id is not None:
            author_update = payload.get("author_update")
            post_detail_update = payload.get("post_detail_update")
            is_independent_author_update = (
                project_id is None
                and isinstance(author_update, dict)
                and bool(author_update.get("scopes"))
            )
            is_author_post_detail_update = (
                project_id is None
                and mode == "author"
                and payload.get("operation") == "post_detail_update"
                and isinstance(post_detail_update, dict)
                and post_detail_update.get("scope") == "author"
                and post_detail_update.get("scope_id") == author_id
            )
            if not is_independent_author_update and not is_author_post_detail_update:
                raise ValueError(
                    "research author_id is only supported for independent author or post detail updates"
                )
        if task_type not in ("research", "vision", "ai_report") and author_id is not None:
            raise ValueError("author_id is not supported for this task type")
        if _report_placeholder is not None:
            if task_type != "ai_report":
                raise ValueError("report placeholders require an ai_report task")
            if not isinstance(_report_placeholder, dict):
                raise ValueError("report placeholder must be an object")
        if _presentation_placeholder is not None:
            if task_type != "ai_report" or _report_placeholder is not None:
                raise ValueError("presentation placeholders require a dedicated ai_report task")
            if not isinstance(_presentation_placeholder, dict):
                raise ValueError("presentation placeholder must be an object")
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        try:
            with self.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if project_id is not None and not conn.execute(
                    "SELECT 1 FROM projects WHERE id=?", (project_id,),
                ).fetchone():
                    raise KeyError("project not found")
                if author_id is not None and not conn.execute(
                    "SELECT 1 FROM authors WHERE id=?", (author_id,),
                ).fetchone():
                    raise KeyError("author not found")
                if post_id is not None and not conn.execute(
                    "SELECT 1 FROM posts WHERE id=?", (post_id,),
                ).fetchone():
                    raise KeyError("post not found")
                conn.execute(
                    """INSERT INTO tasks(
                           id,project_id,author_id,post_id,task_type,mode,created_from,input_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (task_id, project_id, author_id, post_id, task_type, mode, created_from, _json(payload), utcnow()),
                )
                if _report_placeholder is not None:
                    self._insert_pending_report(
                        conn,
                        task_id=task_id,
                        project_id=project_id,
                        author_id=author_id,
                        mode=mode,
                        placeholder=_report_placeholder,
                    )
                if _presentation_placeholder is not None:
                    presentation_id = self._insert_pending_presentation(
                        conn,
                        task_id=task_id,
                        project_id=project_id,
                        author_id=author_id,
                        placeholder=_presentation_placeholder,
                    )
                    payload["presentation_generation"]["presentation_id"] = presentation_id
                    conn.execute(
                        "UPDATE tasks SET input_json=? WHERE id=?",
                        (_json(payload), task_id),
                    )
                if _after_insert is not None:
                    _after_insert()
        except sqlite3.IntegrityError as exc:
            if task_type in ("vision", "ai_report", "keyword_suggestions") and (
                "tasks.project_id, tasks.task_type" in str(exc)
                or "idx_tasks_one_active_enrichment" in str(exc)
            ):
                label = {
                    "vision": "图片理解",
                    "ai_report": "大模型报告",
                    "keyword_suggestions": "AI 关键词生成",
                }[task_type]
                raise ActiveTaskConflict(f"项目已有运行中的{label}任务") from exc
            if task_type in ("vision", "ai_report") and author_id is not None and (
                "tasks.author_id, tasks.task_type" in str(exc)
                or "idx_tasks_one_active_author_enrichment" in str(exc)
            ):
                label = "图片理解" if task_type == "vision" else "大模型报告"
                raise ActiveTaskConflict(f"作者已有运行中的{label}任务") from exc
            if task_type == "comments" and post_id is not None and (
                "tasks.post_id, tasks.task_type" in str(exc)
                or "idx_tasks_one_active_post_comments" in str(exc)
            ):
                raise ActiveTaskConflict("该帖子已有运行中的评论采集任务") from exc
            raise
        return task_id

    def update_task(self, task_id: str, **values):
        allowed = {"status", "current_phase", "progress_current", "progress_total", "warning_count",
                   "error_message", "result_json", "started_at", "finished_at"}
        updates = {k: (_json(v) if k == "result_json" and not isinstance(v, str) else v)
                   for k, v in values.items() if k in allowed}
        if not updates:
            return
        with self.connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {','.join(f'{key}=?' for key in updates)} WHERE id=? AND status!='cancelled'",
                list(updates.values()) + [task_id],
            )

    @staticmethod
    def _delete_pending_reports(conn, task_id: str):
        conn.execute("DELETE FROM reports WHERE task_id=? AND status='generating'", (task_id,))
        conn.execute(
            "DELETE FROM author_reports WHERE task_id=? AND status='generating'",
            (task_id,),
        )
        conn.execute(
            "DELETE FROM report_presentations WHERE task_id=? AND status='generating'",
            (task_id,),
        )

    def fail_report_task(self, task_id: str, message: str, *, phase: str = "failed",
                         event_type: str = "error",
                         event_phase: Optional[str] = None,
                         event_payload: Optional[Dict[str, Any]] = None) -> bool:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            failed = conn.execute(
                """UPDATE tasks SET status='failed',current_phase=?,error_message=?,finished_at=?
                   WHERE id=? AND task_type='ai_report'
                     AND status IN ('queued','running','waiting_login')""",
                (phase, str(message), utcnow(), task_id),
            )
            if failed.rowcount != 1:
                return False
            self._delete_pending_reports(conn, task_id)
            payload = dict(event_payload or {})
            payload.setdefault("message", str(message))
            conn.execute(
                "INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (task_id, event_phase or phase, event_type, _json(payload), utcnow()),
            )
            return True

    def cancel_task(self, task_id: str) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE tasks SET status='cancelled',current_phase='cancelled',error_message='',finished_at=? "
                "WHERE id=? AND status IN ('queued','running','waiting_login')",
                (utcnow(), task_id),
            )
            if not result.rowcount:
                return False
            self._delete_pending_reports(conn, task_id)
            conn.execute(
                "INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (task_id, "cancelled", "cancelled", _json({"message": "任务已由用户取消"}), utcnow()),
            )
            return True

    def is_task_cancelled(self, task_id: str) -> bool:
        return bool(self.scalar("SELECT 1 FROM tasks WHERE id=? AND status='cancelled'", (task_id,)))

    def has_active_task_predecessor(self, task_id: str, project_id: Optional[int]) -> bool:
        if project_id is None:
            return False
        return bool(self.scalar(
            """SELECT 1 FROM tasks previous JOIN tasks current ON current.id=?
               WHERE previous.project_id=? AND previous.id!=current.id
                 AND previous.status IN ('queued','running','waiting_login')
                 AND NOT (
                   (previous.task_type='vision' AND current.task_type='ai_report') OR
                   (previous.task_type='ai_report' AND current.task_type='vision')
                 )
                 AND (previous.created_at<current.created_at OR
                      (previous.created_at=current.created_at AND previous.id<current.id))
               LIMIT 1""",
            (task_id, project_id),
        ))

    def append_task_event(self, task_id: str, phase: str, event_type: str, payload: Dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (task_id, phase, event_type, _json(payload), utcnow()),
            )

    def list_task_events(self, task_id: str, after: int = 0):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM task_events WHERE task_id=? AND id>? ORDER BY id", (task_id, after)).fetchall()
            return [self._row(row) for row in rows]

    def get_cached_report_chunk(self, cache_key: str):
        with self.connect() as conn:
            row = conn.execute(
                """SELECT result_json FROM report_chunks
                   WHERE cache_key=? AND status='completed'
                   ORDER BY updated_at DESC,id DESC LIMIT 1""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            try:
                value = json.loads(row["result_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

    def save_report_chunk(self, task_id: str, chunk_index: int, cache_key: str,
                          input_chars: int, status: str, result: Optional[Dict[str, Any]] = None,
                          diagnostics: Optional[Dict[str, Any]] = None, error_message: str = ""):
        if status not in ("running", "completed", "failed"):
            raise ValueError("invalid report chunk status")
        now = utcnow()
        diagnostics = diagnostics or {}
        attempts = max(0, int(diagnostics.get("attempts") or 0))
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO report_chunks(
                       task_id,chunk_index,cache_key,status,attempts,input_chars,
                       result_json,diagnostics_json,error_message,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id,chunk_index) DO UPDATE SET
                     cache_key=excluded.cache_key,status=excluded.status,
                     attempts=excluded.attempts,input_chars=excluded.input_chars,
                     result_json=excluded.result_json,diagnostics_json=excluded.diagnostics_json,
                     error_message=excluded.error_message,updated_at=excluded.updated_at""",
                (
                    task_id, int(chunk_index), cache_key, status, attempts, max(0, int(input_chars)),
                    _json(result or {}), _json(diagnostics), str(error_message or "")[-4000:], now, now,
                ),
            )

    def list_report_chunks(self, task_id: str):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_chunks WHERE task_id=? ORDER BY chunk_index",
                (task_id,),
            ).fetchall()
            return [self._row(row) for row in rows]

    def get_task(self, task_id: str, include_cancelled: bool = False):
        with self.connect() as conn:
            sql = "SELECT * FROM tasks WHERE id=?" + ("" if include_cancelled else " AND status!='cancelled'")
            row = conn.execute(sql, (task_id,)).fetchone()
            return self._row(row) if row else None

    def create_report(self, project_id: int, task_id: str, report_type: str, title: str,
                      content: str, summary: Dict[str, Any], status: str = "completed",
                      evidence_post_count: int = 0, evidence_author_count: int = 0,
                      generator_type: str = "template", model: str = "", prompt_version: str = "",
                      evidence_snapshot: Optional[Dict[str, Any]] = None,
                      generation_config: Optional[Dict[str, Any]] = None,
                      task_warning_count: int = 0,
                      completion_event: Optional[Dict[str, Any]] = None,
                      _after_task_check: Optional[Callable[[], None]] = None) -> Optional[int]:
        if generator_type not in ("template", "llm"):
            raise ValueError("generator_type must be template or llm")
        if status not in ("completed", "partial"):
            raise ValueError("report status must be completed or partial")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT project_id,status FROM tasks WHERE id=?", (task_id,),
            ).fetchone()
            if (
                not task
                or int(task["project_id"]) != int(project_id)
                or task["status"] not in ("queued", "running", "waiting_login")
            ):
                return None
            if _after_task_check is not None:
                _after_task_check()
            pending = conn.execute(
                """SELECT id FROM reports
                   WHERE project_id=? AND task_id=? AND generator_type=? AND status='generating'""",
                (project_id, task_id, generator_type),
            ).fetchone()
            if pending:
                report_id = int(pending["id"])
                conn.execute(
                    """UPDATE reports SET report_type=?,status=?,title=?,summary_json=?,
                       content_markdown=?,evidence_post_count=?,evidence_author_count=?,model=?,
                       prompt_version=?,evidence_snapshot_json=?,generation_config_json=?,generated_at=?
                       WHERE id=? AND status='generating'""",
                    (
                        report_type, status, title, _json(summary), content,
                        evidence_post_count, evidence_author_count, model, prompt_version,
                        _json(evidence_snapshot or {}), _json(generation_config or {}),
                        utcnow(), report_id,
                    ),
                )
            else:
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM reports WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
                generator_version = conn.execute(
                    "SELECT COALESCE(MAX(generator_version),0)+1 FROM reports WHERE project_id=? AND generator_type=?",
                    (project_id, generator_type),
                ).fetchone()[0]
                cur = conn.execute(
                    """INSERT INTO reports(project_id,task_id,version,report_type,generator_type,generator_version,status,title,
                       summary_json,content_markdown,evidence_post_count,evidence_author_count,model,prompt_version,
                       evidence_snapshot_json,generation_config_json,generated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (project_id, task_id, version, report_type, generator_type, generator_version, status, title,
                     _json(summary), content, evidence_post_count, evidence_author_count, model, prompt_version,
                     _json(evidence_snapshot or {}), _json(generation_config or {}), utcnow()),
                )
                report_id = int(cur.lastrowid)
            conn.execute("UPDATE projects SET latest_report_id=?,updated_at=? WHERE id=?", (report_id, utcnow(), project_id))
            completed = conn.execute(
                """UPDATE tasks SET status=?,current_phase='completed',progress_current=1,
                   progress_total=1,warning_count=?,error_message='',result_json=?,finished_at=?
                   WHERE id=? AND project_id=?
                     AND status IN ('queued','running','waiting_login')""",
                (
                    status, max(0, int(task_warning_count)), _json(summary), utcnow(),
                    task_id, project_id,
                ),
            )
            if completed.rowcount != 1:
                raise RuntimeError("task stopped before report commit")
            conn.execute(
                """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    task_id, "completed", status,
                    _json(completion_event if completion_event is not None else {"summary": summary}),
                    utcnow(),
                ),
            )
            return report_id

    def create_author_report(self, author_id: int, task_id: str, title: str,
                             content: str, summary: Dict[str, Any],
                             evidence_post_count: int = 0, evidence_author_count: int = 1,
                             model: str = "", prompt_version: str = "",
                             evidence_snapshot: Optional[Dict[str, Any]] = None,
                             generation_config: Optional[Dict[str, Any]] = None,
                             completion_event: Optional[Dict[str, Any]] = None) -> Optional[int]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT project_id,author_id,status FROM tasks WHERE id=?", (task_id,),
            ).fetchone()
            if (
                not task
                or task["project_id"] is not None
                or int(task["author_id"] or 0) != int(author_id)
                or task["status"] not in ("queued", "running", "waiting_login")
            ):
                return None
            pending = conn.execute(
                """SELECT id FROM author_reports
                   WHERE author_id=? AND task_id=? AND status='generating'""",
                (author_id, task_id),
            ).fetchone()
            if pending:
                report_id = int(pending["id"])
                conn.execute(
                    """UPDATE author_reports SET status='completed',title=?,summary_json=?,
                       content_markdown=?,evidence_post_count=?,evidence_author_count=?,model=?,
                       prompt_version=?,evidence_snapshot_json=?,generation_config_json=?,generated_at=?
                       WHERE id=? AND status='generating'""",
                    (
                        title, _json(summary), content, evidence_post_count,
                        evidence_author_count, model, prompt_version,
                        _json(evidence_snapshot or {}), _json(generation_config or {}),
                        utcnow(), report_id,
                    ),
                )
            else:
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM author_reports WHERE author_id=?",
                    (author_id,),
                ).fetchone()[0]
                cur = conn.execute(
                    """INSERT INTO author_reports(
                           author_id,task_id,version,report_type,generator_type,generator_version,status,title,
                           summary_json,content_markdown,evidence_post_count,evidence_author_count,model,
                           prompt_version,evidence_snapshot_json,generation_config_json,generated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        author_id, task_id, version, "author", "llm", version, "completed", title,
                        _json(summary), content, evidence_post_count, evidence_author_count, model,
                        prompt_version, _json(evidence_snapshot or {}), _json(generation_config or {}), utcnow(),
                    ),
                )
                report_id = int(cur.lastrowid)
            completed = conn.execute(
                """UPDATE tasks SET status='completed',current_phase='completed',progress_current=1,
                   progress_total=1,warning_count=0,error_message='',result_json=?,finished_at=?
                   WHERE id=? AND project_id IS NULL AND author_id=?
                     AND status IN ('queued','running','waiting_login')""",
                (_json(summary), utcnow(), task_id, author_id),
            )
            if completed.rowcount != 1:
                raise RuntimeError("task stopped before author report commit")
            conn.execute(
                """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    task_id, "completed", "completed",
                    _json(completion_event if completion_event is not None else {"summary": summary}),
                    utcnow(),
                ),
            )
            return report_id

    def complete_report_presentation(
        self,
        task_id: str,
        presentation_id: int,
        slides: Dict[str, Any],
        html_content: str,
        *,
        model: str = "",
        prompt_version: str = "",
        generation_config: Optional[Dict[str, Any]] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> bool:
        slide_count = len(slides.get("slides") or [])
        if slide_count <= 0 or not html_content.strip():
            raise ValueError("completed presentation requires slides and HTML")
        now = utcnow()
        result = {
            "presentation_id": int(presentation_id),
            "slide_count": slide_count,
            "title": str(slides.get("title") or "HTML 演示稿"),
        }
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                """SELECT project_id,author_id,status FROM tasks
                   WHERE id=? AND task_type='ai_report'""",
                (task_id,),
            ).fetchone()
            presentation = conn.execute(
                """SELECT id FROM report_presentations
                   WHERE id=? AND task_id=? AND status='generating'""",
                (int(presentation_id), task_id),
            ).fetchone()
            if (
                not task
                or task["status"] not in ("queued", "running", "waiting_login")
                or not presentation
            ):
                return False
            updated = conn.execute(
                """UPDATE report_presentations SET status='completed',title=?,slide_count=?,
                   slides_json=?,html_content=?,model=?,prompt_version=?,generation_config_json=?,
                   generated_at=? WHERE id=? AND task_id=? AND status='generating'""",
                (
                    result["title"], slide_count, _json(slides), html_content, model,
                    prompt_version, _json(generation_config or {}), now,
                    int(presentation_id), task_id,
                ),
            )
            if updated.rowcount != 1:
                return False
            completed = conn.execute(
                """UPDATE tasks SET status='completed',current_phase='completed',
                   progress_current=1,progress_total=1,warning_count=0,error_message='',
                   result_json=?,finished_at=? WHERE id=?
                   AND status IN ('queued','running','waiting_login')""",
                (_json(result), now, task_id),
            )
            if completed.rowcount != 1:
                raise RuntimeError("task stopped before presentation commit")
            conn.execute(
                """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    task_id, "completed", "completed",
                    _json({"message": "HTML 演示稿已生成", "summary": result,
                           "diagnostics": diagnostics or {}}), now,
                ),
            )
            return True

    def create_data_summary(self, *, project_id: Optional[int] = None,
                            author_id: Optional[int] = None,
                            summary: Dict[str, Any], task_id: Optional[str] = None,
                            task_status: str = "completed",
                            task_result: Optional[Dict[str, Any]] = None,
                            task_warning_count: int = 0,
                            completion_event: Optional[Dict[str, Any]] = None,
                            generation_config: Optional[Dict[str, Any]] = None,
                            evidence_snapshot: Optional[Dict[str, Any]] = None) -> int:
        if (project_id is None) == (author_id is None):
            raise ValueError("data summary requires exactly one project or author")
        captured_at = str(summary.get("captured_at") or utcnow())
        scope = str(summary.get("scope") or "")
        if project_id is not None and scope != "project":
            raise ValueError("project data summary scope mismatch")
        if author_id is not None and scope != "author":
            raise ValueError("author data summary scope mismatch")
        if task_status not in ("completed", "partial"):
            raise ValueError("task status must be completed or partial")
        core = summary.get("core") if isinstance(summary.get("core"), dict) else {}
        post_count = int(
            core.get("post_count")
            if project_id is not None
            else core.get("stored_post_count")
            or 0
        )
        author_count = int(core.get("author_count") or (1 if author_id is not None else 0))
        title = f"{summary.get('subject', {}).get('name') or '未命名'} 数据摘要"
        generation_config = generation_config or {"trigger": "manual"}
        snapshot = {
            "captured_at": captured_at,
            "post_count": post_count,
            "author_count": author_count,
            "ocr_post_count": summary.get("post_completeness", {}).get("ocr", 0),
            "vision_post_count": summary.get("post_completeness", {}).get("vision", 0),
            **(evidence_snapshot or {}),
        }
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if task_id is not None:
                task = conn.execute(
                    "SELECT project_id,author_id,status FROM tasks WHERE id=?", (task_id,),
                ).fetchone()
                if not task or task["status"] not in ("queued", "running", "waiting_login"):
                    raise RuntimeError("task stopped before data summary commit")
                if project_id is not None and int(task["project_id"] or 0) != int(project_id):
                    raise ValueError("project data summary task scope mismatch")
                if author_id is not None and int(task["author_id"] or 0) != int(author_id):
                    raise ValueError("author data summary task scope mismatch")
            if project_id is not None:
                if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                    raise KeyError("project not found")
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM reports WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
                generator_version = conn.execute(
                    """SELECT COALESCE(MAX(generator_version),0)+1 FROM reports
                       WHERE project_id=? AND generator_type='template'""",
                    (project_id,),
                ).fetchone()[0]
                cur = conn.execute(
                    """INSERT INTO reports(
                           project_id,task_id,version,report_type,generator_type,generator_version,
                           status,title,summary_json,content_markdown,evidence_post_count,
                           evidence_author_count,model,prompt_version,evidence_snapshot_json,
                           generation_config_json,generated_at
                       ) VALUES(?,?,?,'data_summary','template',?,?,?,?,'',?,?,'','',
                                ?,?,?)""",
                    (
                        project_id, task_id, version, generator_version, task_status,
                        title, _json(summary),
                        post_count, author_count, _json(snapshot),
                        _json(generation_config), captured_at,
                    ),
                )
                report_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE projects SET latest_report_id=?,updated_at=? WHERE id=?",
                    (report_id, utcnow(), project_id),
                )
                if task_id is not None:
                    self._complete_task_for_data_summary(
                        conn, task_id, project_id, None, task_status,
                        task_result or summary, task_warning_count, completion_event,
                    )
                return report_id
            if not conn.execute("SELECT 1 FROM authors WHERE id=?", (author_id,)).fetchone():
                raise KeyError("author not found")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM author_reports WHERE author_id=?",
                (author_id,),
            ).fetchone()[0]
            generator_version = conn.execute(
                """SELECT COALESCE(MAX(generator_version),0)+1 FROM author_reports
                   WHERE author_id=? AND generator_type='template'""",
                (author_id,),
            ).fetchone()[0]
            cur = conn.execute(
                """INSERT INTO author_reports(
                       author_id,task_id,version,report_type,generator_type,generator_version,
                       status,title,summary_json,content_markdown,evidence_post_count,
                       evidence_author_count,model,prompt_version,evidence_snapshot_json,
                       generation_config_json,generated_at
                   ) VALUES(?,?,?,'data_summary','template',?,?,?,?,'',?,1,'','',
                            ?,?,?)""",
                (
                    author_id, task_id, version, generator_version, task_status,
                    title, _json(summary),
                    post_count, _json(snapshot), _json(generation_config), captured_at,
                ),
            )
            report_id = int(cur.lastrowid)
            if task_id is not None:
                self._complete_task_for_data_summary(
                    conn, task_id, None, author_id, task_status,
                    task_result or summary, task_warning_count, completion_event,
                )
            return report_id

    def _complete_task_for_data_summary(
        self, conn: sqlite3.Connection, task_id: str, project_id: Optional[int],
        author_id: Optional[int], status: str, result: Dict[str, Any], warning_count: int,
        completion_event: Optional[Dict[str, Any]],
    ) -> None:
        scope_sql = "project_id=?" if project_id is not None else "project_id IS NULL AND author_id=?"
        scope_id = project_id if project_id is not None else author_id
        completed = conn.execute(
            f"""UPDATE tasks SET status=?,current_phase='completed',warning_count=?,error_message='',
                   result_json=?,finished_at=? WHERE id=? AND {scope_sql}
                   AND status IN ('queued','running','waiting_login')""",
            (status, max(0, int(warning_count)), _json(result), utcnow(), task_id, scope_id),
        )
        if completed.rowcount != 1:
            raise RuntimeError("task stopped before data summary commit")
        conn.execute(
            """INSERT INTO task_events(task_id,phase,event_type,payload_json,created_at)
               VALUES(?,?,?,?,?)""",
            (
                task_id, "completed", status,
                _json(completion_event if completion_event is not None else {"summary": result}),
                utcnow(),
            ),
        )

    def list_projects(self):
        return self.query(
            """SELECT p.*,
               (SELECT COUNT(*) FROM project_posts pp WHERE pp.project_id=p.id) AS post_count,
               (SELECT COUNT(DISTINCT pa.author_id) FROM project_authors pa WHERE pa.project_id=p.id) AS author_count,
               (SELECT COUNT(*) FROM project_keywords pk WHERE pk.project_id=p.id) AS keyword_count,
               (SELECT COUNT(*) FROM reports r WHERE r.project_id=p.id) AS report_count,
               (SELECT status FROM tasks t WHERE t.project_id=p.id AND t.status!='cancelled' ORDER BY t.created_at DESC LIMIT 1) AS latest_task_status
               FROM projects p ORDER BY p.updated_at DESC"""
        )

    def list_posts(self):
        return self.query(
            """SELECT p.*,a.display_name AS author_name,a.author_id AS external_author_id,
               CAST({ocr_complete} AS INTEGER) AS has_ocr_result,
               {ocr_status} AS ocr_status,
               {media_local_path} AS media_local_path,
               {media_original_url} AS media_original_url,
               COUNT(DISTINCT pp.project_id) AS project_count
               FROM posts p LEFT JOIN authors a ON a.id=p.author_id
               LEFT JOIN project_posts pp ON pp.post_id=p.id
            GROUP BY p.id ORDER BY p.updated_at DESC,p.id DESC""".format(
                ocr_complete=_POST_OCR_COMPLETE_SQL,
                ocr_status=_POST_OCR_STATUS_SQL,
                media_local_path=_POST_LIST_MEDIA_LOCAL_PATH_SQL,
                media_original_url=_POST_LIST_MEDIA_ORIGINAL_URL_SQL,
            )
        )

    def list_posts_page(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str = "",
        note_type: str = "all",
        detail: str = "all",
        ocr: str = "all",
        vision: str = "all",
        sort: str = "default",
        exclude_project_id: Optional[int] = None,
        vision_model: str = "",
        vision_prompt_version: str = "",
    ):
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        where = []
        params: list = []
        normalized = str(query or "").strip().lower()
        if normalized:
            pattern = f"%{normalized}%"
            where.append(
                """(LOWER(p.title) LIKE ? OR LOWER(p.content) LIKE ?
                   OR LOWER(COALESCE(a.display_name,'')) LIKE ?
                   OR LOWER(COALESCE(a.author_id,'')) LIKE ? OR LOWER(p.note_id) LIKE ?)"""
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])
        if note_type == "image":
            where.append("p.note_type!='video'")
        elif note_type == "video":
            where.append("p.note_type='video'")
        if detail == "preview":
            where.append("p.detail_level='card'")
        elif detail == "detailed":
            where.append("p.detail_level!='card'")
        ocr_filter = _post_ocr_filter_sql(ocr)
        if ocr_filter:
            where.append(ocr_filter)
        if exclude_project_id is not None:
            where.append(
                "NOT EXISTS(SELECT 1 FROM project_posts excluded_pp "
                "WHERE excluded_pp.project_id=? AND excluded_pp.post_id=p.id)"
            )
            params.append(int(exclude_project_id))
        has_current_vision = bool(vision_model and vision_prompt_version)
        vision_exists = """EXISTS(
            SELECT 1 FROM vision_analyses va
            WHERE va.post_id=p.id AND va.model=? AND va.prompt_version=? AND va.is_current=1
        )"""
        if vision in ("yes", "no"):
            if has_current_vision:
                where.append(("" if vision == "yes" else "NOT ") + vision_exists)
                params.extend([vision_model, vision_prompt_version])
            elif vision == "yes":
                where.append("0")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(
            self.scalar(
                f"""SELECT COUNT(*) FROM posts p LEFT JOIN authors a ON a.id=p.author_id
                    {where_sql}""",
                params,
            )
            or 0
        )
        max_page = max(1, (total + page_size - 1) // page_size)
        page = min(page, max_page)
        sort_sql = {
            "likes_asc": "COALESCE(p.likes_count,0),p.id DESC",
            "likes_desc": "COALESCE(p.likes_count,0) DESC,p.id DESC",
            "favorites_asc": "COALESCE(p.favorites_count,0),p.id DESC",
            "favorites_desc": "COALESCE(p.favorites_count,0) DESC,p.id DESC",
            "comments_asc": "COALESCE(p.comments_count,0),p.id DESC",
            "comments_desc": "COALESCE(p.comments_count,0) DESC,p.id DESC",
            "published_asc": "p.publish_date,p.id DESC",
            "published_desc": "p.publish_date DESC,p.id DESC",
            "updated_asc": "p.updated_at,p.id DESC",
            "updated_desc": "p.updated_at DESC,p.id DESC",
            "title_asc": "p.title COLLATE NOCASE,p.id DESC",
            "title_desc": "p.title COLLATE NOCASE DESC,p.id DESC",
            "project_count_asc": "project_count,p.id DESC",
            "project_count_desc": "project_count DESC,p.id DESC",
        }.get(sort, "SUBSTR(p.note_id,1,8) DESC,p.note_id DESC")
        vision_select = "0"
        item_params: list = []
        if has_current_vision:
            vision_select = vision_exists
            item_params.extend([vision_model, vision_prompt_version])
        item_params.extend(params)
        item_params.extend([page_size, (page - 1) * page_size])
        items = self.query(
            f"""SELECT p.id,p.note_id,p.author_id,p.title,'' AS content,p.note_type,p.note_url,
                   p.cover_url,p.cover_local_path,p.publish_date,p.likes_count,p.favorites_count,
                   p.comments_count,p.detail_level,p.updated_at,p.last_seen_at,p.last_detail_fetched_at,
                   a.display_name AS author_name,a.author_id AS external_author_id,
                   (SELECT COUNT(*) FROM project_posts pp WHERE pp.post_id=p.id) AS project_count,
                   CAST({_POST_OCR_COMPLETE_SQL} AS INTEGER) AS has_ocr_result,
                   {_POST_OCR_STATUS_SQL} AS ocr_status,
                   CAST({vision_select} AS INTEGER) AS has_vision_result,
                   {_POST_LIST_MEDIA_LOCAL_PATH_SQL} AS media_local_path,
                   {_POST_LIST_MEDIA_ORIGINAL_URL_SQL} AS media_original_url
                FROM posts p LEFT JOIN authors a ON a.id=p.author_id
                {where_sql} ORDER BY {sort_sql} LIMIT ? OFFSET ?""",
            item_params,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def select_post_detail_update_candidates(
        self,
        scope: str,
        scope_id: Optional[int],
        target: str,
        max_posts: int,
        post_ids: Iterable[int] = (),
        detail_ttl_days: int = 30,
    ):
        scope = str(scope or "global")
        target = str(target or "needs_update")
        if scope not in ("global", "project", "author"):
            raise ValueError("scope must be global, project or author")
        if target not in ("needs_update", "preview", "all"):
            raise ValueError("target must be needs_update, preview or all")
        if scope != "global" and (scope_id is None or int(scope_id) <= 0):
            raise ValueError("project and author scopes require a positive scope_id")

        normalized_ids = list(dict.fromkeys(int(value) for value in post_ids))
        joins = ["LEFT JOIN authors a ON a.id=p.author_id"]
        clauses = []
        params = []
        if scope == "project":
            if not self.get_project(int(scope_id)):
                raise KeyError("project not found")
            joins.append("JOIN project_posts pp ON pp.post_id=p.id")
            clauses.append("pp.project_id=?")
            params.append(int(scope_id))
        elif scope == "author":
            if not self.get_author(int(scope_id)):
                raise KeyError("author not found")
            clauses.append("p.author_id=?")
            params.append(int(scope_id))

        if normalized_ids:
            placeholders = ",".join("?" for _ in normalized_ids)
            clauses.append(f"p.id IN ({placeholders})")
            params.extend(normalized_ids)
        elif target == "preview":
            clauses.append("p.detail_level='card'")
        elif target == "needs_update":
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(detail_ttl_days)))).isoformat()
            clauses.append(
                "(p.detail_level='card' OR p.last_detail_fetched_at IS NULL "
                "OR p.last_detail_fetched_at<?)"
            )
            params.append(cutoff)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.query(
            f"""SELECT p.*,a.display_name AS author_name,a.author_id AS external_author_id
                FROM posts p {' '.join(joins)} {where}
                ORDER BY CASE WHEN p.detail_level='card' THEN 0 ELSE 1 END,
                         COALESCE(p.last_detail_fetched_at,''),p.id
                LIMIT ?""",
            [*params, max(1, int(max_posts))],
        )
        if normalized_ids:
            found = {int(row["id"]) for row in rows}
            missing = [value for value in normalized_ids if value not in found]
            if missing:
                raise KeyError(f"posts not found in scope: {','.join(map(str, missing))}")
            order = {value: index for index, value in enumerate(normalized_ids)}
            rows.sort(key=lambda row: order[int(row["id"])])
        return rows

    def list_authors(self):
        return self.query(
            """SELECT a.*,COUNT(DISTINCT p.id) AS post_count,
               COUNT(DISTINCT p.id) AS stored_post_count,
               COUNT(DISTINCT pa.project_id) AS project_count
               FROM authors a LEFT JOIN posts p ON p.author_id=a.id
               LEFT JOIN project_authors pa ON pa.author_id=a.id
               GROUP BY a.id
               ORDER BY a.updated_at DESC,a.id DESC"""
        )

    def get_project(self, project_id: int):
        rows = self.query(
            """SELECT p.*,
               (SELECT COUNT(*) FROM project_posts pp WHERE pp.project_id=p.id) AS post_count,
               (SELECT COUNT(DISTINCT pa.author_id) FROM project_authors pa WHERE pa.project_id=p.id) AS author_count,
               (SELECT COUNT(*) FROM project_keywords pk WHERE pk.project_id=p.id) AS keyword_count,
               (SELECT COUNT(*) FROM reports r WHERE r.project_id=p.id) AS report_count,
               (SELECT status FROM tasks t WHERE t.project_id=p.id AND t.status!='cancelled'
                 ORDER BY t.created_at DESC LIMIT 1) AS latest_task_status
               FROM projects p WHERE p.id=?""",
            (project_id,),
        )
        return rows[0] if rows else None

    def list_project_keywords(self, project_id: int):
        return self.query(
            """SELECT id,project_id,keyword,source,created_at,updated_at
               FROM project_keywords WHERE project_id=?
               ORDER BY created_at DESC,id DESC""",
            (project_id,),
        )

    def add_project_keywords(self, project_id: int, keywords: Iterable[Any], source: str = "manual"):
        source = str(source or "manual").strip()
        if source not in ("manual", "ai_generated"):
            raise ValueError("source must be one of: manual, ai_generated")
        values = list(dict.fromkeys(_normalize_project_keyword(value) for value in keywords))
        if not values:
            raise ValueError("at least one keyword is required")
        if len(values) > 100:
            raise ValueError("cannot add more than 100 keywords at once")
        now = utcnow()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError("project not found")
            for keyword, normalized_keyword in values:
                conn.execute(
                    """INSERT INTO project_keywords(project_id,keyword,normalized_keyword,source,created_at,updated_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,normalized_keyword)
                       DO UPDATE SET
                         keyword=excluded.keyword,
                         source=CASE
                           WHEN project_keywords.source='manual' OR excluded.source='manual'
                             THEN 'manual'
                           ELSE 'ai_generated'
                         END,
                         updated_at=excluded.updated_at""",
                    (project_id, keyword, normalized_keyword, source, now, now),
                )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        return self.list_project_keywords(project_id)

    def remove_project_keywords(self, project_id: int, keyword_ids: Iterable[Any]):
        ids = list(dict.fromkeys(int(value) for value in keyword_ids))
        if not ids:
            raise ValueError("at least one keyword_id is required")
        if len(ids) > 100:
            raise ValueError("cannot remove more than 100 keywords at once")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError("project not found")
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM project_keywords WHERE project_id=? AND id IN ({placeholders})",
                (project_id, *ids),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (utcnow(), project_id))
        return self.list_project_keywords(project_id)

    def project_reference_ids(self, project_id: int):
        return {
            "post_ids": [
                int(row["post_id"])
                for row in self.query(
                    "SELECT post_id FROM project_posts WHERE project_id=? ORDER BY post_id",
                    (project_id,),
                )
            ],
            "author_ids": [
                int(row["author_id"])
                for row in self.query(
                    """SELECT DISTINCT author_id FROM project_authors
                       WHERE project_id=? ORDER BY author_id""",
                    (project_id,),
                )
            ],
        }

    def attach_project_references(
        self,
        project_id: int,
        post_ids: Iterable[int] = (),
        author_ids: Iterable[int] = (),
    ):
        normalized_post_ids = list(dict.fromkeys(int(value) for value in post_ids))
        normalized_author_ids = list(dict.fromkeys(int(value) for value in author_ids))
        if not normalized_post_ids and not normalized_author_ids:
            raise ValueError("at least one post_id or author_id is required")
        if len(normalized_post_ids) + len(normalized_author_ids) > 500:
            raise ValueError("cannot attach more than 500 references at once")

        now = utcnow()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError("project not found")

            post_rows = []
            if normalized_post_ids:
                placeholders = ",".join("?" for _ in normalized_post_ids)
                post_rows = conn.execute(
                    f"SELECT id,author_id FROM posts WHERE id IN ({placeholders})",
                    normalized_post_ids,
                ).fetchall()
                found = {int(row["id"]) for row in post_rows}
                missing = [value for value in normalized_post_ids if value not in found]
                if missing:
                    raise KeyError(f"posts not found: {','.join(map(str, missing))}")

            if normalized_author_ids:
                placeholders = ",".join("?" for _ in normalized_author_ids)
                found = {
                    int(row["id"])
                    for row in conn.execute(
                        f"SELECT id FROM authors WHERE id IN ({placeholders})",
                        normalized_author_ids,
                    ).fetchall()
                }
                missing = [value for value in normalized_author_ids if value not in found]
                if missing:
                    raise KeyError(f"authors not found: {','.join(map(str, missing))}")

            posts_before = int(conn.execute(
                "SELECT COUNT(*) FROM project_posts WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            authors_before = int(conn.execute(
                "SELECT COUNT(DISTINCT author_id) FROM project_authors WHERE project_id=?", (project_id,),
            ).fetchone()[0])

            for post in post_rows:
                conn.execute(
                    """INSERT INTO project_posts(project_id,post_id,first_seen_at,last_seen_at)
                       VALUES(?,?,?,?) ON CONFLICT(project_id,post_id)
                       DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                    (project_id, int(post["id"]), now, now),
                )
                if post["author_id"] is not None:
                    conn.execute(
                        """INSERT INTO project_authors(
                               project_id,author_id,relation_type,first_seen_at,last_seen_at
                           ) VALUES(?,?,?,?,?)
                           ON CONFLICT(project_id,author_id,relation_type)
                           DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                        (project_id, int(post["author_id"]), "post_author", now, now),
                    )

            for author_id in normalized_author_ids:
                conn.execute(
                    """INSERT INTO project_authors(
                           project_id,author_id,relation_type,first_seen_at,last_seen_at
                       ) VALUES(?,?,?,?,?)
                       ON CONFLICT(project_id,author_id,relation_type)
                       DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                    (project_id, author_id, "manual", now, now),
                )

            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            post_count = int(conn.execute(
                "SELECT COUNT(*) FROM project_posts WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            author_count = int(conn.execute(
                "SELECT COUNT(DISTINCT author_id) FROM project_authors WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            return {
                "project_id": project_id,
                "post_ids": normalized_post_ids,
                "author_ids": normalized_author_ids,
                "added_post_count": post_count - posts_before,
                "added_author_count": author_count - authors_before,
                "post_count": post_count,
                "author_count": author_count,
            }

    def detach_project_references(
        self,
        project_id: int,
        post_ids: Iterable[int] = (),
        author_ids: Iterable[int] = (),
        confirm_remove_author_posts: bool = False,
    ):
        normalized_post_ids = list(dict.fromkeys(int(value) for value in post_ids))
        normalized_author_ids = list(dict.fromkeys(int(value) for value in author_ids))
        if not normalized_post_ids and not normalized_author_ids:
            raise ValueError("at least one post_id or author_id is required")
        if len(normalized_post_ids) + len(normalized_author_ids) > 500:
            raise ValueError("cannot detach more than 500 references at once")

        now = utcnow()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError("project not found")

            if normalized_post_ids:
                placeholders = ",".join("?" for _ in normalized_post_ids)
                found = {
                    int(row["id"])
                    for row in conn.execute(
                        f"SELECT id FROM posts WHERE id IN ({placeholders})",
                        normalized_post_ids,
                    ).fetchall()
                }
                missing = [value for value in normalized_post_ids if value not in found]
                if missing:
                    raise KeyError(f"posts not found: {','.join(map(str, missing))}")

            if normalized_author_ids:
                placeholders = ",".join("?" for _ in normalized_author_ids)
                author_rows = conn.execute(
                    f"""SELECT id,author_id,display_name FROM authors
                        WHERE id IN ({placeholders})""",
                    normalized_author_ids,
                ).fetchall()
                found = {int(row["id"]) for row in author_rows}
                missing = [value for value in normalized_author_ids if value not in found]
                if missing:
                    raise KeyError(f"authors not found: {','.join(map(str, missing))}")

                post_count_rows = conn.execute(
                    f"""SELECT a.id,a.author_id,a.display_name,COUNT(DISTINCT pp.post_id) AS project_post_count
                        FROM authors a
                        JOIN posts p ON p.author_id=a.id
                        JOIN project_posts pp ON pp.post_id=p.id AND pp.project_id=?
                        WHERE a.id IN ({placeholders})
                        GROUP BY a.id
                        HAVING project_post_count > 0
                        ORDER BY project_post_count DESC,a.display_name,a.author_id""",
                    [project_id, *normalized_author_ids],
                ).fetchall()
                if post_count_rows and not confirm_remove_author_posts:
                    authors = [
                        {
                            "id": int(row["id"]),
                            "name": row["display_name"] or row["author_id"] or f"作者 #{row['id']}",
                            "project_post_count": int(row["project_post_count"] or 0),
                        }
                        for row in post_count_rows
                    ]
                    total_post_count = sum(int(value["project_post_count"]) for value in authors)
                    raise ProjectReferenceConflict(
                        "selected authors still have posts in this project",
                        {
                            "code": "author_has_project_posts",
                            "error": "选中的作者在本项目下仍有帖子",
                            "authors": authors,
                            "total_post_count": total_post_count,
                        },
                    )

            posts_before = int(conn.execute(
                "SELECT COUNT(*) FROM project_posts WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            authors_before = int(conn.execute(
                "SELECT COUNT(DISTINCT author_id) FROM project_authors WHERE project_id=?", (project_id,),
            ).fetchone()[0])

            affected_author_ids = set()
            if normalized_post_ids:
                placeholders = ",".join("?" for _ in normalized_post_ids)
                for row in conn.execute(
                    f"""SELECT DISTINCT p.author_id FROM project_posts pp
                        JOIN posts p ON p.id=pp.post_id
                        WHERE pp.project_id=? AND pp.post_id IN ({placeholders})
                          AND p.author_id IS NOT NULL""",
                    [project_id, *normalized_post_ids],
                ).fetchall():
                    affected_author_ids.add(int(row["author_id"]))
                conn.execute(
                    f"DELETE FROM project_posts WHERE project_id=? AND post_id IN ({placeholders})",
                    [project_id, *normalized_post_ids],
                )

            if normalized_author_ids:
                placeholders = ",".join("?" for _ in normalized_author_ids)
                affected_author_ids.update(normalized_author_ids)
                if confirm_remove_author_posts:
                    conn.execute(
                        f"""DELETE FROM project_posts
                            WHERE project_id=? AND post_id IN (
                                SELECT id FROM posts WHERE author_id IN ({placeholders})
                            )""",
                        [project_id, *normalized_author_ids],
                    )
                conn.execute(
                    f"""DELETE FROM project_authors
                        WHERE project_id=? AND author_id IN ({placeholders})""",
                    [project_id, *normalized_author_ids],
                )

            if affected_author_ids:
                placeholders = ",".join("?" for _ in affected_author_ids)
                conn.execute(
                    f"""DELETE FROM project_authors
                        WHERE project_id=? AND relation_type IN ('post_author','keyword_post_author')
                          AND author_id IN ({placeholders})
                          AND NOT EXISTS (
                              SELECT 1 FROM project_posts pp
                              JOIN posts p ON p.id=pp.post_id
                              WHERE pp.project_id=project_authors.project_id
                                AND p.author_id=project_authors.author_id
                          )""",
                    [project_id, *affected_author_ids],
                )

            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
            post_count = int(conn.execute(
                "SELECT COUNT(*) FROM project_posts WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            author_count = int(conn.execute(
                "SELECT COUNT(DISTINCT author_id) FROM project_authors WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            return {
                "project_id": project_id,
                "post_ids": normalized_post_ids,
                "author_ids": normalized_author_ids,
                "removed_post_count": posts_before - post_count,
                "removed_author_count": authors_before - author_count,
                "post_count": post_count,
                "author_count": author_count,
            }

    def delete_project(
        self,
        project_id: int,
        require_empty: bool = False,
        _after_guard: Optional[Callable[[], None]] = None,
    ):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                return None
            task_count = int(conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id=?", (project_id,),
            ).fetchone()[0])
            if require_empty and task_count:
                raise ProjectDeleteConflict(
                    "project has tasks and cannot be removed by empty-project cleanup"
                )
            active_count = int(conn.execute(
                """SELECT COUNT(*) FROM tasks WHERE project_id=?
                   AND status IN ('queued','running','waiting_login')""",
                (project_id,),
            ).fetchone()[0])
            if active_count:
                raise ProjectDeleteConflict("project has an active task")
            summary = {
                "deleted_project_id": project_id,
                "name": project["name"],
                "deleted_tasks": 0,
                "detached_tasks": task_count,
                "deleted_project_posts": int(conn.execute(
                    "SELECT COUNT(*) FROM project_posts WHERE project_id=?", (project_id,),
                ).fetchone()[0]),
                "deleted_project_authors": int(conn.execute(
                    "SELECT COUNT(*) FROM project_authors WHERE project_id=?", (project_id,),
                ).fetchone()[0]),
                "deleted_reports": int(conn.execute(
                    "SELECT COUNT(*) FROM reports WHERE project_id=?", (project_id,),
                ).fetchone()[0]),
                "global_entities_preserved": True,
            }
            if _after_guard is not None:
                _after_guard()
            conn.execute("UPDATE tasks SET project_id=NULL WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return summary

    def list_project_posts(self, project_id: int):
        return self.query(
            """WITH source_values AS (
                   SELECT tp.post_id,GROUP_CONCAT(DISTINCT tp.source_value) AS sources
                   FROM task_posts tp JOIN tasks t ON t.id=tp.task_id
                   WHERE t.project_id=? GROUP BY tp.post_id
               )
               SELECT p.*, a.display_name AS author_name, a.author_id AS external_author_id,
               pp.popularity_score,pp.popularity_percentile,pp.popularity_level,pp.popularity_method,
               CAST({ocr_complete} AS INTEGER) AS has_ocr_result,
               {ocr_status} AS ocr_status,
               0 AS has_vision_result,
               {media_local_path} AS media_local_path,
               {media_original_url} AS media_original_url,
               source_values.sources
               FROM project_posts pp JOIN posts p ON p.id=pp.post_id LEFT JOIN authors a ON a.id=p.author_id
               LEFT JOIN source_values ON source_values.post_id=p.id
               WHERE pp.project_id=? ORDER BY COALESCE(pp.popularity_percentile,0) DESC,p.last_seen_at DESC""".format(
                ocr_complete=_POST_OCR_COMPLETE_SQL,
                ocr_status=_POST_OCR_STATUS_SQL,
                media_local_path=_POST_LIST_MEDIA_LOCAL_PATH_SQL,
                media_original_url=_POST_LIST_MEDIA_ORIGINAL_URL_SQL,
            ),
            (project_id, project_id),
        )

    def list_project_posts_page(
        self,
        project_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str = "",
        note_type: str = "all",
        detail: str = "all",
        ocr: str = "all",
        vision: str = "all",
        media_storage: str = "all",
        popularity: str = "all",
        sort: str = "default",
        vision_model: str = "",
        vision_prompt_version: str = "",
    ):
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        where = ["pp.project_id=?"]
        params: list = [project_id]
        normalized = str(query or "").strip().lower()
        if normalized:
            pattern = f"%{normalized}%"
            where.append(
                """(LOWER(p.title) LIKE ? OR LOWER(p.content) LIKE ?
                   OR LOWER(COALESCE(a.display_name,'')) LIKE ?
                   OR LOWER(COALESCE(a.author_id,'')) LIKE ? OR LOWER(p.note_id) LIKE ?
                   OR EXISTS(
                       SELECT 1 FROM task_posts tp JOIN tasks t ON t.id=tp.task_id
                       WHERE tp.post_id=p.id AND t.project_id=?
                         AND LOWER(tp.source_value) LIKE ?
                   ))"""
            )
            params.extend([pattern, pattern, pattern, pattern, pattern, project_id, pattern])
        if note_type == "image":
            where.append("p.note_type!='video'")
        elif note_type == "video":
            where.append("p.note_type='video'")
        if detail == "preview":
            where.append("p.detail_level='card'")
        elif detail == "detailed":
            where.append("p.detail_level!='card'")
        ocr_filter = _post_ocr_filter_sql(ocr)
        if ocr_filter:
            where.append(ocr_filter)
        media_storage_filter = _post_media_storage_filter_sql(media_storage)
        if media_storage_filter:
            where.append(media_storage_filter)
        if popularity and popularity != "all":
            where.append("COALESCE(pp.popularity_level,'')=?")
            params.append(popularity)
        has_current_vision = bool(vision_model and vision_prompt_version)
        vision_exists = """EXISTS(
            SELECT 1 FROM vision_analyses va
            WHERE va.post_id=p.id AND va.model=? AND va.prompt_version=? AND va.is_current=1
        )"""
        if vision in ("yes", "no"):
            if has_current_vision:
                where.append(("" if vision == "yes" else "NOT ") + vision_exists)
                params.extend([vision_model, vision_prompt_version])
            elif vision == "yes":
                where.append("0")
        where_sql = " AND ".join(where)
        total = int(
            self.scalar(
                f"""SELECT COUNT(*) FROM project_posts pp
                    JOIN posts p ON p.id=pp.post_id LEFT JOIN authors a ON a.id=p.author_id
                    WHERE {where_sql}""",
                params,
            )
            or 0
        )
        max_page = max(1, (total + page_size - 1) // page_size)
        page = min(page, max_page)
        sort_sql = {
            "likes_asc": "COALESCE(p.likes_count,0),p.id DESC",
            "likes_desc": "COALESCE(p.likes_count,0) DESC,p.id DESC",
            "favorites_asc": "COALESCE(p.favorites_count,0),p.id DESC",
            "favorites_desc": "COALESCE(p.favorites_count,0) DESC,p.id DESC",
            "comments_asc": "COALESCE(p.comments_count,0),p.id DESC",
            "comments_desc": "COALESCE(p.comments_count,0) DESC,p.id DESC",
            "published_asc": "p.publish_date,p.id DESC",
            "published_desc": "p.publish_date DESC,p.id DESC",
            "updated_asc": "p.updated_at,p.id DESC",
            "updated_desc": "p.updated_at DESC,p.id DESC",
            "title_asc": "p.title COLLATE NOCASE,p.id DESC",
            "title_desc": "p.title COLLATE NOCASE DESC,p.id DESC",
            "popularity_asc": "COALESCE(pp.popularity_percentile,0),p.id DESC",
            "popularity_desc": "COALESCE(pp.popularity_percentile,0) DESC,p.id DESC",
            "attention_asc": (
                "CASE WHEN attention_ranked.attention_score IS NULL THEN 1 ELSE 0 END,"
                "attention_ranked.attention_metric,p.id DESC"
            ),
            "attention_desc": (
                "CASE WHEN attention_ranked.attention_score IS NULL THEN 1 ELSE 0 END,"
                "attention_ranked.attention_metric DESC,p.id DESC"
            ),
        }.get(sort, "SUBSTR(p.note_id,1,8) DESC,p.note_id DESC")
        vision_select = "0"
        item_params: list = [project_id, project_id, project_id]
        if has_current_vision:
            vision_select = vision_exists
            item_params.extend([vision_model, vision_prompt_version])
        item_params.extend(params)
        item_params.extend([page_size, (page - 1) * page_size])
        items = self.query(
            f"""WITH source_values AS (
                    SELECT tp.post_id,GROUP_CONCAT(DISTINCT tp.source_value) AS sources
                    FROM task_posts tp JOIN tasks t ON t.id=tp.task_id
                    WHERE t.project_id=? GROUP BY tp.post_id
                ), attention_valid AS (
                    SELECT p.id AS post_id,
                       CAST(p.likes_count + p.favorites_count + p.comments_count AS REAL)
                           AS interactions,
                       CAST(MAX(a.followers_count,0) AS REAL) AS followers
                    FROM project_posts attention_pp
                    JOIN posts p ON p.id=attention_pp.post_id
                    LEFT JOIN authors a ON a.id=p.author_id
                    WHERE attention_pp.project_id=?
                      AND p.likes_count IS NOT NULL
                      AND p.favorites_count IS NOT NULL
                      AND p.comments_count IS NOT NULL
                      AND a.followers_count IS NOT NULL
                ), attention_authors AS (
                    SELECT DISTINCT p.author_id,
                       CAST(MAX(a.followers_count,0) AS REAL) AS followers
                    FROM project_posts attention_pp
                    JOIN posts p ON p.id=attention_pp.post_id
                    JOIN authors a ON a.id=p.author_id
                    WHERE attention_pp.project_id=? AND a.followers_count IS NOT NULL
                ), attention_author_ordered AS (
                    SELECT followers,
                       ROW_NUMBER() OVER (ORDER BY followers) AS rn,
                       COUNT(*) OVER () AS cnt
                    FROM attention_authors
                ), attention_post_ordered AS (
                    SELECT interactions,
                       ROW_NUMBER() OVER (ORDER BY interactions) AS rn,
                       COUNT(*) OVER () AS cnt
                    FROM attention_valid
                ), attention_coefficients AS (
                    SELECT
                       MAX(
                           {FOLLOWER_SMOOTHING_MIN},
                           COALESCE((
                               SELECT AVG(followers) FROM attention_author_ordered
                               WHERE rn IN ((cnt+1)/2,(cnt+2)/2)
                           ), {FOLLOWER_SMOOTHING_MIN})
                       ) AS follower_smoothing,
                       MAX(
                           {INTERACTION_SMOOTHING_MIN},
                           COALESCE((
                               SELECT AVG(interactions) FROM attention_post_ordered
                               WHERE rn IN ((cnt+1)/2,(cnt+2)/2)
                           ), {INTERACTION_SMOOTHING_MIN})
                       ) AS interaction_smoothing
                ), attention_metrics AS (
                    SELECT attention_valid.post_id,
                       1000.0 * interactions / (followers + follower_smoothing)
                           * interactions / (interactions + interaction_smoothing)
                           AS attention_metric
                    FROM attention_valid CROSS JOIN attention_coefficients
                ), attention_ranked AS (
                    SELECT post_id,attention_metric,
                       CAST(ROUND(
                           100.0 * CUME_DIST() OVER (ORDER BY attention_metric)
                       ) AS INTEGER) AS attention_score
                    FROM attention_metrics
                )
                SELECT p.id,p.note_id,p.author_id,p.title,'' AS content,p.note_type,p.note_url,
                   p.cover_url,p.cover_local_path,p.publish_date,p.likes_count,p.favorites_count,
                   p.comments_count,p.detail_level,p.updated_at,p.last_seen_at,p.last_detail_fetched_at,
                   a.display_name AS author_name,a.author_id AS external_author_id,
                   a.followers_count AS author_followers_count,
                   attention_ranked.attention_score,
                   pp.popularity_score,pp.popularity_percentile,pp.popularity_level,pp.popularity_method,
                   CAST({_POST_OCR_COMPLETE_SQL} AS INTEGER) AS has_ocr_result,
                   {_POST_OCR_STATUS_SQL} AS ocr_status,
                   {_POST_MEDIA_STORAGE_STATUS_SQL} AS media_storage_status,
                   CAST({vision_select} AS INTEGER) AS has_vision_result,
                   {_POST_LIST_MEDIA_LOCAL_PATH_SQL} AS media_local_path,
                   {_POST_LIST_MEDIA_ORIGINAL_URL_SQL} AS media_original_url,
                   source_values.sources
                FROM project_posts pp JOIN posts p ON p.id=pp.post_id
                LEFT JOIN authors a ON a.id=p.author_id
                LEFT JOIN source_values ON source_values.post_id=p.id
                LEFT JOIN attention_ranked ON attention_ranked.post_id=p.id
                WHERE {where_sql} ORDER BY {sort_sql} LIMIT ? OFFSET ?""",
            item_params,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def project_post_coverage(self, project_id: int):
        """Return project-wide post completeness counts for the posts workspace."""
        row = self.query(
            f"""SELECT
                   COUNT(*) AS total,
                   COUNT(CASE WHEN p.detail_level!='card' THEN 1 END) AS detailed,
                   COUNT(CASE WHEN p.detail_level='card' THEN 1 END) AS preview,
                   COUNT(CASE WHEN {_POST_OCR_COMPLETE_SQL} THEN 1 END) AS ocr_completed,
                   COUNT(CASE WHEN {_POST_OCR_PENDING_SQL} THEN 1 END) AS ocr_pending,
                   COUNT(CASE WHEN NOT {_POST_OCR_COMPLETE_SQL}
                                      AND NOT {_POST_OCR_PENDING_SQL} THEN 1 END) AS ocr_other
                FROM project_posts pp JOIN posts p ON p.id=pp.post_id
                WHERE pp.project_id=?""",
            (project_id,),
        )[0]
        value = self._row(row)
        value["ocr_available"] = value["ocr_completed"] + value["ocr_pending"]
        return value

    def project_status_counts(
        self,
        project_id: int,
        vision_model: str = "",
        vision_prompt_version: str = "",
    ):
        vision_params: list = []
        vision_condition = "0"
        if vision_model and vision_prompt_version:
            vision_condition = """EXISTS(
                SELECT 1 FROM vision_analyses va
                WHERE va.post_id=pp.post_id AND va.model=? AND va.prompt_version=?
                  AND va.is_current=1
            )"""
            vision_params = [vision_model, vision_prompt_version]
        ocr_complete = _POST_OCR_COMPLETE_SQL.replace("p.id", "post.id")
        rows = self.query(
            f"""SELECT
                   (SELECT COUNT(*) FROM project_posts pp WHERE pp.project_id=p.id)
                     AS post_count,
                   (SELECT COUNT(DISTINCT pa.author_id) FROM project_authors pa
                     WHERE pa.project_id=p.id) AS author_count,
                   (SELECT COUNT(*) FROM project_posts pp
                     JOIN posts post ON post.id=pp.post_id
                     WHERE pp.project_id=p.id AND {ocr_complete}) AS ocr_post_count,
                   (SELECT COUNT(DISTINCT pp.post_id) FROM project_posts pp
                     JOIN media_assets m ON m.post_id=pp.post_id
                     WHERE pp.project_id=p.id AND m.local_path!=''
                       AND m.download_status='downloaded') AS available_posts,
                   (SELECT COUNT(*) FROM project_posts pp
                     WHERE pp.project_id=p.id AND {vision_condition}) AS vision_post_count
                FROM projects p WHERE p.id=?""",
            (*vision_params, project_id),
        )
        return rows[0] if rows else None

    def list_task_posts(self, task_id: str):
        return self.query(
            """SELECT p.*,a.display_name AS author_name,a.author_id AS external_author_id,
               MIN(tp.source_rank) AS source_rank,
               GROUP_CONCAT(DISTINCT tp.source_value) AS sources
               FROM task_posts tp JOIN posts p ON p.id=tp.post_id
               LEFT JOIN authors a ON a.id=p.author_id
               WHERE tp.task_id=? GROUP BY p.id
               ORDER BY COALESCE(MIN(tp.source_rank),999999),p.last_seen_at DESC,p.id DESC""",
            (task_id,),
        )

    def list_task_authors(self, task_id: str):
        return self.query(
            """SELECT a.*,COUNT(DISTINCT tp.post_id) AS task_post_count
               FROM task_posts tp JOIN posts p ON p.id=tp.post_id
               JOIN authors a ON a.id=p.author_id
               WHERE tp.task_id=? GROUP BY a.id
               ORDER BY task_post_count DESC,a.followers_count DESC,a.id DESC""",
            (task_id,),
        )

    def list_project_media_for_vision(self, project_id: int):
        return self.query(
            """SELECT m.post_id,m.media_index,m.media_type,m.local_path,m.sha256,m.ocr_text
               FROM media_assets m JOIN project_posts pp ON pp.post_id=m.post_id
               WHERE pp.project_id=? AND m.local_path!=''
               ORDER BY m.post_id,m.media_index,m.id""",
            (project_id,),
        )

    def list_project_media_for_ocr(self, project_id: int):
        return self.query(
            """SELECT m.id,m.post_id,m.media_index,m.media_type,m.local_path,m.ocr_completed_at,
                      m.ocr_engine,m.ocr_version
               FROM media_assets m JOIN project_posts pp ON pp.post_id=m.post_id
               WHERE pp.project_id=? AND m.local_path!=''
               ORDER BY m.post_id,m.media_index,m.id""",
            (project_id,),
        )

    def list_project_vision_cache(self, project_id: int, model: str, prompt_version: str):
        return self.query(
            """SELECT va.* FROM vision_analyses va
               JOIN project_posts pp ON pp.post_id=va.post_id
               WHERE pp.project_id=? AND va.model=? AND va.prompt_version=?
               ORDER BY va.analyzed_at DESC,va.id DESC""",
            (project_id, model, prompt_version),
        )

    def list_post_media_for_vision(self, post_id: int):
        return self.query(
            """SELECT post_id,media_index,media_type,local_path,ocr_text FROM media_assets
               WHERE post_id=? AND local_path!='' ORDER BY media_index,id""",
            (post_id,),
        )

    def list_post_vision_cache(self, post_id: int, model: str, prompt_version: str):
        return self.query(
            """SELECT * FROM vision_analyses
               WHERE post_id=? AND model=? AND prompt_version=?
               ORDER BY analyzed_at DESC,id DESC""",
            (post_id, model, prompt_version),
        )

    def list_global_media_for_vision(self):
        return self.query(
            """SELECT post_id,media_index,media_type,local_path,sha256,ocr_text FROM media_assets
               WHERE local_path!='' ORDER BY post_id,media_index,id"""
        )

    def list_global_vision_cache(self, model: str, prompt_version: str):
        return self.query(
            """SELECT * FROM vision_analyses WHERE model=? AND prompt_version=?
               ORDER BY analyzed_at DESC,id DESC""",
            (model, prompt_version),
        )

    def list_author_media_for_vision(self, author_id: int):
        return self.query(
            """SELECT m.post_id,m.media_index,m.media_type,m.local_path,m.sha256,m.ocr_text
               FROM media_assets m JOIN posts p ON p.id=m.post_id
               WHERE p.author_id=? AND m.local_path!=''
               ORDER BY m.post_id,m.media_index,m.id""",
            (author_id,),
        )

    def list_author_media_for_ocr(self, author_id: int):
        return self.query(
            """SELECT m.id,m.post_id,m.media_index,m.media_type,m.local_path,m.ocr_completed_at,
                      m.ocr_engine,m.ocr_version
               FROM media_assets m JOIN posts p ON p.id=m.post_id
               WHERE p.author_id=? AND m.local_path!=''
               ORDER BY m.post_id,m.media_index,m.id""",
            (author_id,),
        )

    def list_author_vision_cache(
        self,
        author_id: int,
        model: str,
        prompt_version: str,
    ):
        return self.query(
            """SELECT va.* FROM vision_analyses va JOIN posts p ON p.id=va.post_id
               WHERE p.author_id=? AND va.model=? AND va.prompt_version=?
               ORDER BY va.analyzed_at DESC,va.id DESC""",
            (author_id, model, prompt_version),
        )

    def get_vision_analysis_cache(self, cache_keys, model: str, prompt_version: str):
        keys = list(dict.fromkeys(str(value) for value in cache_keys if value))
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self.query(
            f"""SELECT cache_key,analysis_json FROM vision_analyses
                WHERE model=? AND prompt_version=? AND cache_key IN ({placeholders})
                ORDER BY analyzed_at DESC,id DESC""",
            (model, prompt_version, *keys),
        )
        result = {}
        for row in rows:
            if isinstance(row.get("analysis_json"), dict):
                result.setdefault(row["cache_key"], row["analysis_json"])
        return result

    def save_current_vision_analysis(
        self,
        post_id: int,
        cache_key: str,
        model: str,
        prompt_version: str,
        analysis: Dict[str, Any],
        image_scope: str = "all",
    ):
        with self.connect() as conn:
            conn.execute(
                """UPDATE vision_analyses SET is_current=0
                   WHERE post_id=? AND model=? AND prompt_version=? AND image_scope=?""",
                (post_id, model, prompt_version, image_scope),
            )
            conn.execute(
                """INSERT INTO vision_analyses(
                       post_id,cache_key,model,prompt_version,image_scope,analysis_json,analyzed_at,is_current
                   ) VALUES(?,?,?,?,?,?,?,1)
                   ON CONFLICT(post_id,cache_key) DO UPDATE SET
                     model=excluded.model,prompt_version=excluded.prompt_version,
                     image_scope=excluded.image_scope,
                     analysis_json=excluded.analysis_json,analyzed_at=excluded.analyzed_at,
                     is_current=1""",
                (
                    post_id,
                    cache_key,
                    model,
                    prompt_version,
                    image_scope,
                    _json(analysis),
                    utcnow(),
                ),
            )

    def capture_report_evidence(
        self,
        project_id: int,
        _after_snapshot_started: Optional[Callable[[], None]] = None,
        vision_model: str = "",
        vision_prompt_version: str = "",
        vision_cache_key: Optional[Callable[[list], str]] = None,
    ):
        """Read every report input from one WAL snapshot.

        The optional private hook exists for deterministic concurrency regression
        tests; production callers leave it unset.
        """
        with self.connect() as conn:
            conn.execute("BEGIN")
            project_row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project_row:
                raise KeyError("project not found")
            # The first SELECT above establishes the read snapshot. Anything a
            # concurrent vision task commits after this timestamp is excluded.
            captured_at = utcnow()
            if _after_snapshot_started is not None:
                _after_snapshot_started()

            post_rows = conn.execute(
                """SELECT p.*, a.display_name AS author_name, a.author_id AS external_author_id,
                   pp.popularity_score,pp.popularity_percentile,pp.popularity_level,pp.popularity_method,
                   0 AS has_vision_result,
                   (SELECT local_path FROM media_assets m WHERE m.post_id=p.id ORDER BY media_index LIMIT 1) AS media_local_path,
                   (SELECT GROUP_CONCAT(DISTINCT source_value) FROM task_posts tp JOIN tasks t ON t.id=tp.task_id
                     WHERE tp.post_id=p.id AND t.project_id=?) AS sources
                   FROM project_posts pp JOIN posts p ON p.id=pp.post_id LEFT JOIN authors a ON a.id=p.author_id
                   WHERE pp.project_id=? ORDER BY COALESCE(pp.popularity_percentile,0) DESC,p.last_seen_at DESC""",
                (project_id, project_id),
            ).fetchall()
            media_rows = conn.execute(
                """SELECT m.post_id,m.media_index,m.media_type,m.local_path,m.original_url,m.download_status,
                          m.ocr_text,m.ocr_completed_at,m.updated_at
                   FROM media_assets m
                   JOIN project_posts pp ON pp.post_id=m.post_id
                   WHERE pp.project_id=? ORDER BY m.post_id,m.media_index,m.id""",
                (project_id,),
            ).fetchall()
            vision_rows = []
            if vision_cache_key is not None and vision_model and vision_prompt_version:
                vision_rows = conn.execute(
                    """SELECT va.* FROM vision_analyses va
                       JOIN project_posts pp ON pp.post_id=va.post_id
                       WHERE pp.project_id=? AND va.model=? AND va.prompt_version=?
                       ORDER BY va.analyzed_at DESC,va.id DESC""",
                    (project_id, vision_model, vision_prompt_version),
                ).fetchall()
            author_rows = conn.execute(
                """SELECT a.*,GROUP_CONCAT(DISTINCT pa.relation_type) AS relation_type,
                   COUNT(DISTINCT pp.post_id) AS project_post_count,
                   COUNT(DISTINCT CASE WHEN COALESCE(pp.popularity_percentile, 0) >= 0.7 THEN pp.post_id END) AS hot_post_count,
                   MAX(COALESCE(pp.popularity_percentile, 0)) AS peak_popularity_percentile
                   FROM project_authors pa JOIN authors a ON a.id=pa.author_id
                   LEFT JOIN posts p ON p.author_id=a.id LEFT JOIN project_posts pp ON pp.post_id=p.id AND pp.project_id=pa.project_id
                   WHERE pa.project_id=? GROUP BY a.id
                   ORDER BY hot_post_count DESC,peak_popularity_percentile DESC,project_post_count DESC,a.followers_count DESC""",
                (project_id,),
            ).fetchall()

            ocr_by_post: Dict[int, list] = {}
            media_by_post: Dict[int, list] = {}
            for row in media_rows:
                ocr_by_post.setdefault(int(row["post_id"]), []).append(row["ocr_text"] or "")
                media_by_post.setdefault(int(row["post_id"]), []).append(dict(row))
            current_vision = _current_vision_by_scope(
                media_rows, vision_rows, self.path.parent, vision_cache_key,
            )

            posts = []
            for row in post_rows:
                post = self._row(row)
                post_id = int(post["id"])
                post["ocr_text"] = "\n".join(ocr_by_post.get(post_id, [])).strip()
                scoped_states = {
                    scope: current_vision[scope].get(post_id) or {}
                    for scope in current_vision
                }
                scoped_results = [
                    result
                    for scope in IMAGE_SCOPES
                    for result in (scoped_states[scope].get("vision_results") or [])
                ]
                post["vision_results"] = scoped_results or (
                    scoped_states["all"].get("vision_results") or []
                )
                post["has_vision_result"] = int(bool(post["vision_results"]))
                post_media = media_by_post.get(post_id, [])
                local_media = [item for item in post_media if str(item.get("local_path") or "")]
                local_cover_media = [
                    item for item in local_media if media_matches_scope(item.get("media_type"), "cover")
                ]
                local_detail_media = [
                    item for item in local_media if media_matches_scope(item.get("media_type"), "detail")
                ]
                post["media_count"] = len(post_media)
                post["local_media_count"] = len(local_media)
                post["cover_media_count"] = sum(
                    media_matches_scope(item.get("media_type"), "cover") for item in post_media
                )
                post["detail_media_count"] = sum(
                    media_matches_scope(item.get("media_type"), "detail") for item in post_media
                )
                post["local_cover_media_count"] = len(local_cover_media)
                post["local_detail_media_count"] = len(local_detail_media)
                post["ocr_completed_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_media
                )
                post["ocr_completed_cover_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_cover_media
                )
                post["ocr_completed_detail_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_detail_media
                )
                post["has_detail"] = str(post.get("detail_level") or "card") != "card"
                post["has_ocr_result"] = int(
                    bool(local_media) and all(item.get("ocr_completed_at") for item in local_media)
                )
                post["ocr_status"] = (
                    "completed" if post["has_ocr_result"]
                    else "pending" if local_media
                    else "other"
                )
                post["last_ocr_at"] = max(
                    (str(item.get("ocr_completed_at")) for item in local_media if item.get("ocr_completed_at")),
                    default=None,
                )
                vision_rows_for_post = [
                    row
                    for state in scoped_states.values()
                    for row in (state.get("vision_rows") or [])
                ]
                post["last_vision_at"] = max(
                    (str(row.get("analyzed_at")) for row in vision_rows_for_post if row.get("analyzed_at")),
                    default=None,
                )
                all_analyzed = bool(scoped_states["all"].get("analyzed"))
                cover_analyzed = all_analyzed or bool(scoped_states["cover"].get("analyzed"))
                detail_analyzed = all_analyzed or bool(scoped_states["detail"].get("analyzed"))
                post["vision_analyzed_cover_media_count"] = (
                    len(local_cover_media) if cover_analyzed else 0
                )
                post["vision_analyzed_detail_media_count"] = (
                    len(local_detail_media) if detail_analyzed else 0
                )
                post["vision_analyzed_media_count"] = (
                    post["vision_analyzed_cover_media_count"]
                    + post["vision_analyzed_detail_media_count"]
                )
                posts.append(post)
            return {
                "captured_at": captured_at,
                "project": self._row(project_row),
                "posts": posts,
                "authors": [self._row(row) for row in author_rows],
                "keywords": [
                    self._row(row) for row in conn.execute(
                        """SELECT id,project_id,keyword,source,created_at,updated_at
                           FROM project_keywords WHERE project_id=? ORDER BY created_at DESC,id DESC""",
                        (project_id,),
                    ).fetchall()
                ],
                "tasks": [
                    self._row(row) for row in conn.execute(
                        """SELECT * FROM tasks WHERE project_id=? AND status!='cancelled'
                           ORDER BY created_at DESC""",
                        (project_id,),
                    ).fetchall()
                ],
            }

    def capture_author_report_evidence(
        self,
        author_id: int,
        vision_model: str = "",
        vision_prompt_version: str = "",
        vision_cache_key: Optional[Callable[[list], str]] = None,
    ):
        """Read one author and all globally known posts from one WAL snapshot."""
        with self.connect() as conn:
            conn.execute("BEGIN")
            author_row = conn.execute("SELECT * FROM authors WHERE id=?", (author_id,)).fetchone()
            if not author_row:
                raise KeyError("author not found")
            captured_at = utcnow()
            post_rows = conn.execute(
                """SELECT p.*,a.display_name AS author_name,a.author_id AS external_author_id,
                   NULL AS popularity_score,NULL AS popularity_percentile,'' AS popularity_level,
                   '' AS popularity_method,0 AS has_vision_result,
                   (SELECT local_path FROM media_assets m WHERE m.post_id=p.id ORDER BY media_index,id LIMIT 1) AS media_local_path,
                   (SELECT GROUP_CONCAT(DISTINCT source_value) FROM task_posts tp WHERE tp.post_id=p.id) AS sources
                   FROM posts p JOIN authors a ON a.id=p.author_id
                   WHERE p.author_id=?
                   ORDER BY COALESCE(p.likes_count,0) DESC,p.last_seen_at DESC,p.id DESC""",
                (author_id,),
            ).fetchall()
            media_rows = conn.execute(
                """SELECT m.post_id,m.media_index,m.media_type,m.local_path,m.original_url,m.download_status,
                          m.ocr_text,m.ocr_completed_at,m.updated_at
                   FROM media_assets m
                   JOIN posts p ON p.id=m.post_id WHERE p.author_id=?
                   ORDER BY m.post_id,m.media_index,m.id""",
                (author_id,),
            ).fetchall()
            vision_rows = []
            if vision_cache_key is not None and vision_model and vision_prompt_version:
                vision_rows = conn.execute(
                    """SELECT va.* FROM vision_analyses va JOIN posts p ON p.id=va.post_id
                       WHERE p.author_id=? AND va.model=? AND va.prompt_version=?
                       ORDER BY va.analyzed_at DESC,va.id DESC""",
                    (author_id, vision_model, vision_prompt_version),
                ).fetchall()
            ocr_by_post: Dict[int, list] = {}
            media_by_post: Dict[int, list] = {}
            for row in media_rows:
                ocr_by_post.setdefault(int(row["post_id"]), []).append(row["ocr_text"] or "")
                media_by_post.setdefault(int(row["post_id"]), []).append(dict(row))
            current_vision = _current_vision_by_scope(
                media_rows, vision_rows, self.path.parent, vision_cache_key,
            )
            posts = []
            for row in post_rows:
                post = self._row(row)
                post_id = int(post["id"])
                post["ocr_text"] = "\n".join(ocr_by_post.get(post_id, [])).strip()
                scoped_states = {
                    scope: current_vision[scope].get(post_id) or {}
                    for scope in current_vision
                }
                scoped_results = [
                    result
                    for scope in IMAGE_SCOPES
                    for result in (scoped_states[scope].get("vision_results") or [])
                ]
                post["vision_results"] = scoped_results or (
                    scoped_states["all"].get("vision_results") or []
                )
                post["has_vision_result"] = int(bool(post["vision_results"]))
                post_media = media_by_post.get(post_id, [])
                local_media = [item for item in post_media if str(item.get("local_path") or "")]
                local_cover_media = [
                    item for item in local_media if media_matches_scope(item.get("media_type"), "cover")
                ]
                local_detail_media = [
                    item for item in local_media if media_matches_scope(item.get("media_type"), "detail")
                ]
                post["media_count"] = len(post_media)
                post["local_media_count"] = len(local_media)
                post["cover_media_count"] = sum(
                    media_matches_scope(item.get("media_type"), "cover") for item in post_media
                )
                post["detail_media_count"] = sum(
                    media_matches_scope(item.get("media_type"), "detail") for item in post_media
                )
                post["local_cover_media_count"] = len(local_cover_media)
                post["local_detail_media_count"] = len(local_detail_media)
                post["ocr_completed_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_media
                )
                post["ocr_completed_cover_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_cover_media
                )
                post["ocr_completed_detail_media_count"] = sum(
                    bool(item.get("ocr_completed_at")) for item in local_detail_media
                )
                post["has_detail"] = str(post.get("detail_level") or "card") != "card"
                post["has_ocr_result"] = int(
                    bool(local_media) and all(item.get("ocr_completed_at") for item in local_media)
                )
                post["ocr_status"] = (
                    "completed" if post["has_ocr_result"]
                    else "pending" if local_media
                    else "other"
                )
                post["last_ocr_at"] = max(
                    (str(item.get("ocr_completed_at")) for item in local_media if item.get("ocr_completed_at")),
                    default=None,
                )
                vision_rows_for_post = [
                    row
                    for state in scoped_states.values()
                    for row in (state.get("vision_rows") or [])
                ]
                post["last_vision_at"] = max(
                    (str(row.get("analyzed_at")) for row in vision_rows_for_post if row.get("analyzed_at")),
                    default=None,
                )
                all_analyzed = bool(scoped_states["all"].get("analyzed"))
                cover_analyzed = all_analyzed or bool(scoped_states["cover"].get("analyzed"))
                detail_analyzed = all_analyzed or bool(scoped_states["detail"].get("analyzed"))
                post["vision_analyzed_cover_media_count"] = (
                    len(local_cover_media) if cover_analyzed else 0
                )
                post["vision_analyzed_detail_media_count"] = (
                    len(local_detail_media) if detail_analyzed else 0
                )
                post["vision_analyzed_media_count"] = (
                    post["vision_analyzed_cover_media_count"]
                    + post["vision_analyzed_detail_media_count"]
                )
                posts.append(post)
            author = self._row(author_row)
            author["project_post_count"] = len(posts)
            author["relation_type"] = "report_subject"
            subject = {
                "id": f"author-{author_id}",
                "author_id": author_id,
                "name": author.get("display_name") or author.get("author_id") or f"作者 {author_id}",
                "research_type": "author",
                "description": author.get("bio") or "",
                "report_scope": "author",
            }
            return {
                "captured_at": captured_at,
                "project": subject,
                "posts": posts,
                "authors": [author],
                "projects": [
                    self._row(row) for row in conn.execute(
                        """SELECT project.id,project.name,project.slug
                           FROM project_authors relation
                           JOIN projects project ON project.id=relation.project_id
                           WHERE relation.author_id=?
                           GROUP BY project.id ORDER BY project.updated_at DESC,project.id DESC""",
                        (author_id,),
                    ).fetchall()
                ],
                "report_count": int(conn.execute(
                    "SELECT COUNT(*) FROM author_reports WHERE author_id=?",
                    (author_id,),
                ).fetchone()[0]),
            }

    def get_post(self, post_id: int):
        rows = self.query(
            """SELECT p.*,a.display_name AS author_name,a.author_id AS external_author_id FROM posts p
               LEFT JOIN authors a ON a.id=p.author_id WHERE p.id=?""", (post_id,)
        )
        if not rows:
            return None
        value = rows[0]
        value["media"] = self.query(
            "SELECT * FROM media_assets WHERE post_id=? ORDER BY media_index,id",
            (post_id,),
        )
        # Historical rows remain stored but are never exposed as current without
        # validating them against the active provider and current media content.
        value["vision"] = []
        value["projects"] = self.query(
            """SELECT p.id,p.name,p.slug FROM project_posts pp
               JOIN projects p ON p.id=pp.project_id
               WHERE pp.post_id=? ORDER BY p.updated_at DESC,p.id DESC""",
            (post_id,),
        )
        value["project_count"] = len(value["projects"])
        return value

    def get_post_comment_checkpoint(self, post_id: int):
        rows = self.query(
            "SELECT * FROM post_comment_checkpoints WHERE post_id=?", (post_id,),
        )
        return rows[0] if rows else None

    def mark_post_comment_checkpoint_invalid(self, post_id: int, task_id: str, message: str):
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """UPDATE post_comment_checkpoints
                   SET status='invalid',last_task_id=?,last_error=?,updated_at=?
                   WHERE post_id=?""",
                (task_id, str(message or "")[:1000], now, post_id),
            )

    def save_post_comment_page(
        self,
        task_id: str,
        post_id: int,
        page_number: int,
        comments: Sequence[Dict[str, Any]],
        *,
        advance_checkpoint: bool = False,
        reset_checkpoint: bool = False,
        next_cursor: str = "",
        has_more: bool = False,
    ) -> Dict[str, int]:
        """Persist one provider page atomically without retaining its raw response."""
        now = utcnow()
        saved_roots = 0
        saved_reply_previews = 0
        saved_replies = 0
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT post_id,task_type,status FROM tasks WHERE id=?", (task_id,),
            ).fetchone()
            if (
                not task
                or task["task_type"] != "comments"
                or int(task["post_id"] or 0) != int(post_id)
                or task["status"] == "cancelled"
            ):
                return {"root_count": 0, "reply_preview_count": 0, "reply_count": 0}
            for rank, raw in enumerate(comments):
                comment_id = str(raw.get("comment_id") or "").strip()
                comment_type = str(raw.get("comment_type") or "")
                if not comment_id or comment_type not in ("root", "reply_preview"):
                    continue
                conn.execute(
                    """INSERT INTO post_comments(
                           post_id,comment_id,parent_comment_id,root_comment_id,comment_type,is_reply_preview,
                           author_user_id,author_name,author_avatar_url,content,likes_count,
                           published_at,ip_location,platform_reply_count,status,is_invalid,
                           first_seen_at,last_seen_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(post_id,comment_id) DO UPDATE SET
                         parent_comment_id=excluded.parent_comment_id,
                         root_comment_id=excluded.root_comment_id,
                         comment_type=excluded.comment_type,
                         is_reply_preview=MIN(post_comments.is_reply_preview,excluded.is_reply_preview),
                         author_user_id=excluded.author_user_id,
                         author_name=excluded.author_name,
                         author_avatar_url=excluded.author_avatar_url,
                         content=excluded.content,
                         likes_count=excluded.likes_count,
                         published_at=excluded.published_at,
                         ip_location=excluded.ip_location,
                         platform_reply_count=excluded.platform_reply_count,
                         status=excluded.status,is_invalid=excluded.is_invalid,
                         last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at""",
                    (
                        int(post_id), comment_id,
                        str(raw.get("parent_comment_id") or ""),
                        str(raw.get("root_comment_id") or comment_id), comment_type,
                        int(bool(raw.get("is_reply_preview", comment_type == "reply_preview"))),
                        str(raw.get("author_user_id") or ""), str(raw.get("author_name") or ""),
                        str(raw.get("author_avatar_url") or ""), str(raw.get("content") or ""),
                        max(0, int(raw.get("likes_count") or 0)),
                        str(raw.get("published_at") or ""), str(raw.get("ip_location") or ""),
                        max(0, int(raw.get("platform_reply_count") or 0)), raw.get("status"),
                        int(bool(raw.get("is_invalid"))), now, now, now,
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM post_comments WHERE post_id=? AND comment_id=?",
                    (post_id, comment_id),
                ).fetchone()
                page_rank = int(raw.get("page_rank", rank))
                conn.execute(
                    """INSERT INTO task_comments(
                           task_id,post_comment_id,page_number,page_rank,is_reply_preview
                       ) VALUES(?,?,?,?,?)
                       ON CONFLICT(task_id,post_comment_id) DO UPDATE SET
                         page_number=excluded.page_number,page_rank=excluded.page_rank,
                         is_reply_preview=excluded.is_reply_preview""",
                    (task_id, row["id"], max(1, int(page_number)), page_rank,
                     int(bool(raw.get("is_reply_preview", comment_type == "reply_preview")))),
                )
                if comment_type == "root":
                    saved_roots += 1
                elif bool(raw.get("is_reply_preview", True)):
                    saved_reply_previews += 1
                else:
                    saved_replies += 1
            if advance_checkpoint:
                previous = conn.execute(
                    "SELECT completed_pages FROM post_comment_checkpoints WHERE post_id=?",
                    (post_id,),
                ).fetchone()
                completed_pages = (
                    0 if reset_checkpoint else int(previous["completed_pages"] or 0) if previous else 0
                ) + 1
                checkpoint_status = "active" if has_more and next_cursor else "exhausted"
                conn.execute(
                    """INSERT INTO post_comment_checkpoints(
                           post_id,next_cursor,status,completed_pages,last_task_id,last_error,captured_at,updated_at
                       ) VALUES(?,?,?,?,?,'',?,?)
                       ON CONFLICT(post_id) DO UPDATE SET
                         next_cursor=excluded.next_cursor,status=excluded.status,
                         completed_pages=excluded.completed_pages,last_task_id=excluded.last_task_id,
                         last_error='',captured_at=excluded.captured_at,updated_at=excluded.updated_at""",
                    (
                        post_id, str(next_cursor or ""), checkpoint_status, completed_pages,
                        task_id, now, now,
                    ),
                )
        return {
            "root_count": saved_roots,
            "reply_preview_count": saved_reply_previews,
            "reply_count": saved_replies,
        }

    def mark_post_comments_fetched(self, post_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE posts SET last_comments_fetched_at=?,updated_at=? WHERE id=?",
                (utcnow(), utcnow(), post_id),
            )

    def list_post_comments(self, post_id: int, *, page: int = 1, page_size: int = 20):
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        with self.connect() as conn:
            post = conn.execute(
                "SELECT id,comments_count,last_comments_fetched_at FROM posts WHERE id=?",
                (post_id,),
            ).fetchone()
            if not post:
                return None
            active_row = conn.execute(
                """SELECT * FROM tasks WHERE post_id=? AND task_type='comments'
                     AND status IN ('queued','running','waiting_login')
                   ORDER BY created_at DESC,id DESC LIMIT 1""",
                (post_id,),
            ).fetchone()
            latest_row = conn.execute(
                """SELECT t.* FROM tasks t WHERE t.post_id=? AND t.task_type='comments'
                     AND EXISTS(SELECT 1 FROM task_comments tc WHERE tc.task_id=t.id)
                   ORDER BY t.created_at DESC,t.id DESC LIMIT 1""",
                (post_id,),
            ).fetchone()
            latest_task = self._row(latest_row) if latest_row else None
            active_task = self._row(active_row) if active_row else None
            task_id = latest_row["id"] if latest_row else ""
            counts = conn.execute(
                """SELECT
                     SUM(CASE WHEN comment_type='root' THEN 1 ELSE 0 END) AS roots,
                     SUM(CASE WHEN comment_type='reply_preview' AND is_reply_preview=1 THEN 1 ELSE 0 END) AS previews,
                     SUM(CASE WHEN comment_type='reply_preview' AND is_reply_preview=0 THEN 1 ELSE 0 END) AS replies
                   FROM post_comments WHERE post_id=?""",
                (post_id,),
            ).fetchone()
            root_count = int(counts["roots"] or 0)
            reply_preview_count = int(counts["previews"] or 0)
            reply_count = int(counts["replies"] or 0)
            items = []
            if root_count:
                root_rows = conn.execute(
                    """SELECT pc.* FROM post_comments pc
                       WHERE pc.post_id=? AND pc.comment_type='root'
                       ORDER BY pc.id LIMIT ? OFFSET ?""",
                    (post_id, page_size, (page - 1) * page_size),
                ).fetchall()
                root_ids = [row["comment_id"] for row in root_rows]
                replies_by_root: Dict[str, list] = {value: [] for value in root_ids}
                if root_ids:
                    placeholders = ",".join("?" for _ in root_ids)
                    reply_rows = conn.execute(
                        f"""SELECT pc.* FROM post_comments pc
                            WHERE pc.post_id=? AND pc.comment_type='reply_preview'
                              AND pc.root_comment_id IN ({placeholders})
                            ORDER BY pc.id""",
                        [post_id, *root_ids],
                    ).fetchall()
                    for row in reply_rows:
                        replies_by_root.setdefault(row["root_comment_id"], []).append(self._row(row))
                for row in root_rows:
                    item = self._row(row)
                    item["reply_previews"] = replies_by_root.get(item["comment_id"], [])
                    items.append(item)
            checkpoint_row = conn.execute(
                """SELECT status,completed_pages,last_task_id,last_error,captured_at,updated_at
                   FROM post_comment_checkpoints WHERE post_id=?""",
                (post_id,),
            ).fetchone()
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": root_count,
                "summary": {
                    "platform_comment_count": post["comments_count"],
                    "root_comment_count": root_count,
                    "reply_preview_count": reply_preview_count,
                    "reply_count": reply_count,
                    "last_comments_fetched_at": post["last_comments_fetched_at"],
                    "latest_task": latest_task,
                    "active_task": active_task,
                    "checkpoint": self._row(checkpoint_row) if checkpoint_row else None,
                },
            }

    def list_project_authors(self, project_id: int):
        return self.query(
            """SELECT a.*,GROUP_CONCAT(DISTINCT pa.relation_type) AS relation_type,
               COUNT(DISTINCT p.id) AS stored_post_count,
               COUNT(DISTINCT pp.post_id) AS project_post_count,
               COUNT(DISTINCT CASE WHEN COALESCE(pp.popularity_percentile, 0) >= 0.7 THEN pp.post_id END) AS hot_post_count,
               MAX(COALESCE(pp.popularity_percentile, 0)) AS peak_popularity_percentile
               FROM project_authors pa JOIN authors a ON a.id=pa.author_id
               LEFT JOIN posts p ON p.author_id=a.id LEFT JOIN project_posts pp ON pp.post_id=p.id AND pp.project_id=pa.project_id
               WHERE pa.project_id=? GROUP BY a.id
               ORDER BY hot_post_count DESC,peak_popularity_percentile DESC,project_post_count DESC,a.followers_count DESC""",
            (project_id,),
        )

    def get_author(self, author_id: int):
        rows = self.query("SELECT * FROM authors WHERE id=?", (author_id,))
        if not rows:
            return None
        value = rows[0]
        value["posts"] = self.query(
            """SELECT p.id,p.note_id,p.title,p.note_type,p.note_url,p.cover_url,p.cover_local_path,
               p.likes_count,p.favorites_count,p.comments_count,p.publish_date,p.detail_level,p.updated_at,
               CAST({ocr_complete} AS INTEGER) AS has_ocr_result,
               {ocr_status} AS ocr_status,
               {media_storage_status} AS media_storage_status,
               {media_local_path} AS media_local_path,
               {media_original_url} AS media_original_url
               FROM posts p WHERE p.author_id=? ORDER BY p.last_seen_at DESC,p.id DESC""".format(
                ocr_complete=_POST_OCR_COMPLETE_SQL,
                ocr_status=_POST_OCR_STATUS_SQL,
                media_storage_status=_POST_MEDIA_STORAGE_STATUS_SQL,
                media_local_path=_POST_LIST_MEDIA_LOCAL_PATH_SQL,
                media_original_url=_POST_LIST_MEDIA_ORIGINAL_URL_SQL,
            ),
            (author_id,),
        )
        value["projects"] = self.query(
            """SELECT p.id,p.name,p.slug,GROUP_CONCAT(DISTINCT pa.relation_type) AS relation_type
               FROM project_authors pa JOIN projects p ON p.id=pa.project_id
               WHERE pa.author_id=? GROUP BY p.id ORDER BY p.updated_at DESC,p.id DESC""",
            (author_id,),
        )
        value["post_count"] = len(value["posts"])
        value["stored_post_count"] = len(value["posts"])
        value["project_count"] = len(value["projects"])
        return value

    def list_tasks(self, project_id: Optional[int] = None):
        if project_id is None:
            return self.query("SELECT * FROM tasks WHERE status!='cancelled' ORDER BY created_at DESC")
        return self.query("SELECT * FROM tasks WHERE project_id=? AND status!='cancelled' ORDER BY created_at DESC", (project_id,))

    def list_reports(self, project_id: int):
        return self.query("SELECT * FROM reports WHERE project_id=? ORDER BY version DESC", (project_id,))

    def get_project_report(self, project_id: int, report_id: int):
        rows = self.query(
            "SELECT * FROM reports WHERE project_id=? AND id=?", (project_id, report_id),
        )
        return rows[0] if rows else None

    def list_author_reports(self, author_id: int):
        return self.query(
            "SELECT ar.*,NULL AS project_id FROM author_reports ar WHERE author_id=? ORDER BY version DESC",
            (author_id,),
        )

    def get_author_report(self, author_id: int, report_id: int):
        rows = self.query(
            """SELECT ar.*,NULL AS project_id FROM author_reports ar
               WHERE author_id=? AND id=?""",
            (author_id, report_id),
        )
        return rows[0] if rows else None

    def list_report_presentations(self, *, project_report_id: Optional[int] = None,
                                  author_report_id: Optional[int] = None):
        if (project_report_id is None) == (author_report_id is None):
            raise ValueError("presentation list requires exactly one source report")
        if project_report_id is not None:
            return self.query(
                """SELECT id,project_report_id,author_report_id,task_id,version,status,title,
                          page_mode,slide_count,model,prompt_version,generation_config_json,generated_at
                   FROM report_presentations WHERE project_report_id=? ORDER BY version DESC""",
                (project_report_id,),
            )
        return self.query(
            """SELECT id,project_report_id,author_report_id,task_id,version,status,title,
                      page_mode,slide_count,model,prompt_version,generation_config_json,generated_at
               FROM report_presentations WHERE author_report_id=? ORDER BY version DESC""",
            (author_report_id,),
        )

    def get_report_presentation(self, presentation_id: int):
        rows = self.query(
            "SELECT * FROM report_presentations WHERE id=?", (presentation_id,),
        )
        return rows[0] if rows else None

    def get_app_settings(self):
        values = {}
        for row in self.query("SELECT key,value_json FROM app_settings"):
            try:
                values[row["key"]] = json.loads(row["value_json"])
            except (TypeError, json.JSONDecodeError):
                values[row["key"]] = row["value_json"]
        return values

    def set_app_settings(self, values: Dict[str, Any]):
        with self.connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                    (key, _json(value), utcnow()),
                )

    def get_stats(self):
        values = {
            "projects": int(self.scalar("SELECT COUNT(*) FROM projects") or 0),
            "global_posts": int(self.scalar("SELECT COUNT(*) FROM posts") or 0),
            "global_authors": int(self.scalar("SELECT COUNT(*) FROM authors") or 0),
            "tasks": int(self.scalar("SELECT COUNT(*) FROM tasks WHERE status!='cancelled'") or 0),
            "reports": int(self.scalar(
                "SELECT (SELECT COUNT(*) FROM reports)+(SELECT COUNT(*) FROM author_reports)"
            ) or 0),
            "media_assets": int(self.scalar("SELECT COUNT(*) FROM media_assets") or 0),
            "downloaded_media": int(self.scalar("SELECT COUNT(*) FROM media_assets WHERE download_status='downloaded'") or 0),
            "vision_analyses": int(self.scalar("SELECT COUNT(*) FROM vision_analyses") or 0),
            "database_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
        values["media_bytes"] = int(
            self.scalar(
                """SELECT COALESCE(SUM(file_size_bytes),0) FROM (
                       SELECT local_path,MAX(file_size_bytes) AS file_size_bytes
                       FROM media_assets
                       WHERE download_status='downloaded' AND local_path!=''
                       GROUP BY local_path
                   )"""
            )
            or 0
        )
        return values

    def query(self, sql: str, params: Sequence[Any] = ()):
        with self.connect() as conn:
            return [self._row(row) for row in conn.execute(sql, params).fetchall()]

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        for key in ("config_json", "input_json", "result_json", "payload_json", "summary_json", "analysis_json",
                    "diagnostics_json", "evidence_snapshot_json", "generation_config_json", "slides_json"):
            if key in value and isinstance(value[key], str):
                try:
                    value[key] = json.loads(value[key])
                except json.JSONDecodeError:
                    pass
        return value
