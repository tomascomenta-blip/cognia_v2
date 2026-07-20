"""
test_tui_chat.py -- Verificacion headless de la vista de chat de la TUI.

Corre la app con Pilot (run_test, sin terminal) y comprueba, con el backend
MOCKEADO (para no depender del modelo lento): que el mensaje del usuario aparece
en el historial, que la respuesta del backend aparece tras el worker, que un
"[backend no disponible: ...]" se muestra como mensaje de SISTEMA sin excepcion,
y que respond() NO corre en el hilo de la UI (worker -> UI no bloqueada).

Para mockear se parchea CogniaBackend.respond a nivel de clase, asi la instancia
que crea ChatView usa la version de prueba. pytest-asyncio en modo auto.
"""

from __future__ import annotations

import threading

import pytest

from cognia.tui import backend
from cognia.tui.app import CogniaTUI
from cognia.tui.widgets.chat import ChatView
from textual.widgets import Input


async def _send(pilot, app, text: str) -> ChatView:
    """Enfoca el input, escribe `text`, presiona Enter y devuelve la ChatView."""
    chat = app.query_one(ChatView)
    inp = app.query_one("#chat-input", Input)
    inp.focus()
    await pilot.pause()
    inp.value = text
    await pilot.press("enter")
    await pilot.pause()
    return chat


@pytest.mark.asyncio
async def test_user_message_appears(monkeypatch):
    monkeypatch.setattr(backend.CogniaBackend, "respond",
                        lambda self, m: "respuesta de prueba")
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        chat = await _send(pilot, app, "hola cognia")
        # El mensaje del usuario esta en el historial inmediatamente (sin esperar
        # al worker: se agrega en el hilo de la UI antes de lanzarlo).
        assert "hola cognia" in chat.history_text()


@pytest.mark.asyncio
async def test_assistant_response_appears(monkeypatch):
    monkeypatch.setattr(backend.CogniaBackend, "respond",
                        lambda self, m: "respuesta de prueba")
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        chat = await _send(pilot, app, "pregunta")
        # Esperar a que el worker termine y a que el call_from_thread procese.
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "respuesta de prueba" in chat.history_text()
        assert chat.last_message_role() == "assistant"


@pytest.mark.asyncio
async def test_backend_unavailable_graceful(monkeypatch):
    monkeypatch.setattr(backend.CogniaBackend, "respond",
                        lambda self, m: "[backend no disponible: test]")
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        chat = await _send(pilot, app, "hay alguien?")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # Se muestra como mensaje de SISTEMA (warn), no como crash.
        assert "[backend no disponible: test]" in chat.history_text()
        assert chat.last_message_role() == "system"


@pytest.mark.asyncio
async def test_ui_not_blocked(monkeypatch):
    # respond() registra en que hilo corrio: debe ser un worker-thread, NUNCA el
    # hilo principal (el de la UI). Si corriera en el hilo de la UI, la TUI se
    # congelaria durante toda la generacion.
    seen: dict = {}

    def _fake_respond(self, message):
        seen["is_main"] = threading.current_thread() is threading.main_thread()
        return "ok"

    monkeypatch.setattr(backend.CogniaBackend, "respond", _fake_respond)
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _send(pilot, app, "test no-bloqueo")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert seen.get("is_main") is False
