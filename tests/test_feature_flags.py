"""
tests/test_feature_flags.py
============================
6 tests for FeatureFlagManager.
"""

import os
import tempfile
import pytest

from cognia.features.feature_flags import FeatureFlagManager
from storage.db_pool import close_pool


@pytest.fixture
def mgr(tmp_path):
    db = str(tmp_path / "test_flags.db")
    m = FeatureFlagManager(db_path=db)
    yield m
    close_pool(db)


def test_is_enabled_free_tier_free_flag(mgr):
    """free tier + free flag => True"""
    assert mgr.is_enabled("semantic_search", "free") is True


def test_is_enabled_free_tier_pro_flag(mgr):
    """free tier + pro flag => False"""
    assert mgr.is_enabled("self_critique", "free") is False


def test_is_enabled_pro_tier_pro_flag(mgr):
    """pro tier + pro flag => True"""
    assert mgr.is_enabled("self_critique", "pro") is True


def test_set_flag_updates_value(mgr):
    """set_flag disables a flag and is_enabled returns False afterward"""
    assert mgr.is_enabled("semantic_search", "free") is True
    result = mgr.set_flag("semantic_search", False)
    assert result is True
    assert mgr.is_enabled("semantic_search", "free") is False


def test_get_accessible_returns_correct_subset(mgr):
    """free tier should not have access to pro/enterprise flags"""
    accessible_free = set(mgr.get_accessible("free"))
    accessible_pro = set(mgr.get_accessible("pro"))
    # self_critique is pro-only — not in free, yes in pro
    assert "self_critique" not in accessible_free
    assert "self_critique" in accessible_pro
    # debug_endpoints is enterprise-only — not in pro
    assert "debug_endpoints" not in accessible_pro
    # free flags present for free
    assert "semantic_search" in accessible_free


def test_get_all_returns_10_flags(mgr):
    """get_all() must return exactly 10 seeded flags"""
    flags = mgr.get_all()
    assert len(flags) == 10
    names = {f["name"] for f in flags}
    expected = {
        "semantic_search", "proactive_engine", "auto_notes", "feedback_learning",
        "long_term_memory", "self_critique", "recommendations", "achievements",
        "spaced_repetition", "debug_endpoints",
    }
    assert names == expected
