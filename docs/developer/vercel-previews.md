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

There are two Vercel projects, and each reads its own config file (the one in its Root Directory):

| Project | Root Directory | Config file | `ignoreCommand` |
|---|---|---|---|
| Frontend (`store-cart-next-js`) | repo root | `vercel.json` | `bash scripts/vercel-ignore-build.sh` |
| Backend (`store-cart-backend`) | `fastapi_backend` | `fastapi_backend/vercel.json` | `bash ../scripts/vercel-ignore-build.sh` |

The backend project's script lives outside its Root Directory, so that project needs Settings > Build and Deployment > **Include source files outside of the Root Directory in the Build Step** turned on. Without it the script is missing, the command fails, and Vercel builds (fail open: the backend keeps building every branch, but nothing is ever wrongly skipped). The script never skips `main`.

(ADR-011 describes a single project with services; if the backend is ever folded into the root project, `fastapi_backend/vercel.json` can be deleted.)

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

It runs the script under main, feature-branch, marker, case, empty-env and hostile-message scenarios (quotes, `$`, backticks, multi-line), checks the exit codes and that the commit message is never echoed, and checks that both `vercel.json` files parse and point at an existing script.

## Owner checklist (dashboard)

Settings that only the project owner can verify or change:

1. Both projects, Settings > Build and Deployment > Ignored Build Step: leave on **Automatic**. The `vercel.json` files override it.
2. Backend project (`store-cart-backend`) only: turn on **Include source files outside of the Root Directory in the Build Step**.
3. Both projects, Settings > Git: confirm the production branch is `main`.
4. After the first merge, on each project confirm a push to a throwaway branch creates no deployment, a push to `main` still deploys, and a throwaway branch with `[deploy preview]` does create one.
5. Confirm Git fork protection is on for the project and that preview environment variables hold no production secrets. The `[deploy preview]` marker is a quota control, not an access control: anyone who can push to the repo can use it, and the script itself lives in the pushed branch.
6. If the `ignoreCommand` is not honoured on a project, set its Ignored Build Step in the dashboard to the same command (`bash scripts/vercel-ignore-build.sh` for the frontend, `bash ../scripts/vercel-ignore-build.sh` for the backend).
