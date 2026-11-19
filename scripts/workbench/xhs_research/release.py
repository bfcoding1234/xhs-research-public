"""Explicit, local-only promotion of development research data to stable storage."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, Iterable
from urllib.error import URLError
from urllib.request import urlopen
import uuid

from .db import Database


STABLE_DATA_DIR = Path.home() / "Documents" / "Codex" / "xhs-research-data"
ACTIVE_STATUSES = ("queued", "running", "waiting_login")
TERMINAL_STATUSES = ("completed", "partial", "failed", "cancelled")


class DataReleaseError(ValueError):
    """Raised when a local development-to-stable release cannot safely run."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _row(value: sqlite3.Row) -> Dict[str, Any]:
    return dict(value)


class DataReleaseService:
    """Promotes immutable-identity research data without sharing live SQLite files."""

    def __init__(self, source_data_dir: Path, *, stable_data_dir: Path | None = None,
                 stable_port: int = 4318):
        self.source_data_dir = Path(source_data_dir).expanduser().resolve()
        configured = os.environ.get("XHS_RESEARCH_STABLE_DATA_DIR", "").strip()
        self.stable_data_dir = Path(
            stable_data_dir or configured or STABLE_DATA_DIR
        ).expanduser().resolve()
        self.stable_port = int(stable_port)

    @property
    def source_db(self) -> Database:
        return Database(self.source_data_dir / "research.sqlite3")

    @property
    def stable_db(self) -> Database:
        return Database(self.stable_data_dir / "research.sqlite3")

    def enabled(self) -> bool:
        return self.source_data_dir != self.stable_data_dir and (
            self.source_data_dir.name.endswith("-develop")
            or os.environ.get("XHS_RESEARCH_RELEASE_SOURCE", "").strip() == "develop"
        )

    def _assert_enabled(self):
        if not self.enabled():
            raise DataReleaseError("仅开发版可以发起发布到线上")

    def _active_tasks(self, data_dir: Path) -> list[Dict[str, Any]]:
        database = Database(data_dir / "research.sqlite3")
        if not database.path.exists():
            return []
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with database.connect() as conn:
            return [
                _row(row)
                for row in conn.execute(
                    f"SELECT id,status,task_type,current_phase FROM tasks WHERE status IN ({placeholders})",
                    ACTIVE_STATUSES,
                ).fetchall()
            ]

    def _stable_health(self) -> Dict[str, Any]:
        try:
            with urlopen(f"http://127.0.0.1:{self.stable_port}/api/health", timeout=1) as response:
                value = json.loads(response.read())
                return value if isinstance(value, dict) else {}
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _counts(connection: sqlite3.Connection, source: bool = True) -> Dict[str, int]:
        tables = {
            "authors": "authors",
            "posts": "posts",
            "projects": "projects",
            "media": "media_assets",
            "comments": "post_comments",
            "comment_checkpoints": "post_comment_checkpoints",
            "vision": "vision_analyses",
            "reports": "reports",
            "author_reports": "author_reports",
        }
        return {name: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for name, table in tables.items()}

    def preview(self) -> Dict[str, Any]:
        self._assert_enabled()
        source = self.source_db
        target = self.stable_db
        source.initialize()
        if target.path.exists():
            target.initialize()
        with source.connect() as source_conn:
            source_counts = self._counts(source_conn)
        if target.path.exists():
            with target.connect() as target_conn:
                target_counts = self._counts(target_conn)
        else:
            target_counts = {key: 0 for key in source_counts}
        source_active = self._active_tasks(self.source_data_dir)
        stable_active = self._active_tasks(self.stable_data_dir)
        health = self._stable_health()
        return {
            "enabled": True,
            "source_data_dir": str(self.source_data_dir),
            "target_data_dir": str(self.stable_data_dir),
            "target_online": bool(health.get("status") == "ok"),
            "target_version": health.get("version", ""),
            "source_counts": source_counts,
            "target_counts": target_counts,
            "source_active_tasks": source_active,
            "target_active_tasks": stable_active,
            "can_publish": not source_active and not stable_active,
            "rules": [
                "作者按作者 ID、帖子按 note_id、项目按 slug 合并。",
                "只新增或更新较新的开发记录，不删除线上记录。",
                "只同步已结束任务的可读结果；不带入排队、运行与登录等待任务。",
            ],
        }

    def list_releases(self) -> list[Dict[str, Any]]:
        self.source_db.initialize()
        with self.source_db.connect() as conn:
            return [
                _row(row) for row in conn.execute(
                    "SELECT * FROM data_releases ORDER BY created_at DESC LIMIT 30"
                ).fetchall()
            ]

    @staticmethod
    def _newer(source: Dict[str, Any], target: sqlite3.Row | None) -> bool:
        if target is None:
            return True
        return str(source.get("updated_at") or "") > str(target["updated_at"] or "")

    def _copy_media_file(self, raw_path: Any, copied: Counter) -> str:
        if not raw_path:
            return ""
        source = Path(str(raw_path)).expanduser()
        try:
            source = source.resolve(strict=True)
            relative = source.relative_to(self.source_data_dir)
        except (OSError, ValueError):
            return ""
        if not relative.parts or relative.parts[0] != "media" or not source.is_file():
            return ""
        target = (self.stable_data_dir / relative).resolve()
        try:
            target.relative_to(self.stable_data_dir)
        except ValueError:
            return ""
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            try:
                if source.stat().st_size == target.stat().st_size:
                    copied["unchanged"] += 1
                    return str(target)
            except OSError:
                pass
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        copied["copied"] += 1
        return str(target)

    @staticmethod
    def _upsert_row(conn: sqlite3.Connection, table: str, key: str, value: Dict[str, Any],
                    *, skip: Iterable[str] = ()) -> tuple[int, bool]:
        skipped = {"id", *skip}
        columns = [column for column in value if column not in skipped]
        existing = conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (value[key],)).fetchone()
        if existing is not None and not DataReleaseService._newer(value, existing):
            return int(existing["id"]), False
        if existing is None:
            marks = ",".join("?" for _ in columns)
            cursor = conn.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
                [value[column] for column in columns],
            )
            return int(cursor.lastrowid), True
        updates = [column for column in columns if column != key and column not in {"first_seen_at"}]
        conn.execute(
            f"UPDATE {table} SET {','.join(f'{column}=?' for column in updates)} WHERE {key}=?",
            [value[column] for column in updates] + [value[key]],
        )
        return int(existing["id"]), True

    def publish(self) -> Dict[str, Any]:
        preview = self.preview()
        if not preview["can_publish"]:
            raise DataReleaseError("开发版或线上版存在活跃任务，暂不能发布")
        release_id = f"release_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        source_db = self.source_db
        target_db = self.stable_db
        target_db.initialize()
        copied = Counter()
        changed = Counter()
        try:
            with source_db.connect() as source_conn, target_db.connect() as target_conn:
                target_conn.execute("BEGIN IMMEDIATE")
                authors = [_row(row) for row in source_conn.execute("SELECT * FROM authors").fetchall()]
                author_map: Dict[int, int] = {}
                for author in authors:
                    author["avatar_local_path"] = self._copy_media_file(author.get("avatar_local_path"), copied)
                    target_id, did_change = self._upsert_row(target_conn, "authors", "author_id", author)
                    author_map[int(author["id"])] = target_id
                    changed["authors"] += int(did_change)

                posts = [_row(row) for row in source_conn.execute("SELECT * FROM posts").fetchall()]
                post_map: Dict[int, int] = {}
                for post in posts:
                    post["author_id"] = author_map.get(post.get("author_id"))
                    post["cover_local_path"] = self._copy_media_file(post.get("cover_local_path"), copied)
                    target_id, did_change = self._upsert_row(target_conn, "posts", "note_id", post)
                    post_map[int(post["id"])] = target_id
                    changed["posts"] += int(did_change)

                projects = [_row(row) for row in source_conn.execute("SELECT * FROM projects").fetchall()]
                project_map: Dict[int, int] = {}
                for project in projects:
                    project["latest_report_id"] = None
                    target_id, did_change = self._upsert_row(target_conn, "projects", "slug", project)
                    project_map[int(project["id"])] = target_id
                    changed["projects"] += int(did_change)

                tasks = [_row(row) for row in source_conn.execute(
                    "SELECT * FROM tasks WHERE status IN (?,?,?,?)", TERMINAL_STATUSES
                ).fetchall()]
                task_ids = set()
                for task in tasks:
                    task["project_id"] = project_map.get(task.get("project_id"))
                    task["author_id"] = author_map.get(task.get("author_id"))
                    task["post_id"] = post_map.get(task.get("post_id"))
                    if task.get("created_from") not in ("codex", "web", "test"):
                        task["created_from"] = "web"
                    exists = target_conn.execute("SELECT 1 FROM tasks WHERE id=?", (task["id"],)).fetchone()
                    if not exists:
                        columns = [column for column in task if column != "id"]
                        target_conn.execute(
                            f"INSERT INTO tasks(id,{','.join(columns)}) VALUES({','.join('?' for _ in range(len(columns) + 1))})",
                            [task["id"]] + [task[column] for column in columns],
                        )
                        changed["tasks"] += 1
                    task_ids.add(str(task["id"]))

                for media in [_row(row) for row in source_conn.execute("SELECT * FROM media_assets").fetchall()]:
                    post_id = post_map.get(int(media["post_id"]))
                    if post_id is None:
                        continue
                    media["post_id"] = post_id
                    media["local_path"] = self._copy_media_file(media.get("local_path"), copied)
                    existing = target_conn.execute(
                        "SELECT * FROM media_assets WHERE post_id=? AND media_index=? AND media_type=?",
                        (post_id, media["media_index"], media["media_type"]),
                    ).fetchone()
                    if existing is not None and not self._newer(media, existing):
                        continue
                    if existing is None:
                        columns = [column for column in media if column != "id"]
                        target_conn.execute(
                            f"INSERT INTO media_assets({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                            [media[column] for column in columns],
                        )
                    else:
                        columns = [column for column in media if column not in {"id", "post_id", "media_index", "media_type"}]
                        target_conn.execute(
                            f"UPDATE media_assets SET {','.join(f'{column}=?' for column in columns)} WHERE id=?",
                            [media[column] for column in columns] + [existing["id"]],
                        )
                    changed["media"] += 1

                comment_map: Dict[int, int] = {}
                for comment in [_row(row) for row in source_conn.execute("SELECT * FROM post_comments").fetchall()]:
                    post_id = post_map.get(int(comment["post_id"]))
                    if post_id is None:
                        continue
                    source_comment_id = int(comment["id"])
                    comment["post_id"] = post_id
                    existing = target_conn.execute(
                        "SELECT * FROM post_comments WHERE post_id=? AND comment_id=?",
                        (post_id, comment["comment_id"]),
                    ).fetchone()
                    if existing is None:
                        columns = [column for column in comment if column != "id"]
                        cursor = target_conn.execute(
                            f"INSERT INTO post_comments({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                            [comment[column] for column in columns],
                        )
                        target_comment_id = int(cursor.lastrowid)
                        changed["comments"] += 1
                    else:
                        target_comment_id = int(existing["id"])
                        if self._newer(comment, existing):
                            columns = [column for column in comment if column not in {"id", "post_id", "comment_id", "first_seen_at"}]
                            target_conn.execute(
                                f"UPDATE post_comments SET {','.join(f'{column}=?' for column in columns)} WHERE id=?",
                                [comment[column] for column in columns] + [target_comment_id],
                            )
                            changed["comments"] += 1
                    comment_map[source_comment_id] = target_comment_id

                for row in source_conn.execute("SELECT * FROM vision_analyses").fetchall():
                    vision = _row(row)
                    vision["post_id"] = post_map.get(int(vision["post_id"]))
                    if vision["post_id"] is None:
                        continue
                    existing = target_conn.execute(
                        "SELECT * FROM vision_analyses WHERE post_id=? AND cache_key=?",
                        (vision["post_id"], vision["cache_key"]),
                    ).fetchone()
                    if existing is not None and str(vision["analyzed_at"]) <= str(existing["analyzed_at"]):
                        continue
                    if existing is None:
                        columns = [column for column in vision if column != "id"]
                        target_conn.execute(
                            f"INSERT INTO vision_analyses({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                            [vision[column] for column in columns],
                        )
                    else:
                        target_conn.execute(
                            "UPDATE vision_analyses SET model=?,prompt_version=?,analysis_json=?,analyzed_at=?,is_current=? WHERE id=?",
                            (vision["model"], vision["prompt_version"], vision["analysis_json"], vision["analyzed_at"], vision["is_current"], existing["id"]),
                        )
                    changed["vision"] += 1

                for keyword in [_row(row) for row in source_conn.execute("SELECT * FROM project_keywords").fetchall()]:
                    project_id = project_map.get(int(keyword["project_id"]))
                    if project_id is None:
                        continue
                    existing = target_conn.execute(
                        "SELECT id FROM project_keywords WHERE project_id=? AND normalized_keyword=?",
                        (project_id, keyword["normalized_keyword"]),
                    ).fetchone()
                    if existing is None:
                        target_conn.execute(
                            "INSERT INTO project_keywords(project_id,keyword,normalized_keyword,source,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                            (project_id, keyword["keyword"], keyword["normalized_keyword"], keyword["source"], keyword["created_at"], keyword["updated_at"]),
                        )
                        changed["keywords"] += 1

                for relation in [_row(row) for row in source_conn.execute("SELECT * FROM project_posts").fetchall()]:
                    project_id, post_id = project_map.get(int(relation["project_id"])), post_map.get(int(relation["post_id"]))
                    if project_id is None or post_id is None:
                        continue
                    target_conn.execute(
                        "INSERT OR IGNORE INTO project_posts(project_id,post_id,first_task_id,first_seen_at,last_seen_at,is_featured,popularity_score,popularity_percentile,popularity_level,popularity_method,score_version,scored_at,project_notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (project_id, post_id, relation["first_task_id"] if relation["first_task_id"] in task_ids else None,
                         relation["first_seen_at"], relation["last_seen_at"], relation["is_featured"], relation["popularity_score"], relation["popularity_percentile"], relation["popularity_level"], relation["popularity_method"], relation["score_version"], relation["scored_at"], relation["project_notes"]),
                    )
                for relation in [_row(row) for row in source_conn.execute("SELECT * FROM project_authors").fetchall()]:
                    project_id, author_id = project_map.get(int(relation["project_id"])), author_map.get(int(relation["author_id"]))
                    if project_id is None or author_id is None:
                        continue
                    target_conn.execute(
                        "INSERT OR IGNORE INTO project_authors(project_id,author_id,relation_type,first_task_id,first_seen_at,last_seen_at,project_notes) VALUES(?,?,?,?,?,?,?)",
                        (project_id, author_id, relation["relation_type"], relation["first_task_id"] if relation["first_task_id"] in task_ids else None,
                         relation["first_seen_at"], relation["last_seen_at"], relation["project_notes"]),
                    )
                for reference in [_row(row) for row in source_conn.execute("SELECT * FROM task_posts").fetchall()]:
                    post_id = post_map.get(int(reference["post_id"]))
                    if reference["task_id"] not in task_ids or post_id is None:
                        continue
                    target_conn.execute(
                        "INSERT OR IGNORE INTO task_posts(task_id,post_id,source_type,source_value,source_rank,discovered_at) VALUES(?,?,?,?,?,?)",
                        (reference["task_id"], post_id, reference["source_type"], reference["source_value"], reference["source_rank"], reference["discovered_at"]),
                    )
                for reference in [_row(row) for row in source_conn.execute("SELECT * FROM task_comments").fetchall()]:
                    comment_id = comment_map.get(int(reference["post_comment_id"]))
                    if reference["task_id"] not in task_ids or comment_id is None:
                        continue
                    target_conn.execute(
                        """INSERT OR IGNORE INTO task_comments(
                               task_id,post_comment_id,page_number,page_rank,is_reply_preview
                           ) VALUES(?,?,?,?,?)""",
                        (
                            reference["task_id"], comment_id, reference["page_number"],
                            reference["page_rank"], reference["is_reply_preview"],
                        ),
                    )

                for checkpoint in [
                    _row(row)
                    for row in source_conn.execute("SELECT * FROM post_comment_checkpoints").fetchall()
                ]:
                    post_id = post_map.get(int(checkpoint["post_id"]))
                    if post_id is None:
                        continue
                    checkpoint["post_id"] = post_id
                    if checkpoint.get("last_task_id") not in task_ids:
                        checkpoint["last_task_id"] = None
                    existing = target_conn.execute(
                        "SELECT * FROM post_comment_checkpoints WHERE post_id=?", (post_id,),
                    ).fetchone()
                    if existing is not None and str(checkpoint["updated_at"]) <= str(existing["updated_at"]):
                        continue
                    columns = list(checkpoint)
                    target_conn.execute(
                        f"""INSERT INTO post_comment_checkpoints({','.join(columns)})
                            VALUES({','.join('?' for _ in columns)})
                            ON CONFLICT(post_id) DO UPDATE SET
                              next_cursor=excluded.next_cursor,status=excluded.status,
                              completed_pages=excluded.completed_pages,
                              last_task_id=excluded.last_task_id,last_error=excluded.last_error,
                              captured_at=excluded.captured_at,updated_at=excluded.updated_at""",
                        [checkpoint[column] for column in columns],
                    )
                    changed["comment_checkpoints"] += 1

                for table, parent_column, mapping in (("reports", "project_id", project_map), ("author_reports", "author_id", author_map)):
                    for report in [_row(row) for row in source_conn.execute(f"SELECT * FROM {table} WHERE status!='generating'").fetchall()]:
                        parent_id = mapping.get(int(report[parent_column]))
                        if parent_id is None or report["task_id"] not in task_ids:
                            continue
                        if target_conn.execute(f"SELECT 1 FROM {table} WHERE task_id=?", (report["task_id"],)).fetchone():
                            continue
                        report[parent_column] = parent_id
                        report["version"] = int(target_conn.execute(
                            f"SELECT COALESCE(MAX(version),0)+1 FROM {table} WHERE {parent_column}=?", (parent_id,)
                        ).fetchone()[0])
                        columns = [column for column in report if column != "id"]
                        target_conn.execute(
                            f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                            [report[column] for column in columns],
                        )
                        changed[table] += 1

            summary = {
                "release_id": release_id,
                "changed": dict(changed),
                "media": dict(copied),
                "source_counts": preview["source_counts"],
                "target_counts_before": preview["target_counts"],
            }
            with source_db.connect() as source_conn:
                source_conn.execute(
                    "INSERT INTO data_releases(id,source_data_dir,target_data_dir,status,summary_json,created_at,completed_at,error_message) VALUES(?,?,?,?,?,?,?,?)",
                    (release_id, str(self.source_data_dir), str(self.stable_data_dir), "completed", _json(summary), _now(), _now(), ""),
                )
            return {"status": "completed", **summary}
        except Exception as exc:
            with source_db.connect() as source_conn:
                source_conn.execute(
                    "INSERT OR REPLACE INTO data_releases(id,source_data_dir,target_data_dir,status,summary_json,created_at,completed_at,error_message) VALUES(?,?,?,?,?,?,?,?)",
                    (release_id, str(self.source_data_dir), str(self.stable_data_dir), "failed", _json({}), _now(), _now(), str(exc)[:1000]),
                )
            raise DataReleaseError(f"发布失败：{exc}") from exc
