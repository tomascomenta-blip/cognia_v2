# -*- coding: utf-8 -*-
"""Regresión: el paso ReAct del agente acota max_tokens y penaliza repetición.

Bug cazado 2026-07-10 (repro de búsqueda): el paso ReAct usaba el default de
768 tokens; a temp=0 el 3B DEGENERA (cola repetida hasta el cap) -> un infer de
768 tok / ~70s, y varios pasos así colgaban el loop ~30 min en tareas de
búsqueda. Fix: max_tokens=256 + repeat_penalty=1.3 en el infer del paso ReAct
(y en el _reinfer_fix de reparación de formato). orchestrator.infer/_local_infer
extendidos para pasar repeat_penalty al backend.
"""
import inspect


def test_react_step_acota_tokens_y_penaliza_repeticion():
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    # el infer del paso ReAct (con stop de ACCION) debe acotar el presupuesto
    assert "max_tokens=256" in src, "el paso ReAct no acota max_tokens"
    assert "repeat_penalty=1.3" in src, "el paso ReAct no penaliza la repetición"
    # ambos deben aparecer >=2 veces (paso ReAct + _reinfer_fix)
    assert src.count("repeat_penalty=1.3") >= 2, "el _reinfer_fix no penaliza repetición"


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
