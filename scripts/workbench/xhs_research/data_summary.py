"""Deterministic descriptive statistics for project and author report snapshots."""

from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean, median
import re
from typing import Any, Dict, Iterable, List, Optional

from .attention import calculate_project_attention, interaction_total


_ACTIONABLE_TITLE_WORDS = ("教程", "步骤", "搞定", "指南", "必备", "入门", "方法", "清单")
_QUESTION_TITLE_WORDS = ("?", "？", "怎么", "如何", "为什么")


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    number = _number(value)
    return 0 if number is None else int(number)


def _percentile(values: Iterable[float], ratio: float) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _distribution(values: Iterable[Any]) -> Dict[str, Any]:
    numbers = [number for value in values if (number := _number(value)) is not None]
    if not numbers:
        return {
            "count": 0, "average": None, "median": None, "p75": None, "p90": None,
            "max": None,
            "buckets": _histogram([]),
        }
    return {
        "count": len(numbers),
        "average": round(mean(numbers), 2),
        "median": round(median(numbers), 2),
        "p75": round(_percentile(numbers, 0.75) or 0, 2),
        "p90": round(_percentile(numbers, 0.9) or 0, 2),
        "max": round(max(numbers), 2),
        "buckets": _histogram(numbers),
    }


def _histogram(numbers: Iterable[float]) -> List[Dict[str, Any]]:
    values = list(numbers)
    definitions = (
        ("0", 0, 0),
        ("1–9", 1, 9),
        ("10–99", 10, 99),
        ("100–999", 100, 999),
        ("1千–9999", 1000, 9999),
        ("1万+", 10000, None),
    )
    return [
        {
            "label": label,
            "min": lower,
            "max": upper,
            "count": sum(
                number >= lower and (upper is None or number <= upper)
                for number in values
            ),
        }
        for label, lower, upper in definitions
    ]


def _latest(values: Iterable[Any]) -> Optional[str]:
    normalized = [str(value) for value in values if str(value or "").strip()]
    return max(normalized) if normalized else None


def _post_interactions(post: Dict[str, Any]) -> Optional[int]:
    return interaction_total(post)


def _top_post(post: Dict[str, Any]) -> Dict[str, Any]:
    note_type = str(post.get("note_type") or "").strip().lower()
    return {
        "id": int(post["id"]),
        "title": str(post.get("title") or ""),
        "author_id": post.get("author_id"),
        "author_name": str(post.get("author_name") or ""),
        "note_type": "video" if note_type == "video" else "image",
        "publish_date": str(post.get("publish_date") or ""),
        "likes_count": post.get("likes_count"),
        "favorites_count": post.get("favorites_count"),
        "comments_count": post.get("comments_count"),
        "total_interactions": _post_interactions(post),
        "popularity_percentile": post.get("popularity_percentile"),
        "popularity_level": str(post.get("popularity_level") or ""),
        "has_detail": bool(post.get("has_detail")),
        "has_ocr_result": bool(post.get("has_ocr_result")),
        "has_vision_result": bool(post.get("has_vision_result")),
    }


