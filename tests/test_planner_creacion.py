# -*- coding: utf-8 -*-
"""REGRESION 2026-08-01 (auditoria A8): el clasificador de tareas por keywords
no conocia los verbos de CREACION: "crear un juego HTML sobre el sistema solar
con informacion de los planetas" clasificaba research_topic (por "informacion")
y terminaba en search_wikipedia con el objetivo ENTERO como query. Ahora:
- verbo de creacion VETA research_topic/explain_concept (cae al plan generico,
  cuyo research_llm si razona sobre el goal completo);
- "informacion"/"information" solas no clasifican research_topic;
- el planner extrae el TEMA a SubTask.args y el supervisor lo usa como query.
"""
from cognia.agents.planner import SubTask, classify_task, plan_task
from cognia.agents.supervisor import build_tool_kwargs

GOAL_CREACION = "crear un juego HTML sobre el sistema solar con informacion de los planetas"


def test_creacion_no_es_research_topic():
    assert classify_task(GOAL_CREACION) not in ("research_topic", "explain_concept")


def test_creacion_cae_al_plan_generico_con_research_llm():
    plan = plan_task(GOAL_CREACION, task_id="t")
    assert plan[0].tool_required == "research_llm"
    # research_llm SI ve el objetivo entero (razona, no busca en Wikipedia)
    assert plan[0].args.get("question") == GOAL_CREACION


def test_veto_con_acentos():
    # "diseña" normaliza a "disena"; el veto aplica igual con tildes/enie
    assert classify_task("diseña una pagina con informacion de gatos") != "research_topic"


def test_informacion_sola_no_clasifica_research():
    assert classify_task("necesito informacion de los planetas para un juego") is None


def test_investigar_sigue_siendo_research():
    # el veto no rompe la investigacion legitima (verbo fuerte)
    assert classify_task("investiga Python async") == "research_topic"


def test_args_llevan_el_tema_no_el_goal_entero():
    plan = plan_task("investiga qué es el teorema de Bayes", task_id="t")
    search = next(s for s in plan if s.tool_required == "search_wikipedia")
    assert search.args["query"] == "el teorema de Bayes"


def test_build_tool_kwargs_prefiere_args_del_planner():
    st = SubTask(id="x", description="Search Wikipedia for the topic: goal entero",
                 tool_required="search_wikipedia", args={"query": "el tema"})
    assert build_tool_kwargs(st) == {"query": "el tema"}


def test_build_tool_kwargs_sin_args_cae_a_descripcion():
    st = SubTask(id="x", description="Search Wikipedia for the topic: bayes",
                 tool_required="search_wikipedia")
    assert build_tool_kwargs(st) == {"query": "bayes"}


# ── REGRESION 2026-08-01 (revision adversarial): el veto matcheaba por
# SUBSTRING. "crea" dentro de "creatividad" y "genera" dentro de "generacion"
# mataban research_topic legitimo y devolvian None: en /flujo esos goals
# volvian al camino sin ejecucion. Ahora el match es por palabra completa.

def test_creatividad_no_dispara_el_veto():
    # 'crea' esta DENTRO de 'creatividad': no es un pedido de construccion
    assert classify_task("que es la creatividad") == "research_topic"


def test_generacion_no_dispara_el_veto():
    # 'genera' esta DENTRO de 'generacion'
    assert classify_task("investiga la generacion del 27") == "research_topic"


def test_otros_substrings_inocentes_no_vetan():
    # 'crea' en 'creacion'/'creador', 'haz' en 'hazana', 'disena' en 'disenador'
    assert classify_task("investiga la creacion del universo") == "research_topic"
    assert classify_task("que es un creador de contenido") == "research_topic"
    assert classify_task("investiga la generatriz de un cono") == "research_topic"


def test_verdaderos_positivos_siguen_vetados():
    # el veto no se aflojo: los pedidos de construccion reales siguen fuera
    for goal in ("crear un juego HTML sobre el sistema solar",
                 "construye una pagina web con tres secciones",
                 "hazme una calculadora en HTML",
                 "genera un informe en markdown",
                 "escribeme un programa que ordene una lista",
                 "build a snake game in HTML"):
        assert classify_task(goal) not in ("research_topic", "explain_concept"), goal


