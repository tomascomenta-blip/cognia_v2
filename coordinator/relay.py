"""
coordinator/relay.py
====================
WebSocket relay de hidden states entre nodos.

Problema: los nodos están detrás de NAT, no pueden recibir
conexiones directas entre sí. El coordinador actúa de intermediario.

Flujo por sesión:
  1. Nodo 0 inicia sesión → recibe session_id
  2. Nodo 0 conecta WS /ws/relay/{session_id}/0
  3. Nodo 1 conecta WS /ws/relay/{session_id}/1
  4. ...
  5. Nodo 0 envía hidden state → coordinador lo reenvía a Nodo 1
  6. Nodo 1 procesa → envía a Nodo 2
  7. Último nodo envía resultado final → vuelve al cliente

El coordinador solo retransmite bytes — no lee ni modifica el contenido.
"""

import asyncio
import logging
import uuid
import time
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Gauge as _PGauge
    _RELAY_SESSIONS = _PGauge("relay_sessions_active", "Active relay inference sessions")
except ImportError:
    _RELAY_SESSIONS = None

# Per-token inference timeout (seconds): how long the HTTP /infer endpoint waits
# for the last shard to return a result before giving up.
INFER_TIMEOUT_S = 60


# ══════════════════════════════════════════════════════════════════════
# SESIÓN DE INFERENCIA
# ══════════════════════════════════════════════════════════════════════

