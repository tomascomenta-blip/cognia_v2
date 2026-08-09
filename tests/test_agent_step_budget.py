# -*- coding: utf-8 -*-
"""Regresión: el paso ReAct del agente acota max_tokens y NO usa repeat_penalty.

Bug cazado 2026-07-10 (repro de búsqueda): el paso ReAct usaba el default de
768 tokens; a temp=0 el 3B DEGENERA y varios pasos así colgaban el loop ~30 min.
Fixes que SÍ funcionan: max_tokens=256 (cota por paso) + _FAIL_STREAK (corte por
no-progreso = bound REAL del cuelgue).

CORRECCIÓN 3.8.5: en 3.8.4 agregué también repeat_penalty=1.3, pero un e2e del
camino feliz mostró que penalizaba los tokens de los nombres de tool (que se
repiten desde TOOLS_DOC en el prompt) y empujaba al 3B a BASURA -> tareas normales
0/5 con rp, 5/5 sin rp. repeat_penalty REVERTIDO del agente. El param sigue en
orchestrator.infer (extensión legítima del API), solo que el agente no lo usa.
"""
import inspect


def test_react_step_acota_tokens_sin_repeat_penalty():
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    # el infer del paso ReAct debe acotar el presupuesto por paso -- pero la cota
    # sale del nivel /esfuerzo activo, NO de un literal (ver el test de abajo).
    assert "max_tokens=min(_active_effort()" in src, \
        "el paso ReAct no acota max_tokens"
    # REGRESIÓN 3.8.4 revertida: repeat_penalty=1.3 empujaba al 3B a basura (e2e
    # 0/5 tareas normales). Guard: no re-introducirlo en el loop del agente.
    assert "repeat_penalty=1.3" not in src, \
        "repeat_penalty=1.3 en el agente REGRESIONA (empuja a basura); no re-introducir"


def test_react_step_cubre_el_pensamiento_del_razonador():
    """Regresión 2026-08-02: el 256 fijo mataba al agente con un razonador.

    Qwythos-9B inyecta `<think>` en CADA turno desde su plantilla de chat, así
    que la ACCION (corta) se emite DESPUÉS del pensamiento. Medido contra el
    server real con un prompt trivial: max_tokens=150 -> finish_reason=length,
    content de 0 CHARS y 713 de reasoning_content. Con 256 por paso el modelo
    gastaba el presupuesto pensando, el loop leía prosa vacía y cerraba con
    "2 pasos sin ACCION valida" SIN ejecutar ninguna tool -- se veía como que
    el modelo era incapaz. 8º caso de presupuesto-tokens-razonamiento.

    El guard es doble: la cota existe (no volver al default de 768 que colgaba
    al 3B) pero es suficiente para el pensamiento en TODOS los niveles.
    """
    from cognia.effort_levels import EFFORT_LEVELS

    for nombre, params in EFFORT_LEVELS.items():
        presupuesto = min(params["max_tokens"], 8000)
        assert presupuesto >= 2000, (
            f"nivel '{nombre}': {presupuesto} tokens/paso no cubren el "
            f"pensamiento de un razonador (medido: 713 chars de think en la "
            f"tarea MAS trivial)")
        assert presupuesto <= 8000, (
            f"nivel '{nombre}': sin cota por paso, un paso degenerado cuelga "
            f"el loop (bug 2026-07-10)")


def test_sin_pensamiento_limpia_el_bloque_think():
    """Regresión 2026-08-02: gate e2e 0/5, las 5 tareas devolviendo '<think>'.

    El loop del agente era el ÚNICO consumidor de LLM del repo que no
    strippeaba el bloque de pensamiento (razonador.py, mockup.py,
    juez_ejecutable.py, generator.py, pulidor.py, critico.py y
    arbitro_visual.py sí lo hacen). Con un razonador, el <think> entero
    aterrizaba en raw_response y el parser no encontraba ninguna ACCION.
    """
    from cognia.cli import _sin_pensamiento

    # par completo -> solo la respuesta
    assert _sin_pensamiento(
        "<think>me lo pienso</think>\nACCION: leer_archivo x.txt"
    ) == "ACCION: leer_archivo x.txt"
    # cierre SIN apertura (la plantilla ya inyectó el <think>)
    assert _sin_pensamiento(
        "divago un rato</think>\nACCION: listar_dir ."
    ) == "ACCION: listar_dir ."
    # apertura sin cierre = se quedó sin presupuesto pensando -> vacío, para
    # que el loop lo cuente como fallo en vez de parsear medio razonamiento
    assert _sin_pensamiento("<think>pienso y me quedo sin tokens") == ""
    # texto normal intacto
    assert _sin_pensamiento("ACCION: responder hola") == "ACCION: responder hola"
    assert _sin_pensamiento("") == ""
    assert _sin_pensamiento(None) == ""


