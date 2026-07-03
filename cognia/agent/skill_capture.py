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


def hard_oracle_evidence(trace: list) -> str:
    """Evidencia de oraculo duro en la traza, o ''. v1: una corrida de la
    tool ``tests`` exitosa con '<n> passed' y sin 'failed' — el veredicto
    es del pytest real, no del modelo."""
    for step in trace:
        if step.get("action") != "tests" or not step.get("ok"):
            continue
        head = step.get("result_head", "")
        m = _PASSED_RX.search(head)
        if m and "failed" not in head:
            return f"tests verdes ({m.group(1)} passed): {step.get('args', '')[:60]}"
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
