# Plan: KAN-25 — Commit monorepo move into nextjs-frontend/ and fastapi_backend/

## Summary
The Next.js app has been moved on disk from the repo root into `nextjs-frontend/`, and the vintasoftware template backend was copied into `fastapi_backend/`, but nothing is committed and the root `.gitignore` would leak build/test/log output and blocks lockfiles. This story fixes `.gitignore`, commits the move so Git keeps rename history, imports the template backend unmodified with attribution, and commits the planning docs — in five reviewable commits on one branch.

## User Story
As the StoreCart developer (and the agents working the backlog), I want the monorepo layout committed cleanly with correct ignore rules, so that every later story starts from a reproducible, secret-free tree with intact file history.

## Problem → Solution
Uncommitted move, leaky root-anchored `.gitignore`, ignored lockfile, untracked template backend → five clean commits on `chore/KAN-25-commit-monorepo-move`, verified renames, no secrets or generated output tracked, frontend builds from a clean install.

## Metadata
- **Complexity**: Small (config + git operations; ~4 edited files, ~170 renamed files, ~48 imported files)
- **Source PRD**: N/A — Jira KAN-25 (epic E1, KAN-4), refined by architect + PM review on 2026-10-11
- **PRD Phase**: Foundation / E1 / start-order step 1
- **Estimated Files**: 4 edited, 1 added (template licence), ~170 renamed, ~48 imported, docs

---

## UX Design
N/A — internal repository change. No user-facing behaviour changes.

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `.gitignore` | 1-73 | Every pattern to keep, re-anchor or scope (see Task 2) |
| P0 | `fastapi_backend/.gitignore` | all | Only contains `.vercel` — root must cover Python caches |
| P0 | `nextjs-frontend/playwright.config.ts` | 59-60 | `webServer.command: 'pnpm dev'` → `npm run dev` |
| P0 | `.claude/CLAUDE.md` | "Repository layout", "Testing Notes" | Already says npm commands run from `nextjs-frontend/`; remove the stale `pnpm dev` note |
| P1 | `nextjs-frontend/package.json` | 12-35 | `build` = `next build --webpack`, `typecheck` = `tsc --noEmit`, `lint` = `next lint` (do not touch here — KAN-111) |
| P2 | `.claude/plans/storecart-plan.md` | all | Committed in the docs commit |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| Rename detection | `git diff -M` / `git log --follow` | Renames are inferred from content similarity; keep moved files byte-identical in the move commit |
| Template licence | github.com/vintasoftware/nextjs-fastapi-template (MIT) | MIT requires keeping the copyright and permission notice with copies |
| Upstream reference | `vintasoftware/nextjs-fastapi-template@62b67456e8f01760970455282282ecaa393fbd38` (latest `main`, 2025-12-17) | Record in commit 4; the exact commit the user copied from is not known — say so |

---

## Patterns to Mirror

### COMMIT_MESSAGES
// SOURCE: .claude/CLAUDE.md "Work tracking (Jira)" rule 3
`<type>(KAN-<n>): <description>` — conventional commit types. Branch `<type>/KAN-<n>-<short-slug>`.

### JIRA_WORKFLOW
// SOURCE: .claude/CLAUDE.md "Work tracking (Jira)"
Move KAN-25 To-do → In Progress with a pickup comment naming the branch before any change; PR → In Review; merge → Done.

### NPM_ONLY
// SOURCE: .claude/CLAUDE.md "Package Manager"
"This project uses npm exclusively. Do not use pnpm or yarn." → lockfile is `package-lock.json`; ignore `yarn.lock`, `pnpm-lock.yaml`.

### ERROR_HANDLING / LOGGING / REPOSITORY / SERVICE / TEST_STRUCTURE
N/A — no application code changes in this story. Verification is by git and npm commands (see Validation).

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `.gitignore` | UPDATE | Nested patterns, frontend-scoped rules, Python caches, lockfile policy |
| `nextjs-frontend/**` (~170 files) | RENAME (from root) | The move itself — byte-identical |
| `nextjs-frontend/playwright.config.ts` | UPDATE | `pnpm dev` → `npm run dev` (moved here from KAN-28) |
| `.claude/CLAUDE.md` | UPDATE | Remove stale `pnpm dev` note in Testing Notes |
| `fastapi_backend/**` (48 files) | ADD | Unmodified template import |
| `fastapi_backend/TEMPLATE_LICENSE.txt` | ADD | MIT notice from upstream `LICENSE.txt` |
| `.claude/plans/**`, `.claude/PRPs/**`, `PROJECT-CONTEXT.md` | ADD | Planning docs (separate commit) |
| root `.next/` | DELETE (untracked, disk only) | Stale build output from before the move |

