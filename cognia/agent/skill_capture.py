"""
cognia/agent/skill_capture.py
=============================
Trigger de creacion de skills nivel-2 (CP2, 06_AGENTE_PLAN §3.3-3.4).

Tras una tarea del agente: si hubo >= MIN_OK_CALLS tool-calls exitosos Y la
traza cerro con un ORACULO DURO (tests verdes de verdad — no 'salio bien'
segun el modelo), el procedimiento que funciono se persiste como skill
nivel-2 (markdown, instrucciones; blast radius cero). El umbral 4 esta
pre-registrado; se ajusta con datos de uso, no por intuicion.

Diferenciador vs Hermes (§3.4): Hermes persiste porque la tarea 'salio
bien'; aca NADA se persiste sin corrida verificada — el gate de evidencia
vive en skills.persist_skill y esta funcion solo lo alimenta con la
evidencia REAL encontrada en la traza.
"""
from __future__ import annotations

import re

MIN_OK_CALLS = 4

# acciones que no aportan a un procedimiento reutilizable
_NON_PROCEDURAL = {"responder", "fecha", "notas"}

_PASSED_RX = re.compile(r"\b(\d+)\s+passed\b")
_BON_VISIBLE_RX = re.compile(r"tests visibles (\d+)/(\d+)")
_CONTRACTS_OK_TXT = "todos los contratos pasan"


# ── Registro pluggable de reconocedores de oraculo duro ─────────────────
# Cada reconocedor es (action, result_head) -> bool: reconoce el formato
# REAL de una tool/verificador concreto y dice si esa corrida es evidencia
# de oraculo duro (ejecucion real — no "el modelo dice que salio bien").
# hard_oracle_evidence() los prueba en orden de registro sobre cada paso
# 'ok' de la traza; el primero que reconoce gana. Nuevas tools/verificadores
# extienden el gate con register_oracle_recognizer() sin tocar esta funcion.
_ORACLE_RECOGNIZERS: list = []


def register_oracle_recognizer(fn) -> None:
    """Agrega un reconocedor (action: str, result_head: str) -> bool al
    registro global de oraculos duros."""
    _ORACLE_RECOGNIZERS.append(fn)


def _recognize_pytest_verde(action: str, result_head: str) -> bool:
    """v1 (original, regresion intacta): tool ``tests`` con '<n> passed' y
    sin 'failed' — el veredicto es del pytest real, no del modelo."""
    if action != "tests":
        return False
    return bool(_PASSED_RX.search(result_head)) and "failed" not in result_head


def _recognize_bon_tests_visibles(action: str, result_head: str) -> bool:
    """generar_codigo (BoN test-first, candidates.py vía tools.py:
    _generar_codigo). El RESULTADO real trae 'tests visibles X/Y': X asserts
    EJECUTADOS de verdad en sandbox (candidates.score_candidate) sobre Y
    generados test-first. Y==0 es rank_mode 'greedy_fallback' (no hubo
    asserts que correr — no es oraculo); solo cuenta si Y>0 y TODOS pasaron
    (X==Y), mismo criterio 'verde total' que el reconocedor de pytest."""
    if "generar_codigo" not in action:
        return False
    m = _BON_VISIBLE_RX.search(result_head)
    if not m:
        return False
    passed, total = int(m.group(1)), int(m.group(2))
    return total > 0 and passed == total


def _recognize_contratos_pasan(action: str, result_head: str) -> bool:
    """contracts.py:attribute_failure — la cascada plan->design->code->test
    devuelve literalmente 'todos los contratos pasan' cuando los 3
    contratos (oraculos ejecutables/deterministas: cobertura de entidades,
    firmas, ejecucion real via run_task_tests) pasan. Forward-looking: hoy
    ninguna tool de tools.py expone esta cascada al loop del agente (solo
    la usan tests/bench_arbitro); el reconocedor queda listo para cuando se
    wiree una tool cuyo nombre contenga 'contrat' (p.ej. 'contratos')."""
    if "contrat" not in action:
        return False
    return _CONTRACTS_OK_TXT in result_head


register_oracle_recognizer(_recognize_pytest_verde)
register_oracle_recognizer(_recognize_bon_tests_visibles)
register_oracle_recognizer(_recognize_contratos_pasan)


def hard_oracle_evidence(trace: list) -> str:
    """Evidencia de oraculo duro en la traza, o ''. Prueba cada paso 'ok'
    contra el registro de reconocedores (orden de registro); el primero que
    reconoce el formato gana."""
    for step in trace:
        if not step.get("ok"):
            continue
        action = step.get("action", "")
        head = step.get("result_head", "")
        for rec in _ORACLE_RECOGNIZERS:
            if rec(action, head):
                return (f"oraculo duro via '{action}': {head[:80]} "
                        f"(args: {step.get('args', '')[:60]})")
    return ""


def slug_from_task(task: str) -> str:
    """Nombre de skill (kebab, <= 40 chars) a partir de la tarea."""
    words = re.findall(r"[a-záéíóúñ0-9]{3,}", (task or "").lower())
    stop = {"que", "una", "los", "las", "del", "para", "con", "the", "and",
            "for", "una", "este", "esta", "crea", "crear", "hace", "hacer"}
    kept = [w for w in words if w not in stop][:5]
    slug = "-".join(kept)[:40].strip("-")
    return slug or "procedimiento-verificado"


def build_skill_body(task: str, trace: list) -> str:
    """Cuerpo del skill: el procedimiento REAL que cerro con oraculo (solo
    pasos exitosos, args truncados). Formato simple estilo SKILL.md."""
    lines = ["## Cuando usar",
             f"Tareas como: {task.strip()[:200]}", "",
             "## Procedimiento verificado"]
    n = 0
    for step in trace:
        if not step.get("ok") or step.get("action") in _NON_PROCEDURAL:
            continue
        n += 1
        args = (step.get("args") or "").replace("\n", " ")[:120]
        lines.append(f"{n}. ACCION: {step['action']} {args}".rstrip())
    lines += ["", "## Verificacion",
              "Cerrar SIEMPRE corriendo los tests (tool `tests`) y confirmar "
              "'N passed'."]
    return "\n".join(lines)


def maybe_capture_skill(task: str, trace: list) -> dict:
    """Aplica el trigger §3.3. Devuelve {captured, name?/reason}.
    Nunca levanta (best-effort al final del loop del agente)."""
    try:
        ok_calls = [s for s in trace
                    if s.get("ok") and s.get("action") not in _NON_PROCEDURAL]
        if len(ok_calls) < MIN_OK_CALLS:
            return {"captured": False,
                    "reason": f"solo {len(ok_calls)} tool-calls exitosos (< {MIN_OK_CALLS})"}
        evidence = hard_oracle_evidence(trace)
        if not evidence:
            return {"captured": False, "reason": "sin oraculo duro en la traza"}
        from cognia.agent.skills import persist_skill
        name = slug_from_task(task)
        res = persist_skill(name, task.strip()[:120],
                            build_skill_body(task, trace), evidence)
        if res.get("ok"):
            return {"captured": True, "name": name, "path": res["path"]}
        return {"captured": False, "reason": res.get("reason", "?")}
    except Exception as exc:
        return {"captured": False, "reason": f"error interno: {exc}"}