def test_react_step_suprime_y_limpia_el_pensamiento():
    """El paso ReAct debe cerrar el <think> en la PLANTILLA y limpiar la salida."""
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "_sin_pensamiento(" in src, \
        "el paso ReAct no limpia el bloque <think> (gate e2e 0/5)"
    assert "nothink=True" in src, \
        "el paso ReAct no suprime el pensamiento en origen (115-174s por paso)"


def test_nothink_va_en_el_turno_del_assistant():
    """Regresión 2026-08-02: el bloque tiene que ir DESPUÉS de
    `<|im_start|>assistant`, no al final del mensaje de usuario.

    Primer intento del fix: concatenar el sufijo al prompt. No hizo NADA — el
    orquestador envuelve el prompt con _apply_qwen_template(), así que el
    sufijo quedaba dentro del turno `user`, antes del `<|im_end|>`, y el modelo
    abría su propio <think> igual. El gate pasó de fallar con '<think>' a
    fallar con '[DEGRADADO]': síntoma distinto, misma causa sin tocar.
    """
    from node.inference_pipeline import _apply_qwen_template

    normal = _apply_qwen_template("hola", "sys")
    assert normal.endswith("<|im_start|>assistant\n")
    assert "<think>" not in normal, "nothink=False no debe inyectar nada"

    sin_pensar = _apply_qwen_template("hola", "sys", nothink=True)
    assert sin_pensar.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n"), \
        "el bloque debe cerrar el pensamiento en el turno del ASSISTANT"
    # y NO dentro del mensaje de usuario (el bug del primer intento)
    assert "<think>" not in sin_pensar.split("<|im_start|>assistant")[0]


def test_paso_vacio_no_se_confunde_con_falta_de_backend():
    """Un paso que se agotó pensando NO es 'no hay modelo instalado'.

    _sin_pensamiento() devuelve "" cuando el <think> quedó sin cerrar; si eso
    cae en la rama `if not raw_response` el loop aborta entero diciéndole al
    usuario que instale un modelo — diagnóstico FALSO, había backend.
    """
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "_llm_crudo" in src, "no se conserva la respuesta cruda"
    assert 'if not raw_response and (_llm_crudo or "").strip():' in src, \
        "vacío-tras-limpiar no se distingue de 'sin backend'"


def test_corte_por_no_progreso():
    # racha de fallos consecutivos -> cierre honesto (cota dura al cuelgue).
    # El stuck-detector viejo contaba (action,args) idénticos; la degeneración
    # de búsqueda genera basura DISTINTA cada paso, así que no disparaba.
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "_FAIL_STREAK" in src, "no hay corte por racha de fallos"
    assert "acciones seguidas fallaron" in src or "sin progreso" in src.lower(), \
        "el corte no cierra honestamente"
    # la lógica: si ninguna de las últimas N acciones fue ok -> break
    assert "not any(a[\"ok\"] for a in _recent)" in src or \
           "not any(a['ok'] for a in _recent)" in src, "la condición de corte no es 'todas fallaron'"


def test_orchestrator_infer_pasa_repeat_penalty():
    from shattering.orchestrator import ShatteringOrchestrator
    for fn in (ShatteringOrchestrator.infer, ShatteringOrchestrator._local_infer):
        assert "repeat_penalty" in inspect.signature(fn).parameters, \
            f"{fn.__name__} no expone repeat_penalty"
    # _local_infer debe reenviar repeat_penalty a generate()
    src = inspect.getsource(ShatteringOrchestrator._local_infer)
    assert "repeat_penalty=repeat_penalty" in src, \
        "_local_infer no reenvía repeat_penalty al backend"


def test_default_none_no_cambia_comportamiento():
    # repeat_penalty default None -> el backend usa su default (no rompe callers viejos)
    from shattering.orchestrator import ShatteringOrchestrator
    assert inspect.signature(ShatteringOrchestrator.infer).parameters[
        "repeat_penalty"].default is None


def test_slash_plan_crear_acota_max_tokens():
    # /plan crear decompone en 3-5 pasos (salida corta); sin cota el 3B podía
    # degenerar hasta el default del orquestador (~70s de basura). Cuelgue latente
    # de la misma clase que la búsqueda, acotado con max_tokens=160 (sin repeat_penalty).
    from cognia import cli
    src = inspect.getsource(cli._slash_plan_crear)
    assert "max_tokens=160" in src, "/plan crear no acota max_tokens (cuelgue latente)"
    assert "repeat_penalty=1.3" not in src, "no usar repeat_penalty (empuja al 3B a basura)"


def test_slash_resumir_acota_max_tokens():
    # /resumir promete '2-3 oraciones' (salida corta); acotar evita el desperdicio
    # si el 3B degenera. Mismo patrón de bound que /plan crear (single-shot).
    from cognia import cli
    full = inspect.getsource(cli)
    assert "_orch_r.infer(_summary_prompt, max_tokens=256)" in full, \
        "/resumir no acota max_tokens (infer del summary sin cota)"
