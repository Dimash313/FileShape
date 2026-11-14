"""Versioned, path-free description of a future single-file worker job.

This is a CONTROL-PLANE CONTRACT ONLY. It must never be passed directly to
the legacy api.worker process: the legacy worker expects trusted local paths.
A later authenticated storage adapter must resolve opaque file references and
a durable queue must atomically coordinate admission, retries and settlement.

Opaque references are identifiers, NOT bearer credentials or authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from api.conversion_catalog import SUPPORTED, file_kind


SCHEMA_VERSION = 1
MAX_ENVELOPE_BYTES = 2048
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{32}\Z")
_PAGE_SELECTION = re.compile(r"[0-9,\s-]{1,90}\Z")
_KEYS = frozenset({
    "schema_version", "kind", "job_id", "input_ref", "result_ref",
    "action", "suffix", "pages",
})


class JobEnvelopeError(ValueError):
    """A versioned dispatch description is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class SingleFileJobV1:
    """Immutable, minimal metadata for one future durable conversion.

    No original filename, OS path, Telegram identity, payment information,
    worker lease or raw idempotency key belongs in this envelope.
    """

    job_id: str
    input_ref: str
    result_ref: str
    action: str
    suffix: str
    pages: str = ""

    def __post_init__(self) -> None:
        for name in ("job_id", "input_ref", "result_ref"):
            value = getattr(self, name)
            if type(value) is not str or _OPAQUE_ID.fullmatch(value) is None:
                raise JobEnvelopeError(f"Invalid {name}")
        if self.input_ref == self.result_ref:
            raise JobEnvelopeError("Input and output must have distinct references")
        if type(self.action) is not str or type(self.suffix) is not str:
            raise JobEnvelopeError("Invalid action or suffix")
        if not self.suffix.startswith(".") or self.suffix != self.suffix.lower():
            raise JobEnvelopeError("Invalid source suffix")
        kind, canonical_suffix = file_kind("source" + self.suffix)
        if kind == "other" or canonical_suffix != self.suffix:
            raise JobEnvelopeError("Unsupported source suffix")
        if self.action not in SUPPORTED.get(kind, ()):
            raise JobEnvelopeError("Operation is not supported for the input")
        if type(self.pages) is not str or len(self.pages) > 90:
            raise JobEnvelopeError("Invalid PDF page selection")
        if self.pages and _PAGE_SELECTION.fullmatch(self.pages) is None:
            raise JobEnvelopeError("Invalid PDF page selection")
        if self.pages and self.action not in {"pdf:extract", "pdf:remove", "pdf:first"}:
            raise JobEnvelopeError("Page selection is not applicable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "single",
            "job_id": self.job_id,
            "input_ref": self.input_ref,
            "result_ref": self.result_ref,
            "action": self.action,
            "suffix": self.suffix,
            "pages": self.pages,
        }

    def to_json(self) -> bytes:
        """Deterministic UTF-8 serialization, bounded before queue insertion."""
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        if len(encoded) > MAX_ENVELOPE_BYTES:
            raise JobEnvelopeError("Job description exceeds limit")
        return encoded

    @classmethod
    def from_dict(cls, data: object) -> SingleFileJobV1:
        if type(data) is not dict or set(data) != _KEYS:
            raise JobEnvelopeError("Unexpected job description fields")
        if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
            raise JobEnvelopeError("Unsupported job schema version")
        if data["kind"] != "single" or type(data["kind"]) is not str:
            raise JobEnvelopeError("Unsupported job kind")
        return cls(
            job_id=data["job_id"], input_ref=data["input_ref"],
            result_ref=data["result_ref"], action=data["action"],
            suffix=data["suffix"], pages=data["pages"],
        )

    @classmethod
    def from_json(cls, payload: bytes | str) -> SingleFileJobV1:
        if type(payload) is bytes:
            if len(payload) > MAX_ENVELOPE_BYTES:
                raise JobEnvelopeError("Job description exceeds limit")
            try:
                raw = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise JobEnvelopeError("Job description must be UTF-8") from exc
        elif type(payload) is str:
            if len(payload.encode("utf-8")) > MAX_ENVELOPE_BYTES:
                raise JobEnvelopeError("Job description exceeds limit")
            raw = payload
        else:
            raise JobEnvelopeError("Job description must be JSON text")

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise JobEnvelopeError("Duplicate JSON field")
                result[key] = value
            return result

        def no_constants(_: str) -> Any:
            raise JobEnvelopeError("Non-finite JSON values are forbidden")

        try:
            data = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=no_constants)
        except (ValueError, TypeError) as exc:
            raise JobEnvelopeError("Invalid job JSON") from exc
        return cls.from_dict(data)
