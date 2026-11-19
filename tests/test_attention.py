import unittest

from scripts.workbench.xhs_research.attention import calculate_project_attention


class AttentionScoreTests(unittest.TestCase):
    def test_smooths_small_followers_and_low_interactions_before_percentile_ranking(self):
        authors = [
            {"id": 1, "followers_count": 10},
            {"id": 2, "followers_count": 100},
            {"id": 3, "followers_count": 1000},
        ]
        posts = [
            {"id": 1, "author_id": 1, "likes_count": 20, "favorites_count": 40, "comments_count": 60},
            {"id": 2, "author_id": 2, "likes_count": 10, "favorites_count": 20, "comments_count": 30},
            {"id": 3, "author_id": 3, "likes_count": 30, "favorites_count": 60, "comments_count": 90},
            {"id": 4, "author_id": 1, "likes_count": 999, "favorites_count": None, "comments_count": None},
        ]

        result = calculate_project_attention(posts, authors)

        self.assertEqual(result["criteria"], {
            "follower_smoothing": 100.0,
            "interaction_smoothing": 120.0,
            "eligible_post_count": 3,
            "eligible_author_count": 3,
            "candidate_count": 3,
        })
        self.assertEqual([item["post"]["id"] for item in result["items"]], [1, 2, 3])
        self.assertEqual([item["attention_score"] for item in result["items"]], [100, 67, 33])


if __name__ == "__main__":
    unittest.main()
