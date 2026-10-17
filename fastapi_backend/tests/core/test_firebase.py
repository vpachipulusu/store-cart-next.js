import threading
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from app.core import firebase as module
from app.core.config import settings
from app.core.firebase import (
    AuthenticationFailed,
    FirebaseIdentityProvider,
    IdentityProviderUnavailable,
)


@pytest.fixture
def sdk_app(monkeypatch):
    app = object()
    monkeypatch.setattr(module, "firebase_app", lambda: app)
    return app


@pytest.mark.parametrize(
    "method,sdk_method",
    [
        ("verify_id_token", "verify_id_token"),
        ("verify_session_cookie", "verify_session_cookie"),
    ],
)
async def test_verification_checks_revocation_off_the_event_loop(
    monkeypatch, sdk_app, method, sdk_method
):
    event_thread = threading.get_ident()

    def verify(token, *, app, check_revoked, clock_skew_seconds):
        assert threading.get_ident() != event_thread
        assert token == "credential" and app is sdk_app and check_revoked is True
        assert clock_skew_seconds == settings.FIREBASE_CLOCK_SKEW_SECONDS
        return {"uid": "verified"}

    monkeypatch.setattr(module.auth, sdk_method, verify)
    assert await getattr(FirebaseIdentityProvider(), method)("credential") == {
        "uid": "verified"
    }


@pytest.mark.parametrize(
    "method,sdk_method",
    [
        ("verify_id_token", "verify_id_token"),
        ("verify_session_cookie", "verify_session_cookie"),
        ("create_session_cookie", "create_session_cookie"),
    ],
)
async def test_invalid_credentials_are_domain_errors_without_original_details(
    monkeypatch, sdk_app, method, sdk_method
):
    monkeypatch.setattr(
        module.auth,
        sdk_method,
        Mock(side_effect=module.auth.InvalidIdTokenError("private-token")),
    )
    args = ("token", 432000) if method == "create_session_cookie" else ("token",)
    with pytest.raises(AuthenticationFailed) as error:
        await getattr(FirebaseIdentityProvider(), method)(*args)
    assert str(error.value) == ""


async def test_minting_and_revocation_use_worker_threads(monkeypatch, sdk_app):
    event_thread = threading.get_ident()

    def mint(token, *, expires_in, app):
        assert threading.get_ident() != event_thread
        assert app is sdk_app and expires_in.total_seconds() == 432000
        return "session"

    def revoke(uid, *, app):
        assert (
            threading.get_ident() != event_thread and app is sdk_app and uid == "user"
        )

    monkeypatch.setattr(module.auth, "create_session_cookie", mint)
    monkeypatch.setattr(module.auth, "revoke_refresh_tokens", revoke)
    provider = FirebaseIdentityProvider()
    assert await provider.create_session_cookie("token", 432000) == "session"
    await provider.revoke_refresh_tokens("user")


@pytest.mark.parametrize(
    "method",
    [
        "verify_id_token",
        "verify_session_cookie",
        "create_session_cookie",
        "revoke_refresh_tokens",
        "delete_user",
    ],
)
async def test_sdk_outages_are_sanitized(monkeypatch, sdk_app, method):
    monkeypatch.setattr(
        module.auth,
        method,
        Mock(side_effect=module.exceptions.UnavailableError("secret")),
    )
    args = ("token", 432000) if method == "create_session_cookie" else ("token",)
    with pytest.raises(IdentityProviderUnavailable):
        await getattr(FirebaseIdentityProvider(), method)(*args)


def test_missing_credentials_fail_closed_without_sdk_initialization(monkeypatch):
    module.firebase_app.cache_clear()
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_PROJECT_ID", None)
    with pytest.raises(IdentityProviderUnavailable):
        module.firebase_app()
    module.firebase_app.cache_clear()


