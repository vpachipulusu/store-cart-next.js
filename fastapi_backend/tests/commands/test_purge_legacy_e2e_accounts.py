"""KAN-131: the guarded purge of legacy e2e accounts. A local fake stands in for Firebase Auth."""

from dataclasses import dataclass, field

import pytest

from commands import purge_legacy_e2e_accounts as purge
from commands.purge_legacy_e2e_accounts import (
    Account,
    AccountNotFound,
    AccountPage,
    PurgeFailed,
    find_legacy_e2e_accounts,
    is_legacy_e2e_account,
    main,
    mask_email,
)

PROJECT = "storecart-prod"
SECRET_UID = "uid-secret-1234567890"
E2E_USER = "e2e-user-0123456789ab@example.com"
E2E_ADMIN = "e2e-admin-0123456789ab@example.com"
E2E_TEMP = "e2e-temp-0123456789ab@example.com"
LEGACY_DEFAULT = "testuser@example.com"
REAL = "ada.lovelace@gmail.com"


@dataclass
class FakeAuth:
    """Pages of accounts of page_size; records every mutating call in order."""

    accounts: list[Account]
    project_id: str = PROJECT
    page_size: int = 2
    calls: list[tuple[str, str]] = field(default_factory=list)
    missing: set[str] = field(default_factory=set)
    fail_on: tuple[str, str] | None = None

    def list_page(self, token: str | None) -> AccountPage:
        start = int(token) if token else 0
        end = start + self.page_size
        more = str(end) if end < len(self.accounts) else None
        return AccountPage(tuple(self.accounts[start:end]), more)

    def _act(self, action: str, uid: str) -> None:
        self.calls.append((action, uid))
        if self.fail_on == (action, uid):
            raise PurgeFailed(f"boom {uid} {E2E_USER}")  # a leak if ever printed
        if uid in self.missing:
            raise AccountNotFound()

    def revoke_refresh_tokens(self, uid: str) -> None:
        self._act("revoke", uid)

    def delete_user(self, uid: str) -> None:
        self._act("delete", uid)


def acct(
    uid: str, email: str | None, claims: dict[str, object] | None = None
) -> Account:
    return Account(uid=uid, email=email, claims=claims or {})


def world() -> list[Account]:
    return [
        acct("u1", E2E_USER, {"e2e": True}),
        acct("u2", REAL),
        acct("u3", E2E_ADMIN),
        acct(SECRET_UID, "bob@gmail.com", {"e2e": True}),  # claim alone
        acct("u5", "e2e-user-feedfacecafe@gmail.com"),  # e2e-looking, wrong domain
        acct("u6", LEGACY_DEFAULT),
        acct("u7", E2E_TEMP),
        acct("u8", None, {"e2e": True}),  # no email at all
    ]


def test_selects_only_e2e_shaped_emails_never_claim_or_domain_alone():
    found = find_legacy_e2e_accounts(FakeAuth(world()))

    assert [a.uid for a in found] == ["u1", "u3", "u6", "u7"]


def test_real_looking_users_are_never_selected():
    for email in (REAL, "e2e-user-feedfacecafe@gmail.com", "e2e@example.org", None):
        assert not is_legacy_e2e_account(acct("x", email))
        assert not is_legacy_e2e_account(acct("x", email, {"e2e": True}))


def test_claim_plus_e2e_shaped_variant_email_is_selected():
    variant = "e2e-smoke.1@example.com"
    assert not is_legacy_e2e_account(acct("x", variant))
    assert is_legacy_e2e_account(acct("x", variant, {"e2e": True}))
    assert not is_legacy_e2e_account(acct("x", variant, {"e2e": False}))


def test_paging_visits_every_page():
    many = [acct(f"u{i}", f"e2e-temp-{i:012x}@example.com") for i in range(7)]

    assert len(find_legacy_e2e_accounts(FakeAuth(many, page_size=3))) == 7


def test_dry_run_deletes_nothing_and_prints_counts_and_masks(capsys):
    fake = FakeAuth(world())

    code = main([], gateway_override=fake)

    out = capsys.readouterr().out
    assert code == 0
    assert fake.calls == []
    assert "DRY RUN" in out
    assert "4 legacy e2e account(s)" in out
    assert "e2e-us***@example.com" in out
    assert E2E_USER not in out
    assert LEGACY_DEFAULT not in out


