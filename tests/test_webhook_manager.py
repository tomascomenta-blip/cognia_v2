"""
tests/test_webhook_manager.py
==============================
Unit tests for cognia/webhooks/webhook_manager.py.
All HTTP calls are mocked — no real network required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on sys.path so storage/ is importable
import sys
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cognia.webhooks.webhook_manager import WebhookManager, SUPPORTED_EVENTS


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def wm(tmp_path):
    """WebhookManager backed by a temp SQLite file."""
    db = str(tmp_path / "test_webhooks.db")
    return WebhookManager(db_path=db)


# ── Tests ─────────────────────────────────────────────────────────────

class TestRegister:
    def test_register_valid_returns_dict_with_id(self, wm):
        result = wm.register("http://example.com/hook", ["goal.completed"])
        assert isinstance(result, dict)
        assert "id" in result
        assert result["id"] is not None
        assert result["url"] == "http://example.com/hook"
        assert "goal.completed" in result["events"]
        assert result["active"] is True

    def test_register_invalid_event_raises_value_error(self, wm):
        with pytest.raises(ValueError, match="Unsupported events"):
            wm.register("http://example.com/hook", ["nonexistent.event"])

    def test_register_empty_events_raises_value_error(self, wm):
        with pytest.raises(ValueError, match="must not be empty"):
            wm.register("http://example.com/hook", [])

    def test_register_invalid_url_raises_value_error(self, wm):
        with pytest.raises(ValueError, match="Invalid webhook URL"):
            wm.register("not-a-url", ["goal.completed"])

    def test_register_ftp_url_raises_value_error(self, wm):
        with pytest.raises(ValueError, match="Invalid webhook URL"):
            wm.register("ftp://example.com/hook", ["goal.completed"])

    def test_register_multiple_events(self, wm):
        result = wm.register(
            "https://example.com/hook",
            ["goal.completed", "goal.created"],
        )
        assert set(result["events"]) == {"goal.completed", "goal.created"}


class TestListWebhooks:
    def test_list_webhooks_includes_registered(self, wm):
        wm.register("http://example.com/a", ["goal.created"])
        wm.register("http://example.com/b", ["message.received"])
        hooks = wm.list_webhooks()
        urls = [h["url"] for h in hooks]
        assert "http://example.com/a" in urls
        assert "http://example.com/b" in urls

    def test_list_webhooks_excludes_unregistered(self, wm):
        h = wm.register("http://example.com/del", ["goal.created"])
        wm.unregister(h["id"])
        hooks = wm.list_webhooks()
        assert all(x["id"] != h["id"] for x in hooks)


class TestUnregister:
    def test_unregister_returns_true_when_found(self, wm):
        h = wm.register("http://example.com/hook", ["goal.completed"])
        assert wm.unregister(h["id"]) is True

    def test_unregister_returns_false_when_not_found(self, wm):
        assert wm.unregister(99999) is False


class TestSendWebhook:
    def test_send_returns_true_on_200(self, wm):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = wm._send_webhook(
                "http://example.com/hook",
                {"event": "goal.completed", "data": {}, "ts": 1.0, "cognia_version": "3.0"},
                "",
                1,
                "goal.completed",
            )
        assert result is True

    def test_send_returns_false_on_500(self, wm):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="http://example.com/hook",
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=None,
            ),
        ):
            result = wm._send_webhook(
                "http://example.com/hook",
                {"event": "goal.completed", "data": {}, "ts": 1.0, "cognia_version": "3.0"},
                "",
                1,
                "goal.completed",
            )
        assert result is False

    def test_send_returns_false_on_network_error(self, wm):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = wm._send_webhook(
                "http://example.com/hook",
                {"event": "goal.completed", "data": {}, "ts": 1.0, "cognia_version": "3.0"},
                "",
                1,
                "goal.completed",
            )
        assert result is False


class TestFire:
    def test_fire_does_not_block(self, wm):
        """fire() must return almost immediately regardless of HTTP latency."""
        wm.register("http://example.com/hook", ["goal.completed"])

        call_time = None

        def slow_urlopen(*args, **kwargs):
            time.sleep(0.5)
            raise OSError("mock")

        with patch("urllib.request.urlopen", side_effect=slow_urlopen):
            t0 = time.monotonic()
            wm.fire("goal.completed", {"goal_id": 1, "title": "test"})
            elapsed = time.monotonic() - t0

        # fire() itself should return in well under 100 ms
        assert elapsed < 0.1, f"fire() blocked for {elapsed:.3f}s"

    def test_fire_ignored_for_unknown_event(self, wm):
        """fire() with an unknown event silently does nothing."""
        # Should not raise even with no registered webhooks
        wm.fire("nonexistent.event", {})


class TestHmacSignature:
    def test_hmac_signature_generated_when_secret_present(self, wm):
        """X-Cognia-Signature header must be sha256=<hex> of the request body."""
        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(dict(req.headers))
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        secret = "my-signing-secret"
        payload = {
            "event": "goal.completed",
            "data": {"goal_id": 42},
            "ts": 1000.0,
            "cognia_version": "3.0",
        }
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            wm._send_webhook(
                "http://example.com/hook",
                payload,
                secret,
                1,
                "goal.completed",
            )

        assert "X-cognia-signature" in captured_headers
        sig_header = captured_headers["X-cognia-signature"]
        assert sig_header.startswith("sha256=")
        hex_val = sig_header[len("sha256="):]

        body = json.dumps(payload).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        assert hex_val == expected

    def test_no_signature_header_when_no_secret(self, wm):
        """No X-Cognia-Signature when secret is empty."""
        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(dict(req.headers))
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        payload = {"event": "goal.created", "data": {}, "ts": 1.0, "cognia_version": "3.0"}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            wm._send_webhook("http://example.com/hook", payload, "", 1, "goal.created")

        assert "X-cognia-signature" not in captured_headers


class TestDeliveryLog:
    def test_delivery_log_populated_after_fire(self, wm):
        """Delivery log should record a row after _send_webhook() runs."""
        h = wm.register("http://example.com/hook", ["goal.completed"])

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        payload = {"event": "goal.completed", "data": {}, "ts": 1.0, "cognia_version": "3.0"}
        with patch("urllib.request.urlopen", return_value=mock_resp):
            wm._send_webhook("http://example.com/hook", payload, "", h["id"], "goal.completed")

        log = wm.get_delivery_log(h["id"])
        assert len(log) >= 1
        assert log[0]["event_type"] == "goal.completed"
        assert log[0]["status"] == "ok"
        assert log[0]["response_code"] == 200
