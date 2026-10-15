# Backend store connection strings (KAN-53)

Each store has its own database (ADR-005). Its connection string is a credential, so the platform database keeps only
an AES-256-GCM envelope in `stores.connection_string_encrypted` (migration `0005`). No API returns it and nothing logs it.

## Configuration

| Variable                           | Purpose                                                                                                  |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `STORE_DB_ENCRYPTION_KEY`          | Current key: base64url of 32 random bytes. **Required** outside local, test, Vercel preview/development. |
| `STORE_DB_ENCRYPTION_KEY_PREVIOUS` | Optional comma separated retired keys, used only to decrypt during rotation.                             |

Generate a key with `python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. Settings
validation fails at startup when a key is missing (deployed) or malformed. Keep it in a secret manager, separate from
`TOTP_ENCRYPTION_KEY`; losing it makes every stored connection string unrecoverable.

## Envelope and behaviour

`v1.<key id>.<base64url(nonce || ciphertext || tag)>`. The key id is a short SHA-256 fingerprint of the key, so the right
key is picked during rotation. The store id is bound as associated data: a value copied to another store's row fails
authentication. Tampering, a wrong key, a wrong store or a malformed value all raise `StoreSecretUnavailable` with no
detail; the service logs only the store id.

Use `app.services.store_secrets` (`set_connection_string`, `reveal_connection_string`, `rotate_connection_string`);
the session factory (KAN-54) is the only intended caller of `reveal_connection_string`. Callers commit.

## Rotation

1. Set `STORE_DB_ENCRYPTION_KEY` to a new key and move the old one to `STORE_DB_ENCRYPTION_KEY_PREVIOUS`; deploy.
2. Re-encrypt rows with `rotate_connection_string` (it is a no-op for rows already on the current key).
3. Once no row uses the old key id, remove it from `STORE_DB_ENCRYPTION_KEY_PREVIOUS`.

The audit trail redacts `connection string`, `database url`, `dsn` keys and `postgres://` values.