def test_execute_requires_project_id(capsys):
    fake = FakeAuth(world())

    assert main(["--execute"], gateway_override=fake) == 2

    assert fake.calls == []
    assert "--project-id" in capsys.readouterr().err


def test_project_id_mismatch_is_refused(capsys):
    fake = FakeAuth(world())

    code = main(["--execute", "--project-id", "storecart-test"], gateway_override=fake)

    assert code == 2
    assert fake.calls == []
    assert "does not match" in capsys.readouterr().err


def test_project_id_mismatch_is_refused_even_in_dry_run():
    assert main(["--project-id", "other"], gateway_override=FakeAuth(world())) == 2


def test_execute_revokes_before_deleting_each_account(capsys):
    fake = FakeAuth(world())

    code = main(["--execute", "--project-id", PROJECT], gateway_override=fake)

    assert code == 0
    assert fake.calls == [
        ("revoke", "u1"),
        ("delete", "u1"),
        ("revoke", "u3"),
        ("delete", "u3"),
        ("revoke", "u6"),
        ("delete", "u6"),
        ("revoke", "u7"),
        ("delete", "u7"),
    ]
    assert "deleted 4" in capsys.readouterr().out


def test_not_found_counts_as_already_done(capsys):
    fake = FakeAuth(world(), missing={"u3"})

    code = main(["--execute", "--project-id", PROJECT], gateway_override=fake)

    out = capsys.readouterr().out
    assert code == 0
    assert "already gone 1" in out
    assert ("delete", "u7") in fake.calls


def test_rerun_after_purge_finds_nothing_and_is_a_no_op(capsys):
    fake = FakeAuth([acct("u2", REAL)])

    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 0

    assert fake.calls == []
    assert "0 legacy e2e account(s)" in capsys.readouterr().out


def test_other_errors_fail_without_printing_any_data(capsys):
    fake = FakeAuth(world(), fail_on=("delete", "u3"))

    code = main(["--execute", "--project-id", PROJECT], gateway_override=fake)

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code == 1
    assert "FAILED" in text
    assert "boom" not in text and E2E_USER not in text and "u3" not in text
    assert ("revoke", "u6") not in fake.calls  # stopped at the first failure


def test_output_never_contains_uids_full_emails_or_credentials(capsys):
    fake = FakeAuth(world())
    main([], gateway_override=fake)
    main(["--execute", "--project-id", PROJECT], gateway_override=fake)

    captured = capsys.readouterr()
    text = captured.out + captured.err
    for secret in (
        SECRET_UID,
        "u1",
        E2E_USER,
        E2E_ADMIN,
        E2E_TEMP,
        LEGACY_DEFAULT,
        REAL,
    ):
        assert secret not in text
    for marker in ("private_key", "token", "password"):
        assert marker not in text.lower()


def test_mask_email_keeps_a_short_prefix_and_the_domain():
    assert mask_email(E2E_USER) == "e2e-us***@example.com"
    assert mask_email("ab@example.com") == "ab***@example.com"
    assert mask_email(None) == "(no email)"
    assert mask_email("not-an-email") == "***"


def test_missing_credentials_fail_cleanly(monkeypatch, capsys):
    def unavailable() -> purge.AuthGateway:
        raise purge.IdentityProviderUnavailable()

    monkeypatch.setattr(purge, "_firebase_gateway", unavailable)

    assert main([]) == 1
    assert "credentials" in capsys.readouterr().err.lower()


class _Page:
    def __init__(self, users: list[object], next_token: str | None) -> None:
        self.users = users
        self.next_page_token = next_token


class _User:
    def __init__(self, uid: str, email: str | None, claims: dict[str, object] | None):
        self.uid = uid
        self.email = email
        self.custom_claims = claims


