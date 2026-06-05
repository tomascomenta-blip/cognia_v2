"""
tests/test_cache_warmer.py — Unit tests for CacheWarmer (cognia/reasoning/cache_warmer.py)

All tests are in-memory using MagicMock. No real cognia instances or DB required.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call


def _make_warmer(thought_cache=None, busy=False):
    """Helper: build a CacheWarmer with mocked dependencies."""
    cognia = MagicMock()
    if busy:
        cognia._inference_active = True
    else:
        # ensure attribute absent so getattr fallback returns False
        del cognia._inference_active

    semantic_cache = MagicMock()
    semantic_cache.lookup.return_value = None  # no hit by default

    # IntentPredictor is imported lazily inside __init__, patch at its source module
    with patch("cognia.reasoning.intent_predictor.IntentPredictor") as MockPredictor:
        MockPredictor.return_value = MagicMock()
        from cognia.reasoning.cache_warmer import CacheWarmer
        warmer = CacheWarmer(cognia, semantic_cache, thought_cache=thought_cache)
    return warmer, cognia, semantic_cache


class TestCacheWarmerInit(unittest.TestCase):
    def test_instantiates_without_error(self):
        warmer, cognia, sem = _make_warmer()
        self.assertFalse(warmer._shutdown)
        self.assertIs(warmer.cognia, cognia)
        self.assertIs(warmer.semantic_cache, sem)

    def test_instantiates_with_thought_cache(self):
        tc = MagicMock()
        warmer, _, _ = _make_warmer(thought_cache=tc)
        self.assertIs(warmer.thought_cache, tc)

    def test_no_thought_cache_by_default(self):
        warmer, _, _ = _make_warmer()
        self.assertIsNone(warmer.thought_cache)


class TestWarmAsync(unittest.TestCase):
    def test_warm_async_returns_immediately(self):
        """warm_async must not block — returns in well under 100ms."""
        warmer, _, _ = _make_warmer()
        warmer._executor = MagicMock()
        t0 = time.monotonic()
        warmer.warm_async("query", "response")
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.1)

    def test_warm_async_submits_to_executor(self):
        warmer, _, _ = _make_warmer()
        warmer._executor = MagicMock()
        warmer.warm_async("q", "r")
        warmer._executor.submit.assert_called_once()

    def test_warm_async_after_shutdown_does_not_submit(self):
        warmer, _, _ = _make_warmer()
        warmer._executor = MagicMock()
        warmer.shutdown()
        warmer.warm_async("q", "r")
        warmer._executor.submit.assert_not_called()


class TestShutdown(unittest.TestCase):
    def test_shutdown_sets_flag(self):
        warmer, _, _ = _make_warmer()
        self.assertFalse(warmer._shutdown)
        warmer.shutdown()
        self.assertTrue(warmer._shutdown)

    def test_shutdown_calls_executor_shutdown(self):
        warmer, _, _ = _make_warmer()
        warmer._executor = MagicMock()
        warmer.shutdown()
        warmer._executor.shutdown.assert_called_once_with(wait=False)


class TestIsCogniaBusy(unittest.TestCase):
    def test_returns_false_when_attr_absent(self):
        warmer, cognia, _ = _make_warmer()
        # _inference_active was deleted in _make_warmer
        self.assertFalse(warmer._is_cognia_busy())

    def test_returns_true_when_inference_active(self):
        warmer, cognia, _ = _make_warmer(busy=True)
        self.assertTrue(warmer._is_cognia_busy())

    def test_returns_false_when_inference_active_false(self):
        warmer, cognia, _ = _make_warmer()
        cognia._inference_active = False
        self.assertFalse(warmer._is_cognia_busy())


class TestGenerate(unittest.TestCase):
    def test_generate_uses_respond_and_returns_string(self):
        warmer, cognia, _ = _make_warmer()
        cognia.respond.return_value = "some answer text"
        result = warmer._generate("test query")
        self.assertEqual(result, "some answer text")
        cognia.respond.assert_called_once_with("test query")

    def test_generate_falls_back_to_infer_when_no_respond(self):
        warmer, cognia, _ = _make_warmer()
        # Remove respond so hasattr returns False
        del cognia.respond
        cognia.infer.return_value = "infer answer"
        result = warmer._generate("test query")
        self.assertEqual(result, "infer answer")

    def test_generate_returns_none_on_exception(self):
        warmer, cognia, _ = _make_warmer()
        cognia.respond.side_effect = RuntimeError("connection failed")
        result = warmer._generate("test query")
        self.assertIsNone(result)

    def test_generate_returns_text_attr_from_respond_result(self):
        warmer, cognia, _ = _make_warmer()
        obj = MagicMock()
        obj.__class__ = object  # not a str
        obj.text = "response via .text"
        # Make respond return something that is NOT a str but has .text
        cognia.respond.return_value = obj
        result = warmer._generate("q")
        self.assertEqual(result, "response via .text")


class TestWarmForQuery(unittest.TestCase):
    def test_skips_on_semantic_cache_hit(self):
        warmer, cognia, sem = _make_warmer()
        sem.lookup.return_value = "x" * 25  # len > 20
        warmer._warm_for_query("what is python?")
        # Should return early — generate never called
        cognia.respond.assert_not_called()
        sem.store.assert_not_called()

    def test_skips_on_thought_cache_hit(self):
        tc = MagicMock()
        tc.lookup.return_value = "cached thought"
        warmer, cognia, sem = _make_warmer(thought_cache=tc)
        sem.lookup.return_value = None  # no semantic hit
        warmer._warm_for_query("what is python?")
        cognia.respond.assert_not_called()
        sem.store.assert_not_called()

    def test_skips_when_warming_lock_held(self):
        warmer, cognia, sem = _make_warmer()
        sem.lookup.return_value = None
        # Pre-acquire the lock so trylock fails
        warmer._warming_lock.acquire()
        try:
            warmer._warm_for_query("what is python?")
            cognia.respond.assert_not_called()
            sem.store.assert_not_called()
        finally:
            warmer._warming_lock.release()

    def test_stores_response_when_not_cached(self):
        warmer, cognia, sem = _make_warmer()
        sem.lookup.return_value = None
        cognia.respond.return_value = "a" * 15  # len > 10
        warmer._warm_for_query("what is python?")
        sem.store.assert_called_once_with("what is python?", "a" * 15, model="cip_warmer")


if __name__ == "__main__":
    unittest.main()
