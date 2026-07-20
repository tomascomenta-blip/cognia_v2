"""
coordinator/registry.py
=======================
SQLite registry de nodos del swarm.
Maneja registro, heartbeat, asignación de shards y routing.
"""

import sqlite3
import sys
import time
import uuid
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# Allow running coordinator standalone (python -m coordinator.app)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shattering.model_constants import LLAMA_32_3B, QWEN25_CODER_3B

DB_PATH     = "coordinator.db"
NODE_TIMEOUT = 60   # segundos sin heartbeat → nodo inactivo


# ── Configuración de modelos soportados ──────────────────────────────

def _llama32(**extra) -> dict:
    return {**LLAMA_32_3B, **extra}

def _qwen25(**extra) -> dict:
    return {**QWEN25_CODER_3B, **extra}

MODELS = {
    # ── Qwen2.5-Coder-3B (primary model, Apache-2.0) ───────────────────
    "qwen-coder-3b-q4": _qwen25(sub_model=None),
    # ── Legacy Llama keys (backward compat) ────────────────────────────
    "llama-3.2-3b-q4": _llama32(sub_model=None),
    "llama-3.1-8b-q4": {
        "total_layers":      32,
        "hidden_dim":        4096,
        "intermediate_dim":  14336,
        "n_shards":          4,
        "layers_per_shard":  8,
        "vocab_size":        32000,
        "size_per_shard_gb": 1.0,
        "params_b":          8.0,
        "sub_model":         None,
    },
    # ── Shattering sub-models (Llama 3.2-3B base, domain-specialised) ──
    "logos-3.2-3b-q4":  _llama32(sub_model="logos",  domain="reasoning_knowledge"),
    "techne-3.2-3b-q4": _llama32(sub_model="techne", domain="code_technical"),
    "rhetor-3.2-3b-q4": _llama32(sub_model="rhetor", domain="writing_academic"),
}

DEFAULT_MODEL    = "qwen-coder-3b-q4"
DEFAULT_SUBMODEL = "logos"

# Ordered list of Shattering sub-model registry keys
SHATTERING_MODELS = ["logos-3.2-3b-q4", "techne-3.2-3b-q4", "rhetor-3.2-3b-q4"]


@dataclass
class Node:
    node_id:       str
    shard:         int
    model_name:    str
    hardware_info: str
    registered_at: float
    last_heartbeat: float
    is_active:     bool

    def to_dict(self):
        return asdict(self)

    def seconds_since_heartbeat(self) -> float:
        return time.time() - self.last_heartbeat


# ── Schema ────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id        TEXT PRIMARY KEY,
    shard          INTEGER NOT NULL,
    model_name     TEXT NOT NULL DEFAULT 'llama-3.2-3b-q4',
    hardware_info  TEXT DEFAULT '',
    registered_at  REAL NOT NULL,
    last_heartbeat REAL NOT NULL,
    is_active      INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_nodes_shard  ON nodes(shard);
CREATE INDEX IF NOT EXISTS idx_nodes_active ON nodes(is_active);

