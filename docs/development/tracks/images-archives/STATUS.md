# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Current Issue: [#138 — atomic multi-image PDF publication](https://github.com/Dimash313/FileShape/issues/138)
Current branch: `fix/image-bundle-atomic-output-h3`
Active PR: [#144](https://github.com/Dimash313/FileShape/pull/144) (**Draft**; base `fix/image-atomic-output-h2`)
Source commit before updating handoff: `256148529ba84eaf67e704cc5e245f4b4abc4246`. **Check PR #144 live for final head SHA**, including these documentation commits.

## What was changed (Draft; NOT merged)

- `services/image_bundle.py`: publish a multi-page PDF only after successful Pillow encoding, via the existing parent-PR `services.image_tools._atomic_image_output`. Maintain private same-directory temporary stage, `os.replace` atomic final publication, stage cleanup if encoder/publish fails, previous target preservation on failure.
- `tests/test_image_bundle_atomic.py`: 9 new real-file/adversarial cases: page count and order; successful replacement; partial PDF encoder failure (existing/absent targets); publication failure; symlink target without modifying external file; corrupt input/2–8 count/20 MiB aggregate admission; 22m cumulative pixel rule; 0600 output mode.
- Existing PDF image bundle return contract, 2–8 input limit, 20 MiB source budget, 22 million-pixel cap, EXIF/alpha behavior, consumer route/port/filenames and private input workspaces unchanged.
- No new API, authentication, quotas, UI, payments, media assets or dependencies; AGENTS.md continues to apply.

## Verified / not verified

- **Actually executed locally**: Python 3.13.5, Pillow 12.3.0, pypdf 5.9.0 on reconstructed copies of the changed image domain files (not a full GitHub repository checkout), `python -m unittest -v tests.test_image_bundle tests.test_image_bundle_atomic`: **12 tests passed** (3 existing and 9 newly committed).
- Exact PR head Python suite, Mini App tests/typecheck/build, Docker, bot/API security/transport integration, final GitHub Actions and deployment-volume behavior: **NOT EXECUTED / NOT VERIFIED**.
- [Issue #101](https://github.com/Dimash313/FileShape/issues/101): GitHub-hosted runner allocation blocked before job steps in recent runs. No 0-step status is test success.

## Stacked PR chain

1. [#144](https://github.com/Dimash313/FileShape/pull/144) image-bundle PDF staging (Issue #138) → [#137](https://github.com/Dimash313/FileShape/pull/137) atomic single-image output (Issue #133).
2. [#128](https://github.com/Dimash313/FileShape/pull/128) staged ZIP extraction (Issue #121) → [#112](https://github.com/Dimash313/FileShape/pull/112) GitHub-first development handoff.
3. [#111](https://github.com/Dimash313/FileShape/pull/111) ZIP output compatibility (Issue #110) → [#109](https://github.com/Dimash313/FileShape/pull/109) HTTP ZIP creation → earlier architecture parents.

**Do not merge out of dependency order**. Each final head needs real green CI and review; verify push-triggered main CI afterwards.

## Next work / risks

- First audit PR #144 / #137 / #128, parent-base drift and exact-head CI status.
- ZIP HTTP extraction protocol is owned by `api-security`; [Issue #132](https://github.com/Dimash313/FileShape/issues/132) / [PR #135](https://github.com/Dimash313/FileShape/pull/135) is a separate proposed contract, **not an implemented feature**.
- Further independent image error/size-budget hardening requires its own Issue/claim. Do not silently change shared contracts, raise limits or implement separate platforms.
