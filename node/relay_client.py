"""
node/relay_client.py
====================
Cliente WebSocket que conecta al relay del coordinador para participar
en una inferencia distribuida real entre máquinas.

Diseño:
  - Corre en un hilo dedicado con su propio event loop
  - Expone una API síncrona al resto de Cognia (no rompe el código existente)
  - Se conecta al relay, procesa hidden states y retorna resultados

Protocolo:
  1. Cliente llama relay_client.run_inference(prompt) → str
  2. relay_client crea sesión en el coordinador
  3. Cada nodo en la ruta conecta WS /ws/relay/{session_id}/{shard_index}
  4. El hidden state viaja shard 0 → 1 → 2 → 3 → vuelve como texto
"""

import os
import json
import time
import asyncio
import threading
import queue
import urllib.request
from typing import Optional

import numpy as np

from node.shard_engine import (
    ShardEngine, encode_hidden_state, decode_hidden_state
)


COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "")
WS_TIMEOUT      = int(os.environ.get("SWARM_WS_TIMEOUT_S", "60"))


# ══════════════════════════════════════════════════════════════════════
# BRIDGE SYNC ↔ ASYNC
# ══════════════════════════════════════════════════════════════════════

class _AsyncBridge:
    """
    Corre un event loop asyncio en un hilo de fondo.
    Permite llamar código async desde código síncrono.
    """

    def __init__(self):
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread]          = None
        self._ready   = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="cognia-relay-loop"
        )
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def run(self, coro) -> any:
        """Ejecuta una coroutine desde código síncrono y espera el resultado."""
        if not self._loop:
            self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=WS_TIMEOUT)

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# Singleton del bridge
_bridge = _AsyncBridge()


# ══════════════════════════════════════════════════════════════════════
# RELAY CLIENT
# ══════════════════════════════════════════════════════════════════════