## NOT Building
- No template adaptation (KAN-30), no pre-commit (KAN-111), CI (KAN-27), Docker Compose (KAN-26), Vercel projects (KAN-28/KAN-112), ADRs (KAN-29).
- No change to the `lint` script (`next lint`) — KAN-111.
- No push or PR without the user's go-ahead.

---

## Step-by-Step Tasks

### Task 1: Pick up the story
- **ACTION**: Transition KAN-25 to In Progress; comment "Picked up on branch `chore/KAN-25-commit-monorepo-move`"; `git switch -c chore/KAN-25-commit-monorepo-move`.
- **GOTCHA**: Creating the branch carries the uncommitted working tree with it — nothing is lost.
- **VALIDATE**: `git branch --show-current` prints the branch; Jira shows In Progress.

### Task 2: Fix `.gitignore` (commit 1)
- **ACTION**: Rewrite `.gitignore`:
  - Unanchor nested output: `.next/`, `coverage/`, `logs/`, `playwright-report/`, `test-results/`, `playwright/.cache/`, `.pnp`, `.pnp.js`.
  - Scope to frontend: `nextjs-frontend/out/`, `nextjs-frontend/build/`, `nextjs-frontend/ios/`, `nextjs-frontend/android/`, `nextjs-frontend/capacitor.config.json`, `nextjs-frontend/prisma/migrations/`.
  - Lockfiles: remove `package-lock.json`; keep `yarn.lock`; add `pnpm-lock.yaml`.
  - Python: `.venv/`, `venv/`, `__pycache__/`, `*.py[cod]`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `.coverage`, `htmlcov/`.
  - Keep: env files (`.env`, `.env.local`, `.env*.local` …), `*.pem`, `.sentryclirc`, `.vercel`, `*.tsbuildinfo`, IDE, `next-env.d.ts`, `nul`.
- **GOTCHA**: `out/` and `build/` unanchored would also match legitimate source folders — scope them.
- **VALIDATE**: `git check-ignore -v nextjs-frontend/.env nextjs-frontend/.env.local nextjs-frontend/logs nextjs-frontend/playwright-report nextjs-frontend/test-results .ruff_cache` all match; `git check-ignore nextjs-frontend/package-lock.json fastapi_backend/uv.lock nextjs-frontend/.env.example fastapi_backend/.env.example` match nothing.
- **COMMIT**: `chore(KAN-25): update .gitignore for monorepo layout`

### Task 3: Pure move (commit 2)
- **ACTION**: `git add -A nextjs-frontend` and `git add -u .` (stages root deletions) — nothing else.
- **GOTCHA**: Do not edit any moved file before this commit. `core.autocrlf=true` normalises line endings to LF, matching the originals.
- **VALIDATE**: `git diff --cached -M --summary` lists only `rename` lines apart from genuinely new files (the lockfile); `git diff --cached --name-only | grep -E '(^|/)\.env($|\.local)|/logs/|test-results|playwright-report|\.next/|\.pem$'` returns nothing.
- **COMMIT**: `chore(KAN-25): move Next.js app into nextjs-frontend/`

### Task 4: Path fixes (commit 3)
- **ACTION**: `playwright.config.ts` line 60 `'pnpm dev'` → `'npm run dev'`; `.claude/CLAUDE.md` Testing Notes: replace the stale `pnpm dev` bullet with "Playwright starts `npm run dev` in `nextjs-frontend/`".
- **VALIDATE**: `git diff` shows only those lines.
- **COMMIT**: `fix(KAN-25): use npm in Playwright config and update CLAUDE.md`

