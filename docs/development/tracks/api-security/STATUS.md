# API & security — handoff

Updated: 2026-11-15 UTC. Live GitHub issues, PR heads and workflow runs override this snapshot.
Track: `api-security`.
Current Issue: [#147](https://github.com/Dimash313/FileShape/issues/147) — privacy-safe route tracing.
Active PR: [#151](https://github.com/Dimash313/FileShape/pull/151) (**Draft**, base `docs/independent-development-tracks`, unmerged [#112](https://github.com/Dimash313/FileShape/pull/112)).
Branch: `api-security/147-private-route-traces`.
Code/test commit: `86e7b3dfd3fceace944ca745d69606719ab84306` (this handoff update advances head; inspect PR #151 for latest SHA).

## This bounded PR

- `api/observability.py` classifies implemented HTTP and internal access/quota endpoints using **finite, static labels** instead of defaulting to `other`. Job URL routes match server-generated 32-character URL-safe ID syntax and expose only labels `job_status`, `job_result`, `job_cancel`, `job_retry`, **never** their ID values.
- `tests/test_observability_route_labels.py` covers static route inventory, dynamic valid jobs, malformed/unmatched paths, request ID/header/status and sanitized error logs without private secrets.
- No public route, auth, billing, quota, worker or domain changes. No new dependencies or paid/third-party services; AGENTS.md retained.

**Verification:** code and tests committed to GitHub. **Full repo Python suite / Mini App tests & build / Docker build NOT EXECUTED on exact head.** Added tests are not considered successful until actually run. Review and local checks remain mandatory.

## Release-blocking CI issue #101

[Issue #101](https://github.com/Dimash313/FileShape/issues/101) is still open. Verified recent [run #43722956682](https://github.com/Dimash313/FileShape/actions/runs/43722956682) failed with both Python and Mini App jobs `runner_id=0`, `steps=[]` (before checkout). Root cause not confirmed from repository tools: account Actions billing/usage/runner policy and annotation wording require owner UI inspection. Do not enable paid overages, bypass red checks or merge Draft PRs.

## Parallel API/security work and integration blockers

- [Draft #124](https://github.com/Dimash313/FileShape/pull/124) / [Issue #120](https://github.com/Dimash313/FileShape/issues/120): upload HTTP Content-Length framing hardening.
- [Draft #135](https://github.com/Dimash313/FileShape/pull/135) / [Issue #132](https://github.com/Dimash313/FileShape/issues/132): design-only authenticated HTTP ZIP multi-artifact extraction contract, no runtime route.
- [Draft #142](https://github.com/Dimash313/FileShape/pull/142) / [Issue #141](https://github.com/Dimash313/FileShape/issues/141): pin single-result artifact device/inode/exact length to prevent replacement; unmerged.
- PR #87 overlaps capability discovery in stacked PR #107; the integration team must reconcile these designs before merging either. Additional PDF merge #108 and ZIP create #109 are also draft and unmerged.
- Parallel edits to this STATUS file must be reconciled during branch integration; **do not overwrite other track work**.

## Next actions

1. Owner verifies exact Actions failure annotation, repo Actions policy and personal Actions budget; restore #101 without extra spend or bypass. Require true exact-head full Python, Mini App and Docker green checks, review and merged-main checks.
2. Review #151 labels against the actually implemented HTTP routes and assess privacy for unauthenticated/malformed IDs; add no paths that do not exist.
3. Coordinate integration order #124/#135/#142/#151 with PR #112 and core architecture chain. Obtain images/archives review for #135 before any ZIP extraction implementation.
