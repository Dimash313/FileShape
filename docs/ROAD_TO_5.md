# FileShape: continuation toward 5.0

This is an implementation checkpoint, not a public-launch announcement.

## Verified milestones

- 3.9: PR #39 merged; PR and main Actions succeeded. SQLite secure creation, sidecar checks, private permissions, CAS stale-state regression, legitimate processing cancellation and failed-initialization cleanup. 130 Python tests at that milestone.
- 4.0: PR #40 merged; PR and main Actions succeeded. Real HTTP conversions use bounded owner-scoped SQLite metadata. Exclusive process ownership precedes interrupted-job reconciliation. Metadata-only Docker volume, expiry and cancellation/error cleanup. Disabled ASGI lifespan fails closed. 140 Python tests at that milestone.
- 4.1: PR #41 merged; PR and main Actions succeeded. Internal bounded dispatcher integrated into HTTP conversion workers; 147 local Python tests and TypeScript/Vite build passed. No throughput claim.
- 4.2: PR #42 merged; PR and main CI succeeded. HTTP 202, private expiring/quota-reserved results and owner-only download; 200 Python tests, TS/build and a real read-only Docker HTTP conversion/download/IDOR smoke passed. Results are not recovered across restart.
- 4.3: PR #43 merged; PR and main CI succeeded. Confirmed Mini App statuses, bounded hidden/offline-aware polling, authenticated result retrieval and owner-scoped references. 200 Python + 35 frontend tests, build and mocked mobile Chromium smoke passed.
- 4.4: [PR #44](https://github.com/Dimash313/FileShape/pull/44) merged; [main CI](https://github.com/Dimash313/FileShape/actions/runs/43382550867) succeeded at `7a7b83f`. Owner-only cancellation, explicit validated reupload retry and durable owner-scoped idempotency; 225 Python + 54 native Node tests, TypeScript/Mini App and Docker builds passed. Server input retention is unchanged; no automatic replay.
- 4.5: `feature/recovery-cleanup-v45` contains recovery/cleanup hardening. Local 279 Python + 54 native Node tests, TypeScript/Mini App build, Docker build and real read-only HTTP smoke passed. PR CI and post-merge main CI are pending; check the final PR before proceeding. No result recovery or input replay.

Read the current PR's validation notes for local Docker results. The managed
execution environment has an 8 GB filesystem and a VFS Docker daemon. Multiple
images can exhaust that disk. Remove only test images/cache created by the
current task; preserve source, state volumes and unrelated images. Inspect
`docker buildx du --verbose` and target verified cache IDs if cleanup is needed;
do not use broad cache pruning on a shared builder. HTTPS builds
in this environment need a trusted proxy CA supplied as a BuildKit secret;
never disable TLS verification or commit the environment's certificate.

## Current gate: 4.5 recovery and cleanup

The implementation retains exclusive JobRuntime ownership before startup
reconciliation: accepted queued/processing records become failed, unaccepted
claims are deleted and completed metadata follows normal expiry. It never
replays input or recovers per-boot result files. Actual process-crash fixtures
cover held locks, SIGKILL, mixed SQLite states, orphan cleanup and a killed
worker followed by a successful real conversion.

Maintenance owns a fair, retained-cursor janitor examining at most 500 root
entries per sweep, with directory and marker locks protecting active workspaces
(including a missing marker on an active generation). Unsafe markers are left
for deliberate operator cleanup. Known metadata cleanup failures are retried in
bounded batches; artifact reconciliation remains independent of a SQLite outage.
New reservations require their bytes plus a 64 MiB reported-free floor; the
256 MiB logical budget, entry limit and deployment tmpfs/disk cap remain separate.
Failed deletion and open download leases keep their byte charge. Legacy download
responses run final cleanup on success/error/disconnect with a 120-second limit.
Shutdown preparation draining and its fault cases are part of this gate.

**Local verification:** 279 Python tests, 54 native Node tests, TypeScript/Mini
App build, Docker build and real read-only HTTP smoke passed. Regression tests
include actual SIGKILL, repeated shutdown cancellation, GC descriptor release,
cleanup-failure isolation and free-space/readiness failures. Docker exercised
create/replay, cancel/retry/replay, foreign-result 404, WebP and legacy DOCX.
**Pending gate:** separate version PR, successful final-head checks and successful
push-triggered CI on the exact merged main SHA. No production deployment or real
Telegram WebView test is implied.

## Next: 4.6 interface refinement

Start a new version branch from updated main only after the 4.5 gate succeeds.
Preserve every working local/server/batch tool, background status and authenticated
result flow, cancel/retry/idempotency behavior and data-retention limits. Refine
the dark/blue mobile UI across home/catalog/file/conversion/history/profile and
all loading/error/empty states. Keep Android-size layouts, keyboard/screen-reader
accessibility, WebView performance and motion preferences in scope. Browser
emulation and mocked Telegram data remain separate from real Telegram WebView
validation. Apply the normal Python/Node/build/Docker/PR/main CI gates.

## Remaining sequence (not implemented)

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
54 individual frontend checks at the merged 4.4 milestone; record the actual
count after later additions.

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
