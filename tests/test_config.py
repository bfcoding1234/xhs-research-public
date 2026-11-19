from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.config import Settings, is_loopback_host, load_settings


class CanonicalConfigurationTests(unittest.TestCase):
    def test_tilde_data_directory_is_expanded_once_for_every_consumer(self):
        with patch.dict(os.environ, {"XHS_RESEARCH_DATA_DIR": "~/xhs-canonical-test"}, clear=True):
            settings = load_settings()
        expected = (Path.home() / "xhs-canonical-test").resolve()
        self.assertEqual(settings.data_dir, expected)
        self.assertEqual(settings.database_path, expected / "research.sqlite3")
        self.assertEqual(settings.runs_dir, expected / "runs")

    def test_relative_and_symlink_data_directories_are_canonical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target.mkdir()
            link = root / "linked"
            link.symlink_to(target, target_is_directory=True)
            self.assertEqual(Settings(data_dir=link).data_dir, target.resolve())

            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(Settings(data_dir=Path("relative")).data_dir, (root / "relative").resolve())
            finally:
                os.chdir(previous)

    def test_only_loopback_hosts_are_accepted(self):
        for host in ("127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"):
            self.assertTrue(is_loopback_host(host), host)
        for host in ("0.0.0.0", "192.168.1.10", "example.com", "localhost.example"):
            self.assertFalse(is_loopback_host(host), host)


if __name__ == "__main__":
    unittest.main()
