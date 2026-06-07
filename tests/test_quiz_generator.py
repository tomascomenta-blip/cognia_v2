"""
tests/test_quiz_generator.py
==============================
6 tests for QuizGenerator: KG questions, SR questions, mixed, answer recording.
"""
import pytest
import tempfile
import os


@pytest.fixture
def quiz_tmp(tmp_path):
    """Create a QuizGenerator with isolated temp DBs."""
    from cognia.learning.quiz_generator import QuizGenerator

    db = str(tmp_path / "quiz.db")
    kg_db = str(tmp_path / "kg.db")

    # Bootstrap sr_cards table in quiz db
    from storage.db_pool import get_pool
    with get_pool(db).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sr_cards ("
            "  id INTEGER PRIMARY KEY,"
            "  front TEXT NOT NULL,"
            "  back TEXT NOT NULL,"
            "  topic TEXT NOT NULL DEFAULT 'general',"
            "  ease_factor REAL NOT NULL DEFAULT 2.5,"
            "  interval_days REAL NOT NULL DEFAULT 1.0,"
            "  repetitions INTEGER NOT NULL DEFAULT 0,"
            "  next_review REAL NOT NULL DEFAULT 0,"
            "  last_reviewed REAL,"
            "  created_at REAL NOT NULL DEFAULT 0"
            ")"
        )
        conn.execute(
            "INSERT INTO sr_cards (front, back, topic, next_review, created_at) "
            "VALUES ('Que es Python?', 'Un lenguaje de programacion', 'tech', 0, 0)"
        )
        conn.execute(
            "INSERT INTO sr_cards (front, back, topic, next_review, created_at) "
            "VALUES ('Que es SQL?', 'Un lenguaje de consulta', 'tech', 0, 0)"
        )

    # Bootstrap knowledge_graph table in kg db
    with get_pool(kg_db).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_graph ("
            "  id INTEGER PRIMARY KEY,"
            "  subject TEXT NOT NULL,"
            "  predicate TEXT NOT NULL,"
            "  object TEXT NOT NULL,"
            "  weight REAL NOT NULL DEFAULT 1.0,"
            "  source TEXT DEFAULT 'test',"
            "  timestamp REAL DEFAULT 0"
            ")"
        )
        conn.execute(
            "INSERT INTO knowledge_graph (subject, predicate, object, weight) "
            "VALUES ('Python', 'es_un', 'lenguaje', 1.0)"
        )
        conn.execute(
            "INSERT INTO knowledge_graph (subject, predicate, object, weight) "
            "VALUES ('SQL', 'tiene', 'sintaxis declarativa', 0.9)"
        )

    return QuizGenerator(db_path=db, kg_db_path=kg_db)


def test_generate_from_kg_returns_list(quiz_tmp):
    result = quiz_tmp.generate_from_kg(limit=5)
    assert isinstance(result, list)


def test_generate_from_kg_has_questions(quiz_tmp):
    result = quiz_tmp.generate_from_kg(limit=5)
    assert len(result) >= 1
    q = result[0]
    assert "question" in q
    assert "answer" in q
    assert q["source"] == "kg"


def test_generate_from_sr_returns_list(quiz_tmp):
    result = quiz_tmp.generate_from_sr(limit=5)
    assert isinstance(result, list)


def test_generate_from_sr_has_questions(quiz_tmp):
    result = quiz_tmp.generate_from_sr(limit=5)
    assert len(result) >= 1
    q = result[0]
    assert "question" in q
    assert "answer" in q
    assert q["source"] == "sr"


def test_generate_mixed_returns_list(quiz_tmp):
    result = quiz_tmp.generate_mixed(limit=6)
    assert isinstance(result, list)


def test_record_answer_correct_returns_true(quiz_tmp):
    result = quiz_tmp.record_answer("Q?", "Python", "Python", source="test")
    assert result is True


def test_record_answer_wrong_returns_false(quiz_tmp):
    result = quiz_tmp.record_answer("Q?", "Python", "Java", source="test")
    assert result is False


def test_get_stats_returns_required_keys(quiz_tmp):
    quiz_tmp.record_answer("Q1?", "A", "A", source="kg")
    quiz_tmp.record_answer("Q2?", "B", "X", source="sr")
    stats = quiz_tmp.get_stats()
    assert "total_attempts" in stats
    assert "correct" in stats
    assert "accuracy" in stats
    assert "by_source" in stats
    assert stats["total_attempts"] == 2
    assert stats["correct"] == 1
    assert stats["accuracy"] == 0.5