def test_initialization_is_named_and_idempotent(monkeypatch):
    module.firebase_app.cache_clear()
    app = object()
    get = Mock(side_effect=[ValueError(), app])
    certificate, initialize = Mock(return_value=object()), Mock(return_value=app)
    monkeypatch.setattr(module.firebase_admin, "get_app", get)
    monkeypatch.setattr(module.credentials, "Certificate", certificate)
    monkeypatch.setattr(module.firebase_admin, "initialize_app", initialize)
    assert module.firebase_app() is app
    assert module.firebase_app() is app
    initialize.assert_called_once()
    assert initialize.call_args.kwargs["name"] == "storecart-auth"
    module.firebase_app.cache_clear()


async def test_user_deletion_is_off_loop_and_idempotent_for_missing_users(
    monkeypatch, sdk_app
):
    event_thread = threading.get_ident()

    def delete(uid, *, app):
        assert threading.get_ident() != event_thread
        assert uid == "user" and app is sdk_app
        raise module.auth.UserNotFoundError("private")

    monkeypatch.setattr(module.auth, "delete_user", delete)
    await FirebaseIdentityProvider().delete_user("user")


async def test_disabling_a_user_is_off_loop_and_passes_the_flag(monkeypatch, sdk_app):
    event_thread = threading.get_ident()
    seen = []

    def update(uid, *, disabled, app):
        assert threading.get_ident() != event_thread and app is sdk_app
        seen.append((uid, disabled))

    monkeypatch.setattr(module.auth, "update_user", update)
    provider = FirebaseIdentityProvider()
    await provider.set_user_disabled("user", True)
    await provider.set_user_disabled("user", False)

    assert seen == [("user", True), ("user", False)]


async def test_disabling_an_unknown_user_raises_a_sanitized_not_found(
    monkeypatch, sdk_app
):
    monkeypatch.setattr(
        module.auth,
        "update_user",
        Mock(side_effect=module.auth.UserNotFoundError("private")),
    )

    with pytest.raises(module.IdentityUserNotFound):
        await FirebaseIdentityProvider().set_user_disabled("user", True)


async def test_disabling_a_user_sanitizes_sdk_outages(monkeypatch, sdk_app):
    monkeypatch.setattr(
        module.auth,
        "update_user",
        Mock(side_effect=module.exceptions.UnavailableError("secret")),
    )

    with pytest.raises(IdentityProviderUnavailable):
        await FirebaseIdentityProvider().set_user_disabled("user", True)


async def test_updating_a_password_is_off_loop_and_passes_the_password(
    monkeypatch, sdk_app
):
    event_thread = threading.get_ident()
    seen = []

    def update(uid, *, password, app):
        assert threading.get_ident() != event_thread and app is sdk_app
        seen.append((uid, password))

    monkeypatch.setattr(module.auth, "update_user", update)
    await FirebaseIdentityProvider().update_password("user", "new-password-1")

    assert seen == [("user", "new-password-1")]


async def test_updating_the_password_of_an_unknown_user_is_a_sanitized_not_found(
    monkeypatch, sdk_app
):
    monkeypatch.setattr(
        module.auth,
        "update_user",
        Mock(side_effect=module.auth.UserNotFoundError("private")),
    )

    with pytest.raises(module.IdentityUserNotFound):
        await FirebaseIdentityProvider().update_password("user", "new-password-1")


@pytest.mark.parametrize(
    "error",
    [
        ValueError("weak password secret"),
        module.exceptions.InvalidArgumentError("secret"),
    ],
)
async def test_a_rejected_password_is_its_own_sanitized_error(
    monkeypatch, sdk_app, error
):
    monkeypatch.setattr(module.auth, "update_user", Mock(side_effect=error))

    with pytest.raises(module.IdentityPasswordRejected) as caught:
        await FirebaseIdentityProvider().update_password("user", "new-password-1")

    assert "secret" not in str(caught.value)


