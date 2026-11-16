# Track: images & archives — roadmap

**Scope:** images, compression/format transformations, ZIP create/list/extract, archive validation, bomb resistance, safe filenames and format-specific tests. HTTP route/auth contracts are coordinated with API/security.

1. Reconcile image adapter drafts #99–#100, ZIP module drafts #105–#106 and HTTP ZIP creation PR #109 with current main.
2. **ZIP writer/reader compatibility:** issue #110, draft PR #111; preserve external ZIP bomb checks, validate roundtrip and reconcile 50 MiB bot vs 20 MiB HTTP limits. Do not close until real CI and review pass.
3. **ZIP extraction HTTP gap:** design safe bounded owner-scoped multi-result protocol with API/security; do not implement insecure public file links or advertise the feature early.
4. Real-file ZIP safety: symlink/path traversal, encryption, high compression ratio, duplicate names, oversized members, cancellation, timeout and cleanup.
5. Image domain performance and capability parity, with bounded image dimensions/pixel budgets and real benchmark evidence.

Work through Issues and independent PRs. New chat must inspect live PR heads and update STATUS in its own branch.
