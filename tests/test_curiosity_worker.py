"""
test_curiosity_worker.py
Tests for CuriosityEngine and CuriosityWorker (curiosity_engine.py / curiosity_worker.py).
All tests use temp SQLite files -- no network calls, no leftover files.
"""

import os
import tempfile
import threading
import time

import pytest

from cognia.reasoning.curiosity_engine import CuriosityEngine
from cognia.reasoning.curiosity_worker import CuriosityWorker, _extract_topic


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine(tmp_path):
    """CuriosityEngine backed by a temp SQLite file."""
    db = str(tmp_path / "curiosity_test.db")
    return CuriosityEngine(db_path=db)


# ── _extract_keywords ─────────────────────────────────────────────────────────

def test_extract_keywords_basic(engine):
    kws = engine._extract_keywords("transformers neural networks attention")
    assert "transformers" in kws
    assert "neural" in kws
    assert "networks" in kws
    assert "attention" in kws


def test_extract_keywords_short_words_filtered(engine):
    # "ai" (2 chars) and "ml" (2 chars) are below MIN_KEYWORD_LEN=4
    kws = engine._extract_keywords("ai ml deep learning")
    assert "ai" not in kws
    assert "ml" not in kws
    assert "deep" in kws
    assert "learning" in kws


def test_extract_keywords_stopwords_filtered(engine):
    kws = engine._extract_keywords("what how does neural network work")
    # stopwords "what", "how", "does", "work" -- "work" is 4 chars but not a stopword
    assert "what" not in kws
    assert "does" not in kws
    assert "neural" in kws
    assert "network" in kws


def test_extract_keywords_dedup(engine):
    kws = engine._extract_keywords("python python python")
    assert kws.count("python") == 1


def test_extract_keywords_empty(engine):
    assert engine._extract_keywords("") == []


# ── generate_questions ────────────────────────────────────────────────────────

def test_generate_questions_high_confidence_returns_empty(engine):
    qs = engine.generate_questions("transformers attention heads", "", confidence=0.5)
    assert qs == []


def test_generate_questions_low_confidence_returns_questions(engine):
    qs = engine.generate_questions("transformers neural networks", "", confidence=0.2)
    assert len(qs) >= 1
    assert len(qs) <= 2


def test_generate_questions_empty_prompt_returns_empty(engine):
    qs = engine.generate_questions("", "", confidence=0.1)
    assert qs == []


def test_generate_questions_at_threshold_returns_empty(engine):
    # Exactly at threshold (0.4) should return empty
    qs = engine.generate_questions("transformers neural networks", "", confidence=0.4)
    assert qs == []


# ── enqueue / get_pending ─────────────────────────────────────────────────────

def test_enqueue_and_get_pending(engine):
    engine.enqueue(["question one about transformers", "question two about networks"], "source prompt")
    pending = engine.get_pending()
    assert len(pending) == 2
    questions = [p["question"] for p in pending]
    assert "question one about transformers" in questions
    assert "question two about networks" in questions


def test_get_pending_empty_when_none(engine):
    assert engine.get_pending() == []


def test_enqueue_noop_on_empty_list(engine):
    engine.enqueue([], "some prompt")
    assert engine.get_pending() == []


def test_enqueue_limit_respected(engine):
    engine.enqueue(["q1 about alpha", "q2 about beta", "q3 about gamma"], "prompt")
    pending = engine.get_pending(limit=2)
    assert len(pending) == 2


# ── mark_answered / mark_failed ───────────────────────────────────────────────

def test_mark_answered_removes_from_pending(engine):
    engine.enqueue(["question about transformers"], "prompt")
    pending = engine.get_pending()
    assert len(pending) == 1
    qid = pending[0]["id"]
    engine.mark_answered(qid, "answer text here")
    assert engine.get_pending() == []


def test_mark_failed_removes_from_pending(engine):
    engine.enqueue(["question about networks"], "prompt")
    pending = engine.get_pending()
    qid = pending[0]["id"]
    engine.mark_failed(qid)
    assert engine.get_pending() == []


# ── get_insights ──────────────────────────────────────────────────────────────

def test_get_insights_returns_answered_only(engine):
    engine.enqueue(["question about transformers", "question about networks"], "p")
    pending = engine.get_pending()
    engine.mark_answered(pending[0]["id"], "answer about transformers")
    engine.mark_failed(pending[1]["id"])
    insights = engine.get_insights()
    assert len(insights) == 1
    assert insights[0]["answer"] == "answer about transformers"


def test_get_insights_empty_when_none_answered(engine):
    engine.enqueue(["pending question about nets"], "p")
    assert engine.get_insights() == []


# ── _extract_topic ────────────────────────────────────────────────────────────

def test_extract_topic_que_no_entiendo():
    result = _extract_topic("Que no entiendo sobre transformers")
    assert result == "transformers"


def test_extract_topic_cual_estado_arte():
    result = _extract_topic("Cual es el estado del arte en redes neuronales")
    assert result == "redes neuronales"


def test_extract_topic_fallback_last_words():
    # No recognized pattern -> last 3 words
    result = _extract_topic("something about deep neural networks here")
    assert result == "neural networks here"  # last 3 words of 6-word string


def test_extract_topic_strips_question_marks():
    result = _extract_topic("Que no entiendo sobre Python?")
    assert "?" not in result
    assert result == "Python"


# ── CuriosityWorker ───────────────────────────────────────────────────────────

def test_worker_thread_is_daemon(tmp_path):
    db = str(tmp_path / "worker_test.db")
    eng = CuriosityEngine(db_path=db)
    worker = CuriosityWorker(eng, interval_s=9999)
    assert worker._thread.daemon is True


def test_worker_start_sets_thread_alive(tmp_path):
    db = str(tmp_path / "worker_start.db")
    eng = CuriosityEngine(db_path=db)
    worker = CuriosityWorker(eng, interval_s=9999)
    worker.start()
    assert worker._thread.is_alive()
    worker.stop()


def test_worker_stop_sets_flag(tmp_path):
    db = str(tmp_path / "worker_stop.db")
    eng = CuriosityEngine(db_path=db)
    worker = CuriosityWorker(eng, interval_s=9999)
    assert not worker._stop_flag.is_set()
    worker.stop()
    assert worker._stop_flag.is_set()


def test_worker_process_batch_noop_without_scraper(tmp_path, monkeypatch):
    """_process_batch returns immediately when _GitHubScraper is None."""
    import cognia.reasoning.curiosity_worker as cw_module
    monkeypatch.setattr(cw_module, "_GitHubScraper", None)

    db = str(tmp_path / "worker_noop.db")
    eng = CuriosityEngine(db_path=db)
    eng.enqueue(["question about transformers"], "prompt")

    worker = CuriosityWorker(eng, interval_s=9999)
    worker._process_batch()  # must not raise, must not change DB

    # Item stays pending because scraper was None
    assert len(eng.get_pending()) == 1
