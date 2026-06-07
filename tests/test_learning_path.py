"""
tests/test_learning_path.py
============================
5 tests for LearningPathGenerator.
"""
from __future__ import annotations

import os
import tempfile
import pytest

from cognia.learning.learning_path import LearningPathGenerator


@pytest.fixture()
def gen(tmp_path):
    db = str(tmp_path / "test_lp.db")
    return LearningPathGenerator(db_path=db)


def test_generate_returns_dict_with_steps(gen):
    result = gen.generate("matematica avanzada")
    assert isinstance(result, dict)
    assert "id" in result
    assert "goal" in result
    assert "steps" in result
    assert isinstance(result["steps"], list)
    assert len(result["steps"]) == 5
    assert result["current_step"] == 0


def test_generate_uses_python_template(gen):
    result = gen.generate("aprender python desde cero")
    titles = [s["title"] for s in result["steps"]]
    assert any("Python" in t or "python" in t or "entorno" in t.lower() for t in titles), (
        f"Expected python template steps, got: {titles}"
    )
    assert titles[0] == "Instalar Python y configurar entorno"


def test_get_active_paths_returns_list(gen):
    gen.generate("ingles para negocios")
    gen.generate("git avanzado")
    active = gen.get_active_paths()
    assert isinstance(active, list)
    assert len(active) >= 2
    for p in active:
        assert p["completed"] is False


def test_advance_step_increments_current_step(gen):
    path = gen.generate("web development")
    path_id = path["id"]
    assert path["current_step"] == 0

    advanced = gen.advance_step(path_id)
    assert advanced["current_step"] == 1
    assert advanced["steps"][0]["completed"] is True
    assert advanced["steps"][1]["completed"] is False


def test_get_stats_returns_required_keys(gen):
    gen.generate("machine learning basico")
    stats = gen.get_stats()
    assert "total_paths" in stats
    assert "active" in stats
    assert "completed" in stats
    assert "avg_completion_pct" in stats
    assert stats["total_paths"] >= 1
    assert isinstance(stats["avg_completion_pct"], float)
