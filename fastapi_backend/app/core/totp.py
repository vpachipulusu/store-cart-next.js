import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken


class TotpUnavailable(Exception):
    """Encryption configuration or stored material cannot be used safely."""


class TotpCodec:
    def __init__(self, encryption_key: str | None) -> None:
        try:
            if not encryption_key:
                raise ValueError()
            self.cipher = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise TotpUnavailable() from None

    def encrypt(self, secret: str) -> str:
        return self.cipher.encrypt(secret.encode("ascii")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self.cipher.decrypt(ciphertext.encode("ascii")).decode("ascii")
        except (InvalidToken, ValueError, UnicodeError):
            raise TotpUnavailable() from None


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def provisioning_uri(secret: str, email: str, issuer: str = "StoreCart") -> str:
    label = quote(f"{issuer}:{email}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": 6,
            "period": 30,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def token_at(secret: str, timestamp: float) -> str:
    try:
        key = base64.b32decode(secret, casefold=True)
        digest = hmac.new(
            key, struct.pack(">Q", int(timestamp // 30)), hashlib.sha1
        ).digest()
    except (ValueError, struct.error):
        raise TotpUnavailable() from None
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_token(secret: str, token: str, timestamp: float | None = None) -> bool:
    if len(token) != 6 or not token.isascii() or not token.isdigit():
        return False
    now = time.time() if timestamp is None else timestamp
    matches = [
        hmac.compare_digest(token_at(secret, now + drift * 30), token)
        for drift in (-1, 0, 1)
        if now + drift * 30 >= 0
    ]
    return any(matches)
