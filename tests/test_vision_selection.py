from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.vision import select_vision_candidates


def posts(count):
    return [
        {
            "post_id": index,
            "title": f"帖子 {index}",
            "popularity_percentile": index / max(count, 1),
            "author_id": f"author-{index % 3}",
            "note_type": "normal",
            "ocr_text": "有文字" if index % 2 else "",
        }
        for index in range(1, count + 1)
    ]


class VisionSelectionTests(unittest.TestCase):
    def test_uses_count_when_it_is_larger_than_ratio_target(self):
        selected = select_vision_candidates(posts(10), ratio=0.2, count=10)

        self.assertEqual(len(selected), 10)

    def test_uses_ratio_when_it_is_larger_than_count(self):
        selected = select_vision_candidates(posts(100), ratio=0.2, count=10)

        self.assertEqual(len(selected), 20)

    def test_never_selects_more_than_available_posts(self):
        selected = select_vision_candidates(posts(6), ratio=0.2, count=10)

        self.assertEqual(len(selected), 6)

    def test_respects_maximum_count_even_when_ratio_or_minimum_is_larger(self):
        selected = select_vision_candidates(posts(100), ratio=0.8, count=60, max_count=30)

        self.assertEqual(len(selected), 30)


if __name__ == "__main__":
    unittest.main()
