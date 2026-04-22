"""
cognia/reasoning/world_model.py
================================
Modelo del mundo: relaciones entre entidades observadas.
"""

from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH


class WorldModelModule:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def add_relation(self, entity_a: str, relation: str, entity_b: str, strength: float = 0.5):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, strength FROM world_model
            WHERE entity_a=? AND relation=? AND entity_b=?
        """, (entity_a, relation, entity_b))
        row = c.fetchone()
        if row:
            new_str = min(1.0, row[1] + strength * 0.2)
            c.execute("UPDATE world_model SET strength=? WHERE id=?", (new_str, row[0]))
        else:
            c.execute("""
                INSERT INTO world_model (entity_a, relation, entity_b, strength)
                VALUES (?, ?, ?, ?)
            """, (entity_a, relation, entity_b, strength))
        conn.commit()
        conn.close()

    def get_relations(self, entity: str) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT entity_b, relation, strength FROM world_model
            WHERE entity_a=? ORDER BY strength DESC LIMIT 5
        """, (entity,))
        rows = [{"entity": r[0], "relation": r[1], "strength": r[2]} for r in c.fetchall()]
        conn.close()
        return rows
