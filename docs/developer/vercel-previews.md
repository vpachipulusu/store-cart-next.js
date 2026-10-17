# Vercel deployments: only `main` deploys, previews are manual

The Vercel Hobby plan allows 100 deployments per day. Only the `CI gate` check matters for merging, so branch pushes and PR previews no longer build by default (KAN-212).

## What builds

| Push | Vercel creates a deployment? |
|---|---|
| `main` | Yes (production) |
| Any other branch or PR | No deployment record at all (KAN-244) |
| `vercel deploy` from the CLI | Yes (not Git-triggered, so Git settings do not apply) |

`CI gate` is unchanged and stays the only required check.

## Why it changed (KAN-244)

KAN-212's Ignored Build Step cancels the build, but Vercel still creates a **Canceled** deployment record for each push, and those records count toward the Hobby limit of 100 deployments per day (`vercel list` shows them, the dashboard hides them). The only way to avoid the record is to stop Vercel from creating the deployment, which is the `git.deploymentEnabled` setting in `vercel.json`:

```json
"git": { "deploymentEnabled": { "main": true, "**": false } }
```

Both `vercel.json` files carry it (root services project and `fastapi_backend`). Vercel accepts `git` beside `services` (unlike a top-level `ignoreCommand`, see below).

Evidence: before and after pushing the throwaway branch `fix/KAN-244-no-preview-deployments` (the push that carried this change), `vercel list` for the team was identical apart from ageing; no new deployment, Canceled or otherwise, and no Vercel status or check on the commit.

Limit: `deploymentEnabled` is per branch, so it cannot read the commit message. The old `[deploy preview]` Git opt-in therefore no longer produces a preview; a preview is now made by hand (below).

## Fallback: Ignored Build Step

`scripts/vercel-ignore-build.sh` (`bash scripts/vercel-ignore-build.sh`, dashboard Ignored Build Step on `store-cart-next.js`; `ignoreCommand` in `fastapi_backend/vercel.json`) stays as a fallback. It exits `1` (build) for `main`, a commit message containing `[deploy preview]`, or no git branch info, otherwise `0` (skip). It reads only `VERCEL_GIT_COMMIT_REF` and `VERCEL_GIT_COMMIT_MESSAGE` and never prints them. It only matters if `git.deploymentEnabled` is removed or the branch is main.

A `vercel.json` that defines `services` cannot carry a top-level `ignoreCommand`: Vercel rejects the deploy with "cannot be used with `services` because the owning service is ambiguous" (the cause of the "Deployment failed." status, PR #176). So the root project uses the dashboard setting for that.

The backend project's script lives outside its Root Directory, so it needs Settings > Build and Deployment > **Include source files outside of the Root Directory in the Build Step** turned on, otherwise the command fails and Vercel builds (fail open).

(ADR-011 describes a single project with services; if the backend is ever folded into the root project, `fastapi_backend/vercel.json` can be deleted.)

## Getting a preview on purpose

Deploy by hand from your checkout (does not use Git, so it always creates one deployment):

```bash
npm run vercel:pull && npm run vercel:build && npm run vercel:preview
```

Each manual preview counts toward the 100/day limit. Preview deployments need their own preview environment variables (see the backend deploy audit and ADR-003); one built without them answers 503 on the routes that need them.

## Dry-run test

```bash
bash scripts/vercel-ignore-build.test.sh
```

It runs the script under main, feature-branch, marker, case, empty-env and hostile-message scenarios (quotes, `$`, backticks, multi-line), checks the exit codes and that the commit message is never echoed, and checks that both `vercel.json` files parse and point at an existing script.

## Owner checklist (dashboard)

1. Extra project **`store-cart-next-js`** (Root Directory `fastapi_backend`, linked to the same GitHub repo, no Ignored Build Step set): disconnect its Git repository (Settings > Git > Disconnect) or delete the project. The real projects are `store-cart-next.js` (root services) and, per ADR, the backend; this duplicate was building every branch. After this change it also obeys `git.deploymentEnabled`, but it is redundant.
2. `store-cart-next.js`: keep Ignored Build Step on **Custom** `bash scripts/vercel-ignore-build.sh` (fallback). Production branch `main`, Git fork protection on (already confirmed via the API).
3. After this merges, confirm one push to `main` deploys to production on `store-cart-next.js` (not testable before merge) and that a throwaway branch push adds nothing to `vercel list`.
4. Preview environment variables must not hold production secrets.
5. Delete the throwaway remote branch `fix/KAN-244-no-preview-deployments` after the PR merges (GitHub "delete branch").
