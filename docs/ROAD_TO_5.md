# FileShape: continuation toward 5.0

This is an implementation checkpoint, not a public-launch announcement.

## Verified milestones

- 3.9: PR #39 merged; PR and main Actions succeeded. SQLite secure creation, sidecar checks, private permissions, CAS stale-state regression, legitimate processing cancellation and failed-initialization cleanup. 130 Python tests at that milestone.
- 4.0: PR #40 merged; PR and main Actions succeeded. Real HTTP conversions use bounded owner-scoped SQLite metadata. Exclusive process ownership precedes interrupted-job reconciliation. Metadata-only Docker volume, expiry and cancellation/error cleanup. Disabled ASGI lifespan fails closed. 140 Python tests at that milestone.
- 4.1: `feature/job-manager-v41` contains the internal bounded dispatcher integrated into HTTP conversion workers. Its PR/merge/main CI status must be checked on GitHub before proceeding. Local Python suite: 147 tests passed; TypeScript/Vite build passed. CPU, RAM, output and wall-time limits remain in `api/worker_runner.py`. No processing throughput claim.

Read the current PR's validation notes for local Docker results. The managed
execution environment has an 8 GB filesystem and a VFS Docker daemon. Multiple
images can exhaust that disk. Remove only test images/cache created by the
current task; preserve source, state volumes and unrelated images. HTTPS builds
in this environment need a trusted proxy CA supplied as a BuildKit secret;
never disable TLS verification or commit the environment's certificate.

## Next: 4.2 background API

Begin only after the 4.1 PR and post-merge main CI succeed. Create a new branch
from updated main and keep the old HTTP routes compatible.

1. Extend `JobManager` with a bounded submission handle so HTTP 202 can return
   without creating a task per request. Consume background errors explicitly;
   preserve the tested cleanup-before-cancellation-completion ordering.
2. Add a private, service-owned artifact directory with explicit TTL and disk
   reservations. Keep file bytes outside SQLite. Persist only the minimal
   operation manifest needed to locate/validate a result; use opaque job IDs
   and fixed server-controlled filenames, never client-supplied paths.
3. Validate owner/auth, action, actual upload size and safe content checks
   before acceptance. Resource-intensive validation belongs in bounded workers.
   A successful create response must contain a real stored job ID and HTTP 202.
4. Let the worker own queued -> processing -> terminal transitions. Finalize
   output before recording completed. On rejection, cancellation or failure,
   release reservations, processes and files consistently.
5. Add owner-only result retrieval, with authorization before filesystem access,
   symlink/path checks and safe download lifetime during cleanup. Knowing an ID
   must never grant access. Limit result retention; do not promise conversion
   recovery after restart.
6. Integrate startup/shutdown and artifact expiry with existing exclusive
   `JobRuntime` ownership. Never mark jobs failed before acquiring its lock.
7. Test HTTP 202, real conversion/result integrity, unauthenticated access,
   cross-owner access, known-ID attacks, overload, size limits, worker failure,
   expiry, download/cleanup races, cancellation and restart semantics.

## Remaining sequence (not implemented)

- 4.3: connect the Mini App to background creation and results; actual XHR upload progress, bounded polling, terminal stop, hidden/offline/reopen behavior, confirmed states only.
- 4.4: owner-only queued/running cancellation, process cleanup, completion races, retry with a valid retained input, idempotent duplicate protection.
- 4.5: crash reconciliation, periodic orphan/result cleanup, bounded disk, active artifact protection and worker shutdown fault tests. No unsafe replay.
- 4.6: premium dark/blue accessible mobile UI, preserving every working tool; history/profile/navigation and all empty/error/loading states.
- 4.7: reproducible CPU/RAM/process/queue/disk/SQLite load tests and measured report. Keep safe concurrency until deployment-class hardware is measured.
- 4.8: auth/IDOR/archive/parser/subprocess/CORS/rate/size/replay/temp/SQLite/log/race/download audit, confirmed fixes and residual-risk report.
- 4.9: release-candidate regression and end-to-end matrix, Docker/production/retention/backup/rollback review. Real Android and Telegram WebView validation remains a gate; do not substitute browser emulation for a real Telegram test.
- 5.0: final PR, changelog, deployment/operations/production configuration, release checklist, rollback plan, known limitations and v5.0.0 Release after all gates succeed. Production deployment/public exposure needs separate explicit authorization. No monetization.

## Validation and GitHub workflow for every version

Use an isolated Python environment, FFmpeg/ffprobe and the repository's Node
build. In this managed environment, ASGI TestClient tests need execution outside
the restricted sandbox; they hung on the first request inside it.

```sh
python -m compileall -q main.py config.py api services tests
python -m unittest discover -s tests -v
cd miniapp
npm install --no-audit --no-fund
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
