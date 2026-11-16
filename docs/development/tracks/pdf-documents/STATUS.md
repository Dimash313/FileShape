# PDF & Documents — integrated engineering handoff

Updated: 2026-11-17 UTC. Track: `pdf-documents`.
Current integration candidate: branch `integration/pdf-safety-20261117` from merged `main` at `17fd3f256d384b748005d4b047ba13cbb2d95dba` (merged DOCX integration [#225](https://github.com/Dimash313/FileShape/pull/225)).
References: [integration coordination #217](https://github.com/Dimash313/FileShape/issues/217), PDF issues [#113](https://github.com/Dimash313/FileShape/issues/113) and [#182](https://github.com/Dimash313/FileShape/issues/182).

## Actually integrated in main
- [#218](https://github.com/Dimash313/FileShape/pull/218): consolidated architecture and format/API ports; original architecture stack #93–#112 is represented in main history. It is incorrect to treat each closed original PR as a separately merged PR.
- [#224](https://github.com/Dimash313/FileShape/pull/224): security hardening of background workers.
- [#225](https://github.com/Dimash313/FileShape/pull/225): cumulative DOCX/TXT safety from upstream #125→#130→#146→#154→#160→#187→#194→#199→#205→#214, including safe ZIP paths, malformed OOXML and table limits, atomic document outputs, actual bounded UTF-8 TXT reads, pinned DOCX validation/parse and rejection of unsafe input types. The `services/document_tools.py` source blob matched #214 (SHA `23bd9306ff08acc21b2d04bb10c2179fd8aa1f78`). Exact-head #225 [workflow 43934141579](https://github.com/Dimash313/FileShape/actions/runs/43934141579) completed successfully (Python unittest + Docker, Mini App tests/build); merge to main was verified. This does not assert live end-to-end production readiness.
- Owner's [no-beta launch policy](https://github.com/Dimash313/FileShape/blob/main/docs/NO_BETA_LAUNCH_POLICY.md) remains mandatory. No prelaunch real-user beta, but automated/simulated integration/security/resource testing and owner-authorized first public launch remain required.

## Current PDF integration candidate — not yet merged
- Original PDF [#114](https://github.com/Dimash313/FileShape/pull/114), Issue #113: five real generated PDF regressions for malformed/truncated, encrypted, oversized page count, combined page overflow and ordinary extraction.
- Original PDF [#183](https://github.com/Dimash313/FileShape/pull/183), Issue #182: output publication for PDF extract/rotate/merge/remove is now staged into private same-directory temporary files and published with `os.replace` only when fully written. Seven real generated and fault-injection tests cover writing/publishing failure, old output preservation, cleanup, private file modes, symlink destination and input==output.
- Files in this integration branch are **exactly byte-identical** to those original reviewed CI heads: `services/pdf_tools.py` blob `39d9ae86a303e0a9e266f035a5e6aab8f0e48504`, `tests/test_pdf_safety_regressions.py` blob `70757fb7336832af6e5277ff41da421781e11e26`, `tests/test_pdf_atomic_output.py` blob `b0d4dd3686128a7842875c09f460fc20502dd3ed`. These upstream PR heads have green exact-head GitHub CI, but this **combined current-main candidate must independently pass new exact-head CI**.
- The original PDF branches (#114→#183) remain Draft/unmerged during candidate verification. Do not merge them again on top of this consolidated integration if the candidate lands.

## Verification and remaining boundaries
- **Not yet verified for this new candidate at status commit:** new head's full Python unittest suite, Docker build, npm Mini App tests/typecheck/build. GitHub Actions must execute all required steps and finish success; then independent CTO/security review, followed by a successful main push CI after merge.
- The existing `pdf_tools.py` assumes private, server-controlled input/output paths. Atomic publication does not confer `fsync` durability against power loss or protect user-supplied paths from parent-directory races. Ownership, auth, upload sealing, resource budgets and cleanup remain enforced at application/API/worker boundaries.
- No API endpoints, auth/contracts, billing/payments, UI, external services, dependencies, audio, imagery or advertising were changed in this integration candidate. No new prohibited/doubtful product behavior.

## Next steps
1. Open a single Draft PR on current `main`, inspect exactly the three PDF implementation/test changes plus this reconciled handoff, and run exact-head GitHub Actions.
2. Obtain independent review, audit PDF error/cleanup and shared worker boundaries, and merge only with approved gates and an actual green main push run. No forced merge, no beta deployment or launch.
3. Once merged, close/supersede original PDF PRs #114 and #183 without merging duplicate changes, preserve their evidence links, and update Issue #217 and this handoff in a separate reviewed follow-up if further facts change.