class RelayClient:
    """
    Gestiona la participación de este nodo en inferencias distribuidas
    vía el relay WebSocket del coordinador.

    Dos modos:
      PARTICIPANT  — este nodo tiene un shard y procesa hidden states
      INITIATOR    — este nodo inicia la inferencia (puede tener shard 0
                     o ninguno — solo coordina el pipeline)
    """

    def __init__(self, coordinator_url: str, engine: Optional[ShardEngine],
                 shard_index: int):
        self.coordinator = coordinator_url.rstrip("/")
        self.engine      = engine
        self.shard_index = shard_index
        self._bridge     = _bridge
        self._bridge.start()

    # ── API síncrona pública ──────────────────────────────────────────

    def run_inference(self, initial_hidden: np.ndarray,
                      max_tokens: int = 200) -> dict:
        """
        Ejecuta una inferencia completa a través del swarm.
        Llamada síncrona — bloquea hasta obtener el resultado.

        Args:
            initial_hidden: (1, hidden_dim) float16 — embedding inicial
            max_tokens:     máximo de tokens a generar

        Returns:
            {ok, hidden_states: List[np.ndarray], latency_ms, tokens}
        """
        return self._bridge.run(
            self._async_run_inference(initial_hidden, max_tokens)
        )

    def join_as_participant(self, session_id: str) -> dict:
        """
        Une este nodo al relay de una sesión activa como participante.
        El nodo procesa hidden states que llegan y los reenvía.
        Llamada síncrona — retorna cuando la sesión termina.
        """
        return self._bridge.run(
            self._async_participant(session_id)
        )

    # ── Implementación async ──────────────────────────────────────────

    async def _async_run_inference(self, initial_hidden: np.ndarray,
                                    max_tokens: int) -> dict:
        """Orquesta el pipeline completo de inferencia."""
        t0 = time.perf_counter()

        # 1. Crear sesión
        try:
            session = await self._post_async(
                f"{self.coordinator}/api/session/create",
                {"model_name": "llama-3.2-3b-q4"},
            )
            session_id = session["session_id"]
            n_shards   = session["n_shards"]
        except Exception as e:
            return {"ok": False, "error": f"No se pudo crear sesión: {e}"}

        # 2. Obtener ruta
        try:
            route = await self._get_async(
                f"{self.coordinator}/api/swarm/route?model_name=llama-3.2-3b-q4"
            )
            if not route.get("ok"):
                return {"ok": False, "error": route.get("error", "swarm no listo")}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo obtener ruta: {e}"}

        # 3. Ejecutar tokens
        hidden        = initial_hidden
        all_outputs   = []
        tokens_done   = 0

        for _ in range(max_tokens):
            hidden, success = await self._forward_one_token(
                hidden, session_id, n_shards
            )
            if not success:
                break
            all_outputs.append(hidden.copy())
            tokens_done += 1
            # EOS simple: si el primer elemento es muy negativo, parar
            if float(hidden.flatten()[0]) < -10.0:
                break

        latency = (time.perf_counter() - t0) * 1000
        return {
            "ok":            True,
            "hidden_states": all_outputs,
            "latency_ms":    round(latency, 1),
            "tokens":        tokens_done,
            "session_id":    session_id,
        }

    async def _forward_one_token(self, hidden: np.ndarray,
                                  session_id: str, n_shards: int) -> tuple:
        """
        Envía un hidden state por todos los shards del relay.
        Retorna (hidden_out, success).

        Conecta al relay como shard -1 (initiator): envía al shard 0
        y espera el resultado del último shard que se reenvía al shard 0
        via `send_to_client` del relay.
        """
        try:
            import websockets
        except ImportError:
            # Sin websockets: fallback a local si hay engines registrados
            return await self._forward_local(hidden)

        ws_url = (f"{self.coordinator.replace('http','ws')}"
                  f"/ws/relay/{session_id}/0")
        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                # Enviar hidden state al shard 0
                wire = encode_hidden_state(0, 0, hidden)
                await ws.send(wire)

                # Esperar resultado del último shard (vuelve al shard 0)
                result_bytes = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                if isinstance(result_bytes, bytes):
                    _, _, hidden_out = decode_hidden_state(result_bytes)
                    return hidden_out, True
                return hidden, False

        except Exception as e:
            # Fallback a local si el relay falla
            return await self._forward_local(hidden)

    async def _forward_local(self, hidden: np.ndarray) -> tuple:
        """Fallback: usa engines locales registrados en inference_pipeline."""
        from node.inference_pipeline import _LOCAL_ENGINES
        if not _LOCAL_ENGINES:
            return hidden, False
        for engine in _LOCAL_ENGINES:
            wire = encode_hidden_state(
                engine.config.shard_index, engine.config.n_layers, hidden
            )
            out_wire, _ = engine.process_bytes(wire)
            _, _, hidden = decode_hidden_state(out_wire)
        return hidden, True

    async def _async_participant(self, session_id: str) -> dict:
        """
        El nodo se une al relay como participante con su shard_index.
        Procesa todos los hidden states que recibe hasta que la sesión cierra.
        """
        if not self.engine:
            return {"ok": False, "error": "sin engine local"}

        try:
            import websockets
        except ImportError:
            return {"ok": False, "error": "librería 'websockets' no instalada"}

        ws_url = (f"{self.coordinator.replace('http','ws')}"
                  f"/ws/relay/{session_id}/{self.shard_index}")
        processed = 0
        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                async for message in ws:
                    if isinstance(message, bytes):
                        out_bytes, ms = self.engine.process_bytes(message)
                        await ws.send(out_bytes)
                        processed += 1
            return {"ok": True, "processed": processed}
        except Exception as e:
            return {"ok": False, "error": str(e), "processed": processed}

    # ── HTTP helpers async ────────────────────────────────────────────

    async def _post_async(self, url: str, body: dict) -> dict:
        import json as _json
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _http_post_sync(url, body))

    async def _get_async(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _http_get_sync(url))


# ── HTTP sync helpers ─────────────────────────────────────────────────

def _http_post_sync(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _http_get_sync(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


# ══════════════════════════════════════════════════════════════════════
# LISTENER DE SESIONES ENTRANTES
# ══════════════════════════════════════════════════════════════════════

class SessionListener:
    """
    Escucha notificaciones del coordinador de nuevas sesiones de inferencia
    donde este nodo está en la ruta, y se une automáticamente al relay.

    El coordinador notifica vía polling o WebSocket de notificación.
    Esta implementación usa polling liviano cada 2 segundos.
    """

    def __init__(self, coordinator_url: str, node_id: str,
                 relay_client: RelayClient):
        self.coordinator  = coordinator_url.rstrip("/")
        self.node_id      = node_id
        self.relay_client = relay_client
        self._stop        = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_sessions: set = set()

    def start(self):
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="cognia-session-listener"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _poll_loop(self):
        while not self._stop.wait(2.0):
            try:
                self._check_pending_sessions()
            except Exception:
                pass

    def _check_pending_sessions(self):
        """
        Consulta si hay sesiones pendientes donde este nodo debe participar.
        El coordinador expone /api/node/{node_id}/pending_sessions.
        """
        url = f"{self.coordinator}/api/node/{self.node_id}/pending_sessions"
        try:
            result = _http_get_sync(url)
            for session_id in result.get("sessions", []):
                if session_id not in self._active_sessions:
                    self._active_sessions.add(session_id)
                    t = threading.Thread(
                        target=self._join_session,
                        args=(session_id,),
                        daemon=True,
                    )
                    t.start()
        except Exception:
            pass

    def _join_session(self, session_id: str):
        result = self.relay_client.join_as_participant(session_id)
        self._active_sessions.discard(session_id)