### Task 5: Template import (commit 4)
- **ACTION**: Fetch upstream `LICENSE.txt` into `fastapi_backend/TEMPLATE_LICENSE.txt`; `git add fastapi_backend`.
- **GOTCHA**: No nested `.git` in `fastapi_backend/` (verified). Do not modify template files.
- **VALIDATE**: `git diff --cached --stat` shows only `fastapi_backend/`; `.env.example` included, no `.env`.
- **COMMIT**: `chore(KAN-25): import fastapi_backend from vintasoftware/nextjs-fastapi-template` with body naming the upstream repo, latest-main SHA `62b6745` (exact copied commit unknown), MIT licence.

### Task 6: Planning docs (commit 5)
- **ACTION**: `git add .claude/plans .claude/PRPs PROJECT-CONTEXT.md`.
- **COMMIT**: `docs(KAN-25): add StoreCart plan, backlog, Jira map and project context`

### Task 7: Clean up and verify
- **ACTION**: Delete untracked root `.next/`. In `nextjs-frontend/`: `npm ci`, `npm run typecheck`, `npm run test:unit`, `npm run build`.
- **VALIDATE**: All pass; `git status` clean except ignored files.

### Task 8: Hand-off
- **ACTION**: Ask the user before pushing / opening the PR. On PR: comment link on KAN-25 and move to In Review.

---

## Testing Strategy
No new application code. Verification is the command set below; the existing unit tests are run once to confirm the move did not break module resolution.

### Edge Cases Checklist
- [ ] `.env` / `.env.local` present on disk but never staged
- [ ] Lockfiles present and tracked
- [ ] Files with CRLF warnings still detected as renames
- [ ] No nested `.git` in `fastapi_backend/`

## Validation Commands

### Static Analysis
```bash
npm --prefix nextjs-frontend run typecheck
```
EXPECT: zero type errors

### Unit Tests
```bash
npm --prefix nextjs-frontend run test:unit
```
EXPECT: same results as before the move

### Build
```bash
npm --prefix nextjs-frontend ci && npm --prefix nextjs-frontend run build
```
EXPECT: clean install and production build succeed

### Git checks
```bash
git log --oneline main..HEAD
git log --follow --oneline -- nextjs-frontend/src/proxy.ts
git ls-files | grep -E '(^|/)\.env($|\.local)|/logs/|test-results/|playwright-report/|(^|/)\.next/|\.pem$'
```
EXPECT: 5 commits; `--follow` reaches the initial commit; last command prints nothing

## Acceptance Criteria
- [ ] All KAN-25 Jira acceptance criteria met
- [ ] Validation commands pass
- [ ] No secrets or generated output tracked

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `npm run build` needs env vars or network | Medium | Low | `.env`/`.env.local` exist locally; if build fails for env reasons, record it and confirm typecheck + unit tests |
| Rename detection drops below threshold for edited files | Low | Medium | No edits in the move commit |
| Wrong upstream SHA attributed | Medium | Low | Commit message states the exact copied commit is unknown |

## Notes
- Reviews: architect and PM agreed on lockfile commit, scoped patterns, template import in this story, Playwright fix moved here.
- Confidence: 9/10.

## Execution notes (2026-10-11)
- **The move was already committed and pushed** by the user (`ab379f0 Added fastapi`, 166 renames recorded, so history is kept; `fastapi_backend/` and the plans followed in `1e87d33`, `8aee769`). Tasks 3, 5 (import) and 6 were therefore already done; the branch carries only the fixes.
- The old `.gitignore` let `nextjs-frontend/logs/`, `playwright-report/` and `test-results/` into `main` (public repo). Scanned: no credentials, emails or tokens; one log line contains a local filesystem path. Untracked in this branch; no history rewrite needed.
- `package-lock.json` was stale (missing Sentry, winston, …); regenerated with `npm install` (no `package.json` change). `npm ci` then succeeds.
- After `npm ci`, `npm run typecheck` fails until `npm run db:generate` runs (no `postinstall`). With it: typecheck passes, 15/15 unit tests pass. CI (KAN-27) must run `db:generate`.
- **`npm run build` fails — pre-existing boilerplate defect, not caused by the move**: the client component `src/components/admin/general-settings-form.tsx` imports `CURRENCIES` from `src/config/subscriptions.ts`, which imports Stripe, Prisma and the winston logger (`fs`). Raised with the user as a separate bug story.
- Branch commits: `f43b998` .gitignore + untrack output, `17a3b75` lockfile, `2eb6a5a` Playwright/CLAUDE.md, `dde276f` template licence, then this plan.
