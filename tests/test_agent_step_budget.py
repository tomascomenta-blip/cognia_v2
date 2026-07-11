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
    # el infer del paso ReAct debe acotar el presupuesto por paso
    assert "max_tokens=256" in src, "el paso ReAct no acota max_tokens"
    # REGRESIÓN 3.8.4 revertida: repeat_penalty=1.3 empujaba al 3B a basura (e2e
    # 0/5 tareas normales). Guard: no re-introducirlo en el loop del agente.
    assert "repeat_penalty=1.3" not in src, \
        "repeat_penalty=1.3 en el agente REGRESIONA (empuja a basura); no re-introducir"


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
