"""
El JUEZ EJECUTABLE dentro del lazo diseno-a-codigo (2026-07-25).

Antes de esto el lazo entregaba por nota_visual de un VLM de 3B — el juez que
firmo 7.5/10 a un juego de memoria con las 16 cartas destapadas. Estos tests
verifican la LOGICA del cableado (el juez real con Chromium se prueba aparte,
en el banco brutal): con veredicto APROBADO se corta y se sella; con FALLIDO
la nota del VLM NO puede entregar y los contraejemplos van a reparar_web; sin
juez posible el sello queda "sin verificar" y rigen los cortes de siempre.
"""

from unittest.mock import patch

from cognia.program_creator import diseno_a_codigo as d2c
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.juez_ejecutable import Check, Veredicto
from cognia.program_creator.vista_navegador import InformeVisual


def _prog(code="<html><body>hola</body></html>"):
    return GeneratedProgram(title="P", description="d", code=code,
                            category="dashboard", lenguaje="html")


def _informe(defectos=None):
    return InformeVisual(defectos=list(defectos or []),
                         input_images=["/tmp/shot.png"])


def _veredicto(aprobado, fallas=()):
    v = Veredicto(producto="x", aprobado=aprobado, con_contrato=True)
    v.checks = [Check("carga", True, "ok", critico=True)] + [
        Check(nombre, False, detalle, critico=True)
        for nombre, detalle in fallas]
    v.motivo = "test"
    return v


