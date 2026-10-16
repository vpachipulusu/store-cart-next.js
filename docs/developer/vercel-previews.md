# Vercel deployments: only `main` deploys, previews are opt-in

The Vercel Hobby plan allows 100 deployments per day. Only the `CI gate` check matters for merging, so branch pushes and PR previews no longer build by default (KAN-212).

## What builds

| Push | Vercel builds? |
|---|---|
| `main` | Yes (production) |
| Any other branch or PR | No (skipped), unless the head commit message contains `[deploy preview]` |
| `vercel deploy` from the CLI | Yes (not Git-triggered, the ignore step is not consulted) |

A skipped build shows as skipped/neutral on the PR and does not count toward the daily quota. `CI gate` is unchanged and stays the only required check.

## How it works

`vercel.json` sets `"ignoreCommand": "bash scripts/vercel-ignore-build.sh"`. The script exits `1` (build) for `main`, for a commit message containing `[deploy preview]` (case-insensitive), or when no git branch info is available; otherwise it exits `0` (skip). It reads only `VERCEL_GIT_COMMIT_REF` and `VERCEL_GIT_COMMIT_MESSAGE` and never prints the message or any secret.

The repo is a single Vercel project (root `vercel.json`, ADR-011, services `nextjs-frontend` and `fastapi_backend`), so one ignore command covers frontend and backend. If a separate backend project is ever created, point its `ignoreCommand` at the same script (the path is relative to that project's Root Directory; use `bash ../scripts/vercel-ignore-build.sh` when the root is `fastapi_backend`, and enable "Include source files outside of the Root Directory").

## Getting a preview on purpose

Put the marker in the head commit message of the branch, then push:

```bash
git commit --allow-empty -m "chore(KAN-123): preview please [deploy preview]"
git push
```

Only the head commit is checked, so repeat the marker on each push that needs a fresh preview. Alternatively deploy by hand with the root scripts: `npm run vercel:pull`, `npm run vercel:build`, `npm run vercel:preview`.

Preview deployments need their own preview environment variables (see the backend deploy audit and ADR-003); a preview built without them will answer 503 on the routes that need them.

## Dry-run test

```bash
bash scripts/vercel-ignore-build.test.sh
```

It runs the script under main, feature-branch, marker, case and empty-env scenarios and checks the exit codes and that the commit message is never echoed.

## Owner checklist (dashboard)

Settings that only the project owner can verify or change:

1. Project Settings > Build and Deployment > Ignored Build Step: leave on **Automatic**. `vercel.json` overrides it.
2. Project Settings > Git: confirm the production branch is `main`.
3. After the first merge, confirm a push to a throwaway branch creates no deployment, and a throwaway branch with `[deploy preview]` does create one.
4. Confirm Git fork protection is on for the project and that preview environment variables hold no production secrets. The `[deploy preview]` marker is a quota control, not an access control: anyone who can push to the repo can use it, and the script itself lives in the pushed branch.
5. If the `ignoreCommand` is not honoured for the `services` layout (services are in beta), set the Ignored Build Step in the dashboard to `bash scripts/vercel-ignore-build.sh` instead.
