# FileShape: continuation toward 5.0

This is an implementation checkpoint, not a public-launch announcement.

## Verified milestones

- 3.9: PR #39 merged; PR and main Actions succeeded. SQLite secure creation, sidecar checks, private permissions, CAS stale-state regression, legitimate processing cancellation and failed-initialization cleanup. 130 Python tests at that milestone.
- 4.0: PR #40 merged; PR and main Actions succeeded. Real HTTP conversions use bounded owner-scoped SQLite metadata. Exclusive process ownership precedes interrupted-job reconciliation. Metadata-only Docker volume, expiry and cancellation/error cleanup. Disabled ASGI lifespan fails closed. 140 Python tests at that milestone.
- 4.1: PR #41 merged; PR and main Actions succeeded. Internal bounded dispatcher integrated into HTTP conversion workers; 147 local Python tests and TypeScript/Vite build passed. No throughput claim.
- 4.2: branch `feature/background-api-v42` implements HTTP 202, bounded submission handles, private TTL/quota artifacts and owner-only result download. Check its PR and post-merge main CI before proceeding. Exact validation results are recorded in the PR. No upload/result recovery across restart.

Read the current PR's validation notes for local Docker results. The managed
execution environment has an 8 GB filesystem and a VFS Docker daemon. Multiple
images can exhaust that disk. Remove only test images/cache created by the
current task; preserve source, state volumes and unrelated images. HTTPS builds
in this environment need a trusted proxy CA supplied as a BuildKit secret;
never disable TLS verification or commit the environment's certificate.

## Next: 4.3 Mini App background integration

Begin only after the 4.2 PR and post-merge main CI succeed. Start a separate
branch from updated main. In `miniapp/src/api.ts`, use POST `/api/v1/jobs`
for single-file server tools; preserve existing local image conversion and
synchronous batch photos until equivalent async batch support exists. Keep
actual XHR upload-byte progress. Poll GET `/api/v1/jobs/{job_id}` with bounded
intervals compatible with the shared 12 requests/minute rate limit, stop on
terminal states and abort in-flight polling on hidden/offline/unmount. Handle
reopen without storing uploaded bytes or initData. Fetch the owner-authenticated
result as a blob only after completed; a 404 can mean TTL expiry or restart,
so present that honestly and allow reupload. Show confirmed states, never an
invented conversion percentage. Test upload -> queued -> processing -> download,
error/cancelled, hidden/offline/reopen and terminal polling stop. Follow the
per-version validation/PR/CI/main sequence below.

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
