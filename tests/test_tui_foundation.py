"""
test_tui_foundation.py -- Verificacion headless de la fundacion de la TUI.

Corre la app con Pilot (run_test, sin terminal) y comprueba: que el layout existe
(header/sidebar/mainview/statusbar/footer), que las teclas de navegacion cambian
de vista, que j/k mueven el cursor del menu, que el empty-state se muestra, y que
'q' cierra la app. No necesita pesos ni servicios; solo Textual.

pytest-asyncio en modo auto (pytest.ini): los tests async se detectan solos.
"""

from __future__ import annotations

import pytest

from cognia.tui.app import CogniaTUI
from cognia.tui.widgets import MainView, Sidebar
from cognia.tui.widgets.logspanel import LogsPanel
from cognia.tui.widgets.mainview import VIEWS


def test_views_match_sidebar_keys():
    # Cada vista tiene clave unica y hay 6 secciones esperadas.
    keys = [key for key, _t, _i in VIEWS]
    assert keys == ["chat", "entrenamiento", "memoria", "modelos", "logs", "ayuda"]
    assert len(keys) == len(set(keys))


@pytest.mark.asyncio
async def test_app_boots():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#header") is not None
        assert app.query_one("#sidebar") is not None
        assert app.query_one("#mainview") is not None
        assert app.query_one("#statusbar") is not None
        # Footer nativo presente (atajos visibles).
        from textual.widgets import Footer
        assert len(app.query(Footer)) == 1
        # Vista inicial = chat.
        assert app.query_one(MainView).current == "chat"
        # El foco arranca en el sidebar (navegacion por teclado).
        assert isinstance(app.focused, Sidebar)


@pytest.mark.asyncio
async def test_navigation_keys():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one(MainView)
        assert switcher.current == "chat"
        await pilot.press("3")  # -> memoria
        await pilot.pause()
        assert switcher.current == "memoria"
        await pilot.press("1")  # -> chat
        await pilot.pause()
        assert switcher.current == "chat"


@pytest.mark.asyncio
async def test_jk_moves_cursor():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        sidebar = app.query_one(Sidebar)
        assert sidebar.index == 0
        await pilot.press("j")
        await pilot.pause()
        assert sidebar.index == 1
        assert app.query_one(MainView).current == "entrenamiento"
        await pilot.press("k")
        await pilot.pause()
        assert sidebar.index == 0
        assert app.query_one(MainView).current == "chat"


@pytest.mark.asyncio
async def test_help_binding_switches_to_ayuda():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert app.query_one(MainView).current == "ayuda"


@pytest.mark.asyncio
async def test_empty_state_present():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # La vista chat tiene un empty-state (no es una pantalla vacia).
        from textual.widgets import Static
        empty = app.query_one("#chat .empty-state", Static)
        assert "Sin conversacion" in empty.render().plain


@pytest.mark.asyncio
async def test_logs_panel_write_levels():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        logs = app.query_one(LogsPanel)
        # write(msg, level) no debe romper para ningun nivel semantico.
        for level in ("ok", "info", "warn", "err", "muted"):
            logs.write("linea de prueba", level)
        await pilot.pause()


@pytest.mark.asyncio
async def test_quit_binding():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    # Si run_test() sale del contexto sin colgar, 'q' cerro la app.
    assert app.return_code == 0
