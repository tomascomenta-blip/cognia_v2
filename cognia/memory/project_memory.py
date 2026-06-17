"""
cognia/memory/project_memory.py — FASE 6 (nivel "proyectos" de la taxonomia O2)
==============================================================================
Memoria PERSISTENTE de proyectos/flujos. Completa el nivel "proyectos" de
MEMORY_LEVELS (antes solo cubierto [parcial] por agents/task_queue.py): guarda el
estado de cada corrida de /flujo (objetivo, ruta de etapas, etapas completadas,
informe, score, status) para poder RETOMAR entre sesiones.

NO almacena la conversacion completa — solo el estado util de cada flujo, alineado
con el principio de "guardar conocimiento util, no transcripciones".

Usa storage/db_pool (regla dura del repo: sin sqlite3.connect directo) con el patron
`with get_pool(db).get() as conn:` — el context manager hace commit/rollback y devuelve
la conexion al pool en TODAS las ramas (sin fuga; ver Gotchas.md).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from storage.db_pool import get_pool

_DDL = """
CREATE TABLE IF NOT EXISTS project_flows (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal         TEXT NOT NULL,
    route        TEXT NOT NULL DEFAULT '[]',   -- JSON list de etapas planeadas
    stages_done  TEXT NOT NULL DEFAULT '[]',   -- JSON list de etapas completadas
    report       TEXT NOT NULL DEFAULT '',
    score        REAL,
    status       TEXT NOT NULL DEFAULT 'running',  -- running | done | aborted
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pf_status ON project_flows(status);
CREATE INDEX IF NOT EXISTS idx_pf_updated ON project_flows(updated_at);
"""

_STATUS_RUNNING = "running"
_STATUS_DONE = "done"
_STATUS_ABORTED = "aborted"


def _row_to_dict(row) -> dict:
    return {
        "id":          row[0],
        "goal":        row[1],
        "route":       json.loads(row[2] or "[]"),
        "stages_done": json.loads(row[3] or "[]"),
        "report":      row[4],
        "score":       row[5],
        "status":      row[6],
        "created_at":  row[7],
        "updated_at":  row[8],
    }


_COLS = "id, goal, route, stages_done, report, score, status, created_at, updated_at"


class ProjectMemory:
    """Estado persistente de flujos/proyectos para retomar entre sesiones."""

    def __init__(self, db_path: str = "cognia_memory.db"):
        self.db = db_path
        with get_pool(self.db).get() as conn:
            conn.executescript(_DDL)

    # ── escritura ──────────────────────────────────────────────────────

    def start_flow(self, goal: str, route: List[str]) -> int:
        """Registra el inicio de un flujo (status=running). Devuelve su id."""
        now = datetime.now().isoformat()
        with get_pool(self.db).get() as conn:
            cur = conn.execute(
                "INSERT INTO project_flows "
                "(goal, route, stages_done, report, status, created_at, updated_at) "
                "VALUES (?, ?, '[]', '', ?, ?, ?)",
                (goal, json.dumps(list(route or [])), _STATUS_RUNNING, now, now),
            )
            return cur.lastrowid

    def mark_stage(self, flow_id: int, stage: str) -> None:
        """Anexa una etapa completada al flujo (idempotente por etapa)."""
        now = datetime.now().isoformat()
        with get_pool(self.db).get() as conn:
            row = conn.execute(
                "SELECT stages_done FROM project_flows WHERE id=?", (flow_id,)
            ).fetchone()
            if not row:
                return
            done = json.loads(row[0] or "[]")
            if stage not in done:
                done.append(stage)
            conn.execute(
                "UPDATE project_flows SET stages_done=?, updated_at=? WHERE id=?",
                (json.dumps(done), now, flow_id),
            )

    def finish_flow(self, flow_id: int, report: str = "", score: float = None,
                    status: str = _STATUS_DONE) -> None:
        """Cierra el flujo con el informe final + score + status."""
        now = datetime.now().isoformat()
        with get_pool(self.db).get() as conn:
            conn.execute(
                "UPDATE project_flows SET report=?, score=?, status=?, updated_at=? "
                "WHERE id=?",
                (report or "", score, status, now, flow_id),
            )

    # ── lectura ────────────────────────────────────────────────────────

    def get_flow(self, flow_id: int) -> Optional[dict]:
        with get_pool(self.db).get() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM project_flows WHERE id=?", (flow_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def latest_unfinished(self) -> Optional[dict]:
        """El flujo running mas reciente (para retomar), o None."""
        with get_pool(self.db).get() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM project_flows WHERE status=? "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (_STATUS_RUNNING,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def recent(self, n: int = 5) -> List[dict]:
        with get_pool(self.db).get() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM project_flows "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (max(1, int(n)),),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


_INSTANCE: Optional[ProjectMemory] = None


def get_project_memory(db_path: str = "cognia_memory.db") -> ProjectMemory:
    """Singleton de ProjectMemory (thread-safe basico: idempotente por proceso)."""
    global _INSTANCE
    if _INSTANCE is None or _INSTANCE.db != db_path:
        _INSTANCE = ProjectMemory(db_path)
    return _INSTANCE
