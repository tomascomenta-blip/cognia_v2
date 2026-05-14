"""
tests/test_phase9_security.py
==============================
Phase 9 security regression tests.
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── 9.1: SQL injection via emotion_filter ─────────────────────────────────────

class TestEpisodicSQLInjection:
    """9.1: emotion_filter must be parameterized, never interpolated."""

    def _setup_db(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE episodic_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, observation TEXT, label TEXT,
                vector TEXT, confidence REAL DEFAULT 0.5,
                importance REAL DEFAULT 1.0, access_count INTEGER DEFAULT 0,
                last_accessed TEXT, emotional_context TEXT,
                emotion_score REAL DEFAULT 0.0,
                emotion_label TEXT DEFAULT 'neutral',
                surprise REAL DEFAULT 0.0,
                feedback_weight REAL DEFAULT 1.0,
                encrypted_at TEXT DEFAULT NULL,
                forgotten INTEGER DEFAULT 0, notes TEXT
            )
        """)
        conn.execute(
            "INSERT INTO episodic_memory (timestamp, observation, label, vector, emotion_label) "
            "VALUES ('2026-01-01', 'safe observation', 'test', '[0.1,0.2]', 'happy')"
        )
        conn.execute(
            "INSERT INTO episodic_memory (timestamp, observation, label, vector, emotion_label) "
            "VALUES ('2026-01-01', 'other observation', 'test', '[0.1,0.2]', 'neutral')"
        )
        conn.commit()
        return conn

    def test_injection_attempt_returns_empty(self):
        import sqlite3
        from unittest.mock import patch
        conn = self._setup_db()
        from cognia.memory.episodic import EpisodicMemory
        em = EpisodicMemory(":memory:")
        with patch("cognia.memory.episodic.db_connect", return_value=conn):
            results = em.retrieve_similar([0.1] * 8, emotion_filter="' OR '1'='1")
        assert results == [], f"Injection should return no rows, got {len(results)}"

    def test_legitimate_filter_returns_matching_rows(self):
        import sqlite3
        from unittest.mock import patch
        conn = self._setup_db()
        from cognia.memory.episodic import EpisodicMemory
        em = EpisodicMemory(":memory:")
        with patch("cognia.memory.episodic.db_connect", return_value=conn):
            results = em.retrieve_similar([0.1] * 8, emotion_filter="happy")
        labels = [r["emotion"]["label"] for r in results]
        assert all(l == "happy" for l in labels), f"Unexpected labels: {labels}"



# ── 9.5: web_app.py optional API key middleware ────────────────────────────────

