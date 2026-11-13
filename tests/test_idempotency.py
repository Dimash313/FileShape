"""Durable owner-scoped admission claims, validation and restart semantics."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from api.durable_jobs import DurableJobStore, IdempotencyConflict, IdempotencyPending
from api.job_runtime import JobRuntime
from api.jobs import JobCapacityExceeded, JobNotFound

KEY = "a" * 64
FINGERPRINT = "b" * 64
OTHER_FINGERPRINT = "c" * 64
OTHER_KEY = "d" * 64


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "jobs.sqlite3"

    def test_pending_claim_is_not_published_or_overwritten(self):
        with DurableJobStore(self.path) as store:
            first, is_new = store.create_idempotent(11, KEY, FINGERPRINT)
            self.assertTrue(is_new)
            with self.assertRaises(IdempotencyPending):
                store.create_idempotent(11, KEY, FINGERPRINT)
            with self.assertRaises(IdempotencyConflict):
                store.create_idempotent(11, KEY, OTHER_FINGERPRINT)
            self.assertEqual(store.get(first.job_id, 11).state, "queued")
            self.assertEqual(store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 1)
            self.assertEqual(store._db.execute("SELECT accepted FROM admissions").fetchone()[0], 0)

    def test_accepted_duplicate_survives_reopen_and_returns_current_terminal_state(self):
        with DurableJobStore(self.path) as store:
            original, _ = store.create_idempotent(11, KEY, FINGERPRINT)
            store.accept_admission(original.job_id, 11, KEY)
            store.transition(original.job_id, 11, "processing")
            store.transition(original.job_id, 11, "failed")
        with DurableJobStore(self.path) as reopened:
            replay, is_new = reopened.create_idempotent(11, KEY, FINGERPRINT)
            self.assertFalse(is_new)
            self.assertEqual(replay.job_id, original.job_id)
            self.assertEqual(replay.state, "failed")
            self.assertEqual(replay.created_at, original.created_at)
            with self.assertRaises(IdempotencyConflict):
                reopened.create_idempotent(11, KEY, OTHER_FINGERPRINT)

    def test_completed_and_cancelled_duplicates_remain_same_job(self):
        with DurableJobStore(self.path) as store:
            for owner, terminal in ((11, "completed"), (12, "cancelled")):
                original, _ = store.create_idempotent(owner, KEY, FINGERPRINT)
                store.accept_admission(original.job_id, owner, KEY)
                store.transition(original.job_id, owner, "processing")
                store.transition(original.job_id, owner, terminal)
                replay, is_new = store.create_idempotent(owner, KEY, FINGERPRINT)
                self.assertFalse(is_new)
                self.assertEqual((replay.job_id, replay.state), (original.job_id, terminal))

    def test_same_key_is_scoped_to_owner_and_foreign_acceptance_cannot_publish_it(self):
        with DurableJobStore(self.path) as store:
            first, _ = store.create_idempotent(11, KEY, FINGERPRINT)
            second, _ = store.create_idempotent(12, KEY, FINGERPRINT)
            self.assertNotEqual(first.job_id, second.job_id)
            for job_id, owner, key in ((first.job_id, 12, KEY),
                                       (first.job_id, 11, OTHER_KEY),
                                       ("missing", 11, KEY),
                                       (first.job_id, True, KEY)):
                with self.subTest(owner=owner, key=key):
                    with self.assertRaises(JobNotFound):
                        store.accept_admission(job_id, owner, key)
            self.assertFalse(store.discard_queued(first.job_id, 12))
            store.accept_admission(second.job_id, 12, KEY)
            replay, is_new = store.create_idempotent(12, KEY, FINGERPRINT)
            self.assertFalse(is_new)
            self.assertEqual(replay.job_id, second.job_id)
            with self.assertRaises(IdempotencyPending):
                store.create_idempotent(11, KEY, FINGERPRINT)
            with self.assertRaises(JobNotFound):
                store.get(first.job_id, 12)

    def test_two_connections_cannot_both_claim_the_same_pending_operation(self):
        with DurableJobStore(self.path) as first, DurableJobStore(self.path) as second:
            barrier = threading.Barrier(2)
            def claim(store):
                barrier.wait(timeout=5)
                try:
                    return store.create_idempotent(11, KEY, FINGERPRINT)
                except IdempotencyPending:
                    return "pending"
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(claim, store) for store in (first, second)]
                results = [future.result(timeout=10) for future in futures]
            claimed = [item for item in results if item != "pending"]
            self.assertEqual(len(claimed), 1)
            self.assertTrue(claimed[0][1])
            self.assertEqual(results.count("pending"), 1)
            self.assertEqual(first._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual(first._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 1)

    def test_capacity_applies_to_new_claims_but_not_to_accepted_replays(self):
        with DurableJobStore(self.path, max_entries=1) as store:
            original, _ = store.create_idempotent(11, KEY, FINGERPRINT)
            with self.assertRaises(JobCapacityExceeded):
                store.create_idempotent(11, OTHER_KEY, FINGERPRINT)
            with self.assertRaises(JobCapacityExceeded):
                store.create(11)
            with self.assertRaises(IdempotencyPending):
                store.create_idempotent(11, KEY, FINGERPRINT)
            store.accept_admission(original.job_id, 11, KEY)
            replay, is_new = store.create_idempotent(11, KEY, FINGERPRINT)
            self.assertFalse(is_new)
            self.assertEqual(replay.job_id, original.job_id)
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 1)

    def test_rejection_discard_cascades_and_allows_a_fresh_claim(self):
        with DurableJobStore(self.path, max_entries=1) as store:
            original, _ = store.create_idempotent(11, KEY, FINGERPRINT)
            # A validated admission can still fail the synchronous queue submit;
            # no request received 202, so its queued claim must be discardable.
            store.accept_admission(original.job_id, 11, KEY)
            self.assertTrue(store.discard_queued(original.job_id, 11))
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 0)
            replacement, is_new = store.create_idempotent(11, KEY, FINGERPRINT)
            self.assertTrue(is_new)
            self.assertNotEqual(replacement.job_id, original.job_id)

    def test_terminal_expiry_cascades_claim_and_releases_its_key(self):
        with DurableJobStore(self.path, max_entries=1, retention_seconds=60) as store:
            with patch("api.durable_jobs.time.time", return_value=1000):
                original, _ = store.create_idempotent(11, KEY, FINGERPRINT)
                store.accept_admission(original.job_id, 11, KEY)
                store.transition(original.job_id, 11, "failed")
            with patch("api.durable_jobs.time.time", return_value=1060):
                replacement, is_new = store.create_idempotent(11, KEY, FINGERPRINT)
                self.assertTrue(is_new)
                self.assertNotEqual(replacement.job_id, original.job_id)
                self.assertEqual(store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
                self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 1)
                with self.assertRaises(JobNotFound):
                    store.get(original.job_id, 11)

    def test_invalid_hashes_and_owners_never_allocate_rows(self):
        with DurableJobStore(self.path) as store:
            invalid = (None, 1, True, "", "a" * 63, "a" * 65,
                       "A" * 64, "g" * 64, "я" * 64, "a" * 63 + "\n")
            for value in invalid:
                with self.subTest(value=repr(value)):
                    with self.assertRaises(ValueError):
                        store.create_idempotent(11, value, FINGERPRINT)
                    with self.assertRaises(ValueError):
                        store.create_idempotent(11, KEY, value)
            for owner in (None, True, 0, -1, "11", 2**63):
                with self.assertRaises(ValueError):
                    store.create_idempotent(owner, KEY, FINGERPRINT)
            self.assertEqual(store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 0)

    def test_mapping_insert_failure_rolls_back_the_job_and_capacity(self):
        with DurableJobStore(self.path, max_entries=1) as store:
            store._db.execute("""CREATE TRIGGER reject_admission BEFORE INSERT ON admissions
                                 BEGIN SELECT RAISE(ABORT, 'admission unavailable'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                store.create_idempotent(11, KEY, FINGERPRINT)
            self.assertEqual(store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 0)
            store._db.execute("DROP TRIGGER reject_admission")
            self.assertTrue(store.create_idempotent(11, KEY, FINGERPRINT)[1])

    def test_foreign_keys_and_accepted_boolean_are_enforced(self):
        with DurableJobStore(self.path) as store:
            self.assertEqual(store._db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                store._db.execute("""INSERT INTO admissions(owner_id,key_hash,fingerprint,job_id,accepted,created_at)
                                     VALUES(?,?,?,?,0,?)""", (11, KEY, FINGERPRINT, "missing", 1000))
            original, _ = store.create_idempotent(11, KEY, FINGERPRINT)
            with self.assertRaises(sqlite3.IntegrityError):
                store._db.execute("UPDATE admissions SET accepted=2 WHERE job_id=?", (original.job_id,))

    def test_restart_discards_unaccepted_claims_and_fails_only_admitted_jobs(self):
        state_dir = Path(self.temporary.name) / "state"
        runtime = JobRuntime(state_dir)
        try:
            pending, _ = runtime.store.create_idempotent(11, KEY, FINGERPRINT)
            accepted, _ = runtime.store.create_idempotent(11, OTHER_KEY, FINGERPRINT)
            runtime.store.accept_admission(accepted.job_id, 11, OTHER_KEY)
            runtime.store.transition(accepted.job_id, 11, "processing")
            legacy = runtime.store.create(11)
            # A competing runtime must never discard the live pending upload.
            with self.assertRaises(RuntimeError):
                JobRuntime(state_dir)
            self.assertEqual(runtime.store.get(pending.job_id, 11).state, "queued")
        finally:
            runtime.close()
        restarted = JobRuntime(state_dir)
        try:
            with self.assertRaises(JobNotFound):
                restarted.store.get(pending.job_id, 11)
            self.assertEqual(restarted.store.get(accepted.job_id, 11).state, "failed")
            self.assertEqual(restarted.store.get(legacy.job_id, 11).state, "failed")
            replay, is_new = restarted.store.create_idempotent(11, OTHER_KEY, FINGERPRINT)
            self.assertFalse(is_new)
            self.assertEqual((replay.job_id, replay.state), (accepted.job_id, "failed"))
            fresh, is_new = restarted.store.create_idempotent(11, KEY, FINGERPRINT)
            self.assertTrue(is_new)
            self.assertNotEqual(fresh.job_id, pending.job_id)
            self.assertEqual(restarted.store.discard_pending_admissions(), 1)
            self.assertEqual(restarted.store.discard_pending_admissions(), 0)
        finally:
            restarted.close()
