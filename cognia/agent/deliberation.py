"""
cognia/agent/deliberation.py
============================
Mesa redonda ENTRE modelos con oráculo duro (FLEET-30, mandato 2026-07-11).

"Los modelos se retroalimentan entre ellos": el candidato del modelo A se
ejecuta contra los tests visibles; el modelo B recibe el código de A MÁS el
resultado REAL de la ejecución (qué assert falló, con qué error) y produce
una revisión; se rankea por el mismo oráculo; se repite alternando modelos.
El loop corta apenas un candidato pasa todos los tests visibles (early-exit
sin pérdida) y NUNCA devuelve algo peor que lo que entró (keep-best).

La retroalimentación es EJECUCIÓN, no opinión: sigue vigente la prohibición
de autocrítica-LLM como juez (candidates.py, P8/CYCLE 12). Un modelo nunca
juzga "qué candidato se ve mejor"; solo REPARA con el traceback en mano, y
el veredicto lo da el sandbox. Sin tests visibles NO hay deliberación (se
declara "sin_oraculo" y se devuelve el candidato inicial intacto).

RAM (i3 ~12GB): los participantes generan SECUENCIALMENTE; el caller decide
el lifecycle de cada backend (p.ej. 7B lazy-usar-cerrar). Este módulo no
arranca ni para servers.

Concreto: funciones planas; cada participante entra como
``(nombre, gen_fn)`` con ``gen_fn(prompt, temperature, seed) -> str``,
igual que candidates.py.
"""
from __future__ import annotations

MAX_ROUNDS_DEFAULT = 2


def execution_feedback(code, asserts, entry_point):
    """Ejecuta `code` contra CADA assert por separado y devuelve la lista
    [{assert, ok, error_type, detalle}]. Es la 'crítica' de la mesa redonda:
    hechos del sandbox, no opinión de un LLM."""
    from cognia_v3.eval.benchmark_code import run_task_tests
    out = []
    for a in asserts:
        ok, etype, detail = run_task_tests(code, a + "\n", entry_point)
        out.append({"assert": a, "ok": bool(ok),
                    "error_type": etype, "detalle": detail})
    return out


def feedback_score(feedback):
    """(n_passed, n_total) de un feedback de execution_feedback()."""
    return sum(1 for f in feedback if f["ok"]), len(feedback)


def build_repair_prompt(task_prompt, entry_point, code, feedback):
    """Prompt de reparación para el siguiente participante: la tarea, el
    candidato actual (de OTRO modelo) y el resultado real de cada test.
    Texto plano: el caller lo envuelve en su chat-template."""
    lines = []
    for f in feedback:
        if f["ok"]:
            lines.append(f"PASA  : {f['assert']}")
        else:
            lines.append(f"FALLA : {f['assert']}  -> {f['error_type']}: "
                         f"{f['detalle']}")
    reporte = "\n".join(lines) if lines else "(sin tests visibles)"
    return (
        "Tarea original:\n" + task_prompt.strip() + "\n\n"
        "Candidato actual (INCORRECTO o incompleto):\n"
        "```python\n" + code.strip() + "\n```\n\n"
        "Resultado REAL de ejecutar sus tests:\n" + reporte + "\n\n"
        f"Corrige la funcion `{entry_point}` para que TODOS los tests pasen. "
        "No expliques nada: responde SOLO con un bloque ```python ...``` con "
        "la funcion completa corregida."
    )


def deliberate(task_prompt, entry_point, participants, extract_code_fn,
               asserts, initial_code="", rounds=MAX_ROUNDS_DEFAULT,
               max_tokens_hint=768):
    """Mesa redonda: refina `initial_code` alternando participantes, con el
    feedback de ejecución como única crítica. Devuelve dict:

      {code, score, total, mejorado, rounds_run, motivo, historial}

    - keep-best: el code devuelto nunca puntúa peor que el inicial.
    - early-exit: corta apenas un candidato pasa todos los tests.
    - sin oráculo (asserts vacío): no delibera; motivo="sin_oraculo".
    - participants: [(nombre, gen_fn)]; se recorren en orden, `rounds` veces.
    """
    historial = []
    if not asserts:
        return {"code": initial_code, "score": 0, "total": 0,
                "mejorado": False, "rounds_run": 0,
                "motivo": "sin_oraculo", "historial": historial}
    if not participants:
        return {"code": initial_code, "score": 0, "total": 0,
                "mejorado": False, "rounds_run": 0,
                "motivo": "sin_participantes", "historial": historial}

    best_code = initial_code or ""
    best_fb = execution_feedback(best_code, asserts, entry_point)
    best_score, total = feedback_score(best_fb)
    score_inicial = best_score
    if total and best_score >= total:
        return {"code": best_code, "score": best_score, "total": total,
                "mejorado": False, "rounds_run": 0,
                "motivo": "inicial_perfecto", "historial": historial}

    rounds_run = 0
    motivo = "rondas_agotadas"
    for r in range(max(1, rounds)):
        for nombre, gen_fn in participants:
            rounds_run += 1
            prompt = build_repair_prompt(task_prompt, entry_point,
                                         best_code, best_fb)
            try:
                raw = gen_fn(prompt, temperature=0.0, seed=None) or ""
            except Exception as exc:
                historial.append({"ronda": r, "participante": nombre,
                                  "error": str(exc)})
                continue
            code = extract_code_fn(raw)
            if not code.strip() or f"def {entry_point}" not in code:
                historial.append({"ronda": r, "participante": nombre,
                                  "score": None, "nota": "sin_funcion"})
                continue
            fb = execution_feedback(code, asserts, entry_point)
            score, _ = feedback_score(fb)
            historial.append({"ronda": r, "participante": nombre,
                              "score": score, "total": total})
            if score > best_score:          # keep-best: solo mejora estricta
                best_code, best_fb, best_score = code, fb, score
            if best_score >= total:
                motivo = "tests_perfectos"
                return {"code": best_code, "score": best_score,
                        "total": total,
                        "mejorado": best_score > score_inicial,
                        "rounds_run": rounds_run, "motivo": motivo,
                        "historial": historial}

    return {"code": best_code, "score": best_score, "total": total,
            "mejorado": best_score > score_inicial,
            "rounds_run": rounds_run, "motivo": motivo,
            "historial": historial}
