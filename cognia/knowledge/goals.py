"""
cognia/knowledge/goals.py
==========================
Sistema de objetivos cognitivos internos con prioridad dinámica.
"""

import json
from datetime import datetime
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH


class GoalSystem:
    """
    Sistema de objetivos cognitivos internos.
    Genera automáticamente objetivos basados en el estado interno y
    aumenta su prioridad si no se resuelven.
    """

    GOAL_TYPES = {
        "consolidar_memoria":    "Consolidar episodios en conceptos semánticos",
        "resolver_contradiccion": "Resolver contradicción cognitiva detectada",
        "repasar_memoria":       "Repasar episodios pendientes (repetición espaciada)",
        "explorar_concepto":     "Explorar concepto con baja confianza",
        "fortalecer_grafo":      "Fortalecer conexiones débiles en el grafo de conocimiento",
        "aprender_nuevo":        "Aprender información nueva para reducir ignorancia",
        "comprimir_conceptos":   "Comprimir episodios similares en abstracciones",
    }

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def add_goal(self, goal_type: str, description: str = "",
                 priority: float = 0.5, metadata: dict = None) -> int:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT id FROM goal_system WHERE goal_type=? AND status='pending'", (goal_type,))
        existing = c.fetchone()
        if existing:
            c.execute("UPDATE goal_system SET priority=MIN(1.0, priority+0.1) WHERE id=?", (existing[0],))
            conn.commit()
            conn.close()
            return existing[0]

        c.execute("""
            INSERT INTO goal_system (goal_type, description, priority, status, created_at, metadata)
            VALUES (?, ?, ?, 'pending', ?, ?)
        """, (goal_type, description or self.GOAL_TYPES.get(goal_type, ""),
              priority, datetime.now().isoformat(), json.dumps(metadata or {})))
        goal_id = c.lastrowid
        conn.commit()
        conn.close()
        return goal_id

    def get_active_goals(self, top_k: int = 5) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, goal_type, description, priority, created_at, metadata
            FROM goal_system WHERE status='pending' ORDER BY priority DESC LIMIT ?
        """, (top_k,))
        rows = [{"id": r[0], "type": r[1], "description": r[2],
                 "priority": r[3], "created_at": r[4],
                 "metadata": json.loads(r[5] or "{}")}
                for r in c.fetchall()]
        conn.close()
        return rows

    def resolve_goal(self, goal_id: int):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("UPDATE goal_system SET status='resolved', resolved_at=? WHERE id=?",
                  (datetime.now().isoformat(), goal_id))
        conn.commit()
        conn.close()

    def auto_generate_goals(self, metacog_state: dict) -> list:
        """Genera objetivos automáticamente según el estado cognitivo."""
        generated = []

        if metacog_state.get("due_for_review", 0) > 3:
            gid = self.add_goal("repasar_memoria",
                                f"{metacog_state['due_for_review']} episodios pendientes",
                                priority=0.7)
            generated.append(gid)

        if metacog_state.get("contradictions_pending", 0) > 0:
            gid = self.add_goal("resolver_contradiccion",
                                f"{metacog_state['contradictions_pending']} contradicciones",
                                priority=0.8)
            generated.append(gid)

        if metacog_state.get("active_memories", 0) > 20 and metacog_state.get("concepts", 0) < 5:
            gid = self.add_goal("consolidar_memoria",
                                "Muchos episodios sin conceptualizar", priority=0.6)
            generated.append(gid)

        if metacog_state.get("error_rate", 0) > 0.4:
            gid = self.add_goal("aprender_nuevo",
                                f"Tasa de error alta: {metacog_state['error_rate']:.0%}",
                                priority=0.9)
            generated.append(gid)

        return generated

    def format_goals(self) -> str:
        goals = self.get_active_goals()
        if not goals:
            return "✅ Sin objetivos cognitivos pendientes."
        lines = [f"🎯 {len(goals)} objetivos activos:\n"]
        for g in goals:
            bar = "█" * int(g["priority"] * 10) + "░" * (10 - int(g["priority"] * 10))
            lines.append(f"  [{g['id']}] {bar} {g['type']}: {g['description']}")
        return "\n".join(lines)