def test_firebase_gateway_maps_sdk_calls_and_errors(monkeypatch):
    seen: list[tuple[str, object]] = []

    def list_users(page_token=None, max_results=1000, app=None):
        seen.append(("list", page_token))
        return _Page(
            [_User("u1", E2E_USER, {"e2e": True}), _User("u2", None, None)], "t2"
        )

    def revoke(uid, app=None):
        seen.append(("revoke", uid))

    def delete(uid, app=None):
        seen.append(("delete", uid))
        raise purge.auth.UserNotFoundError("gone", None, None)

    monkeypatch.setattr(purge.auth, "list_users", list_users)
    monkeypatch.setattr(purge.auth, "revoke_refresh_tokens", revoke)
    monkeypatch.setattr(purge.auth, "delete_user", delete)
    gateway = purge.FirebaseAuthGateway(app=object(), project_id=PROJECT)  # type: ignore[arg-type]

    page = gateway.list_page(None)
    gateway.revoke_refresh_tokens("u1")
    with pytest.raises(AccountNotFound):
        gateway.delete_user("u1")

    assert page.next_token == "t2"
    assert page.accounts[0] == Account("u1", E2E_USER, {"e2e": True})
    assert page.accounts[1] == Account("u2", None, {})
    assert seen == [("list", None), ("revoke", "u1"), ("delete", "u1")]


def test_firebase_gateway_hides_sdk_error_details(monkeypatch):
    def boom(*_a, **_k):
        raise purge.exceptions.UnknownError(f"secret {E2E_USER}")

    monkeypatch.setattr(purge.auth, "revoke_refresh_tokens", boom)
    gateway = purge.FirebaseAuthGateway(app=object(), project_id=PROJECT)  # type: ignore[arg-type]

    with pytest.raises(PurgeFailed) as caught:
        gateway.revoke_refresh_tokens("u1")

    assert E2E_USER not in str(caught.value)
    assert caught.value.__cause__ is None


# --- additions from the TDD review -------------------------------------------------


def test_revoke_failure_stops_before_any_delete(capsys):
    fake = FakeAuth(world(), fail_on=("revoke", "u3"))

    code = main(["--execute", "--project-id", PROJECT], gateway_override=fake)

    assert code == 1
    assert ("delete", "u3") not in fake.calls
    assert "u3" not in capsys.readouterr().err


def test_delete_not_found_after_revoke_counts_as_already_gone(capsys):
    class DeleteRace(FakeAuth):
        def delete_user(self, uid: str) -> None:
            self.calls.append(("delete", uid))
            if uid == "u3":
                raise AccountNotFound()

    fake = DeleteRace(world())

    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 0

    assert "deleted 3, already gone 1" in capsys.readouterr().out


def test_listing_failure_changes_nothing(capsys):
    class ListFails(FakeAuth):
        def list_page(self, token: str | None) -> AccountPage:
            if token:
                raise PurgeFailed()
            return super().list_page(token)

    fake = ListFails(world())

    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 1
    assert fake.calls == []


def test_empty_project_id_is_refused_with_execute():
    fake = FakeAuth(world())
    assert main(["--execute", "--project-id", ""], gateway_override=fake) == 2
    assert fake.calls == []


def test_project_id_comparison_is_case_sensitive():
    fake = FakeAuth(world())
    assert (
        main(["--execute", "--project-id", PROJECT.upper()], gateway_override=fake) == 2
    )
    assert fake.calls == []


def test_dry_run_with_matching_project_id_still_changes_nothing(capsys):
    fake = FakeAuth(world())

    assert main(["--project-id", PROJECT], gateway_override=fake) == 0

    assert fake.calls == []
    assert "Nothing was changed" in capsys.readouterr().out


def test_selection_edge_cases():
    shapes = {
        "E2E-USER-0123456789AB@EXAMPLE.COM": True,
        "TESTUSER@example.com": True,
        "e2e-user-0123456789ab@example.com.evil.io": False,
        "xe2e-user-0123456789ab@example.com": False,
        "e2e-user-0123456789a@example.com": False,
        "e2e-user-0123456789abc@example.com": False,
        "e2e-user-0123456789zz@example.com": False,
        "testuser2@example.com": False,
        " e2e-user-0123456789ab@example.com": False,
    }
    for email, expected in shapes.items():
        assert is_legacy_e2e_account(acct("x", email)) is expected, email


def test_only_the_boolean_true_claim_counts():
    variant = "e2e-smoke.1@example.com"
    for claim in ("true", 1, "yes", None):
        assert not is_legacy_e2e_account(acct("x", variant, {"e2e": claim}))
    assert not is_legacy_e2e_account(
        acct("x", "e2e-smoke.1@example.org", {"e2e": True})
    )


