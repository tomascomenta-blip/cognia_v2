"""
tests/test_response_cache_ram_hit.py
====================================
Regression for a live bug in response_cache.ResponseCache._search_ram: on a RAM
hit it called self._ram.move_to_end(str(id(entry))), but entries are keyed as
"{timestamp}_{id}". The reconstructed key never matched, so OrderedDict.move_to_end
raised KeyError on EVERY in-RAM cache hit -- and ResponseCache.get() is called
unguarded from LanguageEngine.process() (language_engine.py:224), so a warm cache
crashed the chat path instead of serving the cached answer.

The fix tracks the real dict key while scanning, so the LRU touch uses it.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from cognia_v3.interfaces.response_cache import ResponseCache, CACHE_MAX_RAM


@pytest.fixture
def cache():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = ResponseCache(db_path=path)
    yield c
    try:
        os.unlink(path)
    except OSError:
        pass


def test_ram_hit_does_not_raise_and_returns_entry(cache):
    vec = [1.0, 0.0, 0.0, 0.0]
    cache.store("hola mundo", "respuesta cacheada", vec, confidence=0.9)
    # Identical vector -> cosine 1.0 -> guaranteed RAM hit. Must not raise KeyError.
    hit = cache.get("hola mundo", vec)
    assert hit is not None
    assert hit.response == "respuesta cacheada"
    assert cache._hits == 1


def test_ram_hit_refreshes_lru_recency(cache):
    # Two distinct (orthogonal) vectors so each matches only itself.
    cache.store("uno", "r1", [1.0, 0.0], confidence=0.9)
    cache.store("dos", "r2", [0.0, 1.0], confidence=0.9)
    keys_before = list(cache._ram.keys())
    # Hit the OLDEST entry -> it must move to the most-recent position.
    cache.get("uno", [1.0, 0.0])
    keys_after = list(cache._ram.keys())
    assert keys_after[-1] == keys_before[0], "hit entry must become most-recent (LRU)"
    assert set(keys_after) == set(keys_before)


def test_db_layer_hits_with_full_dim_vector(cache):
    """Regression for the persistent-layer dead-cache bug. _persist_to_db used to
    store only entry.vector[:64] (a leftover from a 64-dim embedding era), while
    _search_db compares the full query vector via _cosine(), which returns 0.0 on
    any length mismatch. With today's 384-dim embeddings every DB comparison was a
    length mismatch -> the SQLite layer NEVER hit, so anything evicted from RAM (or
    any entry after a restart) was unrecoverable. Here we store with a >64-dim
    vector, drop the RAM layer to force the DB path, and require a HIT."""
    vec = [float((i * 37) % 11) for i in range(128)]  # 128 dims > 64
    cache.store("pregunta larga", "respuesta persistida", vec, confidence=0.9)
    cache._ram.clear()          # force the lookup through the SQLite layer
    hit = cache.get("pregunta larga", vec)
    assert hit is not None, "persistent DB layer must hit for a >64-dim vector"
    assert hit.response == "respuesta persistida"


def test_ram_eviction_keeps_recently_hit_entry(cache):
    # Fill past the RAM cap; each store evicts the oldest. A recently-hit entry
    # should be protected because the hit moved it to the back.
    base = cache.store("keep", "keep-resp", [1.0, 0.0], confidence=0.9)
    for i in range(CACHE_MAX_RAM + 5):
        cache.store(f"q{i}", f"r{i}", [0.0, 1.0, float(i)], confidence=0.5)
        if i % 10 == 0:
            cache.get("keep", [1.0, 0.0])  # keep refreshing recency
    # The protected entry must still be in RAM.
    assert any(e is base for e in cache._ram.values())
