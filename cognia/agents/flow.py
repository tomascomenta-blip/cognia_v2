"""
cognia/agents/flow.py — FASE 5
==============================
Orquestador de flujo estructurado (objetivo O1). run_flow descompone un objetivo en etapas
y decide DINAMICAMENTE cuales correr segun la complejidad (ComplexityScorer, 0 LLM) y el
nivel de /esfuerzo. Reusa piezas existentes (planner, synthesizer, verifier, response_gate);
NO reescribe. Sin clases: un dict STAGES + funciones planas _stage_*(ctx) -> ctx.

Presupuesto de inferencia (hardware i3 ~8 tok/s): 1 LLM (el informe via synthesize) en goals
simples; hasta 2 (informe + 1 correccion gated) en goals complejos. Si no hay backend, el
informe degrada a un resumen determinista (0 LLM). NUNCA usa el ReAct loop (5-20 inferencias).

Orden real: analisis -> [plan] -> ejecucion -> informe -> [verificacion] -> [correccion].
(informe va antes de verificacion/correccion: no se puede verificar un informe inexistente.)
"""

from __future__ import annotations


def _stage_analisis(ctx: dict) -> dict:
    """Clasifica complejidad (0 LLM) y emite la lista de etapas a correr."""
    from cognia.reasoning.complexity_scorer import ComplexityScorer
    res = ComplexityScorer().score(ctx["goal"])
    ctx["complexity"] = res.score
    ctx["budget"] = res.budget
    if res.budget == "fast" or res.score <= 2:
        route = ["ejecucion", "informe"]
    elif res.score >= 4 or res.budget == "deep":
        route = ["plan", "ejecucion", "informe", "verificacion", "correccion"]
    else:
        route = ["plan", "ejecucion", "informe", "verificacion"]
    # Override por esfuerzo explicito (alto/maximo): forzar verificacion + correccion
    # aunque el score sea bajo (mitiga clasificacion errada; el usuario pidio profundidad).
    if int(ctx["effort"].get("verificaciones", 0)) >= 2:
        route = ["plan", "ejecucion", "informe", "verificacion", "correccion"]
    ctx["route"] = route
    ctx["print_fn"](f"[detail]analisis: complejidad={res.score} ({res.budget}) -> "
                    f"{' > '.join(['analisis'] + route)}[/detail]")
    return ctx


def _stage_plan(ctx: dict) -> dict:
    """Descompone en subtareas (0 LLM, templates simbolicos), truncado por esfuerzo."""
    from cognia.agents.planner import plan_task
    subtasks = plan_task(ctx["goal"], task_id="flujo")
    cap = max(1, int(ctx["effort"].get("subtareas_max", 5)))
    non_synth = [st for st in subtasks if st.tool_required != "synthesize"][:cap]
    synth = [st for st in subtasks if st.tool_required == "synthesize"]
    ctx["subtasks"] = non_synth + synth
    ctx["print_fn"](f"[detail]plan: {len(ctx['subtasks'])} subtareas[/detail]")
    return ctx


# Pseudo-tools que NO se ejecutan aqui: "step" es el carrier de contexto del
# camino fast, "synthesize" corre en la etapa informe, y "research_llm" queda
# excluido a proposito para respetar el presupuesto de <=2 LLM por flujo (su
# descripcion alimenta al synthesize, que es quien razona).
_TOOLS_SOLO_CONTEXTO = {"step", "synthesize", "research_llm"}


def _ejecutar_tool(registry, tool_name: str, kwargs: dict, timeout_s: int):
    """registry.execute en un hilo con deadline. None = timeout (el hilo del
    tool queda huerfano pero el flujo no se cuelga; los tools del registry son
    read-only o sandboxeados)."""
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(registry.execute, tool_name, **kwargs)
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        return None
    finally:
        ex.shutdown(wait=False)


