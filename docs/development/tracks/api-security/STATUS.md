# API & security — handoff

Updated: 2026-11-15 UTC (initial snapshot; verify live GitHub).
**P0 blocker:** issue #101 — GitHub Actions tests/miniapp jobs fail before runner allocation (zero steps); root cause not confirmed. CI improvement PR #102 exists separately.
Current state: stacked architecture drafts include #107 HTTP capabilities, #108 PDF merge, #109 ZIP creation, #111 ZIP compatibility. Do not treat draft code as merged. Earlier PR #87 overlaps capability manifest design; reconcile rather than blindly merge both.
Verified: no exact-head green CI for these stacked PRs; no deployment readiness.
Next: inspect actual GitHub Actions job failure banners/settings with owner, unblock runners, then audit PR dependency graph and coordinate ZIP extract HTTP contract.
Shared-file coordination: this track owns API/auth/worker contract review, but changes affecting domain behavior need domain-track signoff.
