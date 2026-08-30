"""
tests/test_flow.py — FASE 5: orquestador run_flow.
Fake orchestrator que cuenta inferencias (requisito critico: <=2 LLM por flujo).
Sin DB pesada (el fake AI no instancia memoria -> no dispara el seeder del KG).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeInfer:
    def __init__(self, text):
        self.text = text


class _FakeOrch:
    """Imita ShatteringOrchestrator.infer y cuenta llamadas."""
    def __init__(self, text="Respuesta sintetizada del flujo sobre el tema solicitado."):
        self.calls = 0
        self._text = text

    def infer(self, prompt, lpc_session_id=None, max_tokens=None, temperature=None):
        self.calls += 1
        return _FakeInfer(self._text)


class _FakeAI:
    def __init__(self, orch=None):
        self._orchestrator = orch


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.timeout_seconds = 5


class _FakeRegistry:
    """Registry hermetico: la etapa redaccion corre tools REALES
    (search_wikipedia = red), asi que los tests le dan outputs enlatados."""
    def __init__(self, outputs=None, fail=()):
        self.outputs = outputs or {}
        self.fail = set(fail)
        self.calls = []

    def get(self, name):
        if name in self.outputs or name in self.fail:
            return _FakeTool(name)
        return None

    def execute(self, name, **kwargs):
        from cognia.agents.tool_registry import ToolResult
        self.calls.append((name, kwargs))
        if name in self.fail:
            return ToolResult(False, None, "boom simulado", 1.0)
        return ToolResult(True, self.outputs[name], "", 1.0)


def _patch_registry(monkeypatch, registry):
    import cognia.agents.tool_registry as tr
    monkeypatch.setattr(tr, "get_tool_registry", lambda: registry)


def _effort(name):
    from cognia.effort_levels import get_effort
    return get_effort(name)


def test_simple_goal_one_inference():
    """Goal trivial (saludo) -> ruta fast [redaccion, informe] con 1 sola inferencia."""
    from cognia.agents.flow import run_flow
    orch = _FakeOrch()
    report = run_flow(_FakeAI(orch), "hola", _effort("bajo"), print_fn=lambda *_: None)
    assert orch.calls == 1
    assert "Respuesta sintetizada" in report
    assert "etapas=analisis>redaccion>informe" in report   # fast: sin plan/verificacion


def test_complex_goal_runs_verification_stage(monkeypatch):
    """Goal complejo + esfuerzo alto -> ruta deep con verificacion; <=2 inferencias."""
    from cognia.agents.flow import run_flow
    _patch_registry(monkeypatch, _FakeRegistry(outputs={
        "search_wikipedia": {"found": True, "title": "async", "extract": "dato"},
        "query_episodic": {"found": False, "content": ""},
    }))
    orch = _FakeOrch()
    goal = ("compara las ventajas y desventajas de async frente a threads en Python "
            "para un servidor concurrente de alta latencia")
    report = run_flow(_FakeAI(orch), goal, _effort("alto"), print_fn=lambda *_: None)
    assert "verificacion" in report
    assert 1 <= orch.calls <= 2
    assert "score=" in report


def test_degrades_without_backend(monkeypatch):
    """Sin backend (construccion del orquestador falla) -> informe determinista, no crashea."""
    import shattering.orchestrator as so

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no backend")

    monkeypatch.setattr(so, "ShatteringOrchestrator", _Boom)
    from cognia.agents.flow import run_flow
    _patch_registry(monkeypatch, _FakeRegistry())   # sin tools: solo contexto
    report = run_flow(_FakeAI(None), "que es una lista enlazada", _effort("bajo"),
                      print_fn=lambda *_: None)
    assert report and "etapas=" in report   # produjo informe determinista sin excepcion


def test_redaccion_ejecuta_tools_reales(monkeypatch):
    """REGRESION 2026-08-01: _stage_redaccion copiaba la DESCRIPCION del paso
    como output (el flujo nunca ejecutaba nada). Ahora la tool corre de verdad,
    con los kwargs que el planner extrajo (el TEMA, no el goal entero)."""
    from cognia.agents.flow import _stage_redaccion
    from cognia.agents.planner import SubTask
    reg = _FakeRegistry(outputs={
        "search_wikipedia": {"found": True, "title": "T", "extract": "DATO_REAL_XYZ"}})
    _patch_registry(monkeypatch, reg)
    st = SubTask(id="f_search", description="Search Wikipedia for the topic: goal entero",
                 tool_required="search_wikipedia", args={"query": "el tema"})
    ctx = {"goal": "g", "ai": _FakeAI(), "effort": {}, "print_fn": lambda *_: None,
           "subtasks": [st]}
    ctx = _stage_redaccion(ctx)
    assert reg.calls == [("search_wikipedia", {"query": "el tema"})]
    assert "DATO_REAL_XYZ" in ctx["results"]["f_search"]["output"]


def test_redaccion_fallo_marca_etapas_sin_ejecutar(monkeypatch):
    """Tool que falla -> results[id] = {'output': '', 'error': ...} y una linea
    visible '[etapas sin ejecutar: N]' (nada de exito fingido)."""
    from cognia.agents.flow import _stage_redaccion
    from cognia.agents.planner import SubTask
    _patch_registry(monkeypatch, _FakeRegistry(fail={"search_wikipedia"}))
    lineas = []
    st = SubTask(id="f_search", description="Search: x",
                 tool_required="search_wikipedia", args={"query": "x"})
    ctx = {"goal": "g", "ai": _FakeAI(), "effort": {}, "print_fn": lineas.append,
           "subtasks": [st]}
    ctx = _stage_redaccion(ctx)
    assert ctx["results"]["f_search"]["output"] == ""
    assert "boom simulado" in ctx["results"]["f_search"]["error"]
    assert any("[etapas sin ejecutar: 1]" in l for l in lineas)


def _ctx_ejecucion(goal, subtasks, lineas):
    return {"goal": goal, "ai": _FakeAI(), "effort": {}, "print_fn": lineas.append,
            "subtasks": subtasks}


def test_redaccion_run_code_manda_el_codigo_real(monkeypatch):
    """REGRESION 2026-08-01 (revision adversarial): build_tool_kwargs solo se
    habia arreglado para las tools de investigacion. run_code seguia mandando
    la DESCRIPCION literal del paso como 'code' ({'code': 'Validate Python
    syntax before running: ejecuta print(2+2)...'}) y el sandbox devolvia
    ToolResult.success=True con esa basura."""
    from cognia.agents.flow import _stage_redaccion
    from cognia.agents.planner import plan_task
    reg = _FakeRegistry(outputs={
        "validate_python": {"valid": True, "errors": [], "warnings": []},
        "execute_python": {"success": True, "output": "4\n", "errors": ""}})
    _patch_registry(monkeypatch, reg)
    goal = "ejecuta print(2+2) y dime el resultado"
    lineas = []
    ctx = _stage_redaccion(_ctx_ejecucion(goal, plan_task(goal, task_id="flujo"), lineas))
    assert reg.calls == [("validate_python", {"code": "print(2+2)"}),
                         ("execute_python", {"code": "print(2+2)"})]
    # nada de descripcion de paso viajando como codigo
    assert all("Validate Python syntax" not in kw["code"] for _, kw in reg.calls)
    assert not any("sin ejecutar" in l for l in lineas)
    assert "4" in ctx["results"]["flujo_execute"]["output"]


def test_redaccion_sin_codigo_extraible_marca_sin_ejecutar(monkeypatch):
    """Pedido sin codigo real -> NO se ejecuta nada y el hueco es VISIBLE.
    Jamas un success=True con la descripcion del paso ejecutada."""
    from cognia.agents.flow import _stage_redaccion
    from cognia.agents.planner import plan_task
    reg = _FakeRegistry(outputs={
        "validate_python": {"valid": True}, "execute_python": {"success": True}})
    _patch_registry(monkeypatch, reg)
    goal = "ejecuta el programa que calcula la nomina"
    lineas = []
    ctx = _stage_redaccion(_ctx_ejecucion(goal, plan_task(goal, task_id="flujo"), lineas))
    assert reg.calls == []                       # no se ejecuto basura
    assert any("[etapas sin ejecutar: 2]" in l for l in lineas)
    assert ctx["results"]["flujo_validate"]["output"] == ""
    assert "sin argumento" in ctx["results"]["flujo_execute"]["error"]


def test_analisis_route_differs_by_complexity():
    """Decision dinamica de etapas (0 LLM): simple vs complejo dan rutas distintas."""
    from cognia.agents.flow import _stage_analisis
    simple = _stage_analisis({"goal": "hola", "effort": {}, "print_fn": lambda *_: None})
    cplx = _stage_analisis({
        "goal": ("explica como se compara async vs threads en python con cache, latency y "
                 "memory en un sistema distribuido concurrent"),
        "effort": {}, "print_fn": lambda *_: None})
    assert simple["route"] == ["redaccion", "informe"]
    assert "verificacion" in cplx["route"]
    assert simple["route"] != cplx["route"]


def test_empty_goal_returns_usage():
    from cognia.agents.flow import run_flow
    out = run_flow(_FakeAI(), "   ", _effort("medio"), print_fn=lambda *_: None)
    assert "vacio" in out.lower()


# ── HONESTIDAD DE /flujo (2026-08-29) ──────────────────────────────────────
# El dueno: "los workflows no entregan nada al final ni hacen nada en mi PC".
# Para /flujo es CIERTO POR DISENO. Lo que se arregla no es la capacidad (eso ya
# lo hace /hacer con 16 tools reales): es que el resultado lo diga.


def test_flujo_no_escribe_nada_en_el_disco_y_lo_declara(tmp_path, monkeypatch):
    """EFECTO OBSERVABLE, con el registro REAL de agents/tool_registry.

    Se le pide EXACTAMENTE lo que el dueno pidio ("escribe el fichero X") desde
    un cwd vacio y se afirma sobre el DISCO: no aparece ni un fichero. Y como
    /flujo no puede entregarlo, el informe tiene que empezar diciendolo. Ningun
    monkeypatch del registry: si alguna plantilla del planner empezara a emitir
    write_file, este test lo veria en el disco y se pondria rojo (a proposito).
    """
    from cognia.agents.flow import CABECERA_INFORME, run_flow
    from cognia.agents.tool_registry import get_tool_registry

    monkeypatch.chdir(tmp_path)
    reg = get_tool_registry()
    assert reg.get("write_file") is not None, (
        "el registro SI tiene con que escribir: por eso el nombre 'ejecucion' "
        "enganaba y por eso este test mira el disco")

    orch = _FakeOrch("Para escribir ese fichero necesitas /hacer.")
    report = run_flow(_FakeAI(orch),
                      "escribe el fichero PRUEBA_FLUJO.txt con el texto HOLA_FLUJO",
                      _effort("alto"), print_fn=lambda *_: None)

    assert list(tmp_path.iterdir()) == [], (
        f"/flujo dejo ficheros en el PC: {[p.name for p in tmp_path.iterdir()]}")
    assert not (tmp_path / "PRUEBA_FLUJO.txt").exists()
    assert report.startswith(CABECERA_INFORME), report[:200]
    assert "/hacer" in report and "/flujoteca ejecutar" in report


def test_la_cabecera_va_primera_y_no_al_final():
    """Un aviso al pie de 4.000 tokens de informe es decoracion."""
    from cognia.agents.flow import CABECERA_INFORME, run_flow
    report = run_flow(_FakeAI(_FakeOrch()), "hola", _effort("bajo"),
                      print_fn=lambda *_: None)
    assert report.index(CABECERA_INFORME) == 0
    assert "NO ejecuta nada en tu PC" in report


def test_el_eco_del_objetivo_no_se_devuelve_como_resultado(monkeypatch):
    """Ruta rapida sin backend: el informe era el objetivo LITERAL y salia como
    resultado (medido: goal='escribe el fichero X' -> 'Results for: <goal>


    [step] <goal>', 1,4 s, 0 ficheros). Ahora se declara que no hay contenido."""
    import shattering.orchestrator as so

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no backend")

    monkeypatch.setattr(so, "ShatteringOrchestrator", _Boom)
    from cognia.agents.flow import SIN_CONTENIDO, run_flow
    _patch_registry(monkeypatch, _FakeRegistry())
    goal = "escribe el fichero PRUEBA_FLUJO.txt con el texto HOLA_FLUJO"
    report = run_flow(_FakeAI(None), goal, _effort("bajo"), print_fn=lambda *_: None)
    assert SIN_CONTENIDO in report
    assert "Results for:" not in report
    # el objetivo no vuelve disfrazado de informe
    cuerpo = report.split("[flujo:")[0]
    assert "PRUEBA_FLUJO.txt" not in cuerpo


def test_un_informe_con_contenido_propio_no_se_marca_sin_contenido():
    """Contra-caso: si el modelo aporta algo, se entrega tal cual."""
    from cognia.agents.flow import SIN_CONTENIDO, run_flow
    orch = _FakeOrch("Una lista enlazada es una estructura de nodos encadenados.")
    report = run_flow(_FakeAI(orch), "que es una lista enlazada", _effort("bajo"),
                      print_fn=lambda *_: None)
    assert "estructura de nodos encadenados" in report
    assert SIN_CONTENIDO not in report


def test_ninguna_etapa_se_anuncia_como_ejecucion():
    """La etapa se llama 'redaccion': prometer 'ejecucion' es la mentira que el
    dueno cazo. El alias viejo sigue en STAGES para no romper un flujo
    persistido, pero NO se anuncia."""
    from cognia.agents.flow import STAGES, _stage_analisis
    lineas = []
    ctx = _stage_analisis({"goal": "hola", "effort": {}, "print_fn": lineas.append})
    assert "ejecucion" not in ctx["route"]
    assert "ejecucion" not in " ".join(lineas)
    assert STAGES["ejecucion"] is STAGES["redaccion"]   # compat, sin anuncio