def _stage_ejecucion(ctx: dict) -> dict:
    """Ejecuta las tools REALES de cada subtarea (0 LLM: research_llm excluido) y
    guarda results[id]['output'] que synthesize consume. Antes esta etapa solo
    copiaba la DESCRIPCION del paso como output — el flujo nunca buscaba ni
    exploraba nada (auditoria 2026-08-01). Inyecta el bloque de memoria HYDRA
    del REPL si esta disponible."""
    from cognia.agents.planner import SubTask
    from cognia.agents.supervisor import build_tool_kwargs
    from cognia.agents.tool_registry import get_tool_registry
    subtasks = ctx.get("subtasks")
    if not subtasks:
        subtasks = [SubTask(id="flujo_0", description=ctx["goal"], tool_required="step")]
        ctx["subtasks"] = subtasks
    mem_block = ""
    try:
        from cognia.cli import _build_memory_block_for
        mem_block = _build_memory_block_for(ctx["ai"], ctx["goal"]) or ""
    except Exception:
        mem_block = ""
    try:
        registry = get_tool_registry()
    except Exception:
        registry = None
    results = {}
    sin_ejecutar = 0
    for st in subtasks:
        if st.tool_required == "synthesize":
            continue
        base = st.description
        if mem_block:
            base = f"{st.description}\n[memoria]\n{mem_block}"
        tool = registry.get(st.tool_required) if registry else None
        if st.tool_required in _TOOLS_SOLO_CONTEXTO or tool is None:
            # paso de contexto puro: la descripcion ES el output (camino viejo)
            results[st.id] = {"output": base}
            if st.tool_required not in _TOOLS_SOLO_CONTEXTO:
                sin_ejecutar += 1   # tool declarada pero no registrada: honestidad
            continue
        kwargs = build_tool_kwargs(st, results)
        if not kwargs:
            # Sin argumento REAL extraible. Ejecutar igual mandaba la
            # DESCRIPCION del paso como 'code' y el sandbox devolvia
            # success=True con basura, que synthesize consumia como resultado
            # (auditoria 2026-08-01). Preferimos un hueco VISIBLE.
            results[st.id] = {"output": "",
                              "error": f"sin argumento para {st.tool_required}"}
            sin_ejecutar += 1
            continue
        timeout_s = getattr(tool, "timeout_seconds", 30) or 30
        tr = _ejecutar_tool(registry, st.tool_required, kwargs, timeout_s)
        if tr is not None and tr.success:
            # resultado ANTES de la memoria: synthesize trunca cada entrada y
            # el bloque [memoria] enterraba el texto real (medido 2026-08-01)
            out = (f"{st.description}\n[resultado {st.tool_required}]\n"
                   f"{str(tr.output)[:2000]}")
            if mem_block:
                out = f"{out}\n[memoria]\n{mem_block}"
            results[st.id] = {"output": out}
        else:
            err = f"timeout {timeout_s}s" if tr is None else (tr.error or "fallo")
            results[st.id] = {"output": "", "error": err}
            sin_ejecutar += 1
    if sin_ejecutar:
        # linea VISIBLE (sin [detail]): que nadie confunda contexto con resultado
        ctx["print_fn"](f"[etapas sin ejecutar: {sin_ejecutar}]")
    ctx["results"] = results
    return ctx


def _stage_informe(ctx: dict) -> dict:
    """Sintetiza la respuesta final (1 LLM via synthesize; determinista si orch=None)."""
    from cognia.agents.planner import SubTask
    from cognia.agents.synthesizer import synthesize
    subtasks = ctx.get("subtasks") or [
        SubTask(id="flujo_0", description=ctx["goal"], tool_required="step")]
    results = ctx.get("results") or {st.id: {"output": st.description} for st in subtasks}
    ctx["report"] = synthesize(ctx["goal"], subtasks, results,
                               orchestrator=ctx.get("orch")) or ""
    return ctx


