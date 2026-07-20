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
    import model_router as mr
    src = inspect.getsource(mr.llamar_ollama_routed)
    assert "_llamar_shard_local" in src, "Ollama failure must fall back to local shards"


def test_local_shard_fallback_graceful_without_shards(monkeypatch, tmp_path):
    """
    Sin shards instalados, devolver None sin lanzar.

    Este test simulaba "no hay shards" con SHARD_WEIGHTS_DIR="" y pasaba por el
    motivo equivocado: la cadena vacia se resolvia contra la raiz del repo, que
    existe, y shard_0.npz no estaba alli. Es decir, pasaba GRACIAS al bug del
    2026-07-20 — el mismo que impedia que la inferencia por shards arrancara en
    una instalacion por defecto. Arreglada la resolucion (model_constants.
    shard_weights_dir), "" significa "no configurado" y cae al default, donde
    los shards SI estan: el test empezo a fallar porque el router por fin
    respondia de verdad.

    Ahora se simula lo que se queria simular: un directorio que existe pero no
    tiene pesos dentro (bajaste el repo, no bajaste los shards).
    """
    import model_router as mr
    vacio = tmp_path / "sin_shards"
    vacio.mkdir()
    monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(vacio))
    mr._LOCAL_ORCH = None                        # reset the lazy singleton
    # Must never raise; returns None when there is nothing to run.
    assert mr._llamar_shard_local("hola") is None


def test_route_cache_is_lru_not_fifo():
    """Regression: the route() cache claims LRU but the hit path never refreshed
    recency, so eviction degraded to FIFO and evicted the just-used entry.
    Re-accessing a key must protect it from eviction."""
    import model_router as mr
    r = mr.ModelRouter()
    r._max_cache = 3
    for q in ("aaa", "bbb", "ccc"):
        r.route(q)
    r.route("aaa")          # re-access -> "aaa" becomes most-recently-used
    r.route("ddd")          # overflow -> evict the true LRU, which is "bbb"

    keys = list(r._cache.keys())
    assert any("aaa" in k for k in keys), "recently-used 'aaa' must survive eviction"
    assert not any("bbb" in k for k in keys), "true-LRU 'bbb' must be evicted"
    assert len(r._cache) == 3


def test_route_cache_returns_same_decision_on_hit():
    """A cache hit must return the cached decision (identity), not recompute."""
    import model_router as mr
    r = mr.ModelRouter()
    first = r.route("escribe una funcion python para sumar")
    second = r.route("escribe una funcion python para sumar")
    assert first is second
