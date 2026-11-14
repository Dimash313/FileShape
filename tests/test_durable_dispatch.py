"""Behavioral gates for the opt-in metered dispatch outbox.

These tests are NOT evidence that the live server uses this adapter or
that a remote worker/blob store is already implemented.
"""
from concurrent.futures import ThreadPoolExecutor
import secrets
from pathlib import Path
import tempfile
import time
import unittest

from api.durable_dispatch import (
    MAX_DELIVERIES, DispatchLeaseConflict, DurableDispatchStore,
)
from api.durable_jobs import IdempotencyConflict
from api.job_envelope import JobEnvelopeError, SingleFileJobV1
from api.jobs import JobNotFound
from api.usage_ledger import OperationConcurrencyExceeded


def refs():
    return secrets.token_urlsafe(24), secrets.token_urlsafe(24)


def admit(store, *, owner=101, key="a" * 64, fingerprint="b" * 64, now=None,
          action="pdf:extract", suffix=".pdf", pages="1-3"):
    source, target = refs()
    return store.admit_staged_single(
        owner, key, fingerprint, input_ref=source, result_ref=target,
        action=action, suffix=suffix, pages=pages, now=now,
    )


class DurableDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "private.sqlite3"
        self.start = time.time()

    def test_atomic_admission_and_idempotent_replay(self):
        with DurableDispatchStore(self.db_path) as store:
            original, created = admit(store, now=self.start)
            self.assertTrue(created)
            self.assertEqual(store.get(original.job_id, 101).state, "queued")
            self.assertEqual(store.usage_snapshot(101, now=self.start)["daily_used"], 1)
            repeated, created = admit(store, now=self.start + 1)
            self.assertFalse(created)
            self.assertEqual(repeated, original)
            self.assertEqual(store.usage_snapshot(101, now=self.start + 1)["daily_used"], 1)
            with self.assertRaises(IdempotencyConflict):
                admit(store, fingerprint="c" * 64)
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 1)

    def test_invalid_envelope_rolls_back_job_quota_and_admission(self):
        with DurableDispatchStore(self.db_path) as store:
            with self.assertRaises(JobEnvelopeError):
                admit(store, action="execute:cmd", now=self.start)
            self.assertEqual(store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 0)
            self.assertEqual(store._db.execute("SELECT count(*) FROM dispatch_outbox").fetchone()[0], 0)
            self.assertEqual(store.usage_snapshot(101, now=self.start)["daily_used"], 0)
            _, created = admit(store, now=self.start)
            self.assertTrue(created)

    def test_owner_quota_concurrency_and_cancel(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            with self.assertRaises(OperationConcurrencyExceeded):
                admit(store, key="c" * 64, now=self.start + 1)
            with self.assertRaises(JobNotFound):
                store.cancel_dispatch(envelope.job_id, 202, now=self.start + 2)
            self.assertEqual(store.usage_snapshot(101, now=self.start + 2)["daily_used"], 1)
            self.assertTrue(store.cancel_dispatch(envelope.job_id, 101, now=self.start + 3))
            self.assertFalse(store.cancel_dispatch(envelope.job_id, 101, now=self.start + 4))
            self.assertEqual(store.get(envelope.job_id, 101).state, "cancelled")
            self.assertEqual(store.usage_snapshot(101, now=self.start + 3)["daily_used"], 0)
            _, created = admit(store, key="c" * 64, now=self.start + 4)
            self.assertTrue(created)

    def test_only_one_concurrent_claim_across_sqlite_connections(self):
        with DurableDispatchStore(self.db_path) as first, DurableDispatchStore(self.db_path) as second:
            original, _ = admit(first, now=self.start)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda store: store.claim_next(now=self.start + 1, lease_seconds=20),
                    (first, second),
                ))
            active = [lease for lease in results if lease is not None]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].envelope.job_id, original.job_id)
            self.assertEqual(first.get(original.job_id, 101).state, "processing")
            self.assertEqual(first.usage_snapshot(101, now=self.start + 1)["daily_used"], 1)

    def test_stale_lease_fenced_after_retry(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            old = store.claim_next(now=self.start + 1, lease_seconds=2)
            new = store.claim_next(now=self.start + 4, lease_seconds=10)
            self.assertEqual((old.attempt, new.attempt), (1, 2))
            self.assertNotEqual(old.token, new.token)
            with self.assertRaises(DispatchLeaseConflict):
                store.settle_lease(envelope.job_id, 101, old.token, success=True, now=self.start + 5)
            with self.assertRaises(JobNotFound):
                store.settle_lease(envelope.job_id, 202, new.token, success=True, now=self.start + 5)
            self.assertTrue(store.settle_lease(envelope.job_id, 101, new.token,
                                              success=True, now=self.start + 5))
            self.assertEqual(store.get(envelope.job_id, 101).state, "completed")
            self.assertEqual(store.usage_snapshot(101, now=self.start + 5)["daily_used"], 1)
            with self.assertRaises(DispatchLeaseConflict):
                store.settle_lease(envelope.job_id, 101, new.token,
                                   success=True, now=self.start + 6)

    def test_retries_exhaust_and_refund_once(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            leases = []
            for attempt in range(MAX_DELIVERIES):
                lease = store.claim_next(now=self.start + 1 + attempt * 3, lease_seconds=2)
                leases.append(lease)
                self.assertEqual(lease.attempt, attempt + 1)
            self.assertEqual(store.expire_exhausted(now=self.start + 10), 1)
            self.assertEqual(store.expire_exhausted(now=self.start + 11), 0)
            self.assertIsNone(store.claim_next(now=self.start + 11))
            self.assertEqual(store.get(envelope.job_id, 101).state, "failed")
            self.assertEqual(store.usage_snapshot(101, now=self.start + 11)["daily_used"], 0)
            with self.assertRaises(DispatchLeaseConflict):
                store.settle_lease(envelope.job_id, 101, leases[-1].token,
                                   success=True, now=self.start + 11)

    def test_lease_renew_and_cancellation_fence(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            lease = store.claim_next(now=self.start + 1, lease_seconds=2)
            extended = store.renew_lease(envelope.job_id, 101, lease.token,
                                         now=self.start + 2, lease_seconds=20)
            self.assertEqual(extended, self.start + 22)
            self.assertIsNone(store.claim_next(now=self.start + 5))
            self.assertTrue(store.cancel_dispatch(envelope.job_id, 101, now=self.start + 6))
            with self.assertRaises(DispatchLeaseConflict):
                store.renew_lease(envelope.job_id, 101, lease.token,
                                  now=self.start + 7)
            with self.assertRaises(DispatchLeaseConflict):
                store.settle_lease(envelope.job_id, 101, lease.token,
                                   success=True, now=self.start + 7)
            self.assertEqual(store.usage_snapshot(101, now=self.start + 7)["daily_used"], 0)

    def test_reopen_preserves_outbox_and_fences_old_claim(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            first = store.claim_next(now=self.start + 1, lease_seconds=2)
        # This is a storage-only reopen, NOT the current JobRuntime restart.
        with DurableDispatchStore(self.db_path) as reopened:
            new = reopened.claim_next(now=self.start + 4)
            self.assertIsInstance(new.envelope, SingleFileJobV1)
            self.assertEqual(new.envelope.job_id, envelope.job_id)
            with self.assertRaises(DispatchLeaseConflict):
                reopened.settle_lease(envelope.job_id, 101, first.token,
                                     success=False, now=self.start + 5)
            reopened.settle_lease(envelope.job_id, 101, new.token,
                                  success=False, now=self.start + 5)
            self.assertEqual(reopened.usage_snapshot(101, now=self.start + 5)["daily_used"], 0)

    def test_envelope_and_lease_token_never_stored_together(self):
        with DurableDispatchStore(self.db_path) as store:
            envelope, _ = admit(store, now=self.start)
            lease = store.claim_next(now=self.start + 1)
            row = store._db.execute(
                "SELECT envelope,lease_hash FROM dispatch_outbox WHERE job_id=?",
                (envelope.job_id,),
            ).fetchone()
            self.assertEqual(SingleFileJobV1.from_json(row[0]), envelope)
            self.assertNotIn(lease.token.encode("ascii"), row[0])
            self.assertNotEqual(row[1], lease.token)
            self.assertEqual(len(row[1]), 64)

    def test_duplicate_admission_race_is_metered_once(self):
        with DurableDispatchStore(self.db_path) as first, DurableDispatchStore(self.db_path) as second:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda store: admit(store, now=self.start), (first, second),
                ))
            self.assertEqual(sorted(created for _, created in results), [False, True])
            self.assertEqual(results[0][0], results[1][0])
            self.assertEqual(first.usage_snapshot(101, now=self.start)["daily_used"], 1)
            self.assertEqual(first._db.execute(
                "SELECT COUNT(*) FROM dispatch_outbox"
            ).fetchone()[0], 1)

    def test_pack_quota_refunded_on_outbox_cancellation(self):
        with DurableDispatchStore(self.db_path) as store:
            store.grant_operation_pack(
                101, 10, "trusted:pack:dispatch-test", now=self.start,
            )
            for i in range(10):
                envelope, created = admit(
                    store, key=f"{i:064x}", fingerprint="b" * 64,
                    action="pdf:info", pages="", now=self.start + i,
                )
                self.assertTrue(created)
                lease = store.claim_next(now=self.start + i + 0.1)
                self.assertEqual(lease.envelope.job_id, envelope.job_id)
                store.settle_lease(
                    envelope.job_id, 101, lease.token,
                    success=True, now=self.start + i + 0.2,
                )
            self.assertEqual(store.usage_snapshot(101, now=self.start + 11)["daily_used"], 10)
            packed, _ = admit(
                store, key="c" * 64, action="pdf:info", pages="", now=self.start + 12,
            )
            self.assertEqual(store.usage_snapshot(101, now=self.start + 12)["pack_remaining"], 9)
            self.assertTrue(store.cancel_dispatch(packed.job_id, 101, now=self.start + 13))
            self.assertEqual(store.usage_snapshot(101, now=self.start + 13)["pack_remaining"], 10)
            self.assertEqual(store.usage_snapshot(101, now=self.start + 13)["daily_used"], 10)