def _stage_verificacion(ctx: dict) -> dict:
    """Autoevaluacion del informe (0 LLM). Escala ejes por effort['verificaciones']."""
    if int(ctx["effort"].get("verificaciones", 0)) <= 0:
        return ctx
    from cognia.agents.verifier import verify
    from cognia.quality.response_gate import ResponseGate
    text = ctx.get("report", "") or ""
    gate_score = ResponseGate().score(ctx["goal"], text)
    v = verify(text, "text")
    ctx["score"] = round(min(gate_score, v.score or gate_score), 4)
    ctx["verify_passed"] = bool(v.passed and gate_score >= ResponseGate.RETRY_THRESHOLD)
    ctx["print_fn"](f"[detail]verificacion: score={ctx['score']} "
                    f"passed={ctx['verify_passed']}[/detail]")
    return ctx


def _stage_correccion(ctx: dict) -> dict:
    """1 regeneracion gated si el informe puntua bajo y hay reintentos (<=1 LLM)."""
    if int(ctx["effort"].get("reintentos", 0)) <= 0 or ctx.get("orch") is None:
        return ctx
    from cognia.quality.response_gate import ResponseGate
    gate = ResponseGate()
    text = ctx.get("report", "") or ""
    retry, reason = gate.should_retry(ctx["goal"], text)
    if not retry:
        return ctx
    try:
        res = ctx["orch"].infer(gate.build_retry_prompt(ctx["goal"], text, reason))
        if res and getattr(res, "text", ""):
            ctx["report"] = gate.pick_better(ctx["goal"], text, res.text)
            ctx["print_fn"]("[detail]correccion: regenerado, elegido por score[/detail]")
    except Exception:
        pass
    return ctx


STAGES = {
    "analisis":     _stage_analisis,
    "plan":         _stage_plan,
    "ejecucion":    _stage_ejecucion,
    "informe":      _stage_informe,
    "verificacion": _stage_verificacion,
    "correccion":   _stage_correccion,
}


def run_flow(ai, goal: str, effort_params: dict, print_fn=print) -> str:
    """Orquesta el flujo y devuelve el informe final (string). No imprime el informe
    (el caller lo muestra); print_fn es solo para trazas de etapa."""
    if not goal or not goal.strip():
        return "Flujo vacio: falta el objetivo."

    orch = None
    try:
        from shattering.orchestrator import ShatteringOrchestrator as _O
        orch = getattr(ai, "_orchestrator", None) or _O(mode="local")
    except Exception:
        orch = None

    ctx = {
        "goal": goal.strip(), "ai": ai, "orch": orch,
        "effort": effort_params or {}, "print_fn": print_fn,
        "subtasks": None, "results": None, "report": "", "score": None,
    }
    ctx = _stage_analisis(ctx)          # siempre primero: decide la ruta

    # FASE 6: persistir el estado del flujo (nivel "proyectos" de la taxonomia O2) para
    # retomar entre sesiones. Best-effort: solo si la instancia tiene un db real (los fakes
    # de test sin .db no abren pool ni tocan disco); nunca rompe el flujo.
    pm = flow_id = None
    _db = getattr(ai, "db", None)
    if _db:
        try:
            from cognia.memory.project_memory import get_project_memory
            pm = get_project_memory(_db)
            flow_id = pm.start_flow(ctx["goal"], ["analisis"] + ctx["route"])
            pm.mark_stage(flow_id, "analisis")
        except Exception:
            pm = flow_id = None

    for stage in ctx["route"]:
        ctx = STAGES[stage](ctx)
        if pm and flow_id:
            try:
                pm.mark_stage(flow_id, stage)
            except Exception:
                pass

    report = (ctx.get("report") or "").strip() or "(el flujo no produjo informe)"
    meta = f"[flujo: complejidad={ctx.get('complexity')} ({ctx.get('budget')}); " \
           f"etapas={'>'.join(['analisis'] + ctx['route'])}"
    if ctx.get("score") is not None:
        meta += f"; score={ctx['score']}"
    meta += "]"
    if pm and flow_id:
        try:
            pm.finish_flow(flow_id, report, ctx.get("score"), status="done")
        except Exception:
            pass
    return f"{report}\n\n{meta}"
