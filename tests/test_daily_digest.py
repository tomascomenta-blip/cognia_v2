"""Tests for cognia/social/daily_digest.py"""
import tempfile
import os
import sys
import time

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _make_digest():
    from cognia.social.daily_digest import DailyDigest

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return DailyDigest(db_path=path), path


_REQUIRED_KEYS = {
    "sr_due",
    "goals_pending",
    "new_notes",
    "achievements_unlocked",
    "streak",
    "crystallized_facts",
    "learning_paths_active",
    "top_recommendation",
    "generated_at",
}


def test_generate_returns_all_keys():
    """generate() returns a dict containing every required key."""
    digest, path = _make_digest()
    try:
        data = digest.generate()
        assert isinstance(data, dict)
        for key in _REQUIRED_KEYS:
            assert key in data, f"Missing key: {key}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_format_digest_non_empty():
    """format_digest() returns a non-empty string."""
    digest, path = _make_digest()
    try:
        data = digest.generate()
        text = digest.format_digest(data)
        assert isinstance(text, str)
        assert len(text) > 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_format_digest_contains_header():
    """format_digest() output contains the 'Cognia' header."""
    digest, path = _make_digest()
    try:
        data = digest.generate()
        text = digest.format_digest(data)
        assert "Cognia" in text
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_generate_no_crash_on_empty_db():
    """generate() must not raise an exception against an empty/fresh SQLite DB."""
    digest, path = _make_digest()
    try:
        data = digest.generate()
        assert data["sr_due"] == 0
        assert data["goals_pending"] == 0
        assert data["new_notes"] == 0
        assert data["achievements_unlocked"] == 0
        assert data["streak"] == 0
        assert data["crystallized_facts"] == 0
        assert data["learning_paths_active"] == 0
        assert data["top_recommendation"] == ""
        assert data["generated_at"] <= time.time()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
