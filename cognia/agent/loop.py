"""
cognia/agent/loop.py
====================
Dynamic step-budgeting for the agent loop.

The old loop ran a fixed 12 steps for every task -- wasteful for "que hora es"
and too short for "refactoriza este modulo". This lets the agent decide HOW MANY
steps a task deserves, with a hard ceiling so it can never run away.

Concrete, not abstract: two plain functions and a couple of constants.
"""

from __future__ import annotations

import re

# ── Parsing de la respuesta del modelo ─────────────────────────────────
_ACCION_MARK = re.compile(r"ACCI[OÓ]N:", re.IGNORECASE)
_ACCION_LINE = re.compile(r"\s*ACCI[OÓ]N:", re.IGNORECASE)


def first_action_block(raw: str) -> str:
    """Devuelve SOLO el primer bloque de accion de la respuesta del modelo.

    El 3B (y a veces el 7B) emite VARIAS lineas ``ACCION:`` en una sola respuesta.
    El parser DOTALL del loop (``ACCION:\\s*(\\w+)\\s*(.*)``) junta todo lo que
    sigue al primer nombre de herramienta -- incluidas las ACCION posteriores --
    y ejecuta una accion corrupta (p.ej. escribe un archivo cuyo contenido es el
    resto del rambling). Esta funcion recorta desde el primer ``ACCION:`` hasta
    justo antes de la siguiente linea que EMPIEZA con ``ACCION:``.

    Conserva el contenido multi-linea legitimo (el de ``escribir_archivo`` tras
    ``|`` puede tener varias lineas) porque solo corta en lineas que arrancan con
    ``ACCION:``. Si no hay ninguna ``ACCION:`` devuelve el texto sin cambios.
    """
    if not raw:
        return raw
    lines = raw.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if _ACCION_MARK.search(ln):
            start = i
            break
    if start is None:
        return raw
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if _ACCION_LINE.match(ln):
            break
        block.append(ln)
    return "\n".join(block).strip()


