from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse


_AUTHOR_ID_RE = re.compile(r"[0-9A-Za-z_-]{3,128}")
AUTHOR_UPDATE_SCOPES = ("basic_info", "preview_posts", "detailed_posts")
AUTHOR_COLLECTION_SCOPES = ("basic_info", "posts")
def normalize_author_source(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("author source cannot be empty")

    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in ("http", "https"):
            raise ValueError("author profile URL must use http or https")
        hostname = (parsed.hostname or "").lower()
        if hostname != "xiaohongshu.com" and not hostname.endswith(".xiaohongshu.com"):
            raise ValueError("author profile URL must belong to xiaohongshu.com")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("author profile URL has an invalid port") from exc
        if parsed.username or parsed.password or port not in (None, 80, 443):
            raise ValueError("author profile URL has an invalid authority")
        path = unquote(parsed.path or "")
        match = re.fullmatch(r"/user/profile/([^/?#]+)/?", path)
        if not match or not _AUTHOR_ID_RE.fullmatch(match.group(1)):
            raise ValueError("author profile URL must use /user/profile/{author_id}")
        return match.group(1)

    if any(marker in text for marker in ("/", "\\", ":", "?", "#")) or not _AUTHOR_ID_RE.fullmatch(text):
        raise ValueError("author source must be a stable author ID or Xiaohongshu profile URL")
    return text


def _object(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _list(value: Any, field_name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return value


def _integer(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _number(value: Any, field_name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field_name} must be a finite number")
    return result


@dataclass(frozen=True)
class ResearchRequest:
    mode: str
    project_id: Optional[int] = None
    topic: str = ""
    created_from: str = "codex"
    run_mode: str = "incremental"
    author_ids: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    user_keywords: List[str] = field(default_factory=list)
    user_discovery_limit: int = 5
    discovery_limit: int = 50
    deep_limit: int = 0
    keyword_discovery_limit: int = 50
    keyword_deep_limit: int = 0
    author_discovery_limit: int = 50
    author_deep_limit: int = 0
    filters: Dict[str, str] = field(default_factory=dict)
    image_analysis: str = "ocr-only"
    vision_ratio: float = 0.2
    vision_count: int = 10
    force_refresh: bool = False
    author_update_scopes: List[str] = field(default_factory=list)
    author_collection_scopes: List[str] = field(default_factory=list)
    author_collection_explicit: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        mode = str(payload.get("mode", "")).strip()
        if mode not in ("author", "keyword", "mixed"):
            raise ValueError("mode must be author, keyword or mixed")
        raw_project_id = payload.get("project_id")
        project_id = None
        if raw_project_id not in (None, ""):
            project_id = _integer(raw_project_id, "project_id", 0)
            if project_id <= 0:
                raise ValueError("project_id must be a positive integer")
        source = _object(payload.get("source"), "source")
        limits = _object(payload.get("limits"), "limits")
        analysis = _object(payload.get("image_analysis"), "image_analysis")
        author_values = []
        author_values.extend(_list(source.get("author_ids"), "source.author_ids"))
        author_values.extend(_list(source.get("profile_urls"), "source.profile_urls"))
        if source.get("author_id"):
            author_values.append(source["author_id"])
        if source.get("profile_url"):
            author_values.append(source["profile_url"])
        author_ids = []
        for value in author_values:
            author_id = normalize_author_source(value)
            if author_id and author_id not in author_ids:
                author_ids.append(author_id)
        keywords = []
        seen_keywords = set()
        for value in _list(source.get("keywords"), "source.keywords"):
            keyword = str(value).strip()
            normalized = keyword.casefold()
            if keyword and normalized not in seen_keywords:
                keywords.append(keyword)
                seen_keywords.add(normalized)
        user_keywords = []
        seen_user_keywords = set()
        for value in _list(source.get("user_keywords"), "source.user_keywords"):
            keyword = str(value).strip()
            normalized = keyword.casefold()
            if keyword and normalized not in seen_user_keywords:
                user_keywords.append(keyword)
                seen_user_keywords.add(normalized)
        if mode == "author" and not author_ids:
            raise ValueError("author research requires at least one author")
        if mode == "author" and user_keywords:
            raise ValueError("author research does not support user keyword discovery")
        if mode == "keyword" and not keywords and not user_keywords:
            raise ValueError("keyword research requires at least one post keyword or user keyword")
        if mode == "mixed" and not keywords and not author_ids and not user_keywords:
            raise ValueError("mixed research requires at least one post keyword, author or user keyword")
        discovery = max(1, _integer(limits.get("discovery"), "limits.discovery", 50))
        deep = max(0, min(_integer(limits.get("deep"), "limits.deep", 0), discovery))
        keyword_limits = _object(payload.get("keyword_limits"), "keyword_limits") if payload.get("keyword_limits") is not None else limits
        author_limits = _object(payload.get("author_limits"), "author_limits") if payload.get("author_limits") is not None else limits
        keyword_discovery = max(1, _integer(keyword_limits.get("discovery"), "keyword_limits.discovery", discovery))
        keyword_deep = max(0, min(_integer(keyword_limits.get("deep"), "keyword_limits.deep", deep), keyword_discovery))
        author_discovery = max(1, _integer(author_limits.get("discovery"), "author_limits.discovery", discovery))
        author_deep = max(0, min(_integer(author_limits.get("deep"), "author_limits.deep", deep), author_discovery))
        user_limits = _object(payload.get("user_limits"), "user_limits")
        user_discovery = max(1, _integer(user_limits.get("discovery"), "user_limits.discovery", 5))
        analysis_mode = str(analysis.get("mode", "ocr-only"))
        if analysis_mode not in ("ocr-only", "vision-selective", "vision-all"):
            raise ValueError("image_analysis.mode is invalid")
        filters = _object(source.get("filters"), "source.filters")
        created_from = str(payload.get("created_from", "codex")).strip()
        if created_from not in ("codex", "web", "test"):
            raise ValueError("created_from must be codex, web or test")
        run_mode = str(payload.get("run_mode", "incremental")).strip()
        if run_mode != "incremental":
            raise ValueError("run_mode must be incremental")
        author_update = _object(payload.get("author_update"), "author_update")
        author_update_scopes = []
        if payload.get("author_update") is not None:
            for value in _list(author_update.get("scopes"), "author_update.scopes"):
                scope = str(value or "").strip()
                if scope not in AUTHOR_UPDATE_SCOPES:
                    raise ValueError("author_update.scopes contains an invalid scope")
                if scope not in author_update_scopes:
                    author_update_scopes.append(scope)
            if not author_update_scopes:
                raise ValueError("author_update.scopes requires at least one scope")
            if mode != "author" or len(author_ids) != 1 or user_keywords:
                raise ValueError("author update requires exactly one specified author")
            if "detailed_posts" in author_update_scopes and deep <= 0:
                raise ValueError("detailed_posts requires limits.deep to be at least one")
        author_collection = _object(payload.get("author_collection"), "author_collection")
        author_collection_scopes = []
        if payload.get("author_collection") is not None:
            for value in _list(author_collection.get("scopes"), "author_collection.scopes"):
                scope = str(value or "").strip()
                if scope not in AUTHOR_COLLECTION_SCOPES:
                    raise ValueError("author_collection.scopes contains an invalid scope")
                if scope not in author_collection_scopes:
                    author_collection_scopes.append(scope)
            if mode != "author":
                raise ValueError("author_collection is only supported by author research")
            if not author_collection_scopes:
                raise ValueError("author_collection.scopes requires at least one scope")
        elif mode == "author" and not author_update_scopes:
            # Historical author tasks selected both capabilities implicitly. Keep them runnable.
            author_collection_scopes = list(AUTHOR_COLLECTION_SCOPES)
        return cls(
            mode=mode,
            project_id=project_id,
            topic=str(payload.get("topic") or "").strip()[:500],
            created_from=created_from,
            run_mode=run_mode,
            author_ids=author_ids,
            keywords=keywords,
            user_keywords=user_keywords,
            user_discovery_limit=user_discovery,
            discovery_limit=discovery,
            deep_limit=deep,
            keyword_discovery_limit=keyword_discovery,
            keyword_deep_limit=keyword_deep,
            author_discovery_limit=author_discovery,
            author_deep_limit=author_deep,
            filters={str(k): str(v) for k, v in filters.items()},
            image_analysis=analysis_mode,
            vision_ratio=max(0.0, min(_number(analysis.get("vision_ratio"), "image_analysis.vision_ratio", 0.2), 1.0)),
            vision_count=max(0, min(_integer(analysis.get("vision_count"), "image_analysis.vision_count", 10), 300)),
            force_refresh=bool(payload.get("force_refresh", False)),
            author_update_scopes=author_update_scopes,
            author_collection_scopes=author_collection_scopes,
            author_collection_explicit=payload.get("author_collection") is not None,
        )

    def to_dict(self):
        value = {
            "mode": self.mode,
            "created_from": self.created_from,
            "topic": self.topic,
            "run_mode": self.run_mode,
            "source": {
                "author_ids": self.author_ids,
                "keywords": self.keywords,
                "user_keywords": self.user_keywords,
                "filters": self.filters,
            },
            "limits": {"discovery": self.discovery_limit, "deep": self.deep_limit},
            "user_limits": {"discovery": self.user_discovery_limit},
            "image_analysis": {
                "mode": self.image_analysis,
                "vision_ratio": self.vision_ratio,
                "vision_count": self.vision_count,
            },
            "force_refresh": self.force_refresh,
        }
        if self.project_id is not None:
            value["project_id"] = self.project_id
        if self.author_update_scopes:
            value["author_update"] = {"scopes": self.author_update_scopes}
        if self.author_collection_scopes:
            value["author_collection"] = {"scopes": self.author_collection_scopes}
        if self.mode == "mixed":
            value["keyword_limits"] = {
                "discovery": self.keyword_discovery_limit,
                "deep": self.keyword_deep_limit,
            }
            value["author_limits"] = {
                "discovery": self.author_discovery_limit,
                "deep": self.author_deep_limit,
            }
        return value
