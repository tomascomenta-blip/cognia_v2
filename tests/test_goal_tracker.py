"""
tests/test_goal_tracker.py
==========================
Unit tests for cognia/goals/goal_tracker.py
"""

import os
import tempfile
import pytest

from cognia.goals.goal_tracker import GoalTracker
from storage.db_pool import close_pool


@pytest.fixture()
def tracker(tmp_path):
    db = str(tmp_path / "test_goals.db")
    gt = GoalTracker(db_path=db)
    yield gt
    close_pool(db)


# ── create_goal ───────────────────────────────────────────────────────

def test_create_goal_returns_dict(tracker):
    goal = tracker.create_goal("user1", "Aprender Python", "Con ejercicios diarios")
    assert isinstance(goal, dict)
    assert "id" in goal
    assert goal["title"] == "Aprender Python"
    assert goal["status"] == "active"
    assert goal["progress_pct"] == 0
    assert goal["user_id"] == "user1"


def test_create_goal_id_increments(tracker):
    g1 = tracker.create_goal("user1", "Meta A")
    g2 = tracker.create_goal("user1", "Meta B")
    assert g2["id"] > g1["id"]


# ── update_progress ───────────────────────────────────────────────────

def test_update_progress_100_sets_completed(tracker):
    goal = tracker.create_goal("user2", "Leer 12 libros")
    updated = tracker.update_progress(goal["id"], 100, user_id="user2")
    assert updated is True
    goals = tracker.get_goals("user2")
    assert goals[0]["status"] == "completed"
    assert goals[0]["completed_at"] is not None


def test_update_progress_clamps_to_100(tracker):
    goal = tracker.create_goal("user3", "Correr 5km")
    updated = tracker.update_progress(goal["id"], 150, user_id="user3")
    assert updated is True
    goals = tracker.get_goals("user3")
    assert goals[0]["progress_pct"] == 100
    assert goals[0]["status"] == "completed"


def test_update_progress_partial(tracker):
    goal = tracker.create_goal("user4", "Aprender Git")
    tracker.update_progress(goal["id"], 45, user_id="user4")
    goals = tracker.get_goals("user4")
    assert goals[0]["progress_pct"] == 45
    assert goals[0]["status"] == "active"


def test_update_progress_returns_false_if_not_found(tracker):
    result = tracker.update_progress(9999, 50)
    assert result is False


# ── get_goals ─────────────────────────────────────────────────────────

def test_get_goals_filters_by_status(tracker):
    tracker.create_goal("user5", "Meta activa")
    g2 = tracker.create_goal("user5", "Meta completada")
    tracker.update_progress(g2["id"], 100)

    active = tracker.get_goals("user5", status="active")
    completed = tracker.get_goals("user5", status="completed")

    assert len(active) == 1
    assert active[0]["title"] == "Meta activa"
    assert len(completed) == 1
    assert completed[0]["title"] == "Meta completada"


def test_get_goals_no_status_returns_all(tracker):
    tracker.create_goal("user6", "Meta 1")
    tracker.create_goal("user6", "Meta 2")
    all_goals = tracker.get_goals("user6")
    assert len(all_goals) == 2


def test_get_goals_isolates_users(tracker):
    tracker.create_goal("userA", "Meta de A")
    tracker.create_goal("userB", "Meta de B")
    assert len(tracker.get_goals("userA")) == 1
    assert len(tracker.get_goals("userB")) == 1


# ── get_active_goals_summary ─────────────────────────────────────────

def test_summary_non_empty_when_active_goals(tracker):
    tracker.create_goal("user7", "Aprender Python")
    tracker.create_goal("user7", "Leer 12 libros")
    summary = tracker.get_active_goals_summary("user7")
    assert summary != ""
    assert "Metas activas:" in summary
    assert "Aprender Python" in summary
    assert "Leer 12 libros" in summary


def test_summary_empty_when_no_active_goals(tracker):
    # user with no goals at all
    summary = tracker.get_active_goals_summary("user_no_goals")
    assert summary == ""


def test_summary_empty_when_all_completed(tracker):
    g = tracker.create_goal("user8", "Completada")
    tracker.update_progress(g["id"], 100)
    summary = tracker.get_active_goals_summary("user8")
    assert summary == ""


def test_summary_shows_progress_pct(tracker):
    g = tracker.create_goal("user9", "Aprender Rust")
    tracker.update_progress(g["id"], 33)
    summary = tracker.get_active_goals_summary("user9")
    assert "33%" in summary


# ── auto_detect_progress ─────────────────────────────────────────────

def test_auto_detect_no_overlap_returns_empty(tracker):
    tracker.create_goal("user10", "Aprender Rust")
    results = tracker.auto_detect_progress("user10", "Hacer ejercicio fisico")
    assert results == []


def test_auto_detect_overlap_returns_list(tracker):
    tracker.create_goal("user11", "Aprender Python programacion")
    results = tracker.auto_detect_progress(
        "user11", "Hoy estuve aprendiendo Python y programacion"
    )
    assert len(results) == 1
    assert results[0]["goal_id"] is not None
    assert results[0]["suggested_increment"] == 5


def test_auto_detect_does_not_update_db(tracker):
    g = tracker.create_goal("user12", "Aprender Python")
    tracker.auto_detect_progress("user12", "Python aprender codigo")
    # progress_pct must still be 0 — auto_detect only suggests
    goals = tracker.get_goals("user12")
    assert goals[0]["progress_pct"] == 0


# ── delete_goal ───────────────────────────────────────────────────────

def test_delete_goal_removes_it(tracker):
    g = tracker.create_goal("user13", "Meta temporal")
    deleted = tracker.delete_goal(g["id"], "user13")
    assert deleted is True
    assert tracker.get_goals("user13") == []


def test_delete_goal_wrong_user_returns_false(tracker):
    g = tracker.create_goal("user14", "Meta de user14")
    result = tracker.delete_goal(g["id"], "other_user")
    assert result is False
    assert len(tracker.get_goals("user14")) == 1


def test_delete_goal_not_found_returns_false(tracker):
    result = tracker.delete_goal(9999, "user15")
    assert result is False
