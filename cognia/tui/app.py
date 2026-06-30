"""
app.py -- Aplicacion Textual de Cognia (CogniaTUI).

Que: arma el layout (header / sidebar | mainview / statusbar + footer), registra
el tema de Cognia, conecta el sidebar con el ContentSwitcher para una navegacion
100% por teclado, y suma la capa de UX: paleta de comandos (ctrl+p), toasts
(notify_ok/info/warn/err), modales de confirmacion (confirm) para acciones
destructivas y la ayuda completa de atajos.

Por que: un unico punto que ensambla los componentes reutilizables de
cognia/tui/widgets/ y define los atajos. No duplica logica de las vistas; solo
orquesta foco, navegacion, notificaciones y confirmaciones.

Nota: este es un frontend NUEVO y paralelo. NO reemplaza ni toca cognia/cli.py.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer

from .commands import CogniaCommands
from .theme import COGNIA_THEME_NAME, cognia_theme
from .widgets import CogniaHeader, ConfirmModal, MainView, Sidebar, StatusBar
from .widgets.chat import ChatView
from .widgets.mainview import VIEWS
from .widgets.sidebar import view_key_from_item

# Titulo visible de cada vista, por clave (para el status bar y los toasts).
_TITLES: dict[str, str] = {key: title for key, title, _icon in VIEWS}


class CogniaTUI(App):
    """TUI de Cognia: navegacion por teclado + paleta/toasts/modales/ayuda."""

    CSS_PATH = "app.tcss"
    TITLE = "Cognia"

    # Paleta de comandos: la nativa de Textual (system commands) + las de Cognia.
    COMMANDS = App.COMMANDS | {CogniaCommands}

    BINDINGS = [
        Binding("q", "request_quit", "Salir"),
        Binding("question_mark", "help", "Ayuda"),
        Binding("ctrl+l", "clear_chat", "Limpiar chat"),
        # Paleta de comandos: ctrl+p (nativo, lo re-declaramos explicito porque
        # agregar el bind ":" suprime el default que Textual pone solo) y ":".
        Binding("ctrl+p", "command_palette", "Comandos", show=False),
        Binding("colon", "command_palette", "Comandos", show=False),
        Binding("tab", "focus_next", "Panel sig.", show=False),
        Binding("shift+tab", "focus_previous", "Panel ant.", show=False),
    ]
    # Teclas 1..N -> ir directo a cada vista (ocultas del footer para no saturar).
    BINDINGS += [
        Binding(str(i + 1), f"show_view('{key}')", title, show=False)
        for i, (key, title, _icon) in enumerate(VIEWS)
    ]

    # Vista activa actual; se inicializa al boot para no notificar el primer sync.
    _current_view_key: str = VIEWS[0][0]

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
        self._current_view_key = VIEWS[0][0]
        self._sync_context(VIEWS[0][0])

    # --- Navegacion: sidebar -> ContentSwitcher -------------------------------

    @on(Sidebar.Highlighted)
    def _on_highlight(self, event: Sidebar.Highlighted) -> None:
        item_id = event.item.id if event.item else None
        key = view_key_from_item(item_id)
        if not key:
            return
        self.query_one(MainView).current = key
        self._sync_context(key)
        # Toast solo cuando la vista REALMENTE cambia (no en el sync del boot).
        if key != self._current_view_key:
            self._current_view_key = key
            self.notify_info(f"Vista: {_TITLES.get(key, key)}")

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

    # --- Acciones con confirmacion (workers: no bloquean el loop) -------------

    @work
    async def action_request_quit(self) -> None:
        """Salir con confirmacion: 'q' no cierra directo, pregunta primero."""
        if await self.confirm("Seguro que quieres salir de Cognia?"):
            self.exit()

    @work
    async def action_clear_chat(self) -> None:
        """Limpiar el chat con confirmacion; notifica al completar."""
        if await self.confirm("Limpiar la conversacion actual?"):
            self.query_one(ChatView).clear()
            self.notify_ok("Chat limpiado")

    async def confirm(self, question: str) -> bool:
        """Muestra un ConfirmModal y espera la respuesta (True=si, False=no).

        push_screen_wait corre el modal en el loop async sin congelar la UI; debe
        invocarse desde un worker (por eso las acciones que confirman son @work).
        """
        return await self.push_screen_wait(ConfirmModal(question))

    # --- Toasts (notify) con severidad semantica ------------------------------

    def notify_ok(self, message: str, title: str = "Listo") -> None:
        """Exito. Textual no tiene toast 'success': usa severidad informativa."""
        self.notify(message, title=title, severity="information")

    def notify_info(self, message: str, title: str = "Info") -> None:
        """Informativo (azul)."""
        self.notify(message, title=title, severity="information")

    def notify_warn(self, message: str, title: str = "Atencion") -> None:
        """Advertencia (amarillo)."""
        self.notify(message, title=title, severity="warning")

    def notify_err(self, message: str, title: str = "Error") -> None:
        """Error (rojo)."""
        self.notify(message, title=title, severity="error")
