"""
modals.py -- Modales (pantallas flotantes) de la TUI de Cognia.

Que: ConfirmModal es un ModalScreen[bool] centrado: muestra una pregunta y dos
botones [<accion>] [No]. Devuelve su resultado por dismiss(bool): True si el
usuario confirma, False si cancela. Navegable 100% por teclado (y=si, n/esc=no,
enter=el boton enfocado) ademas de click.

El boton de confirmar lleva el NOMBRE de la accion ("Salir", "Limpiar"), no un
"Si" generico: quien llama pasa `confirmar=`. Un "Si" no dice que va a pasar y
en el dialogo de salida el usuario tiene que deducirlo de la pregunta.

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
    """Dialogo de confirmacion: pregunta + [<accion>] [No]; dismiss(True/False).

    Teclas: y / s / enter -> confirmar (True); n / escape -> No (False). Tambien
    se puede hacer click en los botones. AUTO_FOCUS desactivado asi 'enter' lo
    maneja la pantalla (= confirmar) y no un boton enfocado por defecto.
    """

    # "" y no None: `None` NO desactiva el auto-foco, lo DELEGA. Textual hace
    # `self.app.AUTO_FOCUS if self.AUTO_FOCUS is None else self.AUTO_FOCUS`
    # (screen.py:1493) y App.AUTO_FOCUS es "*", asi que con None la pantalla
    # enfocaba el PRIMER boton -- el destructivo. Se veia en el render: el boton
    # de salir salia con el `background-tint: $foreground 5%` del :focus de
    # Button (#1c2330 -> #262d39, 12.631 px2) mientras el otro quedaba plano.
    # O sea: la accion peligrosa venia preseleccionada y con mas peso visual,
    # justo lo contrario de lo que dice el comentario que estaba aca. La cadena
    # vacia es falsy y corta el `if auto_focus` sin enfocar nada.
    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("y", "confirm", "Si", show=False),
        Binding("s", "confirm", "Si", show=False),
        Binding("enter", "confirm", "Si", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "No", show=False),
    ]

    # Etiqueta por defecto del boton de confirmar cuando quien llama no pasa una.
    ACCION_POR_DEFECTO = "Si"

    def __init__(self, question: str, confirmar: str = ACCION_POR_DEFECTO) -> None:
        super().__init__()
        self._question = question
        self._confirmar = confirmar or self.ACCION_POR_DEFECTO

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._question, id="confirm-question")
            with Horizontal(id="confirm-actions"):
                # JERARQUIA (2026-08-17, tercera pasada): NINGUN boton lleva
                # bloque de color, y el destructivo se nombra y se pinta como lo
                # que es.
                #
                # Historia de las dos vueltas anteriores: primero el bloque de
                # neon #7DE62A estaba en 'No' (el boton que no hace nada) y 'Si'
                # era un bloque rojo -- dos masas compitiendo, la mas grande en
                # la accion inocua. Despues el acento se mudo a 'Si': una sola
                # masa, pero PUESTA EN "CERRAR LA APP", con el color que en todo
                # el resto del producto significa ok / Listo / success.
                #
                # Ahora los dos botones son el mismo boton (fondo del dialogo,
                # contorno `tall`, sin variant): el peso es identico y no hay
                # ningun default anunciado -- correcto, porque 'enter' confirma
                # y un 'No' pesado mentiria. Lo unico que los distingue es el
                # color: $error en el destructivo (4.70:1 sobre el dialogo) y
                # $foreground en el seguro (13.34:1). El color va en el TEXTO y
                # en el contorno, no en un bloque, asi que el dialogo queda sin
                # una sola masa de color. Los estilos estan en app.tcss
                # (#confirm-yes / #confirm-no).
                yield Button(f"{self._confirmar}  (y)", id="confirm-yes")
                yield Button("No  (n)", id="confirm-no")
            # QUE HACE ENTER (2026-08-17, cuarta pasada). Las tres vueltas
            # anteriores discutieron DONDE poner el peso visual y terminaron
            # bien: ningun boton preseleccionado, porque marcar uno mentiria
            # sobre lo que hace el teclado. Pero al quitar el default visual
            # quedo un dialogo donde 'enter' confirma y NADA en pantalla lo
            # dice -- el usuario tiene que probarlo en un dialogo cuya accion
            # es cerrar la app. Se dice con TEXTO y no con peso: una linea
            # tenue centrada no le da masa a ningun boton, asi que la jerarquia
            # de la tercera pasada queda intacta y el default deja de ser
            # invisible. Nombra las tres teclas que el BINDINGS de arriba
            # declara, en el orden en que se usan.
            yield Static("enter confirma · n o esc cancela", id="confirm-hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
