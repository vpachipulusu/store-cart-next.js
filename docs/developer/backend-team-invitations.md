# Team invitations and roles (KAN-62)

Owners and admins invite people to their organisation by email. Code: `app/api/v1/invitations.py`,
`app/services/invitations.py`, `app/repositories/invitations.py`, `app/services/email.py`. The table is
`invitations` from the platform baseline (no new migration).

## Routes

All need `X-Internal-Key` and a verified session, are rate limited by subject and answer `no-store`.

| Route | Who | Notes |
|---|---|---|
| `GET /v1/organizations/{id}/members` | OWNER, ADMIN | Members with email, name and role; `limit` (default 50, max 100) and `offset`. |
| `GET /v1/organizations/{id}/invitations` | OWNER, ADMIN | Pending, unexpired invitations. Never a token, hash or link. |
| `POST /v1/organizations/{id}/invitations` | OWNER, ADMIN | `{email, role}` with role `ADMIN` or `STAFF` (OWNER is a 422). Returns the accept link once, plus `email_sent`. Extra `invitation` budget: 20 per hour per user, fail closed. |
| `POST /v1/invitations/accept` | any signed-in user | `{token}` in the body (never a GET, so link prefetchers cannot spend it). |

STAFF gets 403 and a non-member 404 on the organisation routes.

## Tokens and expiry

- The token is `secrets.token_urlsafe(32)`; only its sha256 is stored in `token_hash`. The link
  `{APP_PUBLIC_URL}/invite/{token}` is returned by the create call and emailed, and is never listed, logged
  or written to the audit log.
- An invitation expires 7 days after creation. Expired PENDING rows are marked `EXPIRED` when the same
  organisation next creates an invitation; a new invitation for that email can then be sent.
- Inviting an address that already has an open invitation supersedes it (the old row is REVOKED and a new link is
  issued, same transaction, same lock), so a lost link never locks an address out. At most 50 open per organisation (409), and the
  staff limit of the plan is checked on create (members plus open invitations, so the plan cannot be
  oversold) and again on accept (members only) (409 with the plan message).

## Accept

Emails are compared in one canonical form (`canonical_email`: trimmed, lower-case), which is also the form invitations
are stored in. Before the lock, a cheap pre-check refuses an unknown, used, revoked or expired token (410) and a session
email that does not match (403). Then one transaction under the organisation row lock (`SELECT ... FOR UPDATE`):

1. `UPDATE invitations SET status='ACCEPTED', accepted_at=:now WHERE token_hash=:h AND status='PENDING'
   AND expires_at > :now AND email = :canonical_session_email RETURNING *`. This is the authority: of two
   concurrent accepts only one sees PENDING; the other gets 410.
2. The caller must not already be a member (409), then the staff limit (409).
3. Insert the membership with the invited role and an `invitation.accept` audit row.

Any refusal rolls the transaction back, so the invitation stays PENDING. Refusals are logged with the cause, the
invitation id and the user id only (never the email or the token).

## Email

`app/services/email.py` holds the `EmailSender` protocol, `ResendEmailSender` (httpx to the Resend API) and
`DisabledEmailSender`. `get_email_sender` in `app/api/deps.py` picks Resend when `RESEND_API_KEY` and
`EMAIL_FROM` are set (set both or neither: one alone refuses to start; blank counts as unset), else the disabled sender, which logs "email disabled" and raises `EmailDisabled` (so the
create response says `email_sent: false`). Senders never log a
recipient, subject or body. The subject is fixed and the organisation name in the body is one line of at most 80
characters (merchant free text, phishing guard). The send has a 5 second total deadline (`asyncio.timeout`, httpx
connect 2 s). If sending fails the invitation still exists and the response has
`email_sent: false`, so the inviter can copy the link.

## Frontend

`src/lib/api/team.ts`, `src/app/actions/team-actions.ts`, `/dashboard/settings/team` (members, invite form,
pending invitations) and the public `/invite/[token]` page with an explicit Accept button. STAFF sees
`PermissionNotice` on the team and billing settings pages (`canManageTeam` in `src/lib/api/team.ts`, billing gate in `src/app/dashboard/settings/billing/layout.tsx`).