def objective_context(history: list, ctx_lo: int, char_cap: int = 8000):
    """Contexto por paso que FIJA el objetivo y crece append-only. Devuelve
    ``(ctx_text, nuevo_ctx_lo)``.

    Antes el loop usaba ``history[-6:]``: una ventana que se desliza de a uno y
    (a) DESALOJA ``history[0]`` (el 'TAREA: ...') a los ~3-6 pasos, con lo que el
    agente OLVIDA su objetivo en tareas largas, y (b) rompe el prefix-cache de
    llama.cpp cada paso (el texto tras el TOOLS_DOC estatico cambia siempre) ->
    re-prefill innecesario.

    Aca ``history[0]`` (objetivo) se fija SIEMPRE y se agrega la cola
    ``history[ctx_lo:]``. Si el total supera ``char_cap`` se avanza ``ctx_lo`` EN
    BLOQUE (descarta ~1/3 de la cola de una), de modo que el prefijo se mantiene
    estable muchos pasos (cache-friendly) en vez de deslizarse cada paso.
    ``ctx_lo`` solo avanza (nunca retrocede) -> el prompt crece como prefijo.
    """
    if not history:
        return "", ctx_lo
    ctx_lo = max(1, ctx_lo)
    tail = history[ctx_lo:]
    while len(tail) > 4 and len("\n".join([history[0]] + tail)) > char_cap:
        ctx_lo += max(1, len(tail) // 3)
        tail = history[ctx_lo:]
    ctx_text = "\n".join([history[0]] + tail) if tail else history[0]
    return ctx_text, ctx_lo


_FILENAME_RE = re.compile(r"\b[\w./\\-]+\.\w{1,4}\b")
_CONTINUIDAD = ("anterior", "antes", "segui", "seguir", "continua",
                "continuar", "retoma", "retomar", "lo de recien")


def prior_context_relevant(task: str, prev_task: str) -> bool:
    """¿El CONTEXTO PREVIO (estado global ~/.cognia_agent_state.json) ayuda a
    esta tarea o es un distractor?

    Causa raíz medida (bench_estancamiento baseline, 2026-07-07): inyectado
    SIEMPRE, el resumen de tareas anteriores mete nombres de archivo AJENOS;
    el 3B ancla en lo literal (lección +62pp ejemplo-concreto), intenta
    leer_archivo <archivo-de-otra-tarea>, el ERROR se repite bajo greedy y el
    stuck-detector mata la tarea: 4/12 stuck, TODOS con esa firma.

    Relevante (se inyecta) solo si: (a) la tarea nueva refiere explícitamente
    a continuidad, o (b) comparte un nombre de archivo con la tarea previa.
    Trade-off declarado: continuidad temática sin filename ni palabra de
    continuidad NO se detecta — preferible a filtrar distractores siempre.
    """
    tl = task.lower()
    if any(w in tl for w in _CONTINUIDAD):
        return True
    propios = set(_FILENAME_RE.findall(tl))
    previos = set(_FILENAME_RE.findall((prev_task or "").lower()))
    return bool(propios & previos)


def register_action(sig_counts: dict, action: str, args: str) -> str:
    """Detector de estancamiento por conteo de ocurrencias del par
    ``(action, args)`` COMPLETO en TODA la tarea (no solo repeticiones
    consecutivas). Devuelve ``'stop'`` a la 3ra vez, ``'warn'`` a la 2da, ``'ok'``
    si es nueva.

    Mejora sobre el detector consecutivo previo (``sig == _last_sig`` con
    ``args[:60]``): caza tambien ciclos oscilantes A,B,A,B (que reseteaban el
    contador) y usa args completos (no colisiona escrituras distintas al mismo
    archivo ni se pierde diferencias pasado el char 60).
    """
    key = (action, args)
    sig_counts[key] = sig_counts.get(key, 0) + 1
    n = sig_counts[key]
    if n >= 3:
        return "stop"
    if n == 2:
        return "warn"
    return "ok"


# Absolute safety ceiling -- the loop can never exceed this regardless of the
# model's estimate or extension requests. Prevents a stuck agent from looping
# forever while still being "effectively unlimited" for real tasks.
AGENT_HARD_CAP = 40

# Complexity rating (1-5) -> initial step budget.
_RATING_TO_BUDGET = {1: 2, 2: 4, 3: 8, 4: 16, 5: 28}

# Cheap keyword prior used when the model is unavailable or vague.
_SIMPLE_HINTS = (
    "hola", "gracias", "que es", "que hora", "fecha", "define", "calcula",
    "calcular", "suma", "resta", "cuanto es",
)


def estimate_step_budget(task: str, orch, hard_cap: int = AGENT_HARD_CAP) -> int:
    """
    Decide how many steps to grant this task.

    First a cheap heuristic prior, then one quick LLM complexity rating (1-5).
    The rating wins when available; otherwise the heuristic stands. Always
    clamped to [1, hard_cap].
    """
    tl = task.lower()
    if len(task) < 60 and any(h in tl for h in _SIMPLE_HINTS):
        heuristic = 2
    elif len(task) > 200:
        heuristic = 8
    else:
        heuristic = 4

    try:
        prompt = (
            "Clasifica la COMPLEJIDAD de esta tarea para un agente con "
            "herramientas, del 1 (trivial, 1-2 pasos) al 5 (muy compleja, muchos "
            "pasos). Responde SOLO el numero.\n\nTarea: " + task[:400]
        )
        # Cap chico + greedy: la respuesta es UN digito (1-5); sin cap el backend
        # generaria hasta 768 tokens si el 3B ignora "SOLO el numero" (~90s CPU).
        rating_text = orch.infer(prompt, max_tokens=16, temperature=0.0).text
        m = re.search(r"[1-5]", rating_text)
        if m:
            return max(1, min(_RATING_TO_BUDGET[int(m.group())], hard_cap))
    except Exception:
        pass
    return max(1, min(heuristic, hard_cap))


def wants_more_steps(task: str, last_results: str, orch, inferir=None) -> int:
    """
    When the budget runs out without a final answer, ask the model whether the
    task is actually done and, if not, how many MORE steps it needs. Returns the
    number of extra steps to grant (0 = done / no extension). Bounded small so an
    extension can't itself run away; the caller still enforces AGENT_HARD_CAP.

    `inferir(orch, prompt) -> str` permite pasar el mismo camino de inferencia
    que usa el bucle, con su caida a llm_local. Sin eso, esta funcion sacaba un
    digito a la brava del texto que devolviera el orquestador — incluido su
    aviso de "no hay backend", que NO es una excepcion sino una respuesta
    normal. Medido el 2026-07-20: eso concedia pasos extra una y otra vez sobre
    un fallo que no se iba a arreglar solo, y el agente encadeno 40 rondas.
    """
    try:
        prompt = (
            "Un agente trabajo en esta tarea pero se quedo sin pasos. Mira el "
            "ultimo progreso. Si la tarea YA esta resuelta responde 0. Si falta, "
            "responde SOLO cuantos pasos mas necesita (1-8).\n\n"
            f"Tarea: {task[:300]}\n\nUltimo progreso:\n{last_results[:600]}"
        )
        # main: fallback 'inferir' + tolerancia a texto vacio;
        # cognia-x: sampling acotado para una clasificacion (16 tokens, t=0).
        texto = (inferir(orch, prompt) if inferir
                 else (orch.infer(prompt, max_tokens=16,
                                  temperature=0.0).text or ""))
        if not texto:
            return 0
        m = re.search(r"\b([0-8])\b", texto)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0


# ── Cierre informativo (E8, bateria 2026-07-09) ─────────────────────────────
# La tarea pide EJECUTAR algo: el responder no debe cerrar sin una ejecucion
# real en el history. Regex conservadora: verbo de ejecucion como palabra
# ("corregi" NO matchea; "corré el script" si) + en ingles run/execute.
_PIDE_EJECUCION_RX = re.compile(
    r"\b(ejecut\w+|corr[eé]|correlo|run|execute)\b",
    re.IGNORECASE)


def task_pide_ejecucion(task: str) -> bool:
    """True si la tarea pide explicitamente ejecutar/correr algo."""
    return bool(_PIDE_EJECUCION_RX.search(task or ""))


def salida_de_ejecucion(history) -> str:
    """Output de la ULTIMA ejecucion exitosa del history ('' si no hubo).
    Solo exitos: 'RESULTADO ejecutar: ...' sin '(exit N)' ni ERROR."""
    for h in reversed(history or []):
        if h.startswith("RESULTADO ejecutar:"):
            out = h[len("RESULTADO ejecutar:"):].strip()
            if out and out != "(sin output)":
                return out
    return ""


def error_accionable_de_ejecucion(history) -> str:
    """Causa del ULTIMO fallo de tool, o '' si la ultima tool fue exitosa /
    no hubo tools.

    Analogo del cierre E8 exitoso (salida_de_ejecucion) para el caso de ERROR:
    el diag CIERRES midio que cuando una tool FALLA (archivo faltante, script
    que rompe, exit != 0) el 3B tiende a cerrar VACIO ('No tengo esa
    informacion', 'Listo, tarea completada') en vez de reportar la causa
    (error_accionable 2/14, 2026-07-10). E8 solo anexa salidas EXITOSAS, asi
    que ese caso queda sin cubrir. Esto reporta la causa real, determinista,
    sin otra llamada al modelo.

    Convencion de tools.py: un RESULTADO fallido trae 'ERROR' en la cabeza o
    '(exit N)'. Se mira el ULTIMO RESULTADO del history: si fue exito -> ''
    (no es caso de error; si aplica lo cubre salida_de_ejecucion); si fue
    fallo -> su causa (recortada). Asi el parche NUNCA se activa cuando la
    tarea termino bien (la bateria E1-E8 termina siempre en exito -> intacta).
    """
    for h in reversed(history or []):
        if not h.startswith("RESULTADO "):
            continue
        cabeza = h[:160]
        if "ERROR" not in cabeza and "(exit " not in cabeza:
            return ""          # la ultima ejecucion fue exitosa
        return h[len("RESULTADO "):].strip()[:300]
    return ""
