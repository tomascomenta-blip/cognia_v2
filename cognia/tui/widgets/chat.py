"""
chat.py -- Vista de chat de la TUI de Cognia (historial + input + worker).

Que: ChatView es una vista usable de conversacion: un area de mensajes
scrollable arriba (burbujas usuario / asistente / sistema con colores distintos
de la paleta) y un Input abajo. Al Enter, agrega el mensaje del usuario, limpia
el input, muestra "Cognia esta pensando..." y lanza un WORKER en un hilo
(@work(thread=True)) que llama a CogniaBackend.respond; cuando vuelve, agrega la
respuesta y quita el indicador.

Por que: la generacion del backend (llama.cpp en CPU, varios segundos) NUNCA
debe correr en el hilo de la UI -- lo haria congelarse. El worker-thread mantiene
la TUI fluida; el resultado se devuelve al hilo de la UI via call_from_thread
(unico lugar seguro para tocar widgets). El backend se carga PEREZOSAMENTE en el
worker (no en el boot), asi el arranque es instantaneo.

El empty-state inicial conserva el texto "Sin conversacion todavia" (lo verifica
test_tui_foundation) y agrega la pista de accion para empezar a hablar.
"""

from __future__ import annotations

from typing import List, Optional

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static

from ..backend import CogniaBackend
from ..theme import COLORS

# Prefijo (etiqueta) y color por rol del mensaje. usuario / asistente / sistema.
_ROLE_LABEL = {
    "user":      "Tu",
    "assistant": "Cognia",
    "system":    "Sistema",
}
_ROLE_COLOR = {
    "user":      COLORS["info"],    # azul
    "assistant": COLORS["accent"],  # violeta (identidad Cognia)
    "system":    COLORS["warn"],    # amarillo (aviso / backend no disponible)
}

# Un mensaje del backend que empieza asi es un fallo controlado, no una
# respuesta real: se muestra como mensaje de SISTEMA (color warn), no asistente.
_UNAVAILABLE_PREFIX = "[backend no disponible"


class ChatView(Vertical):
    """Vista de chat: historial scrollable + indicador + input, con worker."""

    def __init__(self, backend: Optional[CogniaBackend] = None) -> None:
        super().__init__(id="chat", classes="view")
        self.border_title = "Chat"
        # Backend real (carga perezosa en el primer respond()); inyectable en tests.
        self.backend = backend if backend is not None else CogniaBackend()
        # Historial plano de mensajes mostrados (fuente de verdad para los tests
        # y para history_text(); independiente del montaje async de las burbujas).
        self._messages: List[dict] = []
        self._empty_hidden = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-messages"):
            yield Static(self._build_empty(), id="chat-empty", classes="empty-state")
        yield Static("", id="chat-thinking", classes="hidden")
        yield Input(placeholder="Escribi tu mensaje...", id="chat-input")

    # -- API de lectura (tests / UI) --------------------------------------

    def history_text(self) -> str:
        """Texto plano de todo el historial mostrado (un mensaje por linea)."""
        return "\n".join(f"{m['role']}: {m['text']}" for m in self._messages)

    def last_message_role(self) -> Optional[str]:
        """Rol del ultimo mensaje mostrado (user / assistant / system), o None."""
        return self._messages[-1]["role"] if self._messages else None

    # -- entrada del usuario ----------------------------------------------

    @on(Input.Submitted, "#chat-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        """Enter en el input: muestra el mensaje del usuario y lanza el worker."""
        text = event.value.strip()
        if not text:
            return
        inp = self.query_one("#chat-input", Input)
        inp.value = ""
        self._add_message("user", text)
        self._set_thinking(True)
        # Worker en un HILO: la generacion (segundos en CPU) no bloquea la UI.
        self._run_backend(text)

    @work(thread=True)
    def _run_backend(self, message: str) -> None:
        """Worker-thread: pide la respuesta al backend (puede bloquear) y la
        entrega al hilo de la UI via call_from_thread (no toca widgets aca)."""
        try:
            reply = self.backend.respond(message)
        except Exception as exc:  # respond ya atrapa todo; defensa extra
            reply = f"{_UNAVAILABLE_PREFIX}: {type(exc).__name__}: {exc}]"
        self.app.call_from_thread(self._show_reply, reply)

    def _show_reply(self, reply: str) -> None:
        """Corre en el hilo de la UI: agrega la respuesta y quita el indicador."""
        self._set_thinking(False)
        role = "system" if reply.startswith(_UNAVAILABLE_PREFIX) else "assistant"
        self._add_message(role, reply)

    # -- render del historial ---------------------------------------------

    def _add_message(self, role: str, text: str) -> None:
        """Agrega una burbuja al historial, oculta el empty-state y auto-scrollea."""
        self._hide_empty_state()
        self._messages.append({"role": role, "text": text})
        bubble = Static(self._build_bubble(role, text), classes=f"msg msg-{role}")
        container = self.query_one("#chat-messages", VerticalScroll)
        container.mount(bubble)
        container.scroll_end(animate=False)

    def _set_thinking(self, active: bool) -> None:
        """Muestra/oculta el indicador 'Cognia esta pensando...'."""
        indicator = self.query_one("#chat-thinking", Static)
        if active:
            indicator.update(self._build_thinking())
            indicator.remove_class("hidden")
        else:
            indicator.update("")
            indicator.add_class("hidden")

    def _hide_empty_state(self) -> None:
        if self._empty_hidden:
            return
        try:
            self.query_one("#chat-empty", Static).add_class("hidden")
        except Exception:
            pass
        self._empty_hidden = True

    # -- renderables (Rich Text con la paleta semantica) ------------------

    @staticmethod
    def _build_bubble(role: str, text: str) -> Text:
        label = _ROLE_LABEL.get(role, role)
        color = _ROLE_COLOR.get(role, COLORS["text"])
        body_color = COLORS["warn"] if role == "system" else COLORS["text"]
        out = Text(no_wrap=False)
        out.append(f"{label}  ", style=f"bold {color}")
        out.append(text, style=body_color)
        return out

    @staticmethod
    def _build_thinking() -> Text:
        out = Text()
        out.append("Cognia esta pensando...", style=f"italic {COLORS['muted']}")
        return out

    @staticmethod
    def _build_empty() -> Text:
        out = Text(justify="center")
        out.append("[ ]\n\n", style=f"bold {COLORS['accent']}")
        out.append("Sin conversacion todavia\n", style=f"bold {COLORS['text']}")
        out.append("Escribi para empezar a hablar con Cognia", style=COLORS["muted"])
        return out