class TestWebAppApiKeyMiddleware:
    """9.5: COGNIA_WEB_API_KEY gates /api/* routes when set."""

    def _reload_app(self, monkeypatch, api_key=""):
        monkeypatch.setenv("COGNIA_WEB_API_KEY", api_key)
        import importlib
        import web_app as _wa
        importlib.reload(_wa)
        return _wa.app.test_client(), _wa.app

    def test_no_env_var_allows_access(self, monkeypatch):
        client, app = self._reload_app(monkeypatch, "")
        with app.app_context():
            resp = client.get("/api/health")
        assert resp.status_code != 401

    def test_wrong_key_returns_401(self, monkeypatch):
        client, app = self._reload_app(monkeypatch, "secret123")
        with app.app_context():
            resp = client.get("/api/health", headers={"X-Api-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_allows_access(self, monkeypatch):
        client, app = self._reload_app(monkeypatch, "secret123")
        with app.app_context():
            resp = client.get("/api/health", headers={"X-Api-Key": "secret123"})
        assert resp.status_code == 200

    def test_missing_key_header_returns_401(self, monkeypatch):
        client, app = self._reload_app(monkeypatch, "secret123")
        with app.app_context():
            resp = client.get("/api/health")
        assert resp.status_code == 401

    def test_root_always_accessible(self, monkeypatch):
        client, app = self._reload_app(monkeypatch, "secret123")
        with app.app_context():
            resp = client.get("/")
        assert resp.status_code == 200


# ── 9.6: feedback rate limiting ────────────────────────────────────────────────

class TestFeedbackRateLimit:
    """9.6: apply_feedback must rate-limit and prevent double-application."""

    def _make_stub(self):
        """Minimal stub with the feedback guards wired in."""
        import types
        from collections import deque

        stub = types.SimpleNamespace()
        stub._feedback_timestamps = deque()
        stub._feedback_applied_ids = set()

        # Minimal no-op dependencies used by the real apply_feedback path
        stub.chat_history = types.SimpleNamespace(add_feedback=lambda *a, **k: None)
        stub.metacog = types.SimpleNamespace(log_decision=lambda **k: None)
        stub._feedback_engine = None
        stub.working_mem = types.SimpleNamespace(add=lambda *a, **k: None)
        stub.perception = types.SimpleNamespace(encode=lambda t: [0.1] * 8)
        stub.episodic = types.SimpleNamespace(store=lambda **k: -1)

        from cognia.cognia import Cognia
        stub.apply_feedback = Cognia.apply_feedback.__get__(stub, type(stub))
        return stub

    def test_duplicate_feedback_rejected(self):
        stub = self._make_stub()
        stub.apply_feedback("resp-001", True)
        result = stub.apply_feedback("resp-001", True)
        assert "ya fue registrado" in result

    def test_rate_limit_after_10_calls(self):
        stub = self._make_stub()
        for i in range(10):
            r = stub.apply_feedback(f"resp-{i:04d}", True)
            assert "Demasiados" not in r
        result = stub.apply_feedback("resp-0010", True)
        assert "Demasiados" in result

    def test_rate_limit_resets_after_window(self):
        import time
        stub = self._make_stub()
        # Backdate 10 timestamps to simulate expired window (>60 s ago)
        stub._feedback_timestamps.extend([time.time() - 70] * 10)
        result = stub.apply_feedback("resp-new", True)
        assert "Demasiados" not in result

    def test_empty_response_id_not_tracked(self):
        stub = self._make_stub()
        r1 = stub.apply_feedback("", True)
        r2 = stub.apply_feedback("", True)
        # Empty IDs should not trigger duplicate block (they can't be tracked)
        assert "ya fue registrado" not in r2


# ── 9.7: SSRF via OLLAMA_URL ───────────────────────────────────────────────────

class TestOllamaUrlValidation:
    """9.7: validate_ollama_url must block non-localhost URLs."""

    def _v(self, url):
        from security.ollama_url import validate_ollama_url
        return validate_ollama_url(url)

    def test_localhost_allowed(self):
        assert self._v("http://localhost:11434") == "http://localhost:11434"

    def test_localhost_with_path_allowed(self):
        result = self._v("http://localhost:11434/api/generate")
        assert result == "http://localhost:11434/api/generate"

    def test_127_0_0_1_allowed(self):
        assert self._v("http://127.0.0.1:11434") == "http://127.0.0.1:11434"

    def test_ipv6_loopback_allowed(self):
        assert self._v("http://[::1]:11434") == "http://[::1]:11434"

    def test_aws_metadata_blocked(self):
        from security.ollama_url import _FALLBACK
        assert self._v("http://169.254.169.254/latest/meta-data/") == _FALLBACK

    def test_public_ip_blocked(self):
        from security.ollama_url import _FALLBACK
        assert self._v("http://1.2.3.4:11434") == _FALLBACK

    def test_private_network_blocked(self):
        from security.ollama_url import _FALLBACK
        assert self._v("http://10.0.0.1:11434") == _FALLBACK

    def test_empty_returns_fallback(self):
        from security.ollama_url import _FALLBACK
        assert self._v("") == _FALLBACK

    def test_none_like_empty_string_returns_fallback(self):
        from security.ollama_url import _FALLBACK
        assert self._v("") == _FALLBACK
