from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database


class PostSortingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / "research.sqlite3")
        self.db.initialize()
        self.author_ids = [
            self.db.upsert_author({
                "author_id": f"sort-author-{index}",
                "display_name": f"排序作者 {index}",
                "followers_count": followers,
            })
            for index, followers in enumerate([10, 100, 1000], 1)
        ]
        self.post_ids = [
            self.db.upsert_post({
                "note_id": f"note-{index}",
                "author_id": f"sort-author-{index}",
                "title": title,
                "likes_count": likes,
                "favorites_count": likes * 2,
                "comments_count": likes * 3,
                "publish_date": f"2026-07-0{index}",
            })
            for index, (title, likes) in enumerate(
                [("bravo", 20), ("alpha", 10), ("charlie", 30)],
                1,
            )
        ]

    def test_global_post_sorting_supports_both_directions_and_project_count(self):
        project_id = self.db.create_project("排序项目", "keyword", {})
        self.db.attach_post_to_project(project_id, self.post_ids[0])

        likes_asc = self.db.list_posts_page(page=1, page_size=20, sort="likes_asc")
        title_desc = self.db.list_posts_page(page=1, page_size=20, sort="title_desc")
        project_desc = self.db.list_posts_page(
            page=1,
            page_size=20,
            sort="project_count_desc",
        )

        self.assertEqual([post["likes_count"] for post in likes_asc["items"]], [10, 20, 30])
        self.assertEqual(
            [post["title"] for post in title_desc["items"]],
            ["charlie", "bravo", "alpha"],
        )
        self.assertEqual(project_desc["items"][0]["id"], self.post_ids[0])

    def test_project_post_sorting_supports_popularity_and_dates(self):
        project_id = self.db.create_project("热度项目", "keyword", {})
        for post_id in self.post_ids:
            self.db.attach_post_to_project(project_id, post_id)
        self.db.save_project_scores(project_id, {
            "scores": {
                str(self.post_ids[0]): {"score": 1, "percentile": 0.5, "level": "一般"},
                str(self.post_ids[1]): {"score": 1, "percentile": 0.1, "level": "低表现"},
                str(self.post_ids[2]): {"score": 1, "percentile": 0.9, "level": "高热"},
            },
            "method": "test",
        })

        popularity = self.db.list_project_posts_page(
            project_id,
            page=1,
            page_size=20,
            sort="popularity_desc",
        )
        published = self.db.list_project_posts_page(
            project_id,
            page=1,
            page_size=20,
            sort="published_asc",
        )

        self.assertEqual(popularity["items"][0]["id"], self.post_ids[2])
        self.assertEqual(
            [post["publish_date"] for post in published["items"]],
            ["2026-07-01", "2026-07-02", "2026-07-03"],
        )

    def test_project_post_attention_fields_and_sorting_cover_the_full_result(self):
        project_id = self.db.create_project("关注分项目", "keyword", {})
        for post_id in self.post_ids:
            self.db.attach_post_to_project(project_id, post_id)
        invalid_post_id = self.db.upsert_post({
            "note_id": "attention-missing",
            "author_id": "sort-author-1",
            "title": "互动缺失",
            "likes_count": 999,
        })
        self.db.attach_post_to_project(project_id, invalid_post_id)

        descending = self.db.list_project_posts_page(
            project_id,
            page=1,
            page_size=2,
            sort="attention_desc",
        )
        ascending = self.db.list_project_posts_page(
            project_id,
            page=1,
            page_size=20,
            sort="attention_asc",
        )

        self.assertEqual([post["id"] for post in descending["items"]], self.post_ids[:2])
        self.assertEqual(descending["items"][0]["author_followers_count"], 10)
        self.assertEqual(descending["items"][0]["attention_score"], 100)
        self.assertEqual(
            [post["id"] for post in ascending["items"]],
            [self.post_ids[2], self.post_ids[1], self.post_ids[0], invalid_post_id],
        )
        self.assertIsNone(ascending["items"][-1]["attention_score"])


if __name__ == "__main__":
    unittest.main()
