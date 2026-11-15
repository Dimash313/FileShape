# FileShape — modular monolith, stable updates (phase A)

Status: architecture contract and migration plan, **not a completed refactor**.

## Goal

An update to audio should not require edits to video, PDF or archives and must not silently break them. Isolate failures and regressions; **no architecture can guarantee zero defects**. Use evidence-backed tests and staged rollout.

## Target logical dependency direction

```text
Telegram bot / Mini App / website / Android / iOS
                       |
             Versioned application API
                       |
          Operations and job orchestration
             /         |          \
      audio       video / PDF      archives/images/documents
             \         |          /
        Shared minimal contracts / file policy
                       |
        Infrastructure adapters (storage, queue, billing)
```

- Each format domain owns its validators, operations, format-specific errors and tests.
- No format domain imports another format domain. Cross-format operations (e.g. extract audio from video) belong to an explicit orchestration/use-case layer that coordinates independent adapters.
- Domain logic must not import Telegram, FastAPI, UI components, billing, SQLite, HTTP clients or deployment code.
- Shared contracts stay small and stable; avoid a giant global utils module.
- Clients call public application APIs, never internal file-processing functions directly. Authorization, quotas, temporary file ownership and cleanup are enforced by the application boundary.
- A change to one format must not silently change another format's supported operations, output naming, metadata or resource budgets.
- Prefer direct in-process calls with bounded subprocess execution. **Do not introduce per-format microservices** unless benchmarks justify the operational and network overhead.

## Current repository: do not confuse target with implementation

Existing `services/audio_tools.py`, `services/archive_tools.py`, `api/`, `main.py`, and `miniapp/` are real implementation paths. The target structure is **not yet fully implemented**. Existing service modules should be wrapped with compatible adapters before any relocation; do not bulk move files or rewrite imports in one PR.

## Migration in small reversible PRs

1. **A — map and protect:** inventory actual imports, conversion entry points, tests, quotas, cleanup, public API and format-specific behavior. Add an architecture test for new domain boundaries; no behavior changes.
2. **B — define contracts:** typed input/output/error contracts and an explicit operation catalog with compatibility tests. Maintain old import paths.
3. **C — extract one format:** start with audio or archives behind an adapter, with golden-file and negative tests; preserve signatures and existing limits. Compare outputs before/after.
4. **D — repeat:** PDF, images, documents, video when implemented. Cross-format use cases live in orchestration, not mutual imports.
5. **E — integrate and verify:** cross-client contract tests, end-to-end conversion, auth/quotas, failure injection, latency/CPU/memory comparisons, rollback rehearsal.

## Required regression gate per module update

- Unit and real format fixtures for the changed domain, including corrupt and oversized inputs.
- Full existing Python suite, Mini App tests/typecheck/build and Docker build.
- Cross-format smoke matrix to prove unchanged tools still work.
- Cross-client API compatibility and auth/ownership/quota tests.
- Temporary file cleanup, cancellation, subprocess timeout and error propagation.
- Before/after benchmarks on representative files. No claim of zero overhead without measurements.
- Green exact-head CI, then merged-main CI; otherwise keep draft and do not deploy.

## Performance and operational decision

A Python package boundary adds negligible overhead relative to FFmpeg/PDF processing in typical workloads, but this is a hypothesis until benchmarked on FileShape. Separate OS processes or network services add serialization, startup and infrastructure costs. Start with a modular monolith and retain independent worker isolation only where needed for security/resource control.

## Existing architecture

Read [ARCHITECTURE_5.md](ARCHITECTURE_5.md) for current job/storage/accounting invariants and staged migration gates. This module plan supplements it and does not activate the unmerged distributed architecture, payments or new file size promises.
