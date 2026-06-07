"""
tests/test_cognitive_profile.py
================================
Tests for cognia/intelligence/cognitive_profile.py
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repo root is on path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cognia.intelligence.cognitive_profile as _cp_mod
from cognia.intelligence.cognitive_profile import CognitiveProfile


@pytest.fixture()
def profile_with_empty_db(tmp_path):
    """CognitiveProfile pointed at a fresh temporary DB."""
    db = str(tmp_path / "test_profile.db")
    _cp_mod._DB_PATH = db
    yield CognitiveProfile()
    # Reset so other tests are not affected
    _cp_mod._DB_PATH = None


def test_build_returns_required_keys(profile_with_empty_db):
    """build() must return a dict with all top-level required keys."""
    required = {
        "user_id", "identity", "learning", "goals", "feedback",
        "achievements", "analytics", "notes", "kg_facts",
        "synthesis_ready", "overall_score",
    }
    result = profile_with_empty_db.build("testuser")
    assert isinstance(result, dict)
    for key in required:
        assert key in result, f"Missing key: {key}"


def test_build_overall_score_is_numeric_and_nonnegative(profile_with_empty_db):
    """overall_score must be a number >= 0."""
    result = profile_with_empty_db.build("testuser")
    score = result["overall_score"]
    assert isinstance(score, (int, float))
    assert score >= 0


def test_build_does_not_crash_with_empty_db(tmp_path):
    """build() must not raise when all subsystems have empty/fresh databases."""
    db = str(tmp_path / "empty.db")
    _cp_mod._DB_PATH = db
    try:
        cp = CognitiveProfile()
        result = cp.build("nobody")
        assert isinstance(result, dict)
    finally:
        _cp_mod._DB_PATH = None


def test_get_summary_returns_nonempty_string(profile_with_empty_db):
    """get_summary() must return a non-empty string."""
    summary = profile_with_empty_db.get_summary("testuser")
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_notes_section_has_total_key(profile_with_empty_db):
    """notes section must always contain a 'total' key."""
    result = profile_with_empty_db.build("testuser")
    notes = result["notes"]
    assert "total" in notes
    assert isinstance(notes["total"], int)
