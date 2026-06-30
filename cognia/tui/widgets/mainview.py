"""
mainview.py -- Area principal: ContentSwitcher con una vista por seccion.

Que: VIEWS define las secciones (clave, titulo, icono ASCII) que comparten el
sidebar y este switcher. MainView monta una vista por seccion; cada una es un
placeholder con titulo y un empty-state claro (icono + "Sin datos aun" + pista),
nunca una pantalla vacia. La seccion "Logs" hospeda el LogsPanel real; "Ayuda"
muestra los atajos de teclado.

Por que: separar el contenido (placeholders verificables) del chrome (header,
sidebar, status). El contenido real (chat, metricas, memoria) se cablea en
checkpoints siguientes reemplazando cada PlaceholderView por su widget definitivo.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, Static

from ..theme import COLORS
from .logspanel import LogsPanel

# Fuente de verdad de la navegacion: (clave de vista, titulo visible, icono ASCII).
# La clave es el id del child del ContentSwitcher y la base del id del item del
# sidebar (nav-<clave>). El orden define el mapeo de teclas numericas 1..6.
VIEWS: tuple[tuple[str, str, str], ...] = (
    ("chat", "Chat", ">"),
    ("entrenamiento", "Entrenamiento", "^"),
    ("memoria", "Memoria", "*"),
    ("modelos", "Modelos", "#"),
    ("logs", "Logs", "="),
    ("ayuda", "Ayuda", "?"),
)

DEFAULT_VIEW = VIEWS[0][0]

# Empty-state por seccion: (icono grande, mensaje, pista de accion).
_EMPTY_STATE: dict[str, tuple[str, str, str]] = {
    "chat": ("[ ]", "Sin conversacion todavia", "El chat real se conecta en el proximo checkpoint."),
    "entrenamiento": ("[~]", "Sin corridas de entrenamiento", "Las metricas de training apareceran aqui."),
    "memoria": ("{ }", "Sin memorias indexadas", "La memoria episodica/semantica se mostrara aqui."),
    "modelos": ("< >", "Sin modelos cargados", "Los shards y modelos disponibles apareceran aqui."),
}


class PlaceholderView(Vertical):
    """Panel con titulo y empty-state centrado (icono + mensaje + pista)."""

    def __init__(self, key: str, title: str) -> None:
        super().__init__(id=key, classes="view")
        self.border_title = title
        icon, message, hint = _EMPTY_STATE[key]
        self._empty_text = self._build_empty(icon, message, hint)

    def compose(self) -> ComposeResult:
        yield Static(self._empty_text, classes="empty-state")

    @staticmethod
    def _build_empty(icon: str, message: str, hint: str) -> Text:
        text = Text(justify="center")
        text.append(f"{icon}\n\n", style=f"bold {COLORS['accent']}")
        text.append(f"{message}\n", style=f"bold {COLORS['text']}")
        text.append(hint, style=COLORS["muted"])
        return text


class HelpView(Vertical):
    """Vista de Ayuda: lista los atajos de teclado (no es un empty-state)."""

    SHORTCUTS: tuple[tuple[str, str], ...] = (
        ("q", "Salir de Cognia"),
        ("?", "Mostrar esta ayuda"),
        ("tab / shift+tab", "Mover el foco entre paneles"),
        ("j / k  o  flechas", "Navegar la lista del menu"),
        ("1 .. 6", "Ir directo a una seccion"),
        ("enter", "Activar el item del menu"),
    )

    def __init__(self) -> None:
        super().__init__(id="ayuda", classes="view")
        self.border_title = "Ayuda"

    def compose(self) -> ComposeResult:
        yield Static(self._build_help(), classes="help-body")

    def _build_help(self) -> Text:
        text = Text()
        text.append("Atajos de teclado\n\n", style=f"bold {COLORS['accent']}")
        for keys, desc in self.SHORTCUTS:
            text.append(f"  {keys:<20}", style=f"bold {COLORS['info']}")
            text.append(f"{desc}\n", style=COLORS["text"])
        return text


class MainView(ContentSwitcher):
    """ContentSwitcher que alterna entre las vistas segun el sidebar."""

    def __init__(self) -> None:
        super().__init__(initial=DEFAULT_VIEW, id="mainview")

    def compose(self) -> ComposeResult:
        for key, title, _icon in VIEWS:
            if key == "logs":
                yield LogsPanel(id="logs", classes="view")
            elif key == "ayuda":
                yield HelpView()
            else:
                yield PlaceholderView(key, title)
