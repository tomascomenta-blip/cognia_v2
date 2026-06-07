"""
cognia/memory/long_term_consolidator.py
========================================
Long-term memory consolidation: scans episodic memory for recurring patterns
and promotes them to durable KG facts.
"""

import re
import threading
import time
from typing import List

from storage.db_pool import get_pool
from cognia.config import DB_PATH
from cognia.logger_config import get_logger

_logger = get_logger(__name__)

# Matches capitalized words (named entities) and quoted terms
_ENTITY_RE = re.compile(r'"([^"]{2,40})"|\'([^\']{2,40})\'|([A-Z][a-zA-Z0-9_\-]{1,39})')

# Avoid promoting noise words that happen to be capitalized
_STOPWORDS = frozenset({
    "The", "This", "That", "These", "Those", "A", "An", "In", "On",
    "At", "To", "Of", "For", "With", "By", "And", "Or", "But", "Is",
    "Are", "Was", "Were", "Has", "Have", "Had", "I", "You", "We",
    "He", "She", "It", "They", "My", "Your", "Our", "His", "Her",
    "Its", "Their", "Me", "Him", "Us", "Them", "Si", "No", "El",
    "La", "Los", "Las", "Un", "Una",
})

# Rolling window for entity scanning (seconds in 30 days)
_WINDOW_S = 30 * 24 * 3600

# Source tag used when inserting KG triples — allows precise querying later
_KG_SOURCE = "recurrente_para"


def _extract_entities(text: str) -> List[str]:
    entities = []
    for m in _ENTITY_RE.finditer(text):
        entity = m.group(1) or m.group(2) or m.group(3)
        if entity and entity not in _STOPWORDS and len(entity) >= 2:
            entities.append(entity.lower())
    return entities


class LongTermConsolidator:

    def __init__(self, db_path: str = DB_PATH):
        self._db = db_path

    def consolidate(self, user_id: str, min_occurrences: int = 3) -> int:
        """
        Scans episodic_memory for recurring entities in the last 30 days.
        Promotes entities appearing >= min_occurrences times to KG.
        Returns count of new KG facts added.
        """
        cutoff = time.time() - _WINDOW_S
        entity_counts: dict = {}

        try:
            with get_pool(self._db).get() as conn:
                # timestamp column is TEXT (ISO format); compare as unix epoch via strftime
                rows = conn.execute(
                    "SELECT observation FROM episodic_memory "
                    "WHERE CAST(strftime('%s', timestamp) AS REAL) >= ? "
                    "AND forgotten = 0",
                    (cutoff,)
                ).fetchall()
        except Exception as exc:
            # Table may not exist in some environments — fail silently
            _logger.debug("consolidate: episodic_memory query failed: %s", exc)
            return 0

        for (observation,) in rows:
            if not observation:
                continue
            for entity in _extract_entities(observation):
                entity_counts[entity] = entity_counts.get(entity, 0) + 1

        recurring = [e for e, c in entity_counts.items() if c >= min_occurrences]
        if not recurring:
            return 0

        # Import KG here to avoid circular import at module level
        from cognia.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph(db_path=self._db)

        added = 0
        for entity in recurring:
            # add_triple normalises unknown predicates to related_to;
            # source=_KG_SOURCE lets us retrieve only these facts later
            is_new = kg.add_triple(
                subject=user_id,
                predicate="related_to",
                obj=entity,
                weight=0.8,
                source=_KG_SOURCE,
            )
            if is_new:
                added += 1

        if added:
            _logger.info("consolidate: %d new KG facts for user=%s", added, user_id)
        return added

    def get_consolidated_facts(self, user_id: str, limit: int = 5) -> List[str]:
        """Returns entity strings promoted from episodic memory for this user."""
        try:
            with get_pool(self._db).get() as conn:
                rows = conn.execute(
                    "SELECT object FROM knowledge_graph "
                    "WHERE subject=? AND source=? "
                    "ORDER BY weight DESC LIMIT ?",
                    (user_id.lower(), _KG_SOURCE, limit)
                ).fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            _logger.debug("get_consolidated_facts failed: %s", exc)
            return []

    def get_summary(self, user_id: str) -> str:
        """Returns a formatted summary string or '' if no consolidated facts."""
        facts = self.get_consolidated_facts(user_id)
        if not facts:
            return ""
        joined = ", ".join(f.title() for f in facts)
        return f"Temas recurrentes: {joined} ({len(facts)} temas)"


class ConsolidationWorker:
    """
    Daemon thread: runs consolidate("default") every 300 seconds.
    Started once at application startup.
    """

    _INTERVAL_S = 300

    def __init__(self, db_path: str = DB_PATH):
        self._db = db_path
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="cognia-consolidation"
        )

    def start(self) -> None:
        self._thread.start()
        _logger.info("ConsolidationWorker started (interval=%ds)", self._INTERVAL_S)

    def _loop(self) -> None:
        consolidator = LongTermConsolidator(db_path=self._db)
        while True:
            try:
                n = consolidator.consolidate("default", min_occurrences=3)
                if n:
                    _logger.info("ConsolidationWorker: %d new facts", n)
            except Exception as exc:
                _logger.debug("ConsolidationWorker error: %s", exc)
            time.sleep(self._INTERVAL_S)
