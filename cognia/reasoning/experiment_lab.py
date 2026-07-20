"""
cognia/reasoning/experiment_lab.py
==================================
Laboratorio de experimentacion (pieza 5 de la mision creativa). Toma una
afirmacion/hipotesis y la pone a prueba EMPIRICAMENTE: pide al LLM vivo un
experimento Python autocontenido, lo corre en el sandbox seguro (regla 9:
scan estatico de imports + sandbox con timeout) y lee el veredicto del stdout.

NUNCA se ejecuta codigo fuera de run_in_sandbox. Si el sandbox rechaza por
imports bloqueados o sintaxis, se reporta el fallo tal cual; no se finge exito.
"""

from typing import Optional

from .creative_llm import creative_generate


def _extract_code(raw: str) -> str:
    """Extrae el bloque de codigo de una respuesta del LLM.

    Soporta fences ```python ... ``` y ``` ... ```. Si no hay fences, intenta
    tomar el texto desde la primera linea que parezca codigo Python real.
    Devuelve "" si no hay nada util. Reimplementado local (no se importa
    program_creator.generator para no acoplar a su backend Ollama).
    """
    if not raw:
        return ""

    lines = raw.splitlines()
    code_lines, in_code, saw_fence = [], False, False
    for line in lines:
        s = line.strip()
        if not in_code and (s.startswith("```python") or s == "```"):
            in_code, saw_fence = True, True
            continue
        if in_code and s == "```":
            in_code = False
            break  # nos quedamos con el primer bloque cerrado
        if in_code:
            code_lines.append(line)

    if saw_fence:
        return "\n".join(code_lines).strip()

    # Sin fences: tomar desde la primera linea que parezca codigo.
    starters = ("import ", "from ", "def ", "class ", "print(", "for ",
                "while ", "if ", "with ", "try", "#!", "x =", "n =")
    start = -1
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(starters) or "print(" in s:
            start = i
            break
    if start < 0:
        return ""
    return "\n".join(lines[start:]).strip()


def _parse_verdict(output: str) -> str:
    """Busca una linea 'VERDICT: PASS/FAIL' (o 'VEREDICTO:') en el stdout.

    Case-insensitive. Devuelve "PASS", "FAIL" o "inconcluso" si no aparece.
    Toma la ultima coincidencia: el experimento debe TERMINAR con el veredicto.
    """
    if not output:
        return "inconcluso"
    verdict = "inconcluso"
    for line in output.splitlines():
        s = line.strip().lower()
        if s.startswith("verdict:") or s.startswith("veredicto:"):
            rest = s.split(":", 1)[1].strip()
            if rest.startswith("pass") or rest.startswith("aprob"):
                verdict = "PASS"
            elif rest.startswith("fail") or rest.startswith("fall") or rest.startswith("rechaz"):
                verdict = "FAIL"
    return verdict


def design_experiment(orchestrator, claim: str) -> Optional[str]:
    """Pide al LLM un experimento Python autocontenido que ponga a prueba `claim`.

    Devuelve el codigo extraido o None si el modelo no produjo nada util.
    Temperature 0.4: queremos codigo correcto, no divergencia creativa.
    """
    prompt = (
        "Disena un experimento en Python que ponga a prueba EMPIRICAMENTE esta "
        "afirmacion:\n"
        f"  \"{claim.strip()}\"\n\n"
        "Requisitos estrictos:\n"
        "- Solo libreria estandar (stdlib). NADA de pip ni dependencias externas.\n"
        "- PROHIBIDO: input(), red (socket/urllib/requests), leer/escribir archivos "
        "fuera de tmp, os.system, subprocess.\n"
        "- Debe correr 100% solo, sin interaccion ni argumentos.\n"
        "- Debe imprimir MEDICIONES concretas (numeros, conteos, tiempos) que "
        "respalden la conclusion.\n"
        "- La ULTIMA linea del programa debe imprimir EXACTAMENTE una de estas dos:\n"
        "    VERDICT: PASS\n"
        "    VERDICT: FAIL\n"
        "  segun lo que muestren los datos medidos (PASS si la afirmacion se sostiene).\n"
        "- Responde SOLO con el codigo, dentro de un bloque ```python.\n"
    )
    raw = creative_generate(orchestrator, prompt, temperature=0.4, max_tokens=900)
    if not raw:
        return None
    code = _extract_code(raw)
    return code or None


def run_experiment(orchestrator, claim: str) -> dict:
    """Pipeline completo: disena -> ejecuta en sandbox -> lee veredicto.

    No se ejecuta NUNCA codigo fuera de run_in_sandbox. Honestidad: si el
    sandbox rechaza (imports bloqueados / sintaxis), se reporta en
    error/blocked y success queda False; nunca se finge exito.
    """
    if orchestrator is None or not (claim or "").strip():
        return {"executed": False, "reason": "sin backend o afirmacion vacia"}

    code = design_experiment(orchestrator, claim)
    if not code:
        return {"executed": False,
                "reason": "el modelo no produjo codigo ejecutable",
                "code": ""}

    # Import tardio: solo aqui necesitamos el motor de ejecucion segura.
    from cognia.program_creator.sandbox_runner import run_in_sandbox
    res = run_in_sandbox(code)

    return {
        "claim":     claim.strip(),
        "code":      code,
        "executed":  True,
        "success":   res.success,
        "verdict":   _parse_verdict(res.execution_output),
        "output":    res.execution_output[:1500],
        "error":     res.execution_errors[:600],
        "blocked":   res.blocked_imports,
        "timed_out": res.timed_out,
    }
