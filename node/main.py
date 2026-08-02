"""
node/main.py
============
Standalone runner for a Cognia shard node.

Registers with the coordinator, receives a shard assignment,
loads the corresponding INT4 .npz weights, and starts listening
for relay inference sessions.

Usage (one terminal per shard, run 4 in parallel):
    python node/main.py

Environment variables:
    COGNIA_COORDINATOR_URL   default: http://localhost:8001
    SHARD_WEIGHTS_DIR        default: model_shards/qwen-coder-3b-q4
    COGNIA_SWARM_MODEL       default: qwen-coder-3b-q4
    COGNIA_NODE_HARDWARE     optional: human-readable hardware description
"""

from __future__ import annotations

import json
import os
import signal
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

# Allow running from repo root or from node/ directory
_NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_NODE_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from node.shard_engine import ShardEngine, ShardConfig
from shattering.model_constants import QWEN25_CODER_3B

# ── Configuration ─────────────────────────────────────────────────────────────

COORDINATOR_URL  = os.environ.get("COGNIA_COORDINATOR_URL", "http://localhost:8001").rstrip("/")
_DEFAULT_WEIGHTS = os.path.join(os.path.expanduser("~"), ".cognia", "shards", "qwen-coder-3b-q4")
WEIGHTS_DIR      = os.environ.get("SHARD_WEIGHTS_DIR", _DEFAULT_WEIGHTS)
MODEL_NAME       = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
HARDWARE_INFO    = os.environ.get("COGNIA_NODE_HARDWARE", "")
HEARTBEAT_EVERY  = 30   # seconds


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http(method: str, url: str, body: dict | None = None, timeout: int = 10,
          headers: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"} if data else {}
    if headers:
        hdrs.update(headers)
    req  = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")


# ── Contributor token ─────────────────────────────────────────────────────────
# El coordinador emite un contributor_token en el registro: es lo que da
# acceso a la economía (tier, RPM, /api/federated/*). Antes este runner lo
# DESCARTABA y el nodo quedaba fuera de la economía para siempre.

_CONFIG_ENV = os.path.join(os.path.expanduser("~"), ".cognia", "config.env")


def _load_saved_token() -> str:
    tok = os.environ.get("COGNIA_CONTRIBUTOR_TOKEN", "")
    if tok:
        return tok
    try:
        with open(_CONFIG_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("COGNIA_CONTRIBUTOR_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _persist_token(token: str):
    """Actualiza/agrega COGNIA_CONTRIBUTOR_TOKEN en ~/.cognia/config.env."""
    try:
        os.makedirs(os.path.dirname(_CONFIG_ENV), exist_ok=True)
        lines: list[str] = []
        try:
            with open(_CONFIG_ENV, encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines()
                         if not l.startswith("COGNIA_CONTRIBUTOR_TOKEN=")]
        except OSError:
            pass
        lines.append(f"COGNIA_CONTRIBUTOR_TOKEN={token}")
        with open(_CONFIG_ENV, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"[node] Aviso: no se pudo persistir el contributor token: {e}")


# ── Hardware detection ────────────────────────────────────────────────────────

def _detect_hardware() -> str:
    if HARDWARE_INFO:
        return HARDWARE_INFO
    import platform
    desc = platform.processor()[:40] or platform.machine()
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / 1e9
        desc += f" | {ram_gb:.1f}GB RAM"
    except ImportError:
        pass
    return desc


# ── Node runner ───────────────────────────────────────────────────────────────

class ShardNode:
    def __init__(self):
        self.node_id: str | None = None
        self.shard:   int | None = None
        self.engine:  ShardEngine | None = None
        self._stop    = threading.Event()
        self._hb_thread: threading.Thread | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self):
        self._register()
        self._load_engine()
        self._start_heartbeat()
        self._start_relay_listener()
        print(f"[node] Shard {self.shard} listo — modo={self.engine.mode} "
              f"node_id={self.node_id[:8]}...")

    def stop(self):
        self._stop.set()
        if self.node_id:
            try:
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"{COORDINATOR_URL}/api/node/{self.node_id}",
                        method="DELETE",
                    ),
                    timeout=5,
                )
            except Exception:
                pass
        print(f"[node] Shard {self.shard} desconectado.")

    # ── Registration ───────────────────────────────────────────────────

    def _register(self):
        existing_id    = os.environ.get("COGNIA_NODE_ID", "")
        existing_shard = os.environ.get("COGNIA_NODE_SHARD", "")

        if existing_id and existing_shard:
            # Reactivate the existing registration via heartbeat.
            # Avoids being assigned a different shard than the one already on disk.
            try:
                result = _http("POST", f"{COORDINATOR_URL}/api/node/heartbeat",
                               {"node_id": existing_id})
                if result.get("ok"):
                    self.node_id = existing_id
                    self.shard   = int(existing_shard)
                    print(f"[node] Reactivado — shard {self.shard} "
                          f"(node_id: {self.node_id[:8]}...)")
                    return
            except Exception:
                pass  # coordinator unreachable or node expired — fall through to fresh register

        print(f"[node] Registrando en {COORDINATOR_URL}...")
        # Con token previo el coordinador conserva el node_id y la
        # contribución acumula (tier sube con cada shard servido).
        saved_token = _load_saved_token()
        headers = {"X-Contributor-Token": saved_token} if saved_token else None
        result = _http("POST", f"{COORDINATOR_URL}/api/node/register", {
            "hardware_info": _detect_hardware(),
            "model_name":    MODEL_NAME,
        }, headers=headers)
        self.node_id = result["node_id"]
        self.shard   = result["shard"]
        token = result.get("contributor_token", "")
        if token:
            os.environ["COGNIA_CONTRIBUTOR_TOKEN"] = token
            _persist_token(token)
            tier = result.get("tier", "?")
            print(f"[node] Registrado — shard {self.shard} | tier {tier} "
                  f"(token guardado en {_CONFIG_ENV})")
        else:
            print(f"[node] Registrado — shard asignado: {self.shard}")

    # ── Engine load ────────────────────────────────────────────────────

    def _load_engine(self):
        cfg = QWEN25_CODER_3B
        shard_cfg = ShardConfig(
            model_name       = MODEL_NAME,
            shard_index      = self.shard,
            n_shards         = cfg["n_shards"],
            total_layers     = cfg["total_layers"],
            hidden_dim       = cfg["hidden_dim"],
            intermediate_dim = cfg["intermediate_dim"],
            n_heads          = cfg["n_heads"],
            n_kv_heads       = cfg["n_kv_heads"],
            head_dim         = cfg["head_dim"],
            rope_theta       = cfg["rope_theta"],
            rms_norm_eps     = cfg["rms_norm_eps"],
            vocab_size       = cfg["vocab_size"],
            eos_token_id     = cfg["eos_token_id"],
        )

        npz_path = os.path.join(WEIGHTS_DIR, f"shard_{self.shard}.npz")
        weights_dir = WEIGHTS_DIR if os.path.exists(npz_path) else None

        if weights_dir is None:
            print(f"[node] ADVERTENCIA: {npz_path} no encontrado — modo simulacion")
        else:
            print(f"[node] Cargando {npz_path}...")

        self.engine = ShardEngine(shard_cfg, weights_path=weights_dir)

    # ── Heartbeat ──────────────────────────────────────────────────────

    def _start_heartbeat(self):
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name=f"hb-shard{self.shard}"
        )
        self._hb_thread.start()

    def _heartbeat_loop(self):
        while not self._stop.wait(HEARTBEAT_EVERY):
            try:
                _http("POST", f"{COORDINATOR_URL}/api/node/heartbeat",
                      {"node_id": self.node_id})
            except Exception as e:
                print(f"[node] Heartbeat fallido: {e}")

    # ── Relay listener ─────────────────────────────────────────────────

    def _start_relay_listener(self):
        try:
            from node.relay_client import RelayClient, SessionListener
            relay_client = RelayClient(
                coordinator_url = COORDINATOR_URL,
                engine          = self.engine,
                shard_index     = self.shard,
            )
            listener = SessionListener(
                coordinator_url = COORDINATOR_URL,
                node_id         = self.node_id,
                relay_client    = relay_client,
            )
            listener.start()
            self._listener = listener
        except Exception as e:
            print(f"[node] Relay listener no disponible: {e}")
            self._listener = None

    # ── Status ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "node_id": self.node_id,
            "shard":   self.shard,
            "mode":    self.engine.mode if self.engine else "unloaded",
            "model":   MODEL_NAME,
        }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # config.env ANTES de usar las constantes de modulo: el console script
    # cognia-node NO pasa por cognia.__main__ (que si aplica config) y el
    # nodo instalado ignoraba COGNIA_COORDINATOR_URL/COGNIA_NODE_ID/SHARD de
    # ~/.cognia/config.env — podia re-registrarse de cero y caer a 'modo
    # simulacion' (auditoria e2e 2026-07-15). Las globals se recalculan
    # porque se capturaron al importar el modulo.
    try:
        from cognia.first_run import apply_config
        apply_config()
        global COORDINATOR_URL, WEIGHTS_DIR, MODEL_NAME, HARDWARE_INFO
        COORDINATOR_URL = os.environ.get(
            "COGNIA_COORDINATOR_URL", "http://localhost:8001").rstrip("/")
        WEIGHTS_DIR = os.environ.get("SHARD_WEIGHTS_DIR", _DEFAULT_WEIGHTS)
        MODEL_NAME = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
        HARDWARE_INFO = os.environ.get("COGNIA_NODE_HARDWARE", "")
    except Exception:
        pass
    node = ShardNode()

    def _shutdown(sig, frame):
        print("\n[node] Señal de cierre recibida...")
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        node.start()
    except Exception as e:
        print(f"[node] Error al iniciar: {e}")
        sys.exit(1)

    print(f"[node] Corriendo. Ctrl+C para detener.")
    print(f"[node] Estado: {node.status()}")

    while not node._stop.is_set():
        time.sleep(5)


if __name__ == "__main__":
    main()
