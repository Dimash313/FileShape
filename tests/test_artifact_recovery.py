"""Disk pressure, invalid-result reconciliation and descriptor lifetime tests."""
import gc
import os
import shutil
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from api.artifacts import ArtifactCapacity, ArtifactStore, ArtifactUnavailable

ID = 'A' * 32


class ArtifactRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def store(self, **kwargs):
        store = ArtifactStore(self.root, **kwargs)
        self.addCleanup(store.close)
        return store

    def complete(self, store):
        item = store.reserve(ID, 100)
        (item.path / 'result.txt').write_bytes(b'result')
        store.complete(ID, 'result.txt', 'text/plain')
        return item

    def test_disk_floor_rejects_before_creating_or_charging_artifact(self):
        store = self.store(min_free_bytes=100)
        with patch('api.artifacts.shutil.disk_usage', return_value=SimpleNamespace(free=149)):
            with self.assertRaises(ArtifactCapacity):
                store.reserve(ID, 50)
        self.assertEqual(store.reserved_bytes, 0)
        self.assertEqual(store.count, 0)
        self.assertFalse((store.path / ID).exists())
        with patch('api.artifacts.shutil.disk_usage', return_value=SimpleNamespace(free=150)):
            self.assertEqual(store.reserve(ID, 50).reserved_bytes, 50)

    def test_disk_usage_failure_does_not_create_a_reservation(self):
        store = self.store()
        with patch('api.artifacts.shutil.disk_usage', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                store.reserve(ID, 50)
        self.assertEqual(store.reserved_bytes, 0)
        self.assertEqual(store.count, 0)

    def test_reconciliation_drops_missing_completed_result_but_preserves_live_input(self):
        store = self.store()
        completed = self.complete(store)
        (completed.path / 'result.txt').unlink()
        pending = store.reserve('B' * 32, 100)
        (pending.path / 'source.txt').write_bytes(b'live source')
        self.assertEqual(store.reconcile(), 1)
        self.assertFalse(completed.path.exists())
        self.assertEqual((pending.path / 'source.txt').read_bytes(), b'live source')
        self.assertEqual(store.count, 1)
        self.assertEqual(store.reconcile(), 0)

    def test_unsafe_completed_result_pins_existing_download_until_it_closes(self):
        store = self.store()
        item = self.complete(store)
        lease, *_ = store.open_result(ID)
        target = self.root / 'unrelated.txt'
        target.write_bytes(b'unrelated private data')
        (item.path / 'result.txt').unlink()
        (item.path / 'result.txt').symlink_to(target)
        self.assertEqual(store.reconcile(), 1)
        with self.assertRaises(ArtifactUnavailable):
            store.open_result(ID)
        self.assertEqual(store.reserved_bytes, 6)
        self.assertEqual(lease.read(), b'result')
        lease.close()
        self.assertEqual(store.reserved_bytes, 0)
        self.assertFalse(item.path.exists())
        self.assertEqual(target.read_bytes(), b'unrelated private data')

    def test_abandoned_download_lease_releases_its_quota_and_descriptors(self):
        store = self.store()
        self.complete(store)
        lease, *_ = store.open_result(ID)
        fd = lease.fileno()
        store.discard(ID)
        self.assertEqual(store.reserved_bytes, 6)
        reference = weakref.ref(lease)
        del lease
        gc.collect()
        self.assertIsNone(reference())
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertEqual(store.reserved_bytes, 0)
        self.assertEqual(store.count, 0)

    def test_explicit_close_then_gc_does_not_decrement_lease_twice(self):
        store = self.store()
        item = self.complete(store)
        lease, *_ = store.open_result(ID)
        lease.close()
        self.assertEqual(item._leases, 0)
        del lease
        gc.collect()
        self.assertEqual(item._leases, 0)
        store.discard(ID)
        self.assertEqual(store.count, 0)
        self.assertEqual(store.reserved_bytes, 0)
        self.assertFalse(item.path.exists())

    def test_store_gc_does_not_release_lock_while_download_is_leased(self):
        store = ArtifactStore(self.root)
        self.complete(store)
        lease, *_ = store.open_result(ID)
        root_fd, lock_fd = store._root_fd, store._lock_fd
        reference = weakref.ref(store)
        store.close()
        del store
        gc.collect()
        self.assertIsNotNone(reference())
        os.fstat(lock_fd)
        lease.close()
        for fd in (root_fd, lock_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)
        del lease
        gc.collect()
        self.assertIsNone(reference())

    def test_failed_close_gc_releases_descriptors_for_future_orphan_cleanup(self):
        store = ArtifactStore(self.root)
        self.complete(store)
        root_fd, lock_fd = store._root_fd, store._lock_fd
        with patch.object(store._temp, 'cleanup', side_effect=PermissionError('transient')):
            with self.assertRaises(PermissionError):
                store.close()
        reference = weakref.ref(store)
        with self.assertWarns(ResourceWarning):
            del store
            gc.collect()
        self.assertIsNone(reference())
        for fd in (root_fd, lock_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_repeated_close_does_not_close_an_unrelated_reused_descriptor(self):
        store = ArtifactStore(self.root)
        store.close()
        unrelated = os.open('/dev/null', os.O_RDONLY)
        try:
            store.close()
            os.fstat(unrelated)
            del store
            gc.collect()
            os.fstat(unrelated)
        finally:
            os.close(unrelated)

    def test_permission_failure_does_not_starve_other_expired_results(self):
        store = self.store(ttl=1)
        with patch('api.artifacts.time.monotonic', return_value=10):
            damaged = self.complete(store)
            healthy = store.reserve('B' * 32, 100)
            (healthy.path / 'result.txt').write_bytes(b'other')
            store.complete('B' * 32, 'result.txt', 'text/plain')
        remove = shutil.rmtree
        def refuse_damaged(path, *args, **kwargs):
            if Path(path) == damaged.path:
                raise PermissionError('damaged directory needs operator attention')
            return remove(path, *args, **kwargs)
        with patch('api.artifacts.time.monotonic', return_value=11), \
             patch('api.artifacts.shutil.rmtree', side_effect=refuse_damaged):
            with self.assertRaises(PermissionError):
                store.prune()
            self.assertTrue(damaged.path.exists())
            self.assertFalse(healthy.path.exists())
            self.assertEqual(store.count, 1)
            self.assertEqual(store.reserved_bytes, 6)
        self.assertEqual(store.prune(), 1)
        self.assertEqual(store.reserved_bytes, 0)

    def test_directory_symlink_cannot_block_later_expired_result_cleanup(self):
        store = self.store(ttl=1)
        with patch('api.artifacts.time.monotonic', return_value=10):
            damaged = self.complete(store)
            healthy = store.reserve('B' * 32, 100)
            (healthy.path / 'result.txt').write_bytes(b'other')
            store.complete('B' * 32, 'result.txt', 'text/plain')
        moved = store.path / 'moved-by-operator'
        damaged.path.rename(moved)
        damaged.path.symlink_to(moved, target_is_directory=True)
        with patch('api.artifacts.time.monotonic', return_value=11):
            with self.assertRaises(OSError):
                store.reconcile()
            self.assertTrue(damaged.path.is_symlink())
            self.assertEqual((moved / 'result.txt').read_bytes(), b'result')
            self.assertFalse(healthy.path.exists())
            self.assertEqual(store.reserved_bytes, 6)
            self.assertEqual(store.count, 1)
            # Repeated sweeps retain the failed charge and report the fault.
            with self.assertRaises(OSError):
                store.reconcile()
            self.assertEqual(store.reserved_bytes, 6)
        # Restoring the owned directory makes cleanup retryable; no link target
        # is followed or removed while the invalid directory entry remains.
        damaged.path.unlink()
        moved.rename(damaged.path)
        self.assertEqual(store.prune(), 1)
        self.assertEqual(store.reserved_bytes, 0)
