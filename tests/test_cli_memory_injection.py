"""
tests/test_cli_memory_injection.py
==================================
Regression tests for CYCLE 3b: real memory injection in the CLI streaming
fast-path via the HYDRA band router (cognia/context/band_router.py).

Invariants under test (no server, no model -- fakes only):
  1. With seeded memory the block lands INSIDE the last user message and the
     prior history stays byte-identical (the server's cached KV prefix
     survives; injecting before the history would invalidate it every turn).
  2. With no relevant memory the messages are EXACTLY the legacy structure
     (zero overhead on memory-less turns).
  3. The injected block is hard-capped at MEMORY_BLOCK_MAX_CHARS (800).
"""

import copy
import os
import sys
import tempfile
import types

from cognia.context.band_router import (
    HydraContextRouter,
    MEMORY_BLOCK_MAX_CHARS,
)


def _get_cli():
    """Import cognia.cli with a minimal Cognia stub to avoid DB/model loading."""
    if "cognia.cognia" not in sys.modules:
        stub = types.ModuleType("cognia.cognia")
        class _FakeCognia:
            def __init__(self, *a, **kw): pass
        stub.Cognia = _FakeCognia
        sys.modules["cognia.cognia"] = stub

    if "cognia.config" not in sys.modules:
        cfg_stub = types.ModuleType("cognia.config")
        cfg_stub.HAS_RESEARCH_ENGINE = False
        cfg_stub.HAS_PROGRAM_CREATOR = False
        sys.modules["cognia.config"] = cfg_stub

    import cognia.cli as cli
    return cli


# -- Fakes for the router's memory layers (same call signatures as the real
#    PerceptionModule / WorkingMemory / EpisodicMemory / SemanticMemory) ------

class _FakePerception:
    def encode(self, text):
        return [0.5] * 8


class _FakeWorking:
    def __init__(self, entries=None, labels=None):
        self._entries = entries or []
        self._labels = labels or []

    def get_recent(self, n=3):
        return self._entries[-n:]

    def get_context_labels(self):
        return list(self._labels)


class _FakeEpisodic:
    def __init__(self, items=None):
        self._items = items or []

    def retrieve_similar(self, vec, top_k=5):
        return self._items[:top_k]


class _FakeSemantic:
    def __init__(self, items=None):
        self._items = items or []

    def find_related(self, vec, top_k=5):
        return self._items[:top_k]


def _tmp_db_path():
    return os.path.join(tempfile.gettempdir(), "no_such_cognia_db_inj.db")


# -- Fakes for the CLI-side wiring (router already cached on the ai object) --

class _FakeRouter:
    def __init__(self, block):
        self._block = block

    def build_memory_block(self, query, max_chars=MEMORY_BLOCK_MAX_CHARS):
        return self._block


class _FakeAI:
    def __init__(self, block):
        self._hydra_router = _FakeRouter(block)


# ---------------------------------------------------------------------------
# (a) Seeded memory: block inside the LAST user message, history untouched.
# ---------------------------------------------------------------------------

def test_seeded_memory_injected_in_last_user_history_untouched():
    cli = _get_cli()
    block = "[GLOBAL]\n  - episodic[score=0.80]: la capital de francia es paris"
    ai = _FakeAI(block)
    hist = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, que tal"},
    ]
    hist_snapshot = copy.deepcopy(hist)
    raw = "cual es la capital de francia?"

    msgs = cli._build_stream_messages(ai, raw, "sistema", hist)

    assert msgs[0] == {"role": "system", "content": "sistema"}
    # History BYTE-IDENTICAL: the cached KV prefix must survive injection.
    assert msgs[1:3] == hist_snapshot
    last = msgs[-1]
    assert last["role"] == "user"
    assert block in last["content"]
    assert last["content"].startswith("Contexto de memoria")
    assert last["content"].endswith("Pregunta: " + raw)


# ---------------------------------------------------------------------------
# (b) No relevant memory: messages EXACTLY as the legacy fast-path built them.
# ---------------------------------------------------------------------------

