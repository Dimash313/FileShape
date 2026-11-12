"""Capacity configuration regression tests; never run ten heavy workers on CI."""
import os
import unittest
from unittest.mock import patch

from api.server import configured_worker_capacity


class CapacityConfigurationTests(unittest.TestCase):
    def test_default_remains_safe_until_server_sized(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_worker_capacity(), 3)

    def test_can_configure_ten_workers(self):
        with patch.dict(os.environ, {"FILESHAPE_MAX_CONCURRENT_JOBS": "10"}):
            self.assertEqual(configured_worker_capacity(), 10)

    def test_rejects_unsafe_or_invalid_capacity(self):
        for value in ("0", "-1", "11", "abc", "", "1.5"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"FILESHAPE_MAX_CONCURRENT_JOBS": value}):
                    with self.assertRaises(RuntimeError):
                        configured_worker_capacity()


if __name__ == "__main__":
    unittest.main()
