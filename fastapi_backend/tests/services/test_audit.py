import json
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from app.core.permissions import AdminContext
from app.services.audit import REDACTED, AuditService, sanitize

ADMIN = AdminContext("admin-1", "admin", frozenset({"users.update"}))


class RecordingWriter:
    def __init__(self):
        self.rows = []

    async def add(self, **row):
        self.rows.append(row)


async def record(writer=None, **overrides):
    writer = writer or RecordingWriter()
    kwargs = {"action": "admin.users.update", "resource": "users"} | overrides
    await AuditService(writer).record_admin_action(ADMIN, **kwargs)
    return writer.rows[0]


async def test_entry_records_actor_target_and_origin():
    row = await record(
        resource_id="user-9",
        organization_id="org-1",
        ip_address="203.0.113.7",
        user_agent="pytest",
        request_id="req-1",
    )
    assert row["user_id"] == "admin-1"
    assert (row["action"], row["resource"], row["resource_id"]) == (
        "admin.users.update",
        "users",
        "user-9",
    )
    assert row["organization_id"] == "org-1"
    assert (row["ip_address"], row["user_agent"]) == ("203.0.113.7", "pytest")
    assert row["metadata"] == {"actor_role": "admin", "request_id": "req-1"}


async def test_before_after_and_details_are_stored():
    row = await record(
        before={"role": "viewer"}, after={"role": "admin"}, details={"reason": "ops"}
    )
    assert row["metadata"]["before"] == {"role": "viewer"}
    assert row["metadata"]["after"] == {"role": "admin"}
    assert row["metadata"]["details"] == {"reason": "ops"}


async def test_secret_looking_fields_are_never_stored():
    payload = {
        "password": "hunter2",
        "idToken": "eyJ.raw.token",
        "two_factor_secret": "JBSWY3DP",
        "totp_code": "123456",
        "Authorization": "Bearer abc",
        "session-cookie": "s",
        "api_key": "k",
        "backup_codes": ["a", "b"],
        "email": "ada@example.com",
        "phone_number": "+15550100",
        "nested": {"internal_key": "x", "role": "admin"},
        "items": [{"refresh_token": "r", "name": "ok"}],
    }
    row = await record(before=payload, after=payload, details=payload)
    blob = json.dumps(row["metadata"])
    for leaked in (
        "hunter2",
        "eyJ.raw.token",
        "JBSWY3DP",
        "123456",
        "Bearer abc",
        "ada@example.com",
        "+15550100",
    ):
        assert leaked not in blob
    after = row["metadata"]["after"]
    assert after["nested"] == {"internal_key": REDACTED, "role": "admin"}
    assert after["items"] == [{"refresh_token": REDACTED, "name": "ok"}]


def test_sanitize_never_renders_unknown_objects():
    cleaned = sanitize({"value": SecretStr("hunter2"), "obj": object()})
    assert cleaned == {"value": "<SecretStr>", "obj": "<object>"}


def test_sanitize_serialises_dates_and_bounds_size():
    when = datetime(2026, 1, 1, tzinfo=UTC)
    deep: dict = {}
    node = deep
    for _ in range(12):
        node["next"] = {}
        node = node["next"]
    cleaned = sanitize(
        {"at": when, "long": "x" * 5000, "many": list(range(500)), "deep": deep}
    )
    assert cleaned["at"] == when.isoformat()
    assert len(cleaned["long"]) == 500
    assert len(cleaned["many"]) == 50
    assert "[TRUNCATED]" in json.dumps(cleaned["deep"])
    json.dumps(cleaned)


async def test_user_agent_is_truncated():
    row = await record(user_agent="u" * 2000)
    assert len(row["user_agent"]) == 512


@pytest.mark.parametrize("action", ["", "update", "Admin.Users", "admin..x", "a b.c"])
async def test_invalid_action_is_rejected_and_nothing_is_written(action):
    writer = RecordingWriter()
    with pytest.raises(ValueError):
        await record(writer, action=action)
    assert writer.rows == []


@pytest.mark.parametrize("resource", ["", "Users", "users;drop", "x"])
async def test_invalid_resource_is_rejected(resource):
    with pytest.raises(ValueError):
        await record(resource=resource)
