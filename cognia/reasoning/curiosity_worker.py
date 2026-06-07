"""
curiosity_worker.py — CuriosityWorker
=======================================
Background thread (daemon) que cada `interval_s` segundos procesa
preguntas pendientes de CuriosityEngine usando GitHubScraper.

Fire-and-forget: nunca bloquea la respuesta principal.
"""

import threading
import time

from cognia.reasoning.curiosity_engine import CuriosityEngine

# Import GitHubScraper lazily to fail silently if unavailable
_GitHubScraper = None
try:
    from cognia.research_engine.github_scraper import GitHubScraper as _GitHubScraper
except ImportError:
    pass


class CuriosityWorker:
    def __init__(self, engine: CuriosityEngine, interval_s: int = 60):
        self._engine = engine
        self._interval = interval_s
        self._stop_flag = threading.Event()
        self._thread: threading.Thread = threading.Thread(
            target=self._run, daemon=True, name="CuriosityWorker"
        )

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    # ── Worker loop ────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_flag.is_set():
            try:
                self._process_batch()
            except Exception:
                pass  # never crash the daemon thread
            self._stop_flag.wait(timeout=self._interval)

    def _process_batch(self) -> None:
        if _GitHubScraper is None:
            return

        pending = self._engine.get_pending(limit=3)
        if not pending:
            return

        scraper = _GitHubScraper(max_results=3)
        for item in pending:
            qid = item["id"]
            question = item["question"]
            try:
                # Extract the core topic from the curiosity question
                # e.g. "¿Qué no entiendo sobre transformers?" → "transformers"
                topic = _extract_topic(question)
                results = scraper.search_repos(topic)
                if results:
                    summary = "; ".join(
                        f"{r.repo_name}: {r.description or 'sin descripcion'}"
                        for r in results[:3]
                    )
                    self._engine.mark_answered(qid, summary)
                else:
                    self._engine.mark_failed(qid)
            except Exception:
                try:
                    self._engine.mark_failed(qid)
                except Exception:
                    pass


def _extract_topic(question: str) -> str:
    """Strip question marks and common interrogative prefixes to get the topic."""
    import re
    # Remove "¿Qué no entiendo sobre X?" → "X"
    # Remove "¿Cuál es el estado del arte en X?" → "X"
    cleaned = re.sub(r"[¿?]", "", question).strip()
    patterns = [
        r"(?:qué|que)\s+no\s+entiendo\s+sobre\s+(.+)",
        r"(?:cuál|cual)\s+es\s+el\s+estado\s+del\s+arte\s+en\s+(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, cleaned, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip("?").strip()
    # Fallback: last few words
    words = cleaned.split()
    return " ".join(words[-3:]) if len(words) > 3 else cleaned
