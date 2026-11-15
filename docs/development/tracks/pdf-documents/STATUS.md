# PDF & Documents — GitHub-first handoff

Updated: 2026-11-16 UTC. Track: `pdf-documents`.
Active Issue: [#203 — pin DOCX source during validation and parsing](https://github.com/Dimash313/FileShape/issues/203).
Active branch: `pdf-documents/203-pinned-docx-source` (base `pdf-documents/196-bounded-txt-read`; Draft [#199](https://github.com/Dimash313/FileShape/pull/199)).
Source and new tests commit before status: `2b146d0d28a974e983f6b46f0f372874cc1071d4`. This STATUS edit advances the branch head; always verify final SHA through GitHub.

## Reproduced bug and new implementation
- Old `read_docx_text` uses `validate_docx(source)` (opens ZIP at pathname), then `Document(str(source))` (reopens pathname). A file replaced between these two opens can pass preflight as one package and be parsed as a different package. Reproduced on two generated real DOCX files: after validating an opened original stream, replace the pathname; `Document(stream)` still yields the original text, whereas `Document(path)` loads replacement.
- Current branch `services/document_tools.py`: `read_docx_text` opens DOCX once as `source.open("rb")`, passes that stream to `validate_docx`, seeks to start, parses with `Document(stream)`, and closes on all exceptions. Existing `validate_docx(Path)` remains supported; it additionally accepts an already-open binary stream for this internal path. Error normalization and output semantics preserved.
- New `tests/test_docx_pinned_input.py`: seven real generated DOCX regressions covering accepted valid file, public validator path/stream compatibility, atomic replacement and rename after validation, invalid original package even if pathname later changes, parser exception redaction, and fd cleanup on OS errors.
- No new dependencies, API/Telegram/Mini App/billing/worker/quotas changes, user content, imagery, audio, marketing or third-party providers.

## Domain-dependent branches, all currently Draft/unmerged
- Architecture/docs parents [#93→#112](https://github.com/Dimash313/FileShape/pull/112) require independent review and safe sequential integration; governance #91→#92 also green but unmerged.
- PDF [#114](https://github.com/Dimash313/FileShape/pull/114) (malformed/encrypted tests) → [#183](https://github.com/Dimash313/FileShape/pull/183) (atomic PDF writes). Both exact-head GitHub CI successes.
- DOCX [#125](https://github.com/Dimash313/FileShape/pull/125) (ZIP name safety) → [#130](https://github.com/Dimash313/FileShape/pull/130) (corrupt OOXML errors) → [#146](https://github.com/Dimash313/FileShape/pull/146) (table bounds) → [#154](https://github.com/Dimash313/FileShape/pull/154) (vertical merges) → [#160](https://github.com/Dimash313/FileShape/pull/160) (nested tables) → [#187](https://github.com/Dimash313/FileShape/pull/187) (atomic DOCX/TXT outputs) → [#194](https://github.com/Dimash313/FileShape/pull/194) (row offset validity) → [#199](https://github.com/Dimash313/FileShape/pull/199) (bounded actual TXT input bytes).
- #199 HEAD `62b39a9f0e6e134477e3e10575f3258de9f16800`: [GitHub Actions run #43754252338](https://github.com/Dimash313/FileShape/actions/runs/43754252338) completed **success** (Python unittest, Docker build, Mini App tests/typecheck/build).

## Verification and caveats
- **Executed** independent local Python 3.13 / python-docx 1.2.0 proof: `zipfile.ZipFile(stream)` validation did not close the stream; after an `os.replace`, `Document(stream)` read original and `Document(path)` read replacement.
- **Not yet executed on this branch at STATUS creation:** new seven-test module, full repo unittest, Mini App tests/typecheck/build and Docker. GitHub Actions must pass on latest exact head before claiming success.
- Descriptor pinning protects against **pathname replacement** but not **in-place mutation of the same inode**; workers must maintain sealed private input directories and file ownership. This is not a filesystem snapshot.
- CI Issue #101 is closed; approval, parent integration and successful merged-main CI remain required. Do not merge a Draft or infer production readiness from green head checks.

## Next actions
1. Open Draft PR from `pdf-documents/203-pinned-docx-source` to `pdf-documents/196-bounded-txt-read`, verify changed-file scope.
2. Execute exact-head GitHub Actions tests and fix regressions in this PR if discovered. Do not merge without independent review and parent stack integration.
3. Coordinate integration order with CTO; carry contract/ownership/temporary file handling through architecture changes.
