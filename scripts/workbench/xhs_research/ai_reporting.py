from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .codex_process import run_codex_process


REPORT_PROMPT_VERSION = "report-v6"
REPORT_CHUNK_CHAR_BUDGET = 20_000
REPORT_FINAL_CHAR_BUDGET = 60_000
REPORT_CHUNK_TIMEOUT = 240
REPORT_FINAL_TIMEOUT = 480
REPORT_MAX_CONCURRENCY = 2
REPORT_RETRIES = 1
REPORT_REASONING_EFFORT = "medium"
REPORT_PROMPT_TEMPLATE_MAX_LENGTH = 12_000

DEFAULT_REPORT_CHUNK_PROMPT_TEMPLATE = (
    "你是严谨的小红书研究证据分析员。仅根据提供的 JSON 批次证据提炼结构化结论。"
    "不要撰写完整报告，不得补造数据。每条判断必须保留 supporting_post_ids；"
    "同时提取反例和数据缺口。covered_post_ids 必须准确列出本批次帖子。"
    "所有帖子引用只能逐字使用以下 ID：{{allowed_post_ids}}。\n"
    "调研对象：{{subject_name}}\n"
    "批次证据 JSON：\n{{evidence_json}}"
)

DEFAULT_REPORT_FINAL_PROMPT_TEMPLATE = (
    "你是严谨的小红书内容研究员。请仅根据下方 JSON 证据生成中文 Markdown 调研报告，"
    "不得补造未提供的数据或因果关系。报告必须包含：数据与方法、作者与内容定位、"
    "高表现内容规律、标题与选题规律、视觉表达规律、可执行建议、局限与置信度。"
    "只使用 report_context 中已开启的作者或帖子来源；存在帖子证据时，关键判断尽量"
    "按 [帖子 #post_id] 引用，未提供帖子证据时不得虚构帖子引用。样本不足时明确说明。"
    "若证据包含 source_policy，必须严格遵守其中的来源分工：数据摘要负责统计数字、趋势与分布，"
    "当前明细只负责案例、原文和定性证据，不得用当前明细重新计算或覆盖数据摘要指标。"
    "未选择数据摘要时，全量统计是唯一数字口径；批次归纳只用于语义判断。"
    "不要复述整份 JSON，不要使用空泛套话。\n"
    "调研对象（{{scope_label}}）：{{subject_name}}\n"
    "报告名称：{{report_title}}\n"
    "输入上下文详细度：{{context_label}}\n"
    "用户补充要求：{{user_instructions}}\n"
    "证据 JSON：\n{{evidence_json}}"
)

REPORT_CHUNK_PROMPT_VARIABLES = frozenset({
    "subject_name", "allowed_post_ids", "user_instructions", "evidence_json",
})
REPORT_FINAL_PROMPT_VARIABLES = frozenset({
    "scope_label", "subject_name", "report_title", "context_label",
    "user_instructions", "evidence_json",
})
REPORT_PROMPT_REQUIRED_VARIABLES = {
    "chunk": frozenset({"allowed_post_ids", "evidence_json"}),
    "final": frozenset({"evidence_json"}),
}
REPORT_PROMPT_ALLOWED_VARIABLES = {
    "chunk": REPORT_CHUNK_PROMPT_VARIABLES,
    "final": REPORT_FINAL_PROMPT_VARIABLES,
}
_REPORT_PROMPT_TOKEN_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
_REPORT_PROMPT_RAW_TOKEN_RE = re.compile(r"{{(.*?)}}", re.DOTALL)

REPORT_CONTEXT_DETAILS = {
    "brief": {
        "label": "概览",
        "description": "核心统计与代表性帖子，适合快速判断方向。",
        "max_posts": 25,
        "max_authors": 15,
        "content_limit": 280,
        "ocr_limit": 0,
        "vision_items": 0,
        "vision_limit": 0,
    },
    "standard": {
        "label": "标准",
        "description": "覆盖代表帖子、作者、OCR 和图片理解摘要，适合常规调研。",
        "max_posts": 80,
        "max_authors": 50,
        "content_limit": 500,
        "ocr_limit": 500,
        "vision_items": 1,
        "vision_limit": 1200,
    },
    "detailed": {
        "label": "深入",
        "description": "纳入更多帖子，以及更完整的正文、OCR 和图片理解信息。",
        "max_posts": 160,
        "max_authors": 100,
        "content_limit": 1200,
        "ocr_limit": 1200,
        "vision_items": 3,
        "vision_limit": 3000,
    },
}
DEFAULT_REPORT_CONTEXT_DETAIL = "standard"

REPORT_POST_SELECTION_MODES = {
    "representative": {
        "label": "有代表性的帖子",
        "ratio": 0.2,
        "max_posts": 20,
    },
    "expanded": {
        "label": "更多帖子",
        "ratio": 0.5,
        "max_posts": None,
    },
    "all": {
        "label": "全部帖子",
        "ratio": 1.0,
        "max_posts": None,
    },
}
REPORT_POST_SECTIONS = frozenset({"basic", "content", "ocr", "vision"})
DEFAULT_REPORT_POST_SECTIONS = ("basic", "content", "ocr")
DEFAULT_REPORT_CONTEXT_CONFIG = {
    "authors": {"enabled": True},
    "posts": {
        "enabled": True,
        "selection_mode": "representative",
        "sections": list(DEFAULT_REPORT_POST_SECTIONS),
    },
}
REPORT_SECTION_TEXT_LIMITS = {
    "author_bio": 2_000,
    "content": 4_000,
    "ocr": 8_000,
    "vision": 8_000,
}


def _clip(value: Any, limit: int) -> str:
    if limit <= 0:
        return ""
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def report_context_detail(value: Any = None) -> str:
    detail = str(value or DEFAULT_REPORT_CONTEXT_DETAIL).strip().lower()
    if detail not in REPORT_CONTEXT_DETAILS:
        supported = ", ".join(REPORT_CONTEXT_DETAILS)
        raise ValueError(f"context_detail must be one of: {supported}")
    return detail


