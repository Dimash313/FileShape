# API & security — handoff

Updated: 2026-11-15 UTC; review latest PR head SHA before integration.
Track: `api-security`.
Current Issue: [#132](https://github.com/Dimash313/FileShape/issues/132) — proposed HTTP ZIP extraction multi-result contract.
Active PR: [#135](https://github.com/Dimash313/FileShape/pull/135) (**Draft**; base `docs/independent-development-tracks` / PR #112, not `main`).
Branch: `api-security/132-zip-multifile-contract`.
Documentation commit before handoff: `c2d3dc36a1f5c8caaa3b55d5b9ba1c940d192860`. This STATUS edit advances the head; inspect live #135 for exact SHA.

## Current deliverable

- New [HTTP ZIP extraction design](../../../API_ZIP_EXTRACTION_V1_DESIGN.md), documenting **proposed/unimplemented** owner-scoped asynchronous extraction, per-file opaque IDs, owner check before file opens, one atomic manifest, limits, TTL/leases, quota/idempotency, cleanup and adversarial tests.
- No new HTTP route or capability, executable code, payment, account infrastructure, dependencies or domain modules touched. Existing ZIP extraction domain security hardening remains [PR #128](https://github.com/Dimash313/FileShape/pull/128) (`images-archives`).
- PR #87 overlaps capability discovery in [PR #107](https://github.com/Dimash313/FileShape/pull/107). Integration must reconcile/supersede one copy, never merge both independently. HTTP ZIP creation remains draft [PR #109](https://github.com/Dimash313/FileShape/pull/109).
- Previous independent security fix remains **Draft** [Issue #120](https://github.com/Dimash313/FileShape/issues/120), [PR #124](https://github.com/Dimash313/FileShape/pull/124), on its separate branch `api-security/120-upload-framing`. Do not overwrite or merge its code into this documentation branch.

## P0 CI blocker #101 (NOT resolved)

[Issue #101](https://github.com/Dimash313/FileShape/issues/101) remains open. Latest independently checked [run #43721357536](https://github.com/Dimash313/FileShape/actions/runs/43721357536): Python and Mini App jobs failed before any runner allocation (`runner_id=0`, `steps=[]`). The exact account-side billing/runner/annotation reason is not visible via this connector. The owner must review the run's banner, Actions usage/budget, and repository Actions policy. Do not enable paid services or bypass test gates.

**Verified:** design file/branch/Draft PR created in GitHub; source code inspected for existing single-artifact constraints. **NOT VERIFIED:** full Python suite, Mini App tests/typecheck/build, Docker, actual HTTP ZIP-extraction implementation, e2e ZIP fixture tests or working runner. Design is not a shipped feature.

## Next actions and blockers

1. Resolve CI #101 and get real runner-executed exact-head checks; **no PR merges yet**.
2. Review #135's proposal with `images-archives` and integration owner; confirm whether new multi-file store should be separate or a compatible extension, and whether response/TTL/quota semantics meet product requirements.
3. Agree dependency/merge order of stacked #87/#107 (duplicate capability discovery), #108 (PDF merge), #109 (ZIP create), #128 (ZIP extraction domain hardening), and independent #124. These are not already part of `main`.
4. Only after contract signoff create a **separate** implementation Issue/branch/Draft PR for owner-bound ZIP-extraction HTTP endpoints and tests, without advertising before implementation. Keep website and separate native apps out of present scope.
