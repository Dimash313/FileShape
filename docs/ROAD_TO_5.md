# FileShape: continuation toward 5.0

This is an implementation checkpoint, not a public-launch announcement.

## Verified milestones

- 3.9: PR #39 merged; PR and main Actions succeeded. SQLite secure creation, sidecar checks, private permissions, CAS stale-state regression, legitimate processing cancellation and failed-initialization cleanup. 130 Python tests at that milestone.
- 4.0: PR #40 merged; PR and main Actions succeeded. Real HTTP conversions use bounded owner-scoped SQLite metadata. Exclusive process ownership precedes interrupted-job reconciliation. Metadata-only Docker volume, expiry and cancellation/error cleanup. Disabled ASGI lifespan fails closed. 140 Python tests at that milestone.
- 4.1: PR #41 merged; PR and main Actions succeeded. Internal bounded dispatcher integrated into HTTP conversion workers; 147 local Python tests and TypeScript/Vite build passed. No throughput claim.
- 4.2: PR #42 merged; PR and main CI succeeded. HTTP 202, private expiring/quota-reserved results and owner-only download; 200 Python tests, TS/build and a real read-only Docker HTTP conversion/download/IDOR smoke passed. Results are not recovered across restart.
- 4.3: PR #43 merged; PR and main CI succeeded. Confirmed Mini App statuses, bounded hidden/offline-aware polling, authenticated result retrieval and owner-scoped references. 200 Python + 35 frontend tests, build and mocked mobile Chromium smoke passed.
- 4.4: branch `feature/job-controls-v44` implements owner-only cancel, explicit validated reupload retry and durable owner-scoped idempotency. Check its PR/post-merge main CI before proceeding; exact validation results are recorded in the PR. No server input retention increase or automatic replay.

Read the current PR's validation notes for local Docker results. The managed
execution environment has an 8 GB filesystem and a VFS Docker daemon. Multiple
images can exhaust that disk. Remove only test images/cache created by the
current task; preserve source, state volumes and unrelated images. Inspect
`docker buildx du --verbose` and target verified cache IDs if cleanup is needed;
do not use broad cache pruning on a shared builder. HTTPS builds
in this environment need a trusted proxy CA supplied as a BuildKit secret;
never disable TLS verification or commit the environment's certificate.

## Next: 4.5 crash recovery and cleanup

Start only after 4.4 PR and post-merge main CI succeed, on a new branch from
updated main. Preserve the exclusive JobRuntime lock before any recovery:
accepted queued/processing records become failed, unaccepted admission claims
are deleted, and no input is replayed. Reconcile per-boot artifacts and metadata
without promising result recovery after restart. The existing janitor scans at
most 500 entries; improve fairness/cursor behavior so a full first batch cannot
starve old later entries. Preserve active locks and leased downloads.

Exercise hard worker/API crashes, startup with mixed states and leftover files,
active/expired download races, transient deletion failures, directory attacks,
disk exhaustion and idempotent repeated cleanup. Keep byte/entry reservations
and finite TTLs accurate, including slow downloads and failed metadata updates.
Make shutdown bounded/correct without deleting a live worker's files. Record
actual recovery/retention limits in operations documentation. Use the normal
Python/frontend/build/Docker/PR/main CI gates before 4.6.

## Remaining sequence (not implemented)

- 4.5: crash reconciliation, periodic orphan/result cleanup, bounded disk, active artifact protection and worker shutdown fault tests. No unsafe replay.
- 4.6: premium dark/blue accessible mobile UI, preserving every working tool; history/profile/navigation and all empty/error/loading states.
- 4.7: reproducible CPU/RAM/process/queue/disk/SQLite load tests and measured report. Keep safe concurrency until deployment-class hardware is measured.
- 4.8: auth/IDOR/archive/parser/subprocess/CORS/rate/size/replay/temp/SQLite/log/race/download audit, confirmed fixes and residual-risk report.
- 4.9: release-candidate regression and end-to-end matrix, Docker/production/retention/backup/rollback review. Real Android and Telegram WebView validation remains a gate; do not substitute browser emulation for a real Telegram test.
- 5.0: final PR, changelog, deployment/operations/production configuration, release checklist, rollback plan, known limitations and v5.0.0 Release after all gates succeed. Production deployment/public exposure needs separate explicit authorization. No monetization.

## Validation and GitHub workflow for every version

Use an isolated Python environment, FFmpeg/ffprobe and the repository's Node
build. In this managed environment, ASGI TestClient tests need execution outside
the restricted sandbox; they hung on the first request inside it. Run native
Node tests outside that sandbox too: the restricted child-process IPC reporter
can show only passing files rather than all subtests. A real 4.3 run reports
at least 35 individual frontend checks (4.4 adds more).

```sh
python -m compileall -q main.py config.py api services tests
python -m unittest discover -s tests -v
cd miniapp
npm install --no-audit --no-fund
npm test
npm run build
```

Check Docker with the repository Dockerfile and read-only runtime settings.
Create a separate version branch and PR. Record actual checks and limitations
in its body. Wait for every required check on the final head SHA; merge using
an expected-head guard. Then inspect the push-triggered run on the merged main
SHA. The connector's commit-workflow wrapper lists PR-triggered runs only; use
`gh run list --commit <main-sha>` for post-merge push runs. `gh pr edit` can fail
with a deprecated Projects Classic GraphQL field; the structured GitHub PR
update tool works. Do not bypass CI, use auto-success claims, or move ahead
while a blocking failure remains.
