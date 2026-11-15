"""Bounded, opt-in image concurrency measurement regressions.

Only the two-worker / smoke profile executes in CI. The near-cap workload
is deliberately not started by these tests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import image_concurrency
from benchmarks.image_resources import create_fixtures


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "image_concurrency.py"


class ImageConcurrencyBenchmarkTests(unittest.TestCase):
    def test_rejects_unbounded_worker_or_sampling_configuration(self):
        for kwargs in (
            {"workers": 1},
            {"workers": 4},
            {"memory_mib": 100},
            {"timeout": 0},
            {"interval_ms": 0},
            {"interval_ms": 1001},
            {"aggregate_memory_mib": 20},
            {"fixture_style": "random"},
        ):
            arguments = {
                "profile": "smoke",
                "fixture_style": "blocks",
                "workers": 2,
                "memory_mib": 512,
                "timeout": 20,
                "interval_ms": 25,
                "aggregate_memory_mib": 1024,
            }
            arguments.update(kwargs)
            with self.subTest(invalid=kwargs):
                with self.assertRaises((ValueError, RuntimeError)):
                    image_concurrency.run_parallel(**arguments)

    @unittest.skipUnless(sys.platform == "linux", "Linux procfs")
    def test_real_two_worker_smoke_reports_separate_measured_results(self):
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--workers", "2",
                "--profile", "smoke", "--fixture-style", "blocks",
                "--timeout", "30", "--memory-mib", "512",
                "--interval-ms", "10",
            ],
            cwd=ROOT, capture_output=True, text=True, timeout=40,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-1000:])
        data = json.loads(completed.stdout)
        print(
            "IMAGE_CONCURRENT_SMOKE_JSON: " + json.dumps(data, sort_keys=True),
            flush=True,
        )
        self.assertEqual(data["workers"], 2)
        self.assertEqual(data["fixture_style"], "blocks")
        self.assertEqual(data["profile"], "smoke")
        self.assertEqual(data["input_pixels_per_worker"], 15_232)
        self.assertEqual(data["platform"], "Linux")
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["per_child_memory_limit_mib"], 512)
        self.assertEqual(data["aggregate_sample_budget_mib"], 1024)
        self.assertGreaterEqual(data["sample_count"], 1)
        self.assertGreaterEqual(data["peak_sampled_children_rss_mib"], 0)
        self.assertGreater(data["sum_individual_peak_rss_mib"], 0)
        self.assertLessEqual(
            data["peak_sampled_children_rss_mib"],
            data["sum_individual_peak_rss_mib"] + 1.0,
        )
        self.assertGreater(data["elapsed_seconds"], 0)
        self.assertGreaterEqual(data["total_cpu_seconds"], 0)
        self.assertIn("sampled", data["rss_scope"])
        for report in data["results"]:
            self.assertEqual(report["result_pages"], 2)
            self.assertEqual(report["fixture_style"], "blocks")
            self.assertGreater(report["result_bytes"], 0)
            self.assertGreater(report["peak_rss_mib"], 0)

    @unittest.skipUnless(sys.platform == "linux", "Linux procfs")
    def test_failure_kills_children_and_removes_all_temp_directories(self):
        original_temp = tempfile.TemporaryDirectory
        locations = []

        def tracked_temp(*args, **kwargs):
            temp = original_temp(*args, **kwargs)
            locations.append(Path(temp.name))
            return temp

        def fixtures_with_corrupt_second(directory, profile, style):
            result = create_fixtures(directory, profile, style)
            if directory.name == "worker_1":
                result[0].write_bytes(b"invalid PNG contents")
            return result

        with patch.object(
            image_concurrency.tempfile, "TemporaryDirectory",
            side_effect=tracked_temp,
        ), patch.object(
            image_concurrency, "create_fixtures",
            side_effect=fixtures_with_corrupt_second,
        ):
            with self.assertRaises(RuntimeError):
                image_concurrency.run_parallel(
                    "smoke", "solid", 2, 512, 30, 10,
                )
        self.assertEqual(len(locations), 1)
        self.assertFalse(locations[0].exists())

    @unittest.skipUnless(sys.platform == "linux", "Linux procfs")
    def test_proc_rss_sampler_reads_current_process(self):
        current = image_concurrency._rss_bytes(os.getpid())
        self.assertGreater(current, 0)


if __name__ == "__main__":
    unittest.main()
