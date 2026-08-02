"""
tests/test_api_key_auth.py
==========================
Unit tests for cognia.auth.api_key_manager.APIKeyManager.
Uses a temporary in-memory SQLite DB via a temp file so db_pool
can address it by path.
"""

import os
import tempfile
import pytest

from cognia.auth.api_key_manager import APIKeyManager


@pytest.fixture()
def mgr(tmp_path):
    """Fresh APIKeyManager backed by a temp SQLite file per test."""
    db_file = str(tmp_path / "test_api_keys.db")
    # Close any previously opened pool for this path (isolation between tests)
    from storage.db_pool import close_pool
    close_pool(db_file)
    manager = APIKeyManager(db_path=db_file)
    yield manager
    close_pool(db_file)


class TestCreateKey:
    def test_returns_cognia_sk_prefix(self, mgr):
        key = mgr.create_key("user1")
        assert key.startswith("cognia_sk_"), f"Expected prefix cognia_sk_, got: {key}"

    def test_key_is_string(self, mgr):
        key = mgr.create_key("user1", label="test label")
        assert isinstance(key, str)
        assert len(key) > len("cognia_sk_")


class TestValidateKey:
    def test_validate_correct_key_returns_user_id(self, mgr):
        key = mgr.create_key("alice")
        result = mgr.validate_key(key)
        assert result == "alice"

    def test_validate_wrong_key_returns_none(self, mgr):
        result = mgr.validate_key("cognia_sk_totally_fake_key_12345678901234")
        assert result is None

    def test_validate_empty_string_returns_none(self, mgr):
        assert mgr.validate_key("") is None

    def test_validate_wrong_prefix_returns_none(self, mgr):
        assert mgr.validate_key("sk_notcognia_abc123") is None


class TestValidateKeyFull:
    """Regresion: el middleware usa validate_key_full (una sola consulta)."""

    def test_valid_key_returns_user_and_tier(self, mgr):
        key = mgr.create_key("alice", tier="pro")
        info = mgr.validate_key_full(key)
        assert info == {"user_id": "alice", "tier": "pro"}

    def test_default_tier_is_free(self, mgr):
        key = mgr.create_key("bob")
        info = mgr.validate_key_full(key)
        assert info == {"user_id": "bob", "tier": "free"}

    def test_invalid_key_returns_none(self, mgr):
        assert mgr.validate_key_full("cognia_sk_totally_fake_key_1234567890") is None

    def test_wrong_prefix_returns_none(self, mgr):
        assert mgr.validate_key_full("sk_notcognia_abc123") is None

    def test_revoked_key_returns_none(self, mgr):
        key = mgr.create_key("carol")
        key_id = mgr.list_keys("carol")[0]["id"]
        assert mgr.validate_key_full(key) is not None
        mgr.revoke_key(key_id)
        assert mgr.validate_key_full(key) is None


class TestGetKeyUser:
    def test_returns_owner_user_id(self, mgr):
        mgr.create_key("dave")
        key_id = mgr.list_keys("dave")[0]["id"]
        assert mgr.get_key_user(key_id) == "dave"

    def test_returns_owner_even_if_revoked(self, mgr):
        mgr.create_key("erin")
        key_id = mgr.list_keys("erin")[0]["id"]
        mgr.revoke_key(key_id)
        assert mgr.get_key_user(key_id) == "erin"

    def test_unknown_id_returns_none(self, mgr):
        assert mgr.get_key_user(999999) is None


class TestRevokeKey:
    def test_revoke_makes_key_invalid(self, mgr):
        key = mgr.create_key("bob")
        keys = mgr.list_keys("bob")
        key_id = keys[0]["id"]

        assert mgr.validate_key(key) == "bob"
        mgr.revoke_key(key_id)
        assert mgr.validate_key(key) is None

    def test_revoke_nonexistent_returns_false(self, mgr):
        result = mgr.revoke_key(999999)
        assert result is False


class TestListKeys:
    def test_list_includes_created_key(self, mgr):
        mgr.create_key("carol", label="my integration")
        keys = mgr.list_keys("carol")
        assert len(keys) == 1
        entry = keys[0]
        assert entry["user_id"] == "carol"
        assert entry["label"] == "my integration"
        assert entry["active"] is True
        assert "id" in entry
        assert "created_at" in entry

    def test_list_empty_for_unknown_user(self, mgr):
        assert mgr.list_keys("nobody") == []

    def test_list_shows_multiple_keys(self, mgr):
        mgr.create_key("dave", label="key1")
        mgr.create_key("dave", label="key2")
        keys = mgr.list_keys("dave")
        assert len(keys) == 2
        labels = {k["label"] for k in keys}
        assert labels == {"key1", "key2"}
