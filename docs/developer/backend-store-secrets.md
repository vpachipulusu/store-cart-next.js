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

## Store database sessions (KAN-54)

`app.services.store_sessions.get_store_session(store_id)` is the only way to open a store database:

```python
async with get_store_session(store_id) as session:
    ...  # an AsyncSession on that store's database only
```

It reads the `Store` row from the platform database, decrypts the connection string, builds a `NullPool` engine for it
(no long-lived pools; safe on Vercel and Neon pooled endpoints, with asyncpg's statement cache off for PgBouncer) and
disposes the engine when the context exits. Failures are typed and carry only the store id, never the connection string:
`StoreNotFound`, `StoreDatabaseNotConfigured` (no connection string yet) and `StoreDatabaseUnavailable` (cannot be
decrypted or parsed), all subclasses of `StoreSessionError`. No new environment variable.

A ruff `TID251` banned-api rule (`pyproject.toml`) rejects `create_engine`, `create_async_engine` and
`app.core.database.build_engine` everywhere except `app/core/database.py`, `app/services/store_sessions.py`, Alembic's
`env.py` and the tests.
