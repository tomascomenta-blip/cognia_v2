"""
Regression: the spaced-repetition CLI commands must work standalone, i.e.
without the :8765 desktop API running. Before the fix they hit HTTP and timed
out with "Servicio de aprendizaje no disponible".
"""
import cognia.cli as cli


def _patch_engine(tmp_path, monkeypatch):
    from cognia.learning.spaced_repetition import SpacedRepetitionEngine
    db = str(tmp_path / "sr.db")
    monkeypatch.setattr(cli, "_sr_engine", lambda: SpacedRepetitionEngine(db_path=db))


def test_aprender_and_aprendiendo_no_http(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)

    cli._slash_aprender_card("Capital de Francia | Paris | geografia")
    out = capsys.readouterr().out
    assert "Tarjeta guardada" in out
    assert "no disponible" not in out.lower()

    cli._slash_aprendiendo()
    out = capsys.readouterr().out
    assert "Total tarjetas : 1" in out
    assert "geografia" in out
    assert "no disponible" not in out.lower()


def test_aprendiendo_buscar_finds_card(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    cli._slash_aprender_card("Capital de Francia | Paris | geografia")
    capsys.readouterr()

    cli._slash_aprendiendo_buscar("francia")
    out = capsys.readouterr().out
    assert "Paris" in out
    assert "no disponible" not in out.lower()


def test_revisar_sm2_reviews_due_card(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    cli._slash_aprender_card("2+2 | 4 | mates")
    capsys.readouterr()

    # New cards are due immediately; feed Enter + a quality rating to input().
    answers = iter(["", "5"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

    cli._slash_revisar_sm2()
    out = capsys.readouterr().out
    assert "Proxima revision" in out
    assert "no disponible" not in out.lower()


def _patch_quiz(tmp_path, monkeypatch):
    from cognia.learning.quiz_generator import QuizGenerator
    db = str(tmp_path / "learn.db")
    monkeypatch.setattr(cli, "_quiz_gen", lambda: QuizGenerator(db_path=db, kg_db_path=db))
    return db


def test_quiz_from_sr_cards_no_http(tmp_path, monkeypatch, capsys):
    db = _patch_quiz(tmp_path, monkeypatch)
    # SR cards live in the same learning DB so quiz can draw from them.
    from cognia.learning.spaced_repetition import SpacedRepetitionEngine
    SpacedRepetitionEngine(db_path=db).add_card("2+2", "4", "mates")

    answers = iter(["4"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    cli._slash_quiz("")
    out = capsys.readouterr().out
    assert "Quiz:" in out
    assert "Resultado:" in out
    assert "no disponible" not in out.lower()

    cli._slash_quiz_stats("")
    out = capsys.readouterr().out
    assert "Intentos totales : 1" in out
    assert "no disponible" not in out.lower()


def test_learning_path_create_view_advance_no_http(tmp_path, monkeypatch, capsys):
    from cognia.learning.learning_path import LearningPathGenerator
    db = str(tmp_path / "learn.db")
    monkeypatch.setattr(cli, "_lpath_gen", lambda: LearningPathGenerator(db_path=db))

    cli._slash_camino_nuevo("Aprender Python")
    out = capsys.readouterr().out
    assert "Camino creado" in out
    assert "no disponible" not in out.lower()

    cli._slash_caminos("")
    out = capsys.readouterr().out
    assert "Aprender Python" in out

    cli._slash_camino_avanzar("1")
    out = capsys.readouterr().out
    assert "Proximo paso" in out or "completado" in out.lower()
    assert "no disponible" not in out.lower()