def test_second_execute_run_makes_no_calls(capsys):
    class Stateful(FakeAuth):
        def delete_user(self, uid: str) -> None:
            super().delete_user(uid)
            self.accounts = [a for a in self.accounts if a.uid != uid]

    fake = Stateful(world())
    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 0
    first = len(fake.calls)

    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 0

    assert len(fake.calls) == first
    assert [a.uid for a in fake.accounts if is_legacy_e2e_account(a)] == []


def test_mask_email_edge_cases():
    assert mask_email("") == "***"
    assert mask_email("@example.com") == "***"
    assert mask_email("abcdef@example.com") == "abcdef***@example.com"


def test_missing_credentials_print_nothing_to_stdout(monkeypatch, capsys):
    def unavailable() -> purge.AuthGateway:
        raise purge.IdentityProviderUnavailable()

    monkeypatch.setattr(purge, "_firebase_gateway", unavailable)

    assert main([]) == 1
    assert capsys.readouterr().out == ""


class _FakeApp:
    def __init__(self, project_id: str | None) -> None:
        self.project_id = project_id


def test_firebase_gateway_factory_uses_the_apps_project_id(monkeypatch):
    monkeypatch.setattr(purge, "firebase_app", lambda: _FakeApp(PROJECT))

    assert purge._firebase_gateway().project_id == PROJECT


def test_firebase_gateway_factory_refuses_an_app_without_project_id(monkeypatch):
    monkeypatch.setattr(purge, "firebase_app", lambda: _FakeApp(None))

    with pytest.raises(purge.IdentityProviderUnavailable):
        purge._firebase_gateway()


def test_firebase_gateway_list_arguments_and_empty_last_token(monkeypatch):
    seen: dict[str, object] = {}
    app = object()

    def list_users(page_token=None, max_results=None, app=None):
        seen.update(token=page_token, max=max_results, app=app)
        return _Page([], "")

    monkeypatch.setattr(purge.auth, "list_users", list_users)
    gateway = purge.FirebaseAuthGateway(app=app, project_id=PROJECT)  # type: ignore[arg-type]

    page = gateway.list_page("tok")

    assert seen == {"token": "tok", "max": purge.PAGE_SIZE, "app": app}
    assert page.next_token is None


@pytest.mark.parametrize(
    "method", ["list_page", "revoke_refresh_tokens", "delete_user"]
)
@pytest.mark.parametrize("error", [purge.exceptions.UnknownError("x"), ValueError("x")])
def test_firebase_gateway_flattens_sdk_errors(monkeypatch, method, error):
    def boom(*_a, **_k):
        raise error

    for name in ("list_users", "revoke_refresh_tokens", "delete_user"):
        monkeypatch.setattr(purge.auth, name, boom)
    gateway = purge.FirebaseAuthGateway(app=object(), project_id=PROJECT)  # type: ignore[arg-type]
    call = getattr(gateway, method)

    with pytest.raises(PurgeFailed) as caught:
        call(None) if method == "list_page" else call("u1")

    assert caught.value.__cause__ is None


def test_firebase_gateway_revoke_not_found_is_already_gone(monkeypatch):
    def gone(*_a, **_k):
        raise purge.auth.UserNotFoundError("gone", None, None)

    monkeypatch.setattr(purge.auth, "revoke_refresh_tokens", gone)
    gateway = purge.FirebaseAuthGateway(app=object(), project_id=PROJECT)  # type: ignore[arg-type]

    with pytest.raises(AccountNotFound):
        gateway.revoke_refresh_tokens("u1")


def test_failure_reports_progress_without_details(capsys):
    fake = FakeAuth(world(), fail_on=("delete", "u6"))

    assert main(["--execute", "--project-id", PROJECT], gateway_override=fake) == 1

    assert "after 2 of 4 account(s)" in capsys.readouterr().err


def test_google_auth_errors_are_flattened(monkeypatch):
    def boom(*_a, **_k):
        raise purge.google_exceptions.TransportError("https://leak.example/" + E2E_USER)

    monkeypatch.setattr(purge.auth, "list_users", boom)
    gateway = purge.FirebaseAuthGateway(app=object(), project_id=PROJECT)  # type: ignore[arg-type]

    with pytest.raises(PurgeFailed):
        gateway.list_page(None)


def test_malformed_credentials_fail_cleanly(monkeypatch, capsys):
    def bad_key() -> purge.AuthGateway:
        raise ValueError("bad private key material")

    monkeypatch.setattr(purge, "_firebase_gateway", bad_key)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "bad private key" not in captured.out + captured.err
