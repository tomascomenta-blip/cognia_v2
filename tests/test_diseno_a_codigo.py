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
    devolviendo lo que el test dicte. Devuelve una lista de patchers activos.
    El juez ejecutable tambien se neutraliza (LLM + Chromium): estos tests
    verifican los cortes de OPINION; los del juez van en
    test_diseno_a_codigo_juez.py."""
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
        patch.object(d2c, "_juez_del_lazo", return_value=None),
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

    def _reparar(program, defectos, llm=None, profundo=False):
        capturado["defectos"] = list(defectos)
        return None      # corta tras capturar

    ps = _parchar(
        informe_ret={"return_value": _informe(["la pagina no cambia sola"])},
        arb_ret={"return_value": {"nota": 3.0, "veredicto": "no se parece",
                                  "defectos": ["el header deberia ser una barra"],
                                  "critico": "vlm"}},
        reparado_ret={"side_effect": _reparar})
    res = _run(ps, gate_nota=7.0, max_rondas=3)
    # El estructural va tal cual; el visual va prefijado con "(visual)".
    assert "la pagina no cambia sola" in capturado["defectos"]
    assert any(d.startswith("(visual) ") for d in capturado["defectos"])
    assert res.nota_visual == 3.0


# ── degradacion sin VLM: solo defectos estructurales ─────────────────────────

def test_sin_vlm_usa_solo_defectos_estructurales():
    capturado = {}

    def _reparar(program, defectos, llm=None, profundo=False):
        capturado["defectos"] = list(defectos)
        return None

    ps = _parchar(
        informe_ret={"return_value": _informe(["errores de JavaScript: x"])},
        arb_ret={"return_value": None},        # arbitro no disponible
        reparado_ret={"side_effect": _reparar})
    res = _run(ps, gate_nota=7.0, max_rondas=3)
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


# ── defectos estaticos: elementos que desaparecen / alert() ─────────────────

def test_detecta_ids_desaparecidos():
    """El bug del juego arcade: draw() vaciaba el contenedor con innerHTML=''
    y borraba #ship y #hud — la pagina quedaba en puntitos sobre negro."""
    fuente = '<div id="game"><div id="ship"></div><div id="hud"></div></div>'
    dom = '<div id="game"><div class="asteroid"></div></div>'
    perdidos = d2c._ids_desaparecidos(fuente, dom)
    assert perdidos == ["ship", "hud"]


def test_ids_presentes_no_disparan():
    fuente = '<div id="game"><div id="ship"></div></div>'
    dom = '<div id="game"><div id="ship" style="left:10px"></div></div>'
    assert d2c._ids_desaparecidos(fuente, dom) == []


def test_defecto_estatico_por_alert():
    inf = _informe([])
    inf.dom_renderizado = "<div></div>"
    defs = d2c._defectos_estaticos("<script>alert('Game Over')</script>", inf)
    assert any("alert()" in d for d in defs)


def test_los_defectos_estaticos_entran_al_lazo():
    """El lazo debe pasar los defectos estaticos a reparar_web junto al resto."""
    capturado = {}

    def _reparar(program, defectos, llm=None, profundo=False):
        capturado["defectos"] = list(defectos)
        return None

    inf = _informe(["algo"])
    inf.dom_renderizado = "<div></div>"     # sin #ship -> desaparecido
    prog = _prog(code='<html><body><div id="ship"></div>'
                      "<script>alert(1)</script></body></html>")
    ps = _parchar(
        informe_ret={"return_value": inf},
        arb_ret={"return_value": None},
        reparado_ret={"side_effect": _reparar},
        prog_ini=prog)
    _run(ps, gate_nota=7.0, max_rondas=3)
    assert any("DESAPARECEN" in d for d in capturado["defectos"])
    assert any("alert()" in d for d in capturado["defectos"])


# ── el brief entra a la generacion ──────────────────────────────────────────

