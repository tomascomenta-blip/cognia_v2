"""
coordinator/event_bus.py
========================
Event bus para broadcast de eventos de red a suscriptores WebSocket.

Eventos soportados:
  node_joined        — nodo registrado en el swarm
  node_left          — nodo desconectado (voluntario o por timeout)
  shard_available    — shard cubierto por al menos un nodo
  shard_unavailable  — shard sin cobertura activa
  inference_started  — sesion de inferencia iniciada
  inference_done     — sesion de inferencia finalizada
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class CoordinatorEventBus:
    """Broadcast de eventos de red a suscriptores WebSocket."""

    def __init__(self, history_size: int = 50):
        self._subscribers: Set[WebSocket] = set()
        self._history: deque = deque(maxlen=history_size)
        self._lock = asyncio.Lock()
        # Cache of running loop for publish_sync
        self._loop: asyncio.AbstractEventLoop | None = None

    async def subscribe(self, ws: WebSocket) -> None:
        """Acepta el websocket, lo registra y le envía el historial actual."""
        await ws.accept()
        async with self._lock:
            self._subscribers.add(ws)
            history_snapshot = list(self._history)

        # Replay history to the new subscriber so it is immediately up to date.
        for event in history_snapshot:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                # If it fails during replay just continue; it will be cleaned up
                # on the next publish.
                break

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Remueve el websocket de la lista de suscriptores."""
        async with self._lock:
            self._subscribers.discard(ws)

    async def publish(self, event_type: str, data: dict) -> None:
        """
        Publica un evento a todos los suscriptores.
        Guarda en history y broadcastea; los suscriptores caidos se remueven.
        """
        event = {"type": event_type, "data": data, "ts": time.time()}
        payload = json.dumps(event)

        async with self._lock:
            self._history.append(event)
            current_subs = set(self._subscribers)

        dead: list[WebSocket] = []
        for ws in current_subs:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers.discard(ws)

        logger.debug("[EventBus] %s -> %d subs (%d dead)", event_type,
                     len(current_subs) - len(dead), len(dead))

    def publish_sync(self, event_type: str, data: dict) -> None:
        """
        Version sincrona de publish(). Llama desde codigo no-async.

        Si hay un loop asyncio corriendo, encola la coroutine en ese loop
        (fire-and-forget, no bloquea). Si no hay loop, guarda en history
        pero no broadcastea (best-effort).
        """
        event = {"type": event_type, "data": data, "ts": time.time()}

        # Always store in history synchronously (deque is not thread-safe but
        # coordinator runs in a single process — GIL provides enough protection
        # for simple append/read operations between an async context and a sync
        # callback that runs in the same thread).
        self._history.append(event)

        # Try to schedule the broadcast on the running loop.
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                self._broadcast_event(event), loop
            )
        except RuntimeError:
            # No running loop — broadcast skipped, event already in history.
            pass

    async def _broadcast_event(self, event: dict) -> None:
        """Internal: broadcast a pre-built event dict to current subscribers."""
        payload = json.dumps(event)
        async with self._lock:
            current_subs = set(self._subscribers)

        dead: list[WebSocket] = []
        for ws in current_subs:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers.discard(ws)

    def get_history(self) -> list:
        return list(self._history)


# Singleton global
_bus = CoordinatorEventBus()


def get_event_bus() -> CoordinatorEventBus:
    return _bus