def normalize_report_context_config(value: Any = None) -> Dict[str, Any]:
    """Validate the explicit v2 report context contract.

    Legacy ``context_detail`` configurations intentionally bypass this function
    so historical tasks keep their original limits and evidence shape.
    """
    if value is None:
        value = DEFAULT_REPORT_CONTEXT_CONFIG
    if not isinstance(value, dict):
        raise ValueError("context_config must be an object")
    unknown = sorted(set(value) - {"authors", "posts"})
    if unknown:
        raise ValueError(f"context_config contains unknown fields: {', '.join(unknown)}")

    authors = value.get("authors", DEFAULT_REPORT_CONTEXT_CONFIG["authors"])
    posts = value.get("posts", DEFAULT_REPORT_CONTEXT_CONFIG["posts"])
    if not isinstance(authors, dict) or not isinstance(posts, dict):
        raise ValueError("context_config authors and posts must be objects")
    unknown_authors = sorted(set(authors) - {"enabled"})
    unknown_posts = sorted(set(posts) - {"enabled", "selection_mode", "sections"})
    if unknown_authors:
        raise ValueError(f"context_config.authors contains unknown fields: {', '.join(unknown_authors)}")
    if unknown_posts:
        raise ValueError(f"context_config.posts contains unknown fields: {', '.join(unknown_posts)}")

    authors_enabled = authors.get("enabled", True)
    posts_enabled = posts.get("enabled", True)
    if not isinstance(authors_enabled, bool) or not isinstance(posts_enabled, bool):
        raise ValueError("report context source switches must be booleans")
    if not authors_enabled and not posts_enabled:
        raise ValueError("引用作者和引用帖子至少需要开启一项")

    selection_mode = str(posts.get("selection_mode") or "representative").strip().lower()
    if selection_mode not in REPORT_POST_SELECTION_MODES:
        supported = ", ".join(REPORT_POST_SELECTION_MODES)
        raise ValueError(f"post selection_mode must be one of: {supported}")
    sections = posts.get("sections", list(DEFAULT_REPORT_POST_SECTIONS))
    if not isinstance(sections, list) or any(not isinstance(section, str) for section in sections):
        raise ValueError("context_config.posts.sections must be an array of strings")
    sections = list(dict.fromkeys(section.strip().lower() for section in sections))
    unknown_sections = sorted(set(sections) - REPORT_POST_SECTIONS)
    if unknown_sections:
        raise ValueError(f"unknown post context sections: {', '.join(unknown_sections)}")
    if posts_enabled and not sections:
        raise ValueError("引用帖子开启时至少选择一项帖子内容")

    return {
        "authors": {"enabled": authors_enabled},
        "posts": {
            "enabled": posts_enabled,
            "selection_mode": selection_mode,
            "sections": sections,
        },
    }


def report_post_selection_count(total_posts: int, selection_mode: str) -> int:
    total = max(0, int(total_posts))
    mode = REPORT_POST_SELECTION_MODES.get(str(selection_mode or "").strip().lower())
    if mode is None:
        supported = ", ".join(REPORT_POST_SELECTION_MODES)
        raise ValueError(f"post selection_mode must be one of: {supported}")
    if not total:
        return 0
    count = max(1, math.ceil(total * float(mode["ratio"])))
    if mode["max_posts"] is not None:
        count = min(count, int(mode["max_posts"]))
    return min(total, count)


def default_report_prompt_templates() -> Dict[str, str]:
    return {
        "chunk": DEFAULT_REPORT_CHUNK_PROMPT_TEMPLATE,
        "final": DEFAULT_REPORT_FINAL_PROMPT_TEMPLATE,
    }


def _validate_report_prompt_template(kind: str, value: Any) -> str:
    label = "分批分析提示词" if kind == "chunk" else "最终报告提示词"
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    if len(value) > REPORT_PROMPT_TEMPLATE_MAX_LENGTH:
        raise ValueError(f"{label}不能超过 {REPORT_PROMPT_TEMPLATE_MAX_LENGTH} 字")
    raw_tokens = _REPORT_PROMPT_RAW_TOKEN_RE.findall(value)
    if value.count("{{") != len(raw_tokens) or value.count("}}") != len(raw_tokens):
        raise ValueError(f"{label}包含未闭合的模板变量")
    variables = set()
    for raw in raw_tokens:
        variable = raw.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            raise ValueError(f"{label}包含无效模板变量：{{{{{raw}}}}}")
        variables.add(variable)
    unknown = sorted(variables - REPORT_PROMPT_ALLOWED_VARIABLES[kind])
    if unknown:
        raise ValueError(f"{label}包含未知模板变量：{', '.join(unknown)}")
    missing = sorted(REPORT_PROMPT_REQUIRED_VARIABLES[kind] - variables)
    if missing:
        raise ValueError(f"{label}缺少必需模板变量：{', '.join('{{' + name + '}}' for name in missing)}")
    return value


def normalize_report_prompt_templates(value: Any = None, require_both: bool = False) -> Dict[str, str]:
    defaults = default_report_prompt_templates()
    if value is None:
        return defaults
    if not isinstance(value, dict):
        raise ValueError("report_prompt_templates must be an object")
    unknown = sorted(set(value) - set(defaults))
    if unknown:
        raise ValueError(f"报告提示词配置包含未知字段：{', '.join(unknown)}")
    if require_both:
        missing = sorted(set(defaults) - set(value))
        if missing:
            raise ValueError(f"报告提示词配置缺少字段：{', '.join(missing)}")
    return {
        kind: _validate_report_prompt_template(kind, value.get(kind, default))
        for kind, default in defaults.items()
    }


