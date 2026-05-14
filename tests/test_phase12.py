"""
tests/test_phase12.py
=====================
Phase 12 — Production Hardening test suite.

Covers:
  - CompressedKVCache.evict_stale() TTL eviction (12.1)
  - ShatteringOrchestrator._evict_mla_caches() integration (12.1)
  - DELETE /user/data response includes scope/warning fields (12.4)
"""

import sys
import os
import time

# Ensure repo root is resolvable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest


# ── 12.1 CompressedKVCache evict_stale ──────────────────────────────────

class TestCompressedKVCacheEviction:

    def setup_method(self):
        from shattering.mla import CompressedKVCache
        self.cache = CompressedKVCache()

    def _put(self, session_id: str, layer_idx: int = 0):
        c_kv = np.zeros((4, 512), dtype=np.float32)
        self.cache.put(session_id, layer_idx, c_kv, 4)

    def test_evict_stale_removes_expired(self):
        self._put("s1")
        self._put("s2")
        assert self.cache.active_sessions() == 2
        # Negative max_age_seconds → everything is stale
        evicted = self.cache.evict_stale(max_age_seconds=-1.0)
        assert evicted == 2
        assert self.cache.active_sessions() == 0

    def test_evict_stale_keeps_fresh(self):
        self._put("s1")
        evicted = self.cache.evict_stale(max_age_seconds=3600.0)
        assert evicted == 0
        assert self.cache.active_sessions() == 1

    def test_evict_stale_partial(self):
        self._put("fresh")
        # Manually backdate last_access for "stale"
        self._put("stale")
        self.cache._last_access["stale"] = time.monotonic() - 7200.0
        evicted = self.cache.evict_stale(max_age_seconds=3600.0)
        assert evicted == 1
        assert self.cache.active_sessions() == 1
        assert self.cache.get("fresh", 0) is not None
        assert self.cache.get("stale", 0) is None

    def test_evict_stale_empty_cache(self):
        evicted = self.cache.evict_stale(max_age_seconds=1.0)
        assert evicted == 0

    def test_clear_removes_last_access(self):
        self._put("s1")
        self.cache.clear("s1")
        assert "s1" not in self.cache._last_access
        assert self.cache.active_sessions() == 0

    def test_put_updates_last_access(self):
        self._put("s1")
        t1 = self.cache._last_access["s1"]
        time.sleep(0.01)
        self._put("s1", layer_idx=1)
        t2 = self.cache._last_access["s1"]
        assert t2 >= t1

    def test_get_updates_last_access(self):
        self._put("s1")
        t1 = self.cache._last_access["s1"]
        time.sleep(0.01)
        self.cache.get("s1", 0)
        t2 = self.cache._last_access["s1"]
        assert t2 >= t1

    def test_active_sessions_reflects_eviction(self):
        for i in range(5):
            self._put(f"session_{i}")
            self.cache._last_access[f"session_{i}"] = time.monotonic() - 9999.0
        assert self.cache.active_sessions() == 5
        self.cache.evict_stale(max_age_seconds=1.0)
        assert self.cache.active_sessions() == 0


# ── 12.1 Orchestrator._evict_mla_caches ─────────────────────────────────

class TestOrchestratorEvictMLA:

    def _make_orch(self):
        from shattering.orchestrator import ShatteringOrchestrator
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "shattering", "manifests", "cognia_desktop.json",
        )
        return ShatteringOrchestrator(manifest_path=manifest_path, mode="local")

    def test_evict_mla_caches_no_engines_no_crash(self):
        orch = self._make_orch()
        orch._evict_mla_caches()   # no loaded engines → must not raise

    def test_evict_mla_caches_with_mock_engine(self):
        from shattering.mla import CompressedKVCache
        orch = self._make_orch()

        # Attach a fake engine with a real CompressedKVCache containing a stale entry
        kv = CompressedKVCache()
        c_kv = np.zeros((2, 512), dtype=np.float32)
        kv.put("old_session", 0, c_kv, 2)
        kv._last_access["old_session"] = time.monotonic() - 9999.0

        class FakeEngine:
            _kv_cache = kv

        orch._fragments._engines["logos/0"] = FakeEngine()

        orch._evict_mla_caches(max_age_seconds=1.0)
        assert kv.active_sessions() == 0

    def test_status_calls_evict(self):
        from shattering.mla import CompressedKVCache
        orch = self._make_orch()

        kv = CompressedKVCache()
        c_kv = np.zeros((1, 512), dtype=np.float32)
        kv.put("stale", 0, c_kv, 1)
        kv._last_access["stale"] = time.monotonic() - 9999.0

        class FakeEngine:
            _kv_cache = kv
            _layers = []

        orch._fragments._engines["logos/0"] = FakeEngine()

        # status() must call _evict_mla_caches; stale entry should be gone
        orch.status()
        assert kv.active_sessions() == 0


# ── 12.4 DELETE /user/data scope warning ────────────────────────────────

class TestUserDataDeleteWarning:

    def test_delete_response_includes_warning_fields(self):
        """Response body must include scope='all' and a warning string."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        import importlib, types

        # Minimal stub: patch db_connect to avoid real SQLite
        import sqlite3, tempfile, pathlib

        tmp = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(tmp)
        conn.execute(
            "CREATE TABLE episodic_memory "
            "(id INTEGER PRIMARY KEY, forgotten INTEGER DEFAULT 0)"
        )
        conn.commit()
        conn.close()

        import cognia.database as _cdb
        orig_connect = _cdb.db_connect

        def _fake_connect(path):
            return sqlite3.connect(tmp)

        _cdb.db_connect = _fake_connect

        try:
            os.environ["COGNIA_ADMIN_KEY"] = "test-key"
            from app.routes.user_data import router
            test_app = FastAPI()
            test_app.include_router(router, prefix="/api")
            client = TestClient(test_app)

            resp = client.delete(
                "/api/user/data",
                headers={"X-Admin-Key": "test-key"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["scope"] == "all"
            assert "warning" in body
            assert len(body["warning"]) > 0
        finally:
            _cdb.db_connect = orig_connect
            del os.environ["COGNIA_ADMIN_KEY"]
            try:
                os.unlink(tmp)
            except OSError:
                pass
