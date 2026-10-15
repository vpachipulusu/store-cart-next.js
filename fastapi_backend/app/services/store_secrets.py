"""Encrypt, read and rotate a store's database connection string (KAN-53).

The plaintext exists only in memory, for the duration of a call. Nothing here logs
it, and failures log only the store id. Persisting is the caller's job: these helpers
mutate the ``Store`` instance and the request's session commits.
"""

import logging
from functools import lru_cache

from app.core.config import settings
from app.core.store_crypto import StoreSecretCodec, StoreSecretUnavailable
from app.models.platform.store import Store

logger = logging.getLogger("storecart.store_secrets")


@lru_cache(maxsize=1)
def get_codec() -> StoreSecretCodec:
    """Codec for the configured keys; raises StoreSecretUnavailable when unset."""
    key = settings.STORE_DB_ENCRYPTION_KEY
    return StoreSecretCodec(
        key.get_secret_value() if key else None, settings.store_db_previous_keys
    )


def set_connection_string(
    store: Store, connection_string: str, codec: StoreSecretCodec | None = None
) -> None:
    if not connection_string.strip():
        raise ValueError("connection string must not be empty")
    store.connection_string_encrypted = (codec or get_codec()).encrypt(
        connection_string, store.id
    )


def reveal_connection_string(
    store: Store, codec: StoreSecretCodec | None = None
) -> str | None:
    """Plaintext connection string, or None when none is stored.

    Raises StoreSecretUnavailable on tampering, a wrong store or a wrong key.
    """
    if store.connection_string_encrypted is None:
        return None
    try:
        return (codec or get_codec()).decrypt(
            store.connection_string_encrypted, store.id
        )
    except StoreSecretUnavailable:
        logger.error(
            "store connection string could not be decrypted",
            extra={"store_id": store.id},
        )
        raise


def rotate_connection_string(
    store: Store, codec: StoreSecretCodec | None = None
) -> bool:
    """Re-encrypt under the current key. True when the stored value changed."""
    envelope = store.connection_string_encrypted
    if envelope is None:
        return False
    active = codec or get_codec()
    if not active.needs_rotation(envelope):
        return False
    try:
        store.connection_string_encrypted = active.rotate(envelope, store.id)
    except StoreSecretUnavailable:
        logger.error(
            "store connection string rotation failed", extra={"store_id": store.id}
        )
        raise
    return True