def report_prompt_template_hash(templates: Dict[str, str]) -> str:
    normalized = normalize_report_prompt_templates(templates, require_both=True)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_report_prompt_template(kind: str, template: str, values: Dict[str, Any]) -> str:
    template = _validate_report_prompt_template(kind, template)
    allowed = REPORT_PROMPT_ALLOWED_VARIABLES[kind]
    missing_values = sorted(variable for variable in allowed if variable not in values)
    if missing_values:
        raise ValueError(f"报告提示词缺少渲染值：{', '.join(missing_values)}")
    return _REPORT_PROMPT_TOKEN_RE.sub(
        lambda match: str(values[match.group(1)]),
        template,
    )


def _ranked_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        posts,
        key=lambda post: (
            float(post.get("popularity_percentile") or 0),
            int(post.get("likes_count") or 0),
            int(post.get("id") or 0),
        ),
        reverse=True,
    )


def _stratified_posts(posts: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Select stable high performers plus broad author/source/time/content strata."""
    ranked = _ranked_posts(posts)
    if len(ranked) <= limit:
        return ranked
    selected: List[Dict[str, Any]] = []
    seen = set()

    def add(post: Dict[str, Any]) -> bool:
        post_id = int(post.get("id") or 0)
        if not post_id or post_id in seen or len(selected) >= limit:
            return False
        selected.append(post)
        seen.add(post_id)
        return True

    # Keep the strongest examples, but reserve most of the budget for coverage.
    for post in ranked[:max(1, limit // 3)]:
        add(post)

    # Guarantee that low and medium performers are available as counterpoints.
    heat_ranges = ((0.7, 2.0), (0.3, 0.7), (-1.0, 0.3))
    for lower, upper in heat_ranges:
        representative = next(
            (
                post for post in ranked
                if lower <= float(post.get("popularity_percentile") or 0) < upper
            ),
            None,
        )
        if representative is not None:
            add(representative)

    dimensions: List[Callable[[Dict[str, Any]], str]] = [
        lambda post: f"author:{post.get('external_author_id') or post.get('author_name') or 'unknown'}",
        lambda post: f"source:{post.get('sources') or 'unknown'}",
        lambda post: f"type:{post.get('note_type') or 'unknown'}",
        lambda post: f"month:{str(post.get('publish_date') or '')[:7] or 'unknown'}",
        lambda post: "heat:high" if float(post.get("popularity_percentile") or 0) >= 0.7
        else ("heat:medium" if float(post.get("popularity_percentile") or 0) >= 0.3 else "heat:low"),
        lambda post: "richness:vision" if post.get("vision_results")
        else ("richness:ocr" if str(post.get("ocr_text") or "").strip()
              else ("richness:content" if str(post.get("content") or "").strip() else "richness:card")),
    ]
    groups: List[List[Dict[str, Any]]] = []
    for dimension in dimensions:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for post in ranked:
            grouped.setdefault(dimension(post), []).append(post)
        groups.extend(grouped[key] for key in sorted(grouped))

    offsets = [0] * len(groups)
    while len(selected) < limit:
        progressed = False
        for index, group in enumerate(groups):
            while offsets[index] < len(group):
                post = group[offsets[index]]
                offsets[index] += 1
                if add(post):
                    progressed = True
                    break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    for post in ranked:
        add(post)
        if len(selected) >= limit:
            break
    return selected


def _selection_summary(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    def count_by(key: Callable[[Dict[str, Any]], str]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for post in posts:
            value = key(post)
            result[value] = result.get(value, 0) + 1
        return result

    return {
        "strategy": "stratified-v1",
        "note_types": count_by(lambda post: str(post.get("note_type") or "unknown")),
        "heat_bands": count_by(
            lambda post: "high" if float(post.get("popularity_percentile") or 0) >= 0.7
            else ("medium" if float(post.get("popularity_percentile") or 0) >= 0.3 else "low")
        ),
        "authors_represented": len({
            str(post.get("external_author_id") or post.get("author_name") or "unknown")
            for post in posts
        }),
        "sources_represented": len({str(post.get("sources") or "unknown") for post in posts}),
    }


def _build_configured_ai_report_evidence(
    subject: Dict[str, Any],
    posts: List[Dict[str, Any]],
    authors: List[Dict[str, Any]],
    context_config: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    config = normalize_report_context_config(context_config)
    post_config = config["posts"]
    author_config = config["authors"]
    selection_mode = post_config["selection_mode"]
    selection_profile = REPORT_POST_SELECTION_MODES[selection_mode]
    selected_post_count = (
        report_post_selection_count(len(posts), selection_mode)
        if post_config["enabled"] else 0
    )
    selected_posts = _stratified_posts(posts, selected_post_count) if selected_post_count else []
    selected_authors = list(authors) if author_config["enabled"] else []
    sections = set(post_config["sections"])
    truncation_counts = {"author_bio": 0, "content": 0, "ocr": 0, "vision": 0}

    def clip_section(value: Any, section: str) -> str:
        text = str(value or "").strip()
        limit = REPORT_SECTION_TEXT_LIMITS[section]
        if len(text) > limit:
            truncation_counts[section] += 1
        return _clip(text, limit)

    def post_evidence(post: Dict[str, Any]) -> Dict[str, Any]:
        value: Dict[str, Any] = {"post_id": post.get("id")}
        if "basic" in sections:
            value.update({
                "note_id": post.get("note_id", ""),
                "title": _clip(post.get("title"), 200),
                "author_name": post.get("author_name", ""),
                "note_type": post.get("note_type", ""),
                "note_url": post.get("note_url", ""),
                "publish_date": post.get("publish_date", ""),
                "likes_count": post.get("likes_count"),
                "favorites_count": post.get("favorites_count"),
                "comments_count": post.get("comments_count"),
                "popularity_percentile": post.get("popularity_percentile"),
                "popularity_level": post.get("popularity_level", ""),
                "sources": post.get("sources", ""),
            })
        if "content" in sections:
            value["content"] = clip_section(post.get("content"), "content")
        if "ocr" in sections:
            value["ocr_text"] = clip_section(post.get("ocr_text"), "ocr")
        if "vision" in sections:
            value["vision_analysis"] = clip_section(
                json.dumps(post.get("vision_results") or [], ensure_ascii=False),
                "vision",
            )
        return value

    scope_ocr_post_count = sum(bool(str(post.get("ocr_text") or "").strip()) for post in posts)
    scope_vision_post_count = sum(bool(post.get("vision_results")) for post in posts)
    evidence_ocr_post_count = (
        sum(bool(str(post.get("ocr_text") or "").strip()) for post in selected_posts)
        if "ocr" in sections else 0
    )
    evidence_vision_post_count = (
        sum(bool(post.get("vision_results")) for post in selected_posts)
        if "vision" in sections else 0
    )
    detailed_count = sum(
        post.get("favorites_count") is not None and post.get("comments_count") is not None
        for post in posts
    )
    scope_key = "author" if subject.get("report_scope") == "author" else "project"
    evidence = {
        "report_context": {
            "version": 2,
            "label": "精确设置",
            "description": "作者与帖子来源独立设置，帖子按动态比例选样。",
            "authors": author_config,
            "posts": {
                **post_config,
                "selection_label": selection_profile["label"],
                "selection_ratio": selection_profile["ratio"],
                "selection_max_posts": selection_profile["max_posts"],
                "selected_post_count": len(selected_posts),
            },
            "text_limits": REPORT_SECTION_TEXT_LIMITS,
        },
        scope_key: {
            "id": subject.get("id"),
            "name": subject.get("name", ""),
            "research_type": subject.get("research_type", ""),
            "description": subject.get("description", ""),
        },
        "statistics": {
            "post_count": len(posts),
            "author_count": len(authors),
            "ocr_post_count": scope_ocr_post_count,
            "vision_post_count": scope_vision_post_count,
            "interaction_detail_count": detailed_count,
            "image_post_count": sum(post.get("note_type") != "video" for post in posts),
            "video_post_count": sum(post.get("note_type") == "video" for post in posts),
            "likes_total": sum(int(post.get("likes_count") or 0) for post in posts),
            "favorites_total": sum(int(post.get("favorites_count") or 0) for post in posts),
            "comments_total": sum(int(post.get("comments_count") or 0) for post in posts),
        },
        "authors": [{
            "author_id": author.get("id"),
            "external_author_id": author.get("author_id", ""),
            "display_name": author.get("display_name", ""),
            "bio": clip_section(author.get("bio"), "author_bio"),
            "followers_count": author.get("followers_count"),
            "likes_collections_count": author.get("likes_collections_count"),
            "project_post_count": author.get("project_post_count"),
            "relation_type": author.get("relation_type", ""),
        } for author in selected_authors],
        "posts": [post_evidence(post) for post in selected_posts],
    }
    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "post_ids": sorted(int(post["id"]) for post in posts),
        "author_ids": sorted(int(author["id"]) for author in authors),
        "selected_post_ids": [int(post["id"]) for post in selected_posts],
        "selected_author_ids": [int(author["id"]) for author in selected_authors],
        "post_count": len(posts),
        "author_count": len(authors),
        "evidence_post_count": len(selected_posts),
        "evidence_author_count": len(selected_authors),
        "ocr_post_count": evidence_ocr_post_count,
        "vision_post_count": evidence_vision_post_count,
        "scope_ocr_post_count": scope_ocr_post_count,
        "scope_vision_post_count": scope_vision_post_count,
        "interaction_detail_count": detailed_count,
        "context_config": config,
        "selection": _selection_summary(selected_posts),
        "truncated_sections": truncation_counts,
    }
    return evidence, snapshot


def build_ai_report_evidence(project: Dict[str, Any], posts: List[Dict[str, Any]],
                             authors: List[Dict[str, Any]], max_posts: Optional[int] = None,
                             max_authors: Optional[int] = None,
                             context_detail: str = DEFAULT_REPORT_CONTEXT_DETAIL,
                             context_config: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if context_config is not None:
        return _build_configured_ai_report_evidence(project, posts, authors, context_config)
    context_detail = report_context_detail(context_detail)
    profile = REPORT_CONTEXT_DETAILS[context_detail]
    max_posts = min(max_posts, profile["max_posts"]) if max_posts is not None else profile["max_posts"]
    max_authors = min(max_authors, profile["max_authors"]) if max_authors is not None else profile["max_authors"]
    selected_posts = _stratified_posts(posts, max_posts)
    selected_authors = sorted(
        authors,
        key=lambda author: int(author.get("followers_count") or 0),
        reverse=True,
    )[:max_authors]
    ocr_post_count = sum(bool(str(post.get("ocr_text") or "").strip()) for post in posts)
    vision_post_count = sum(bool(post.get("vision_results")) for post in posts)
    detailed_count = sum(
        post.get("favorites_count") is not None and post.get("comments_count") is not None
        for post in posts
    )
    scope_key = "author" if project.get("report_scope") == "author" else "project"

    def vision_summary(post: Dict[str, Any]) -> str:
        if not profile["vision_items"]:
            return ""
        return _clip(
            json.dumps((post.get("vision_results") or [])[:profile["vision_items"]], ensure_ascii=False),
            profile["vision_limit"],
        )

    evidence = {
        "report_context": {
            "detail": context_detail,
            "label": profile["label"],
            "description": profile["description"],
            "selected_post_limit": max_posts,
            "selected_author_limit": max_authors,
        },
        scope_key: {
            "id": project.get("id"),
            "name": project.get("name", ""),
            "research_type": project.get("research_type", ""),
            "description": project.get("description", ""),
        },
        "statistics": {
            "post_count": len(posts),
            "author_count": len(authors),
            "ocr_post_count": ocr_post_count,
            "vision_post_count": vision_post_count,
            "interaction_detail_count": detailed_count,
            "image_post_count": sum(post.get("note_type") != "video" for post in posts),
            "video_post_count": sum(post.get("note_type") == "video" for post in posts),
            "likes_total": sum(int(post.get("likes_count") or 0) for post in posts),
            "favorites_total": sum(int(post.get("favorites_count") or 0) for post in posts),
            "comments_total": sum(int(post.get("comments_count") or 0) for post in posts),
        },
        "authors": [{
            "author_id": author.get("id"),
            "external_author_id": author.get("author_id", ""),
            "display_name": author.get("display_name", ""),
            "bio": _clip(author.get("bio"), 500),
            "followers_count": author.get("followers_count"),
            "likes_collections_count": author.get("likes_collections_count"),
            "project_post_count": author.get("project_post_count"),
            "relation_type": author.get("relation_type", ""),
        } for author in selected_authors],
        "posts": [{
            "post_id": post.get("id"),
            "note_id": post.get("note_id", ""),
            "title": _clip(post.get("title"), 200),
            "content": _clip(post.get("content"), profile["content_limit"]),
            "author_name": post.get("author_name", ""),
            "note_type": post.get("note_type", ""),
            "note_url": post.get("note_url", ""),
            "publish_date": post.get("publish_date", ""),
            "likes_count": post.get("likes_count"),
            "favorites_count": post.get("favorites_count"),
            "comments_count": post.get("comments_count"),
            "popularity_percentile": post.get("popularity_percentile"),
            "popularity_level": post.get("popularity_level", ""),
            "sources": post.get("sources", ""),
            "ocr_text": _clip(post.get("ocr_text"), profile["ocr_limit"]),
            "vision_analysis": vision_summary(post),
        } for post in selected_posts],
    }
    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "post_ids": sorted(int(post["id"]) for post in posts),
        "author_ids": sorted(int(author["id"]) for author in authors),
        "selected_post_ids": [int(post["id"]) for post in selected_posts],
        "selected_author_ids": [int(author["id"]) for author in selected_authors],
        "post_count": len(posts),
        "author_count": len(authors),
        "ocr_post_count": ocr_post_count,
        "vision_post_count": vision_post_count,
        "interaction_detail_count": detailed_count,
        "context_detail": context_detail,
        "context_label": profile["label"],
        "selection": _selection_summary(selected_posts),
    }
    return evidence, snapshot


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_report_chunks(evidence: Dict[str, Any], char_budget: int = REPORT_CHUNK_CHAR_BUDGET) -> List[Dict[str, Any]]:
    """Split selected post evidence by serialized size while preserving shared context."""
    posts = list(evidence.get("posts") or [])
    if not posts:
        return []
    shared = {
        key: value for key, value in evidence.items()
        if key not in ("posts", "authors")
    }
    chunks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    current_size = len(_compact_json(shared)) + 256
    for post in posts:
        post_size = len(_compact_json(post)) + 1
        if current and current_size + post_size > max(2_000, int(char_budget)):
            chunks.append({**shared, "posts": current})
            current = []
            current_size = len(_compact_json(shared)) + 256
        current.append(post)
        current_size += post_size
    if current:
        chunks.append({**shared, "posts": current})
    return chunks


class CodexReportError(RuntimeError):
    def __init__(self, message: str, diagnostics: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def _trim_tail(value: Any, limit: int = 3000) -> str:
    text = str(value or "").strip()
    return text[-limit:]


def _diagnostic_summary(value: Any, fallback: str) -> str:
    text = str(value or "")
    messages = re.findall(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if messages:
        try:
            return str(json.loads(f'"{messages[-1]}"'))[:800]
        except json.JSONDecodeError:
            return messages[-1][:800]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines[-1][-800:]
    return fallback


def _merge_chunk_summaries(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {
        "covered_post_ids": [],
        "themes": [],
        "content_patterns": [],
        "visual_patterns": [],
        "high_performance_patterns": [],
        "claims": [],
        "counterexamples": [],
        "data_gaps": [],
    }
    limits = {
        "themes": 12,
        "content_patterns": 12,
        "visual_patterns": 12,
        "high_performance_patterns": 12,
        "claims": 24,
        "counterexamples": 10,
        "data_gaps": 10,
    }
    seen_scalars: Dict[str, set] = {key: set() for key in limits}
    covered = set()
    for summary in summaries:
        covered.update(int(value) for value in summary.get("covered_post_ids") or [])
        for key, limit in limits.items():
            for item in summary.get(key) or []:
                marker = _compact_json(item) if isinstance(item, dict) else str(item).strip()
                if not marker or marker in seen_scalars[key] or len(merged[key]) >= limit:
                    continue
                seen_scalars[key].add(marker)
                merged[key].append(item)
    merged["covered_post_ids"] = sorted(covered)
    return merged


class CodexReportProvider:
    def __init__(self, binary: str = "codex", model: Optional[str] = None,
                 prompt_version: str = REPORT_PROMPT_VERSION, work_dir: Optional[Path] = None,
                 timeout: float = REPORT_FINAL_TIMEOUT,
                 chunk_timeout: float = REPORT_CHUNK_TIMEOUT,
                 max_concurrency: int = REPORT_MAX_CONCURRENCY,
                 chunk_char_budget: int = REPORT_CHUNK_CHAR_BUDGET,
                 retries: int = REPORT_RETRIES,
                 reasoning_effort: str = REPORT_REASONING_EFFORT):
        self.binary = binary
        self.model = model
        self.prompt_version = prompt_version
        self.work_dir = Path(work_dir) if work_dir else None
        self.timeout = timeout
        self.chunk_timeout = min(float(chunk_timeout), float(timeout))
        self.max_concurrency = max(1, min(int(max_concurrency), REPORT_MAX_CONCURRENCY))
        self.chunk_char_budget = max(2_000, int(chunk_char_budget))
        self.retries = max(0, min(int(retries), 2))
        self.reasoning_effort = reasoning_effort if reasoning_effort in ("low", "medium", "high") else "medium"
        self._codex_slots = threading.BoundedSemaphore(self.max_concurrency)

    def _base_args(self, output_root: Path, output: Path, schema: Optional[Path] = None) -> List[str]:
        args = [
            self.binary,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable", "plugins",
            "--disable", "remote_plugin",
            "--disable", "apps",
            "--disable", "hooks",
            "--disable", "browser_use",
            "--disable", "computer_use",
            "--disable", "multi_agent",
            "--disable", "skill_search",
            "--skip-git-repo-check",
            "-C", str(output_root),
            "--sandbox", "read-only",
            "--color", "never",
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "-o", str(output),
        ]
        if schema is not None:
            args.extend(["--output-schema", str(schema)])
        if self.model:
            args.extend(["--model", self.model])
        return args

    def _invoke(self, prompt: str, output_root: Path, suffix: str, timeout: float,
                schema: Optional[Path], should_cancel: Optional[Callable[[], bool]]) -> Tuple[str, Dict[str, Any]]:
        diagnostics: Dict[str, Any] = {
            "model": self.model or "default",
            "reasoning_effort": self.reasoning_effort,
            "input_chars": len(prompt),
            "attempts": 0,
        }
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.retries + 2):
            diagnostics["attempts"] = attempt
            output = output_root / f"report-{suffix}-{uuid.uuid4().hex}.out"
            started = time.monotonic()
            try:
                with self._codex_slots:
                    result = run_codex_process(
                        self._base_args(output_root, output, schema),
                        prompt,
                        timeout,
                        should_cancel=should_cancel,
                    )
                diagnostics.update({
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "returncode": result.returncode,
                    "stdout_tail": _trim_tail(result.stdout),
                    "stderr_tail": _trim_tail(result.stderr),
                })
                if result.returncode:
                    raise CodexReportError(
                        _diagnostic_summary(
                            diagnostics["stderr_tail"],
                            "Codex report generation failed",
                        ),
                        diagnostics,
                    )
                content = output.read_text(encoding="utf-8").strip() if output.exists() else ""
                if not content:
                    raise CodexReportError("Codex report generation returned empty content", diagnostics)
                return content, diagnostics
            except subprocess.TimeoutExpired as exc:
                diagnostics.update({
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "timed_out": True,
                    "stdout_tail": _trim_tail(exc.output),
                    "stderr_tail": _trim_tail(exc.stderr),
                })
                last_error = exc
            except CodexReportError as exc:
                diagnostics.update(exc.diagnostics)
                last_error = exc
            finally:
                output.unlink(missing_ok=True)
            if attempt <= self.retries:
                deadline = time.monotonic() + min(1.0, 0.25 * attempt)
                while time.monotonic() < deadline:
                    if should_cancel and should_cancel():
                        from .codex_process import CodexProcessCancelled
                        raise CodexProcessCancelled("Codex task cancelled")
                    time.sleep(0.05)
        reason = _diagnostic_summary(
            diagnostics.get("stderr_tail"),
            str(last_error or "Codex report generation failed"),
        )
        if diagnostics.get("timed_out"):
            reason = f"Codex 生成超时（{int(timeout)} 秒）" + (f"：{reason}" if reason else "")
        raise CodexReportError(reason, diagnostics)

    def _chunk_cache_key(self, chunk: Dict[str, Any], template_hash: str, instructions: str) -> str:
        payload = "\0".join([
            self.prompt_version,
            self.model or "default",
            self.reasoning_effort,
            template_hash,
            instructions,
            _compact_json(chunk),
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _chunk_validation_details(result: Dict[str, Any], allowed_ids: set) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        invalid_ids = set()

        covered = {int(value) for value in result.get("covered_post_ids") or []}
        invalid_covered = sorted(covered - allowed_ids)
        if not covered or invalid_covered:
            issues.append({
                "field": "covered_post_ids",
                "reason": "empty" if not covered else "outside_evidence",
                "invalid_post_ids": invalid_covered,
            })
            invalid_ids.update(invalid_covered)

        for index, claim in enumerate(result.get("claims") or []):
            cited = {int(value) for value in claim.get("supporting_post_ids") or []}
            invalid = sorted(cited - allowed_ids)
            if invalid:
                issues.append({
                    "field": f"claims[{index}].supporting_post_ids",
                    "reason": "outside_evidence",
                    "invalid_post_ids": invalid,
                })
                invalid_ids.update(invalid)

        for index, counterexample in enumerate(result.get("counterexamples") or []):
            cited = {int(value) for value in counterexample.get("post_ids") or []}
            invalid = sorted(cited - allowed_ids)
            if invalid:
                issues.append({
                    "field": f"counterexamples[{index}].post_ids",
                    "reason": "outside_evidence",
                    "invalid_post_ids": invalid,
                })
                invalid_ids.update(invalid)

        return {
            "issues": issues,
            "invalid_post_ids": sorted(invalid_ids),
            "allowed_post_ids": sorted(allowed_ids),
        }

    def _validate_chunk_summary(self, result: Dict[str, Any], allowed_ids: set) -> None:
        validation = self._chunk_validation_details(result, allowed_ids)
        if not validation["issues"]:
            return
        fields = {issue["field"] for issue in validation["issues"]}
        if "covered_post_ids" in fields:
            message = "批次报告返回了无效的帖子覆盖范围"
        elif any(field.startswith("claims[") for field in fields):
            message = "批次报告引用了证据快照以外的帖子"
        else:
            message = "批次报告反例引用了证据快照以外的帖子"
        raise CodexReportError(message, {"validation": validation})

    def _repair_chunk_summary(self, result: Dict[str, Any], validation: Dict[str, Any],
                              allowed_ids: set, chunk_index: int, output_root: Path,
                              should_cancel: Optional[Callable[[], bool]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        prompt = (
            "请修复下面的小红书批次分析 JSON。只修复列出的问题，不得增加新结论、"
            "不得补造证据，也不得使用允许列表以外的帖子 ID。输出符合原结构的完整 JSON。\n"
            f"允许使用的帖子 ID：{sorted(allowed_ids)}\n"
            f"校验问题：{_compact_json(validation['issues'])}\n"
            "待修复 JSON：\n" + _compact_json(result)
        )
        content, diagnostics = self._invoke(
            prompt,
            output_root,
            f"chunk-{chunk_index}-repair",
            self.chunk_timeout,
            Path(__file__).with_name("report-chunk-schema.json"),
            should_cancel,
        )
        try:
            repaired = json.loads(content)
        except json.JSONDecodeError as exc:
            raise CodexReportError("批次报告修复后没有返回有效 JSON", diagnostics) from exc
        if not isinstance(repaired, dict):
            raise CodexReportError("批次报告修复后的返回值必须是对象", diagnostics)
        try:
            self._validate_chunk_summary(repaired, allowed_ids)
        except CodexReportError as exc:
            diagnostics.update(exc.diagnostics)
            diagnostics["invalid_result"] = repaired
            raise CodexReportError(str(exc), diagnostics) from exc
        return repaired, diagnostics

    def _summarize_chunk(self, project: Dict[str, Any], chunk: Dict[str, Any], chunk_index: int,
                         instructions: str, prompt_templates: Dict[str, str], template_hash: str,
                         output_root: Path, should_cancel: Optional[Callable[[], bool]],
                         cache_get=None, cache_save=None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        allowed_ids = {int(post["post_id"]) for post in chunk.get("posts") or []}
        input_chars = len(_compact_json(chunk))
        prompt = render_report_prompt_template("chunk", prompt_templates["chunk"], {
            "subject_name": project.get("name", ""),
            "allowed_post_ids": sorted(allowed_ids),
            "user_instructions": _clip(instructions, 1000) or "无",
            "evidence_json": _compact_json(chunk),
        })
        cache_key = self._chunk_cache_key(chunk, template_hash, instructions)
        rejected_cache_validation = None
        if cache_get:
            cached = cache_get(cache_key)
            if isinstance(cached, dict):
                rejected_cache_validation = self._chunk_validation_details(cached, allowed_ids)
                if not rejected_cache_validation["issues"]:
                    diagnostics = {"cache_hit": True, "input_chars": input_chars, "attempts": 0}
                    if cache_save:
                        cache_save(cache_key, chunk_index, input_chars, "completed", cached, diagnostics, "")
                    return cached, diagnostics
        result = None
        diagnostics: Dict[str, Any] = {}
        try:
            content, diagnostics = self._invoke(
                prompt,
                output_root,
                f"chunk-{chunk_index}",
                self.chunk_timeout,
                Path(__file__).with_name("report-chunk-schema.json"),
                should_cancel,
            )
            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                raise CodexReportError("批次报告没有返回有效 JSON", diagnostics) from exc
            if not isinstance(result, dict):
                raise CodexReportError("批次报告返回值必须是对象", diagnostics)
            validation = self._chunk_validation_details(result, allowed_ids)
            if validation["issues"]:
                initial_result = result
                diagnostics["validation"] = validation
                diagnostics["initial_invalid_result"] = initial_result
                try:
                    result, repair_diagnostics = self._repair_chunk_summary(
                        initial_result,
                        validation,
                        allowed_ids,
                        chunk_index,
                        output_root,
                        should_cancel,
                    )
                except Exception as exc:
                    repair_diagnostics = getattr(exc, "diagnostics", {})
                    diagnostics["repair"] = repair_diagnostics
                    if repair_diagnostics.get("validation"):
                        diagnostics["repair_validation"] = repair_diagnostics["validation"]
                    raise CodexReportError(str(exc), diagnostics) from exc
                diagnostics["repair"] = repair_diagnostics
                diagnostics["repair_succeeded"] = True
            if rejected_cache_validation and rejected_cache_validation["issues"]:
                diagnostics["rejected_cache_validation"] = rejected_cache_validation
            if cache_save:
                cache_save(cache_key, chunk_index, input_chars, "completed", result, diagnostics, "")
            return result, diagnostics
        except Exception as exc:
            exception_diagnostics = getattr(exc, "diagnostics", {})
            if exception_diagnostics is not diagnostics:
                diagnostics.update(exception_diagnostics)
            if rejected_cache_validation and rejected_cache_validation["issues"]:
                diagnostics["rejected_cache_validation"] = rejected_cache_validation
            if cache_save:
                cache_save(cache_key, chunk_index, input_chars, "failed", result, diagnostics, str(exc))
            raise

    @staticmethod
    def _report_validation_errors(content: str, allowed_ids: set) -> List[str]:
        errors = []
        if len(content.strip()) < 200:
            errors.append("报告正文过短")
        for section in ("数据与方法", "可执行建议", "局限"):
            if section not in content:
                errors.append(f"缺少“{section}”部分")
        cited = {int(value) for value in re.findall(r"帖子\s*#(\d+)", content)}
        invalid = sorted(cited - allowed_ids)
        if invalid:
            errors.append(f"引用了不存在的帖子：{invalid[:10]}")
        if allowed_ids and not cited:
            errors.append("没有引用任何证据帖子")
        return errors

    def _final_prompt(self, project: Dict[str, Any], evidence: Dict[str, Any], instructions: str,
                      prompt_templates: Dict[str, str],
                      chunk_summaries: Optional[List[Dict[str, Any]]] = None) -> str:
        scope_label = "作者" if project.get("report_scope") == "author" else "项目"
        if chunk_summaries is None:
            final_evidence = evidence
        else:
            final_evidence = {
                key: value for key, value in evidence.items() if key != "posts"
            }
            final_evidence["authors"] = [
                {**author, "bio": _clip(author.get("bio"), 160)}
                for author in evidence.get("authors") or []
            ]
            final_evidence["batch_analysis"] = _merge_chunk_summaries(chunk_summaries)
            final_evidence["batch_count"] = len(chunk_summaries)
            if len(_compact_json(final_evidence)) > REPORT_FINAL_CHAR_BUDGET - 6_000:
                final_evidence["authors"] = final_evidence["authors"][:50]
                analysis = final_evidence["batch_analysis"]
                for key in ("themes", "content_patterns", "visual_patterns", "high_performance_patterns"):
                    analysis[key] = analysis.get(key, [])[:8]
                analysis["claims"] = analysis.get("claims", [])[:16]
                analysis["counterexamples"] = analysis.get("counterexamples", [])[:8]
                analysis["data_gaps"] = analysis.get("data_gaps", [])[:8]
        return render_report_prompt_template("final", prompt_templates["final"], {
            "scope_label": scope_label,
            "subject_name": project.get("name", ""),
            "report_title": project.get("report_title") or project.get("name", ""),
            "context_label": evidence.get("report_context", {}).get("label", "标准"),
            "user_instructions": _clip(instructions, 1000) or "无",
            "evidence_json": _compact_json(final_evidence),
        })

    def generate(self, project: Dict[str, Any], evidence: Dict[str, Any], instructions: str = "",
                 should_cancel: Optional[Callable[[], bool]] = None,
                 on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
                 cache_get=None, cache_save=None,
                 prompt_templates: Optional[Dict[str, str]] = None) -> str:
        output_root = self.work_dir or Path.cwd()
        output_root.mkdir(parents=True, exist_ok=True)
        prompt_templates = normalize_report_prompt_templates(prompt_templates)
        template_hash = report_prompt_template_hash(prompt_templates)
        chunks = build_report_chunks(evidence, self.chunk_char_budget)
        direct = len(chunks) <= 1
        if on_progress:
            on_progress({
                "stage": "planned",
                "message": "正在生成大模型报告",
                "current": 0,
                "total": 1 if direct else len(chunks) + 1,
                "chunk_count": len(chunks),
                "input_chars": len(_compact_json(evidence)),
                "prompt_template_hash": template_hash,
            })
        summaries: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
        diagnostics: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
        if not direct:
            aborted = threading.Event()

            def chunk_cancelled() -> bool:
                return aborted.is_set() or bool(should_cancel and should_cancel())

            with ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="report-chunk") as executor:
                futures = {
                    executor.submit(
                        self._summarize_chunk,
                        project,
                        chunk,
                        index,
                        instructions,
                        prompt_templates,
                        template_hash,
                        output_root,
                        chunk_cancelled,
                        cache_get,
                        cache_save,
                    ): index
                    for index, chunk in enumerate(chunks)
                }
                completed = 0
                try:
                    for future in as_completed(futures):
                        index = futures[future]
                        summary, detail = future.result()
                        summaries[index] = summary
                        diagnostics[index] = detail
                        completed += 1
                        if on_progress:
                            on_progress({
                                "stage": "analyzing",
                                "message": "正在生成大模型报告",
                                "current": completed,
                                "total": len(chunks) + 1,
                                "chunk_count": len(chunks),
                                "cache_hits": sum(bool(item and item.get("cache_hit")) for item in diagnostics),
                            })
                except Exception:
                    aborted.set()
                    for future in futures:
                        future.cancel()
                    raise
        usable_summaries = [value for value in summaries if value is not None]
        prompt = self._final_prompt(
            project,
            evidence,
            instructions,
            prompt_templates,
            None if direct else usable_summaries,
        )
        if len(prompt) > REPORT_FINAL_CHAR_BUDGET and not direct:
            # The merge already caps repeated patterns; this guard makes unexpected
            # verbose schema output fail clearly instead of causing another hang.
            raise CodexReportError(
                f"汇总后的报告上下文仍过大（{len(prompt)} 字符），请减少单批输出或证据详细度"
            )
        if on_progress:
            on_progress({
                "stage": "synthesizing",
                "message": "正在生成大模型报告",
                "current": 0 if direct else len(chunks),
                "total": 1 if direct else len(chunks) + 1,
                "chunk_count": len(chunks),
            })
        content, final_diagnostics = self._invoke(
            prompt,
            output_root,
            f"final-{project['id']}",
            self.timeout,
            None,
            should_cancel,
        )
        allowed_ids = {int(post["post_id"]) for post in evidence.get("posts") or []}
        validation_errors = self._report_validation_errors(content, allowed_ids)
        if validation_errors:
            repair_prompt = (
                "请修复下面的 Markdown 报告，只处理列出的问题，不得新增证据或引用。"
                "输出完整修复版 Markdown。\n"
                f"允许引用的帖子 ID：{sorted(allowed_ids)}\n"
                f"问题：{validation_errors}\n"
                "原报告：\n" + content
            )
            content, repair_diagnostics = self._invoke(
                repair_prompt,
                output_root,
                f"repair-{project['id']}",
                self.timeout,
                None,
                should_cancel,
            )
            final_diagnostics["repair"] = repair_diagnostics
            remaining = self._report_validation_errors(content, allowed_ids)
            if remaining:
                raise CodexReportError(f"报告质量校验未通过：{'；'.join(remaining)}", final_diagnostics)
        if on_progress:
            on_progress({
                "stage": "completed",
                "message": "大模型报告已生成",
                "current": 1 if direct else len(chunks) + 1,
                "total": 1 if direct else len(chunks) + 1,
                "chunk_count": len(chunks),
                "cache_hits": sum(bool(item and item.get("cache_hit")) for item in diagnostics),
                "final_input_chars": len(prompt),
                "final_diagnostics": final_diagnostics,
                "prompt_template_hash": template_hash,
            })
        return content.strip() + "\n"
