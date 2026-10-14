# Backend admin users API (KAN-47, KAN-124)

Platform-admin user management in FastAPI. Authorisation is the `require_admin(...)`
dependency and the audit trail is `AdminAuditor` (see [backend-auth.md](backend-auth.md) and
[platform-models.md](platform-models.md)). Stats and admin-sent notifications are KAN-114.

## Routes

All under `/v1/admin/users`, behind the internal service key and the `X-Session-Token` session.
Success bodies are `{"success": true, "data": ...}`; errors use the standard envelope.

| Route                     | Permission      | Notes                                                                                         |
| ------------------------- | --------------- | --------------------------------------------------------------------------------------------- |
| `GET ""`                  | `users.read`    | `limit` 1 to 100 (default 20), `offset`, `search` (email or name, literal match)              |
| `GET /{user_id}`          | `users.read`    | Profile, admin role and effective permissions. No 2FA secret                                  |
| `PATCH /{user_id}`        | `users.update`  | Profile fields only (name, bio, location, website, phone, avatar). Email is owned by Firebase |
| `DELETE /{user_id}`       | `users.delete`  | Deletes the Firebase account and the row. Refuses admins and organisation owners              |
| `PUT /{user_id}/admin`    | `admins.create` | Body `{role, permissions}`; creates or replaces the admin grant                               |
| `DELETE /{user_id}/admin` | `admins.delete` | Removes the admin grant                                                                       |
| `POST /{user_id}/ban`     | `users.update`  | Disables the Firebase user and revokes refresh tokens. Optional `{reason}`                    |
| `POST /{user_id}/unban`   | `users.update`  | Re-enables the Firebase user                                                                  |

Ban state lives in Firebase (a disabled user fails session verification), so no column was added
and the detail response has no `banned` field.

## Privilege rules (KAN-124)

Enforced in `app/services/admin_users.py`, on top of `assert_can_grant`:

- Nobody changes their own admin grant, up or down (403). Revoking, banning or deleting yourself is 409.
- Only a `super_admin` grants `super_admin` or `*`; nobody grants a permission they do not hold. `*` with
  the `admin` role is a 422.
- A non-super admin cannot grant to, revoke, ban or edit a `super_admin`, or an admin holding permissions
  they lack (403).
- The last `super_admin` cannot be revoked or demoted (409). The check locks the super-admin rows, so two
  super admins revoking each other at once leave one.

Denied requests write no audit row; they are logged without payload by `require_admin`.

## Audit

Each change stages one row in the same transaction and commits once after `record`:
`admin.users.update`, `admin.users.delete`, `admin.users.ban`, `admin.users.unban`,
`admin.users.grant_admin` and `admin.users.revoke_admin` (resource `admin_users`, with `before` and `after`
role and permissions). Profile updates record changed field names only, never values.

Ban and delete call Firebase after the audit row is staged and before the commit. A Firebase failure rolls
the change back; a commit failure after a successful Firebase call leaves the same residue as account
deletion (see [backend-profile.md](backend-profile.md)).

## Tests

- `tests/services/test_admin_users.py`: rules with in-memory fakes.
- `tests/api/test_admin_users.py`: routes through the real `require_admin` chain.
- `tests/api/test_admin_users_e2e.py`: real Postgres through the real app (same `TEST_DATABASE_URL` contract
  as the Stripe webhook e2e); asserts 401, 403, self-escalation refusal, audit rows, rollback and the
  concurrent super-admin case.
