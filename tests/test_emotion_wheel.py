"""
tests/test_emotion_wheel.py
Unit tests for cognia/memory/emotion_wheel.py — Plutchik processor.
No LLM calls, no network. Uses a real temp SQLite DB with mock for db_connect.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from cognia.memory.emotion_wheel import (
    _BOOST_FACTOR,
    _DAMPEN_FACTOR,
    _DOMINANCE_THRESHOLD,
    _LABEL_MAP,
    _PLUTCHIK,
    _detect_imbalance,
    _dominant,
    EmotionReport,
    EmotionWheelProcessor,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("""CREATE TABLE episodic_memory (
        id INTEGER PRIMARY KEY,
        emotion_score REAL DEFAULT 0.5,
        emotion_label TEXT DEFAULT 'neutral',
        importance REAL DEFAULT 1.0,
        forgotten INTEGER DEFAULT 0,
        timestamp TEXT
    )""")
    conn.commit()
    conn.close()
    yield f.name
    os.unlink(f.name)


def _insert_rows(db_path, rows):
    """Helper: insert list of (emotion_score, emotion_label, importance, forgotten, timestamp)."""
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO episodic_memory (emotion_score, emotion_label, importance, forgotten, timestamp) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _future_ts():
    return (datetime.now() + timedelta(hours=1)).isoformat()


def _proc(db_path):
    return EmotionWheelProcessor(db_path)


# ── Pure function: _dominant ──────────────────────────────────────────────────

def test_dominant_returns_none_for_empty_dist():
    assert _dominant({}) is None


def test_dominant_returns_none_below_threshold():
    dist = {k: 0.0 for k in _PLUTCHIK}
    dist["joy"] = _DOMINANCE_THRESHOLD - 0.001
    assert _dominant(dist) is None


def test_dominant_returns_correct_emotion_above_threshold():
    dist = {k: 0.0 for k in _PLUTCHIK}
    dist["sadness"] = 0.50
    assert _dominant(dist) == "sadness"


def test_dominant_exact_threshold_is_included():
    dist = {k: 0.0 for k in _PLUTCHIK}
    dist["fear"] = _DOMINANCE_THRESHOLD
    assert _dominant(dist) == "fear"


# ── Pure function: _detect_imbalance ─────────────────────────────────────────

def test_detect_imbalance_none_when_dominant_is_none():
    dist = {k: 0.125 for k in _PLUTCHIK}
    assert _detect_imbalance(dist, None) is None


def test_detect_imbalance_high_sadness_low_joy():
    dist = {k: 0.0 for k in _PLUTCHIK}
    dist["sadness"] = 0.40  # > 0.35
    dist["joy"] = 0.05      # < 0.10 (opposite of sadness)
    result = _detect_imbalance(dist, "sadness")
    assert result == "high_sadness_low_joy"


def test_detect_imbalance_excess_positive_bias():
    dist = {k: 0.0 for k in _PLUTCHIK}
    dist["joy"] = 0.50
    dist["trust"] = 0.25    # joy+trust = 0.75 > 0.70
    result = _detect_imbalance(dist, "joy")
    assert result == "excess_positive_bias"


def test_detect_imbalance_none_for_balanced_distribution():
    dist = {k: 1.0 / len(_PLUTCHIK) for k in _PLUTCHIK}  # ~0.125 each
    # No emotion exceeds thresholds for imbalance
    dominant = _dominant(dist)
    result = _detect_imbalance(dist, dominant)
    assert result is None


# ── _LABEL_MAP Spanish labels ─────────────────────────────────────────────────

def test_label_map_spanish_alegria_maps_to_joy():
    assert _LABEL_MAP.get("alegria") == "joy"


def test_label_map_spanish_tristeza_maps_to_sadness():
    assert _LABEL_MAP.get("tristeza") == "sadness"


def test_label_map_spanish_ira_maps_to_anger():
    assert _LABEL_MAP.get("ira") == "anger"


def test_label_map_neutral_maps_to_none():
    assert _LABEL_MAP.get("neutral") is None


# ── EmotionWheelProcessor.process() ──────────────────────────────────────────

def test_process_empty_db_returns_zero_report(tmp_db):
    with patch("cognia.memory.emotion_wheel.db_connect", side_effect=lambda path: sqlite3.connect(path)):
        proc = _proc(tmp_db)
        report = proc.process(hours=48.0)
    assert isinstance(report, EmotionReport)
    assert report.episodes_processed == 0
    assert report.dominant is None
    assert report.intensity == 0.0
    assert report.importance_modulated == 0


def test_process_detects_dominant_emotion(tmp_db):
    ts = _future_ts()
    rows = [(0.9, "sadness", 1.0, 0, ts)] * 8 + [(0.3, "joy", 1.0, 0, ts)]
    _insert_rows(tmp_db, rows)
    with patch("cognia.memory.emotion_wheel.db_connect", side_effect=lambda path: sqlite3.connect(path)):
        proc = _proc(tmp_db)
        report = proc.process(hours=48.0)
    assert report.episodes_processed == 9
    assert report.dominant == "sadness"


def test_process_modulates_importance_for_negative_dominant(tmp_db):
    ts = _future_ts()
    # Strong sadness dominance (negative valence) should dampen importance
    rows = [(0.9, "sadness", 1.0, 0, ts)] * 10
    _insert_rows(tmp_db, rows)
    with patch("cognia.memory.emotion_wheel.db_connect", side_effect=lambda path: sqlite3.connect(path)):
        proc = _proc(tmp_db)
        report = proc.process(hours=48.0)
    assert report.importance_modulated > 0


def test_process_skips_neutral_episodes(tmp_db):
    ts = _future_ts()
    # Only neutral rows — all skipped, distribution stays zero
    rows = [(0.5, "neutral", 1.0, 0, ts)] * 5
    _insert_rows(tmp_db, rows)
    with patch("cognia.memory.emotion_wheel.db_connect", side_effect=lambda path: sqlite3.connect(path)):
        proc = _proc(tmp_db)
        report = proc.process(hours=48.0)
    # Rows are fetched but all skipped because neutral -> None
    assert report.dominant is None
    assert report.distribution == {}


# ── Constants sanity ──────────────────────────────────────────────────────────

def test_boost_factor_in_expected_range():
    assert 1.05 <= _BOOST_FACTOR <= 1.15


def test_dampen_factor_in_expected_range():
    assert 0.85 <= _DAMPEN_FACTOR <= 0.95
