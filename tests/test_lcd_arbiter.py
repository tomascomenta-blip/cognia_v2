"""
Regresion del arbitro AI-nativo de LCD (cognia_x/lcd/arbiter.py + tools
atribuir_fallo/reejecutar_etapa): atribucion por etapa cero-LLM con fallos
inyectados como ground-truth. Plan 12, Fase 1/3 (el aporte de investigacion).
"""
import cognia_x.lcd.tools_lcd as _lcd   # noqa: F401 -- registra las tools
from cognia.agent.tools import run_tool, TOOLS
from cognia_x.lcd.arbiter import (
    attribute_scene_failure, eval_attribution, inject_fault,
)
from cognia_x.lcd.planner import plan

SPECS = [
    "a red cup on a blue table", "una taza roja sobre una mesa azul",
    "a green ball to the left of a yellow box", "a book on a table",
    "un plato sobre una mesa", "a lamp to the right of a chair",
    "a sun above a house", "una pelota debajo de una mesa",
]


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


def test_escena_correcta_no_tiene_culpa():
    v = attribute_scene_failure("a red cup on a blue table",
                                plan("a red cup on a blue table"))
    assert v["stage"] is None
    assert "todos los contratos pasan" in v["reason"]


def test_atribucion_100pct_con_culpas_balanceadas():
    """El resultado clave del CP2: cascada cero-LLM atribuye TODOS los fallos
    inyectados a su etapa, con distribucion balanceada (anti-colapso)."""
    r = eval_attribution(SPECS)
    assert r["accuracy"] == 1.0, r
    # ninguna etapa acapara las culpas (el sesgo que colapso al arbitro-LLM)
    culpas = r["culpa_distribution"]
    assert culpas["plan"] > 0 and culpas["geometria"] > 0 and culpas["render"] > 0
    # sin confusion fuera de la diagonal
    off = {k: v for k, v in r["confusion"].items()
           if k.split("->")[0] != k.split("->")[1]}
    assert off == {}, off


def test_fallo_plan_se_atribuye_a_plan():
    base = plan("a red cup on a blue table")
    corrupt, render_ok = inject_fault(base, "plan")
    v = attribute_scene_failure("a red cup on a blue table", corrupt, render_ok)
    assert v["stage"] == "plan"


def test_fallo_geometria_se_atribuye_a_geometria():
    base = plan("a green ball to the left of a yellow box")
    corrupt, render_ok = inject_fault(base, "geometria")
    v = attribute_scene_failure("a green ball to the left of a yellow box",
                                corrupt, render_ok)
    assert v["stage"] == "geometria"


def test_fallo_render_se_atribuye_a_render():
    base = plan("a book on a table")
    corrupt, render_ok = inject_fault(base, "render")   # render_ok=False
    v = attribute_scene_failure("a book on a table", corrupt, render_ok)
    assert v["stage"] == "render"


# ── tools atribuir_fallo / reejecutar_etapa ──────────────────────────────

def test_tools_arbitro_registradas():
    assert "atribuir_fallo" in TOOLS and "reejecutar_etapa" in TOOLS


def test_atribuir_fallo_tool_escena_correcta():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("atribuir_fallo", "", ctx)
    assert "todos los contratos pasan" in out


def test_reejecutar_etapa_repara_fallo_de_plan():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    # corromper la escena viva: borrar un objeto (fallo de plan)
    scene = ctx["working_memory"]["_lcd_scene"]["escena"]
    scene.objects = scene.objects[:-1]
    culpa = run_tool("atribuir_fallo", "", ctx)
    assert "plan" in culpa
    # re-ejecutar plan -> escena reparada (control 3/3 de nuevo)
    rep = run_tool("reejecutar_etapa", "plan", ctx)
    assert "control 3/3" in rep
    assert "todos los contratos pasan" in run_tool("atribuir_fallo", "", ctx)


def test_reejecutar_etapa_render_escribe_png(tmp_path, monkeypatch):
    ctx = _ctx()
    monkeypatch.chdir(tmp_path)
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("reejecutar_etapa", "render", ctx)
    assert "ERROR" not in out and "PNG" in out


def test_reejecutar_etapa_invalida():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "ERROR" in run_tool("reejecutar_etapa", "materiales", ctx)
