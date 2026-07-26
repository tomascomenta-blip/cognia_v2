"""
Best-of-N verificado + rondas con progreso + telemetria de sellos (2026-07-26).

PREREG_BON_RONDAS_20260726.md: la serie b2 de la config final (3,4,5,5,4 / 6)
midio que el cuello es la VARIANZA de la generacion inicial y la reparacion
que se corta a 1-2 checks del pase. Estos tests verifican la LOGICA del
cableado (el juez real con Chromium se prueba en el banco):
  - BoN: el juez elige el primer candidato que aprueba ANTES de gastar rondas;
    sin aprobados, el de mas checks_ok; sin juez posible, no se quema GPU.
  - Rondas: checks_ok creciendo extiende el tope hasta max_rondas_progreso;
    sin progreso, el tope fijo manda.
  - Telemetria: cada construccion deja su sello en el JSONL (la tasa de
    "sin verificar" es la metrica de salud del pensador).
"""

import json
from unittest.mock import patch

from cognia.program_creator import diseno_a_codigo as d2c
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.juez_ejecutable import Check, Veredicto
from cognia.program_creator.vista_navegador import InformeVisual


def _prog(code="<html><body>v1</body></html>"):
    return GeneratedProgram(title="P", description="d", code=code,
                            category="dashboard", lenguaje="html")


def _informe():
    return InformeVisual(defectos=[], input_images=["/tmp/shot.png"])


def _veredicto(aprobado, n_ok=1, falla="x"):
    """Veredicto con n_ok checks OK; si no aprueba, un check fallido con
    nombre `falla` (nombres distintos entre rondas = huellas distintas para
    el disyuntor)."""
    v = Veredicto(producto="x", aprobado=aprobado, con_contrato=True)
    v.checks = [Check(f"ok{i}", True, "ok", critico=True) for i in range(n_ok)]
    if not aprobado:
        v.checks.append(Check(falla, False, f"esperaba {falla}", critico=True))
    v.motivo = "test"
    return v


def _base(gen_ret, juez_ret, reparado_ret):
    return [
        patch.object(d2c._mockup, "imaginar_vision",
                     return_value={"brief": "b", "prompt_imagen": "p"}),
        patch.object(d2c._mockup, "generar_mockup", return_value=None),
        patch.object(d2c, "generate_program", **gen_ret),
        patch.object(d2c, "revisar_en_navegador", return_value=_informe()),
        patch.object(d2c, "arbitrar_desde_informe", return_value=None),
        patch.object(d2c, "reparar_web", **reparado_ret),
        patch.object(d2c, "_juez_del_lazo", **juez_ret),
    ]


def _run(ps, **kw):
    for p in ps:
        p.start()
    try:
        return d2c.construir_para_mockup("un contador web", verbose=False, **kw)
    finally:
        for p in reversed(ps):
            p.stop()


# ── BoN: el primero que aprueba gana, antes de gastar reparacion ─────────────

def test_bon_elige_el_primer_candidato_aprobado_y_corta_sin_relazo():
    p1, p2 = _prog("<html><body>c1</body></html>"), _prog("<html><body>c2</body></html>")
    # BoN: c1 FALLIDO, c2 APROBADO -> elegido c2 y el lazo NO corre: re-juzgar
    # el mismo HTML con un juez flaky seria doble jeopardy (revisor 2026-07-26).
    vs = [_veredicto(False, n_ok=3), _veredicto(True, n_ok=5)]
    gen = {"side_effect": [p1, p2]}
    juez = {"side_effect": vs}
    ps = _base(gen, juez, {"return_value": None})
    res = _run(ps, candidatos_iniciales=3)
    assert res.bon["elegido"] == 2
    assert res.bon["candidatos"][1]["sello"] == "APROBADO"
    assert res.program.code == p2.code
    assert res.sello == "APROBADO"
    assert res.veredicto is not None          # el veredicto del BoN es EL veredicto
    assert res.motivo_corte == "aprobado por juez ejecutable (best-of-N)"
    assert res.rondas == 0                    # ni una ronda de reparacion gastada


def test_bon_reintenta_el_contrato_sobre_el_mismo_candidato():
    """El intento 1 de contrato falla (~1/2 medido): el reintento se paga sobre
    el MISMO candidato 1, sin gastar una generacion de GPU para eso."""
    llamadas = []

    def _juez(idea, codigo, tmp_dir, ronda, res, verbose=False):
        llamadas.append(ronda)
        if len(llamadas) == 1:
            res.contrato_intentos = 1        # intento 1 fallido, queda margen
            return None
        return _veredicto(True, n_ok=4)

    gen = {"side_effect": [_prog()]}          # UNA sola generacion
    ps = _base(gen, {"side_effect": _juez}, {"return_value": None})
    res = _run(ps, candidatos_iniciales=3)
    assert llamadas == ["0c1", "0c1b"]        # reintento en el mismo candidato
    assert res.sello == "APROBADO"
    assert res.bon["elegido"] == 1


