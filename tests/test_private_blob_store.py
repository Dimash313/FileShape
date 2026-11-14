"""Contract tests for local private artifact staging (not a public API)."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import secrets
import threading
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import unittest

from api.private_blob_store import (
    BlobCapacity, BlobUnavailable, PrivateBlobStore,
)


OWNER = 101
OTHER = 202
JOB = "J" * 32
OTHER_JOB = "K" * 32


class PrivateBlobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.now = time.time()

    def new_store(self, **kwargs):
        return PrivateBlobStore(self.root, **kwargs)

    def test_owner_scoped_stage_bind_and_reopen(self):
        with self.new_store() as store:
            ref = store.stage_input(OWNER, b"sensitive test input", now=self.now)
            self.assertTrue((self.root / ref).is_file())
            self.assertEqual((self.root / ref).stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, JOB, ref, now=self.now + 1)
            with self.assertRaises(BlobUnavailable):
                store.bind_input(OTHER, JOB, ref, now=self.now + 1)
            self.assertTrue(store.bind_input(OWNER, JOB, ref, now=self.now + 1))
            self.assertFalse(store.bind_input(OWNER, JOB, ref, now=self.now + 2))
            with self.assertRaises(BlobUnavailable):
                store.bind_input(OWNER, OTHER_JOB, ref, now=self.now + 3)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OTHER, JOB, ref, now=self.now + 3)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, OTHER_JOB, ref, now=self.now + 3)
            self.assertEqual(
                store.read_input(OWNER, JOB, ref, now=self.now + 3),
                b"sensitive test input",
            )
            self.assertFalse(store.delete(OTHER, ref, job_id=JOB))
        with self.new_store() as reopened:
            self.assertEqual(
                reopened.read_input(OWNER, JOB, ref, now=self.now + 3),
                b"sensitive test input",
            )
            self.assertTrue(reopened.delete(OWNER, ref, job_id=JOB))
            self.assertFalse((self.root / ref).exists())
            with self.assertRaises(BlobUnavailable):
                reopened.read_input(OWNER, JOB, ref, now=self.now + 4)

    def test_candidate_never_publicly_published_and_is_job_scoped(self):
        with self.new_store() as store:
            ref = store.stage_candidate(OWNER, JOB, b"untrusted result", now=self.now)
            self.assertEqual(
                store.read_candidate(OWNER, JOB, ref, now=self.now + 1),
                b"untrusted result",
            )
            with self.assertRaises(BlobUnavailable):
                store.read_candidate(OWNER, OTHER_JOB, ref, now=self.now + 1)
            with self.assertRaises(BlobUnavailable):
                store.read_candidate(OTHER, JOB, ref, now=self.now + 1)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, JOB, ref, now=self.now + 1)
            self.assertFalse(hasattr(store, "publish_output"))
            self.assertFalse(hasattr(store, "read_published"))
            self.assertTrue(store.delete(OWNER, ref, job_id=JOB))

    def test_expiry_and_purge(self):
        with self.new_store() as store:
            ref = store.stage_input(OWNER, b"expiry", ttl=5, now=self.now)
            with self.assertRaises(BlobUnavailable):
                store.bind_input(OWNER, JOB, ref, now=self.now + 5)
            self.assertEqual(store.purge_expired(now=self.now + 5), 1)
            self.assertEqual(store.purge_expired(now=self.now + 6), 0)
            self.assertFalse((self.root / ref).exists())

    def test_file_and_total_resource_limits(self):
        with self.new_store(max_bytes=10, max_blob_bytes=8, max_entries=2) as store:
            first = store.stage_input(OWNER, b"hello", now=self.now)
            second = store.stage_input(OWNER, b"world", now=self.now)
            with self.assertRaises(BlobCapacity):
                store.stage_input(OWNER, b"one", now=self.now)
            with self.assertRaises(ValueError):
                store.stage_input(OWNER, b"oversized!", now=self.now)
            with self.assertRaises(ValueError):
                store.stage_input(OWNER, b"", now=self.now)
            self.assertEqual(len(list(self.root.glob("[A-Za-z0-9_-]" * 32))), 2)
            self.assertTrue(store.delete(OWNER, first))
            ref = store.stage_input(OWNER, b"one", now=self.now)
            self.assertNotEqual(ref, second)

    def test_bad_ids_owners_and_ttl_fail_closed(self):
        with self.new_store() as store:
            for owner in (0, True, "101", -1):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    store.stage_input(owner, b"x")
            for data in (bytearray(b"x"), "x", None):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    store.stage_input(OWNER, data)
            for ttl in (0, -1, True, float("inf"), 1e8):
                with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                    store.stage_input(OWNER, b"x", ttl=ttl)
            with self.assertRaises(ValueError):
                store.stage_candidate(OWNER, "../../etc/passwd", b"x")
            ref = store.stage_input(OWNER, b"x", now=self.now)
            for bad in ("../evil", "a" * 31, "", None):
                with self.subTest(bad=bad), self.assertRaises(BlobUnavailable):
                    store.bind_input(OWNER, JOB, bad)
            self.assertFalse(store.delete(OTHER, ref))

    def test_symlink_and_inode_tampering_rejected(self):
        with self.new_store() as store:
            ref = store.stage_input(OWNER, b"private", now=self.now)
            store.bind_input(OWNER, JOB, ref, now=self.now)
            path = self.root / ref
            target = Path(self.temp.name) / "secret"
            target.write_bytes(b"do not touch")
            path.unlink()
            path.symlink_to(target)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, JOB, ref, now=self.now + 1)
            self.assertEqual(target.read_bytes(), b"do not touch")
            path.unlink()
            os.link(target, path)
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, JOB, ref, now=self.now + 1)
            path.unlink()
            self.assertTrue(store.delete(OWNER, ref))
            self.assertEqual(target.read_bytes(), b"do not touch")

    def test_hash_verification_catches_same_size_corruption(self):
        with self.new_store() as store:
            ref = store.stage_input(OWNER, b"safe", now=self.now)
            store.bind_input(OWNER, JOB, ref, now=self.now)
            (self.root / ref).write_bytes(b"evil")
            with self.assertRaises(BlobUnavailable):
                store.read_input(OWNER, JOB, ref, now=self.now + 1)

    def test_disk_content_never_stored_in_sqlite_metadata(self):
        secret = b"VERY_SECRET_FILE_PAYLOAD_DO_NOT_PERSIST_IN_SQLITE"
        with self.new_store() as store:
            ref = store.stage_input(OWNER, secret, now=self.now)
            cols = {
                row[1] for row in store._db.execute(
                    "PRAGMA table_info(staged_blobs)"
                )
            }
            self.assertNotIn("payload", cols)
            self.assertNotIn("filename", cols)
            self.assertNotIn("path", cols)
            store.bind_input(OWNER, JOB, ref, now=self.now)
        self.assertNotIn(secret, (self.root / "blobs.sqlite3").read_bytes())

    def test_two_connections_share_atomic_byte_limit(self):
        with self.new_store(max_bytes=10, max_blob_bytes=8) as first:
            with self.new_store(max_bytes=10, max_blob_bytes=8) as second:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(store.stage_input, OWNER, b"1234567", now=self.now)
                        for store in (first, second)
                    ]
                    results = []
                    for future in futures:
                        try:
                            results.append(future.result())
                        except BlobCapacity:
                            results.append(None)
                self.assertEqual(len([x for x in results if x]), 1)
                self.assertEqual(
                    first._db.execute(
                        "SELECT COALESCE(SUM(byte_count),0) FROM staged_blobs"
                    ).fetchone()[0], 7,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX safety only")
    def test_reject_public_or_symlink_root(self):
        self.root.mkdir(mode=0o700)
        self.root.chmod(0o755)
        with self.assertRaises(RuntimeError):
            self.new_store()
        self.root.chmod(0o700)
        symlink = Path(self.temp.name) / "link"
        symlink.symlink_to(self.root)
        with self.assertRaises((RuntimeError, OSError)):
            PrivateBlobStore(symlink)

    def test_closed_store_rejects_access(self):
        store = self.new_store()
        store.close()
        with self.assertRaises(RuntimeError):
            store.stage_input(OWNER, b"x")


    @staticmethod
    def write_untracked(path, data=b"orphan", *, mtime):
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.utime(path, (mtime, mtime))

    def test_orphan_sweep_recovers_untracked_crash_files_only(self):
        with self.new_store() as store:
            live = store.stage_input(OWNER, b"live, private", now=self.now)
            store.bind_input(OWNER, JOB, live, now=self.now)
            staged_candidate = store.stage_candidate(
                OWNER, JOB, b"candidate", now=self.now,
            )
            orphan = secrets.token_urlsafe(24)
            self.write_untracked(
                self.root / orphan, mtime=self.now - 700,
            )
            (self.root / "README").write_text("not a blob")
            report = store.sweep_orphans(
                now=self.now, minimum_age_seconds=300,
            )
            self.assertEqual(report.removed, 1)
            self.assertGreaterEqual(report.preserved_live, 2)
            self.assertFalse((self.root / orphan).exists())
            self.assertEqual(
                store.read_input(OWNER, JOB, live, now=self.now + 1),
                b"live, private",
            )
            self.assertEqual(
                store.read_candidate(
                    OWNER, JOB, staged_candidate, now=self.now + 1,
                ), b"candidate",
            )
            self.assertTrue((self.root / "README").exists())
            self.assertTrue((self.root / "blobs.sqlite3").exists())
            self.assertEqual(store.sweep_orphans(now=self.now).removed, 0)

    def test_orphan_sweep_respects_age_and_bounded_batches(self):
        with self.new_store() as store:
            recent = secrets.token_urlsafe(24)
            self.write_untracked(self.root / recent, mtime=self.now)
            old_refs = [secrets.token_urlsafe(24) for _ in range(3)]
            for ref in old_refs:
                self.write_untracked(
                    self.root / ref, mtime=self.now - 1000,
                )
            first = store.sweep_orphans(
                now=self.now, minimum_age_seconds=300, delete_limit=1,
            )
            self.assertEqual(first.removed, 1)
            self.assertTrue((self.root / recent).exists())
            self.assertEqual(sum((self.root / ref).exists() for ref in old_refs), 2)
            second = store.sweep_orphans(
                now=self.now, minimum_age_seconds=300,
            )
            self.assertEqual(second.removed, 2)
            self.assertGreaterEqual(second.skipped_young, 1)
            self.assertTrue((self.root / recent).exists())
            self.assertEqual(
                store.sweep_orphans(now=self.now + 310).removed, 1,
            )
            self.assertFalse((self.root / recent).exists())

    def test_symlinks_hardlinks_and_unknown_files_survive_sweep(self):
        with self.new_store() as store:
            outside = Path(self.temp.name) / "outside"
            outside.write_bytes(b"external")
            os.chmod(outside, 0o600)
            link_name = secrets.token_urlsafe(24)
            hard_name = secrets.token_urlsafe(24)
            (self.root / link_name).symlink_to(outside)
            os.link(outside, self.root / hard_name)
            (self.root / "..unsafe").write_bytes(b"control")
            report = store.sweep_orphans(
                now=self.now + 1000, minimum_age_seconds=60,
            )
            self.assertEqual(report.removed, 0)
            self.assertEqual(report.skipped_unsafe, 2)
            self.assertTrue((self.root / link_name).is_symlink())
            self.assertTrue((self.root / hard_name).exists())
            self.assertEqual(outside.read_bytes(), b"external")
            self.assertTrue((self.root / "..unsafe").exists())

    def test_sweep_fails_closed_if_root_path_is_replaced(self):
        with self.new_store() as store:
            replacement = Path(self.temp.name) / "renamed"
            self.root.rename(replacement)
            self.root.mkdir(mode=0o700)
            orphan = secrets.token_urlsafe(24)
            self.write_untracked(self.root / orphan, mtime=self.now - 1000)
            with self.assertRaises(RuntimeError):
                store.sweep_orphans(now=self.now)
            self.assertTrue((self.root / orphan).exists())

    def test_sweep_invalid_limits_do_not_delete_files(self):
        with self.new_store() as store:
            orphan = secrets.token_urlsafe(24)
            self.write_untracked(self.root / orphan, mtime=self.now - 1000)
            for kw in (
                {"minimum_age_seconds": -1},
                {"minimum_age_seconds": 0},
                {"minimum_age_seconds": 59},
                {"minimum_age_seconds": float("nan")},
                {"minimum_age_seconds": True},
                {"scan_limit": 0}, {"scan_limit": True},
                {"delete_limit": 1001}, {"delete_limit": "20"},
                {"now": True},
            ):
                with self.subTest(kwargs=kw), self.assertRaises(ValueError):
                    store.sweep_orphans(**kw)
                self.assertTrue((self.root / orphan).exists())

    def test_sweep_does_not_delete_inflight_blob_from_other_connection(self):
        written = threading.Event()
        entered_sweep = threading.Event()
        resume_stage = threading.Event()
        with self.new_store() as stage, self.new_store() as sweep:
            original_write = stage._write_private
            original_sweep_open = sweep._open

            def paused_write(ref, payload):
                original_write(ref, payload)
                written.set()
                if not resume_stage.wait(timeout=10):
                    raise RuntimeError("Timed out while testing stage race")

            def observed_sweep_open():
                entered_sweep.set()
                return original_sweep_open()

            with patch.object(stage, "_write_private", side_effect=paused_write):
                with patch.object(sweep, "_open", side_effect=observed_sweep_open):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        future_stage = executor.submit(
                            stage.stage_input, OWNER, b"active upload", now=self.now,
                        )
                        try:
                            self.assertTrue(written.wait(timeout=10))
                            future_sweep = executor.submit(
                                sweep.sweep_orphans,
                                now=self.now + 1000,
                                minimum_age_seconds=60,
                            )
                            # Ensure the sweeper entered while the file is
                            # physically present but not committed in SQLite.
                            self.assertTrue(entered_sweep.wait(timeout=10))
                            self.assertFalse(future_sweep.done())
                        finally:
                            resume_stage.set()
                        reference = future_stage.result(timeout=15)
                        report = future_sweep.result(timeout=15)
            self.assertEqual(report.removed, 0)
            self.assertEqual(
                stage._db.execute(
                    "SELECT count(*) FROM staged_blobs WHERE ref=?",
                    (reference,),
                ).fetchone()[0], 1,
            )
            stage.bind_input(OWNER, JOB, reference, now=self.now + 1)
            self.assertEqual(
                stage.read_input(OWNER, JOB, reference, now=self.now + 1),
                b"active upload",
            )
