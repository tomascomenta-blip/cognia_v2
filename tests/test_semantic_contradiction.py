"""
tests/test_semantic_contradiction.py — detect_contradiction cableada.

Regresion: detect_contradiction era huerfana (nadie la llamaba). Ahora
SemanticMemory.update_concept la consulta antes de escribir: si la nueva
evidencia contradice un concepto establecido (similitud < 0.2 con
confianza > 0.6), la actualizacion BAJA la confianza en vez de subirla.
"""

import pytest

from cognia.database import init_db
from cognia.memory.semantic import SemanticMemory
from storage.db_pool import close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "semantic_contra.db")
    init_db(path)
    yield path
    close_pool(path)


VEC_A = [1.0] + [0.0] * 9
VEC_B = [0.0, 1.0] + [0.0] * 8   # ortogonal a VEC_A: coseno 0.0 < 0.2


def test_contradiccion_baja_confianza(db_path):
    sm = SemanticMemory(db_path)
    sm.update_concept("gato", VEC_A, confidence_delta=0.2)   # crea con conf=0.5
    sm.update_concept("gato", VEC_A, confidence_delta=0.2)   # 0.7
    sm.update_concept("gato", VEC_A, confidence_delta=0.2)   # 0.9
    antes = sm.get_concept("gato")["confidence"]
    assert antes > 0.6

    # detect_contradiction dispara (sim=0.0 < 0.2, conf > 0.6): resta el delta
    sm.update_concept("gato", VEC_B, confidence_delta=0.2)
    despues = sm.get_concept("gato")["confidence"]
    assert despues == pytest.approx(antes - 0.2)


def test_confirmacion_sigue_subiendo(db_path):
    sm = SemanticMemory(db_path)
    sm.update_concept("perro", VEC_A, confidence_delta=0.1)  # crea con 0.5
    sm.update_concept("perro", VEC_A, confidence_delta=0.1)  # 0.6
    assert sm.get_concept("perro")["confidence"] == pytest.approx(0.6)


def test_concepto_nuevo_no_penaliza(db_path):
    """Sin concepto previo no hay contradiccion posible: inserta normal."""
    sm = SemanticMemory(db_path)
    sm.update_concept("nuevo", VEC_B)
    assert sm.get_concept("nuevo")["confidence"] == pytest.approx(0.5)
