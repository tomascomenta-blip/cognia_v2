"""
test_tui_ux.py -- Verificacion headless de la capa de UX/polish de la TUI.

Corre la app con Pilot (run_test, sin terminal) y comprueba las cuatro piezas del
checkpoint CP7: paleta de comandos (ctrl+p abre la CommandPalette y CogniaCommands
produce hits), toasts (cambiar de vista deja una notificacion), modal de
confirmacion (y/enter -> True; n/escape -> False) y la ayuda completa (lista q, ?,
ctrl+p con sus descripciones). Tambien que 'q' pide confirmacion (no sale directo).

pytest-asyncio en modo auto (pytest.ini): los tests async se detectan solos.
"""

from __future__ import annotations

import pytest
from textual.command import CommandPalette

from cognia.tui.app import CogniaTUI
from cognia.tui.commands import CogniaCommands
from cognia.tui.widgets import MainView
from cognia.tui.widgets.modals import ConfirmModal


async def _collect_hits(provider: CogniaCommands, query: str) -> list:
    """Junta todos los Hit que devuelve provider.search(query)."""
    hits = []
    async for hit in provider.search(query):
        hits.append(hit)
    return hits


@pytest.mark.asyncio
async def test_command_palette_opens():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause()
        # La pantalla activa es la paleta de comandos nativa de Textual.
        assert CommandPalette.is_open(app)
        assert isinstance(app.screen, CommandPalette)
        # Y CogniaCommands produce hits para "chat".
        provider = CogniaCommands(app.screen)
        hits = await _collect_hits(provider, "chat")
        assert len(hits) >= 1
        assert any("Chat" in (hit.text or "") for hit in hits)


@pytest.mark.asyncio
async def test_notification_shows():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app._notifications) == 0
        # Cambiar de vista dispara un toast ("Vista: Memoria").
        await pilot.press("3")  # -> memoria
        await pilot.pause()
        assert len(app._notifications) >= 1
        assert any("Memoria" in n.message for n in app._notifications)


@pytest.mark.asyncio
async def test_confirm_modal():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()

        # 'y' confirma -> dismiss(True).
        results: list = []
        app.push_screen(ConfirmModal("Confirmar?"), callback=results.append)
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")
        await pilot.pause()
        assert results == [True]

        # 'enter' tambien confirma (no hay boton enfocado por defecto).
        results.clear()
        app.push_screen(ConfirmModal("Confirmar?"), callback=results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert results == [True]

        # 'n' cancela -> dismiss(False).
        results.clear()
        app.push_screen(ConfirmModal("Confirmar?"), callback=results.append)
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert results == [False]

        # 'escape' cancela -> dismiss(False).
        results.clear()
        app.push_screen(ConfirmModal("Confirmar?"), callback=results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results == [False]


@pytest.mark.asyncio
async def test_help_lists_shortcuts():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")  # -> vista Ayuda
        await pilot.pause()
        assert app.query_one(MainView).current == "ayuda"
        renderable = app.query_one("#help-body").render()
        text = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        # Teclas principales presentes con su descripcion.
        assert "q" in text and "Salir" in text
        assert "?" in text and "Ayuda" in text
        assert "ctrl+p" in text and "paleta" in text


@pytest.mark.asyncio
async def test_quit_confirms():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # 'q' ya NO sale directo: muestra el ConfirmModal.
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        # Cancelar para no colgar el test; la app sigue viva.
        await pilot.press("n")
        await pilot.pause()
        assert app.return_code is None
