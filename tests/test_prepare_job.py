"""Run with: python -m unittest discover -s tests -v"""

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_job.py"
SPEC = importlib.util.spec_from_file_location("prepare_job", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# A genuine 1 x 1 PNG fixture, kept in the test to avoid external dependencies.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jBz8AAAAASUVORK5CYII="
)


class PrepareJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.styles = list(MODULE.load_styles())
        if len(cls.styles) < 2:
            raise AssertionError("The published registry must include at least two styles.")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "photo.png"
        self.source.write_bytes(PNG)
        self.output = self.root / "job"

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            env=self.utf8_environment(),
            check=False,
        )

    @staticmethod
    def utf8_environment():
        import os
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

    def standard_args(self):
        return ["--input", self.source, "--style", self.styles[0], "--output", self.output]

    def assert_rejected_without_output(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".*-staging-*")))

    def test_two_sources_two_styles_and_source_integrity(self):
        source_two = self.root / "second photo.PNG"
        source_two.write_bytes(PNG)
        anchors = self.root / "anchors.txt"
        anchors.write_text("保留人物所在位置与原有轮廓。", encoding="utf-8")
        hashes_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.source, source_two, anchors)}
        result = self.run_cli(
            *self.standard_args(), "--input", source_two, "--style", self.styles[1],
            "--anchors", anchors,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        job = json.loads((self.output / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["schema_version"], "1.0")
        self.assertEqual(job["status"], "awaiting_image_tool")
        self.assertEqual(len(job["tasks"]), 4)
        expected_pairs = {(str(p.resolve()), style) for p in (self.source, source_two) for style in self.styles[:2]}
        self.assertEqual({(t["source"], t["style_id"]) for t in job["tasks"]}, expected_pairs)
        self.assertEqual(list((self.output / "images").iterdir()), [])
        for task in job["tasks"]:
            self.assertEqual(task["status"], "pending")
            self.assertFalse(Path(task["prompt_file"]).is_absolute())
            self.assertFalse((self.output / task["suggested_output"]).exists())
            prompt = (self.output / task["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("must attach the actual source image", prompt)
            self.assertIn("Gallery images", prompt)
            self.assertIn("保留人物所在位置与原有轮廓。", prompt)
            self.assertNotIn(str(self.root), prompt)
        for path, expected_hash in hashes_before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)

    def test_preserve_rejects_changed_ratio(self):
        result = self.run_cli(*self.standard_args(), "--ratio", "4:5")
        self.assert_rejected_without_output(result)
        self.assertIn("poster", result.stderr)

    def test_poster_accepts_ratio_and_empty_output(self):
        self.output.mkdir()
        result = self.run_cli(*self.standard_args(), "--layout", "poster", "--ratio", "4:5", "--strength", "high")
        self.assertEqual(result.returncode, 0, result.stderr)
        job = json.loads((self.output / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["settings"]["ratio"], "4:5")
        self.assertEqual(job["settings"]["strength"], "high")
        prompt = (self.output / job["tasks"][0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("poster composition at a 4:5 aspect ratio", prompt)

    def test_fake_image_rejected(self):
        self.source.write_text("This is text with a .png name.", encoding="utf-8")
        self.assert_rejected_without_output(self.run_cli(*self.standard_args()))

    def test_mismatched_image_extension_rejected(self):
        jpeg_name = self.root / "wrong.jpg"
        jpeg_name.write_bytes(PNG)
        result = self.run_cli("--input", jpeg_name, "--style", self.styles[0], "--output", self.output)
        self.assert_rejected_without_output(result)

    def test_unknown_style_rejected(self):
        result = self.run_cli(*self.standard_args(), "--style", "not-a-real-style")
        self.assert_rejected_without_output(result)
        self.assertIn("Unknown style", result.stderr)

    def test_later_invalid_input_does_not_write_partial_job(self):
        result = self.run_cli(*self.standard_args(), "--input", self.root / "missing.png")
        self.assert_rejected_without_output(result)

    def test_nonempty_output_is_preserved(self):
        self.output.mkdir()
        keep = self.output / "keep.txt"
        keep.write_text("existing work", encoding="utf-8")
        result = self.run_cli(*self.standard_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(keep.read_text(encoding="utf-8"), "existing work")
        self.assertEqual(list(self.output.iterdir()), [keep])

    def test_output_cannot_replace_source(self):
        original = self.source.read_bytes()
        result = self.run_cli("--input", self.source, "--style", self.styles[0], "--output", self.source)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_bytes(), original)

    def test_output_cannot_replace_anchors(self):
        anchors = self.root / "anchors.txt"
        anchors.write_text("Keep the source composition.", encoding="utf-8")
        result = self.run_cli(
            "--input", self.source, "--style", self.styles[0],
            "--anchors", anchors, "--output", anchors,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(anchors.read_text(encoding="utf-8"), "Keep the source composition.")

    def test_list_styles_needs_no_input_or_output(self):
        result = self.run_cli("--list-styles")
        self.assertEqual(result.returncode, 0, result.stderr)
        for style_id in self.styles:
            self.assertIn(style_id, result.stdout)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
