"""Delete legacy e2e accounts from the Firebase project the backend credentials point at (KAN-131).

    uv run python -m commands.purge_legacy_e2e_accounts                              # dry run
    uv run python -m commands.purge_legacy_e2e_accounts --execute --project-id <id>  # real

Run by the owner against the Firebase project that holds the legacy accounts, with that project's
FIREBASE_ADMIN_PROJECT_ID / _CLIENT_EMAIL / _PRIVATE_KEY exported (see docs/developer/e2e-firebase-runbook.md).
The command reads exactly those three variables itself: it does not load the backend settings or any .env, and
it has no database. The service account's email must end with @<project>.iam.gserviceaccount.com.

A user is selected only when its email is e2e-shaped: the generated e2e pattern, the old default
test-user address, or (with the {e2e: true} claim) any e2e-prefixed @example.com address. A claim alone, or an
e2e-looking address on another domain, is never enough. The default is a dry run. --execute also needs
--project-id equal to the credential's project id. Each match gets its refresh tokens revoked, then is deleted.
Output is counts and masked emails only: no uids, full emails or credentials.
"""

import argparse
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import firebase_admin
from firebase_admin import auth, credentials, exceptions
from google.auth import exceptions as google_exceptions

PAGE_SIZE = 1000  # the Admin SDK maximum
# Every provider failure is flattened: the messages can contain emails or URLs.
PROVIDER_ERRORS = (
    exceptions.FirebaseError,
    ValueError,
    google_exceptions.GoogleAuthError,
)

# Mirrors E2E_EMAIL in nextjs-frontend/scripts/e2e-accounts.mjs.
E2E_EMAIL = re.compile(r"e2e-(user|admin|temp|seed)-[0-9a-f]{12}@example\.com")
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
        except PROVIDER_ERRORS:
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
        except PROVIDER_ERRORS:
            raise PurgeFailed() from None

    def delete_user(self, uid: str) -> None:
        try:
            auth.delete_user(uid, app=self._app)
        except auth.UserNotFoundError:
            raise AccountNotFound() from None
        except PROVIDER_ERRORS:
            raise PurgeFailed() from None


class CredentialsInvalid(Exception):
    """Missing or unusable FIREBASE_ADMIN_* variables. Carries no details on purpose."""


class GuardRefused(Exception):
    """A safety check failed; the message is fixed text, never input."""


def _firebase_gateway() -> AuthGateway:
    project = os.environ.get("FIREBASE_ADMIN_PROJECT_ID", "").strip()
    email = os.environ.get("FIREBASE_ADMIN_CLIENT_EMAIL", "").strip()
    key = os.environ.get("FIREBASE_ADMIN_PRIVATE_KEY", "")
    if not (project and email and key):
        raise CredentialsInvalid()
    if not email.lower().endswith(f"@{project}.iam.gserviceaccount.com"):
        raise GuardRefused(
            "Refusing: the service account does not belong to the credential's project."
        )
    try:
        certificate = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": project,
                "client_email": email,
                "private_key": key.replace("\\n", "\n"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        app = firebase_admin.initialize_app(
            certificate, {"projectId": project}, name="purge-legacy-e2e"
        )
    except Exception:  # noqa: BLE001 - parser errors can quote key material
        raise CredentialsInvalid() from None
    return FirebaseAuthGateway(app, project)


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


def main(
    argv: Sequence[str] | None = None, gateway_override: AuthGateway | None = None
) -> int:
    args = parse_args(argv)
    if args.execute and not args.project_id:
        return _fail("Refusing: --execute requires --project-id <id>.", 2)
    try:
        gateway = (
            gateway_override if gateway_override is not None else _firebase_gateway()
        )
    except GuardRefused as refusal:
        return _fail(str(refusal), 2)
    except CredentialsInvalid:
        return _fail("FAILED: Firebase Admin credentials are missing or invalid.", 1)
    except Exception:  # noqa: BLE001
        return _fail("FAILED: unexpected error while preparing credentials.", 1)
    if args.project_id and args.project_id != gateway.project_id:
        return _fail(
            "Refusing: --project-id does not match the credential's Firebase project "
            f"({gateway.project_id}).",
            2,
        )
    try:
        return _run(gateway, execute=args.execute)
    except Exception:  # noqa: BLE001 - raw tracebacks can carry emails or URLs
        return _fail("FAILED: unexpected error; details withheld. Re-run is safe.", 1)


def _run(gateway: AuthGateway, *, execute: bool) -> int:
    try:
        matches = find_legacy_e2e_accounts(gateway)
    except PurgeFailed:
        return _fail("FAILED: the scan failed; nothing was changed.", 1)
    mode = "EXECUTE" if execute else "DRY RUN"
    print(
        f"{mode} (project {gateway.project_id}): "
        f"{len(matches)} legacy e2e account(s) matched."
    )
    for account in matches:
        print(f"  {mask_email(account.email)}")
    if not execute:
        print("Nothing was changed. Re-run with --execute --project-id <id> to delete.")
        return 0
    deleted = done = 0
    try:
        for account in matches:
            deleted += _purge_one(gateway, account.uid)
            done += 1
    except PurgeFailed:
        return _fail(
            f"FAILED: the identity provider rejected a call after {done} of "
            f"{len(matches)} account(s); stopped, details withheld. Re-run is safe.",
            1,
        )
    print(f"deleted {deleted}, already gone {len(matches) - deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
