"""
tests/test_model_router_local_fallback.py
=========================================
Regression for bug #2: when Ollama is down and no coordinator is configured, the
REPL chat used to error out ("Ollama no disponible") even though local INT4
shards were loaded. model_router now falls back to in-process local shard
inference (ShatteringOrchestrator.infer) so chat works offline / out-of-the-box.

(The end-to-end "produces real text" check needs the real shards and is verified
manually / via scripts; here we cover wiring + graceful degradation.)
"""

from __future__ import annotations

import inspect


def test_ollama_except_block_wires_local_shard_fallback():
    from cognia_v3.interfaces import model_router as mr
    src = inspect.getsource(mr.llamar_ollama_routed)
    assert "_llamar_shard_local" in src, "Ollama failure must fall back to local shards"


def test_local_shard_fallback_graceful_without_shards(monkeypatch):
    from cognia_v3.interfaces import model_router as mr
    monkeypatch.setenv("SHARD_WEIGHTS_DIR", "")  # no shards available
    mr._LOCAL_ORCH = None                        # reset the lazy singleton
    # Must never raise; returns None when there is nothing to run.
    assert mr._llamar_shard_local("hola") is None
