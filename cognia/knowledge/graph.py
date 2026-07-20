"""
cognia/knowledge/graph.py
==========================
Grafo de conocimiento simbólico con relaciones tipadas.
Almacena en SQLite + capa opcional en memoria con networkx.
"""

import re
import time
from datetime import datetime
from typing import List, Tuple, Optional
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH, KG_STOPWORDS, HAS_NETWORKX
from ..logger_config import get_logger as _get_kg_logger
_kg_logger = _get_kg_logger(__name__)

# Articles/stopwords to strip when normalizing entity strings
_STRIP_ARTICLES = re.compile(
    r'^\s*(?:el|la|los|las|un|una|unos|unas|the|a|an)\s+', re.IGNORECASE
)

# Common stop words too short/generic to be useful entities
_ENTITY_STOPWORDS = frozenset({
    "que", "qué", "es", "son", "un", "una", "el", "la", "los", "las",
    "de", "del", "en", "y", "o", "a", "al", "lo", "se", "su", "sus",
    "con", "por", "para", "pero", "como", "cómo", "más", "muy", "también",
    "the", "is", "are", "was", "were", "has", "have", "had", "can", "could",
    "this", "that", "these", "those", "and", "or", "but", "in", "on", "at",
    "to", "of", "for", "with", "by", "from", "not", "be", "been",
})

# Extraction patterns: (regex, predicate, subject_group, object_group)
# Groups: 1=subject, 2=object (or None to use label fallback)
_EXTRACT_PATTERNS: List[Tuple] = [
    # "X is a Y" / "X es un/una Y"
    (re.compile(
        r'\b(.+?)\s+(?:es\s+un[ao]?|is\s+an?)\s+(.+?)(?:[.,;]|$)',
        re.IGNORECASE), "is_a"),
    # "X es Y" (descriptor, not article+noun)
    (re.compile(
        r'\b(.{3,40}?)\s+es\s+([a-záéíóúñ][a-záéíóúñ ]{2,40}?)(?:[.,;]|$)',
        re.IGNORECASE), "has_property"),
    # "X is Y" (descriptor)
    (re.compile(
        r'\b(.{3,40}?)\s+is\s+([a-z][a-z ]{2,40}?)(?:[.,;]|$)',
        re.IGNORECASE), "has_property"),
    # "X tiene Y" / "X has Y"
    (re.compile(
        r'\b(.+?)\s+(?:tiene|has)\s+(.+?)(?:[.,;]|$)',
        re.IGNORECASE), "tiene"),
    # "X puede Y" / "X can Y"
    (re.compile(
        r'\b(.+?)\s+(?:puede|can)\s+(.+?)(?:[.,;]|$)',
        re.IGNORECASE), "puede"),
    # "X fue creado por Y" / "X was created by Y"
    (re.compile(
        r'\b(.+?)\s+(?:fue\s+creado\s+por|was\s+created\s+by)\s+(.+?)(?:[.,;]|$)',
        re.IGNORECASE), "creado_por"),
    # "X pertenece a Y" / "X belongs to Y"
    (re.compile(
        r'\b(.+?)\s+(?:pertenece\s+a|belongs\s+to)\s+(.+?)(?:[.,;]|$)',
        re.IGNORECASE), "pertenece_a"),
]

# Map auto-extraction predicates to valid KG predicates
_PRED_MAP = {
    "is_a": "is_a",
    "has_property": "has_property",
    "tiene": "has_property",
    "puede": "capable_of",
    "creado_por": "related_to",
    "pertenece_a": "part_of",
}

