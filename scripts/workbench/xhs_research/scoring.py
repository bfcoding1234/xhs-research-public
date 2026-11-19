import math
from typing import Any, Dict, List


def _percentiles(posts: List[Dict[str, Any]], key: str) -> Dict[int, float]:
    values = sorted((math.log1p(max(0, int(post.get(key) or 0))), int(post["post_id"])) for post in posts)
    if not values:
        return {}
    if len(values) == 1:
        return {values[0][1]: 1.0}
    return {post_id: rank / (len(values) - 1) for rank, (_, post_id) in enumerate(values)}


def _level(percentile: float) -> str:
    if percentile >= 0.9:
        return "高热"
    if percentile >= 0.7:
        return "较热"
    if percentile >= 0.3:
        return "一般"
    return "低表现"


def score_posts(posts: List[Dict[str, Any]], coverage_threshold: float = 0.7) -> Dict[str, Any]:
    if not posts:
        return {"method": "likes", "reason": "无可评分帖子", "coverage": {}, "scores": {}}
    detailed = sum(post.get("favorites_count") is not None and post.get("comments_count") is not None for post in posts)
    coverage = detailed / len(posts)
    likes = _percentiles(posts, "likes_count")
    favorites = _percentiles(posts, "favorites_count")
    comments = _percentiles(posts, "comments_count")
    composite = coverage >= coverage_threshold
    scores = {}
    raw_scores = {}
    for post in posts:
        post_id = int(post["post_id"])
        score = (
            likes.get(post_id, 0) * 0.45 + favorites.get(post_id, 0) * 0.35 + comments.get(post_id, 0) * 0.20
            if composite else likes.get(post_id, 0)
        )
        raw_scores[post_id] = score
    ordered = sorted(raw_scores.items(), key=lambda item: item[1])
    rank_pct = {post_id: (1.0 if len(ordered) == 1 else rank / (len(ordered) - 1)) for rank, (post_id, _) in enumerate(ordered)}
    for post_id, score in raw_scores.items():
        percentile = rank_pct[post_id]
        scores[post_id] = {"score": round(score, 6), "percentile": round(percentile, 6), "level": _level(percentile)}
    return {
        "method": "composite" if composite else "likes",
        "reason": "互动字段完整" if composite else "收藏、评论字段覆盖不足，已降级为点赞排名",
        "coverage": {"detail": round(coverage, 4)},
        "scores": scores,
    }
