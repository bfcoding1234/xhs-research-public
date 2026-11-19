from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.server import build_rerun_payload


class RerunPayloadTests(unittest.TestCase):
    def setUp(self):
        self.source_task = {
            "input_json": {
                "mode": "author",
                "project_id": 7,
                "created_from": "web",
                "source": {"author_id": "old-author"},
                "limits": {"discovery": 50, "deep": 0},
                "image_analysis": {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0},
                "force_refresh": False,
            }
        }

    def test_allows_task_configuration_but_keeps_project_fields_immutable(self):
        result = build_rerun_payload(self.source_task, {
            "created_from": "web",
            "configuration": {
                "mode": "keyword",
                "collector": "auto",
                "project_id": 99,
                "name": "不可覆盖",
                "source": {"author_id": "new-author"},
                "limits": {"discovery": 80, "deep": 5},
                "image_analysis": {"mode": "vision-selective", "vision_ratio": 0.4, "vision_count": 20},
                "force_refresh": True,
            },
        }, 7)

        self.assertEqual(result["mode"], "author")
        self.assertNotIn("collector", result)
        self.assertEqual(result["project_id"], 7)
        self.assertNotIn("name", result)
        self.assertEqual(result["source"]["author_id"], "new-author")
        self.assertEqual(result["limits"], {"discovery": 80, "deep": 5})
        self.assertEqual(result["image_analysis"], {"mode": "ocr-only", "vision_ratio": 0, "vision_count": 0})
        self.assertTrue(result["force_refresh"])

    def test_rejects_non_object_nested_configuration(self):
        with self.assertRaisesRegex(ValueError, "configuration.limits"):
            build_rerun_payload(self.source_task, {"configuration": {"limits": 80}}, 7)

    def test_update_cannot_enable_inline_image_understanding(self):
        result = build_rerun_payload(self.source_task, {
            "configuration": {
                "image_analysis": {"mode": "vision-all", "vision_ratio": 1, "vision_count": 300},
            },
        }, 7)

        self.assertEqual(result["image_analysis"]["mode"], "ocr-only")

    def test_mixed_update_accepts_separate_limits_and_topic(self):
        source_task = {"input_json": {
            "mode": "mixed", "project_id": 7, "topic": "旧主题",
            "source": {"keywords": ["旧词"], "author_ids": []},
            "keyword_limits": {"discovery": 20, "deep": 0},
            "author_limits": {"discovery": 50, "deep": 0},
        }}
        result = build_rerun_payload(source_task, {"configuration": {
            "topic": "新主题",
            "source": {"keywords": ["新词"], "author_ids": ["author-a"]},
            "keyword_limits": {"discovery": 30, "deep": 1},
            "author_limits": {"discovery": 80, "deep": 0},
        }}, 7)

        self.assertEqual(result["mode"], "mixed")
        self.assertEqual(result["topic"], "新主题")
        self.assertEqual(result["keyword_limits"], {"discovery": 30, "deep": 1})
        self.assertEqual(result["author_limits"], {"discovery": 80, "deep": 0})


if __name__ == "__main__":
    unittest.main()
