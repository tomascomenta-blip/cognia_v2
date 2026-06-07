"""
tests/test_persona_advisor.py
==============================
Tests para PersonaAdvisor -- heuristicas de pattern+topic voting.
Mockea UserProfileBuilder y PersonaManager para correr sin BD.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import cognia.persona.persona_advisor as _adv_mod
from cognia.persona.persona_advisor import PersonaAdvisor


# ── Fixtures / helpers ─────────────────────────────────────────────────


def _make_pm_mock(current_persona: str = "default") -> MagicMock:
    mock = MagicMock()
    mock.return_value.get_persona.return_value = {
        "persona": current_persona,
        "custom_instruction": "",
    }
    mock.return_value.set_persona.return_value = True
    return mock


def _patches(profile: dict | None, current_persona: str = "default"):
    """
    Retorna una lista de context managers que parchean:
      - PersonaAdvisor._get_profile -> profile
      - cognia.persona.persona_advisor.PersonaManager -> mock
    """
    advisor = PersonaAdvisor()
    pm_mock = _make_pm_mock(current_persona)
    p1 = patch.object(advisor, "_get_profile", return_value=profile)
    p2 = patch.object(_adv_mod, "PersonaManager", pm_mock)
    return advisor, p1, p2, pm_mock


# ── Tests: recommend() ─────────────────────────────────────────────────


def test_recommend_returns_required_keys():
    """recommend() siempre retorna las 4 claves requeridas."""
    advisor, p1, p2, _ = _patches(profile=None)
    with p1, p2:
        result = advisor.recommend("user_001")

    assert "recommended_persona" in result
    assert "confidence" in result
    assert "reason" in result
    assert "already_set" in result


def test_recommend_asks_code_pattern():
    """Con pattern asks_code dominante, recomienda 'tecnico'."""
    profile = {
        "query_patterns": ["asks_code", "asks_code", "asks_how"],
        "top_topics":     [],
    }
    advisor, p1, p2, _ = _patches(profile=profile)
    with p1, p2:
        result = advisor.recommend("user_002")

    assert result["recommended_persona"] == "tecnico"
    assert result["confidence"] > 0


def test_recommend_asks_why_pattern():
    """Con pattern asks_why dominante, recomienda 'formal'."""
    profile = {
        "query_patterns": ["asks_why", "asks_why", "asks_why"],
        "top_topics":     [],
    }
    advisor, p1, p2, _ = _patches(profile=profile)
    with p1, p2:
        result = advisor.recommend("user_003")

    assert result["recommended_persona"] == "formal"


def test_recommend_no_data_returns_default():
    """Sin patterns ni topics, recomienda 'default' con confidence 0."""
    profile = {
        "query_patterns": [],
        "top_topics":     [],
    }
    advisor, p1, p2, _ = _patches(profile=profile)
    with p1, p2:
        result = advisor.recommend("user_004")

    assert result["recommended_persona"] == "default"
    assert result["confidence"] == 0.0


def test_recommend_none_profile_returns_default():
    """Si get_profile retorna None, recomienda 'default' con confidence 0."""
    advisor, p1, p2, _ = _patches(profile=None)
    with p1, p2:
        result = advisor.recommend("user_005")

    assert result["recommended_persona"] == "default"
    assert result["confidence"] == 0.0


def test_recommend_already_set_true():
    """already_set=True cuando la persona actual coincide con la recomendada."""
    profile = {
        "query_patterns": ["asks_code"],
        "top_topics":     [],
    }
    advisor, p1, p2, _ = _patches(profile=profile, current_persona="tecnico")
    with p1, p2:
        result = advisor.recommend("user_006")

    assert result["already_set"] is True


def test_recommend_already_set_false():
    """already_set=False cuando la persona actual difiere de la recomendada."""
    profile = {
        "query_patterns": ["asks_code"],
        "top_topics":     [],
    }
    advisor, p1, p2, _ = _patches(profile=profile, current_persona="casual")
    with p1, p2:
        result = advisor.recommend("user_007")

    assert result["already_set"] is False


# ── Tests: auto_apply() ────────────────────────────────────────────────


def test_auto_apply_low_confidence_not_applied():
    """auto_apply() no aplica si confidence < min_confidence."""
    profile = {
        "query_patterns": ["asks_code"],
        "top_topics":     [],
    }
    advisor, p1, p2, pm_mock = _patches(profile=profile, current_persona="default")
    with p1, p2:
        # min_confidence=1.1 es imposible de alcanzar
        result = advisor.auto_apply("user_010", min_confidence=1.1)

    assert result["applied"] is False
    pm_mock.return_value.set_persona.assert_not_called()


def test_auto_apply_applies_when_confident_and_not_set():
    """auto_apply() aplica cuando confidence >= min_confidence y not already_set."""
    profile = {
        "query_patterns": ["asks_code", "asks_code", "asks_code"],
        "top_topics":     [],
    }
    advisor, p1, p2, pm_mock = _patches(profile=profile, current_persona="default")
    with p1, p2:
        result = advisor.auto_apply("user_011", min_confidence=0.5)

    assert result["applied"] is True
    assert result["persona"] == "tecnico"
    assert result["confidence"] > 0.5
    pm_mock.return_value.set_persona.assert_called_once_with("user_011", "tecnico")


def test_auto_apply_skips_when_already_set():
    """auto_apply() retorna applied=False si la persona ya esta configurada."""
    profile = {
        "query_patterns": ["asks_code"],
        "top_topics":     [],
    }
    advisor, p1, p2, pm_mock = _patches(profile=profile, current_persona="tecnico")
    with p1, p2:
        result = advisor.auto_apply("user_012", min_confidence=0.0)

    assert result["applied"] is False
    pm_mock.return_value.set_persona.assert_not_called()


# ── Tests: _score_persona() ────────────────────────────────────────────


def test_score_persona_topic_match():
    """Topics con prefijo reconocido deben influir en el voto."""
    advisor = PersonaAdvisor()
    topics  = [{"term": "python"}, {"term": "fastapi"}, {"term": "datos"}]
    persona, confidence = advisor._score_persona([], topics)
    # tecnico: 2 votos (python, fastapi), formal: 1 voto (datos) -> tecnico gana
    assert persona == "tecnico"
    assert confidence == pytest.approx(2 / 3, abs=1e-3)


def test_score_persona_empty_inputs():
    """Sin inputs, retorna ('default', 0.0)."""
    advisor = PersonaAdvisor()
    persona, confidence = advisor._score_persona([], [])
    assert persona == "default"
    assert confidence == 0.0
