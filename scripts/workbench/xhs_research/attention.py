"""Deterministic project-relative attention scoring for posts."""

from bisect import bisect_right
from math import floor
from statistics import median
from typing import Any, Dict, Iterable, List, Optional


FOLLOWER_SMOOTHING_MIN = 100.0
INTERACTION_SMOOTHING_MIN = 1.0


def interaction_total(post: Dict[str, Any]) -> Optional[int]:
    values = [post.get(key) for key in ("likes_count", "favorites_count", "comments_count")]
    if any(value is None or value == "" for value in values):
        return None
    try:
        return sum(int(float(value)) for value in values)
    except (TypeError, ValueError):
        return None


def attention_metric(
    interactions: int,
    followers: int,
    follower_smoothing: float,
    interaction_smoothing: float,
) -> float:
    normalized_followers = max(0, int(followers))
    return (
        1000.0
        * interactions
        / (normalized_followers + follower_smoothing)
        * interactions
        / (interactions + interaction_smoothing)
    )


def calculate_project_attention(
    posts: Iterable[Dict[str, Any]],
    authors: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    post_rows = list(posts)
    author_by_id = {
        int(author["id"]): author
        for author in authors
        if author.get("id") is not None
    }
    project_author_ids = {
        int(post["author_id"])
        for post in post_rows
        if post.get("author_id") is not None
    }
    known_followers = [
        max(0, int(author_by_id[author_id]["followers_count"]))
        for author_id in project_author_ids
        if author_id in author_by_id
        and author_by_id[author_id].get("followers_count") is not None
    ]
    follower_smoothing = max(
        FOLLOWER_SMOOTHING_MIN,
        float(median(known_followers)) if known_followers else FOLLOWER_SMOOTHING_MIN,
    )

    eligible: List[Dict[str, Any]] = []
    for post in post_rows:
        author_id = post.get("author_id")
        interactions = interaction_total(post)
        if author_id is None or interactions is None:
            continue
        author = author_by_id.get(int(author_id))
        if not author or author.get("followers_count") is None:
            continue
        eligible.append({
            "post": post,
            "author": author,
            "interactions": interactions,
            "followers": max(0, int(author["followers_count"])),
        })

    interaction_smoothing = max(
        INTERACTION_SMOOTHING_MIN,
        float(median(item["interactions"] for item in eligible))
        if eligible else INTERACTION_SMOOTHING_MIN,
    )
    for item in eligible:
        interactions = item["interactions"]
        metric = attention_metric(
            interactions,
            item["followers"],
            follower_smoothing,
            interaction_smoothing,
        )
        item["smoothed_interactions_per_1000_followers"] = (
            1000.0 * interactions / (item["followers"] + follower_smoothing)
        )
        item["interaction_confidence"] = interactions / (
            interactions + interaction_smoothing
        )
        item["attention_metric"] = metric

    ordered_metrics = sorted(item["attention_metric"] for item in eligible)
    for item in eligible:
        item["attention_score"] = floor(
            100.0
            * bisect_right(ordered_metrics, item["attention_metric"])
            / len(ordered_metrics)
            + 0.5
        )

    eligible.sort(key=lambda item: (
        -item["attention_metric"],
        -item["interactions"],
        item["followers"],
        int(item["post"].get("id") or 0),
    ))
    return {
        "criteria": {
            "follower_smoothing": round(follower_smoothing, 2),
            "interaction_smoothing": round(interaction_smoothing, 2),
            "eligible_post_count": len(eligible),
            "eligible_author_count": len(known_followers),
            "candidate_count": len(eligible),
        },
        "items": eligible,
    }
