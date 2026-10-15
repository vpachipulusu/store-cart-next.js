import logging

import pytest
from pydantic import SecretStr

from app.core.store_crypto import StoreSecretCodec, StoreSecretUnavailable, generate_key
from app.models.platform.store import Store
from app.services import store_secrets

DSN = "postgresql://user:hunter2@db.example.invalid/store"


def make_store(store_id="s1") -> Store:
    return Store(id=store_id, name="n", slug="n")


def test_set_and_reveal_round_trip_without_plaintext_in_repr():
    codec = StoreSecretCodec(generate_key())
    store = make_store()
    store_secrets.set_connection_string(store, DSN, codec)
    assert "hunter2" not in (store.connection_string_encrypted or "")
    assert "hunter2" not in repr(store)
    assert store_secrets.reveal_connection_string(store, codec) == DSN


def test_reveal_none_when_unset_and_empty_rejected():
    codec = StoreSecretCodec(generate_key())
    assert store_secrets.reveal_connection_string(make_store(), codec) is None
    with pytest.raises(ValueError):
        store_secrets.set_connection_string(make_store(), "  ", codec)


def test_failure_logs_store_id_only(caplog):
    codec = StoreSecretCodec(generate_key())
    store = make_store()
    store_secrets.set_connection_string(store, DSN, codec)
    with caplog.at_level(logging.DEBUG), pytest.raises(StoreSecretUnavailable):
        store_secrets.reveal_connection_string(store, StoreSecretCodec(generate_key()))
    assert "hunter2" not in caplog.text
    assert store.connection_string_encrypted not in caplog.text
    assert any(r.store_id == "s1" for r in caplog.records)


def test_rotate_reencrypts_only_when_needed():
    old, new = generate_key(), generate_key()
    store = make_store()
    store_secrets.set_connection_string(store, DSN, StoreSecretCodec(old))
    codec = StoreSecretCodec(new, [old])
    assert store_secrets.rotate_connection_string(store, codec)
    assert not store_secrets.rotate_connection_string(store, codec)
    assert store_secrets.reveal_connection_string(store, codec) == DSN
    assert not store_secrets.rotate_connection_string(make_store(), codec)


def test_rotate_fails_safely_on_undecryptable_value(caplog):
    old, new = generate_key(), generate_key()
    store = make_store()
    store.connection_string_encrypted = StoreSecretCodec(old).encrypt(DSN, "other")
    with caplog.at_level(logging.DEBUG), pytest.raises(StoreSecretUnavailable):
        store_secrets.rotate_connection_string(store, StoreSecretCodec(new, [old]))
    assert "hunter2" not in caplog.text


def test_get_codec_uses_settings(monkeypatch):
    store_secrets.get_codec.cache_clear()
    monkeypatch.setattr(store_secrets.settings, "STORE_DB_ENCRYPTION_KEY", None)
    with pytest.raises(StoreSecretUnavailable):
        store_secrets.get_codec()
    store_secrets.get_codec.cache_clear()
    monkeypatch.setattr(
        store_secrets.settings, "STORE_DB_ENCRYPTION_KEY", SecretStr(generate_key())
    )
    assert store_secrets.get_codec() is store_secrets.get_codec()
    store_secrets.get_codec.cache_clear()
