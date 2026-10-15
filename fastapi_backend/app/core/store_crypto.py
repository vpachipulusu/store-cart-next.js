"""AES-256-GCM encryption for store database connection strings (KAN-53).

Envelope: ``v1.<key id>.<base64url(nonce || ciphertext || tag)>``. The key id is a
short fingerprint of the key so rotation can pick the right one. The store id is
bound as associated data, so a ciphertext copied to another store's row fails
authentication. Every failure raises :class:`StoreSecretUnavailable` with no detail:
messages never carry plaintext, ciphertext or key material.
"""

import base64
import binascii
import hashlib
import os
from collections.abc import Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENVELOPE_VERSION = "v1"
KEY_BYTES = 32
NONCE_BYTES = 12
KEY_ID_HEX_LENGTH = 8


class StoreSecretUnavailable(Exception):
    """Key configuration or stored ciphertext cannot be used safely."""


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))


def parse_key(value: str) -> bytes:
    """Decode a base64url 32 byte key; raise StoreSecretUnavailable otherwise."""
    try:
        key = _b64decode(value.strip())
    except (binascii.Error, ValueError, UnicodeError):
        raise StoreSecretUnavailable() from None
    if len(key) != KEY_BYTES:
        raise StoreSecretUnavailable()
    return key


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:KEY_ID_HEX_LENGTH]


def _aad(store_id: str) -> bytes:
    return f"storecart:store-connection:{ENVELOPE_VERSION}:{store_id}".encode()


class StoreSecretCodec:
    """Encrypts with ``current_key``; decrypts with it or any ``previous_keys``."""

    def __init__(self, current_key: str | None, previous_keys: Sequence[str] = ()):
        if not current_key:
            raise StoreSecretUnavailable()
        current = parse_key(current_key)
        self._current_id = _key_id(current)
        self._keys = {self._current_id: AESGCM(current)}
        for value in previous_keys:
            raw = parse_key(value)
            self._keys.setdefault(_key_id(raw), AESGCM(raw))

    def encrypt(self, plaintext: str, store_id: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._keys[self._current_id].encrypt(
            nonce, plaintext.encode("utf-8"), _aad(store_id)
        )
        payload = base64.urlsafe_b64encode(nonce + sealed).decode("ascii")
        return f"{ENVELOPE_VERSION}.{self._current_id}.{payload}"

    def decrypt(self, envelope: str, store_id: str) -> str:
        try:
            version, key_id, payload = envelope.split(".")
            raw = _b64decode(payload)
            cipher = self._keys.get(key_id)
            if version != ENVELOPE_VERSION or cipher is None or len(raw) <= NONCE_BYTES:
                raise StoreSecretUnavailable()
            plaintext = cipher.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], _aad(store_id)
            )
            return plaintext.decode("utf-8")
        except (ValueError, binascii.Error, InvalidTag, UnicodeError):
            raise StoreSecretUnavailable() from None

    def needs_rotation(self, envelope: str) -> bool:
        """True when the envelope was sealed with a key other than the current one."""
        parts = envelope.split(".")
        return len(parts) != 3 or parts[1] != self._current_id

    def rotate(self, envelope: str, store_id: str) -> str:
        """Re-encrypt under the current key (decrypts first, so it verifies too)."""
        return self.encrypt(self.decrypt(envelope, store_id), store_id)