# ── REGRESION 2026-08-01: run_code/analyze_file mandaban la DESCRIPCION del
# paso como argumento ('code': 'Validate Python syntax before running: ...').
# El sandbox devolvia success=True ejecutando prosa.

def test_run_code_extrae_el_codigo_real():
    plan = plan_task("ejecuta print(2+2) y muestrame el resultado", task_id="t")
    val = next(s for s in plan if s.tool_required == "validate_python")
    exe = next(s for s in plan if s.tool_required == "execute_python")
    assert val.args == {"code": "print(2+2)"}
    assert build_tool_kwargs(val, {}) == {"code": "print(2+2)"}
    assert build_tool_kwargs(exe, {}) == {"code": "print(2+2)"}


def test_run_code_bloque_cercado():
    plan = plan_task("ejecuta esto:\n```python\nx = 1\nprint(x)\n```", task_id="t")
    exe = next(s for s in plan if s.tool_required == "execute_python")
    assert build_tool_kwargs(exe, {}) == {"code": "x = 1\nprint(x)"}


def test_sin_codigo_extraible_no_hay_kwargs():
    """Nada que ejecutar -> {} (el ejecutor marca 'sin ejecutar'); JAMAS la
    descripcion del paso como 'code'."""
    plan = plan_task("ejecuta el programa que calcula la nomina", task_id="t")
    exe = next(s for s in plan if s.tool_required == "execute_python")
    assert exe.args == {}
    kwargs = build_tool_kwargs(exe, {})
    assert kwargs == {}
    assert "Execute the code in sandbox" not in str(kwargs)


def test_dependencia_con_prosa_no_se_ejecuta_como_codigo():
    """El output de una etapa viene decorado ('Validate...: goal\\n[resultado
    ...]'): no compila, asi que no puede colarse como 'code'."""
    st = SubTask(id="t_execute", description="Execute the code in sandbox: haz algo",
                 tool_required="execute_python", dependencies=["t_validate"])
    sucio = {"t_validate": {"output": "Validate Python syntax before running: haz algo\n"
                                      "[resultado validate_python]\n{'valid': False}"}}
    assert build_tool_kwargs(st, sucio) == {}
    limpio = {"t_validate": {"output": "print('ok')"}}
    assert build_tool_kwargs(st, limpio) == {"code": "print('ok')"}


def test_supervisor_no_ejecuta_ni_reintenta_sin_argumento():
    """El otro consumidor de build_tool_kwargs (_Executor) tampoco puede
    ejecutar sin argumento: corta con motivo legible en vez de reintentar 3
    veces el mismo TypeError."""
    from cognia.agents.supervisor import _Executor

    class _Q:
        def __init__(self):
            self.updates = []

        def update_subtask(self, sid, status, result=None):
            self.updates.append((sid, status, result))

    class _Reg:
        def execute(self, name, **kw):          # pragma: no cover - no debe llamarse
            raise AssertionError(f"tool ejecutada sin argumento real: {name} {kw}")

    q = _Q()
    ex = _Executor(None, q, _Reg(), None, None)
    st = SubTask(id="s", description="Execute the code in sandbox: haz algo",
                 tool_required="execute_python")
    assert ex._run_subtask(st) is False
    assert q.updates == [("s", "failed", "SIN_ARGUMENTO:code")]


def test_analyze_file_usa_la_ruta_real_o_ninguna():
    plan = plan_task("analiza el archivo cognia/agents/flow.py", task_id="t")
    exp = next(s for s in plan if s.tool_required == "file_explorer")
    assert build_tool_kwargs(exp, {}) == {"path": "cognia/agents/flow.py"}
    # sin ruta en el pedido NO se explora "." (devolvia el repo entero con exito)
    sin_ruta = SubTask(id="x", description="Explore file structure: revisa mi codigo",
                       tool_required="file_explorer")
    assert build_tool_kwargs(sin_ruta, {}) == {}
