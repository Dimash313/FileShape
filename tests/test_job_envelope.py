"""Safety and compatibility tests for the future versioned job description."""
from dataclasses import FrozenInstanceError
import json
import unittest

from api.job_envelope import (
    JobEnvelopeError, MAX_ENVELOPE_BYTES, SCHEMA_VERSION, SingleFileJobV1,
)


def sample(**overrides):
    fields = {
        "job_id": "A" * 32,
        "input_ref": "B" * 32,
        "result_ref": "C" * 32,
        "action": "pdf:extract",
        "suffix": ".pdf",
        "pages": "1,3-5",
    }
    fields.update(overrides)
    return SingleFileJobV1(**fields)


class JobEnvelopeContractTests(unittest.TestCase):
    def test_deterministic_round_trip_without_sensitive_fields(self):
        job = sample()
        raw = job.to_json()
        self.assertLessEqual(len(raw), MAX_ENVELOPE_BYTES)
        self.assertEqual(job, SingleFileJobV1.from_json(raw))
        self.assertEqual(raw, SingleFileJobV1.from_json(raw.decode("utf-8")).to_json())
        self.assertEqual(SCHEMA_VERSION, json.loads(raw)["schema_version"])
        self.assertEqual(json.loads(raw)["kind"], "single")
        for sensitive_field in ("work", "path", "owner_id", "bot_token",
                                "filename", "idempotency_key", "telegram_id"):
            self.assertNotIn(sensitive_field, json.loads(raw))
        with self.assertRaises(FrozenInstanceError):
            job.action = "pdf:remove"

    def test_compatible_single_file_actions(self):
        for action, suffix in (
            ("img:JPEG", ".png"), ("img:compress", ".webp"),
            ("pdf:rotate", ".pdf"), ("audio:ogg", ".mp3"),
            ("docx:txt", ".docx"), ("txt:docx", ".txt"),
            ("zip:list", ".zip"),
        ):
            with self.subTest(action=action):
                job = sample(action=action, suffix=suffix, pages="")
                self.assertEqual(SingleFileJobV1.from_json(job.to_json()), job)

    def test_disallows_wrong_action_suffix_and_path_injection(self):
        for override in (
            {"action": "pdf:extract", "suffix": ".mp3", "pages": ""},
            {"action": "__import__:execute", "pages": ""},
            {"action": "pdf:rotate", "pages": "1-4"},
            {"suffix": "/etc/passwd"},
            {"suffix": ".PDF"},
            {"input_ref": "/tmp/upload.pdf"},
            {"input_ref": "B" * 31},
            {"result_ref": "B" * 32},
            {"job_id": "A" * 33},
            {"pages": "../../secret"},
            {"pages": "9" * 91},
            {"pages": 42},
        ):
            with self.subTest(override=override), self.assertRaises(JobEnvelopeError):
                sample(**override)

    def test_exact_schema_and_unknown_key_rejection(self):
        data = sample().to_dict()
        for key, value in (
            ("schema_version", 2),
            ("schema_version", 1.0),
            ("schema_version", True),
            ("kind", "batch"),
            ("kind", True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(JobEnvelopeError):
                SingleFileJobV1.from_dict({**data, key: value})
        for extra in ("owner_id", "work", "cmd", "lease_token"):
            with self.subTest(extra=extra), self.assertRaises(JobEnvelopeError):
                SingleFileJobV1.from_dict({**data, extra: "/tmp/unsafe"})
        with self.assertRaises(JobEnvelopeError):
            SingleFileJobV1.from_dict({k: v for k, v in data.items() if k != "pages"})
        with self.assertRaises(JobEnvelopeError):
            SingleFileJobV1.from_dict([])

    def test_reject_duplicate_json_keys_and_invalid_payloads(self):
        raw = sample().to_json()
        duplicate = raw.decode("utf-8").replace(
            '"kind":"single"', '"kind":"single","kind":"single"',
        )
        for payload in (
            duplicate, b"\xff", '{"schema_version": NaN}', "[]",
            b"x" * (MAX_ENVELOPE_BYTES + 1), None,
        ):
            with self.subTest(payload=str(payload)[:40]), self.assertRaises(JobEnvelopeError):
                SingleFileJobV1.from_json(payload)

    def test_json_does_not_execute_or_trust_paths(self):
        raw = sample().to_dict()
        raw["input_ref"] = "../../../../etc/passwd"
        with self.assertRaises(JobEnvelopeError):
            SingleFileJobV1.from_json(json.dumps(raw))
