# -*- coding: utf-8 -*-
"""Pensamiento profundo en tres actos (SONAR -> PLANIFICAR -> EJECUTAR).

Cubre las piezas puras (sin modelo): la cosecha del texto del razonador
—incluido el caso REAL de thinking truncado que medimos el 2026-07-23—, el
contexto que viaja con cada paso, y el recorrido del plan con un runner falso.
"""
from cognia.agent.plan_artifact import HECHO, PENDIENTE, Plan
from cognia.pensamiento_profundo import (
    IDEA_EN_CONTEXTO, _cosecha, _guia, _limpiar_think, ejecutar, es_pregunta,
    resumen,
)


def test_pregunta_no_entra_al_pipeline():
    assert es_pregunta("por que el cielo es azul?")
    assert es_pregunta("Como funciona un motor diesel")
    assert not es_pregunta("hace un juego de plataformas dificil")
    assert not es_pregunta("")


def test_cosecha_respuesta_normal():
    out = {"respuesta": "la idea", "pensamiento": "divagando"}
    assert _cosecha(out) == "la idea"


def test_cosecha_thinking_truncado_no_pierde_el_sueno():
    """Caso real: sin presupuesto el modelo nunca cierra </think> y todo el
    monologo llega como 'respuesta'. Vale igual, limpio de tags."""
    out = {"respuesta": "<think>\nsone un castillo flotante", "pensamiento": ""}
    assert _cosecha(out) == "sone un castillo flotante"


def test_cosecha_respuesta_vacia_usa_el_pensamiento():
    assert _cosecha({"respuesta": "", "pensamiento": "material util"}) == "material util"
    assert _cosecha(None) == ""


def test_limpiar_think():
    assert _limpiar_think("<think>a</think>") == "a"


def test_guia_lleva_idea_plan_y_posicion():
    plan = Plan("juego", ["crear motor", "agregar jefes"])
    g = _guia("VISION: un roguelike submarino", plan, 1)
    assert "VISION: un roguelike submarino" in g      # la idea viaja
    assert "crear motor" in g and "agregar jefes" in g  # el mapa completo
    assert "paso 2 de 2" in g                          # donde estamos


def test_guia_acota_la_idea():
    plan = Plan("x", ["a"])
    assert len(_guia("z" * 99000, plan, 0)) < IDEA_EN_CONTEXTO + 2000


def test_ejecutar_recorre_marca_y_acumula(tmp_path, monkeypatch):
    import cognia.pensamiento_profundo as pp
    monkeypatch.setattr(pp, "_plan_path", lambda: tmp_path / ".plan.json")
    plan = Plan("juego", ["paso uno", "paso dos"])
    vistos = []

    def runner(tarea, guidance):
        vistos.append((tarea, guidance))
        return f"hecho: {tarea}"

    res = ejecutar(plan, "la idea", runner, soltar_razonador=False)
    assert [r["paso"] for r in res] == ["paso uno", "paso dos"]
    assert all(r["ok"] for r in res)
    assert all(s["estado"] == HECHO for s in plan.pasos)
    assert len(vistos) == 2 and "la idea" in vistos[0][1]


def test_ejecutar_paso_que_revienta_no_mata_la_corrida(tmp_path, monkeypatch):
    import cognia.pensamiento_profundo as pp
    monkeypatch.setattr(pp, "_plan_path", lambda: tmp_path / ".plan.json")
    plan = Plan("j", ["bomba", "sigue"])

    def runner(tarea, guidance):
        if tarea == "bomba":
            raise RuntimeError("backend caido")
        return "ok"

    res = ejecutar(plan, "idea", runner, soltar_razonador=False)
    assert len(res) == 2                       # siguio despues del fallo
    assert res[0]["ok"] is False and res[1]["ok"] is True
    assert plan.pasos[0]["estado"] == PENDIENTE   # el fallido queda pendiente
    assert plan.pasos[1]["estado"] == HECHO