def test_no_memory_messages_identical_to_legacy():
    cli = _get_cli()
    ai = _FakeAI("")  # router finds nothing relevant
    hist = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenas"},
    ]
    raw = "contame un chiste"

    msgs = cli._build_stream_messages(ai, raw, "sistema", hist)

    legacy = ([{"role": "system", "content": "sistema"}] + hist
              + [{"role": "user", "content": raw}])
    assert msgs == legacy
    assert msgs[-1]["content"] == raw  # zero overhead, not even a wrapper


def test_router_failure_falls_back_to_plain_message():
    cli = _get_cli()

    class _Boom:
        def build_memory_block(self, q, max_chars=MEMORY_BLOCK_MAX_CHARS):
            raise RuntimeError("boom")

    ai = types.SimpleNamespace(_hydra_router=_Boom())
    hist = [{"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"}]
    raw = "pregunta normal"

    msgs = cli._build_stream_messages(ai, raw, "sistema", hist)

    legacy = ([{"role": "system", "content": "sistema"}] + hist
              + [{"role": "user", "content": raw}])
    assert msgs == legacy


# ---------------------------------------------------------------------------
# (c) Hard cap at MEMORY_BLOCK_MAX_CHARS.
# ---------------------------------------------------------------------------

def test_block_capped_at_max_chars():
    entries = [{"label": "E" * 500, "observation": ""},
               {"label": "F" * 500, "observation": ""},
               {"label": "G" * 500, "observation": ""}]
    labels = [("L%d " % i) + "x" * 300 for i in range(6)]
    epi = [{"label": ("episodio %d " % i) + "e" * 300, "similarity": 0.9 - i * 0.01}
           for i in range(5)]
    sem = [{"concept": ("concepto %d " % i) + "s" * 300, "similarity": 0.8 - i * 0.01}
           for i in range(5)]
    router = HydraContextRouter(
        db_path=_tmp_db_path(),
        perception=_FakePerception(),
        working=_FakeWorking(entries, labels),
        episodic=_FakeEpisodic(epi),
        semantic=_FakeSemantic(sem),
    )
    # >=12 words + recall cues + clause joiner: LOCAL+MEDIA+GLOBAL all active.
    q = ("recuerda todo lo que hablamos antes sobre el proyecto y resume "
         "cada decision tecnica que tomamos juntos en detalle")

    block = router.build_memory_block(q)

    assert block  # there IS memory, so the block is non-empty
    assert len(block) <= MEMORY_BLOCK_MAX_CHARS
    # Prove the cap actually trimmed: the raw assembly exceeds the cap.
    assert len(router.route(q).assembled_context) > MEMORY_BLOCK_MAX_CHARS


# ---------------------------------------------------------------------------
# Router wiring: injected layers are READ (not the self-built ones), and
# query-only items never produce a block on their own.
# ---------------------------------------------------------------------------

def test_injected_layers_feed_global_band():
    epi = [{"label": "la capital de francia es paris", "similarity": 0.92}]
    sem = [{"concept": "francia", "similarity": 0.81}]
    router = HydraContextRouter(
        db_path=_tmp_db_path(),
        perception=_FakePerception(),
        working=_FakeWorking(),
        episodic=_FakeEpisodic(epi),
        semantic=_FakeSemantic(sem),
    )
    block = router.build_memory_block(
        "recuerda lo que dijiste antes sobre francia")
    assert "[GLOBAL]" in block
    assert "paris" in block


def test_no_real_memory_returns_empty_block():
    # Empty layers: LOCAL only holds the redundant 'query: ...' item and any
    # MEDIA summary derives from the query alone -- both filtered, so "".
    router = HydraContextRouter(
        db_path=_tmp_db_path(),
        perception=_FakePerception(),
        working=_FakeWorking(),
        episodic=_FakeEpisodic(),
        semantic=_FakeSemantic(),
    )
    q = ("explicame con mucho detalle todos los pasos para preparar una "
         "pizza napolitana en casa")
    assert router.build_memory_block(q) == ""
