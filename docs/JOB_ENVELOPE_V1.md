# FileShape 5.0 — single-file job envelope v1

**Status: contract only.** The envelope in `api/job_envelope.py` is not
wired into the API, queue, local subprocess or payment system, and cannot make
jobs durable on its own. It is NOT the existing `api.worker` stdin format.

## Why this exists

Currently `api.worker` receives a trusted local `work` directory path, an
operation and a suffix. That works for our single-instance sandbox but cannot
be copied unchanged into a distributed queue: another server may not have the
same disk or OS pathname. A durable queue needs a small, versioned description
that contains **opaque references** to private artifacts, not filesystem paths.

`SingleFileJobV1` serializes a canonical JSON object with *exactly*:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer `1` | Fail-closed schema negotiation |
| `kind` | `"single"` | Only single-file work in v1 |
| `job_id` | 32-character opaque ID | Existing server-created job identifier |
| `input_ref` | 32-character opaque ID | Private artifact lookup key, **not** access permission |
| `result_ref` | 32-character opaque ID | Private output artifact lookup key |
| `action` | fixed action string | Must be allowed by `conversion_catalog.SUPPORTED` for suffix |
| `suffix` | lowercase extension | Routing hint only; real content must still be validated |
| `pages` | string, up to 90 characters | PDF selection input compatible with the current API |

The object contains no `work` path, shell command, filename, Telegram user ID,
bot token, payment data, raw idempotency key or worker lease secret. Serialization
is bounded to 2048 UTF-8 bytes, deterministic, and rejects unknown/duplicate
keys, unknown versions, invalid opaque IDs, incompatible operations and
unexpected page selections.

## Security and ownership are NOT provided by the envelope

- The API must authenticate the request and verify that the job belongs to the
  user **before** looking up `input_ref` or returning a result.
- An opaque reference is NOT a bearer token. Only the private storage service,
  with server-side owner/job binding, may resolve a reference to a file.
- Workers must never run arbitrary action strings or trust a file extension
  for content detection. The existing sandbox and resource limits must remain.
- Queue messages must not include the worker's host filesystem paths. A future
  trusted per-worker adapter will mount staged content into a private workspace.
- The durable ledger and queued message must be atomically admitted (or have
  an auditable transactional outbox). Duplicate queue delivery, lost ACK,
  lease expiry, cancellation and results must be fenced by an authoritative
  state machine, with no double charging.
- The envelope does **not** include retry attempts or lease tokens; these must
  be issued and checked by the durable scheduler, not copied from untrusted
  messages.
- Single-file format v1 does not represent photo batches, multi-input PDF
  merges, archive packaging or bot-specific workflow steps. They need
  separately designed versioned formats before distributed deployment.
- Never send this object to the current `api.worker.execute` or enable a
  network queue without a reviewed, tested adapter.

## Migration acceptance

Before this contract becomes operational, tests must prove real file staging,
ownership isolation, restart recovery, cancellation races, lease fencing, blob
expiry, quota settlement exactly once, and safe behavior on malformed requests.
Run representative workload/soak tests before claiming capacity.

The Telegram Bot API 20 MiB upload limit and disabled Stars payment gate remain
unchanged. The project-wide halal requirements in `AGENTS.md` still apply.
