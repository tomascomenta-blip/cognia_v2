"""
app.py -- Aplicacion Textual de Cognia (CogniaTUI).

Que: arma el layout (header / sidebar | mainview / statusbar + footer), registra
el tema de Cognia, y conecta el sidebar con el ContentSwitcher para una
navegacion 100% por teclado. Es la FUNDACION: el contenido de cada vista es
placeholder (empty-states), el chat y las metricas reales se cablean despues.

Por que: un unico punto que ensambla los componentes reutilizables de
cognia/tui/widgets/ y define los atajos. No duplica logica de las vistas; solo
orquesta foco, navegacion y estado.

Nota: este es un frontend NUEVO y paralelo. NO reemplaza ni toca cognia/cli.py.
"""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer

from .theme import COGNIA_THEME_NAME, cognia_theme
from .widgets import CogniaHeader, MainView, Sidebar, StatusBar
from .widgets.mainview import VIEWS
from .widgets.sidebar import ITEM_PREFIX, view_key_from_item

# Titulo visible de cada vista, por clave (para el contexto del status bar).
_TITLES: dict[str, str] = {key: title for key, title, _icon in VIEWS}


class CogniaTUI(App):
    """TUI de Cognia: navegacion por teclado sobre header/sidebar/mainview/status."""

    CSS_PATH = "app.tcss"
    TITLE = "Cognia"

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("question_mark", "help", "Ayuda"),
        Binding("tab", "focus_next", "Panel sig.", show=False),
        Binding("shift+tab", "focus_previous", "Panel ant.", show=False),
    ]
    # Teclas 1..N -> ir directo a cada vista (ocultas del footer para no saturar).
    BINDINGS += [
        Binding(str(i + 1), f"show_view('{key}')", title, show=False)
        for i, (key, title, _icon) in enumerate(VIEWS)
    ]

    def compose(self) -> ComposeResult:
        yield CogniaHeader(id="header")
        with Horizontal(id="body"):
            yield Sidebar()
            yield MainView()
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(cognia_theme())
        self.theme = COGNIA_THEME_NAME
        self.query_one(Sidebar).focus()
        self._sync_context(VIEWS[0][0])

    # --- Navegacion: sidebar -> ContentSwitcher -------------------------------

    @on(Sidebar.Highlighted)
    def _on_highlight(self, event: Sidebar.Highlighted) -> None:
        item_id = event.item.id if event.item else None
        key = view_key_from_item(item_id)
        if key:
            self.query_one(MainView).current = key
            self._sync_context(key)

    def action_show_view(self, key: str) -> None:
        """Salta a una vista por su clave moviendo el cursor del sidebar."""
        sidebar = self.query_one(Sidebar)
        for index, (vkey, _title, _icon) in enumerate(VIEWS):
            if vkey == key:
                sidebar.index = index
                break

    def action_help(self) -> None:
        self.action_show_view("ayuda")

    def _sync_context(self, key: str) -> None:
        self.query_one(StatusBar).set_status(context=_TITLES.get(key, ""))