def _daily_publish_trend(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts = Counter(
        str(post.get("publish_date") or "")[:10]
        for post in posts
        if re.match(r"^\d{4}-\d{2}-\d{2}", str(post.get("publish_date") or ""))
    )
    parsed = []
    for value in counts:
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError:
            continue
    if not parsed:
        return []
    current = min(parsed)
    end = max(parsed)
    result = []
    previous = 0
    while current <= end:
        value = counts.get(current.isoformat(), 0)
        change = value - previous
        result.append({
            "date": current.isoformat(),
            "count": value,
            "change": change,
            "change_rate": round(change / previous, 4) if previous else None,
        })
        previous = value
        current += timedelta(days=1)
    return result


def _publish_trend(
    posts: List[Dict[str, Any]], *, single_author: bool = False
) -> Dict[str, Any]:
    parsed: List[tuple[Dict[str, Any], date]] = []
    for post in posts:
        value = str(post.get("publish_date") or "")[:10]
        try:
            parsed.append((post, date.fromisoformat(value)))
        except ValueError:
            continue
    if not parsed:
        return {"granularity": "day", "points": []}
    dates = [value for _, value in parsed]
    span_days = (max(dates) - min(dates)).days
    granularity = "day" if span_days <= 90 else "week" if span_days <= 730 else "month"
    groups: Dict[str, Dict[str, Any]] = {}
    for post, value in parsed:
        if granularity == "day":
            period = value.isoformat()
        elif granularity == "week":
            period = (value - timedelta(days=value.weekday())).isoformat()
        else:
            period = value.strftime("%Y-%m")
        group = groups.setdefault(period, {
            "post_count": 0,
            "authors": set(),
            "likes": 0,
            "likes_valid_post_count": 0,
            "favorites": 0,
            "favorites_valid_post_count": 0,
            "comments": 0,
            "comments_valid_post_count": 0,
        })
        group["post_count"] += 1
        author_key = post.get("author_id") or post.get("external_author_id")
        if author_key is not None and str(author_key).strip():
            group["authors"].add(str(author_key))
        elif single_author:
            group["authors"].add("__summary_subject__")
        for metric, source in (
            ("likes", "likes_count"),
            ("favorites", "favorites_count"),
            ("comments", "comments_count"),
        ):
            raw_value = post.get(source)
            if _number(raw_value) is None:
                continue
            group[metric] += _integer(raw_value)
            group[f"{metric}_valid_post_count"] += 1
    points = []
    for period, group in sorted(groups.items()):
        point = {
            "period": period,
            "count": group["post_count"],
            "post_count": group["post_count"],
            "author_count": len(group["authors"]),
        }
        for metric in ("likes", "favorites", "comments"):
            valid_count = group[f"{metric}_valid_post_count"]
            point[metric] = group[metric] if valid_count else None
            point[f"{metric}_valid_post_count"] = valid_count
        points.append(point)
    return {
        "granularity": granularity,
        "points": points,
    }


def _top_posts_by_metric(posts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    metric_keys = {
        "total_interactions": lambda post: _post_interactions(post),
        "likes": lambda post: _number(post.get("likes_count")),
        "favorites": lambda post: _number(post.get("favorites_count")),
        "comments": lambda post: _number(post.get("comments_count")),
    }
    return {
        metric: [
            _top_post(post)
            for post in sorted(
                (post for post in posts if key(post) is not None),
                key=lambda post: (
                    key(post) or 0,
                    _post_interactions(post) or 0,
                    int(post.get("id") or 0),
                ),
                reverse=True,
            )[:10]
        ]
        for metric, key in metric_keys.items()
    }


def _shared_post_statistics(
    posts: List[Dict[str, Any]], *, single_author: bool = False
) -> Dict[str, Any]:
    total = len(posts)
    complete_interactions = [
        post
        for post in posts
        if all(post.get(key) is not None for key in ("likes_count", "favorites_count", "comments_count"))
    ]
    normalized_types = [str(post.get("note_type") or "").strip().lower() for post in posts]
    video_posts = sum(value == "video" for value in normalized_types)
    image_posts = sum(value in ("image", "normal", "图文") for value in normalized_types)
    months = Counter(
        str(post.get("publish_date") or "")[:7]
        for post in posts
        if re.match(r"^\d{4}-\d{2}", str(post.get("publish_date") or ""))
    )
    titles = [str(post.get("title") or "").strip() for post in posts]
    title_lengths = [len(title) for title in titles if title]
    complete_interactions = [
        value for post in posts if (value := _post_interactions(post)) is not None
    ]
    total_interactions = sum(complete_interactions)
    local_media_count = sum(_integer(post.get("local_media_count")) for post in posts)
    return {
        "post_completeness": {
            "total": total,
            "detailed": sum(bool(post.get("has_detail")) for post in posts),
            "ocr": sum(bool(post.get("has_ocr_result")) for post in posts),
            "vision": sum(bool(post.get("has_vision_result")) for post in posts),
            "missing_publish_date": sum(not str(post.get("publish_date") or "").strip() for post in posts),
            "missing_interactions": total - len(complete_interactions),
            "missing_title": sum(not title for title in titles),
            "missing_content": sum(not str(post.get("content") or "").strip() for post in posts),
        },
        "content": {
            "image_posts": image_posts,
            "video_posts": video_posts,
            "other_posts": max(0, total - image_posts - video_posts),
            "posts_with_media": sum(_integer(post.get("media_count")) > 0 for post in posts),
            "posts_with_local_media": sum(_integer(post.get("local_media_count")) > 0 for post in posts),
            "media_count": sum(_integer(post.get("media_count")) for post in posts),
            "local_media_count": sum(_integer(post.get("local_media_count")) for post in posts),
            "average_media_per_post": round(
                sum(_integer(post.get("media_count")) for post in posts) / total, 2
            ) if total else 0,
            "publish_months": [
                {"month": month, "count": count} for month, count in sorted(months.items())
            ],
            "publish_start": min(
                (str(post.get("publish_date")) for post in posts if str(post.get("publish_date") or "")),
                default=None,
            ),
            "publish_end": max(
                (str(post.get("publish_date")) for post in posts if str(post.get("publish_date") or "")),
                default=None,
            ),
            "publish_daily": _daily_publish_trend(posts),
            "publish_trend": _publish_trend(posts, single_author=single_author),
        },
        "field_coverage": {
            "posts": {
                "total": total,
                "title": sum(bool(str(post.get("title") or "").strip()) for post in posts),
                "content": sum(bool(str(post.get("content") or "").strip()) for post in posts),
                "publish_date": sum(bool(str(post.get("publish_date") or "").strip()) for post in posts),
                "note_type": sum(bool(str(post.get("note_type") or "").strip()) for post in posts),
                "likes": sum(post.get("likes_count") is not None for post in posts),
                "favorites": sum(post.get("favorites_count") is not None for post in posts),
                "comments": sum(post.get("comments_count") is not None for post in posts),
            },
            "media": {
                "total": sum(_integer(post.get("media_count")) for post in posts),
                "local": local_media_count,
                "ocr_completed_images": sum(
                    _integer(post.get("ocr_completed_media_count")) for post in posts
                ),
                "ocr_covered_posts": sum(bool(post.get("has_ocr_result")) for post in posts),
                "vision_analyzed_images": sum(
                    _integer(post.get("vision_analyzed_media_count")) for post in posts
                ),
                "vision_covered_posts": sum(bool(post.get("has_vision_result")) for post in posts),
                "cover": {
                    "total": sum(_integer(post.get("cover_media_count")) for post in posts),
                    "local": sum(_integer(post.get("local_cover_media_count")) for post in posts),
                    "ocr_completed_images": sum(
                        _integer(post.get("ocr_completed_cover_media_count")) for post in posts
                    ),
                    "ocr_covered_posts": sum(
                        _integer(post.get("local_cover_media_count")) > 0
                        and _integer(post.get("ocr_completed_cover_media_count"))
                        == _integer(post.get("local_cover_media_count"))
                        for post in posts
                    ),
                    "vision_analyzed_images": sum(
                        _integer(post.get("vision_analyzed_cover_media_count")) for post in posts
                    ),
                    "vision_covered_posts": sum(
                        _integer(post.get("vision_analyzed_cover_media_count")) > 0
                        for post in posts
                    ),
                },
                "detail": {
                    "total": sum(_integer(post.get("detail_media_count")) for post in posts),
                    "local": sum(_integer(post.get("local_detail_media_count")) for post in posts),
                    "ocr_completed_images": sum(
                        _integer(post.get("ocr_completed_detail_media_count")) for post in posts
                    ),
                    "ocr_covered_posts": sum(
                        _integer(post.get("local_detail_media_count")) > 0
                        and _integer(post.get("ocr_completed_detail_media_count"))
                        == _integer(post.get("local_detail_media_count"))
                        for post in posts
                    ),
                    "vision_analyzed_images": sum(
                        _integer(post.get("vision_analyzed_detail_media_count")) for post in posts
                    ),
                    "vision_covered_posts": sum(
                        _integer(post.get("vision_analyzed_detail_media_count")) > 0
                        for post in posts
                    ),
                },
            },
        },
        "interactions": {
            "complete_post_count": len(complete_interactions),
            "total_interactions": total_interactions,
            "likes": _distribution(post.get("likes_count") for post in posts),
            "favorites": _distribution(post.get("favorites_count") for post in posts),
            "comments": _distribution(post.get("comments_count") for post in posts),
        },
        "title_features": {
            "with_title": sum(bool(title) for title in titles),
            "missing": sum(not title for title in titles),
            "numeric": sum(bool(re.search(r"\d", title)) for title in titles),
            "question": sum(any(mark in title for mark in _QUESTION_TITLE_WORDS) for title in titles),
            "actionable": sum(any(word in title.lower() for word in _ACTIONABLE_TITLE_WORDS) for title in titles),
            "length_average": round(mean(title_lengths), 2) if title_lengths else None,
            "length_median": round(median(title_lengths), 2) if title_lengths else None,
            "length_max": max(title_lengths) if title_lengths else None,
        },
    }


def _top_share(top_posts: List[Dict[str, Any]], posts: List[Dict[str, Any]]) -> Optional[float]:
    total = sum(value for post in posts if (value := _post_interactions(post)) is not None)
    if total <= 0:
        return None
    return round(sum(int(post.get("total_interactions") or 0) for post in top_posts) / total, 4)


def build_project_data_summary(captured: Dict[str, Any]) -> Dict[str, Any]:
    project = captured["project"]
    posts = list(captured.get("posts") or [])
    authors = list(captured.get("authors") or [])
    keywords = list(captured.get("keywords") or [])
    tasks = list(captured.get("tasks") or [])
    shared = _shared_post_statistics(posts)
    top_posts_by_metric = _top_posts_by_metric(posts)
    top_posts = top_posts_by_metric["total_interactions"]
    attention = calculate_project_attention(posts, authors)
    noteworthy_posts = {
        "criteria": attention["criteria"],
        "items": [
            {
                **_top_post(item["post"]),
                "author": {
                    "id": int(item["author"]["id"]),
                    "name": str(
                        item["author"].get("display_name")
                        or item["author"].get("author_id")
                        or ""
                    ),
                    "followers_count": item["author"].get("followers_count"),
                    "project_post_count": item["author"].get("project_post_count"),
                    "published_posts": item["author"].get("total_post_count"),
                    "likes_collections_count": item["author"].get("likes_collections_count"),
                },
                "smoothed_interactions_per_1000_followers": round(
                    item["smoothed_interactions_per_1000_followers"], 2
                ),
                "interaction_confidence": round(item["interaction_confidence"], 4),
                "attention_metric": round(item["attention_metric"], 2),
                "attention_score": item["attention_score"],
            }
            for item in attention["items"][:10]
        ],
    }
    posts_by_author: Dict[int, List[Dict[str, Any]]] = {}
    for post in posts:
        if post.get("author_id") is not None:
            posts_by_author.setdefault(int(post["author_id"]), []).append(post)
    author_rows = []
    for author in authors:
        author_posts = posts_by_author.get(int(author["id"]), [])
        complete_author_interactions = [
            value for post in author_posts if (value := _post_interactions(post)) is not None
        ]
        total_author_interactions = (
            sum(complete_author_interactions) if complete_author_interactions else None
        )
        author_rows.append({
            "id": int(author["id"]),
            "name": str(author.get("display_name") or author.get("author_id") or ""),
            "followers_count": author.get("followers_count"),
            "following_count": author.get("following_count"),
            "likes_collections_count": author.get("likes_collections_count"),
            "published_posts": author.get("total_post_count"),
            "location": str(author.get("ip_location") or ""),
            "post_count": len(author_posts),
            "detailed_post_count": sum(bool(post.get("has_detail")) for post in author_posts),
            "ocr_post_count": sum(bool(post.get("has_ocr_result")) for post in author_posts),
            "vision_post_count": sum(bool(post.get("has_vision_result")) for post in author_posts),
            "profile_updated": bool(author.get("last_profile_fetched_at")),
            "complete_interaction_post_count": len(complete_author_interactions),
            "total_interactions": total_author_interactions,
            "average_interactions": round(
                sum(complete_author_interactions) / len(complete_author_interactions), 2
            ) if complete_author_interactions else None,
        })
    author_rows.sort(
        key=lambda author: (
            author["post_count"],
            _integer(author.get("followers_count")),
            author["id"],
        ),
        reverse=True,
    )
    task_statuses = Counter(str(task.get("status") or "unknown") for task in tasks)
    task_types = Counter(str(task.get("task_type") or "research") for task in tasks)
    keyword_sources = Counter(str(keyword.get("source") or "manual") for keyword in keywords)
    shared["interactions"]["top_10_share"] = _top_share(top_posts, posts)
    author_field_coverage = {
        "total": len(authors),
        "profile_updated": sum(bool(author.get("last_profile_fetched_at")) for author in authors),
        "display_name": sum(bool(str(author.get("display_name") or "").strip()) for author in authors),
        "xhs_id": sum(bool(str(author.get("xhs_id") or "").strip()) for author in authors),
        "followers": sum(author.get("followers_count") is not None for author in authors),
        "following": sum(author.get("following_count") is not None for author in authors),
        "likes_collections": sum(author.get("likes_collections_count") is not None for author in authors),
        "published_posts": sum(author.get("total_post_count") is not None for author in authors),
        "bio": sum(bool(str(author.get("bio") or "").strip()) for author in authors),
        "location": sum(bool(str(author.get("ip_location") or "").strip()) for author in authors),
        "avatar": sum(
            bool(str(author.get("avatar_local_path") or author.get("avatar_url") or "").strip())
            for author in authors
        ),
    }
    author_top_posts = sorted(author_rows, key=lambda item: (item["post_count"], item["id"]), reverse=True)[:10]
    author_top_interactions = sorted(
        (item for item in author_rows if item["total_interactions"] is not None),
        key=lambda item: (_integer(item["total_interactions"]), item["post_count"], item["id"]),
        reverse=True,
    )[:10]
    author_top_followers = sorted(
        (item for item in author_rows if item["followers_count"] is not None),
        key=lambda item: (_integer(item.get("followers_count")), item["post_count"], item["id"]),
        reverse=True,
    )[:10]
    author_top_average = sorted(
        (item for item in author_rows if item["complete_interaction_post_count"] >= 3),
        key=lambda item: (_number(item["average_interactions"]) or 0, item["post_count"], item["id"]),
        reverse=True,
    )[:10]
    total_author_posts = sum(item["post_count"] for item in author_rows)
    total_author_interactions = sum(_integer(item["total_interactions"]) for item in author_rows)
    location_counts = Counter(item["location"] for item in author_rows if item["location"])
    location_distribution = [
        {"label": label, "count": count} for label, count in location_counts.most_common()
    ]
    return {
        "schema_version": 6,
        "scope": "project",
        "captured_at": captured["captured_at"],
        "subject": {"id": int(project["id"]), "name": str(project.get("name") or "")},
        "core": {
            "keyword_count": len(keywords),
            "post_count": len(posts),
            "author_count": len(authors),
            "task_count": len(tasks),
        },
        **shared,
        "top_posts": top_posts,
        "top_posts_by_metric": top_posts_by_metric,
        "top_posts_ranking": "总互动数（并列时按帖子 ID）",
        "noteworthy_posts": noteworthy_posts,
        "author_completeness": {
            "total": len(authors),
            "profile_updated": sum(author["profile_updated"] for author in author_rows),
            "with_posts": sum(author["post_count"] > 0 for author in author_rows),
            "with_detailed_posts": sum(author["detailed_post_count"] > 0 for author in author_rows),
            "with_ocr_posts": sum(author["ocr_post_count"] > 0 for author in author_rows),
            "with_vision_posts": sum(author["vision_post_count"] > 0 for author in author_rows),
        },
        "top_authors": author_rows[:10],
        "author_field_coverage": author_field_coverage,
        "author_statistics": {
            "post_count": _distribution(item["post_count"] for item in author_rows),
            "followers": _distribution(item.get("followers_count") for item in author_rows),
            "following": _distribution(item.get("following_count") for item in author_rows),
            "likes_collections": _distribution(item.get("likes_collections_count") for item in author_rows),
            "published_posts": _distribution(item.get("published_posts") for item in author_rows),
            "total_interactions": _distribution(item["total_interactions"] for item in author_rows),
            "average_interactions": _distribution(item["average_interactions"] for item in author_rows),
            "locations": location_distribution,
            "top_10_post_share": round(
                sum(item["post_count"] for item in author_top_posts) / total_author_posts, 4
            ) if total_author_posts else None,
            "top_10_interaction_share": round(
                sum(_integer(item["total_interactions"]) for item in author_top_interactions) / total_author_interactions, 4
            ) if total_author_interactions else None,
            "top_authors_by_metric": {
                "post_count": author_top_posts,
                "total_interactions": author_top_interactions,
                "followers": author_top_followers,
                "average_interactions": author_top_average,
            },
        },
        "keywords": {
            "total": len(keywords),
            "manual": keyword_sources.get("manual", 0),
            "ai_generated": keyword_sources.get("ai_generated", 0),
        },
        "tasks": {
            "total": len(tasks),
            "by_status": dict(sorted(task_statuses.items())),
            "by_type": dict(sorted(task_types.items())),
        },
        "freshness": {
            "last_task_at": _latest(task.get("finished_at") or task.get("created_at") for task in tasks),
            "last_detail_at": _latest(post.get("last_detail_fetched_at") for post in posts),
            "last_profile_at": _latest(author.get("last_profile_fetched_at") for author in authors),
            "last_ocr_at": _latest(post.get("last_ocr_at") for post in posts),
            "last_vision_at": _latest(post.get("last_vision_at") for post in posts),
        },
    }


def build_author_data_summary(captured: Dict[str, Any]) -> Dict[str, Any]:
    author = captured["authors"][0]
    posts = list(captured.get("posts") or [])
    projects = list(captured.get("projects") or [])
    shared = _shared_post_statistics(posts, single_author=True)
    top_posts_by_metric = _top_posts_by_metric(posts)
    top_posts = top_posts_by_metric["total_interactions"]
    shared["interactions"]["top_10_share"] = _top_share(top_posts, posts)
    return {
        "schema_version": 5,
        "scope": "author",
        "captured_at": captured["captured_at"],
        "subject": {
            "id": int(author["id"]),
            "name": str(author.get("display_name") or author.get("author_id") or ""),
        },
        "core": {
            "stored_post_count": len(posts),
            "published_post_count": author.get("total_post_count"),
            "project_count": len(projects),
            "report_count": int(captured.get("report_count") or 0),
        },
        **shared,
        "top_posts": top_posts,
        "top_posts_by_metric": top_posts_by_metric,
        "top_posts_ranking": "总互动数（并列时按帖子 ID）",
        "author_profile": {
            "profile_updated": bool(author.get("last_profile_fetched_at")),
            "last_profile_at": author.get("last_profile_fetched_at"),
            "display_name": str(author.get("display_name") or ""),
            "xhs_id": str(author.get("xhs_id") or ""),
            "bio": str(author.get("bio") or ""),
            "location": str(author.get("ip_location") or ""),
            "followers_count": author.get("followers_count"),
            "following_count": author.get("following_count"),
            "likes_collections_count": author.get("likes_collections_count"),
            "published_posts": author.get("total_post_count"),
            "has_avatar": bool(author.get("avatar_local_path") or author.get("avatar_url")),
            "has_bio": bool(str(author.get("bio") or "").strip()),
            "has_xhs_id": bool(str(author.get("xhs_id") or "").strip()),
            "has_location": bool(str(author.get("ip_location") or "").strip()),
            "has_followers": author.get("followers_count") is not None,
        },
        "author_field_coverage": {
            "total": 1,
            "profile_updated": int(bool(author.get("last_profile_fetched_at"))),
            "display_name": int(bool(str(author.get("display_name") or "").strip())),
            "xhs_id": int(bool(str(author.get("xhs_id") or "").strip())),
            "followers": int(author.get("followers_count") is not None),
            "following": int(author.get("following_count") is not None),
            "likes_collections": int(author.get("likes_collections_count") is not None),
            "published_posts": int(author.get("total_post_count") is not None),
            "bio": int(bool(str(author.get("bio") or "").strip())),
            "location": int(bool(str(author.get("ip_location") or "").strip())),
            "avatar": int(bool(author.get("avatar_local_path") or author.get("avatar_url"))),
        },
        "freshness": {
            "last_detail_at": _latest(post.get("last_detail_fetched_at") for post in posts),
            "last_profile_at": author.get("last_profile_fetched_at"),
            "last_ocr_at": _latest(post.get("last_ocr_at") for post in posts),
            "last_vision_at": _latest(post.get("last_vision_at") for post in posts),
        },
    }
