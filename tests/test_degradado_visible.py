"""
FASE A2 (2026-07-25): ningun degradado puede ser silencioso.

Motivo real: el sistema tenia DOS backends y nadie lo sabia, y encima cada
pieza sabia degradar sin decirlo — el juez devolvia hallazgos SIN JUZGAR con
el mismo aspecto que los juzgados, el arbitro visual devolvia None y el lazo
seguia como si hubiera mirado, el pulidor escribia "el pensador decidio
ENTREGAR" cuando el pensador no habia contestado, y el STAGE 5 del motor de
lenguaje devolvia una frase canned indistinguible de una respuesta pensada.

Estos tests fijan la MARCA, no el comportamiento: el control de flujo es el
mismo de antes (por eso los tests viejos siguen pasando).
"""

from dataclasses import dataclass
from unittest.mock import patch

from cognia.experts.prompt_forge import forge_prompt
from cognia.program_creator import arbitro_visual as av
from cognia.program_creator import mockup as mk
from cognia.program_creator import pulidor as pl
from cognia.program_creator.generator import GeneratedProgram
from cognia.research_engine import juez, query_planner as qp


# ── juez: una lista sin juicio no puede parecer aprobada ────────────────────

@dataclass
class _H:
    fuente: str
    titulo: str
    resumen: str
    relevancia: float


def _hallazgos():
    return [_H("wikipedia", "Bernhard Rust", "politico aleman", 10.0),
            _H("github", "rust-lang/rust", "el lenguaje", 9.0)]


def test_juez_sin_llm_sella_los_hallazgos_como_no_juzgados():
    hs = _hallazgos()
    with patch("cognia.research_engine.juez.disponible", return_value=False):
        out = juez.juzgar("rust ownership", hs)
    assert out == hs                                   # comportamiento intacto
    assert all(h.juzgado is False for h in out)        # pero marcado
    assert all("SIN JUZGAR" in h.motivo_sin_juicio for h in out)


def test_juez_con_llm_sella_juzgado_true():
    hs = _hallazgos()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar", return_value="1: NO\n2: SI"):
        out = juez.juzgar("rust ownership", hs)
    assert all(h.juzgado is True for h in out)


def test_juez_marca_los_que_el_modelo_se_salto():
    hs = _hallazgos()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar", return_value="1: NO"):
        out = juez.juzgar("rust ownership", hs)
    sin = [h for h in out if h.juzgado is False]
    assert [h.titulo for h in sin] == ["rust-lang/rust"]


# ── arbitro visual: el None NO es un veredicto ─────────────────────────────

def test_arbitro_sin_vlm_deja_estado_sin_vlm(tmp_path):
    p = tmp_path / "s.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch.object(av, "vlm_disponible", return_value=(False, "sin VLM")):
        assert av.arbitrar_visual("idea", p) is None
    assert av.ultimo_estado()["sin_vlm"] is True


def test_arbitro_que_juzga_marca_sin_vlm_false(tmp_path):
    p = tmp_path / "s.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm",
                      return_value="NOTA: 7.0\nVEREDICTO: ok\nDEFECTOS:\n- ninguno"):
        r = av.arbitrar_visual("idea", p)
    assert r["sin_vlm"] is False
    assert av.ultimo_estado()["sin_vlm"] is False


# ── mockup: la idea cruda copiada NO es una vision imaginada ───────────────

def test_vision_degradada_viene_marcada():
    with patch.object(mk, "generar", return_value=None):
        v = mk.imaginar_vision("un juego de plataformas", llm=None)
    assert v["degradado"] is True
    assert v["brief"] == "un juego de plataformas"
    assert v["motivo"]


def test_vision_real_no_esta_marcada():
    with patch.object(mk, "generar",
                      return_value="BRIEF: fondo oscuro\nIMAGEN: dark ui"):
        v = mk.imaginar_vision("idea", llm=None)
    assert v["degradado"] is False


# ── query_planner: el origen del plan viaja con el plan ────────────────────

def test_plan_sin_llm_dice_que_es_deterministico():
    with patch.object(qp, "generar", return_value=None):
        qs, origen = qp.planificar_busquedas("modelo pequeno con contexto",
                                             n=3, con_origen=True)
    assert qs                                   # el plan sigue existiendo
    assert origen["origen"] == "deterministico"
    assert "SIN LLM" in origen["motivo"]


def test_plan_con_llm_dice_que_lo_penso_el_llm():
    with patch.object(qp, "generar",
                      return_value="small context model\nlong context llm"):
        qs, origen = qp.planificar_busquedas("modelo pequeno con contexto",
                                             n=3, con_origen=True)
    assert origen["origen"] == "llm+deterministico"
    assert qp.ultimo_origen()["origen"] == "llm+deterministico"


