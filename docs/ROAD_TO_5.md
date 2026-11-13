# FileShape: continuation toward 5.0

This is an implementation checkpoint, not a public-launch announcement.

## Verified milestones

- 3.9: PR #39 merged; PR and main Actions succeeded. SQLite secure creation, sidecar checks, private permissions, CAS stale-state regression, legitimate processing cancellation and failed-initialization cleanup. 130 Python tests at that milestone.
- 4.0: PR #40 merged; PR and main Actions succeeded. Real HTTP conversions use bounded owner-scoped SQLite metadata. Exclusive process ownership precedes interrupted-job reconciliation. Metadata-only Docker volume, expiry and cancellation/error cleanup. Disabled ASGI lifespan fails closed. 140 Python tests at that milestone.
- 4.1: PR #41 merged; PR and main Actions succeeded. Internal bounded dispatcher integrated into HTTP conversion workers; 147 local Python tests and TypeScript/Vite build passed. No throughput claim.
- 4.2: PR #42 merged; PR and main CI succeeded. HTTP 202, private expiring/quota-reserved results and owner-only download; 200 Python tests, TS/build and a real read-only Docker HTTP conversion/download/IDOR smoke passed. Results are not recovered across restart.
- 4.3: `feature/background-miniapp-v43` integrates the Mini App with confirmed job states, bounded polling, authenticated result retrieval and owner-scoped short-lived references. Check its PR and post-merge main CI before proceeding. Actual test counts/browser limitations are recorded in its PR.

Read the current PR's validation notes for local Docker results. The managed
execution environment has an 8 GB filesystem and a VFS Docker daemon. Multiple
images can exhaust that disk. Remove only test images/cache created by the
current task; preserve source, state volumes and unrelated images. HTTPS builds
in this environment need a trusted proxy CA supplied as a BuildKit secret;
never disable TLS verification or commit the environment's certificate.

## Next: 4.4 cancellation and retry

Start only after 4.3 PR and post-merge main CI succeed, on a new branch from
updated main. Add owner-checked cancellation using the existing submission
handles. Await worker cleanup and settle terminal metadata explicitly before
responding; preserve a completed result if cancellation loses the completion
race. Missing and other-owner job IDs must remain indistinguishable. Queued
cancellation must remove files even though `_execute` never starts.

Define a bounded retry-input policy consistent with minimal retention. Retry
only with a valid input (or require an explicit reupload if it expired); do not
promise a server copy after restart. Add bounded owner-scoped idempotency for
create/retry so accidental repeats do not duplicate work. Keep the existing
input/output/disk quotas, TTL and state transition guards. Add frontend controls
with clear confirmed outcomes, preserving 4.3 polling stop/pause behavior.

Cover active and queued cancellation, repeat cancellation, cross-user access,
completion races, process-group cleanup, invalid/expired retry input, duplicate
keys, overload, restart and shutdown. Use the per-version Python / frontend
native tests / TypeScript build / Docker / PR CI / post-merge main sequence.

## Remaining sequence (not implemented)

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
the restricted sandbox; they hung on the first request inside it. Run native
Node tests outside that sandbox too: the restricted child-process IPC reporter
can show only passing files rather than all subtests. A real 4.3 run reports
35 individual frontend checks.

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