def _pp(tmp_path, monkeypatch):
    """Modulo con el workspace apuntando a tmp_path."""
    import cognia.pensamiento_profundo as pp
    monkeypatch.setattr(pp, "_plan_path", lambda: tmp_path / ".plan.json")
    return pp


def test_rotos_detecta_syntaxerror(tmp_path, monkeypatch):
    pp = _pp(tmp_path, monkeypatch)
    (tmp_path / "bien.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "mal.py").write_text("def f(:\n", encoding="utf-8")
    rotos = pp._rotos()
    assert [n for n, _ in rotos] == ["mal.py"]
    assert "linea" in rotos[0][1]


def test_compuerta_repara_y_cierra_ok(tmp_path, monkeypatch):
    """El paso escribe basura; la reparacion la arregla -> el paso vale."""
    pp = _pp(tmp_path, monkeypatch)
    plan = Plan("j", ["escribir modulo"])
    llamadas = []

    def runner(tarea, guia):
        llamadas.append(tarea)
        if len(llamadas) == 1:
            (tmp_path / "m.py").write_text("def f(:\n", encoding="utf-8")
        else:                                   # la pasada de reparacion
            (tmp_path / "m.py").write_text("def f():\n    pass\n", encoding="utf-8")
        return "ok"

    res = pp.ejecutar(plan, "idea", runner, soltar_razonador=False)
    assert len(llamadas) == 2                   # hubo reparacion
    assert "m.py" in llamadas[1] and "sintaxis" in llamadas[1]
    assert res[0]["ok"] is True and plan.pasos[0]["estado"] == HECHO


def test_compuerta_no_miente_si_sigue_roto(tmp_path, monkeypatch):
    pp = _pp(tmp_path, monkeypatch)
    plan = Plan("j", ["escribir modulo"])

    def runner(tarea, guia):
        (tmp_path / "m.py").write_text("def f(:\n", encoding="utf-8")
        return "ok"                             # nunca lo arregla

    res = pp.ejecutar(plan, "idea", runner, soltar_razonador=False)
    assert res[0]["ok"] is False                # no se declara hecho
    assert "codigo invalido" in res[0]["resultado"]
    assert plan.pasos[0]["estado"] == PENDIENTE


def test_compuerta_ignora_lo_ya_roto_de_antes(tmp_path, monkeypatch):
    """Un archivo roto que YA estaba no puede bloquear al paso siguiente."""
    pp = _pp(tmp_path, monkeypatch)
    (tmp_path / "viejo.py").write_text("def f(:\n", encoding="utf-8")
    plan = Plan("j", ["paso limpio"])

    def runner(tarea, guia):
        (tmp_path / "nuevo.py").write_text("x = 1\n", encoding="utf-8")
        return "ok"

    res = pp.ejecutar(plan, "idea", runner, soltar_razonador=False)
    assert res[0]["ok"] is True                 # no lo penaliza el arrastre


def test_inventario_avisa_lo_ya_construido(tmp_path, monkeypatch):
    pp = _pp(tmp_path, monkeypatch)
    (tmp_path / "nodes.py").write_text("class Node: pass\n", encoding="utf-8")
    g = pp._guia("idea", Plan("j", ["a"]), 0)
    assert "nodes.py" in g
    # sobre lo ya hecho, editar — nunca escribir_archivo (borra el archivo y
    # con el, el trabajo del paso anterior: medido en la corrida 2026-07-23)
    assert "PROHIBIDO usar escribir_archivo" in g and "editar_archivo" in g
    assert "EXACTAMENTE" in g                   # regla del nombre de archivo
    assert "Prohibido el stub" in g             # modulos vacios medidos 2026-07-23


def test_resumen_reporta_conteo_real():
    plan = Plan("j", ["a", "b"])
    r = resumen({"idea": "x" * 10, "plan": plan, "tokens_idea": 900,
                 "resultados": [{"paso": "a", "resultado": "ok", "ok": True},
                                {"paso": "b", "resultado": "no", "ok": False}]})
    assert "1/2 pasos" in r and "900 tokens" in r


def test_resumen_error():
    assert "fallo" in resumen({"error": "backend caido"})
