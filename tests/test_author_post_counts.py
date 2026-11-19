from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.socai import normalize_socai_result


class AuthorPostCountTests(unittest.TestCase):
    def test_socai_profile_normalizes_total_post_count(self):
        result = normalize_socai_result(
            {
                "author_id": "author-1",
                "profile": {
                    "display_name": "作者",
                    "notes_count": "1000",
                },
            },
            "author",
            "author-1",
        )

        self.assertEqual(result["profile"]["total_post_count"], 1000)


if __name__ == "__main__":
    unittest.main()
