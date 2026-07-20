"""
cognia/agents/task_queue.py — Phase 23

TaskQueue respaldada por SQLite WAL en cognia_agents.db (separada de cognia_memory.db
para evitar contención con el sleep cycle).

La queue in-memory (queue.PriorityQueue stdlib) actúa como caché caliente.
SQLite es la fuente de verdad para recuperación tras crash.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

from storage.db_pool import get_pool


# ── Estados de tarea ─────────────────────────────────────────────────────────

CREATED    = "CREATED"
PLANNING   = "PLANNING"
EXECUTING  = "EXECUTING"
VERIFYING  = "VERIFYING"
DONE       = "DONE"
FAILED     = "FAILED"
ABORTED    = "ABORTED"

TERMINAL_STATES = {DONE, FAILED, ABORTED}
# Estados intermedios: una tarea que quedo aqui tras un crash hay que recuperarla.
INTERRUPTED_STATES = (PLANNING, EXECUTING, VERIFYING)
# Tope de reintentos por recovery (evita loop de crash infinito). Espeja
# supervisor.MAX_TASK_RETRIES; local para no acoplar (supervisor importa task_queue).
MAX_RECOVERY_ATTEMPTS = 2

# ── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id    TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'CREATED',
    priority   REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL,
    deadline   REAL,
    result     TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_subtasks (
    subtask_id   TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES agent_tasks(task_id),
    description  TEXT NOT NULL,
    tool_required TEXT NOT NULL,
    dependencies TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'pending',
    result       TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_subtasks_task  ON agent_subtasks(task_id);
"""


@dataclass
class TaskRecord:
    task_id:     str
    description: str
    status:      str   = CREATED
    priority:    float = 0.0
    created_at:  float = field(default_factory=time.monotonic)
    deadline:    Optional[float] = None
    result:      Optional[str]   = None
    attempts:    int  = 0

    # prioridad invertida para PriorityQueue (menor número = mayor prioridad)
    def __lt__(self, other: "TaskRecord") -> bool:
        return self.priority > other.priority


class TaskQueue:
    """
    Queue de tareas con persistencia SQLite y caché in-memory.

    Uso:
        tq = TaskQueue("cognia_agents.db")
        task_id = tq.submit("analiza el archivo main.py", priority=1.0)
        task = tq.pop()          # extrae la tarea de mayor prioridad
        tq.update_status(task.task_id, DONE, result="análisis completado")
    """

    def __init__(self, db_path: str = "cognia_agents.db") -> None:
        self._db_path = db_path
        self._mem: queue.PriorityQueue = queue.PriorityQueue()
        self._init_db()
        self.recover()          # resetea tareas colgadas (crash) antes de recargar
        self._reload_pending()

    # ── Inicialización ───────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _reload_pending(self) -> None:
        """Al arrancar: recarga tareas no terminales desde SQLite al cache in-memory."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task_id, description, status, priority, created_at, deadline, result, attempts "
                "FROM agent_tasks WHERE status NOT IN ('DONE','FAILED','ABORTED') "
                "ORDER BY priority DESC"
            ).fetchall()
        for row in rows:
            self._mem.put(self._row_to_record(row))

    def recover(self) -> None:
        """Recovery tras crash/restart: las tareas colgadas en un estado intermedio
        (PLANNING/EXECUTING/VERIFYING) se resetean a CREATED e incrementan attempts
        para que _reload_pending() las re-encole como re-ejecutables. Las que superan
        MAX_RECOVERY_ATTEMPTS se marcan ABORTED (evita loop de crash infinito)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task_id, attempts FROM agent_tasks WHERE status IN (?, ?, ?)",
                INTERRUPTED_STATES,
            ).fetchall()
            for task_id, attempts in rows:
                if (attempts or 0) + 1 > MAX_RECOVERY_ATTEMPTS:
                    conn.execute(
                        "UPDATE agent_tasks SET status=?, result=? WHERE task_id=?",
                        (ABORTED, "RECOVERY_MAX_RETRIES", task_id),
                    )
                else:
                    conn.execute(
                        "UPDATE agent_tasks SET status=?, attempts=attempts+1 WHERE task_id=?",
                        (CREATED, task_id),
                    )

    # ── Operaciones públicas ─────────────────────────────────────────────────

    def submit(self, description: str, priority: float = 0.0, deadline: float = None) -> str:
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            description=description,
            priority=priority,
            deadline=deadline,
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO agent_tasks (task_id, description, status, priority, created_at, deadline) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, description, CREATED, priority, record.created_at, deadline),
            )
        self._mem.put(record)
        return task_id

    def pop(self) -> Optional[TaskRecord]:
        """Extrae la tarea de mayor prioridad. Retorna None si no hay tareas."""
        try:
            record = self._mem.get_nowait()
        except queue.Empty:
            return None
        self.update_status(record.task_id, PLANNING)
        record.status = PLANNING
        return record

    def update_status(
        self,
        task_id: str,
        status: str,
        result: str = None,
    ) -> None:
        with self._conn() as conn:
            if result is not None:
                conn.execute(
                    "UPDATE agent_tasks SET status=?, result=? WHERE task_id=?",
                    (status, result, task_id),
                )
            else:
                conn.execute(
                    "UPDATE agent_tasks SET status=? WHERE task_id=?",
                    (status, task_id),
                )

    def increment_attempts(self, task_id: str) -> int:
        with self._conn() as conn:
            conn.execute(
                "UPDATE agent_tasks SET attempts = attempts + 1 WHERE task_id=?",
                (task_id,),
            )
            row = conn.execute(
                "SELECT attempts FROM agent_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return row[0] if row else 0

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT task_id, description, status, priority, created_at, deadline, result, attempts "
                "FROM agent_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def pending_count(self) -> int:
        return self._mem.qsize()

    def save_subtasks(self, subtasks: list) -> None:
        """Persiste los SubTasks de una tarea (para recovery tras crash)."""
        # task_id es el prefijo de st.id antes del último '_'
        with self._conn() as conn:
            for st in subtasks:
                task_id = "_".join(st.id.split("_")[:-1])
                conn.execute(
                    "INSERT OR REPLACE INTO agent_subtasks "
                    "(subtask_id, task_id, description, tool_required, dependencies, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (st.id, task_id, st.description, st.tool_required,
                     json.dumps(st.dependencies), st.status),
                )

    def update_subtask(self, subtask_id: str, status: str, result: str = None) -> None:
        with self._conn() as conn:
            if result is not None:
                conn.execute(
                    "UPDATE agent_subtasks SET status=?, result=?, attempts=attempts+1 "
                    "WHERE subtask_id=?",
                    (status, result[:4000], subtask_id),
                )
            else:
                conn.execute(
                    "UPDATE agent_subtasks SET status=? WHERE subtask_id=?",
                    (status, subtask_id),
                )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # db_pool (regla del repo: sin sqlite3.connect directo). get() ya aplica
        # WAL + foreign_keys, hace commit al salir y rollback ante excepcion, y
        # devuelve la conexion al pool en vez de cerrarla.
        with get_pool(self._db_path).get() as conn:
            yield conn

    @staticmethod
    def _row_to_record(row: tuple) -> TaskRecord:
        return TaskRecord(
            task_id=row[0],
            description=row[1],
            status=row[2],
            priority=row[3],
            created_at=row[4],
            deadline=row[5],
            result=row[6],
            attempts=row[7],
        )
