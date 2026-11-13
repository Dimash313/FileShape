"""Artifact quota, expiry, safe file opens and cleanup regression tests."""
import os
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api.artifacts import ArtifactCapacity, ArtifactStore, ArtifactUnavailable, MAX_RESULT_BYTES

FIRST = "A" * 32
SECOND = "B" * 32
THIRD = "C" * 32


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)

    def store(self, **kwargs):
        store = ArtifactStore(self.parent, **kwargs)
        self.addCleanup(store.close)
        return store

    def complete(self, store, job_id=FIRST, payload=b"result"):
        item = store.reserve(job_id, max(32, len(payload)))
        (item.path / "result.txt").write_bytes(payload)
        store.complete(job_id, "result.txt", "text/plain")
        return item

    def test_quota_and_entry_limit_release_only_after_deletion(self):
        store = self.store(max_bytes=64, max_entries=1)
        self.complete(store)
        self.assertEqual(store.reserved_bytes, 6)
        with self.assertRaises(ArtifactCapacity):
            store.reserve(SECOND, 1)
        store.discard(FIRST)
        store.discard(FIRST)
        store.reserve(SECOND, 64)
        with self.assertRaises(ArtifactCapacity):
            store.reserve(THIRD, 1)
        self.assertEqual(store.reserved_bytes, 64)

    def test_result_private_and_fd_survives_expiry(self):
        store = self.store(ttl=60)
        with patch("api.artifacts.time.monotonic", return_value=1000):
            item = self.complete(store)
            stream, size, mime, filename = store.open_result(FIRST)
        self.addCleanup(stream.close)
        self.assertEqual((size, mime, filename), (6, "text/plain", "result.txt"))
        self.assertEqual((item.path / filename).stat().st_mode & 0o777, 0o600)
        with patch("api.artifacts.time.monotonic", return_value=1060):
            self.assertEqual(store.prune(), 1)
            self.assertTrue(item.path.exists())
            self.assertEqual(store.reserved_bytes, 6)
            with self.assertRaises(ArtifactUnavailable):
                store.open_result(FIRST)
        self.assertEqual(stream.read(), b"result")
        self.assertEqual(store.reserved_bytes, 6)
        stream.close()
        self.assertFalse(item.path.exists())
        self.assertEqual(store.reserved_bytes, 0)

    def test_expired_download_pins_quota_until_last_lease_closes(self):
        store = self.store(ttl=1, max_bytes=32)
        with patch("api.artifacts.time.monotonic", return_value=10):
            item = self.complete(store)
            first, *_ = store.open_result(FIRST)
            second, *_ = store.open_result(FIRST)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        with patch("api.artifacts.time.monotonic", return_value=11):
            store.prune()
            with self.assertRaises(ArtifactCapacity):
                store.reserve(SECOND, 32)
            self.assertEqual(first.read(), b"result")
            first.close()
            self.assertTrue(item.path.exists())
            self.assertEqual(store.reserved_bytes, 6)
            with self.assertRaises(ArtifactUnavailable):
                store.open_result(FIRST)
            second.close()
            second.close()
            self.assertFalse(item.path.exists())
            store.reserve(SECOND, 32)

    def test_close_keeps_existing_download_charged_until_fd_closes(self):
        store = self.store()
        item = self.complete(store)
        stream, *_ = store.open_result(FIRST)
        self.addCleanup(stream.close)
        store.close()
        self.assertTrue(store.path.exists())
        self.assertEqual(store.reserved_bytes, 6)
        self.assertEqual(stream.read(), b"result")
        stream.close()
        self.assertFalse(store.path.exists())
        self.assertEqual(store.reserved_bytes, 0)

    def test_failed_discard_is_retried_by_prune_without_releasing_quota_early(self):
        store = self.store()
        item = store.reserve(FIRST, 32)
        (item.path / "source.txt").write_bytes(b"input")
        with patch("api.artifacts.shutil.rmtree", side_effect=PermissionError("temporarily busy")):
            with self.assertRaises(PermissionError):
                store.discard(FIRST)
        self.assertTrue(item.path.exists())
        self.assertEqual(store.reserved_bytes, 32)
        self.assertEqual(store.prune(), 1)
        self.assertFalse(item.path.exists())
        self.assertEqual(store.reserved_bytes, 0)
        self.assertEqual(store.prune(), 0)

    def test_failed_expiry_delete_is_retried_while_live_lease_stays_protected(self):
        store = self.store(ttl=1)
        with patch("api.artifacts.time.monotonic", return_value=10):
            item = self.complete(store)
            second = self.complete(store, SECOND)
            stream, *_ = store.open_result(SECOND)
        self.addCleanup(stream.close)
        with patch("api.artifacts.time.monotonic", return_value=11):
            with patch("api.artifacts.shutil.rmtree", side_effect=PermissionError("temporarily busy")):
                with self.assertRaises(PermissionError):
                    store.prune()
            self.assertEqual(store.reserved_bytes, 12)
            # The first failed pass still marks the other expired lease as
            # unavailable, while its open fd keeps the bytes charged.
            with self.assertRaises(ArtifactUnavailable):
                store.open_result(SECOND)
            self.assertEqual(store.prune(), 1)
            self.assertFalse(item.path.exists())
            self.assertTrue(second.path.exists())
            self.assertEqual(store.prune(), 0)
            self.assertEqual(stream.read(), b"result")
            self.assertEqual(store.reserved_bytes, 6)
            stream.close()
            self.assertEqual(store.reserved_bytes, 0)

    def test_close_failure_preserves_lock_and_quota_for_safe_retry(self):
        store = self.store()
        self.complete(store)
        lock_fd = store._lock_fd
        with patch.object(store._temp, "cleanup", side_effect=PermissionError("temporarily busy")):
            with self.assertRaises(PermissionError):
                store.close()
        self.assertEqual(store.reserved_bytes, 6)
        self.assertTrue(store.path.exists())
        os.fstat(lock_fd)
        other = os.open(store.path / ".active.lock", os.O_RDONLY)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(other)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(FIRST)
        store.close()
        self.assertFalse(store.path.exists())
        self.assertEqual(store.reserved_bytes, 0)
        with self.assertRaises(OSError):
            os.fstat(lock_fd)

    def test_download_close_cleanup_failure_can_be_retried_by_store_close(self):
        store = self.store()
        self.complete(store)
        stream, *_ = store.open_result(FIRST)
        self.addCleanup(stream.close)
        store.close()
        with patch.object(store._temp, "cleanup", side_effect=PermissionError("temporarily busy")):
            with self.assertRaises(PermissionError):
                stream.close()
        self.assertTrue(stream.closed)
        self.assertTrue(store.path.exists())
        self.assertEqual(store.reserved_bytes, 6)
        store.close()
        self.assertFalse(store.path.exists())
        self.assertEqual(store.reserved_bytes, 0)

    def test_active_input_never_expires(self):
        store = self.store(ttl=1)
        with patch("api.artifacts.time.monotonic", return_value=1):
            active = store.reserve(FIRST, 32)
            (active.path / "source.txt").write_bytes(b"input")
        with patch("api.artifacts.time.monotonic", return_value=100000):
            self.assertEqual(store.prune(), 0)
            with self.assertRaises(ArtifactUnavailable):
                store.open_result(FIRST)
        self.assertTrue(active.path.exists())

    def test_expired_open_deletes_before_reporting_unavailable(self):
        store = self.store(ttl=1)
        with patch("api.artifacts.time.monotonic", return_value=10):
            item = self.complete(store)
        with patch("api.artifacts.time.monotonic", return_value=11):
            with self.assertRaises(ArtifactUnavailable):
                store.open_result(FIRST)
        self.assertFalse(item.path.exists())
        self.assertEqual(store.count, 0)

    def test_symlink_and_hardlink_output_rejected(self):
        store = self.store()
        item = store.reserve(FIRST, 32)
        target = self.parent / "outside"
        target.write_bytes(b"secret")
        output = item.path / "result.txt"
        output.symlink_to(target)
        with self.assertRaises(ArtifactUnavailable):
            store.complete(FIRST, "result.txt", "text/plain")
        output.unlink()
        os.link(target, output)
        with self.assertRaises(ArtifactUnavailable):
            store.complete(FIRST, "result.txt", "text/plain")
        self.assertEqual(target.read_bytes(), b"secret")

    def test_replaced_download_path_fails_closed(self):
        store = self.store()
        item = self.complete(store)
        output = item.path / "result.txt"
        output.unlink()
        target = self.parent / "outside"
        target.write_bytes(b"secret")
        output.symlink_to(target)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(FIRST)
        self.assertEqual(target.read_bytes(), b"secret")

    def test_directory_symlink_rejected(self):
        store = self.store()
        item = self.complete(store)
        moved = store.path / "moved"
        item.path.rename(moved)
        item.path.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(FIRST)

    def test_size_and_total_reservation_enforced(self):
        store = self.store(max_bytes=2 * MAX_RESULT_BYTES)
        item = store.reserve(FIRST, MAX_RESULT_BYTES + 1)
        with (item.path / "result.txt").open("wb") as output:
            output.truncate(MAX_RESULT_BYTES + 1)
        with self.assertRaises(ArtifactUnavailable):
            store.complete(FIRST, "result.txt", "text/plain")
        store.discard(FIRST)
        item = store.reserve(FIRST, 8)
        (item.path / "source.txt").write_bytes(b"12345678")
        (item.path / "result.txt").write_bytes(b"result")
        with self.assertRaises(ArtifactCapacity):
            store.complete(FIRST, "result.txt", "text/plain")

    def test_untrusted_ids_names_and_mime_are_rejected(self):
        store = self.store()
        for value in ("../" + FIRST, "/" + FIRST, "A" * 31, "A" * 33, "", 1):
            with self.subTest(value=value), self.assertRaises(ArtifactUnavailable):
                store.reserve(value, 32)
        item = store.reserve(FIRST, 32)
        (item.path / "result.txt").write_bytes(b"result")
        for name in ("../result.txt", "/tmp/result.txt", "a/b", ".hidden", "a..b"):
            with self.subTest(name=name), self.assertRaises(ArtifactUnavailable):
                store.complete(FIRST, name, "text/plain")
        with self.assertRaises(ArtifactUnavailable):
            store.complete(FIRST, "result.txt", "text/plain\r\nX-Evil: yes")

    def test_closed_store_is_empty_and_close_idempotent(self):
        store = self.store()
        self.complete(store)
        root = store.path
        store.close()
        store.close()
        self.assertFalse(root.exists())
        self.assertEqual(store.reserved_bytes, 0)
        with self.assertRaises(ArtifactUnavailable):
            store.reserve(SECOND, 1)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(FIRST)

    def test_root_permissions_and_symlinks(self):
        unsafe = self.parent / "unsafe"
        unsafe.mkdir()
        unsafe.chmod(0o755)
        with self.assertRaises(ValueError):
            ArtifactStore(unsafe)
        link = self.parent / "link"
        link.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            ArtifactStore(link)

    def test_result_open_rejects_non_private_file(self):
        store = self.store()
        item = self.complete(store)
        (item.path / "result.txt").chmod(0o644)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(FIRST)

    def test_settings_and_duplicate_reservations(self):
        for kwargs in ({"max_bytes": 0}, {"max_entries": 0}, {"ttl": 0}, {"ttl": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ArtifactStore(self.parent, **kwargs)
        store = self.store()
        store.reserve(FIRST, 32)
        with self.assertRaises(ValueError):
            store.reserve(FIRST, 32)
        with self.assertRaises(ValueError):
            store.reserve(SECOND, True)
