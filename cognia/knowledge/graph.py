"""
cognia/knowledge/graph.py
==========================
Grafo de conocimiento simbólico con relaciones tipadas.
Almacena en SQLite + capa opcional en memoria con networkx.
"""

from datetime import datetime
from typing import List, Tuple, Optional
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH, KG_STOPWORDS, HAS_NETWORKX

if HAS_NETWORKX:
    import networkx as nx


class KnowledgeGraph:
    """
    Grafo de conocimiento simbólico con relaciones tipadas.

    Relaciones soportadas:
      is_a, part_of, causes, capable_of, related_to,
      has_property, opposite_of, instance_of, used_for, located_in
    """

    VALID_RELATIONS = {
        "is_a", "part_of", "causes", "capable_of", "related_to",
        "has_property", "opposite_of", "instance_of", "used_for", "located_in"
    }

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self._graph = None
        self._dirty = True

    def _get_graph(self):
        if not HAS_NETWORKX:
            return None
        if self._dirty or self._graph is None:
            self._graph = nx.DiGraph()
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT subject, predicate, object, weight FROM knowledge_graph")
            for subj, pred, obj, weight in c.fetchall():
                self._graph.add_edge(subj, obj, relation=pred, weight=weight)
            conn.close()
            self._dirty = False
        return self._graph

    def add_triple(self, subject: str, predicate: str, obj: str,
                   weight: float = 1.0, source: str = "learned") -> bool:
        """Agrega o refuerza una relación. Retorna True si fue nueva."""
        predicate = predicate.lower().strip()
        if predicate not in self.VALID_RELATIONS:
            predicate = "related_to"
        subject = subject.lower().strip()
        obj = obj.lower().strip()

        conn = db_connect(self.db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""
            SELECT id, weight FROM knowledge_graph
            WHERE subject=? AND predicate=? AND object=?
        """, (subject, predicate, obj))
        row = c.fetchone()
        is_new = row is None

        if row:
            new_weight = min(3.0, row[1] + weight * 0.3)
            c.execute("UPDATE knowledge_graph SET weight=? WHERE id=?", (new_weight, row[0]))
        else:
            c.execute("""
                INSERT INTO knowledge_graph (subject, predicate, object, weight, source, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (subject, predicate, obj, weight, source, now))

        conn.commit()
        conn.close()
        self._dirty = True
        return is_new

    def get_facts(self, concept: str, predicate: str = None) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        if predicate:
            c.execute("""
                SELECT subject, predicate, object, weight FROM knowledge_graph
                WHERE (subject=? OR object=?) AND predicate=?
                ORDER BY weight DESC LIMIT 20
            """, (concept, concept, predicate))
        else:
            c.execute("""
                SELECT subject, predicate, object, weight FROM knowledge_graph
                WHERE subject=? OR object=?
                ORDER BY weight DESC LIMIT 20
            """, (concept, concept))
        rows = [{"subject": r[0], "predicate": r[1], "object": r[2], "weight": r[3]}
                for r in c.fetchall()]
        conn.close()
        return rows

    def get_ancestors(self, concept: str, max_depth: int = 4) -> list:
        ancestors = []
        current = concept.lower()
        visited = {current}
        conn = db_connect(self.db)
        c = conn.cursor()
        for _ in range(max_depth):
            c.execute("""
                SELECT object FROM knowledge_graph
                WHERE subject=? AND predicate='is_a' ORDER BY weight DESC LIMIT 1
            """, (current,))
            row = c.fetchone()
            if not row or row[0] in visited:
                break
            parent = row[0]
            visited.add(parent)
            ancestors.append(parent)
            current = parent
        conn.close()
        return ancestors

    def graph_path(self, source: str, target: str) -> Optional[list]:
        g = self._get_graph()
        if g is None:
            return None
        try:
            return nx.shortest_path(g, source.lower(), target.lower())
        except Exception:
            return None

    def get_neighbors(self, concept: str, predicate: str = None) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        concept = concept.lower()
        if predicate:
            c.execute("""
                SELECT object, weight FROM knowledge_graph
                WHERE subject=? AND predicate=? ORDER BY weight DESC LIMIT 10
            """, (concept, predicate))
            rows = c.fetchall()
            conn.close()
            return [{"concept": r[0], "weight": r[1]} for r in rows]
        else:
            c.execute("""
                SELECT object, predicate, weight FROM knowledge_graph
                WHERE subject=? ORDER BY weight DESC LIMIT 15
            """, (concept,))
            rows = c.fetchall()
            conn.close()
            return [{"concept": r[0], "relation": r[1], "weight": r[2]} for r in rows]

    def extract_triples_from_text(self, text: str, label: str) -> List[Tuple[str, str, str]]:
        """Extrae triples simples de texto usando patrones lingüísticos."""
        triples = []
        text_lower = text.lower()
        words = text_lower.split()

        for pat in ["es un ", "es una ", "is a ", "is an ", "son ", "are "]:
            if pat in text_lower:
                parts = text_lower.split(pat, 1)
                if len(parts) == 2:
                    subj = parts[0].strip().split()[-1] if parts[0].strip() else label
                    obj = parts[1].strip().split()[0].rstrip(".,;")
                    if subj and obj and len(subj) > 1 and len(obj) > 1:
                        triples.append((subj, "is_a", obj))

        for pat in ["tiene ", "tiene un ", "tiene una ", "has ", "have "]:
            if pat in text_lower:
                parts = text_lower.split(pat, 1)
                if len(parts) == 2:
                    obj = parts[1].strip().split()[0].rstrip(".,;")
                    if obj and len(obj) > 1:
                        triples.append((label, "has_property", obj))

        for pat in ["puede ", "can ", "es capaz de ", "able to "]:
            if pat in text_lower:
                parts = text_lower.split(pat, 1)
                if len(parts) == 2:
                    obj = parts[1].strip().split()[0].rstrip(".,;")
                    if obj and len(obj) > 1:
                        triples.append((label, "capable_of", obj))

        if "causa " in text_lower or "causes " in text_lower:
            pat = "causa " if "causa " in text_lower else "causes "
            parts = text_lower.split(pat, 1)
            if len(parts) == 2:
                subj = parts[0].strip().split()[-1] if parts[0].strip() else label
                obj = parts[1].strip().split()[0].rstrip(".,;")
                if subj and obj:
                    triples.append((subj, "causes", obj))

        if label:
            for word in words:
                if (len(word) > 5 and word not in KG_STOPWORDS
                        and word != label and not word.isdigit()):
                    triples.append((label, "related_to", word))

        return list(set(triples))

    def stats(self) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM knowledge_graph")
        total = c.fetchone()[0]
        c.execute("SELECT predicate, COUNT(*) FROM knowledge_graph GROUP BY predicate ORDER BY COUNT(*) DESC")
        by_rel = dict(c.fetchall())
        c.execute("SELECT COUNT(DISTINCT subject) FROM knowledge_graph")
        nodes = c.fetchone()[0]
        conn.close()
        return {"total_edges": total, "nodes": nodes, "by_relation": by_rel}