async def test_password_update_outages_are_sanitized(monkeypatch, sdk_app):
    monkeypatch.setattr(
        module.auth,
        "update_user",
        Mock(side_effect=module.exceptions.UnavailableError("secret")),
    )

    with pytest.raises(IdentityProviderUnavailable) as caught:
        await FirebaseIdentityProvider().update_password("user", "new-password-1")

    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("skew", [0, 25, 60])
@pytest.mark.parametrize("sdk_method", ["verify_id_token", "verify_session_cookie"])
async def test_verification_passes_the_configured_clock_skew(
    monkeypatch, sdk_app, sdk_method, skew
):
    monkeypatch.setattr(settings, "FIREBASE_CLOCK_SKEW_SECONDS", skew)
    seen = {}

    def verify(token, **kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(module.auth, sdk_method, verify)
    await getattr(FirebaseIdentityProvider(), sdk_method)("credential")
    assert seen["clock_skew_seconds"] == skew
    assert seen["check_revoked"] is True


@pytest.mark.parametrize(
    "method,args",
    [
        ("verify_id_token", ("token",)),
        ("verify_session_cookie", ("token",)),
        ("create_session_cookie", ("token", 432000)),
        ("revoke_refresh_tokens", ("token",)),
        ("delete_user", ("token",)),
    ],
)
async def test_sdk_outages_are_logged_with_operation_and_code_but_no_details(
    monkeypatch, sdk_app, caplog, method, args
):
    monkeypatch.setattr(
        module.auth,
        method,
        Mock(side_effect=module.exceptions.PermissionDeniedError("private-token")),
    )
    with (
        caplog.at_level("ERROR", logger="storecart.firebase"),
        pytest.raises(IdentityProviderUnavailable),
    ):
        await getattr(FirebaseIdentityProvider(), method)(*args)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert method in text
    assert "PermissionDeniedError" in text and "PERMISSION_DENIED" in text
    assert "private-token" not in text


@pytest.mark.parametrize("method", ["set_user_disabled", "update_password"])
async def test_user_update_outages_are_logged_without_details(
    monkeypatch, sdk_app, caplog, method
):
    monkeypatch.setattr(
        module.auth,
        "update_user",
        Mock(side_effect=module.exceptions.UnavailableError("private-token")),
    )
    args = ("uid", True) if method == "set_user_disabled" else ("uid", "pw")
    with (
        caplog.at_level("ERROR", logger="storecart.firebase"),
        pytest.raises(IdentityProviderUnavailable),
    ):
        await getattr(FirebaseIdentityProvider(), method)(*args)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert method in text and "UNAVAILABLE" in text and "private-token" not in text


async def test_a_local_value_error_is_logged_with_its_class_and_no_code(
    monkeypatch, sdk_app, caplog
):
    monkeypatch.setattr(
        module.auth, "verify_id_token", Mock(side_effect=ValueError("private-key"))
    )
    with (
        caplog.at_level("ERROR", logger="storecart.firebase"),
        pytest.raises(IdentityProviderUnavailable),
    ):
        await FirebaseIdentityProvider().verify_id_token("token")
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "ValueError" in text and "code=None" in text and "private-key" not in text


def test_missing_credentials_log_the_variable_names_only(monkeypatch, caplog):
    module.firebase_app.cache_clear()
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_PROJECT_ID", None)
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_CLIENT_EMAIL", "sa@example.test")
    monkeypatch.setattr(
        settings, "FIREBASE_ADMIN_PRIVATE_KEY", SecretStr("placeholder")
    )
    try:
        with (
            caplog.at_level("ERROR", logger="storecart.firebase"),
            pytest.raises(IdentityProviderUnavailable),
        ):
            module.firebase_app()
    finally:
        module.firebase_app.cache_clear()
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "FIREBASE_ADMIN_PROJECT_ID" in text
    assert "FIREBASE_ADMIN_CLIENT_EMAIL" not in text
    assert "FIREBASE_ADMIN_PRIVATE_KEY" not in text
    assert "placeholder" not in text and "sa@example.test" not in text
