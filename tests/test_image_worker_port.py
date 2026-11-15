"""Batch image worker contract: owner-scoped staged paths and real outputs.

Runs the real in-process worker function and generated PIL/PDF fixtures.
Request authorization and quotas remain enforced before worker admission.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from api import worker


class ImageWorkerPortTests(unittest.TestCase):
    def test_real_two_image_pdf_produced_through_domain_port(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGB", (20, 12), "white").save(root / "image_0.png")
            Image.new("RGB", (8, 24), "black").save(root / "image_1.png")
            result = worker.execute({
                "operation": "batch", "work": str(root),
                "suffixes": [".png", ".png"],
            })
            self.assertTrue(result["ok"])
            self.assertEqual(result["filename"], "fileshape_photos.pdf")
            self.assertGreater(result["bytes"], 0)
            file = root / result["filename"]
            self.assertEqual(result["bytes"], file.stat().st_size)
            self.assertEqual(len(PdfReader(str(file)).pages), 2)

    def test_worker_validates_each_input_before_domain_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGB", (8, 8)).save(root / "image_0.png")
            (root / "image_1.png").write_bytes(b"not a PNG")
            with patch.object(worker, "image_module") as adapter:
                with self.assertRaises(ValueError):
                    worker.execute({
                        "operation": "batch", "work": str(root),
                        "suffixes": [".png", ".png"],
                    })
                adapter.bundle_as_pdf.assert_not_called()

    def test_worker_passes_ordered_paths_and_expected_output_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGB", (8, 8)).save(root / "image_0.png")
            Image.new("RGB", (8, 8)).save(root / "image_1.png")

            def bundle(paths, target):
                self.assertEqual([p.name for p in paths],
                                 ["image_0.png", "image_1.png"])
                self.assertEqual(target, root / "fileshape_photos.pdf")
                target.write_bytes(b"%PDF-1.4\nmock test bytes")
                return 2

            with patch.object(worker, "image_module") as adapter:
                adapter.bundle_as_pdf.side_effect = bundle
                result = worker.execute({
                    "operation": "batch", "work": str(root),
                    "suffixes": [".png", ".png"],
                })
                adapter.bundle_as_pdf.assert_called_once()
            self.assertTrue(result["ok"])
            self.assertEqual(result["filename"], "fileshape_photos.pdf")


if __name__ == "__main__":
    unittest.main()
