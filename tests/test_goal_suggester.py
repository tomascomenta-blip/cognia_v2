"""
tests/test_goal_suggester.py
============================
Tests for GoalSuggester — mocks UserProfileBuilder and GoalTracker so no DB required.
"""

from unittest.mock import MagicMock, patch

import pytest

from cognia.goals.goal_suggester import GoalSuggester


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_profile(topics=None, patterns=None):
    return {
        "top_topics": [{"term": t, "count": 3} for t in (topics or [])],
        "query_patterns": patterns or [],
        "message_count": 10,
        "avg_message_len": 50.0,
    }


def _suggester_with_mocks(profile=None, active_goals=None):
    """Return a GoalSuggester with _load_user_profile and _get_active_goal_titles patched."""
    s = GoalSuggester()
    s._load_user_profile = MagicMock(return_value=profile)
    s._get_active_goal_titles = MagicMock(return_value=active_goals or set())
    return s


# ── tests ─────────────────────────────────────────────────────────────────────

def test_suggest_returns_list_no_profile():
    """suggest() returns list (possibly empty) when there is no user profile."""
    s = _suggester_with_mocks(profile=None)
    result = s.suggest("user_no_profile")
    assert isinstance(result, list)


def test_suggest_empty_profile_returns_generics():
    """With an empty profile, generic suggestions are returned."""
    s = _suggester_with_mocks(profile=_make_profile())
    result = s.suggest("user_empty")
    assert isinstance(result, list)
    # generics should fill the gap
    assert len(result) > 0
    assert all("title" in r and "reason" in r and "source" in r for r in result)


def test_suggest_python_topic_includes_python_suggestion():
    """When profile top_topic is 'python', suggestions include something python-related."""
    s = _suggester_with_mocks(profile=_make_profile(topics=["python"]))
    result = s.suggest("user1")
    titles = [r["title"].lower() for r in result]
    python_keywords = ["python", "pytest", "pypi"]
    assert any(any(kw in t for kw in python_keywords) for t in titles), (
        f"Expected python-related suggestion, got: {titles}"
    )


def test_suggest_code_pattern_includes_code_suggestion():
    """When profile has pattern 'asks_code', suggestions include something code-related."""
    s = _suggester_with_mocks(profile=_make_profile(patterns=["asks_code"]))
    result = s.suggest("user2")
    titles = [r["title"].lower() for r in result]
    code_keywords = ["codigo", "code", "tests", "proyecto"]
    assert any(any(kw in t for kw in code_keywords) for t in titles), (
        f"Expected code-related suggestion, got: {titles}"
    )


def test_suggest_does_not_return_already_active_goal():
    """suggest() must not return a suggestion whose title is already an active goal."""
    active = {"completar un proyecto python de principio a fin"}
    s = _suggester_with_mocks(
        profile=_make_profile(topics=["python"]),
        active_goals=active,
    )
    result = s.suggest("user3")
    for suggestion in result:
        assert suggestion["title"].lower() not in active, (
            f"Active goal appeared in suggestions: {suggestion['title']}"
        )


def test_get_suggestions_context_returns_string_when_suggestions_exist():
    """get_suggestions_context() returns non-empty string when suggestions are available."""
    s = _suggester_with_mocks(profile=_make_profile(topics=["python"]))
    ctx = s.get_suggestions_context("user4")
    assert isinstance(ctx, str)
    assert len(ctx) > 0
    assert "Sugerencias de metas" in ctx


def test_get_suggestions_context_returns_empty_when_all_filtered():
    """get_suggestions_context() returns '' when every candidate is already an active goal."""
    from cognia.goals.goal_suggester import (
        _SUGGESTIONS_BY_TOPIC,
        _PATTERN_SUGGESTIONS,
        _GENERIC_SUGGESTIONS,
    )
    # Build a set that blocks every possible suggestion
    all_titles = set()
    for titles in _SUGGESTIONS_BY_TOPIC.values():
        all_titles.update(t.lower() for t in titles)
    for titles in _PATTERN_SUGGESTIONS.values():
        all_titles.update(t.lower() for t in titles)
    all_titles.update(t.lower() for t in _GENERIC_SUGGESTIONS)

    s = _suggester_with_mocks(
        profile=_make_profile(topics=["python"], patterns=["asks_code"]),
        active_goals=all_titles,
    )
    ctx = s.get_suggestions_context("user5")
    assert ctx == ""


def test_suggest_respects_max_suggestions():
    """suggest() never returns more items than max_suggestions."""
    s = _suggester_with_mocks(
        profile=_make_profile(
            topics=["python", "data", "code", "react", "fastapi"],
            patterns=["asks_code", "asks_how", "asks_list"],
        )
    )
    result = s.suggest("user6", max_suggestions=3)
    assert len(result) <= 3


def test_suggest_source_field_values():
    """Every suggestion dict has a 'source' field with a valid value."""
    s = _suggester_with_mocks(
        profile=_make_profile(topics=["python"], patterns=["asks_how"])
    )
    result = s.suggest("user7")
    valid_sources = {"topic", "pattern", "generic"}
    for r in result:
        assert r["source"] in valid_sources, f"Unexpected source: {r['source']}"