class InferenceSession:
    """
    Mantiene los WebSockets activos de una sesión de inferencia.
    Los nodos se conectan por su índice en la ruta (0, 1, 2, ...).
    """

    SESSION_TIMEOUT = 120   # segundos

    def __init__(self, session_id: str, n_shards: int):
        self.session_id  = session_id
        self.n_shards    = n_shards
        self.sockets:  Dict[int, WebSocket] = {}   # shard_index → websocket
        self.created_at  = time.time()
        self._lock       = asyncio.Lock()
        # Result capture for the HTTP /infer endpoint
        self.result_data:  Optional[bytes]  = None
        self.result_ready: asyncio.Event    = asyncio.Event()
        # Error recovery: set when a shard disconnects mid-pipeline
        self.failed:      bool = False
        self.fail_reason: str  = ""

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.SESSION_TIMEOUT

    def is_complete(self) -> bool:
        return len(self.sockets) == self.n_shards

    async def connect(self, shard_index: int, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.sockets[shard_index] = ws

    async def disconnect(self, shard_index: int):
        async with self._lock:
            self.sockets.pop(shard_index, None)

    async def forward(self, from_shard: int, data: bytes):
        """Forward processed hidden state to the next shard in the pipeline."""
        next_shard = from_shard + 1
        async with self._lock:
            target = self.sockets.get(next_shard)
        if target:
            await target.send_bytes(data)

    async def send_to_shard0(self, data: bytes) -> bool:
        """
        Send initial hidden state to shard 0 to kick off a pipeline pass.
        Called by the HTTP /infer endpoint after all shards have connected.
        Returns False if shard 0 is not connected.
        """
        async with self._lock:
            shard0 = self.sockets.get(0)
        if shard0:
            await shard0.send_bytes(data)
            return True
        return False

    async def send_to_client(self, data: bytes):
        """
        Called by the last shard when it finishes processing.
        Stores the result and signals the waiting HTTP /infer endpoint.
        (Previously this looped back to shard 0, which was incorrect.)
        """
        self.result_data = data
        self.result_ready.set()

    def reset_result(self):
        """Clear result state between tokens in an autoregressive loop."""
        self.result_data = None
        self.result_ready.clear()
        self.failed      = False
        self.fail_reason = ""

    def mark_failed(self, reason: str = "") -> None:
        """
        Signal a relay failure so that HTTP /infer callers fail fast
        instead of waiting for the full INFER_TIMEOUT_S.

        Safe to call multiple times (only the first call takes effect).
        Wakes up any coroutine waiting on result_ready.
        """
        if not self.failed:
            self.failed      = True
            self.fail_reason = reason
            self.result_ready.set()   # unblock waiting HTTP callers immediately
            logger.warning("[Relay] session=%s FAILED: %s", self.session_id, reason)


# ══════════════════════════════════════════════════════════════════════
# GESTOR DE SESIONES
# ══════════════════════════════════════════════════════════════════════

class RelayManager:

    def __init__(self):
        self._sessions: Dict[str, InferenceSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    def start_cleanup(self):
        """Start the background cleanup loop. Call once from the FastAPI lifespan."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(30)
            async with self._lock:
                self._purge_expired()

    def cancel(self):
        """Cancel the background task on application shutdown."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

    async def create_session(self, n_shards: int) -> str:
        session_id = uuid.uuid4().hex[:16]
        async with self._lock:
            self._purge_expired()
            self._sessions[session_id] = InferenceSession(session_id, n_shards)
            if _RELAY_SESSIONS is not None:
                _RELAY_SESSIONS.set(len(self._sessions))
        return session_id

    async def get_session(self, session_id: str) -> Optional[InferenceSession]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_session(self, session_id: str):
        async with self._lock:
            self._sessions.pop(session_id, None)

    def _purge_expired(self):
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]
        if _RELAY_SESSIONS is not None:
            _RELAY_SESSIONS.set(len(self._sessions))

    def active_sessions(self) -> int:
        return len(self._sessions)


# Singleton global
relay_manager = RelayManager()


# ══════════════════════════════════════════════════════════════════════
# HANDLER DE WEBSOCKET
# ══════════════════════════════════════════════════════════════════════

async def handle_relay_ws(websocket: WebSocket,
                          session_id: str,
                          shard_index: int):
    """
    Handler para WS /ws/relay/{session_id}/{shard_index}.

    Cada nodo conecta con su índice en la ruta.
    Cuando recibe datos, los reenvía al siguiente nodo de la cadena.
    El último nodo los reenvía al nodo 0 (quien los devuelve al cliente).

    Security: session_id must exist and shard_index must be within bounds.
    An attacker who does not know the session_id cannot inject data.
    Session IDs are 16-byte random hex (uuid4), providing ~64 bits of entropy.
    """
    # Validate session_id format: exactly 32 hex chars (uuid4.hex[:16] → 16 hex)
    # Accept 8-32 hex chars to be forward-compatible with longer IDs.
    import re as _re
    if not _re.fullmatch(r"[0-9a-f]{8,64}", session_id):
        await websocket.close(code=4003, reason="session_id inválido")
        return

    session = await relay_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="session_id inválido o expirado")
        return

    # Reject out-of-bounds shard indices to prevent hijacking result capture.
    if shard_index < 0 or shard_index >= session.n_shards:
        await websocket.close(code=4003,
                              reason=f"shard_index fuera de rango [0, {session.n_shards - 1}]")
        return

    # Reject a second connection for the same shard slot to prevent slot hijacking.
    if shard_index in session.sockets:
        await websocket.close(code=4003, reason="shard_index ya conectado")
        return

    await session.connect(shard_index, websocket)
    logger.info("[Relay] shard=%d connected  session=%s  (%d/%d shards)",
                shard_index, session_id, len(session.sockets), session.n_shards)

    try:
        while True:
            data = await websocket.receive_bytes()

            is_last = (shard_index == session.n_shards - 1)
            if is_last:
                await session.send_to_client(data)
            else:
                await session.forward(shard_index, data)

    except WebSocketDisconnect:
        logger.warning("[Relay] shard=%d disconnected  session=%s", shard_index, session_id)
        await session.disconnect(shard_index)
        session.mark_failed(f"shard {shard_index} disconnected")

    except Exception as exc:
        logger.error("[Relay] shard=%d error  session=%s  exc=%s", shard_index, session_id, exc)
        await session.disconnect(shard_index)
        session.mark_failed(f"shard {shard_index} error: {exc}")
