"""Smoke tests for the opt-in, isolated image resource benchmark."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from benchmarks.image_resources import (
    MAX_TOTAL_PIXELS, PROFILES, create_fixtures, validate_profile,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "image_resources.py"


class ImageResourceBenchmarkTests(unittest.TestCase):
    def test_benchmark_profiles_respect_pixel_and_count_budgets(self):
        for name in PROFILES:
            with self.subTest(profile=name):
                values = validate_profile(name)
                self.assertGreaterEqual(len(values), 2)
                self.assertLessEqual(len(values), 8)
                self.assertLessEqual(
                    sum(width * height for _, width, height in values),
                    MAX_TOTAL_PIXELS,
                )
        near = validate_profile("near-cap")
        self.assertGreater(sum(w * h for _, w, h in near), 18_000_000)

    def test_abstract_blocks_are_generated_inside_input_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            sources = create_fixtures(Path(folder), "smoke", "blocks")
            self.assertEqual(len(sources), 2)
            with Image.open(sources[0]) as png:
                self.assertEqual(png.format, "PNG")
                self.assertNotEqual(png.getpixel((0, 0)), png.getpixel((20, 20)))
            self.assertTrue(all(file.is_file() for file in sources))
            self.assertLess(sum(file.stat().st_size for file in sources), 20 * 1024 * 1024)

    def test_unrecognized_fixture_style_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Invalid fixture style"):
                create_fixtures(Path(folder), "smoke", "unknown")
            self.assertEqual(list(Path(folder).iterdir()), [])

    @unittest.skipUnless(sys.platform == "linux", "Linux peak RSS and RLIMIT_AS")
    def test_isolated_smoke_report_is_measured_and_has_bounded_inputs(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--profile", "smoke", "--timeout", "30"],
            cwd=ROOT, capture_output=True, text=True, timeout=40,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-1000:])
        result = json.loads(proc.stdout)
        # These numbers come from a real subprocess running FileShape and
        # are safe to print: fixtures and paths are entirely synthetic.
        print("IMAGE_BENCHMARK_SMOKE_JSON: " + json.dumps(result, sort_keys=True), flush=True)
        self.assertEqual(result["profile"], "smoke")
        self.assertEqual(result["result_pages"], result["input_count"])
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["platform"], "Linux")
        self.assertEqual(result["total_input_pixels"], 96 * 72 + 80 * 104)
        self.assertGreater(result["total_input_bytes"], 0)
        self.assertLessEqual(result["total_input_bytes"], 20 * 1024 * 1024)
        self.assertGreater(result["result_bytes"], 0)
        self.assertGreater(result["peak_rss_mib"], 0)
        self.assertGreaterEqual(result["elapsed_seconds"], 0)
        self.assertGreaterEqual(result["cpu_seconds"], 0)
        self.assertIn("imports", result["rss_scope"])

    def test_invalid_timeout_does_not_launch_child(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--profile", "smoke", "--timeout", "0"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--timeout", proc.stderr)


if __name__ == "__main__":
    unittest.main()
