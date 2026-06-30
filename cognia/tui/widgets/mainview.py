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
from .chat import ChatView
from .logspanel import LogsPanel
from .training import TrainingDashboard

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

# Empty-state por seccion: (icono grande, mensaje, pista de accion). Las secciones
# "chat" y "entrenamiento" ya no usan PlaceholderView (las hospedan ChatView y
# TrainingDashboard con su propio empty-state).
_EMPTY_STATE: dict[str, tuple[str, str, str]] = {
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
    """Vista de Ayuda: lista TODOS los atajos agrupados, leidos de BINDINGS.

    Los atajos de la App (navegacion, salir, ayuda) se leen de `App.BINDINGS` en
    tiempo de montaje, asi la ayuda no se desactualiza cuando cambian. Las teclas
    que no son BINDINGS de la App (las provee Textual -- paleta de comandos -- o
    el Sidebar -- j/k) se agregan explicitas en _EXTRA para que la lista quede
    completa. El orden de los grupos lo fija _GROUP_ORDER.
    """

    # action de un Binding de la App -> grupo de la ayuda.
    _ACTION_GROUP: dict[str, str] = {
        "show_view": "Navegacion",
        "focus_next": "Navegacion",
        "focus_previous": "Navegacion",
        "help": "Global",
        "quit": "Global",
        "request_quit": "Global",
        "clear_chat": "Chat",
    }

    # Teclas que NO son BINDINGS de la App (Textual/Sidebar): (grupo, tecla, desc).
    _EXTRA: tuple[tuple[str, str, str], ...] = (
        ("Navegacion", "j / k", "Bajar / subir en el menu"),
        ("Navegacion", "flechas", "Mover el cursor del menu"),
        ("Navegacion", "enter", "Activar el item resaltado"),
        ("Chat", "enter", "Enviar el mensaje al asistente"),
        ("Acciones", "ctrl+p  o  :", "Abrir la paleta de comandos"),
    )

    _GROUP_ORDER: tuple[str, ...] = ("Navegacion", "Chat", "Acciones", "Global")

    # Nombre interno de tecla -> simbolo visible.
    _KEY_DISPLAY: dict[str, str] = {"question_mark": "?"}

    def __init__(self) -> None:
        super().__init__(id="ayuda", classes="view")
        self.border_title = "Ayuda"

    def compose(self) -> ComposeResult:
        yield Static(id="help-body", classes="help-body")

    def on_mount(self) -> None:
        # En on_mount ya hay App: se pueden leer sus BINDINGS reales.
        self.query_one("#help-body", Static).update(self._build_help())

    def _grouped_shortcuts(self) -> dict[str, list[tuple[str, str]]]:
        """Junta los atajos por grupo: BINDINGS de la App + teclas _EXTRA."""
        groups: dict[str, list[tuple[str, str]]] = {g: [] for g in self._GROUP_ORDER}
        for binding in type(self.app).BINDINGS:
            key = getattr(binding, "key", None)
            action = getattr(binding, "action", "")
            desc = getattr(binding, "description", "")
            if key is None:  # forma tupla (key, action, description)
                key, action, desc = binding
            group = self._ACTION_GROUP.get(str(action).split("(", 1)[0])
            if group and desc:
                groups[group].append((self._KEY_DISPLAY.get(key, key), desc))
        for group, key, desc in self._EXTRA:
            groups[group].append((key, desc))
        return groups

    def _build_help(self) -> Text:
        text = Text()
        text.append("Atajos de teclado\n", style=f"bold {COLORS['accent']}")
        groups = self._grouped_shortcuts()
        for group in self._GROUP_ORDER:
            rows = groups.get(group)
            if not rows:
                continue
            text.append(f"\n{group}\n", style=f"bold {COLORS['accent']}")
            for keys, desc in rows:
                text.append(f"  {keys:<16}", style=f"bold {COLORS['info']}")
                text.append(f"{desc}\n", style=COLORS["text"])
        return text


class MainView(ContentSwitcher):
    """ContentSwitcher que alterna entre las vistas segun el sidebar."""

    def __init__(self) -> None:
        super().__init__(initial=DEFAULT_VIEW, id="mainview")

    def compose(self) -> ComposeResult:
        for key, title, _icon in VIEWS:
            if key == "chat":
                yield ChatView()
            elif key == "entrenamiento":
                yield TrainingDashboard()
            elif key == "logs":
                yield LogsPanel(id="logs", classes="view")
            elif key == "ayuda":
                yield HelpView()
            else:
                yield PlaceholderView(key, title)