def test_planificar_sin_con_origen_sigue_devolviendo_una_lista():
    """Contrato viejo intacto: quien no pida el origen recibe la lista pelada."""
    with patch.object(qp, "generar", return_value=None):
        qs = qp.planificar_busquedas("modelo pequeno", n=2)
    assert isinstance(qs, list)


# ── prompt_forge: el aviso viaja DENTRO del .md ────────────────────────────

def _silencio(*a, **k):
    pass


def test_prompt_de_plantilla_arranca_avisando():
    md = forge_prompt("Chef", "recetas", "chat-7b", llm_fn=lambda p: None,
                      print_fn=_silencio)
    assert "PLANTILLA ESTATICA" in md.splitlines()[2]
    assert md.count("\n## ") == 8            # sigue teniendo 8 secciones


def test_prompt_forjado_de_verdad_no_lleva_aviso():
    largo = "Eres un experto meticuloso que trabaja con rigor real. " * 20
    md = forge_prompt("Chef", "recetas", "chat-7b", llm_fn=lambda p: largo,
                      print_fn=_silencio)
    assert "PLANTILLA ESTATICA" not in md


# ── pulidor: el reporte no puede atribuir decisiones a nadie ───────────────

class _R1:
    def __init__(self, code):
        self.program = GeneratedProgram(title="P", description="d", code=code,
                                        category="g", lenguaje="html")
        self.motivo_corte = "x"

    def html_entregable(self):
        return self.program.code


def test_decidir_sin_pensador_marca_sin_pensador():
    with patch.object(pl, "_pensador", return_value=None):
        d = pl._decidir("g", 5.0, ["x"], 1, 4, [])
    assert d["seguir"] is False               # comportamiento intacto
    assert d["sin_pensador"] is True          # y ya no parece una decision


def test_el_corte_sin_pensador_no_dice_que_lo_decidio_el_pensador(tmp_path):
    ps = [
        patch.object(pl, "_combo", return_value=True),
        patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
              return_value=_R1("<html><body>v1</body></html>")),
        patch.object(pl, "_juzgar", return_value=(6.0, ["x"], None)),
        patch.object(pl, "_pensador", return_value=None),
        patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path),
    ]
    for p in ps:
        p.start()
    try:
        res = pl.pulir("un juego chico", verbose=False, gestionar_flota=False,
                       gate_final=9.5, ciclos_max=3)
    finally:
        for p in reversed(ps):
            p.stop()

    assert res.ciclos == 1
    assert "SIN PENSADOR" in res.motivo
    assert any("pensador no respondio" in d for d in res.degradaciones)
    reporte = (tmp_path / "pulidos" / "un_juego_chico" / "reporte.md").read_text(
        encoding="utf-8")
    assert "## Degradaciones" in reporte
    assert "pensador no respondio" in reporte


def test_reporte_sano_declara_que_no_hubo_degradaciones(tmp_path):
    ps = [
        patch.object(pl, "_combo", return_value=True),
        patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
              return_value=_R1("<html><body>v1</body></html>")),
        patch.object(pl, "_juzgar", return_value=(9.0, [], None)),
        patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path),
    ]
    for p in ps:
        p.start()
    try:
        res = pl.pulir("un juego chico", verbose=False, gestionar_flota=False,
                       gate_final=8.5)
    finally:
        for p in reversed(ps):
            p.stop()

    assert res.degradaciones == []
    reporte = (tmp_path / "pulidos" / "un_juego_chico" / "reporte.md").read_text(
        encoding="utf-8")
    assert "ninguna: goal real" in reporte


def test_goal_canned_queda_dicho_en_el_reporte(tmp_path):
    """Sin sueno del pensador el goal es de relleno: el reporte tiene que
    decirlo o parece que el modelo eligio construir eso."""
    ps = [
        patch.object(pl, "_combo", return_value=True),
        patch.object(pl, "sonar_goal", return_value=None),
        patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
              return_value=_R1("<html><body>v1</body></html>")),
        patch.object(pl, "_juzgar", return_value=(9.0, [], None)),
        patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path),
    ]
    for p in ps:
        p.start()
    try:
        res = pl.pulir(None, verbose=False, gestionar_flota=False,
                       gate_final=8.5, usar_mockup=False)
    finally:
        for p in reversed(ps):
            p.stop()

    assert res.goal == "una pagina web visual e interactiva"
    assert any("GOAL CANNED" in d for d in res.degradaciones)
    reporte = (tmp_path / "pulidos" / list(
        (tmp_path / "pulidos").iterdir())[0].name / "reporte.md")
    assert "GOAL CANNED" in reporte.read_text(encoding="utf-8")
    assert "DEGRADADO" in res.resumen()
