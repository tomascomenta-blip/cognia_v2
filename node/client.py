"""
node/client.py
==============
Cliente del swarm que corre en la app de cada usuario.

Responsabilidades:
  1. Registrarse en el coordinador al arrancar
  2. Enviar heartbeats cada 30s (hilo de fondo)
  3. Conectarse al relay WebSocket cuando hay una inferencia en curso
  4. Delegar el cómputo al ShardEngine local
  5. Desregistrarse limpiamente al cerrar

Uso:
    client = SwarmClient(coordinator_url="https://coordinator.railway.app")
    client.start()            # registra + arranca heartbeat
    # ... la app corre normalmente ...
    client.stop()             # desregistra
"""

import os
import time
import json
import uuid
import struct
import threading
import urllib.request
import urllib.error
from typing import Optional, Callable

from node.shard_engine import ShardEngine, ShardConfig, encode_hidden_state


# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════

COORDINATOR_URL  = os.environ.get("COORDINATOR_URL", "http://localhost:8001")
HEARTBEAT_EVERY  = 30    # segundos
WEIGHTS_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "model_shards")


# ══════════════════════════════════════════════════════════════════════
# HTTP HELPER (sin dependencias extra)
# ══════════════════════════════════════════════════════════════════════

def _post(url: str, body: dict, timeout: int = 10) -> dict:
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}")


def _get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _delete(url: str, timeout: int = 5):
    req = urllib.request.Request(url, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=timeout)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# CLIENTE DEL SWARM
# ══════════════════════════════════════════════════════════════════════