CREATE TABLE IF NOT EXISTS inference_log (
    session_id  TEXT PRIMARY KEY,
    node_ids    TEXT NOT NULL,    -- JSON array
    started_at  REAL NOT NULL,
    finished_at REAL,
    status      TEXT DEFAULT 'pending'
);
"""


# ══════════════════════════════════════════════════════════════════════
# REGISTRY
# ══════════════════════════════════════════════════════════════════════

class NodeRegistry:

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Para :memory: usamos una conexión persistente (no se comparte entre conexiones)
        self._mem_conn = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _conn(self):
        if self._mem_conn is not None:
            yield self._mem_conn
            self._mem_conn.commit()
        else:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ── Registro de nodo nuevo ────────────────────────────────────────

    def register(self, hardware_info: str = "",
                 model_name: str = DEFAULT_MODEL) -> dict:
        """
        Registra un nodo nuevo. Asigna el shard con menos réplicas activas.
        Retorna {node_id, shard, model_config}.
        """
        cfg = MODELS.get(model_name, MODELS[DEFAULT_MODEL])
        n_shards = cfg["n_shards"]

        node_id = uuid.uuid4().hex
        now     = time.time()

        shard = self._pick_shard(n_shards, model_name)

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO nodes
                   (node_id, shard, model_name, hardware_info, registered_at, last_heartbeat, is_active)
                   VALUES (?,?,?,?,?,?,1)""",
                (node_id, shard, model_name, hardware_info, now, now),
            )

        return {
            "node_id":      node_id,
            "shard":        shard,
            "model_name":   model_name,
            "model_config": cfg,
            "message":      f"Descargá el shard {shard} (~{cfg['size_per_shard_gb']:.2f} GB)",
        }

    def _pick_shard(self, n_shards: int, model_name: str) -> int:
        """Elige el shard con menos réplicas activas actualmente."""
        self._mark_stale_nodes()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT shard, COUNT(*) as cnt
                   FROM nodes
                   WHERE is_active=1 AND model_name=?
                   GROUP BY shard""",
                (model_name,),
            ).fetchall()

        counts = {i: 0 for i in range(n_shards)}
        for row in rows:
            counts[row["shard"]] = row["cnt"]

        return min(counts, key=counts.get)

    # ── Heartbeat ─────────────────────────────────────────────────────

    def heartbeat(self, node_id: str) -> dict:
        """Actualiza last_heartbeat. Retorna {ok, shard}."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT shard FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "node_id desconocido"}
            conn.execute(
                "UPDATE nodes SET last_heartbeat=?, is_active=1 WHERE node_id=?",
                (time.time(), node_id),
            )
        return {"ok": True, "shard": row["shard"]}

    # ── Desregistro ───────────────────────────────────────────────────

    def unregister(self, node_id: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE nodes SET is_active=0 WHERE node_id=?", (node_id,)
            )

    # ── Routing de inferencia ─────────────────────────────────────────

    def get_route(self, model_name: str = DEFAULT_MODEL,
                  exclude_node: Optional[str] = None) -> dict:
        """
        Construye la ruta de inferencia: un nodo activo por shard, en orden.

        exclude_node: el nodo que hace la petición (para no asignarse shard 0
                      si coincide, opcional).

        Retorna {ok, route: [{node_id, shard, hardware_info}], missing_shards}.
        """
        self._mark_stale_nodes()
        cfg      = MODELS.get(model_name, MODELS[DEFAULT_MODEL])
        n_shards = cfg["n_shards"]
        route    = []
        missing  = []

        with self._conn() as conn:
            for shard in range(n_shards):
                row = conn.execute(
                    """SELECT node_id, shard, hardware_info
                       FROM nodes
                       WHERE is_active=1 AND model_name=? AND shard=?
                       ORDER BY last_heartbeat DESC
                       LIMIT 1""",
                    (model_name, shard),
                ).fetchone()

                if row:
                    route.append({
                        "node_id":       row["node_id"],
                        "shard":         row["shard"],
                        "hardware_info": row["hardware_info"],
                    })
                else:
                    missing.append(shard)

        if missing:
            return {
                "ok":      False,
                "error":   f"Shards sin cobertura: {missing}. Swarm incompleto.",
                "missing": missing,
                "route":   route,
            }

        return {"ok": True, "route": route, "missing": []}

    # ── Estado del swarm ──────────────────────────────────────────────

    def status(self, model_name: str = DEFAULT_MODEL) -> dict:
        """Resumen del estado del swarm."""
        self._mark_stale_nodes()
        cfg      = MODELS.get(model_name, MODELS[DEFAULT_MODEL])
        n_shards = cfg["n_shards"]

        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE model_name=?", (model_name,)
            ).fetchone()[0]

            active = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE is_active=1 AND model_name=?",
                (model_name,),
            ).fetchone()[0]

            shards_rows = conn.execute(
                """SELECT shard, COUNT(*) as replicas
                   FROM nodes WHERE is_active=1 AND model_name=?
                   GROUP BY shard""",
                (model_name,),
            ).fetchall()

        shard_coverage = {i: 0 for i in range(n_shards)}
        for row in shards_rows:
            shard_coverage[row["shard"]] = row["replicas"]

        covered  = sum(1 for v in shard_coverage.values() if v > 0)
        is_ready = covered == n_shards

        return {
            "model":          model_name,
            "ready":          is_ready,
            "active_nodes":   active,
            "total_nodes":    total,
            "shards_total":   n_shards,
            "shards_covered": covered,
            "shard_replicas": shard_coverage,
            "min_replicas":   min(shard_coverage.values()),
        }

    def _get_node(self, node_id: str) -> Optional[Node]:
        """Retorna el Node para un node_id, o None si no existe."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT node_id, shard, model_name, hardware_info, "
                "registered_at, last_heartbeat, is_active "
                "FROM nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
        if not row:
            return None
        return Node(
            node_id        = row["node_id"],
            shard          = row["shard"],
            model_name     = row["model_name"],
            hardware_info  = row["hardware_info"],
            registered_at  = row["registered_at"],
            last_heartbeat = row["last_heartbeat"],
            is_active      = bool(row["is_active"]),
        )

    # ── Mantenimiento ─────────────────────────────────────────────────

    def _mark_stale_nodes(self):
        """Marca como inactivos los nodos que no enviaron heartbeat a tiempo."""
        cutoff = time.time() - NODE_TIMEOUT
        with self._conn() as conn:
            conn.execute(
                "UPDATE nodes SET is_active=0 WHERE last_heartbeat < ?", (cutoff,)
            )
