"""Resolve the one vision analysis that is current for each post."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


IMAGE_SCOPES = ("cover", "detail")


def media_matches_scope(media_type: Any, image_scope: str) -> bool:
    normalized = str(media_type or "").strip().lower()
    if image_scope == "cover":
        return normalized == "cover"
    if image_scope == "detail":
        return normalized != "cover"
    if image_scope == "all":
        return True
    raise ValueError("图片范围无效")


def resolve_current_vision(
    media_rows: Iterable[Any],
    cache_rows: Iterable[Any],
    data_root: Path,
    cache_key_fn: Optional[Callable[[list], str]],
    image_scope: str = "all",
) -> Dict[int, Dict[str, Any]]:
    """Match strict in-root media content to an exact provider cache row.

    Without a provider cache-key function no historical row is considered
    current. The caller may still use the returned media paths to report that a
    post is available/pending.
    """
    root = Path(data_root).expanduser().resolve()
    media_by_post: Dict[int, list] = {}
    for raw in media_rows:
        item = dict(raw)
        if not media_matches_scope(item.get("media_type"), image_scope):
            continue
        try:
            path = Path(item.get("local_path") or "").expanduser().resolve(strict=True)
            path.relative_to(root)
            if not path.is_file():
                continue
        except (OSError, RuntimeError, ValueError):
            continue
        item["local_path"] = str(path)
        media_by_post.setdefault(int(item["post_id"]), []).append(item)

    cache_by_identity = {}
    for raw in cache_rows:
        item = dict(raw)
        if str(item.get("image_scope") or "all") != image_scope:
            continue
        analysis = item.get("analysis_json")
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis)
            except (TypeError, json.JSONDecodeError):
                continue
        if not isinstance(analysis, dict):
            continue
        item["analysis_json"] = analysis
        cache_by_identity.setdefault(
            (int(item["post_id"]), str(item.get("cache_key") or "")), item,
        )

    states = {}
    for post_id, media in media_by_post.items():
        paths = [item["local_path"] for item in media]
        cache_key = ""
        current = None
        if cache_key_fn is not None:
            try:
                cache_key = str(cache_key_fn(paths) or "")
            except (OSError, RuntimeError, ValueError):
                continue
            current = cache_by_identity.get((post_id, cache_key))
        states[post_id] = {
            "media": media,
            "image_paths": paths,
            "image_scope": image_scope,
            "cache_key": cache_key,
            "current": current,
            "analyzed": current is not None,
            "vision_results": [current["analysis_json"]] if current is not None else [],
            "vision_rows": [current] if current is not None else [],
        }
    return states
