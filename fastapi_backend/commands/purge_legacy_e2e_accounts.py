"""Delete legacy e2e accounts from the Firebase project the backend credentials point at (KAN-131).

    uv run python -m commands.purge_legacy_e2e_accounts                              # dry run
    uv run python -m commands.purge_legacy_e2e_accounts --execute --project-id <id>  # real

Run by the owner, once, against the PRODUCTION Firebase project, with that project's FIREBASE_ADMIN_*
variables exported (see docs/developer/e2e-firebase-runbook.md). No database access.

A user is selected only when its email is e2e-shaped: the generated e2e pattern, the old default
test-user address, or (with the {e2e: true} claim) any e2e-prefixed @example.com address. A claim alone, or an
e2e-looking address on another domain, is never enough. The default is a dry run. --execute also needs
--project-id equal to the credential's project id. Each match gets its refresh tokens revoked, then is deleted.
Output is counts and masked emails only: no uids, full emails or credentials.
"""

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import firebase_admin
from firebase_admin import auth, exceptions

from app.core.firebase import IdentityProviderUnavailable, firebase_app

PAGE_SIZE = 1000  # the Admin SDK maximum

# Mirrors E2E_EMAIL in nextjs-frontend/scripts/e2e-accounts.mjs.
E2E_EMAIL = re.compile(r"e2e-(user|admin|temp)-[0-9a-f]{12}@example\.com")
# The default address of the removed scripts/create-test-user.mjs (git: 855cf8c^).
LEGACY_TEST_USER_EMAIL = "testuser@example.com"
# Looser variants, accepted only together with the {e2e: true} claim.
E2E_SHAPED_EMAIL = re.compile(r"e2e[-_.][a-z0-9._-]+@example\.com")


class AccountNotFound(Exception):
    """The account is already gone: counts as done."""


class PurgeFailed(Exception):
    """Any other provider failure. Carries no details on purpose."""


@dataclass(frozen=True)
class Account:
    uid: str
    email: str | None
    claims: Mapping[str, object]


@dataclass(frozen=True)
class AccountPage:
    accounts: tuple[Account, ...]
    next_token: str | None


class AuthGateway(Protocol):
    @property
    def project_id(self) -> str: ...
    def list_page(self, token: str | None) -> AccountPage: ...
    def revoke_refresh_tokens(self, uid: str) -> None: ...
    def delete_user(self, uid: str) -> None: ...


class FirebaseAuthGateway:
    """Admin SDK calls with every provider error flattened: messages can contain emails."""

    def __init__(self, app: firebase_admin.App, project_id: str) -> None:
        self._app = app
        self.project_id = project_id

    def list_page(self, token: str | None) -> AccountPage:
        try:
            page = auth.list_users(
                page_token=token, max_results=PAGE_SIZE, app=self._app
            )
        except (exceptions.FirebaseError, ValueError):
            raise PurgeFailed() from None
        accounts = tuple(
            Account(user.uid, user.email, dict(user.custom_claims or {}))
            for user in page.users
        )
        return AccountPage(accounts, page.next_page_token or None)

    def revoke_refresh_tokens(self, uid: str) -> None:
        try:
            auth.revoke_refresh_tokens(uid, app=self._app)
        except auth.UserNotFoundError:
            raise AccountNotFound() from None
        except (exceptions.FirebaseError, ValueError):
            raise PurgeFailed() from None

    def delete_user(self, uid: str) -> None:
        try:
            auth.delete_user(uid, app=self._app)
        except auth.UserNotFoundError:
            raise AccountNotFound() from None
        except (exceptions.FirebaseError, ValueError):
            raise PurgeFailed() from None


def _firebase_gateway() -> AuthGateway:
    app = firebase_app()
    project_id = app.project_id
    if not project_id:
        raise IdentityProviderUnavailable()
    return FirebaseAuthGateway(app, project_id)


def is_legacy_e2e_account(account: Account) -> bool:
    email = (account.email or "").lower()
    if E2E_EMAIL.fullmatch(email) or email == LEGACY_TEST_USER_EMAIL:
        return True
    return account.claims.get("e2e") is True and bool(E2E_SHAPED_EMAIL.fullmatch(email))


def mask_email(email: str | None) -> str:
    if email is None:
        return "(no email)"
    local, at, domain = email.partition("@")
    if not at or not local:
        return "***"
    return f"{local[:6]}***@{domain}"


def find_legacy_e2e_accounts(gateway: AuthGateway) -> list[Account]:
    """Scan every page before anything is changed, so deletions cannot disturb paging."""
    found: list[Account] = []
    token: str | None = None
    while True:
        page = gateway.list_page(token)
        found.extend(a for a in page.accounts if is_legacy_e2e_account(a))
        token = page.next_token
        if token is None:
            return found


def _purge_one(gateway: AuthGateway, uid: str) -> bool:
    """True when deleted now, False when it was already gone. Revoke first, then delete."""
    try:
        gateway.revoke_refresh_tokens(uid)
        gateway.delete_user(uid)
    except AccountNotFound:
        return False
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete legacy e2e accounts from the credential's Firebase project."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="really revoke and delete (default is a dry run)",
    )
    parser.add_argument(
        "--project-id",
        help="must equal the credential's project id; required with --execute",
    )
    return parser.parse_args(argv)


def _fail(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None, auth: AuthGateway | None = None) -> int:
    args = parse_args(argv)
    if args.execute and not args.project_id:
        return _fail("Refusing: --execute requires --project-id <id>.", 2)
    try:
        gateway = auth if auth is not None else _firebase_gateway()
    except IdentityProviderUnavailable:
        return _fail("FAILED: Firebase Admin credentials are not configured.", 1)
    if args.project_id and args.project_id != gateway.project_id:
        return _fail(
            "Refusing: --project-id does not match the credential's Firebase project "
            f"({gateway.project_id}).",
            2,
        )
    try:
        matches = find_legacy_e2e_accounts(gateway)
        mode = "EXECUTE" if args.execute else "DRY RUN"
        print(
            f"{mode} (project {gateway.project_id}): "
            f"{len(matches)} legacy e2e account(s) matched."
        )
        for account in matches:
            print(f"  {mask_email(account.email)}")
        if not args.execute:
            print(
                "Nothing was changed. Re-run with --execute --project-id <id> to delete."
            )
            return 0
        deleted = sum(_purge_one(gateway, account.uid) for account in matches)
    except PurgeFailed:
        return _fail(
            "FAILED: the identity provider rejected a call; stopped, details withheld.",
            1,
        )
    print(f"deleted {deleted}, already gone {len(matches) - deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
