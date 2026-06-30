"""
backend.py -- Adaptador del backend REAL de inferencia para la TUI de Cognia.

Que: CogniaBackend envuelve el backend llama.cpp (node/llama_backend.py:
LlamaBackend.try_load) detras de una API minima y SINCRONA (respond /
respond_stream) pensada para llamarse desde un worker-thread de Textual. La
carga del modelo es PEREZOSA: nada pesado ocurre en __init__, asi el arranque
de la TUI es instantaneo; el GGUF/llama-server se construye la PRIMERA vez que
se pide una respuesta.

Por que: la vista de chat necesita respuestas reales sin acoplarse a la
maquinaria del REPL (cognia/cli.py) ni al ShatteringOrchestrator (que NO carga
en sandbox). El path elegido es LlamaBackend.try_load() + stream_chat: carga
DIRECTA, multi-turno (la plantilla Qwen la aplica llama-server), y nunca levanta
excepcion (try_load devuelve None si no hay GGUF ni runtime).

Robustez: TODO esta envuelto en try/except y cualquier fallo se traduce a un
string "[backend no disponible: <razon>]" -- el chat de la TUI nunca debe
crashear por un fallo del backend.
"""

from __future__ import annotations

import threading
from typing import Iterator, List, Optional

# Tope de tokens por turno y nro de mensajes de historial reenviados al modelo.
# Mismos valores que el fast-path del REPL (cognia/cli.py): 1024 tokens y los
# ultimos 8 turnos (16 mensajes) para acotar el tamano del prompt.
_MAX_TOKENS = 1024
_HISTORY_MESSAGES = 16


class CogniaBackend:
    """Adaptador perezoso del backend real de inferencia (llama.cpp)."""

    def __init__(self) -> None:
        self._backend = None            # LlamaBackend | None, una vez resuelto
        self._loaded = False            # True tras el primer intento de carga
        self._status = "sin cargar"     # texto humano del estado actual
        self._reason = ""               # razon si no esta disponible
        self._lock = threading.Lock()   # carga thread-safe (worker concurrente)
        self._history: List[dict] = []  # turnos previos (multi-turno)

    # -- estado -----------------------------------------------------------

    def is_ready(self) -> bool:
        """True si el backend real ya esta cargado y disponible."""
        return self._backend is not None

    @property
    def status(self) -> str:
        """Texto humano del estado del backend (para mostrar en la UI)."""
        return self._status

    # -- carga perezosa ---------------------------------------------------

    def ensure_loaded(self) -> bool:
        """Carga el backend la PRIMERA vez (idempotente, thread-safe).

        Devuelve True si quedo disponible. No levanta: cualquier fallo deja
        self._backend en None y registra la razon en self._reason / _status.
        Pensado para llamarse desde un worker-thread (la construccion del
        GGUF / arranque de llama-server puede tardar varios segundos).
        """
        if self._loaded:
            return self._backend is not None
        with self._lock:
            if self._loaded:
                return self._backend is not None
            self._loaded = True
            try:
                from node.llama_backend import LlamaBackend
                self._status = "cargando modelo..."
                backend = LlamaBackend.try_load()
                if backend is None:
                    self._reason = "no se encontro GGUF ni runtime llama.cpp"
                    self._status = "no disponible"
                    self._backend = None
                else:
                    self._backend = backend
                    self._status = "listo"
            except Exception as exc:  # nunca propagar: el chat no debe crashear
                self._reason = f"{type(exc).__name__}: {exc}"
                self._status = "no disponible"
                self._backend = None
        return self._backend is not None

    # -- generacion -------------------------------------------------------

    def respond(self, message: str) -> str:
        """Respuesta COMPLETA y SINCRONA al mensaje (se llama desde un worker).

        Carga el backend perezosamente. Si no esta disponible (o la generacion
        falla / vuelve vacia), devuelve un string "[backend no disponible:
        <razon>]" en vez de levantar -- el caller lo muestra como mensaje de
        sistema, sin crashear la TUI.
        """
        try:
            if not self.ensure_loaded():
                return f"[backend no disponible: {self._reason or self._status}]"
            tokens = list(self._stream(message))
            text = "".join(tokens).strip()
            if not text:
                return "[backend no disponible: respuesta vacia del modelo]"
            self._record_turn(message, text)
            return text
        except Exception as exc:
            return f"[backend no disponible: {type(exc).__name__}: {exc}]"

    def respond_stream(self, message: str) -> Iterator[str]:
        """Itera los tokens de la respuesta (mejor UX). Carga perezosa.

        Si el backend no esta disponible emite un unico chunk
        "[backend no disponible: ...]" en vez de levantar. El turno se registra
        para el contexto multi-turno solo si se genero texto real.
        """
        try:
            if not self.ensure_loaded():
                yield f"[backend no disponible: {self._reason or self._status}]"
                return
            buf: List[str] = []
            for tok in self._stream(message):
                buf.append(tok)
                yield tok
            text = "".join(buf).strip()
            if text:
                self._record_turn(message, text)
        except Exception as exc:
            yield f"[backend no disponible: {type(exc).__name__}: {exc}]"

    # -- internos ---------------------------------------------------------

    def _stream(self, message: str) -> Iterator[str]:
        """Tokens del backend real via stream_chat (multi-turno).

        Arma el prompt como messages [system, ...historial, user] e itera los
        tokens. LlamaBackend.stream_chat usa /v1/chat/completions (plantilla
        Qwen oficial) cuando el impl lo soporta, y degrada a un prompt plano si
        no -- ambas ramas viven en node/llama_backend.py, aca no se duplica.
        """
        from shattering.model_constants import (
            COGNIA_SYSTEM_PROMPT, GEN_CHAT_TEMPERATURE,
        )
        messages = [{"role": "system", "content": COGNIA_SYSTEM_PROMPT}]
        messages.extend(self._history[-_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": message})
        backend = self._backend
        if hasattr(backend, "stream_chat"):
            yield from backend.stream_chat(
                messages, max_tokens=_MAX_TOKENS, temperature=GEN_CHAT_TEMPERATURE)
        else:
            # Fallback ultra-defensivo: un backend sin stream_chat ni stream_*.
            text = backend.generate(
                message, max_tokens=_MAX_TOKENS, temperature=GEN_CHAT_TEMPERATURE)
            if text:
                yield text

    def _record_turn(self, user_text: str, assistant_text: str) -> None:
        """Guarda el turno para dar contexto multi-turno al siguiente mensaje."""
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": assistant_text})
