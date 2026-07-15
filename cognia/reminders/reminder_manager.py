"""
cognia/reminders/reminder_manager.py
=====================================
Sistema de recordatorios temporales con background checker daemon.

Table: reminders
  id         INTEGER PRIMARY KEY AUTOINCREMENT
  user_id    TEXT NOT NULL
  title      TEXT NOT NULL
  body       TEXT NOT NULL DEFAULT ''
  fire_at    REAL NOT NULL              -- Unix timestamp
  status     TEXT NOT NULL DEFAULT 'pending'  -- pending|fired|cancelled
  goal_id    INTEGER DEFAULT NULL
  created_at REAL NOT NULL
"""

from __future__ import annotations

import time
import threading
from pathlib import Path

from storage.db_pool import get_pool

_DEFAULT_DB = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")

# Recurrencia (Cal.com nativo, 2026-07-14): calendario/agenda para los
# agentes sin servicios externos. None = disparo único (comportamiento
# previo intacto). daily/weekly = delta fijo; monthly = mismo día del mes
# siguiente (con arrastre correcto de fin de mes).
_RECUR_DELTA = {"daily": 86400.0, "weekly": 604800.0}
_RECUR_VALIDOS = set(_RECUR_DELTA) | {"monthly"}


def _proxima_ocurrencia(fire_at: float, recur: str, ahora: float) -> float:
    """Siguiente fire_at estrictamente futuro respetando la cadencia. Si el
    daemon estuvo caído y se saltó varias, avanza hasta pasar `ahora` (no
    dispara N veces para 'ponerse al día')."""
    import datetime
    if recur in _RECUR_DELTA:
        delta = _RECUR_DELTA[recur]
        prox = fire_at + delta
        if prox <= ahora:
            saltos = int((ahora - prox) // delta) + 1
            prox += saltos * delta
        return prox
    # monthly: sumar meses hasta superar 'ahora' (aritmética de calendario)
    dt = datetime.datetime.fromtimestamp(fire_at)
    while dt.timestamp() <= ahora:
        mes = dt.month + 1
        anio = dt.year + (mes - 1) // 12
        mes = (mes - 1) % 12 + 1
        # arrastre de fin de mes (31 ene -> 28/29 feb)
        import calendar
        dia = min(dt.day, calendar.monthrange(anio, mes)[1])
        dt = dt.replace(year=anio, month=mes, day=dia)
    return dt.timestamp()


def _row_to_dict(row) -> dict:
    d = {
        "id":         row[0],
        "user_id":    row[1],
        "title":      row[2],
        "body":       row[3],
        "fire_at":    row[4],
        "status":     row[5],
        "goal_id":    row[6],
        "created_at": row[7],
    }
    # recur es opcional (columna agregada por migración): las filas viejas
    # y los SELECT de 8 columnas no lo traen -> None (disparo único).
    if len(row) > 8:
        d["recur"] = row[8]
    return d


class ReminderManager:
    """
    Sistema de recordatorios temporales con background checker.
    El daemon thread revisa cada CHECK_INTERVAL segundos y dispara
    los recordatorios vencidos via NotificationCenter.
    """

    CHECK_INTERVAL = 30  # segundos entre checks

    def __init__(self, db_path: str = _DEFAULT_DB):
        self._db = db_path
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._notification_center = None  # se inyecta post-init
        self._ensure_table()
        self._start_checker()

    def set_notification_center(self, nc) -> None:
        """Inyecta referencia al NotificationCenter para disparar notificaciones."""
        self._notification_center = nc

    def _ensure_table(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    body       TEXT NOT NULL DEFAULT '',
                    fire_at    REAL NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'pending',
                    goal_id    INTEGER DEFAULT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_user_status "
                "ON reminders(user_id, status, fire_at)"
            )
            # Migración compatible: columna recur para tablas ya existentes
            # (patrón ALTER TABLE ADD COLUMN, como el KG con last_accessed).
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(reminders)").fetchall()}
            if "recur" not in cols:
                conn.execute(
                    "ALTER TABLE reminders ADD COLUMN recur TEXT DEFAULT NULL")

    def create(
        self,
        user_id: str,
        title: str,
        fire_at: float,
        body: str = "",
        goal_id: int = None,
        recur: str = None,
    ) -> dict:
        """
        Crea un recordatorio con fire_at como Unix timestamp.
        `recur` (None|daily|weekly|monthly): al dispararse un recordatorio
        recurrente se agenda automáticamente su próxima ocurrencia.
        Retorna dict del reminder con id y status='pending'.
        """
        if recur is not None and recur not in _RECUR_VALIDOS:
            raise ValueError(
                f"recur invalido: {recur!r} (validos: {sorted(_RECUR_VALIDOS)})")
        now = time.time()
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (user_id, title, body, fire_at, status, goal_id, created_at, recur) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
                (user_id, title, body, fire_at, goal_id, now, recur),
            )
            row_id = cur.lastrowid
        return {
            "id":         row_id,
            "user_id":    user_id,
            "title":      title,
            "body":       body,
            "fire_at":    fire_at,
            "status":     "pending",
            "goal_id":    goal_id,
            "created_at": now,
            "recur":      recur,
        }

    def create_relative(
        self,
        user_id: str,
        title: str,
        minutes: int,
        body: str = "",
        goal_id: int = None,
    ) -> dict:
        """
        Crea un recordatorio relativo al tiempo actual.
        fire_at = now + minutes * 60
        """
        fire_at = time.time() + minutes * 60
        return self.create(user_id, title, fire_at, body=body, goal_id=goal_id)

    def get_pending(self, user_id: str) -> list:
        """Retorna recordatorios pendientes del usuario ordenados por fire_at ASC."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, body, fire_at, status, goal_id, created_at, recur "
                "FROM reminders WHERE user_id = ? AND status = 'pending' ORDER BY fire_at ASC",
                (user_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def cancel(self, reminder_id: int, user_id: str) -> bool:
        """
        Cancela un recordatorio por id (scoped a user_id).
        Retorna True si fue encontrado y cancelado.
        """
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "UPDATE reminders SET status = 'cancelled' "
                "WHERE id = ? AND user_id = ? AND status = 'pending'",
                (reminder_id, user_id),
            )
            return cur.rowcount > 0

    def _check_and_fire(self) -> None:
        """
        Selecciona recordatorios pendientes con fire_at <= now,
        los marca como fired y crea notificacion via NotificationCenter.
        """
        now = time.time()
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, body, fire_at, status, goal_id, created_at, recur "
                "FROM reminders WHERE status = 'pending' AND fire_at <= ?",
                (now,),
            ).fetchall()

        for row in rows:
            reminder = _row_to_dict(row)
            rid = reminder["id"]

            # Marcar como fired (con lock para evitar doble-fire en entornos concurrentes)
            with self._lock:
                with get_pool(self._db).get() as conn:
                    updated = conn.execute(
                        "UPDATE reminders SET status = 'fired' "
                        "WHERE id = ? AND status = 'pending'",
                        (rid,),
                    ).rowcount
                if not updated:
                    # Otro thread ya lo procesó
                    continue

            # Disparar notificacion via NotificationCenter
            if self._notification_center is not None:
                try:
                    self._notification_center.create(
                        user_id=reminder["user_id"],
                        title=reminder["title"],
                        body=reminder["body"] or f"Recordatorio: {reminder['title']}",
                        level="info",
                        source="reminder",
                    )
                except Exception:
                    pass

            # Bus interno: el disparo queda observable (oficina/analytics)
            try:
                from cognia.events import emit
                emit("recordatorio.disparado", reminder_id=reminder["id"],
                     titulo=reminder["title"], recur=reminder.get("recur"))
            except Exception:
                pass

            # Recurrencia: si es recurrente, agendar la próxima ocurrencia
            # (fila nueva 'pending'; la disparada queda 'fired' = historial).
            if reminder.get("recur"):
                try:
                    prox = _proxima_ocurrencia(
                        reminder["fire_at"], reminder["recur"], now)
                    self.create(reminder["user_id"], reminder["title"], prox,
                                body=reminder["body"],
                                goal_id=reminder["goal_id"],
                                recur=reminder["recur"])
                except Exception:
                    pass

            # Opcional: anotar en el goal si hay goal_id
            if reminder.get("goal_id") is not None:
                try:
                    from cognia.goals.goal_tracker import GoalTracker
                    _gt = GoalTracker(db_path=self._db)
                    # Añadir nota como notificacion de progreso (best-effort)
                    if self._notification_center is not None:
                        self._notification_center.create(
                            user_id=reminder["user_id"],
                            title=f"Revision de meta #{reminder['goal_id']}",
                            body=reminder["title"],
                            level="info",
                            source="reminder",
                        )
                except Exception:
                    pass

    def _start_checker(self) -> None:
        """Lanza el thread daemon que revisa recordatorios cada CHECK_INTERVAL segundos."""
        threading.Thread(target=self._checker_loop, daemon=True, name="reminder-checker").start()

    def _checker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_and_fire()
            except Exception:
                pass
            self._stop.wait(self.CHECK_INTERVAL)

    def stop(self) -> None:
        """Detiene el checker daemon (para tests o shutdown limpio)."""
        self._stop.set()
