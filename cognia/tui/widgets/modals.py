"""
modals.py -- Modales (pantallas flotantes) de la TUI de Cognia.

Que: ConfirmModal es un ModalScreen[bool] centrado: muestra una pregunta y dos
botones [Si] [No]. Devuelve su resultado por dismiss(bool): True si el usuario
confirma, False si cancela. Navegable 100% por teclado (y=si, n/esc=no,
enter=el boton enfocado) ademas de click.

Por que: las acciones destructivas (salir, limpiar el chat) deben pedir
confirmacion sin congelar la UI. ModalScreen + push_screen_wait es la forma
idiomatica de Textual 8.x de hacerlo: el dialogo corre en el loop async y el
codigo que lo invoca (App.confirm) espera el resultado sin bloquear.

Convencion: codigo y nombres ASCII; los textos visibles pueden llevar acentos.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Dialogo de confirmacion: pregunta + [Si] [No]; dismiss(True/False).

    Teclas: y / s / enter -> Si (True); n / escape -> No (False). Tambien se
    puede hacer click en los botones. AUTO_FOCUS desactivado asi 'enter' lo
    maneja la pantalla (= Si) y no un boton enfocado por defecto.
    """

    AUTO_FOCUS = None

    BINDINGS = [
        Binding("y", "confirm", "Si", show=False),
        Binding("s", "confirm", "Si", show=False),
        Binding("enter", "confirm", "Si", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "No", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._question, id="confirm-question")
            with Horizontal(id="confirm-actions"):
                yield Button("Si  (y)", variant="error", id="confirm-yes")
                yield Button("No  (n)", variant="primary", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
