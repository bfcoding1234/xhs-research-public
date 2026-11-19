from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.db import Database
from xhs_research.runner import TaskRunner


class DataSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.db = Database(self.data_dir / "research.sqlite3")
        self.db.initialize()
        self.project_id = self.db.create_project("描述统计项目", "keyword", {})
        self.author_id = self.db.upsert_author({
            "author_id": "summary-author",
            "xhs_id": "summary-xhs-id",
            "display_name": "摘要作者",
            "bio": "作者简介",
            "ip_location": "上海",
            "followers_count": 1200,
            "following_count": 42,
            "likes_collections_count": 8800,
            "total_post_count": 9,
        })
        self.post_id = self.db.upsert_post({
            "note_id": "summary-post",
            "author_id": "summary-author",
            "author": "摘要作者",
            "title": "5 个入门方法？",
            "content": "正文",
            "note_type": "normal",
            "publish_date": "2026-07-01",
            "likes_count": 100,
            "favorites_count": 20,
            "comments_count": 5,
            "detail_level": "detail",
        })
        self.db.attach_post_to_project(self.project_id, self.post_id)
        self.db.attach_author_to_project(self.project_id, self.author_id, "author")
        self.db.add_project_keywords(self.project_id, ["AI 产品"])
        self.db.mark_post_detail_fetched(self.post_id)
        self.db.mark_author_profile_fetched(self.author_id)
        image = self.data_dir / "summary.jpg"
        image.write_bytes(b"summary-image")
        self.db.upsert_media(
            self.post_id,
            {"local_path": str(image), "ocr_text": "封面文字"},
            0,
            "image",
        )
        self.db.create_task(
            self.project_id,
            "keyword",
            "test",
            {"mode": "keyword"},
        )
        self.runner = TaskRunner(self.db)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_report_task_ids_are_nullable_for_deterministic_summaries(self):
        project_task = next(
            row for row in self.db.query("PRAGMA table_info(reports)")
            if row["name"] == "task_id"
        )
        author_task = next(
            row for row in self.db.query("PRAGMA table_info(author_reports)")
            if row["name"] == "task_id"
        )
        self.assertEqual(project_task["notnull"], 0)
        self.assertEqual(author_task["notnull"], 0)

    def test_project_summary_is_structured_and_versioned_without_a_task(self):
        first = self.runner.create_project_data_summary(self.project_id)
        second = self.runner.create_project_data_summary(self.project_id)

        self.assertIsNone(first["task_id"])
        self.assertEqual(first["generator_type"], "template")
        self.assertEqual(first["generation_config_json"]["trigger"], "manual")
        self.assertEqual(first["generator_version"], 1)
        self.assertEqual(second["generator_version"], 2)
        summary = second["summary_json"]
        self.assertEqual(summary["schema_version"], 6)
        self.assertEqual(summary["scope"], "project")
        self.assertEqual(summary["content"]["image_posts"], 1)
        self.assertEqual(summary["content"]["video_posts"], 0)
        self.assertEqual(summary["content"]["other_posts"], 0)
        self.assertEqual(summary["top_posts"][0]["note_type"], "image")
        self.assertEqual(summary["core"], {
            "keyword_count": 1,
            "post_count": 1,
            "author_count": 1,
            "task_count": 1,
        })
        self.assertEqual(summary["post_completeness"]["detailed"], 1)
        self.assertEqual(summary["post_completeness"]["ocr"], 1)
        self.assertEqual(summary["post_completeness"]["vision"], 0)
        self.assertEqual(summary["field_coverage"]["posts"]["comments"], 1)
        self.assertEqual(summary["field_coverage"]["posts"]["likes"], 1)
        self.assertEqual(summary["field_coverage"]["media"]["ocr_completed_images"], 1)
        self.assertEqual(summary["field_coverage"]["media"]["cover"]["local"], 0)
        self.assertEqual(summary["field_coverage"]["media"]["detail"]["local"], 1)
        self.assertEqual(
            summary["field_coverage"]["media"]["detail"]["ocr_completed_images"], 1,
        )
        self.assertEqual(summary["content"]["publish_daily"][0]["date"], "2026-07-01")
        self.assertEqual(summary["top_posts_by_metric"]["comments"][0]["id"], self.post_id)
        self.assertEqual(summary["author_statistics"]["post_count"]["count"], 1)
        self.assertEqual(summary["author_statistics"]["followers"]["p90"], 1200)
        self.assertEqual(summary["author_statistics"]["locations"], [{"label": "上海", "count": 1}])
        self.assertEqual(summary["author_field_coverage"]["following"], 1)
        self.assertEqual(summary["title_features"]["numeric"], 1)
        self.assertEqual(summary["title_features"]["question"], 1)
        self.assertEqual(summary["title_features"]["actionable"], 1)
        self.assertEqual(summary["top_posts"][0]["id"], self.post_id)
        self.assertEqual(summary["top_authors"][0]["id"], self.author_id)
        self.assertEqual(summary["noteworthy_posts"]["criteria"], {
            "follower_smoothing": 1200.0,
            "interaction_smoothing": 125.0,
            "eligible_post_count": 1,
            "eligible_author_count": 1,
            "candidate_count": 1,
        })
        noteworthy = summary["noteworthy_posts"]["items"][0]
        self.assertEqual(noteworthy["id"], self.post_id)
        self.assertEqual(noteworthy["attention_score"], 100)
        self.assertEqual(noteworthy["author"]["followers_count"], 1200)

    def test_zero_interactions_are_covered_but_missing_values_are_not(self):
        zero_post_id = self.db.upsert_post({
            "note_id": "zero-interactions",
            "author_id": "summary-author",
            "title": "零互动帖子",
            "content": "正文",
            "note_type": "video",
            "publish_date": "2026-07-03",
            "likes_count": 0,
            "favorites_count": 0,
            "comments_count": 0,
        })
        missing_post_id = self.db.upsert_post({
            "note_id": "missing-interactions",
            "author_id": "summary-author",
            "title": "缺失互动帖子",
            "note_type": "normal",
            "publish_date": "2026-07-02",
        })
        self.db.attach_post_to_project(self.project_id, zero_post_id)
        self.db.attach_post_to_project(self.project_id, missing_post_id)

        summary = self.runner.create_project_data_summary(self.project_id)["summary_json"]

        self.assertEqual(summary["field_coverage"]["posts"]["likes"], 2)
        self.assertEqual(summary["field_coverage"]["posts"]["favorites"], 2)
        self.assertEqual(summary["field_coverage"]["posts"]["comments"], 2)
        self.assertEqual(summary["interactions"]["comments"]["count"], 2)
        self.assertEqual(summary["content"]["publish_daily"], [
            {"date": "2026-07-01", "count": 1, "change": 1, "change_rate": None},
            {"date": "2026-07-02", "count": 1, "change": 0, "change_rate": 0.0},
            {"date": "2026-07-03", "count": 1, "change": 0, "change_rate": 0.0},
        ])

    def test_project_summary_keeps_every_location_for_the_region_map(self):
        locations = ["北京", "广东", "浙江", "江苏", "四川", "福建", "天津", "河南", "河北", "山东", "湖北"]
        for index, location in enumerate(locations):
            author_id = self.db.upsert_author({
                "author_id": f"region-author-{index}",
                "display_name": f"地区作者 {index}",
                "ip_location": location,
            })
            self.db.attach_author_to_project(self.project_id, author_id, "author")

        summary = self.runner.create_project_data_summary(self.project_id)["summary_json"]
        distribution = summary["author_statistics"]["locations"]

        self.assertEqual(len(distribution), 12)
        self.assertNotIn({"label": "其他", "count": 2}, distribution)
        self.assertIn({"label": "上海", "count": 1}, distribution)
        self.assertIn({"label": "湖北", "count": 1}, distribution)

    def test_publish_trend_aggregates_posts_distinct_authors_and_interactions(self):
        same_author_post_id = self.db.upsert_post({
            "note_id": "same-author-same-day",
            "author_id": "summary-author",
            "title": "同作者同日第二篇",
            "publish_date": "2026-07-01",
            "likes_count": 10,
            "favorites_count": 0,
        })
        second_author_id = self.db.upsert_author({
            "author_id": "summary-author-2",
            "display_name": "第二位作者",
        })
        second_author_post_id = self.db.upsert_post({
            "note_id": "second-author-same-day",
            "author_id": "summary-author-2",
            "title": "第二位作者同日发布",
            "publish_date": "2026-07-01",
            "likes_count": 30,
            "favorites_count": 4,
            "comments_count": 1,
        })
        self.db.attach_post_to_project(self.project_id, same_author_post_id)
        self.db.attach_post_to_project(self.project_id, second_author_post_id)
        self.db.attach_author_to_project(self.project_id, second_author_id, "author")

        summary = self.runner.create_project_data_summary(self.project_id)["summary_json"]
        point = summary["content"]["publish_trend"]["points"][0]

        self.assertEqual(summary["schema_version"], 6)
        self.assertEqual(point, {
            "period": "2026-07-01",
            "count": 3,
            "post_count": 3,
            "author_count": 2,
            "likes": 140,
            "likes_valid_post_count": 3,
            "favorites": 24,
            "favorites_valid_post_count": 3,
            "comments": 6,
            "comments_valid_post_count": 2,
        })

    def test_total_interactions_require_all_three_metrics(self):
        partial_post_id = self.db.upsert_post({
            "note_id": "partial-interactions",
            "author_id": "summary-author",
            "title": "只有点赞的帖子",
            "likes_count": 9999,
        })
        self.db.attach_post_to_project(self.project_id, partial_post_id)

        summary = self.runner.create_project_data_summary(self.project_id)["summary_json"]

        self.assertEqual(summary["interactions"]["complete_post_count"], 1)
        self.assertEqual(summary["interactions"]["total_interactions"], 125)
        self.assertEqual(summary["top_posts_by_metric"]["total_interactions"][0]["id"], self.post_id)
        self.assertEqual(summary["top_posts_by_metric"]["likes"][0]["id"], partial_post_id)

    def test_author_summary_uses_author_specific_core_and_top_posts(self):
        report = self.runner.create_author_data_summary(self.author_id)

        self.assertIsNone(report["task_id"])
        self.assertEqual(report["generator_type"], "template")
        summary = report["summary_json"]
        self.assertEqual(summary["scope"], "author")
        self.assertEqual(summary["core"]["stored_post_count"], 1)
        self.assertEqual(summary["core"]["published_post_count"], 9)
        self.assertEqual(summary["core"]["project_count"], 1)
        self.assertEqual(summary["core"]["report_count"], 1)
        self.assertTrue(summary["author_profile"]["profile_updated"])
        self.assertEqual(summary["author_profile"]["following_count"], 42)
        self.assertEqual(summary["content"]["publish_trend"]["points"][0]["author_count"], 1)
        self.assertEqual(summary["top_posts"][0]["title"], "5 个入门方法？")


if __name__ == "__main__":
    unittest.main()
