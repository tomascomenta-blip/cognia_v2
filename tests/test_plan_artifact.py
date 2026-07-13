# -*- coding: utf-8 -*-
"""Plan como artefacto mutable (plan_artifact.py, patron OpenManus)."""
from cognia.agent.plan_artifact import EN_CURSO, HECHO, PENDIENTE, Plan, parse_pasos


def test_estados_y_marcar():
    p = Plan("obj", ["a", "b", "c"])
    assert all(s["estado"] == PENDIENTE for s in p.pasos)
    assert p.marcar(0, "en_curso") is True
    assert p.pasos[0]["estado"] == EN_CURSO
    assert p.marcar(0, "hecho") and p.pasos[0]["estado"] == HECHO
    assert p.marcar(9, "hecho") is False       # indice invalido
    assert p.marcar(1, "xyz") is False         # estado invalido


def test_avanzar():
    p = Plan("", ["a", "b"])
    p.pasos[0]["estado"] = EN_CURSO
    i = p.avanzar()                            # a->hecho, b->en_curso
    assert i == 1
    assert p.pasos[0]["estado"] == HECHO and p.pasos[1]["estado"] == EN_CURSO
    assert p.avanzar() is None                 # no quedan pendientes
    assert p.completo()


def test_render_marcas():
    p = Plan("mi obj", ["uno", "dos"])
    p.pasos[0]["estado"] = HECHO
    r = p.render()
    assert "mi obj" in r and "[x] 1. uno" in r and "[ ] 2. dos" in r


def test_persistencia_roundtrip(tmp_path):
    p = Plan("o", ["a", "b"])
    p.marcar(0, "hecho")
    f = tmp_path / ".plan.json"
    p.guardar(f)
    q = Plan.cargar(f)
    assert q is not None
    assert q.objetivo == "o" and q.pasos[0]["estado"] == HECHO
    assert Plan.cargar(tmp_path / "noexiste.json") is None


def test_parse_pasos():
    txt = "1. leer\n2) analizar\n- extra\n* otro\nno-es-paso"
    pasos = parse_pasos(txt)
    assert pasos == ["leer", "analizar", "extra", "otro"]


def test_tool_plan_ciclo(tmp_path, monkeypatch):
    import cognia.agent.plan_artifact as pa
    monkeypatch.setattr(pa, "_plan_path", lambda: tmp_path / ".plan.json")
    from cognia.agent.tools import TOOLS
    plan = TOOLS["plan"]["fn"]
    # crear
    r = plan("crear 1. hacer A\n2. hacer B", {})
    assert "creado" in r and "[→] 1" in r      # primer paso en curso
    # ver
    assert "PLAN" in plan("ver", {})
    # marcar
    r = plan("marcar 1 hecho", {})
    assert "[x] 1" in r
    r = plan("marcar 2 hecho", {})
    assert "COMPLETO" in r