_AUTO_WEIGHT = 0.6

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
        "has_property", "opposite_of", "instance_of", "used_for", "located_in",
        # relaciones de CÓDIGO (code_graph.py, 2026-07-14): el código del
        # repo vive en el MISMO grafo (un solo KG, no dos sistemas); sin
        # estas, add_triple degradaba los predicados de código a related_to
        # y el grafo perdía la dirección semántica (deps vs dependientes).
        "importa", "define", "tiene_metodo", "llama_a",
    }

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self._graph = None
        self._dirty = True
        self._ensure_last_accessed_column()

    def _ensure_last_accessed_column(self):
        """Add last_accessed column if not present (idempotent migration)."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            try:
                c.execute(
                    "ALTER TABLE knowledge_graph ADD COLUMN last_accessed REAL DEFAULT 0.0"
                )
                conn.commit()
            except Exception:
                # Column already exists — ignore
                pass
        finally:
            conn.close()

    def _get_graph(self):
        if not HAS_NETWORKX:
            return None
        if self._dirty or self._graph is None:
            self._graph = nx.DiGraph()
            conn = db_connect(self.db)
            try:
                c = conn.cursor()
                c.execute("SELECT subject, predicate, object, weight FROM knowledge_graph")
                for subj, pred, obj, weight in c.fetchall():
                    self._graph.add_edge(subj, obj, relation=pred, weight=weight)
            finally:
                conn.close()
            self._dirty = False
        return self._graph

    def add_triple(self, subject: str, predicate: str, obj: str,
                   weight: float = 1.0, source: str = "learned") -> bool:
        """Agrega o refuerza una relación. Retorna True si fue nueva."""
        predicate = predicate.lower().strip()
        if predicate not in self.VALID_RELATIONS:
            _kg_logger.debug(
                "add_triple: predicado '%s' no reconocido → 'related_to' (%s→%s)",
                predicate, subject, obj,
            )
            predicate = "related_to"
        subject = subject.lower().strip()
        obj = obj.lower().strip()

        conn = db_connect(self.db)
        try:
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
        finally:
            conn.close()
        self._dirty = True
        return is_new

    def get_facts(self, concept: str, predicate: str = None) -> list:
        # add_triple/_normalize_entity guardan subject/object SIEMPRE en minusculas
        # y la columna es TEXT con collation BINARY (case-sensitive). Sin normalizar
        # aca, get_facts('Python') no matcheaba la fila 'python' y devolvia [] ->
        # kg_buscar reportaba 'sin hechos' para cualquier concepto capitalizado
        # (nombres propios, el caso comun). Igualar a como se almacena.
        concept = concept.lower().strip()
        if predicate:
            predicate = predicate.lower().strip()
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            if predicate:
                c.execute("""
                    SELECT id, subject, predicate, object, weight FROM knowledge_graph
                    WHERE (subject=? OR object=?) AND predicate=?
                    ORDER BY weight DESC LIMIT 20
                """, (concept, concept, predicate))
            else:
                c.execute("""
                    SELECT id, subject, predicate, object, weight FROM knowledge_graph
                    WHERE subject=? OR object=?
                    ORDER BY weight DESC LIMIT 20
                """, (concept, concept))
            raw = c.fetchall()
            if raw:
                now = time.time()
                c.executemany(
                    "UPDATE knowledge_graph SET last_accessed=? WHERE id=?",
                    [(now, r[0]) for r in raw],
                )
                conn.commit()
            rows = [{"subject": r[1], "predicate": r[2], "object": r[3], "weight": r[4]}
                    for r in raw]
        finally:
            conn.close()
        return rows

    def get_ancestors(self, concept: str, max_depth: int = 4) -> list:
        ancestors = []
        current = concept.lower()
        visited = {current}
        conn = db_connect(self.db)
        try:
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
        finally:
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
        try:
            c = conn.cursor()
            concept = concept.lower()
            if predicate:
                c.execute("""
                    SELECT object, weight FROM knowledge_graph
                    WHERE subject=? AND predicate=? ORDER BY weight DESC LIMIT 10
                """, (concept, predicate))
                rows = c.fetchall()
                return [{"concept": r[0], "weight": r[1]} for r in rows]
            else:
                c.execute("""
                    SELECT object, predicate, weight FROM knowledge_graph
                    WHERE subject=? ORDER BY weight DESC LIMIT 15
                """, (concept,))
                rows = c.fetchall()
                return [{"concept": r[0], "relation": r[1], "weight": r[2]} for r in rows]
        finally:
            conn.close()

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

    def _get_isa_parents(self, concept: str) -> list:
        """Return direct is_a parents of concept (one hop). Updates last_accessed."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, object FROM knowledge_graph WHERE subject=? AND predicate='is_a' ORDER BY weight DESC",
                (concept.lower(),),
            )
            rows = c.fetchall()
            if rows:
                now = time.time()
                ids = [r[0] for r in rows]
                c.executemany(
                    "UPDATE knowledge_graph SET last_accessed=? WHERE id=?",
                    [(now, rid) for rid in ids],
                )
                conn.commit()
        finally:
            conn.close()
        return [r[1] for r in rows]

    def _get_direct_facts(self, concept: str) -> list:
        """Return non-is_a facts where concept is subject. Updates last_accessed."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, predicate, object FROM knowledge_graph WHERE subject=? AND predicate != 'is_a' ORDER BY weight DESC LIMIT 10",
                (concept.lower(),),
            )
            rows = c.fetchall()
            if rows:
                now = time.time()
                ids = [r[0] for r in rows]
                c.executemany(
                    "UPDATE knowledge_graph SET last_accessed=? WHERE id=?",
                    [(now, rid) for rid in ids],
                )
                conn.commit()
        finally:
            conn.close()
        return [f"{concept} {pred} {obj}" for pred, obj in [(r[1], r[2]) for r in rows]]

    def get_inherited_facts(self, concept: str, max_depth: int = 2) -> list:
        """Return facts inherited via is_a chain up to max_depth hops."""
        inherited = []
        visited = set()
        queue = [(concept.lower(), 0)]
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            for parent in self._get_isa_parents(current):
                if parent not in visited:
                    queue.append((parent, depth + 1))
                    for fact in self._get_direct_facts(parent):
                        entry = f"{concept} (via {parent}): {fact}"
                        if entry not in inherited:
                            inherited.append(entry)
        return inherited[:8]

    def stats(self) -> dict:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM knowledge_graph")
            total = c.fetchone()[0]
            c.execute("SELECT predicate, COUNT(*) FROM knowledge_graph GROUP BY predicate ORDER BY COUNT(*) DESC")
            by_rel = dict(c.fetchall())
            c.execute("SELECT COUNT(DISTINCT subject) FROM knowledge_graph")
            nodes = c.fetchone()[0]
        finally:
            conn.close()
        return {"total_edges": total, "nodes": nodes, "by_relation": by_rel}

    # ── Auto-extraction from text ─────────────────────────────────────

    @staticmethod
    def _normalize_entity(text: str) -> str:
        """Lowercase, strip leading articles, collapse whitespace."""
        text = text.strip().lower()
        text = _STRIP_ARTICLES.sub("", text).strip()
        text = re.sub(r'\s+', ' ', text)
        return text

    def extract_and_store(self, text: str, source: str = "conversation") -> list:
        """
        Extract subject-predicate-object triples from text using pattern matching.
        Returns list of (s, p, o) triples that were newly added.

        Handles both English and Spanish via regex patterns.
        Weight is fixed at 0.6 (lower confidence than user-taught facts).
        Silently skips duplicates, short/stopword entities, and pattern failures.
        """
        added: list = []
        # Process sentence by sentence to reduce greedy cross-clause matches
        sentences = re.split(r'[.!?\n]+', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            for pattern, raw_pred in _EXTRACT_PATTERNS:
                for m in pattern.finditer(sentence):
                    subj = self._normalize_entity(m.group(1))
                    obj  = self._normalize_entity(m.group(2))
                    # Skip short or stopword entities
                    if len(subj) < 3 or len(obj) < 3:
                        continue
                    if subj in _ENTITY_STOPWORDS or obj in _ENTITY_STOPWORDS:
                        continue
                    # Limit entity length to avoid garbage captures
                    if len(subj) > 60 or len(obj) > 60:
                        continue
                    kg_pred = _PRED_MAP.get(raw_pred, "related_to")
                    is_new = self.add_triple(subj, kg_pred, obj,
                                             weight=_AUTO_WEIGHT, source=source)
                    if is_new:
                        added.append((subj, kg_pred, obj))
        return added

    def get_all_triples(self, limit: int = 1000) -> list:
        """Return all triples ordered by weight descending."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT subject, predicate, object, weight FROM knowledge_graph ORDER BY weight DESC LIMIT ?",
                (limit,),
            )
            rows = c.fetchall()
        finally:
            conn.close()
        return rows

    def get_auto_facts_count(self) -> int:
        """Count of auto-extracted triples (source != 'learned' and != 'user')."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM knowledge_graph WHERE source NOT IN ('learned', 'user')"
            )
            count = c.fetchone()[0]
        finally:
            conn.close()
        return count

    def get_recent_auto_facts(self, limit: int = 10) -> list:
        """Most recently auto-extracted triples with timestamps."""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute(
                """SELECT subject, predicate, object, weight, source, timestamp
                   FROM knowledge_graph
                   WHERE source NOT IN ('learned', 'user')
                   ORDER BY timestamp DESC, id DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = c.fetchall()
        finally:
            conn.close()
        return [
            {
                "subject":   r[0],
                "predicate": r[1],
                "object":    r[2],
                "weight":    r[3],
                "source":    r[4],
                "timestamp": r[5],
            }
            for r in rows
        ]