def test_el_brief_viaja_en_la_idea_de_generacion():
    """Hasta 2026-07-24 la vision solo la veia el arbitro; el constructor
    generaba a ciegas. El brief debe ir en la idea forzada."""
    capturado = {}

    def _gen(forced_idea=None, llm=None, temperature=0.90):
        capturado["idea"] = forced_idea
        return _prog()

    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "neon arcade con HUD",
                                    "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup", return_value=None), \
         patch.object(d2c, "generate_program", side_effect=_gen), \
         patch.object(d2c, "revisar_en_navegador", return_value=_informe([])), \
         patch.object(d2c, "arbitrar_desde_informe", return_value=None), \
         patch.object(d2c, "reparar_web", return_value=None), \
         patch.object(d2c, "_juez_del_lazo", return_value=None):
        d2c.construir_para_mockup("un juego", verbose=False)
    assert "TARGET LOOK" in capturado["idea"]
    assert "neon arcade con HUD" in capturado["idea"]


# ── sprites: el cerebro le pide elementos al modelo de imagenes ─────────────

def test_proponer_sprites_parsea_lineas():
    def _llm(prompt, system, max_tokens, temperature):
        return ("SPRITE nave: sleek neon spaceship seen from above\n"
                "basura sin formato\n"
                "SPRITE asteroide: glowing yellow asteroid rock with craters\n")
    specs = d2c._proponer_sprites("juego", "arcade neon", llm=_llm)
    assert [s["name"] for s in specs] == ["nave", "asteroide"]
    assert "spaceship" in specs[0]["prompt"]


def test_sprites_con_assets_precalc_no_toca_gpu():
    """Con assets pre-generados el lazo NO llama a preparar_assets (GPU), el
    fuente que ve el LLM queda limpio y el entregable lleva el base64."""
    specs = [{"name": "nave", "prompt": "spaceship"}]
    assets = {"nave": "data:image/png;base64,AAAA"}
    capturado = {}

    def _llm_falso(prompt, system, max_tokens, temperature):
        capturado["prompt"] = prompt
        return ('Title: J\nDescription: d\nHTML Code:\n```html\n'
                '<!DOCTYPE html>\n<html><body>'
                '<img data-asset="nave"></body></html>\n```')

    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "b", "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup", return_value=None), \
         patch.object(d2c, "revisar_en_navegador", return_value=_informe([])), \
         patch.object(d2c, "arbitrar_desde_informe", return_value=None), \
         patch.object(d2c, "reparar_web", return_value=None), \
         patch.object(d2c, "_juez_del_lazo", return_value=None), \
         patch("cognia.program_creator.asset_bridge.preparar_assets") as _pa:
        res = d2c.construir_para_mockup(
            "un juego", verbose=False, llm=_llm_falso,
            sprites=specs, assets=assets)

    _pa.assert_not_called()                       # GPU intacta
    assert 'data-asset="nave"' in capturado["prompt"]   # el modelo los conocio
    assert "base64" not in res.html               # fuente limpio
    assert "base64,AAAA" in res.html_entregable() # entregable con sprite


def test_sin_gpu_el_lazo_sigue_sin_sprites():
    """preparar_assets muere (GPU ocupada) -> se degrada a la via normal."""
    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "b", "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup", return_value=None), \
         patch.object(d2c, "generate_program", return_value=_prog()) as _gp, \
         patch.object(d2c, "revisar_en_navegador", return_value=_informe([])), \
         patch.object(d2c, "arbitrar_desde_informe", return_value=None), \
         patch.object(d2c, "reparar_web", return_value=None), \
         patch.object(d2c, "_juez_del_lazo", return_value=None), \
         patch("cognia.program_creator.asset_bridge.preparar_assets",
               side_effect=RuntimeError("CUDA out of memory")):
        res = d2c.construir_para_mockup(
            "un juego", verbose=False,
            sprites=[{"name": "n", "prompt": "x"}])
    _gp.assert_called_once()          # cayo a la generacion normal
    assert res.assets == {}
    assert res.motivo_corte == "sin defectos"


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
         patch.object(d2c, "reparar_web", return_value=None), \
         patch.object(d2c, "_juez_del_lazo", return_value=None):
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
