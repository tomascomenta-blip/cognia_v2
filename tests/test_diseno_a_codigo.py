"""
El lazo DISENO-A-CODIGO con arbitro visual: el cerebro imagina el producto, el
modelo de imagenes dibuja el mockup, y la pagina se itera hasta parecerse a esa
vision. Estos tests parchean las piezas pesadas (LLM, GPU, navegador) y verifican
la LOGICA del lazo: fusion de defectos, cortes (sin defectos / gate / disyuntor /
tope) y degradacion sin VLM.
"""

from unittest.mock import patch

from cognia.program_creator import diseno_a_codigo as d2c
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.vista_navegador import InformeVisual


def _prog(code="<html><body>hola</body></html>", titulo="P"):
    return GeneratedProgram(title=titulo, description="d", code=code,
                            category="dashboard", lenguaje="html")


def _informe(defectos=None):
    return InformeVisual(defectos=list(defectos or []),
                         input_images=["/tmp/shot.png"])


def _parchar(informe_ret, arb_ret, reparado_ret, prog_ini=None):
    """Contexto comun: imaginar/mockup neutralizados, y las piezas pesadas
    devolviendo lo que el test dicte. Devuelve una lista de patchers activos."""
    ps = [
        patch.object(d2c._mockup, "imaginar_vision",
                     return_value={"brief": "un dashboard oscuro",
                                   "prompt_imagen": "dark dashboard"}),
        patch.object(d2c._mockup, "generar_mockup", return_value=None),
        patch.object(d2c, "generate_program",
                     return_value=prog_ini if prog_ini is not None else _prog()),
        patch.object(d2c, "revisar_en_navegador", **informe_ret),
        patch.object(d2c, "arbitrar_desde_informe", **arb_ret),
        patch.object(d2c, "reparar_web", **reparado_ret),
    ]
    return ps


def _run(ps, **kw):
    for p in ps:
        p.start()
    try:
        return d2c.construir_para_mockup("dashboard de inversiones",
                                         verbose=False, **kw)
    finally:
        for p in reversed(ps):
            p.stop()


# ── cortes por calidad ────────────────────────────────────────────────────────

def test_corta_sin_defectos_a_la_primera():
    ps = _parchar(
        informe_ret={"return_value": _informe([])},
        arb_ret={"return_value": None},        # sin VLM
        reparado_ret={"return_value": None})
    res = _run(ps)
    assert res.motivo_corte == "sin defectos"
    assert res.rondas == 1
    assert res.defectos == []


def test_corta_por_gate_de_fidelidad():
    ps = _parchar(
        informe_ret={"return_value": _informe(["algo estructural"])},
        arb_ret={"return_value": {"nota": 8.5, "veredicto": "fiel",
                                  "defectos": [], "critico": "vlm"}},
        reparado_ret={"return_value": None})
    res = _run(ps, gate_nota=7.0)
    # Hay un defecto estructural pero el arbitro la aprueba (8.5 >= 7.0).
    assert res.nota_visual == 8.5
    assert res.motivo_corte.startswith("fidelidad 8.5")
    assert res.rondas == 1


# ── fusion de defectos estructurales + visuales ──────────────────────────────

def test_fusiona_defectos_estructurales_y_visuales():
    capturado = {}

    def _reparar(program, defectos, llm=None):
        capturado["defectos"] = list(defectos)
        return None      # corta tras capturar

    ps = _parchar(
        informe_ret={"return_value": _informe(["la pagina no cambia sola"])},
        arb_ret={"return_value": {"nota": 3.0, "veredicto": "no se parece",
                                  "defectos": ["el header deberia ser una barra"],
                                  "critico": "vlm"}},
        reparado_ret={"side_effect": _reparar})
    res = _run(ps, gate_nota=7.0)
    # El estructural va tal cual; el visual va prefijado con "(visual)".
    assert "la pagina no cambia sola" in capturado["defectos"]
    assert any(d.startswith("(visual) ") for d in capturado["defectos"])
    assert res.nota_visual == 3.0


# ── degradacion sin VLM: solo defectos estructurales ─────────────────────────