def _base(informe_ret, arb_ret, reparado_ret, juez_ret):
    return [
        patch.object(d2c._mockup, "imaginar_vision",
                     return_value={"brief": "b", "prompt_imagen": "p"}),
        patch.object(d2c._mockup, "generar_mockup", return_value=None),
        patch.object(d2c, "generate_program", return_value=_prog()),
        patch.object(d2c, "revisar_en_navegador", **informe_ret),
        patch.object(d2c, "arbitrar_desde_informe", **arb_ret),
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


# ── APROBADO corta y sella, aunque el VLM opine lo contrario ─────────────────

def test_aprobado_del_juez_corta_aunque_haya_defectos_visuales():
    ps = _base(
        informe_ret={"return_value": _informe(["(cosmetico) header feo"])},
        arb_ret={"return_value": {"nota": 3.0, "veredicto": "no se parece",
                                  "defectos": ["feo"], "critico": "vlm"}},
        reparado_ret={"return_value": None},
        juez_ret={"return_value": _veredicto(True)})
    res = _run(ps)
    assert res.sello == "APROBADO"
    assert res.motivo_corte == "aprobado por juez ejecutable"
    assert res.rondas == 1


# ── FALLIDO: la nota bonita del VLM ya no entrega ────────────────────────────

def test_fallido_del_juez_bloquea_el_corte_por_nota():
    capturado = {}

    def _reparar(program, defectos, llm=None, profundo=False):
        capturado["defectos"] = list(defectos)
        return None                          # corta tras capturar

    ps = _base(
        informe_ret={"return_value": _informe([])},
        arb_ret={"return_value": {"nota": 9.5, "veredicto": "preciosa",
                                  "defectos": [], "critico": "vlm"}},
        reparado_ret={"side_effect": _reparar},
        juez_ret={"return_value": _veredicto(
            False, [("al cargar NINGUNA carta muestra su emoji",
                     "visibles('.tile')=16, esperaba 0")])})
    # max_rondas=3 explicito: el default de produccion es 1 (2026-07-27) y
    # este test necesita llegar a reparar_web para capturar los defectos.
    res = _run(ps, gate_nota=7.0, max_rondas=3)
    # Antes de este cableado, nota 9.5 >= 7.0 cortaba con "fidelidad": el VLM
    # entregaba un producto que el juez acababa de reprobar.
    assert res.sello == "FALLIDO"
    assert res.motivo_corte != "sin defectos"
    assert not res.motivo_corte.startswith("fidelidad")
    # El contraejemplo ejecutable viaja a reparar_web, y primero en la lista.
    assert capturado["defectos"][0].startswith("(juez)")
    assert "visibles('.tile')=16" in capturado["defectos"][0]


def test_fallido_luego_aprobado_en_dos_rondas():
    vs = [_veredicto(False, [("x", "esperaba 1")]), _veredicto(True)]
    ps = _base(
        informe_ret={"return_value": _informe([])},
        arb_ret={"return_value": None},
        reparado_ret={"return_value": _prog("<html><body>v2</body></html>")},
        juez_ret={"side_effect": vs})
    res = _run(ps, max_rondas=3)
    assert res.rondas == 2
    assert res.sello == "APROBADO"
    assert res.motivo_corte == "aprobado por juez ejecutable"


# ── sin juez: sello "sin verificar" y cortes de opinion de siempre ───────────

def test_sin_juez_sella_sin_verificar_y_corta_por_gate():
    ps = _base(
        informe_ret={"return_value": _informe(["algo"])},
        arb_ret={"return_value": {"nota": 8.0, "veredicto": "fiel",
                                  "defectos": [], "critico": "vlm"}},
        reparado_ret={"return_value": None},
        juez_ret={"return_value": None})
    res = _run(ps, gate_nota=7.0)
    assert res.sello == "sin verificar"
    assert res.motivo_corte.startswith("fidelidad 8.0")


# ── _juez_del_lazo: degradacion y memoria del intento ────────────────────────

def test_juez_del_lazo_sin_backend_no_insiste(tmp_path):
    res = d2c.ResultadoDiseno(idea="un contador")
    with patch("cognia.llm_local.disponible", return_value=False), \
         patch("cognia.program_creator.juez_ejecutable.generar_contrato") as gc:
        v1 = d2c._juez_del_lazo("un contador", "<html></html>", tmp_path, 1, res)
        v2 = d2c._juez_del_lazo("un contador", "<html></html>", tmp_path, 2, res)
    assert v1 is None and v2 is None
    assert res.contrato_fallido is True
    gc.assert_not_called()                   # sin backend ni se intenta


def test_contrato_generado_queda_escrito_junto_al_html(tmp_path):
    """Cableado 2026-08-01: escribir_contrato era una huerfana (solo el
    subcomando CLI `contrato` la usaba) y el lazo generaba contratos que morian
    en memoria. Ahora el contrato queda en disco (.contrato.json) junto al HTML
    juzgado: re-juzgable con el CLI del juez y auditable."""
    import json as _json

    from cognia.program_creator import juez_ejecutable as je

    contrato = {"idea": "un contador", "pasos": [{"accion": "carga"}]}
    res = d2c.ResultadoDiseno(idea="un contador")
    with patch("cognia.llm_local.disponible", return_value=True), \
         patch.object(je, "generar_contrato", return_value=contrato), \
         patch.object(je, "juzgar_web", return_value=_veredicto(True)):
        v = d2c._juez_del_lazo("un contador", "<html></html>", tmp_path, 1, res)
    assert v is not None and v.aprobado
    f = tmp_path / je.NOMBRE_CONTRATO
    assert f.exists(), "el contrato debe quedar escrito junto al HTML juzgado"
    assert _json.loads(f.read_text(encoding="utf-8")) == contrato


def test_contrato_fallido_paga_un_reintento_y_solo_uno(tmp_path):
    """El pensador falla por la cola de su razonamiento ~1 de 2 veces (medido
    2026-07-26): un None no puede condenar la construccion entera a salir sin
    verificar. Se reintenta UNA vez en la ronda siguiente; al segundo fallo se
    deja de insistir."""
    res = d2c.ResultadoDiseno(idea="x")
    with patch("cognia.llm_local.disponible", return_value=True), \
         patch("cognia.program_creator.juez_ejecutable.generar_contrato",
               return_value=None) as gc:
        d2c._juez_del_lazo("x", "<html></html>", tmp_path, 1, res)
        assert res.contrato_fallido is False     # aun queda un intento
        d2c._juez_del_lazo("x", "<html></html>", tmp_path, 2, res)
        assert res.contrato_fallido is True      # segundo fallo: se corta
        d2c._juez_del_lazo("x", "<html></html>", tmp_path, 3, res)
    assert gc.call_count == 2                    # la ronda 3 ya no paga


def test_construccion_inicial_va_a_temperatura_baja():
    """El lazo construye contra una VISION (y selectores OBLIGATORIOS): la
    generacion inicial debe ir a 0.2, no a la 0.9 creativa del hobby. Medido
    2026-07-26 en b2: 0.2 aprueba el contrato 6/7, 0.9 aprueba 1/5."""
    capturado = {}

    def _gen(seed_concepts=None, forced_idea=None, llm=None, temperature=0.90):
        capturado["temperature"] = temperature
        return _prog()

    with patch.object(d2c._mockup, "imaginar_vision",
                      return_value={"brief": "b", "prompt_imagen": "p"}), \
         patch.object(d2c._mockup, "generar_mockup", return_value=None), \
         patch.object(d2c, "generate_program", side_effect=_gen), \
         patch.object(d2c, "revisar_en_navegador", return_value=_informe([])), \
         patch.object(d2c, "arbitrar_desde_informe", return_value=None), \
         patch.object(d2c, "reparar_web", return_value=None), \
         patch.object(d2c, "_juez_del_lazo", return_value=None):
        d2c.construir_para_mockup("un contador web", verbose=False)
    assert capturado["temperature"] == 0.2


def test_generate_program_propaga_temperature():
    from cognia.program_creator import generator as g
    capturado = {}

    def _llm_capturador(prompt, lenguaje, temperature=0.90, llm=None):
        capturado["temperature"] = temperature
        return None                      # corta el resto del camino

    with patch.object(g, "_call_llm", side_effect=_llm_capturador):
        g.generate_program(forced_idea="una pagina web x", temperature=0.2)
    assert capturado["temperature"] == 0.2


def test_juez_del_lazo_veredicto_con_error_es_none(tmp_path):
    """Playwright ausente u otro fallo del harness NO es un FALLIDO del
    producto: el lazo debe seguir como si no hubiera juez."""
    res = d2c.ResultadoDiseno(idea="x", contrato={"pasos": [{"accion": "existe",
                                                             "selector": "#a"}]})
    roto = Veredicto(producto="x", error="playwright no instalado")
    with patch("cognia.program_creator.juez_ejecutable.juzgar_web",
               return_value=roto):
        v = d2c._juez_del_lazo("x", "<html></html>", tmp_path, 1, res)
    assert v is None
