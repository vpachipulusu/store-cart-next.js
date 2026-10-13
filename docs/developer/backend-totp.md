# Backend TOTP

KAN-39 provides enrolment, verification and disabling through the server-only
backend client. It does not change Firebase sign-in or enforce TOTP during login.
Frontend switch-over remains KAN-41.

All `/v1/me/totp` POST routes require a valid internal service key, a revoked-checked
Firebase session with verified email, and the fail-closed authentication limiter
keyed by Firebase UID. Responses use `Cache-Control: no-store`.

- `/enroll`: supply `id_token` from recent Firebase reauthentication. It must belong
  to the same UID, have verified email, and have `auth_time` within the last five
  minutes. Returns `data.secret` and `data.uri` once for that enrollment.
- `/verify`: supply the six-digit `token` to enable the pending enrollment.
- `/disable`: supply a recent same-user `id_token` and a valid `token`. Disabling
  clears the stored secret.

TOTP uses SHA-1, six digits, a 30-second period and a one-period drift window,
matching the existing authenticator setup. Already-enabled users cannot replace
their secret through enrollment. Reenrollment before confirmation replaces the
pending secret. Verification and disabling return only `success`; no profile,
status or error response returns the secret or provisioning URI.

The existing `two_factor_secret` column holds Fernet ciphertext. Configure a
separate backend `TOTP_ENCRYPTION_KEY` using a securely generated Fernet key.
Missing configuration and undecryptable ciphertext fail closed with 503. An invalid
configured key prevents startup. Preserve this key securely across deployments: replacing it without migrating
ciphertext makes existing enrollments unusable. No plaintext fallback is allowed.
Do not log keys, secrets, codes, ID tokens or provisioning URIs.

Each mutation runs in a service-owned transaction and locks the user's row before
checking and changing enrollment state. Repositories never commit or create a
session. Unit tests use fake identity providers, transactions and repositories;
no real Firebase, Redis or database is contacted.
