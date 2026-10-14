"""Slug rules shared by organisations and stores (KAN-59).

A slug is a DNS-safe label: it becomes part of a store's public host name, so the rules
are strict. Input is ASCII only (checked before lower-casing, so look-alikes such as the
Kelvin sign cannot fold into ``k``), lower-cased, then must be 3 to 63 characters of
``a-z``, ``0-9`` and single hyphens, with no hyphen at either end. Consecutive hyphens
are refused, which also rules out the ``xn--`` punycode prefix. Names on the reserved
list are refused so a merchant cannot take a platform host.
"""

import re

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 63
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "www",
        "admin",
        "api",
        "app",
        "mail",
        "email",
        "smtp",
        "imap",
        "pop",
        "ftp",
        "ns1",
        "ns2",
        "dns",
        "static",
        "assets",
        "cdn",
        "media",
        "dashboard",
        "console",
        "help",
        "support",
        "docs",
        "blog",
        "status",
        "login",
        "logout",
        "signin",
        "signup",
        "auth",
        "account",
        "billing",
        "checkout",
        "cart",
        "webhooks",
        "internal",
        "root",
        "localhost",
        "staging",
        "dev",
        "test",
        "preview",
        "store",
        "stores",
        "shop",
        "storecart",
        "postmaster",
        "abuse",
        "hostmaster",
        "webmaster",
        "noreply",
        "security",
        "mx",
        "vpn",
        "git",
        "ssl",
        "web",
        "webmail",
        "autodiscover",
        "sandbox",
        "demo",
        "prod",
        "production",
        "payments",
        "pay",
        "portal",
        "about",
        "pricing",
        "terms",
        "privacy",
        "legal",
        "contact",
        "careers",
        "stripe",
        "firebase",
        "vercel",
    }
)


class InvalidSlug(ValueError):
    """The slug does not match the format rules (422)."""


class ReservedSlug(ValueError):
    """The slug is on the reserved list (422)."""


def normalize_slug(raw: str) -> str:
    """Return the canonical (lower-case) slug or raise ``InvalidSlug``/``ReservedSlug``."""
    if not raw.isascii():
        raise InvalidSlug
    slug = raw.lower()
    if not SLUG_MIN_LENGTH <= len(slug) <= SLUG_MAX_LENGTH:
        raise InvalidSlug
    if _SLUG_PATTERN.fullmatch(slug) is None:
        raise InvalidSlug
    if slug in RESERVED_SLUGS:
        raise ReservedSlug
    return slug