def test_sin_vlm_usa_solo_defectos_estructurales():
    capturado = {}

    def _reparar(program, defectos, llm=None):
        capturado["defectos"] = list(defectos)
        return None

    ps = _parchar(
        informe_ret={"return_value": _informe(["errores de JavaScript: x"])},
        arb_ret={"return_value": None},        # arbitro no disponible
        reparado_ret={"side_effect": _reparar})
    res = _run(ps, gate_nota=7.0)
    assert capturado["defectos"] == ["errores de JavaScript: x"]
    assert res.nota_visual is None           # nunca hubo arbitro
    assert not any(d.startswith("(visual)") for d in capturado["defectos"])


# ── una reparacion que mejora avanza de ronda ────────────────────────────────

def test_una_reparacion_valida_avanza_y_luego_aprueba():
    # ronda 1: defecto -> repara; ronda 2: queda un defecto estructural menor
    # pero el arbitro la aprueba (9.0 >= gate) -> corta por gate.
    informes = [_informe(["feo"]), _informe(["menor"])]
    arbs = [{"nota": 4.0, "veredicto": "", "defectos": ["(x)"], "critico": "vlm"},
            {"nota": 9.0, "veredicto": "ok", "defectos": [], "critico": "vlm"}]

    ps = _parchar(
        informe_ret={"side_effect": informes},
        arb_ret={"side_effect": arbs},
        reparado_ret={"return_value": _prog(code="<html><body>v2</body></html>")})
    res = _run(ps, gate_nota=7.0, max_rondas=3)
    assert res.rondas == 2
    assert res.nota_visual == 9.0
    assert res.motivo_corte.startswith("fidelidad 9.0")


# ── el disyuntor corta la insistencia esteril ────────────────────────────────

def test_disyuntor_corta_si_el_sintoma_no_cambia():
    # Mismos defectos SIEMPRE + reparaciones que no arreglan nada: el disyuntor
    # debe cortar (D6) antes de agotar las rondas.
    mismo = ["todo del mismo color", "no cambia sola"]
    ps = _parchar(
        informe_ret={"return_value": _informe(mismo)},
        arb_ret={"return_value": None},
        reparado_ret={"return_value": _prog(code="<html><body>igual</body></html>")})
    res = _run(ps, gate_nota=7.0, max_rondas=6)
    assert res.motivo_corte.startswith("disyuntor")
    assert res.rondas < 6           # corto antes del tope


# ── entradas degeneradas ─────────────────────────────────────────────────────

def test_generacion_inicial_fallida():
    # generate_program devuelve None -> motivo_corte lo refleja, sin llegar al lazo.
    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "b", "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup", return_value=None), \
         patch.object(d2c, "generate_program", return_value=None):
        res = d2c.construir_para_mockup("x", verbose=False)
    assert "no se pudo generar" in res.motivo_corte


def test_mockup_provisto_no_se_regenera():
    """Con mockup_path se usa ESE mockup (no se llama a generar_mockup): permite
    generar el mockup aparte cuando SDXL no cabe junto a cerebro+VLM."""
    capturado = {}

    def _arb(idea, informe, mockup=None, **kw):
        capturado["mockup"] = mockup
        return None

    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "b", "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup") as _gm, \
         patch.object(d2c, "generate_program", return_value=_prog()), \
         patch.object(d2c, "revisar_en_navegador", return_value=_informe([])), \
         patch.object(d2c, "arbitrar_desde_informe", side_effect=_arb), \
         patch.object(d2c, "reparar_web", return_value=None):
        res = d2c.construir_para_mockup("un juego", verbose=False,
                                        mockup_path="/ruta/mock.png")
    _gm.assert_not_called()                       # NO se regenero
    assert res.mockup == "/ruta/mock.png"
    assert capturado["mockup"] == "/ruta/mock.png"  # llego al arbitro


def test_idea_no_web_se_reporta():
    prog_py = GeneratedProgram(title="P", description="d", code="print(1)",
                               category="x", lenguaje="python")
    ps = _parchar(
        informe_ret={"return_value": _informe([])},
        arb_ret={"return_value": None},
        reparado_ret={"return_value": None},
        prog_ini=prog_py)
    res = _run(ps)
    assert "no se resolvio como web" in res.motivo_corte
