"""
Regresion de las herramientas AI-nativas de LCD (cognia/lcd/tools_lcd.py):
escena_crear/editar/consultar/render_aprox como tools ACCION con oraculo cero-LLM.
Plan 12 (herramientas virtuales para IAs), Fase 0/1.
"""
import cognia.lcd.tools_lcd as lcd_tools   # noqa: F401 -- registra las tools
from cognia.agent.tools import run_tool, TOOLS
from cognia.lcd.planner import plan
from cognia.lcd.tools_lcd import control_check


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


def test_tools_registradas_en_el_registry():
    for t in ("escena_crear", "escena_editar", "escena_consultar", "render_aprox"):
        assert t in TOOLS, f"{t} no registrada"


def test_escena_crear_construye_y_verifica():
    ctx = _ctx()
    out = run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "ERROR" not in out
    assert "2 objetos" in out
    assert "control 3/3" in out          # presentes + conteo + relacion OK
    # la escena viva persiste en working_memory (componible)
    assert "escena" in ctx["working_memory"]["_lcd_scene"]


def test_escena_crear_sin_objetos_es_error():
    out = run_tool("escena_crear", "algo abstracto sin objetos conocidos", _ctx())
    assert "ERROR" in out and "objetos" in out


def test_control_check_es_oraculo_cero_llm():
    scene = plan("a green ball to the left of a yellow box")
    chk = control_check(scene, "a green ball to the left of a yellow box")
    assert chk["present"] and chk["count_ok"] and chk["relation_ok"]
    assert chk["score"] == 3 and chk["total"] == 3


def test_escena_editar_selectiva_no_toca_el_resto():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_editar", "cup | color=green", ctx)
    assert "ERROR" not in out
    assert "resto intacto=True" in out   # la mesa NO cambio (diferenciador §8.2)
    # verificar en la escena real
    scene = ctx["working_memory"]["_lcd_scene"]["escena"]
    assert scene.get("cup").color == (70, 180, 90)      # verde
    assert scene.get("table").color == (60, 110, 220)   # azul intacto


def test_escena_editar_posicion_numerica():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_editar", "cup | x=0.3", ctx)
    assert "ERROR" not in out
    assert ctx["working_memory"]["_lcd_scene"]["escena"].get("cup").x == 0.3


def test_escena_editar_objeto_inexistente():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "ERROR" in run_tool("escena_editar", "avion | color=red", ctx)


def test_escena_editar_sin_escena_activa():
    assert "ERROR" in run_tool("escena_editar", "cup | color=red", _ctx())


def test_escena_consultar_todo_y_objeto():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    todo = run_tool("escena_consultar", "", ctx)
    assert "2 objetos" in todo
    uno = run_tool("escena_consultar", "cup", ctx)
    assert "forma=" in uno and "pos=" in uno


def test_render_aprox_escribe_png(tmp_path):
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    dest = str(tmp_path / "escena.png")
    out = run_tool("render_aprox", dest, ctx)
    assert "ERROR" not in out
    from pathlib import Path
    assert Path(dest).exists() and Path(dest).stat().st_size > 0


def test_render_aprox_sin_escena_es_error():
    assert "ERROR" in run_tool("render_aprox", "", _ctx())


# ── CP3: planner-LLM como fallback en lenguaje natural (fuera de reglas) ──

class _FakeInfer:
    def __init__(self, text): self.text = text


class _FakeOrchScene:
    """orch.infer que devuelve una escena JSON valida (simula el 3B planner)."""
    def infer(self, prompt, **kw):
        return _FakeInfer('{"objects":[{"name":"dragon","shape":"triangle",'
                          '"x":0.5,"y":0.6,"w":0.2,"h":0.2,"color":[200,60,60]}]}')


def test_escena_crear_usa_reglas_cuando_reconoce():
    ctx = _ctx()
    out = run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "(reglas)" in out          # ruta de reglas, no LLM


def test_escena_crear_cae_a_planner_llm_fuera_de_vocabulario():
    # 'dragon' no esta en la gramatica de reglas -> plan() da 0 objetos ->
    # con orch en ctx, usa el planner-LLM.
    class _AI:
        _orchestrator = _FakeOrchScene()
    ctx = {"working_memory": {}, "agent_state": {}, "ai": _AI()}
    out = run_tool("escena_crear", "un dragon en el centro", ctx)
    assert "planner-LLM" in out
    assert "dragon" in ctx["working_memory"]["_lcd_scene"]["escena"].get("dragon").name


def test_escena_crear_sin_orch_ni_reglas_es_error():
    # fuera de vocabulario y sin modelo -> error claro
    out = run_tool("escena_crear", "un dragon en el centro", _ctx())
    assert "ERROR" in out
