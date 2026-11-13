"""Owner-only required channel configuration storage regressions."""
import tempfile
import unittest
from pathlib import Path

from api.durable_jobs import DurableJobStore


class OwnerChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.sqlite3"

    def add(self, store, **kwargs):
        params = dict(actor_id=11, owner_id=11, chat_id=-1001234, starts_at=1000, ends_at=2000, now=1000)
        params.update(kwargs)
        store.set_required_channel(**params)

    def test_persistence_and_owner_audit(self):
        with DurableJobStore(self.path) as store:
            self.add(store)
            self.assertEqual(store.list_required_channels(), [(-1001234, 1000, 2000, True)])
            self.add(store, enabled=False, ends_at=None)
            self.assertEqual(store.list_required_channels(), [(-1001234, 1000, None, False)])
            self.assertEqual(store._db.execute("SELECT count(*) FROM owner_audit").fetchone()[0], 2)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.list_required_channels(), [(-1001234, 1000, None, False)])
            self.assertTrue(reopened.remove_required_channel(actor_id=11, owner_id=11, chat_id=-1001234, now=3000))
            self.assertFalse(reopened.remove_required_channel(actor_id=11, owner_id=11, chat_id=-1001234, now=3000))
            self.assertEqual(reopened._db.execute("SELECT action FROM owner_audit ORDER BY id").fetchall(),
                             [("channel_upsert",), ("channel_upsert",), ("channel_remove",)])

    def test_non_owner_cannot_change_or_delete(self):
        with DurableJobStore(self.path) as store:
            self.add(store)
            with self.assertRaises(PermissionError):
                self.add(store, actor_id=12)
            with self.assertRaises(PermissionError):
                store.remove_required_channel(actor_id=12, owner_id=11, chat_id=-1001234)
            self.assertEqual(len(store.list_required_channels()), 1)
            self.assertEqual(store._db.execute("SELECT count(*) FROM owner_audit").fetchone()[0], 1)

    def test_invalid_configuration_is_not_written(self):
        with DurableJobStore(self.path) as store:
            invalid = [
                dict(chat_id=True), dict(chat_id=100), dict(chat_id=0),
                dict(chat_id=-(2**63)-1), dict(enabled=1),
                dict(starts_at=0), dict(starts_at=float("nan")),
                dict(ends_at=999), dict(ends_at=float("inf")),
                dict(now=float("nan")), dict(actor_id=0),
            ]
            for case in invalid:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    self.add(store, **case)
            self.assertEqual(store.list_required_channels(), [])
            self.assertEqual(store._db.execute("SELECT count(*) FROM owner_audit").fetchone()[0], 0)

    def test_failed_transaction_does_not_leave_channel(self):
        with DurableJobStore(self.path) as store:
            store._db.execute("""
                CREATE TRIGGER deny_audit BEFORE INSERT ON owner_audit
                BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END
            """)
            with self.assertRaises(Exception):
                self.add(store)
            self.assertEqual(store.list_required_channels(), [])


if __name__ == "__main__":
    unittest.main()
