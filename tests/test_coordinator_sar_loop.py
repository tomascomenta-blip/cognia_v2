"""
tests/test_coordinator_sar_loop.py — Regresión del loop SAR del coordinador.

Bugs cubiertos (coordinator/app.py):
  1. El loop iteraba una tupla hardcodeada ("qwen-coder-3b-q4",) — los
     sub-modelos Shattering del registry nunca pasaban por sync_stale_nodes
     y su shard_debt jamás se registraba.
  2. asyncio.create_task(_sar_sync_loop()) se creaba sin guardar la
     referencia — el event loop guarda weak refs y el GC podía matar la
     task silenciosamente.
"""

from __future__ import annotations

import asyncio

import pytest

import coordinator.app as app_mod
from coordinator.registry import MODELS, SHATTERING_MODELS


# ══════════════════════════════════════════════════════════════════════════════
# 1. El loop SAR debe consultar TODOS los modelos del registry
# ══════════════════════════════════════════════════════════════════════════════

def test_sar_loop_syncs_all_registry_models(monkeypatch):
    """Una pasada del loop debe llamar sync_stale_nodes para cada modelo
    del registry (incluye qwen-coder-3b-q4 y los sub-modelos Shattering)."""
    synced: list[str] = []
    monkeypatch.setattr(
        app_mod._shard_registry, "sync_stale_nodes",
        lambda model_name, node_timeout: synced.append(model_name) or [],
    )

    # Fake sleep: primera llamada pasa (entra a la pasada del loop),
    # segunda llamada corta el while True.
    calls = {"n": 0}

    async def fake_sleep(_secs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_mod.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._sar_sync_loop())

    # Todos los modelos del registry deben haber pasado por sync_stale_nodes
    assert set(synced) == set(MODELS), (
        f"El loop SAR no cubre todo el registry. Faltan: {set(MODELS) - set(synced)}"
    )
    # En particular los sub-modelos Shattering (bug original) y el default
    for m in SHATTERING_MODELS:
        assert m in synced
    assert "qwen-coder-3b-q4" in synced


# ══════════════════════════════════════════════════════════════════════════════
# 2. La task SAR debe quedar referenciada (no GC-able) y cancelarse al cerrar
# ══════════════════════════════════════════════════════════════════════════════

def test_sar_task_is_referenced_and_cancelled_on_shutdown():
    async def run():
        async with app_mod.lifespan(app_mod.app):
            task = getattr(app_mod.app.state, "sar_sync_task", None)
            assert isinstance(task, asyncio.Task), (
                "lifespan no guarda referencia fuerte a la task SAR "
                "(el event loop solo guarda weak refs — GC puede matarla)"
            )
            assert not task.done()
        # Al salir del lifespan la task debe estar cancelada/terminada
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()

    asyncio.run(run())
