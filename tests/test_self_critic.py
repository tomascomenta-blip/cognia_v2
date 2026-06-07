"""
tests/test_self_critic.py -- Unit tests for SelfCritic (Cycle 31A).
"""

import os
import tempfile
import pytest

# Make sure repo root is on path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.reasoning.self_critic import SelfCritic


@pytest.fixture
def critic(tmp_path):
    db = str(tmp_path / "test_critiques.db")
    return SelfCritic(db_path=db)


def test_score_length_ideal(critic):
    """200-char text is in the 100-800 range — should return 1.0."""
    text = "x" * 200
    assert critic._score_length(text) == 1.0


def test_score_length_very_short(critic):
    """Very short text (<50 chars) should return 0.3."""
    text = "hi"
    assert critic._score_length(text) == 0.3


def test_score_clarity_normal_sentence(critic):
    """A normal sentence with varied vocab should score > 0.5."""
    text = "The quick brown fox jumps over the lazy dog near the river bank."
    score = critic._score_clarity(text)
    assert score > 0.5


def test_critique_returns_required_keys(critic):
    """critique() must return dict with 'critique' and 'scores' containing all sub-keys."""
    result = critic.critique("This is a sample response sentence.", "What is this?")
    assert "critique" in result
    assert "scores" in result
    scores = result["scores"]
    for key in ("length", "clarity", "completeness", "overall"):
        assert key in scores
    assert isinstance(result["critique"], str)
    assert len(result["critique"]) > 0


def test_duplicate_critique_no_duplicate_row(critic):
    """Same response text should not insert a duplicate row (INSERT OR IGNORE on hash)."""
    response = "This is an identical response used twice to test deduplication."
    critic.critique(response)
    critic.critique(response)
    recents = critic.get_recent_critiques(limit=10)
    hashes = [r["response_hash"] for r in recents]
    assert len(hashes) == len(set(hashes)), "Duplicate hash found in critiques table"


def test_get_avg_score_returns_float(critic):
    """get_avg_score() must return a float (even when table is empty)."""
    result = critic.get_avg_score(days=7)
    assert isinstance(result, float)


def test_prune_old_records_removes_stale(tmp_path):
    """_prune_old_records() must delete rows older than RETENTION_DAYS."""
    import time
    from storage.db_pool import get_pool

    db = str(tmp_path / "prune_test.db")
    c = SelfCritic(db_path=db)

    # Insert one record manually with a very old timestamp
    old_ts = time.time() - 40 * 86400   # 40 days ago
    with get_pool(db).get() as conn:
        conn.execute(
            "INSERT INTO response_critiques "
            "(response_hash, critique, length_score, clarity_score, "
            "completeness_score, overall_score, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("oldhash", "old critique", 0.5, 0.5, 0.5, 0.5, old_ts),
        )

    # Insert a recent record via critique()
    c.critique("A recent response with good quality text.", "What is quality?")

    before = c.get_recent_critiques(limit=20)
    assert len(before) == 2   # old + recent

    c._prune_old_records()

    after = c.get_recent_critiques(limit=20)
    assert len(after) == 1
    assert after[0]["response_hash"] != "oldhash"


def test_call_count_triggers_prune_at_boundary(tmp_path):
    """critique() must call _prune every PRUNE_EVERY_N calls without error."""
    from cognia.reasoning.self_critic import _PRUNE_EVERY_N

    db = str(tmp_path / "count_test.db")
    c = SelfCritic(db_path=db)
    for i in range(_PRUNE_EVERY_N + 1):
        c.critique(f"Response number {i} with sufficient length to score well.", "test?")
    # Should not raise; call count boundary was crossed
    assert c._call_count == _PRUNE_EVERY_N + 1
