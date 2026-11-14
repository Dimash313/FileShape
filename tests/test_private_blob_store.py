"""Contract tests for local private artifact staging (not a public API)."""
from concurrent.futures import ThreadPoolExecutor
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
