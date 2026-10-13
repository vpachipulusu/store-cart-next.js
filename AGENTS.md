# AGENTS.md: StoreCart

Instructions for any coding agent (OpenAI Codex, Claude Code) working in this repo. Two agents alternate on this
project, so read this file and the baton before you do anything.

## Start every session here

1. Read [`.claude/progress/HANDOFF.md`](.claude/progress/HANDOFF.md) (the baton). Work only if `owner` is you or `none`.
   If the other agent owns it, stop and tell the user.
2. Read [`.claude/CLAUDE.md`](.claude/CLAUDE.md) (repo layout, commands, architecture; written for Claude but it applies to every agent),
   [`docs/developer/workflow.md`](docs/developer/workflow.md) (Jira flow, branches, commits, PRs, review routing),
   [`.claude/plans/storecart-plan.md`](.claude/plans/storecart-plan.md) and [`docs/adr/README.md`](docs/adr/README.md).
3. Check `git status`, `gh pr list` and the Jira tickets In Progress / In Review (project `KAN`,
   https://storecart.atlassian.net) before choosing work. Jira wins over the baton if they disagree.

## Hard rules

- One developer agent at a time, one agent per branch. Never touch the other agent's branch unless the baton was transferred.
- Branch `<type>/KAN-<n>-<slug>`; commits `<type>(KAN-<n>): <description>`. npm only, run from `nextjs-frontend/`.
- No force push, no history rewrite, no `--no-verify`. Never commit secrets or `.env*` files.
- Never commit untracked scratch files under `.claude/` (`.claude/worktrees/`, `kan113-runs.md`, `PRPs/`, per-ticket progress notes) unless the ticket says so.
- Do not widen scope: the ticket's acceptance criteria are the definition of done. Propose extra work as a new ticket.
- **The coverage ratchet is the owner's decision.** Never lower thresholds, and do not invent a fixed 80% target.
- **Capacitor stays in StoreCart** (merchant mobile app, KAN-109). It is left out of the template only by the export script (KAN-145).
- **Do not start KAN-145** (template export, first push to the public repo) until the owner gives an explicit go in chat. When that push does happen, the owner must see the file list first.
- Do not merge to `main` or take irreversible actions (public pushes, deleting data, spending money) without the owner's approval in chat.

## Review routing (by PR type)

| PR type | Review |
|---|---|
| Docs, tests, config only | Merge on a green **CI gate** job, no reviewer |
| Ordinary code | PM pass |
| Auth, payments, proxy, schema, structural change | PM pass and Architect pass |

Claude uses separate PM and Architect subagents. If you have no subagents, do the passes yourself, one at a time, and write each verdict in the PR:

- **PM pass:** every acceptance criterion met, no scope creep, no user-visible regression.
- **Architect pass:** consistent with the ADRs and the plan, no layering or import-cycle problems, nothing else still uses removed code (grep the whole repo).
- **Security pass** (auth, payments, input, secrets): authorization, validation, no secrets, no data leaks.
- Then read `git diff main...HEAD` once more before asking for a merge.

CI: the **CI gate** job must be green. The Playwright e2e job is outside the gate; today it is red only for the known failures KAN-154 to KAN-158 (the same four tests also fail on `main`).

## Jira

Statuses: **To-do → In Progress → In Review → Done**. Take only To-do stories. Before coding: move to In Progress and comment the branch. At PR: comment the link and move to In Review. After merge and an acceptance-criteria check: Done. If you cannot reach Jira, say so in the baton and in your handoff note, and keep the baton accurate so the next agent can sync it.

## Handing the baton back

Hand over only at a clean state: work committed and pushed, no half-run migrations, PR open or none. Then:

1. Update `.claude/progress/HANDOFF.md` (owner, ticket, branch, last SHA, status, next steps, blockers, updated) and commit it on your own branch or in a small docs PR.
2. Mirror the handoff as a comment on the Jira ticket you were working.
3. Tell the user, in chat, that the baton is free or has been passed.

Never do the handoff by editing the other agent's branch.
