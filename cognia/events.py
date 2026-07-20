# -*- coding: utf-8 -*-
"""Bus de eventos interno de Cognia (pub/sub en proceso).

Gap detectado en el inventario 2026-07-14: los subsistemas de cognia/ se
comunican SOLO por llamadas directas y callbacks (print_fn/confirm); el
único bus existente (coordinator/event_bus.py) es WebSocket y vive en la
capa swarm. Este módulo es la infraestructura "Agent Reach" nativa: permite
que agent loop, oficina, analytics, notifications y tools se observen entre
sí SIN acoplarse (el emisor no conoce a los suscriptores y un suscriptor
roto jamás rompe al emisor).

Diseño mínimo deliberado (regla del repo: nada de frameworks):
- síncrono e in-proc (el CLI es sync; nada de hilos ni async acá),
- thread-safe (los reminders y la oficina disparan desde hilos daemon),
- historial acotado en memoria para depurar (/agente estado, oficina),
- wildcard "*" para observadores transversales (analytics, oficina),
- cero persistencia: quien quiera persistir se suscribe y guarda lo suyo.

Uso:
    from cognia.events import emit, subscribe
    subscribe("tool.ejecutada", lambda ev: print(ev["nombre"]))
    emit("tool.ejecutada", nombre="generar_codigo", ok=True)

Convención de nombres: "area.accion" en minúsculas (tool.ejecutada,
agente.paso, meta.creada, recordatorio.disparado, modelo.cargado, ...).
"""
import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

_HISTORIAL_MAX = 200


class EventBus:
    """Pub/sub mínimo, thread-safe, con historial acotado."""

    def __init__(self, historial_max: int = _HISTORIAL_MAX):
        self._lock = threading.RLock()
        self._subs: dict = {}          # evento -> list[callable]
        self._historial = deque(maxlen=historial_max)

    def subscribe(self, evento: str, callback) -> None:
        """Registra callback(dict_evento). "*" recibe todos los eventos."""
        if not callable(callback):
            raise TypeError("callback debe ser callable")
        with self._lock:
            self._subs.setdefault(evento, [])
            if callback not in self._subs[evento]:
                self._subs[evento].append(callback)

    def unsubscribe(self, evento: str, callback) -> None:
        with self._lock:
            try:
                self._subs.get(evento, []).remove(callback)
            except ValueError:
                pass

    def emit(self, evento: str, **datos) -> dict:
        """Publica el evento. Los callbacks corren en el hilo del emisor;
        un suscriptor que lanza NO rompe al emisor ni al resto (se loguea).
        Devuelve el dict del evento (útil para tests)."""
        ev = {"evento": evento, "ts": time.time(), **datos}
        with self._lock:
            self._historial.append(ev)
            # copia: un callback puede (de)suscribir durante la emisión
            callbacks = list(self._subs.get(evento, [])) + \
                list(self._subs.get("*", []))
        for cb in callbacks:
            try:
                cb(ev)
            except Exception:
                logger.warning("[events] suscriptor de %r falló", evento,
                               exc_info=True)
        return ev

    def historial(self, evento: str = None, n: int = 50) -> list:
        """Últimos n eventos (del tipo pedido, o todos)."""
        with self._lock:
            evs = list(self._historial)
        if evento:
            evs = [e for e in evs if e["evento"] == evento]
        return evs[-n:]

    def limpiar(self) -> None:
        """Vacía suscriptores e historial (aislamiento de tests)."""
        with self._lock:
            self._subs.clear()
            self._historial.clear()


_bus = EventBus()


def get_bus() -> EventBus:
    """El bus del proceso (singleton módulo-nivel, como db_pool)."""
    return _bus


def subscribe(evento: str, callback) -> None:
    _bus.subscribe(evento, callback)


def unsubscribe(evento: str, callback) -> None:
    _bus.unsubscribe(evento, callback)


def emit(evento: str, **datos) -> dict:
    return _bus.emit(evento, **datos)
