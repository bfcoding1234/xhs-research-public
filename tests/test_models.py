from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.models import ResearchRequest


class ResearchRequestTests(unittest.TestCase):
    def test_project_id_is_optional_for_independent_task(self):
        request = ResearchRequest.from_dict({
            "mode": "keyword",
            "created_from": "web",
            "source": {"keywords": ["AI 产品经理"]},
        })

        self.assertIsNone(request.project_id)
        self.assertNotIn("project_id", request.to_dict())

    def test_author_request_accepts_multiple_profile_urls_and_deduplicates_ids(self):
        request = ResearchRequest.from_dict({
            "mode": "author",
            "project_id": 7,
            "source": {
                "profile_urls": [
                    "https://www.xiaohongshu.com/user/profile/author-a?xsec_token=one",
                    "author-b",
                    "https://www.xiaohongshu.com/user/profile/author-a",
                ],
            },
        })

        self.assertEqual(request.author_ids, ["author-a", "author-b"])
        self.assertEqual(request.to_dict()["source"]["author_ids"], ["author-a", "author-b"])

    def test_legacy_single_author_source_remains_supported(self):
        request = ResearchRequest.from_dict({
            "mode": "author",
            "project_id": 7,
            "source": {"profile_url": "https://www.xiaohongshu.com/user/profile/legacy-author"},
        })

        self.assertEqual(request.author_ids, ["legacy-author"])

    def test_author_request_requires_explicit_authors_and_rejects_user_keywords(self):
        with self.assertRaisesRegex(ValueError, "does not support user keyword"):
            ResearchRequest.from_dict({
                "mode": "author",
                "project_id": 7,
                "source": {"author_ids": ["author-a"], "user_keywords": ["AI 产品经理"]},
            })

    def test_author_request_keeps_selected_collection_scopes(self):
        request = ResearchRequest.from_dict({
            "mode": "author",
            "source": {"author_ids": ["author-a", "author-b"]},
            "author_collection": {"scopes": ["basic_info", "posts", "basic_info"]},
        })

        self.assertEqual(request.author_collection_scopes, ["basic_info", "posts"])
        self.assertEqual(
            request.to_dict()["author_collection"]["scopes"],
            ["basic_info", "posts"],
        )

    def test_single_author_update_keeps_selected_scopes(self):
        request = ResearchRequest.from_dict({
            "mode": "author",
            "source": {"author_ids": ["author-a"]},
            "author_update": {
                "scopes": ["basic_info", "preview_posts", "detailed_posts", "basic_info"],
            },
            "limits": {"discovery": 12, "deep": 12},
        })

        self.assertEqual(
            request.author_update_scopes,
            ["basic_info", "preview_posts", "detailed_posts"],
        )
        self.assertEqual(
            request.to_dict()["author_update"]["scopes"],
            ["basic_info", "preview_posts", "detailed_posts"],
        )

    def test_author_update_requires_one_author_and_one_valid_scope(self):
        invalid_payloads = [
            {"source": {"author_ids": ["author-a"]}, "author_update": {"scopes": []}},
            {"source": {"author_ids": ["author-a", "author-b"]}, "author_update": {"scopes": ["basic_info"]}},
            {"source": {"author_ids": ["author-a"]}, "author_update": {"scopes": ["unknown"]}},
            {"source": {"author_ids": ["author-a"]}, "limits": {"deep": 0}, "author_update": {"scopes": ["detailed_posts"]}},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ResearchRequest.from_dict({"mode": "author", **payload})

    def test_research_quantities_are_not_capped_at_three_hundred(self):
        request = ResearchRequest.from_dict({
            "mode": "keyword",
            "source": {"user_keywords": ["AI 产品经理"]},
            "limits": {"discovery": 1200, "deep": 900},
            "keyword_limits": {"discovery": 1200, "deep": 900},
            "author_limits": {"discovery": 800, "deep": 700},
            "user_limits": {"discovery": 999},
        })

        self.assertEqual(request.keywords, [])
        self.assertEqual(request.user_keywords, ["AI 产品经理"])
        self.assertEqual(request.discovery_limit, 1200)
        self.assertEqual(request.deep_limit, 900)
        self.assertEqual(request.keyword_discovery_limit, 1200)
        self.assertEqual(request.keyword_deep_limit, 900)
        self.assertEqual(request.author_discovery_limit, 800)
        self.assertEqual(request.author_deep_limit, 700)
        self.assertEqual(request.user_discovery_limit, 999)

    def test_defaults_to_ocr_only_and_selective_count_ten(self):
        request = ResearchRequest.from_dict({
            "mode": "keyword",
            "project_id": 7,
            "source": {"keywords": ["AI 产品经理"]},
        })

        self.assertEqual(request.image_analysis, "ocr-only")
        self.assertEqual(request.vision_count, 10)
        self.assertEqual(request.to_dict()["image_analysis"]["vision_count"], 10)

    def test_mixed_request_keeps_separate_keyword_and_author_limits(self):
        request = ResearchRequest.from_dict({
            "mode": "mixed",
            "project_id": 7,
            "topic": "AI 产品经理",
            "source": {"keywords": ["AI 产品经理"], "author_ids": ["author-a"]},
            "keyword_limits": {"discovery": 20, "deep": 2},
            "author_limits": {"discovery": 80, "deep": 0},
        })

        self.assertEqual(request.topic, "AI 产品经理")
        self.assertEqual(request.keyword_discovery_limit, 20)
        self.assertEqual(request.keyword_deep_limit, 2)
        self.assertEqual(request.author_discovery_limit, 80)
        self.assertEqual(request.to_dict()["author_limits"], {"discovery": 80, "deep": 0})

    def test_mixed_request_requires_at_least_one_confirmed_source(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            ResearchRequest.from_dict({"mode": "mixed", "project_id": 7, "topic": "空项目", "source": {}})

    def test_rejects_external_or_malformed_author_sources(self):
        invalid = [
            "https://example.com/user/profile/author-a",
            "ftp://www.xiaohongshu.com/user/profile/author-a",
            "https://www.xiaohongshu.com/explore/author-a",
            "https://www.xiaohongshu.com/user/profile/author%2Fa",
            "https://www.xiaohongshu.com/user/profile/(author)",
            "ab",
            "author:a",
            "author/a",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ResearchRequest.from_dict({
                    "mode": "author",
                    "project_id": 1,
                    "source": {"profile_urls": [value]},
                })

    def test_accepts_raw_stable_id_and_canonical_profile_url(self):
        request = ResearchRequest.from_dict({
            "mode": "author",
            "project_id": 1,
            "source": {
                "author_ids": ["author-a"],
                "profile_urls": [
                    "https://m.xiaohongshu.com/user/profile/100000000000000000000001?xsec_token=test"
                ],
            },
        })
        self.assertEqual(request.author_ids, ["author-a", "100000000000000000000001"])

    def test_rejects_non_object_nested_values_and_non_finite_numbers(self):
        invalid_payloads = [
            {"mode": "keyword", "project_id": 1, "source": []},
            {"mode": "keyword", "project_id": 1, "source": {"keywords": "AI"}},
            {
                "mode": "keyword", "project_id": 1,
                "source": {"keywords": ["AI"]},
                "image_analysis": {"vision_ratio": float("nan")},
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ResearchRequest.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
