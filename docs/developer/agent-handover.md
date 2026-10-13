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

Continue from the current baton rather than repeating completed work. Codex
completed KAN-37 (PR #43), KAN-38 (#44), KAN-39 (#45), and the requested legacy
browser journeys KAN-162 (#46). KAN-130 was reconciled as already fixed by
KAN-146. PM and Architect recommend KAN-154 and KAN-123 next, then KAN-155.
Recheck To-do status and acceptance criteria before pickup. For KAN-123,
enforce verified Firebase claims at actual legacy server boundaries before
removing proxy cookie decisions; backend guards alone do not protect the old UI.

I authorized two developer agents with separate file/branch ownership, with
one coordinator holding the baton and read-only PM/Architect/Security reviews.
Keep Claude and Codex development mutually exclusive. Retain my configured
Claude model preferences. Create PRs and merge after required reviews and a
green CI gate under my existing authorization; E2E_ENABLED remains false.

Use legacy browser tests with dedicated test services only, as requested.
KAN-162's focused result is 11 passes in 44.2 seconds (eight new journeys and
three setup checks); it is not a full-baseline pass or proof of new FastAPI
execution before KAN-41. Avatar remains a placeholder. KAN-39 does not enforce
TOTP at sign-in (KAN-125 remains open); KAN-163 tracks refresh history duplicates.
Do not add an emulator or automatically enable E2E. Preserve coverage floors.

KAN-145 remains held: no public template export or first push without explicit
go and the file list. KAN-115 only when I am ready. Never operate on production
Neon; no build runs migrations. Do not close stale KAN-3 without asking me.

Keep Jira and the repo baton accurate. When I ask to return to Codex, stop new
work, commit and push a clean reviewable state, record ticket/branch/SHA/PR/checks/
blockers, publish a baton naming codex, and mirror the handoff in Jira. A usage
limit reset does not transfer ownership automatically. Give me a return prompt.
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
