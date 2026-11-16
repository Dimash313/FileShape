# FileShape CI operations and recovery

**Status (2026-11-15): GitHub-hosted runner allocation restored.** The
owner changed FileShape from private to public after account Actions Compute
included usage reached $12/$12. Previously blocked jobs now start on real
GitHub-hosted runners; [issue #101](https://github.com/Dimash313/FileShape/issues/101)
was closed after observing the recovery. **This does not mean the full Python,
Mini App, Docker or integration checks have passed on every PR.** Do not
merge until the exact-head checks and review are green.

Recovery evidence: [PR #164 run #43726214310, attempt 2](https://github.com/Dimash313/FileShape/actions/runs/43726214310)
allocated runner IDs 1000000948 (tests) and 1000000949 (miniapp). At the
time recorded, the Mini App test/build job passed and the Python job had
entered its actual unit tests; Docker was still pending. Re-run checks must
be inspected until terminal success/failure for each exact PR head.

## Evidence

- Last observed successful main run:
  [43641012389](https://github.com/Dimash313/FileShape/actions/runs/43641012389),
  2026-11-14 21:06 UTC. `tests` and `miniapp` ran actual steps and passed.
- First observed failure in this series:
  [43659844768](https://github.com/Dimash313/FileShape/actions/runs/43659844768),
  2026-11-15 00:46 UTC, both jobs fail with zero executed steps.
- Recent representative:
  [43708655915](https://github.com/Dimash313/FileShape/actions/runs/43708655915),
  both jobs failed with `runner_id=0`, no steps and no usable logs.
- The symptom affects unrelated branches, including documentation changes.
  Do not claim a failing Python test, broken Docker image, or TypeScript
  regression when no job steps have run.

The owner subsequently supplied a screenshot from GitHub Billing showing
Actions included Compute $12.00 used of $12.00 included and $0 billable
after discounts. After the repository became public, the formerly blocked
runs received real GitHub-hosted runners. The historical failure is strongly
consistent with exhausted private-repository included Compute. Exact
check-run annotation text was not retrieved through the connector; do not
claim more certainty than the evidence supports.

## Owner's account-side checklist (read-only first)

1. Open the latest failed [Actions run](https://github.com/Dimash313/FileShape/actions/runs/43708655915).
   Check the error banners/annotations for the **exact** message.
2. Open https://github.com/settings/billing. Review **Usage** for Actions,
   then **Budgets and alerts**, included usage and account warnings.
   Check for an exhausted limit or an active stop-usage budget.
3. Verify repository **Settings → Actions → General** allows the existing
   workflow and GitHub-hosted runners.
4. If usage is exhausted, wait for the included usage to reset; consider
   any other options only with the owner's explicit cost approval. Never
   silently add a card, disable budget protections, or enable paid overages.
5. If limits and permissions are healthy but jobs still fail before runner
   allocation, ask GitHub Support to examine the exact annotation and
   linked run IDs.

Documentation:
[GitHub Actions troubleshooting](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows),
[Budgets and alerts](https://docs.github.com/en/billing/how-tos/set-up-budgets).

## Low-cost CI behavior

`.github/workflows/tests.yml` cancels older, superseded **pull-request**
runs when a newer commit arrives on the same PR. This limits wasted hosted
runner time on obsolete heads. It **does not** cancel `main` checks and
does not skip checks for the current PR head.

Python pip **download cache** is keyed by both `requirements.txt` and
`requirements-dev.txt`; it is not a substitute for executing dependency
installation or tests. The two existing jobs still execute Python unit
tests, source compile, FFmpeg installation, Docker build, Mini App tests
and Mini App build. No paid service is added.

The Mini App does not currently commit a package lockfile, so we are
**not** replacing `npm install` with `npm ci` until a deterministic
lockfile has been reviewed in its own PR.

## Mandatory quality gate for each change

- Exact PR head runs with a real runner and every required step completes.
- Full Python suite, Mini App tests/build and Docker build all green.
- Cross-format conversion and authorization/quota/file cleanup regressions
  executed for the affected domains.
- Stacked PR bases reviewed and applied in dependency order, with
  integration conflicts resolved before merging.
- The merged `main` workflow passes again; no red-check overrides or
  'green' labels without execution.
- A passing CI is required, **not sufficient**: realistic bot/API smoke
  tests, security review and performance benchmarks remain necessary for
  the full FileShape production-quality target.
