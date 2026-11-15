# PDF & Documents — GitHub-first handoff

Updated: 2026-11-16 UTC. Track: `pdf-documents`.
Current Issue: [#196 — bound actual TXT input bytes](https://github.com/Dimash313/FileShape/issues/196).
Current branch: `pdf-documents/196-bounded-txt-read`, stacked on `pdf-documents/193-validate-row-grid` / Draft [#194](https://github.com/Dimash313/FileShape/pull/194).
Code and test commit preceding status update: `be38fcab36305ea5397db6904710c276b0c496ed`. This STATUS commit advances the branch head; confirm actual SHA via GitHub.

## Current focused issue
- Reproduced a real TXT byte-limit time-of-check/time-of-use gap: a 3-byte TXT grows to 700,000 multibyte UTF-8 characters (2,100,000 bytes) after the initial `stat()` reports three bytes. Previous `read_plain_text` used unbounded `source.read_bytes()` then enforced only char/line limits; the enlarged file was **accepted** despite exceeding `MAX_TEXT_BYTES=2,097,152`. The reproduction used a test Path subclass that changes the actual file between the two operations, without relying on a production race timing.
- New `read_plain_text` opens a single binary stream and reads at most `MAX_TEXT_BYTES + 1` bytes. It enforces the byte bound on the actual data returned before decoding, avoiding unlimited read and stale stat.
- `tests/test_txt_read_boundaries.py` adds eight real-file regressions: exact 2 MiB Unicode content, one-byte excess, growth race, no `stat`/`read_bytes` dependency, rejected conversion without output, Unicode BOM round-trip, invalid UTF-8/NUL, and existing char/line limits.
- Domain-only change. No API, auth, worker, quotas, payment, media, advertising, UX or new dependency.

## Related unmerged, green exact-head PRs
- PDF: [#114](https://github.com/Dimash313/FileShape/pull/114) malformed/encrypted/large regressions → [#183](https://github.com/Dimash313/FileShape/pull/183) atomic PDF publication (GitHub Actions success).
- DOCX: [#125](https://github.com/Dimash313/FileShape/pull/125) ZIP part safety → [#130](https://github.com/Dimash313/FileShape/pull/130) malformed OOXML → [#146](https://github.com/Dimash313/FileShape/pull/146) table/text quotas → [#154](https://github.com/Dimash313/FileShape/pull/154) vertical-merge limits → [#160](https://github.com/Dimash313/FileShape/pull/160) nested-table quotas → [#187](https://github.com/Dimash313/FileShape/pull/187) atomic DOCX/TXT outputs → **[#194](https://github.com/Dimash313/FileShape/pull/194) / Issue #193** malformed row grid offsets / merge-state checks.
- #194 current unchanged HEAD `a44c8c0271bb452a27a260ec8aed236250174551`: exact-head [GitHub Actions run #43751511301](https://github.com/Dimash313/FileShape/actions/runs/43751511301) completed `success`. Both Python unittest/Docker and Mini App test/typecheck/build executed and passed. It remains Draft/unmerged.

## Verification status / blockers
- **Confirmed independently:** deterministic old-code byte-limit bypass under file-growth race on generated actual UTF-8 TXT; captured actual sizes 2,100,000 > 2,097,152, accepted string length 700,000.
- **Not yet executed for #196 on exact HEAD at status creation:** committed new 8-test module, full Python suite, Mini App, Docker. GitHub Actions must run on final commit. Code review and proper merge ordering are mandatory even with green CI.
- GitHub runner issue #101 closed after workflow recovery, but no waiver of exact-head CI, privacy checks or independent review.
- Target file may be modified externally; a bounded stream read prevents excess byte acceptance/memory allocation but does not guarantee a stable snapshot of a concurrently written input. Application must maintain private, server-controlled processing paths and own upload sealing/leases.

## Integration / next
1. CTO and maintainers: integrate governance #91→#92 and architecture/docs #93→#112 after separate review; run green main push CI between staged merges. No forced or unreviewed merge.
2. Integrate PDF #114→#183 independently and DOCX #125→#130→#146→#154→#160→#187→#194→#196, each with exact-head review/checks, then main CI.
3. Observe full CI on #196 and correct any failures in the same PR; do not misstate release readiness.
