"""
cognia/reasoning/cache_warmer.py — Proactive Cache Warmer (CIP)

Runs in a background thread after each response.
Warms SemanticResponseCache (and optionally ThoughtCache) for predicted follow-ups.

Design constraints:
  - Fire-and-forget: warm_async() returns immediately, never blocks HTTP response.
  - max_workers=1: avoids thundering-herd on the inference engine.
  - Busy-guard: if cognia is running inference, skip warming silently.
  - All errors are caught; cache warming must never affect the main request.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cognia.semantic_cache import SemanticResponseCache
    from cognia.reasoning.thought_cache import ThoughtCache


class CacheWarmer:
    def __init__(
        self,
        cognia_instance,
        semantic_cache: "SemanticResponseCache",
        thought_cache: Optional["ThoughtCache"] = None,
    ) -> None:
        self.cognia        = cognia_instance
        self.semantic_cache = semantic_cache
        self.thought_cache  = thought_cache
        # Lazy import to avoid circular at module load time
        from cognia.reasoning.intent_predictor import IntentPredictor
        self._predictor    = IntentPredictor()
        # Single background worker — no thundering herd
        self._executor     = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cip_warmer")
        # Busy-guard: held during main inference (set externally or checked via cognia state)
        self._warming_lock = threading.Lock()
        self._shutdown     = False

    # ── public API ─────────────────────────────────────────────────────

    def warm_async(self, query: str, response: str) -> None:
        """
        Fire-and-forget: predict follow-ups and warm caches in background.
        Returns immediately — never blocks the main request.
        """
        if self._shutdown:
            return
        try:
            self._executor.submit(self._warm_batch, query, response)
        except Exception as exc:
            logger.debug("CacheWarmer: submit failed (ignored): %s", exc)

    def shutdown(self) -> None:
        """Graceful shutdown of background threads."""
        self._shutdown = True
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

    # ── private ────────────────────────────────────────────────────────

    def _warm_batch(self, query: str, response: str) -> None:
        """Top-level wrapper called in the background thread."""
        try:
            predicted = self._predictor.predict_followups(query, response, n=3)
            for pq in predicted:
                if self._shutdown:
                    return
                self._warm_for_query(pq)
        except Exception as exc:
            logger.debug("CacheWarmer: _warm_batch error (ignored): %s", exc)

    def _warm_for_query(self, predicted_query: str) -> None:
        """
        For each predicted follow-up:
          1. Check semantic cache — if already there, nothing to do.
          2. Check thought cache — if already there, nothing to do.
          3. If not cached: acquire trylock; if already busy, skip silently.
          4. Generate lightweight response via cognia; store in caches.
        """
        try:
            # Step 1: semantic cache hit?
            cached = self.semantic_cache.lookup(predicted_query)
            if cached and len(cached) > 20:
                logger.debug("CacheWarmer: semantic hit for '%s' (skip)", predicted_query[:60])
                return

            # Step 2: thought cache hit?
            if self.thought_cache is not None:
                try:
                    tc_hit = self.thought_cache.lookup(predicted_query)
                    if tc_hit is not None:
                        logger.debug("CacheWarmer: thought hit for '%s' (skip)", predicted_query[:60])
                        return
                except Exception:
                    pass

            # Step 3: trylock — skip if another warming job is running
            acquired = self._warming_lock.acquire(blocking=False)
            if not acquired:
                logger.debug("CacheWarmer: busy, skipping '%s'", predicted_query[:60])
                return

            try:
                # Step 4: also skip if cognia is already doing inference
                # We check _is_cognia_busy() which looks at a lightweight flag.
                if self._is_cognia_busy():
                    logger.debug("CacheWarmer: cognia busy, skipping '%s'", predicted_query[:60])
                    return

                # Generate response
                warm_response = self._generate(predicted_query)
                if warm_response and len(warm_response) > 10:
                    try:
                        self.semantic_cache.store(predicted_query, warm_response, model="cip_warmer")
                    except Exception as exc:
                        logger.debug("CacheWarmer: store error (ignored): %s", exc)
                    logger.debug(
                        "CacheWarmer: warmed '%s' (%d chars)",
                        predicted_query[:60], len(warm_response),
                    )
            finally:
                self._warming_lock.release()

        except Exception as exc:
            logger.debug("CacheWarmer: _warm_for_query error (ignored): %s", exc)

    def _is_cognia_busy(self) -> bool:
        """
        Best-effort check: returns True if cognia appears to be running inference.
        Checks for a _inference_active flag on the cognia instance (if present).
        Falls back to False (allow warming) when the attribute doesn't exist.
        """
        try:
            return bool(getattr(self.cognia, "_inference_active", False))
        except Exception:
            return False

    def _generate(self, query: str) -> Optional[str]:
        """
        Generate a lightweight response for a predicted query using cognia.
        Uses the synchronous respond() API if available, otherwise falls back
        to the orchestrator's blocking infer path.
        """
        try:
            # Prefer cognia.respond() (CLI path — synchronous)
            if hasattr(self.cognia, "respond") and callable(self.cognia.respond):
                result = self.cognia.respond(query)
                if isinstance(result, str):
                    return result
                # Some respond() return dicts or objects
                if hasattr(result, "text"):
                    return result.text
                return str(result) if result else None

            # Fallback: orchestrator blocking infer (if this is the desktop API context)
            if hasattr(self.cognia, "infer") and callable(self.cognia.infer):
                result = self.cognia.infer(query)
                if hasattr(result, "text"):
                    return result.text
                return str(result) if result else None

        except Exception as exc:
            logger.debug("CacheWarmer: _generate error (ignored): %s", exc)
        return None