class SwarmClient:
    """
    Cliente que convierte a un usuario en nodo del swarm.
    Se integra en la app de Cognia — arranca en segundo plano
    sin interferir con la experiencia del usuario.
    """

    def __init__(self, coordinator_url: str = COORDINATOR_URL,
                 model_name: str = "llama-3.2-3b-q4",
                 hardware_info: str = "",
                 on_status_change: Optional[Callable] = None):

        self.coordinator_url  = coordinator_url.rstrip("/")
        self.model_name       = model_name
        self.hardware_info    = hardware_info or self._detect_hardware()
        self.on_status_change = on_status_change

        # Estado (se completan al registrarse)
        self.node_id:     Optional[str] = None
        self.shard:       Optional[int] = None
        self.engine:      Optional[ShardEngine] = None
        self.status:      str = "unregistered"
        self._stop_event  = threading.Event()
        self._hb_thread:  Optional[threading.Thread] = None

    # ── Ciclo de vida ─────────────────────────────────────────────────

    def start(self):
        """Registra el nodo y arranca el heartbeat en segundo plano."""
        try:
            self._register()
            self._load_engine()
            self._start_heartbeat()
            self._start_relay_listener()
            self._set_status("ready")
            print(f"[SwarmClient] Nodo listo — shard {self.shard}, "
                  f"modelo {self.model_name}")
        except Exception as e:
            self._set_status("error")
            print(f"[SwarmClient] Error al iniciar: {e}")

    def stop(self):
        """Desregistra el nodo y detiene todos los hilos de fondo."""
        self._stop_event.set()
        if hasattr(self, "_listener") and self._listener:
            self._listener.stop()
        if self.node_id:
            _delete(f"{self.coordinator_url}/api/node/{self.node_id}")
        self._set_status("stopped")
        print(f"[SwarmClient] Nodo {self.node_id[:8] if self.node_id else '?'}... desconectado")

    # ── Registro ──────────────────────────────────────────────────────

    def _register(self):
        result = _post(
            f"{self.coordinator_url}/api/node/register",
            {"hardware_info": self.hardware_info, "model_name": self.model_name},
        )
        self.node_id = result["node_id"]
        self.shard   = result["shard"]
        self._model_config = result["model_config"]
        print(f"[SwarmClient] Registrado → node_id={self.node_id[:8]}... "
              f"shard={self.shard}")

    # ── Heartbeat en hilo de fondo ────────────────────────────────────

    def _start_heartbeat(self):
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="cognia-heartbeat"
        )
        self._hb_thread.start()

    def _heartbeat_loop(self):
        while not self._stop_event.wait(HEARTBEAT_EVERY):
            try:
                _post(f"{self.coordinator_url}/api/node/heartbeat",
                      {"node_id": self.node_id})
            except Exception as e:
                print(f"[SwarmClient] Heartbeat fallido: {e}")
                self._set_status("degraded")

    # ── Descarga + carga del motor de inferencia ──────────────────────

    def _load_engine(self):
        cfg       = self._model_config
        shard_dir = os.path.join(WEIGHTS_BASE_DIR, self.model_name,
                                 f"shard_{self.shard}")

        # Descargar shard si no está presente
        if not os.path.exists(os.path.join(shard_dir, "shard_meta.json")):
            self._download_shard(shard_dir)

        shard_cfg = ShardConfig(
            model_name       = self.model_name,
            shard_index      = self.shard,
            n_shards         = cfg["n_shards"],
            total_layers     = cfg["total_layers"],
            hidden_dim       = cfg["hidden_dim"],
            intermediate_dim = cfg["intermediate_dim"],
        )
        # Pasar la ruta solo si existe el safetensors real
        weights_path = shard_dir if os.path.exists(
            os.path.join(shard_dir, "shard.safetensors")
        ) else None

        self.engine = ShardEngine(shard_cfg, weights_path=weights_path)

    def _download_shard(self, shard_dir: str):
        """Descarga el shard asignado mostrando progreso en consola."""
        try:
            from node.downloader import ShardDownloader
        except ImportError:
            print(f"[SwarmClient] downloader no disponible, usando simulación")
            return

        hf_token = os.environ.get("HF_TOKEN", "")
        dl       = ShardDownloader(self.shard, self.model_name, hf_token)

        def on_progress(pct: float, msg: str):
            bar_len = 30
            filled  = int(bar_len * pct)
            bar     = "#" * filled + "-" * (bar_len - filled)
            print(f"\r[SwarmClient] [{bar}] {pct:5.1%} {msg[:50]}", end="", flush=True)

        print(f"[SwarmClient] Descargando shard {self.shard} de {self.model_name}...")
        result = dl.download(on_progress=on_progress)
        print()   # newline después de la barra de progreso

        if result.ok:
            print(f"[SwarmClient] Shard {self.shard} listo — "
                  f"{result.size_mb:.1f} MB, modo={result.mode}, "
                  f"tiempo={result.duration_s:.1f}s")
        else:
            print(f"[SwarmClient] Descarga falló: {result.error} — usando simulación")

    # ── Relay listener (sesiones entrantes) ───────────────────────────

    def _start_relay_listener(self):
        """Escucha sesiones de inferencia donde este nodo está en la ruta."""
        try:
            from node.relay_client import RelayClient, SessionListener
            self._relay_client = RelayClient(
                coordinator_url = self.coordinator_url,
                engine          = self.engine,
                shard_index     = self.shard,
            )
            self._listener = SessionListener(
                coordinator_url = self.coordinator_url,
                node_id         = self.node_id,
                relay_client    = self._relay_client,
            )
            self._listener.start()
        except Exception as e:
            print(f"[SwarmClient] Relay listener no disponible: {e}")
            self._listener = None

    # ── Inferencia (proceso de un hidden state) ───────────────────────

    def process_inference(self, hidden_state_bytes: bytes) -> bytes:
        """
        Recibe un hidden state en bytes, lo procesa con el engine local,
        retorna el resultado en bytes para enviar al siguiente nodo.
        """
        if not self.engine:
            raise RuntimeError("Engine no inicializado")
        out_bytes, ms = self.engine.process_bytes(hidden_state_bytes)
        return out_bytes

    # ── Participar en una inferencia vía relay ─────────────────────────

    async def join_inference_session(self, session_id: str):
        """
        Conecta al relay del coordinador para participar en una inferencia.
        Se usa cuando el coordinador seleccionó a este nodo para la ruta.

        Corre en asyncio — se llama desde el servidor FastAPI de la app.
        """
        import websockets

        relay_url = (f"{self.coordinator_url.replace('http', 'ws')}"
                     f"/ws/relay/{session_id}/{self.shard}")
        try:
            async with websockets.connect(relay_url) as ws:
                self._set_status("inferring")
                async for message in ws:
                    if isinstance(message, bytes):
                        result = self.process_inference(message)
                        await ws.send(result)
                self._set_status("ready")
        except Exception as e:
            print(f"[SwarmClient] Error en sesión {session_id}: {e}")
            self._set_status("ready")

    # ── Consultas al coordinador ──────────────────────────────────────

    def swarm_status(self) -> dict:
        """Estado actual del swarm (cuántos nodos, shards cubiertos, etc.)"""
        try:
            return _get(f"{self.coordinator_url}/api/swarm/status"
                        f"?model_name={self.model_name}")
        except Exception as e:
            return {"error": str(e)}

    def get_route(self) -> dict:
        """Ruta de inferencia actual (qué nodo tiene cada shard)."""
        try:
            return _get(f"{self.coordinator_url}/api/swarm/route"
                        f"?model_name={self.model_name}")
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Helpers ───────────────────────────────────────────────────────

    def _set_status(self, new_status: str):
        self.status = new_status
        if self.on_status_change:
            self.on_status_change(new_status)

    @staticmethod
    def _detect_hardware() -> str:
        import platform
        try:
            import psutil
            ram_gb = psutil.virtual_memory().total / 1e9
            return f"{platform.processor()[:40]} | {ram_gb:.1f}GB RAM"
        except ImportError:
            return platform.processor()[:60] or platform.machine()

    def info(self) -> dict:
        return {
            "node_id":   self.node_id,
            "shard":     self.shard,
            "model":     self.model_name,
            "status":    self.status,
            "hardware":  self.hardware_info,
            "engine":    self.engine.info() if self.engine else None,
        }
