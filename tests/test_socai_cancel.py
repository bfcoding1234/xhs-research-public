import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.socai import SocaiError, _execute


class SocaiCancellationTests(unittest.TestCase):
    def test_not_profile_page_is_reported_as_recoverable_verification(self):
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('not_profile_page'); raise SystemExit(1)",
        ]

        with self.assertRaises(SocaiError) as raised:
            _execute(command, os.environ.copy(), 30)

        self.assertEqual(raised.exception.code, "verification_required")

    def test_certificate_verification_failure_is_not_treated_as_human_challenge(self):
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('certificate verify failed'); raise SystemExit(1)",
        ]

        with self.assertRaises(SocaiError) as raised:
            _execute(command, os.environ.copy(), 30)

        self.assertEqual(raised.exception.code, "socai_failed")

    def test_execute_terminates_subprocess_when_task_is_cancelled(self):
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        with self.assertRaisesRegex(SocaiError, "cancelled") as caught:
            _execute(command, os.environ.copy(), 30, lambda: True)
        self.assertEqual(caught.exception.code, "cancelled")


if __name__ == "__main__":
    unittest.main()
