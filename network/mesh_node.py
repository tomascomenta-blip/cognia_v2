"""
network/mesh_node.py
====================
Nodo COGNIA MESH — red distribuida de conocimiento entre instancias.

Fase 3 — Arquitectura distribuida sin coordinador central.

DISEÑO:
  - Transporte: asyncio + websockets (stdlib asyncio, websockets via pip)
  - Consistencia: CRDTKnowledgeGraph (convergencia eventual)
  - Privacidad: privatize_embedding + filter_shareable_triples
  - Episódico: NUNCA sale del dispositivo (Capa 1 PRIVADO)
  - Solo se comparte: triples de conocimiento (Capa 3) y
    embeddings con ruido diferencial (Capa 2)

DEPENDENCIAS:
  - asyncio (stdlib)
  - websockets (pip install websockets — único paquete nuevo, muy liviano)
  - json, hashlib, time (stdlib)
  - network.crdt_graph, network.privacy (propios)

FALLBACK:
  Si websockets no está instalado, el nodo funciona en modo LOCAL_ONLY
  (sin conectividad, pero sin romper el sistema).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import threading
from typing import Dict, List, Optional, Set, Callable

from network.crdt_graph import CRDTKnowledgeGraph
from network.privacy import (
    privatize_embedding,
    filter_shareable_triples,
    PrivacyLayer,
)
from logger_config import get_logger

logger = get_logger(__name__)

# ── Detección de websockets (opcional) ────────────────────────────────
try:
    import websockets
    import websockets.server
    import websockets.client
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning(
        "websockets no instalado — MeshNode en modo LOCAL_ONLY. "
        "Para activar la red: pip install websockets",
        extra={"op": "mesh_node.init", "context": "mode=local_only"},
    )

# ── Constantes ─────────────────────────────────────────────────────────
DEFAULT_PORT         = 7474          # puerto por defecto del nodo
SYNC_INTERVAL_S      = 60.0          # sincronización periódica con peers
FEDERATED_TIMEOUT_MS = 300           # timeout búsqueda federada
MAX_PEERS            = 20            # máximo de peers conectados
MSG_MAX_BYTES        = 512 * 1024    # 512 KB por mensaje


# ══════════════════════════════════════════════════════════════════════
# MENSAJES DEL PROTOCOLO
# ══════════════════════════════════════════════════════════════════════

def _make_msg(msg_type: str, node_id: str, payload: dict) -> str:
    """Serializa un mensaje del protocolo COGNIA MESH a JSON."""
    return json.dumps({
        "type":      msg_type,
        "node_id":   node_id,
        "timestamp": time.time(),
        "payload":   payload,
    }, ensure_ascii=False)


def _parse_msg(raw: str) -> Optional[dict]:
    """Parsea un mensaje recibido. Retorna None si es inválido."""
    try:
        msg = json.loads(raw)
        if not all(k in msg for k in ("type", "node_id", "payload")):
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════
# NODO MESH
# ══════════════════════════════════════════════════════════════════════

class CogniaMeshNode:
    """
    Nodo en la red COGNIA MESH.

    Responsabilidades
    -----------------
    - Publicar deltas de conocimiento (triples nuevos filtrados por privacidad).
    - Recibir y mergear conocimiento de peers vía CRDT.
    - Responder búsquedas federadas sin exponer memorias privadas.
    - Sincronización periódica automática.

    Modo LOCAL_ONLY
    ---------------
    Si websockets no está instalado, todas las operaciones de red son no-ops
    silenciosas. El CRDT local sigue funcionando normalmente.

    Uso
    ---
        node = CogniaMeshNode(node_id="mi-cognia", port=7474)
        node.start()                        # inicia servidor en background
        node.connect_peer("ws://otro:7474") # conectar a un peer
        node.publish_knowledge_delta(triples)
        resultados = node.federated_search(query_vec, k=5)
        node.stop()
    """

    def __init__(
        self,
        node_id:  Optional[str] = None,
        port:     int = DEFAULT_PORT,
        host:     str = "0.0.0.0",
        epsilon:  float = 1.0,
    ):
        # ID único del nodo (hash de hostname + pid si no se provee)
        if node_id is None:
            raw = f"{os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'cognia'))}-{os.getpid()}"
            node_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

        self.node_id  = node_id
        self.host     = host
        self.port     = port
        self.epsilon  = epsilon                        # presupuesto privacidad diferencial

        self.crdt     = CRDTKnowledgeGraph(node_id)   # grafo CRDT local
        self._peers:  Dict[str, str] = {}              # node_id → ws_uri
        self._last_sync: float       = 0.0
        self._running: bool          = False
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._thread:  Optional[threading.Thread]          = None

        # Callbacks externos (opcionales)
        self._on_knowledge_received: Optional[Callable[[List[dict]], None]] = None

        logger.info(
            f"CogniaMeshNode creado: id={node_id} port={port} "
            f"websockets={'OK' if HAS_WEBSOCKETS else 'LOCAL_ONLY'}",
            extra={"op": "mesh_node.__init__",
                   "context": f"id={node_id} port={port}"},
        )

    # ──────────────────────────────────────────────────────────────────
    # Ciclo de vida
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        """
        Inicia el servidor WebSocket en un thread daemon.
        No bloquea el hilo principal.
        En modo LOCAL_ONLY no hace nada de red.
        """
        if self._running:
            return
        self._running = True

        if not HAS_WEBSOCKETS:
            logger.info(
                "MeshNode.start(): modo LOCAL_ONLY (websockets no disponible)",
                extra={"op": "mesh_node.start", "context": "local_only"},
            )
            return

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"cognia-mesh-{self.node_id}"
        )
        self._thread.start()
        logger.info(
            f"MeshNode iniciado en ws://{self.host}:{self.port}",
            extra={"op": "mesh_node.start",
                   "context": f"id={self.node_id} port={self.port}"},
        )

    def stop(self):
        """Detiene el servidor y limpia recursos."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info(
            "MeshNode detenido",
            extra={"op": "mesh_node.stop", "context": f"id={self.node_id}"},
        )

    def _run_loop(self):
        """Hilo daemon — corre el event loop asyncio."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            logger.warning(
                f"MeshNode event loop terminó: {exc}",
                extra={"op": "mesh_node._run_loop", "context": f"err={exc}"},
            )

    async def _serve(self):
        """Servidor WebSocket principal."""
        if not HAS_WEBSOCKETS:
            return
        async with websockets.server.serve(
            self._handle_connection,
            self.host,
            self.port,
            max_size=MSG_MAX_BYTES,
        ):
            # Sincronización periódica con peers
            while self._running:
                await asyncio.sleep(SYNC_INTERVAL_S)
                await self._sync_all_peers()

    # ──────────────────────────────────────────────────────────────────
    # Manejo de conexiones entrantes
    # ──────────────────────────────────────────────────────────────────

    async def _handle_connection(self, websocket, path: str = "/"):
        """Maneja una conexión WebSocket entrante de un peer."""
        try:
            async for raw in websocket:
                if len(raw) > MSG_MAX_BYTES:
                    logger.warning(
                        "Mensaje demasiado grande, ignorado",
                        extra={"op": "mesh_node._handle",
                               "context": f"size={len(raw)}"},
                    )
                    continue
                msg = _parse_msg(raw)
                if msg is None:
                    continue
                await self._dispatch(msg, websocket)
        except Exception as exc:
            logger.debug(
                f"Conexión cerrada: {exc}",
                extra={"op": "mesh_node._handle_connection",
                       "context": f"err={exc}"},
            )

    async def _dispatch(self, msg: dict, websocket):
        """Despacha un mensaje recibido según su tipo."""
        msg_type  = msg.get("type")
        sender_id = msg.get("node_id", "unknown")
        payload   = msg.get("payload", {})

        if msg_type == "knowledge_delta":
            await self._on_knowledge_delta(sender_id, payload)

        elif msg_type == "federated_search":
            await self._on_federated_search(sender_id, payload, websocket)

        elif msg_type == "search_response":
            # Respuesta a búsqueda federada — procesada por el caller
            pass

        elif msg_type == "handshake":
            remote_uri = payload.get("uri", "")
            if remote_uri and sender_id not in self._peers:
                self._peers[sender_id] = remote_uri
                logger.info(
                    f"Nuevo peer registrado: {sender_id}",
                    extra={"op": "mesh_node.handshake",
                           "context": f"peer={sender_id} uri={remote_uri}"},
                )
        else:
            logger.debug(
                f"Mensaje de tipo desconocido: {msg_type}",
                extra={"op": "mesh_node._dispatch",
                       "context": f"type={msg_type} from={sender_id}"},
            )

    # ──────────────────────────────────────────────────────────────────
    # API pública — Knowledge
    # ──────────────────────────────────────────────────────────────────

    def publish_knowledge_delta(self, triples: List[dict]):
        """
        Publica triples nuevos a todos los peers conectados.

        Filtra automáticamente por capa de privacidad (solo SEMI_PRIV y PUBLIC).
        Los triples PRIVADOS (episódicos) nunca salen del dispositivo.

        Parámetros
        ----------
        triples : lista de dicts con claves 'subject', 'predicate', 'object'.
        """
        shareable = filter_shareable_triples(triples)
        if not shareable:
            logger.debug(
                "publish_knowledge_delta: sin triples compartibles",
                extra={"op": "mesh_node.publish",
                       "context": f"total={len(triples)} shareable=0"},
            )
            return

        # Agregar al CRDT local
        for t in shareable:
            self.crdt.add(
                subject   = t["subject_hash"],
                predicate = t["predicate"],
                obj       = t["object_hash"],
            )

        if not HAS_WEBSOCKETS or not self._peers:
            return

        msg = _make_msg("knowledge_delta", self.node_id, {"triples": shareable})

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._broadcast(msg), self._loop
            )

    def on_knowledge_received(self, callback: Callable[[List[dict]], None]):
        """Registra callback para cuando se recibe conocimiento nuevo de peers."""
        self._on_knowledge_received = callback

    # ──────────────────────────────────────────────────────────────────
    # API pública — Búsqueda federada
    # ──────────────────────────────────────────────────────────────────

    def federated_search(
        self,
        query_embedding: List[float],
        k: int = 5,
        timeout_ms: int = FEDERATED_TIMEOUT_MS,
    ) -> List[dict]:
        """
        Búsqueda semántica federada en peers.

        El embedding se privatiza con ruido Laplaciano (ε=self.epsilon)
        antes de enviarlo — los peers no pueden reconstruir la consulta original.

        Retorna lista de resultados de peers (puede estar vacía si no hay peers
        o si websockets no está disponible).

        Esta llamada es SÍNCRONA (bloquea hasta timeout_ms o respuesta).
        """
        if not HAS_WEBSOCKETS or not self._peers:
            return []

        # Privatizar el embedding antes de enviarlo
        noisy_vec = privatize_embedding(query_embedding, epsilon=self.epsilon)

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._federated_search_async(noisy_vec, k, timeout_ms / 1000.0),
                self._loop,
            )
            try:
                return future.result(timeout=timeout_ms / 1000.0 + 0.5)
            except Exception as exc:
                logger.warning(
                    f"federated_search timeout/error: {exc}",
                    extra={"op": "mesh_node.federated_search",
                           "context": f"err={exc}"},
                )
        return []

    # ──────────────────────────────────────────────────────────────────
    # API pública — Peers
    # ──────────────────────────────────────────────────────────────────

    def connect_peer(self, uri: str):
        """
        Conecta a un peer por URI WebSocket (ej. 'ws://192.168.1.10:7474').
        Envía handshake para registrar este nodo en el peer.
        """
        if not HAS_WEBSOCKETS:
            logger.warning(
                "connect_peer: websockets no disponible, modo LOCAL_ONLY",
                extra={"op": "mesh_node.connect_peer", "context": f"uri={uri}"},
            )
            return

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._connect_and_handshake(uri), self._loop
            )
        else:
            logger.warning(
                "connect_peer: el loop no está corriendo, llamar start() primero",
                extra={"op": "mesh_node.connect_peer", "context": f"uri={uri}"},
            )

    def get_peers(self) -> List[str]:
        """Retorna lista de URIs de peers conocidos."""
        return list(self._peers.values())

    def crdt_stats(self) -> dict:
        """Estadísticas del grafo CRDT local."""
        return self.crdt.stats()

    # ──────────────────────────────────────────────────────────────────
    # Internos async
    # ──────────────────────────────────────────────────────────────────

    async def _broadcast(self, msg: str):
        """Envía un mensaje a todos los peers conocidos."""
        if not HAS_WEBSOCKETS:
            return
        for peer_id, uri in list(self._peers.items()):
            try:
                async with websockets.client.connect(uri, open_timeout=3) as ws:
                    await ws.send(msg)
            except Exception as exc:
                logger.debug(
                    f"Broadcast falló para peer {peer_id}: {exc}",
                    extra={"op": "mesh_node._broadcast",
                           "context": f"peer={peer_id} err={exc}"},
                )

    async def _connect_and_handshake(self, uri: str):
        """Conecta a un peer y envía handshake."""
        if not HAS_WEBSOCKETS:
            return
        try:
            async with websockets.client.connect(uri, open_timeout=5) as ws:
                msg = _make_msg("handshake", self.node_id, {
                    "uri": f"ws://{self.host}:{self.port}"
                })
                await ws.send(msg)
                # Leer respuesta de handshake si viene
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    resp = _parse_msg(raw)
                    if resp and resp.get("node_id"):
                        peer_id = resp["node_id"]
                        self._peers[peer_id] = uri
                        logger.info(
                            f"Peer conectado: {peer_id} @ {uri}",
                            extra={"op": "mesh_node.handshake",
                                   "context": f"peer={peer_id}"},
                        )
                except asyncio.TimeoutError:
                    # El peer no respondió handshake — registrar igual por URI
                    self._peers[uri] = uri
        except Exception as exc:
            logger.warning(
                f"No se pudo conectar a peer {uri}: {exc}",
                extra={"op": "mesh_node._connect_and_handshake",
                       "context": f"uri={uri} err={exc}"},
            )

    async def _on_knowledge_delta(self, sender_id: str, payload: dict):
        """Procesa triples recibidos de un peer — merge al CRDT local."""
        triples = payload.get("triples", [])
        if not triples:
            return

        new_count = self.crdt.merge(triples)

        if new_count > 0 and self._on_knowledge_received:
            try:
                self._on_knowledge_received(triples)
            except Exception as exc:
                logger.warning(
                    "on_knowledge_received callback error",
                    extra={"op": "mesh_node._on_knowledge_delta",
                           "context": f"err={exc}"},
                )

        logger.info(
            f"Knowledge delta recibido de {sender_id}: {new_count} triples nuevos",
            extra={"op": "mesh_node._on_knowledge_delta",
                   "context": f"from={sender_id} new={new_count}"},
        )

    async def _on_federated_search(
        self, sender_id: str, payload: dict, websocket
    ):
        """
        Responde a una búsqueda federada de un peer.

        Solo busca en el grafo CRDT local (conocimiento público).
        NO accede a memorias episódicas.
        """
        query_vec = payload.get("embedding", [])
        k         = int(payload.get("k", 5))

        if not query_vec:
            return

        # Buscar en CRDT local por similitud de predicado (búsqueda textual simple)
        # (búsqueda vectorial real requeriría índice adicional — Fase 4)
        query_str = payload.get("query_text", "").lower()
        results   = []
        for triple in self.crdt.get_valid():
            if query_str and query_str in triple.predicate.lower():
                results.append(triple.to_dict())
            if len(results) >= k:
                break

        response = _make_msg("search_response", self.node_id, {
            "results":   results,
            "source":    self.node_id,
            "result_k":  len(results),
        })
        try:
            await websocket.send(response)
        except Exception as exc:
            logger.debug(
                f"Error enviando search_response a {sender_id}: {exc}",
                extra={"op": "mesh_node._on_federated_search",
                       "context": f"peer={sender_id} err={exc}"},
            )

    async def _federated_search_async(
        self, noisy_vec: List[float], k: int, timeout_s: float
    ) -> List[dict]:
        """Envía búsqueda federada a todos los peers y agrega resultados."""
        if not HAS_WEBSOCKETS or not self._peers:
            return []

        msg = _make_msg("federated_search", self.node_id, {
            "embedding": noisy_vec,
            "k":         k,
        })

        all_results = []
        tasks = [
            self._query_peer(uri, msg, timeout_s)
            for uri in self._peers.values()
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for resp in responses:
            if isinstance(resp, list):
                all_results.extend(resp)

        return all_results[:k]

    async def _query_peer(
        self, uri: str, msg: str, timeout_s: float
    ) -> List[dict]:
        """Envía una query a un peer y retorna sus resultados."""
        if not HAS_WEBSOCKETS:
            return []
        try:
            async with websockets.client.connect(uri, open_timeout=3) as ws:
                await ws.send(msg)
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                resp = _parse_msg(raw)
                if resp and resp.get("type") == "search_response":
                    return resp.get("payload", {}).get("results", [])
        except Exception as exc:
            logger.debug(
                f"_query_peer {uri} error: {exc}",
                extra={"op": "mesh_node._query_peer",
                       "context": f"uri={uri} err={exc}"},
            )
        return []

    async def _sync_all_peers(self):
        """Sincronización periódica — envía delta CRDT a todos los peers."""
        delta = self.crdt.get_delta(since_ts=self._last_sync)
        if delta:
            msg = _make_msg("knowledge_delta", self.node_id, {"triples": delta})
            await self._broadcast(msg)
            logger.debug(
                f"Sync periódico: {len(delta)} triples enviados",
                extra={"op": "mesh_node._sync_all_peers",
                       "context": f"delta={len(delta)} peers={len(self._peers)}"},
            )
        self._last_sync = time.time()


# ══════════════════════════════════════════════════════════════════════
# SINGLETON (una instancia por proceso)
# ══════════════════════════════════════════════════════════════════════

_node_instance: Optional[CogniaMeshNode] = None

def get_mesh_node(
    node_id: Optional[str] = None,
    port: int = DEFAULT_PORT,
) -> CogniaMeshNode:
    """Retorna el singleton del nodo mesh (crea uno si no existe)."""
    global _node_instance
    if _node_instance is None:
        _node_instance = CogniaMeshNode(node_id=node_id, port=port)
    return _node_instance
