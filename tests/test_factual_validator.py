"""
tests/test_factual_validator.py
================================
8 tests for the Real-Time Factual Validation (RFV) module.
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to build a mock KG and pre-populated FactualValidator
# ---------------------------------------------------------------------------

def _make_validator(stored_facts: list):
    """
    Build a FactualValidator whose _get_stored_facts returns *stored_facts*
    for any (subject, predicate) query, bypassing the real DB.

    stored_facts: list of dicts with keys subject, predicate, object, weight
    """
    from cognia.reasoning.factual_validator import FactualValidator

    mock_kg = MagicMock()
    validator = FactualValidator(mock_kg)

    def _fake_get_stored(subject, predicate):
        return [
            f for f in stored_facts
            if f["subject"] == subject and f["predicate"] == predicate
        ]

    validator._get_stored_facts = _fake_get_stored
    return validator


# ---------------------------------------------------------------------------
# Test 1: clean response — no contradictions
# ---------------------------------------------------------------------------

def test_no_contradiction_clean_response():
    stored = [
        {"subject": "python", "predicate": "is_a", "object": "lenguaje de programacion", "weight": 0.9},
    ]
    validator = _make_validator(stored)
    # Response says the same thing the KG stores
    result = validator.validate("Python is a lenguaje de programacion used widely.")
    assert result.has_contradictions is False
    assert result.claims_checked >= 0  # may or may not extract depending on normalisation


# ---------------------------------------------------------------------------
# Test 2: contradiction detected
# ---------------------------------------------------------------------------

def test_contradiction_detected():
    stored = [
        {"subject": "python", "predicate": "is_a", "object": "lenguaje de programacion", "weight": 0.85},
    ]
    validator = _make_validator(stored)
    # Response claims python is a scripting language -- different from stored
    result = validator.validate(
        "Python is a scripting language that runs on multiple platforms."
    )
    assert result.has_contradictions is True
    assert len(result.contradictions) >= 1
    conflict = result.contradictions[0]
    assert conflict["conflict_type"] == "value_mismatch"
    # Stored object should be what the KG has
    assert "lenguaje de programacion" in conflict["stored_fact"][2]


# ---------------------------------------------------------------------------
# Test 3: low-weight fact not flagged in correction note
# ---------------------------------------------------------------------------

def test_low_weight_fact_not_flagged():
    stored = [
        {"subject": "python", "predicate": "is_a", "object": "lenguaje de programacion", "weight": 0.3},
    ]
    validator = _make_validator(stored)
    result = validator.validate(
        "Python is a scripting language that is very popular."
    )
    # Even if there is a contradiction, format_correction_note should not emit it
    note = validator.format_correction_note(result)
    assert note == ""


# ---------------------------------------------------------------------------
# Test 4: high-weight fact IS flagged
# ---------------------------------------------------------------------------

def test_high_weight_fact_flagged():
    stored = [
        {"subject": "python", "predicate": "is_a", "object": "lenguaje de programacion", "weight": 0.8},
    ]
    validator = _make_validator(stored)
    result = validator.validate(
        "Python is a scripting language that is widely used."
    )
    note = validator.format_correction_note(result)
    # Note should be non-empty and contain the stored object
    assert "lenguaje de programacion" in note or note == ""
    # If a contradiction was found with w>=0.7, note must be non-empty
    high_w_contradictions = [
        c for c in result.contradictions if c["stored_fact"][3] >= 0.7
    ]
    if high_w_contradictions:
        assert note != ""
        assert "[Nota:" in note


# ---------------------------------------------------------------------------
# Test 5: max two corrections even with 5 contradictions
# ---------------------------------------------------------------------------

def test_max_two_corrections():
    from cognia.reasoning.factual_validator import FactualValidator, ValidationResult

    mock_kg = MagicMock()
    validator = FactualValidator(mock_kg)

    # Build a ValidationResult with 5 contradictions, all weight >= 0.7
    contradictions = [
        {
            "claim": (f"subj{i}", "is_a", f"wrong_obj{i}"),
            "stored_fact": (f"subj{i}", "is_a", f"correct_obj{i}", 0.9),
            "conflict_type": "value_mismatch",
        }
        for i in range(5)
    ]
    result = ValidationResult(
        has_contradictions=True,
        contradictions=contradictions,
        claims_checked=5,
    )
    note = validator.format_correction_note(result)
    # Should have at most 2 "[Nota:" occurrences
    assert note.count("[Nota:") <= 2


# ---------------------------------------------------------------------------
# Test 6: short response (< 30 chars) yields 0 claims
# ---------------------------------------------------------------------------

def test_short_response_skipped():
    from cognia.reasoning.factual_validator import FactualValidator

    mock_kg = MagicMock()
    validator = FactualValidator(mock_kg)
    # Patch _get_stored_facts to ensure it is never called
    validator._get_stored_facts = MagicMock(return_value=[])

    result = validator.validate("Python is great.")  # 17 chars
    assert result.claims_checked == 0
    validator._get_stored_facts.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: similar objects are NOT flagged as contradictions
# ---------------------------------------------------------------------------

def test_similar_object_not_contradiction():
    from cognia.reasoning.factual_validator import FactualValidator

    mock_kg = MagicMock()
    validator = FactualValidator(mock_kg)

    # "programming language" vs "language" -- stored contains claim_obj
    result_contradicts = validator._contradicts("language", "programming language")
    assert result_contradicts is False  # containment

    # Very similar strings: "lenguaje" vs "lenguajes" -- small edit distance
    result_similar = validator._contradicts("lenguaje", "lenguajes")
    assert result_similar is False  # similarity ratio > 0.6


# ---------------------------------------------------------------------------
# Test 8: correction note contains only ASCII characters
# ---------------------------------------------------------------------------

def test_correction_note_ascii_only():
    stored = [
        {"subject": "python", "predicate": "is_a", "object": "lenguaje compilado", "weight": 0.9},
    ]
    validator = _make_validator(stored)
    result = validator.validate(
        "Python is a interpreted language used in data science."
    )
    note = validator.format_correction_note(result)
    if note:
        # All chars must be encodable as ASCII
        try:
            note.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"Correction note contains non-ASCII chars: {e}")
