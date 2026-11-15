# Images & archives — handoff

Updated: 2026-11-15 UTC (initial snapshot; verify live GitHub).
Current state: ZIP HTTP creation PR #109 and ZIP compatibility PR #111 are **draft and stacked**, not merged. Issue #110 tracks the writer/reader mismatch; do not close based on code alone. ZIP extraction over HTTP is not implemented in these drafts.
Verified: GitHub Actions issue #101: jobs failed before runner allocation; tests written in PRs are **NOT executed** by those CI runs.
Next: coordinate ZIP extraction HTTP design with API/security **after** verifying #109/#111 and the CI blocker; independent ZIP security test Issues may proceed without overlapping shared files.
Cross-track owner: API/security for new HTTP routes, signed identity, quota and result delivery.
