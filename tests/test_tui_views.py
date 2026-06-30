"""
test_tui_views.py -- Verificacion headless de las vistas Memoria/Modelos/Logs.

Corre la app con Pilot (run_test, sin terminal) y comprueba que las tres vistas,
antes placeholders, estan cableadas a datos REALES del backend:

  - Modelos: ModelsView lista las claves del registry de GGUF (3b, 7b...) y marca
    existencia en disco (ok/falta) y el modelo activo. resolve_gguf_path se mockea
    para controlar existencia sin depender de pesos de varios GB.
  - Logs: el TuiLogHandler instalado en el root logger empuja un logging real al
    LogsPanel; un getLogger(...).info("hola test") aparece en el panel.
  - Memoria: MemoryView arranca con su empty-state; con un backend mockeado, una
    busqueda (en un worker, sin bloquear la UI) muestra los resultados.
  - No-regresiones: la app bootea con las 6 vistas reales montadas (sin placeholders).

Backends mockeados (no tocar DB pesada ni cargar modelos). pytest-asyncio auto.
"""

from __future__ import annotations

import logging

import pytest

from cognia.tui.app import CogniaTUI
from cognia.tui.widgets import memory_view as memory_view_mod
from cognia.tui.widgets import models_view as models_view_mod
from cognia.tui.widgets.logspanel import LogsPanel
from cognia.tui.widgets.mainview import MainView
from cognia.tui.widgets.memory_view import MemoryView
from cognia.tui.widgets.models_view import ModelsView, active_key
from shattering.model_constants import MODEL_GGUF_DEFAULT, MODEL_GGUF_REGISTRY


# --- Modelos ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_models_view_lists_registry(monkeypatch, tmp_path):
    # 3b existe en disco (archivo temporal), 7b falta. Sin env -> activo = default.
    exist = tmp_path / "qwen3b.gguf"
    exist.write_bytes(b"x" * 1234)
    missing = tmp_path / "qwen7b.gguf"  # no se crea
    paths = {"3b": exist, "7b": missing}
    monkeypatch.setattr(models_view_mod, "resolve_gguf_path", lambda key: paths.get(key))
    monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)

    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        mv = app.query_one(ModelsView)
        # Lista TODAS las claves del registry, en orden.
        assert mv._row_keys == list(MODEL_GGUF_REGISTRY)
        txt = mv.table_text()
        for key in MODEL_GGUF_REGISTRY:
            assert key in txt
        # Existencia marcada: 3b ok, 7b falta.
        assert "ok" in txt
        assert "falta" in txt
        # El activo (sin env) es el default del registry.
        assert active_key() == MODEL_GGUF_DEFAULT
        assert MODEL_GGUF_DEFAULT in mv.table_text()


# --- Logs -------------------------------------------------------------------

def _logs_text(logs: LogsPanel) -> str:
    """Texto del panel: lineas ya renderizadas + las diferidas (size aun no conocido)."""
    parts = [strip.text for strip in logs.lines]
    for deferred in getattr(logs, "_deferred_renders", []):
        content = getattr(deferred, "content", "")
        parts.append(content.plain if hasattr(content, "plain") else str(content))
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_logs_view_receives_logs():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Mostrar la vista Logs (tecla 5) para que el RichLog tenga tamano.
        await pilot.press("5")
        await pilot.pause()
        # Logger generico (no-cognia) -> propaga al root -> capturado.
        logging.getLogger("x").info("hola test")
        # Logger de cognia (propagate=False) -> capturado por el handler en "cognia".
        logging.getLogger("cognia.tui.test").warning("aviso cognia")
        await pilot.pause()
        logs = app.query_one(LogsPanel)
        text = _logs_text(logs)
        assert "hola test" in text
        assert "aviso cognia" in text


@pytest.mark.asyncio
async def test_log_handler_installed_at_info():
    # El handler se instala en root Y en "cognia" con nivel INFO al montar la app.
    from cognia.tui.log_handler import TuiLogHandler
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        root = logging.getLogger()
        cognia = logging.getLogger("cognia")
        assert len([h for h in root.handlers if isinstance(h, TuiLogHandler)]) == 1
        assert len([h for h in cognia.handlers if isinstance(h, TuiLogHandler)]) == 1
        assert root.level <= logging.INFO
    # Tras cerrar, el handler se quito de ambos (no se filtra entre apps).
    assert not any(isinstance(h, TuiLogHandler) for h in logging.getLogger().handlers)
    assert not any(isinstance(h, TuiLogHandler) for h in logging.getLogger("cognia").handlers)


# --- Memoria ----------------------------------------------------------------

class _FakeMemoryBackend:
    """Backend de memoria mockeado (no toca DB): stats y search canned."""

    def stats(self) -> dict:
        return {"projects": [("conversacion", 7), ("default", 3)], "total_pointers": 10}

    def search(self, query: str, limit: int = 20):
        return [{
            "score": 0.91,
            "text": "resultado de prueba para " + query,
            "source_kind": "text",
            "source_ref": "mem:1",
        }]


@pytest.mark.asyncio
async def test_memory_view_starts_with_empty_state():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        mv = app.query_one(MemoryView)
        assert "Escribi para buscar" in mv.output_text()


@pytest.mark.asyncio
async def test_memory_view_search_shows_results():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        mv = app.query_one(MemoryView)
        # Inyectar el backend mock y suprimir el worker de stats (no tocar la DB real).
        mv._backend = _FakeMemoryBackend()
        mv._stats_loaded = True
        # Disparar la busqueda por el mismo camino-worker que usa el Input.
        mv._run_search("prueba")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out = mv.output_text()
        assert "resultado de prueba" in out


@pytest.mark.asyncio
async def test_memory_view_stats_render():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        mv = app.query_one(MemoryView)
        mv._backend = _FakeMemoryBackend()
        mv._stats_loaded = True
        mv._load_stats()
        await app.workers.wait_for_complete()
        await pilot.pause()
        stats = mv.stats_text()
        assert "10 punteros" in stats
        assert "2 proyectos" in stats


@pytest.mark.asyncio
async def test_memory_backend_search_never_raises():
    # Sin DB util/conexion rara, search degrada a [] sin levantar (best-effort).
    backend = memory_view_mod.MemoryBackend(db_path="/nonexistent/dir/does/not/exist.db")
    assert backend.search("cualquier cosa") == []
    assert backend.stats()["total_pointers"] == 0


# --- No regresiones (las 6 vistas reales montadas, sin placeholders) --------

@pytest.mark.asyncio
async def test_no_regressions():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Las tres vistas nuevas estan cableadas como widgets reales.
        assert app.query_one(MemoryView) is not None
        assert app.query_one(ModelsView) is not None
        assert app.query_one(LogsPanel) is not None
        # No quedaron placeholders: ya no existe PlaceholderView en mainview.
        from cognia.tui.widgets import mainview
        assert not hasattr(mainview, "PlaceholderView")
        # El switcher conserva las 6 secciones.
        switcher = app.query_one(MainView)
        ids = {child.id for child in switcher.children}
        assert {"chat", "entrenamiento", "memoria", "modelos", "logs", "ayuda"} <= ids
