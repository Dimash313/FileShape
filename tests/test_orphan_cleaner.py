"""Fair bounded crash cleanup without leaking per-root directory cursors."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import gc
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

from api.workspaces import MAX_SCAN, STALE_SECONDS, OrphanCleaner, Workspace


class OrderedScans:
    """Deterministic root iteration; real child rmtree scans stay unchanged."""
    def __init__(self, roots):
        self.identities = {(path.stat().st_dev, path.stat().st_ino) for path in roots}
        self.original = os.scandir
        self.scans = []

    def add_root(self, root):
        info = root.stat()
        self.identities.add((info.st_dev, info.st_ino))

    def __call__(self, path):
        if not isinstance(path, int):
            return self.original(path)
        info = os.fstat(path)
        if (info.st_dev, info.st_ino) not in self.identities:
            return self.original(path)
        held = self.original(path)
        entries = iter(SimpleNamespace(name=name) for name in sorted(os.listdir(path)))
        tracked = SimpleNamespace(closed=False, names=[], fd=path)
        class Scan:
            def __iter__(self):
                return self
            def __next__(self):
                entry = next(entries)
                tracked.names.append(entry.name)
                return entry
            def close(self):
                tracked.closed = True
                held.close()
        self.scans.append(tracked)
        return Scan()


@unittest.skipUnless(os.name == "posix", "Requires POSIX fd-relative traversal and flock")
class OrphanCleanerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "root"
        self.root.mkdir(mode=0o700)
        self.now = time.time()
        self.old = self.now - STALE_SECONDS - 100

    def orphan(self, name, root=None):
        path = (root or self.root) / name
        path.mkdir(mode=0o700)
        (path / ".active.lock").touch(mode=0o600)
        (path / "source.txt").write_bytes(b"private input")
        os.utime(path, (self.old, self.old))
        return path

    def cleaner(self, root=None, max_scan=MAX_SCAN):
        cleaner = OrphanCleaner(root or self.root, max_scan=max_scan)
        self.addCleanup(cleaner.close)
        return cleaner

    def test_more_than_five_hundred_preserved_entries_cannot_starve_a_later_orphan(self):
        for index in range(MAX_SCAN + 2):
            # Mix recent valid workspaces and unrelated entries; both consume
            # scan budget but must allow the cursor to progress past them.
            name = f"000-{index:04d}"
            (self.root / name).touch(mode=0o600)
        recent = self.orphan("fileshape_api_recent")
        os.utime(recent, (self.now, self.now))
        old = self.orphan("fileshape_background_zold")
        scans = OrderedScans([self.root])
        cleaner = self.cleaner()
        with patch("api.workspaces.os.scandir", side_effect=scans):
            self.assertEqual(cleaner.sweep(self.now), 0)
            self.assertEqual(len(scans.scans), 1)
            self.assertEqual(len(scans.scans[0].names), MAX_SCAN)
            self.assertFalse(scans.scans[0].closed)
            self.assertTrue(old.exists())
            self.assertEqual(cleaner.sweep(self.now), 1)
            self.assertEqual(len(scans.scans), 1, "Second batch must resume the same cursor")
            self.assertLessEqual(len(scans.scans[0].names) - MAX_SCAN, MAX_SCAN)
            self.assertTrue(scans.scans[0].closed)
            self.assertTrue(recent.exists())
            self.assertFalse(old.exists())
            self.assertEqual(cleaner.sweep(self.now), 0)
        self.assertTrue(all((self.root / f"000-{index:04d}").is_file() for index in range(MAX_SCAN + 2)))

    def test_active_recent_unsafe_and_unrelated_entries_are_preserved(self):
        active = self.orphan("fileshape_api_active")
        active_lock = os.open(active / ".active.lock", os.O_RDONLY)
        self.addCleanup(os.close, active_lock)
        fcntl.flock(active_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recent = self.orphan("fileshape_batch_recent")
        os.utime(recent, (self.now, self.now))
        unsafe = self.orphan("fileshape_background_unsafe")
        unsafe.chmod(0o755)
        unsafe_lock = self.orphan("fileshape_api_unsafe_lock")
        (unsafe_lock / ".active.lock").unlink()
        (unsafe_lock / ".active.lock").mkdir(mode=0o700)
        missing_lock = self.orphan("fileshape_api_missing_lock")
        (missing_lock / ".active.lock").unlink()
        os.utime(missing_lock, (self.now, self.now))
        unrelated = self.orphan("operator-data")
        old = self.orphan("fileshape_background_old")
        self.assertEqual(self.cleaner().sweep(self.now), 1)
        self.assertFalse(old.exists())
        for path in (active, recent, unsafe, unsafe_lock, missing_lock, unrelated):
            self.assertTrue(path.exists(), f"Cleanup removed protected entry {path.name}")
            self.assertEqual((path / "source.txt").read_bytes(), b"private input")

    def test_symlink_and_hardlink_locks_never_follow_or_modify_outside_targets(self):
        outside = self.orphan("outside", root=Path(self.temporary.name))
        linked_directory = self.root / "fileshape_api_directory_link"
        linked_directory.symlink_to(outside, target_is_directory=True)
        outside_lock = outside / ".active.lock"
        outside_lock.chmod(0o644)
        for name, hard in (("fileshape_batch_symlink", False), ("fileshape_background_hardlink", True)):
            path = self.orphan(name)
            (path / ".active.lock").unlink()
            if hard:
                os.link(outside_lock, path / ".active.lock")
            else:
                (path / ".active.lock").symlink_to(outside_lock)
            os.utime(path, (self.old, self.old))
        self.assertEqual(self.cleaner().sweep(self.now), 0)
        self.assertTrue(linked_directory.is_symlink())
        self.assertEqual((outside / "source.txt").read_bytes(), b"private input")
        self.assertTrue((self.root / "fileshape_batch_symlink").exists())
        self.assertTrue((self.root / "fileshape_background_hardlink").exists())
        self.assertEqual(outside_lock.stat().st_mode & 0o777, 0o644,
                         "Unsafe linked lock inode must never be chmodded")

    def test_new_workspace_lock_is_private_under_permissive_umasks(self):
        for mask in (0o022, 0):
            with self.subTest(mask=oct(mask)):
                previous = os.umask(mask)
                try:
                    with patch("api.workspaces.workspace_root", return_value=self.root):
                        work = Workspace(prefix="fileshape_api_")
                finally:
                    os.umask(previous)
                try:
                    path = Path(work.name)
                    self.assertEqual((path / ".active.lock").stat().st_mode & 0o777, 0o600)
                    os.utime(path, (self.old, self.old))
                    self.assertEqual(self.cleaner().sweep(self.now), 0)
                    self.assertTrue(path.exists())
                finally:
                    work.cleanup()

    def test_abandoned_workspace_gc_releases_directory_and_marker_descriptors(self):
        with patch("api.workspaces.workspace_root", return_value=self.root):
            work = Workspace(prefix="fileshape_api_")
        directory_fd = work._directory_fd
        marker_lock = work._lock  # Hold the file object so its own GC cannot hide a leak.
        marker_fd = marker_lock.fileno()
        path = Path(work.name)
        reference = weakref.ref(work)
        with self.assertWarns(ResourceWarning):
            del work
            gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(marker_lock.closed)
        self.assertFalse(path.exists())
        for fd in (directory_fd, marker_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_repeated_workspace_cleanup_and_gc_do_not_close_reused_descriptors(self):
        with patch("api.workspaces.workspace_root", return_value=self.root):
            work = Workspace(prefix="fileshape_api_")
        work.cleanup()
        unrelated = [os.open("/dev/null", os.O_RDONLY) for _ in range(2)]
        try:
            work.cleanup()
            del work
            gc.collect()
            for fd in unrelated:
                os.fstat(fd)
        finally:
            for fd in unrelated:
                os.close(fd)

    def test_legacy_owned_0644_locks_are_tightened_and_active_ones_still_survive(self):
        old = self.orphan("fileshape_api_legacy_old")
        active = self.orphan("fileshape_background_legacy_active")
        (old / ".active.lock").chmod(0o644)
        (active / ".active.lock").chmod(0o644)
        active_lock = os.open(active / ".active.lock", os.O_RDONLY)
        self.addCleanup(os.close, active_lock)
        fcntl.flock(active_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.cleaner().sweep(self.now), 1)
        self.assertFalse(old.exists(), "A legacy 0644 lock must not retain stale files forever")
        self.assertTrue(active.exists())
        self.assertEqual((active / ".active.lock").stat().st_mode & 0o777, 0o600)
        self.assertEqual((active / "source.txt").read_bytes(), b"private input")

    def test_old_unlocked_generation_without_marker_can_be_removed(self):
        orphan = self.orphan("fileshape_background_missing_marker")
        (orphan / ".active.lock").unlink()
        os.utime(orphan, (self.old, self.old))
        self.assertEqual(self.cleaner().sweep(self.now), 1)
        self.assertFalse(orphan.exists())

    def test_active_generation_directory_lock_survives_missing_marker(self):
        with patch("api.workspaces.workspace_root", return_value=self.root):
            work = Workspace(prefix="fileshape_background_")
        try:
            path = Path(work.name)
            (path / "source.txt").write_bytes(b"active input")
            (path / ".active.lock").unlink()
            os.utime(path, (self.old, self.old))
            self.assertEqual(self.cleaner().sweep(self.now), 0)
            self.assertEqual((path / "source.txt").read_bytes(), b"active input")
        finally:
            work.cleanup()

    def test_partial_deletion_losing_marker_is_reconsidered_after_grace(self):
        orphan = self.orphan("fileshape_background_partial")
        cleaner = self.cleaner()
        def partial_remove(*args, **kwargs):
            (orphan / ".active.lock").unlink()
            raise OSError("temporary removal failure")
        with patch("api.workspaces.shutil.rmtree", side_effect=partial_remove):
            self.assertEqual(cleaner.sweep(self.now), 0)
        self.assertTrue((orphan / "source.txt").exists())
        self.assertFalse((orphan / ".active.lock").exists())
        self.assertEqual(cleaner.sweep(self.now + STALE_SECONDS + 100), 1)
        self.assertFalse(orphan.exists())

    def test_fifo_lock_does_not_block_a_sweep(self):
        path = self.orphan("fileshape_background_fifo")
        (path / ".active.lock").unlink()
        os.mkfifo(path / ".active.lock", 0o600)
        os.utime(path, (self.old, self.old))
        # A regressed blocking FIFO open must fail this test promptly rather
        # than hanging the entire Python test process during shutdown.
        script = "from pathlib import Path; import sys; from api.workspaces import OrphanCleaner; c=OrphanCleaner(Path(sys.argv[1])); assert c.sweep(float(sys.argv[2])) == 0; c.close()"
        child = subprocess.run([sys.executable, "-c", script, str(self.root), str(self.now)],
                               capture_output=True, timeout=3)
        self.assertEqual(child.returncode, 0, child.stderr.decode())
        self.assertTrue(path.exists())

    def test_age_and_lock_identity_are_rechecked_after_acquiring_flock(self):
        path = self.orphan("fileshape_background_race")
        original = fcntl.flock
        def made_recent(fd, operation):
            original(fd, operation)
            os.utime(path, (self.now, self.now))
        with patch("api.workspaces.fcntl.flock", side_effect=made_recent):
            self.assertEqual(self.cleaner().sweep(self.now), 0)
        self.assertTrue(path.exists())
        os.utime(path, (self.old, self.old))
        def replaced_lock(fd, operation):
            original(fd, operation)
            (path / ".active.lock").unlink()
            (path / ".active.lock").touch(mode=0o600)
            os.utime(path, (self.old, self.old))
        with patch("api.workspaces.fcntl.flock", side_effect=replaced_lock):
            self.assertEqual(self.cleaner().sweep(self.now), 0)
        self.assertTrue(path.exists())

    def test_exhaustion_and_close_release_cursor_and_parent_fd(self):
        (self.root / "a").touch()
        (self.root / "b").touch()
        scans = OrderedScans([self.root])
        cleaner = self.cleaner(max_scan=1)
        with patch("api.workspaces.os.scandir", side_effect=scans):
            cleaner.sweep(self.now)
            fd = scans.scans[0].fd
            self.assertFalse(scans.scans[0].closed)
            cleaner.sweep(self.now)
            cleaner.sweep(self.now)
            self.assertTrue(scans.scans[0].closed)
            with self.assertRaises(OSError):
                os.fstat(fd)
            cleaner.sweep(self.now)
            self.assertEqual(len(scans.scans), 2)
            last_fd = scans.scans[-1].fd
            cleaner.close()
            cleaner.close()
            self.assertTrue(scans.scans[-1].closed)
            with self.assertRaises(OSError):
                os.fstat(last_fd)
            self.assertEqual(cleaner.sweep(self.now), 0)
            self.assertEqual(len(scans.scans), 2)

    def test_abandoned_cleaner_gc_closes_cursor_and_parent_descriptor(self):
        (self.root / "a").touch()
        (self.root / "b").touch()
        scans = OrderedScans([self.root])
        cleaner = OrphanCleaner(self.root, max_scan=1)
        with patch("api.workspaces.os.scandir", side_effect=scans):
            cleaner.sweep(self.now)
            cursor = scans.scans[0]
            self.assertFalse(cursor.closed)
            reference = weakref.ref(cleaner)
            del cleaner
            gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(cursor.closed)
        with self.assertRaises(OSError):
            os.fstat(cursor.fd)

    def test_replaced_root_resets_cursor_and_invalid_root_closes_it(self):
        (self.root / "a").touch()
        (self.root / "b").touch()
        scans = OrderedScans([self.root])
        cleaner = self.cleaner(max_scan=1)
        with patch("api.workspaces.os.scandir", side_effect=scans):
            cleaner.sweep(self.now)
            previous = scans.scans[0]
            moved = Path(self.temporary.name) / "former-root"
            self.root.rename(moved)
            self.root.mkdir(mode=0o700)
            orphan = self.orphan("fileshape_background_new_root")
            scans.add_root(self.root)
            self.assertEqual(cleaner.sweep(self.now), 1)
            self.assertTrue(previous.closed)
            self.assertFalse(orphan.exists())
            self.assertTrue((moved / "b").exists())
            current = scans.scans[-1]
            self.root.chmod(0o755)
            with self.assertRaises(ValueError):
                cleaner.sweep(self.now)
            self.assertTrue(current.closed)
            with self.assertRaises(OSError):
                os.fstat(current.fd)

    def test_two_instances_keep_independent_root_positions(self):
        other = Path(self.temporary.name) / "other-root"
        other.mkdir(mode=0o700)
        for root in (self.root, other):
            (root / "a").touch()
            (root / "b").touch()
            self.orphan("fileshape_background_orphan", root=root)
        scans = OrderedScans([self.root, other])
        first = self.cleaner(max_scan=1)
        second = self.cleaner(root=other, max_scan=2)
        with patch("api.workspaces.os.scandir", side_effect=scans):
            self.assertEqual(first.sweep(self.now), 0)
            self.assertEqual(second.sweep(self.now), 0)
            self.assertEqual(first.sweep(self.now), 0)
            self.assertEqual(second.sweep(self.now), 1)
            self.assertEqual(first.sweep(self.now), 1)
        self.assertFalse((self.root / "fileshape_background_orphan").exists())
        self.assertFalse((other / "fileshape_background_orphan").exists())

    def test_close_waits_for_an_in_progress_sweep_then_prevents_reopening(self):
        (self.root / "unrelated").touch()
        cleaner = self.cleaner(max_scan=1)
        entered = threading.Event()
        release = threading.Event()
        closing = threading.Event()
        def pause_entry(entry, cutoff):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Test did not release sweep")
            return False
        def close():
            closing.set()
            cleaner.close()
        with patch.object(cleaner, "_remove_if_stale", side_effect=pause_entry):
            with ThreadPoolExecutor(max_workers=2) as pool:
                sweep = pool.submit(cleaner.sweep, self.now)
                try:
                    self.assertTrue(entered.wait(2))
                    shutdown = pool.submit(close)
                    self.assertTrue(closing.wait(2))
                    self.assertFalse(shutdown.done())
                finally:
                    release.set()
                self.assertEqual(sweep.result(timeout=3), 0)
                shutdown.result(timeout=3)
        self.assertEqual(cleaner.sweep(self.now), 0)

    def test_invalid_limits_and_time_cannot_force_an_unbounded_or_early_sweep(self):
        for value in (0, -1, MAX_SCAN + 1, True, 1.5):
            with self.assertRaises(ValueError):
                OrphanCleaner(self.root, max_scan=value)
        cleaner = self.cleaner()
        for value in (float("nan"), float("inf"), True, "now"):
            with self.assertRaises(ValueError):
                cleaner.sweep(value)
