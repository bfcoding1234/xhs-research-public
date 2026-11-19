from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research.vision import CodexVisionProvider, list_codex_image_models


class VisionProviderConcurrencyTests(unittest.TestCase):
    def test_lists_only_visible_codex_models_that_accept_images(self):
        payload = {
            "models": [
                {
                    "slug": "vision-model",
                    "display_name": "Vision Model",
                    "visibility": "list",
                    "input_modalities": ["text", "image"],
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [
                        {"effort": "low"}, {"effort": "medium"}, {"effort": "high"},
                    ],
                },
                {
                    "slug": "text-model",
                    "visibility": "list",
                    "input_modalities": ["text"],
                },
                {
                    "slug": "hidden-vision-model",
                    "visibility": "hidden",
                    "input_modalities": ["text", "image"],
                },
            ],
        }
        completed = subprocess.CompletedProcess(
            ["codex", "debug", "models"], 0, json.dumps(payload), "",
        )
        with patch("xhs_research.vision.subprocess.run", return_value=completed) as run:
            models = list_codex_image_models("codex")

        self.assertEqual(models, [{
            "id": "vision-model",
            "label": "Vision Model",
            "default_reasoning_effort": "medium",
            "reasoning_efforts": ["low", "medium", "high"],
        }])
        run.assert_called_once()

    def test_configured_provider_freezes_command_timeout_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "cover.jpg"
            image.write_bytes(b"cover")
            provider = CodexVisionProvider("codex", work_dir=root).configured(
                model="vision-model", reasoning_effort="high", timeout=900,
            )
            low_provider = provider.configured(
                model="vision-model", reasoning_effort="low", timeout=120,
            )
            shorter_timeout_provider = provider.configured(
                model="vision-model", reasoning_effort="high", timeout=120,
            )
            observed = {}

            def fake_run(args, _prompt, timeout, should_cancel=None):
                observed["args"] = args
                observed["timeout"] = timeout
                output = Path(args[args.index("-o") + 1])
                output.write_text(json.dumps({"cover_hook": "ok"}), encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch("xhs_research.vision.run_codex_process", side_effect=fake_run):
                result = provider.analyze("标题", [str(image)], root / "schema.json")

            self.assertEqual(result["cover_hook"], "ok")
            self.assertEqual(observed["timeout"], 900)
            self.assertEqual(
                observed["args"][observed["args"].index("--model") + 1],
                "vision-model",
            )
            self.assertIn('model_reasoning_effort="high"', observed["args"])
            self.assertEqual(
                provider.persisted_model_identity,
                "vision-model::reasoning=high",
            )
            self.assertNotEqual(
                provider.cache_key([str(image)], "cover"),
                low_provider.cache_key([str(image)], "cover"),
            )
            self.assertEqual(
                provider.cache_key([str(image)], "cover"),
                shorter_timeout_provider.cache_key([str(image)], "cover"),
            )

    def _run_concurrently(self, invoke, response_for_prompt):
        entered = threading.Barrier(2)
        written = threading.Barrier(2)
        outputs = []
        output_lock = threading.Lock()

        def fake_run(args, prompt, _timeout, should_cancel=None):
            output = Path(args[args.index("-o") + 1])
            with output_lock:
                outputs.append(output)
            entered.wait(timeout=2)
            output.write_text(json.dumps(response_for_prompt(prompt)), encoding="utf-8")
            written.wait(timeout=2)
            return subprocess.CompletedProcess(args, 0, "", "")

        values = []
        errors = []

        def worker(label):
            try:
                values.append((label, invoke(label)))
            except Exception as exc:
                errors.append(exc)

        with patch("xhs_research.vision.run_codex_process", side_effect=fake_run):
            threads = [threading.Thread(target=worker, args=(label,)) for label in ("甲", "乙")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertEqual(errors, [])
        self.assertEqual(len(values), 2)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(len(set(outputs)), 2)
        return dict(values)

    def test_analyze_and_batch_use_unique_output_files_for_identical_cache_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "same.jpg"
            image.write_bytes(b"same-image")
            provider = CodexVisionProvider("codex", work_dir=root)

            single = self._run_concurrently(
                lambda label: provider.analyze(f"标题{label}", [str(image)], root / "schema.json"),
                lambda prompt: {"marker": "甲" if "标题甲" in prompt else "乙"},
            )
            self.assertEqual(single["甲"]["marker"], "甲")
            self.assertEqual(single["乙"]["marker"], "乙")

            batch = self._run_concurrently(
                lambda _label: provider.analyze_batch(
                    [{"post_id": 1, "title": "相同", "image_paths": [str(image)]}],
                    root / "batch-schema.json",
                ),
                lambda _prompt: {
                    "results": [{
                        "post_id": 1,
                        "analysis": {"marker": threading.current_thread().name},
                    }],
                },
            )
            self.assertNotEqual(batch["甲"][1]["marker"], batch["乙"][1]["marker"])


if __name__ == "__main__":
    unittest.main()
