# -*- coding: utf-8 -*-
"""Tests del cuaderno inteligente (cognia/notebook.py) — Open Notebook nativo."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.notebook import Cuaderno


@pytest.fixture()
def db(tmp_path):
    from cognia.database import init_db
    p = str(tmp_path / "cuad.db")
    init_db(p)
    return p


class _FakeEpisodic:
    def __init__(self, hits):
        self._hits = hits

    def retrieve_similar(self, vec, top_k=5):
        return self._hits[:top_k]


class _FakeAI:
    def __init__(self, db, hits=None):
        self.db = db
        self.episodic = _FakeEpisodic(hits or [])


def test_anotar_y_listar(db):
    cua = Cuaderno(db_path=db)
    nid = cua.anotar("La colonia muerde por pedazos", tipo="insight")
    assert isinstance(nid, int)
    notas = cua.notas()
    assert any(n["content"].startswith("La colonia") for n in notas)


def test_resumen_separa_notas_de_fuentes(db):
    cua = Cuaderno(db_path=db)
    cua.anotar("nota uno")
    cua.anotar("nota dos")
    # fuente simulada directamente como nota tipo fuente
    cua._notas.add_note("doc.pdf (5 fragmentos)", note_type="fuente",
                        session_id="default", source="doc.pdf")
    r = cua.resumen()
    assert r["notas"] == 2 and r["fuentes"] == 1


def test_consultar_sin_ai_devuelve_vacio(db):
    cua = Cuaderno(db_path=db)
    assert cua.consultar("algo") == []


def test_consultar_filtra_por_piso_y_ordena(db):
    hits = [
        {"observation": "irrelevante", "similarity": 0.02},
        {"observation": "muy relevante", "similarity": 0.9},
        {"observation": "algo relevante", "similarity": 0.5},
    ]
    cua = Cuaderno(ai=_FakeAI(db, hits), db_path=db)
    res = cua.consultar("pregunta", top_k=5)
    assert [r["texto"] for r in res] == ["muy relevante", "algo relevante"]
    assert res[0]["score"] == 0.9              # el ruido 0.02 se descarta


def test_agregar_fuente_sin_ai_da_error(db):
    cua = Cuaderno(db_path=db)
    assert "error" in cua.agregar_fuente("x.txt")


def test_agregar_fuente_ingiere_y_registra(db, tmp_path):
    """Fuente real: ingiere un .md y lo registra como fuente del cuaderno."""
    doc = tmp_path / "notas.md"
    doc.write_text("# Titulo\n\n" + ("contenido relevante y sustancioso. " * 10),
                   encoding="utf-8")

    class _RealishAI:
        """AI mínimo con las piezas que ingest_file usa."""
        def __init__(self, db):
            self.db = db
            import numpy as np
            class _Perc:
                def extract_features(self, txt):
                    return {"vector": np.zeros(64, dtype="float32")}
            class _Epi:
                def __init__(self): self.stored = []
                def store(self, *a, **k): self.stored.append(a)
            self.perception = _Perc()
            self.episodic = _Epi()

    ai = _RealishAI(db)
    cua = Cuaderno(ai=ai, db_path=db)
    res = cua.agregar_fuente(str(doc))
    assert "error" not in res and res["chunks"] >= 1
    fuentes = cua.fuentes()
    assert len(fuentes) == 1 and "notas.md" in fuentes[0]["content"]


def test_tool_cuaderno_subcomandos(db, monkeypatch):
    """La tool del agente responde nota/consultar/ver/invalido."""
    import cognia.agent.tools as T
    hits = [{"observation": "material clave", "similarity": 0.8}]
    ctx = {"ai": _FakeAI(db, hits)}
    # forzar que Cuaderno use la db de test
    import cognia.notebook as NB
    orig = NB.Cuaderno

    def _factory(ai=None, db_path=None, cuaderno_id="default"):
        return orig(ai=ai, db_path=db, cuaderno_id=cuaderno_id)
    monkeypatch.setattr(NB, "Cuaderno", _factory)

    assert "nota #" in T.run_tool("cuaderno", "nota | primera idea", ctx)
    assert "material clave" in T.run_tool("cuaderno", "consultar | idea", ctx)
    assert "notas" in T.run_tool("cuaderno", "ver", ctx)
    assert "invalido" in T.run_tool("cuaderno", "zzz | x", ctx)