def test_bon_sin_aprobados_elige_el_de_mas_checks_ok():
    p1 = _prog("<html><body>c1</body></html>")
    p2 = _prog("<html><body>c2</body></html>")
    p3 = _prog("<html><body>c3</body></html>")
    # Ninguno aprueba: 3, 5 y 1 checks OK -> se entra al lazo con c2.
    vs = [_veredicto(False, n_ok=3, falla="a"),
          _veredicto(False, n_ok=5, falla="b"),
          _veredicto(False, n_ok=1, falla="c"),
          _veredicto(False, n_ok=5, falla="b")]     # lazo ronda 1
    ps = _base({"side_effect": [p1, p2, p3]}, {"side_effect": vs},
               {"return_value": None})               # reparacion corta el lazo
    res = _run(ps, candidatos_iniciales=3)
    assert res.bon["elegido"] == 2
    assert res.program.code == p2.code
    assert res.sello == "FALLIDO"


def test_bon_sin_juez_posible_no_quema_candidatos():
    """Sin contrato posible (backend caido / 2 intentos quemados) elegir es
    imposible: no se genera ni un candidato extra — seria GPU a ciegas."""
    def _sin_juez(idea, codigo, tmp_dir, ronda, res, verbose=False):
        res.contrato_fallido = True
        return None

    gen = {"side_effect": [_prog()]}          # si pidiera un 2o, IndexError
    ps = _base(gen, {"side_effect": _sin_juez}, {"return_value": None})
    res = _run(ps, candidatos_iniciales=3)
    assert res.bon["candidatos"] == [{"candidato": 1, "sello": "sin juez"}]
    assert res.sello == "sin verificar"


# ── Rondas: el progreso extiende, el estancamiento no ────────────────────────

def test_checks_ok_creciendo_extiende_hasta_el_tope_progreso():
    # 2 -> 3 -> 4 -> 5 -> 6 checks OK: progreso real en cada ronda; el lazo
    # debe llegar a la ronda 5 (tope extendido), no cortarse en la 3.
    vs = [_veredicto(False, n_ok=n, falla=f"f{n}") for n in (2, 3, 4, 5, 6)]
    ps = _base({"return_value": _prog()}, {"side_effect": vs},
               {"return_value": _prog("<html><body>vN</body></html>")})
    res = _run(ps, max_rondas=3, max_rondas_progreso=5)
    assert res.rondas == 5
    assert res.motivo_corte == "tope de rondas"


def test_sin_progreso_el_tope_fijo_manda():
    # checks_ok clavado en 3 (sintomas distintos, asi el disyuntor no es el
    # que corta): sin crecimiento no hay extension — corta en max_rondas.
    vs = [_veredicto(False, n_ok=3, falla=f"f{n}") for n in range(5)]
    ps = _base({"return_value": _prog()}, {"side_effect": vs},
               {"return_value": _prog("<html><body>vN</body></html>")})
    res = _run(ps, max_rondas=3, max_rondas_progreso=5)
    assert res.rondas == 3
    assert res.motivo_corte.startswith("tope de rondas")


def test_sin_max_rondas_progreso_comportamiento_de_siempre():
    vs = [_veredicto(False, n_ok=n, falla=f"f{n}") for n in (2, 3, 4)]
    ps = _base({"return_value": _prog()}, {"side_effect": vs},
               {"return_value": _prog("<html><body>vN</body></html>")})
    res = _run(ps, max_rondas=3)
    assert res.rondas == 3
    assert res.motivo_corte == "tope de rondas"


# ── El default de produccion entrega la primera generacion juzgada ───────────

def test_default_de_produccion_es_una_ronda():
    """A/B nocturno 2026-07-26/27: con el juez interno funcionando, reparar
    RESTA (primgen 4.0/6 vs 3.33 con reparacion; best-of-so-far 2.33 KILL).
    El default queda en 1 ronda hasta que el contrato interno mejore. Este
    test protege la politica: si alguien vuelve a subir el default, que sea
    a proposito y con un numero nuevo."""
    assert d2c.MAX_RONDAS_DEFECTO == 1


def test_con_default_no_se_repara_y_el_sello_queda():
    reparado = {"llamado": False}

    def _reparar(program, defectos, llm=None, profundo=False):
        reparado["llamado"] = True
        return _prog("<html><body>v2</body></html>")

    vs = [_veredicto(False, n_ok=3)]
    ps = _base({"return_value": _prog()}, {"side_effect": vs},
               {"side_effect": _reparar})
    res = _run(ps)                            # sin max_rondas: el default
    assert res.rondas == 1
    assert res.sello == "FALLIDO"             # el juez sigue sellando
    assert reparado["llamado"] is False       # pero no se gasta reparacion


# ── Telemetria: el sello queda contado, tambien el "sin verificar" ───────────

def test_telemetria_registra_el_sello(tmp_path):
    ps = _base({"return_value": _prog()}, {"return_value": None},
               {"return_value": None})
    _run(ps)                                  # sin juez -> "sin verificar"
    ruta = tmp_path / "telemetria_test.jsonl"    # redirigida por conftest
    lineas = [json.loads(l) for l in
              ruta.read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == 1
    assert lineas[0]["sello"] == "sin verificar"
    assert lineas[0]["idea"] == "un contador web"
    assert "contrato_intentos" in lineas[0]
