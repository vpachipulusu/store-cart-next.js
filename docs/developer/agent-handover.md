# Claude and Codex continuity

The owner alternates between Claude Code and Codex subscriptions. The durable communication channel is the committed [baton](../../.claude/progress/HANDOFF.md), linked Jira comments and GitHub pull requests. Neither agent should assume it can read the other's chat or continue in the background after a turn ends.

## Taking over

1. Open this repository and read `AGENTS.md`, the baton, `.claude/CLAUDE.md`, developer workflow, implementation plan and ADR index.
2. Verify the baton names the incoming agent or `none`. If the other agent owns it, stop development until an explicit handoff; a subscription reset alone is not a transfer.
3. Check Git status, branch/head, open PRs and live Jira In Progress/In Review. Preserve unrelated untracked files. Update main only by a safe fast-forward when the working state permits; never reset or force-push to make a handover fit.
4. Resume the recorded active ticket or select an eligible To-do ticket, with the owner holds and dependencies preserved. Comment the branch and update Jira before coding. One developer owns a branch; PM/Architect/Security reviewers are read-only unless separately assigned.
5. Read the current ticket acceptance criteria and apply `AGENTS.md` review routing and CI requirements. A focused test pass is not evidence that the full suite passes. Do not weaken the coverage ratchet.

## Handing over

Finish at a reviewable, committed and pushed state: no uncommitted feature changes or half-run migration. A PR may remain open; record its exact state. If work cannot reach that state, explain the blocker and agree a recovery path instead of setting a misleading clean baton.

Update the baton on the outgoing agent's branch or a small documentation PR. Record incoming owner, active ticket, branch, last completed SHA, current PR links/head, verification results, next action, blockers, preserved scratch and date. Resolve the handover document's own revision from Git history rather than putting a self-referential SHA in its contents. Mirror the transfer as a Jira comment on the ticket last worked, or the active ticket. Tell the owner when the transfer is published. Then stop developer mutations; the incoming agent can proceed after checking the published record.

If a documentation PR still needs merging, mark that prerequisite explicitly and provide its link. Never imply the transfer is on main before it is merged. Keep Jira states truthful: only merged work with verified acceptance criteria is Done. Existing approval boundaries still apply; the handover itself does not authorize held exports, destructive operations or deployment spending.

## Prompt for a new Claude Code chat

```text
Take over StoreCart from Codex in C:\MainData\AI-Projects\store-cart-next.js.

Read AGENTS.md and .claude/progress/HANDOFF.md first, then .claude/CLAUDE.md,
docs/developer/agent-handover.md, docs/developer/workflow.md,
.claude/plans/storecart-plan.md and docs/adr/README.md. Confirm the committed
baton names claude before making developer changes. Check Git status, current
branch/head, open PRs and live Jira; preserve unrelated scratch and credentials.

Continue from the current baton rather than repeating completed work. KAN-111,
KAN-153 (PR #28) and KAN-144 (PR #29) were completed by Codex. Architect and
Product Manager recommend KAN-141 next; reread its live Jira acceptance criteria
and dependencies, and consult PM/Architect before taking it if still To-do.
Check your Vercel/Neon access before considering KAN-112. KAN-145 remains on
explicit hold; do not export or push the public template. Do not close stale
KAN-3 without asking me. Follow ticket scope, review routing and CI gates.

Check the pending full E2E run mentioned in the baton and report its actual
result; do not claim the full suite passes from the focused checks. Preserve
the KAN-144 test-only identity guards and existing coverage ratchet.

You are the sole developer while the baton names claude. Keep Jira and the
repo baton accurate. When I ask to return to Codex, stop new work, commit and
push a clean reviewable state, record ticket/branch/SHA/PR/checks/blockers,
publish a baton naming codex, and mirror that handoff in Jira. A usage-limit
reset does not transfer ownership automatically. Give me a return prompt.
```

## Prompt when returning to Codex

Use this only after explicitly requesting Claude's handback and receiving confirmation that it is published:

```text
Resume StoreCart from Claude Code in C:\MainData\AI-Projects\store-cart-next.js.
Read AGENTS.md, the latest committed .claude/progress/HANDOFF.md and
docs/developer/agent-handover.md, then the workflow, plan and ADRs. Verify the
baton names codex and check live Jira, open PRs, branch/head and Git status.
Resume the recorded next action, preserving scratch and unresolved blockers.
If claude still owns the baton, do not start concurrent edits. Consult PM and
Architect where required. KAN-145 remains held unless I explicitly release it.
```
