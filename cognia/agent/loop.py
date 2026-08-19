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

import os
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

    # A6 (obra 2026-08-09): el clasificador-racionador LLM esta APAGADO por
    # defecto — la heuristica barata ya es mas fiable que sacar un digito de
    # un razonador con max_tokens=16 (que ademas truncaba el pensamiento:
    # leccion 'presupuesto-tokens-razonamiento'). COGNIA_BUDGET_LLM=1 lo
    # reactiva para medirlo por gate, no por nostalgia.
    if os.environ.get("COGNIA_BUDGET_LLM", "") != "1":
        return max(1, min(heuristic, hard_cap))

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
    # A6 (obra 2026-08-09): APAGADO por defecto. Buscar `[0-8]` en el texto
    # crudo de un razonador es leer hojas de te; el tope real del bucle es
    # max_turns/AGENT_HARD_CAP. COGNIA_WANTS_MORE=1 lo reactiva para medir.
    if os.environ.get("COGNIA_WANTS_MORE", "") != "1":
        return 0
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


# ── Bucle NATIVO (A1/A2/A6, obra 2026-08-09) ────────────────────────────────
# El paso del agente con tool-calling nativo: mensajes estructurados por
# /v1/chat/completions, el server parsea los tool calls (harmony via --jinja)
# y el FIN NATURAL es una respuesta sin tool calls. Sin marco ACCION:, sin
# regex, sin stops que decapiten razonadores, sin cierre-por-prosa degradado.
# El marco texto queda en cli.py como fallback para modelos sin tool-calling.

def _parece_cortado(crudo: str) -> bool:
    """True si el JSON de los argumentos se quedo a medias (no si es raro).

    LA DISTINCION IMPORTA (2026-08-18): `argumentos_rotos` marca cualquier JSON
    que no parsea, y ahi caben DOS cosas muy distintas:
      - CORTADO: {"path":"x.html","contenido":"<!DOCTYPE...   <- se acabo el turno
      - MALFORMADO pero COMPLETO: {'path': 'a.txt'}           <- comillas simples
    El segundo lo rescataba el passthrough de args_legacy y la tool se ejecutaba
    bien. Bloquear los dos por igual convertia un caso que FUNCIONABA en un
    fallo -- lo cazo la revision adversarial con un contrafactual contra el
    commit anterior. Solo el cortado justifica no ejecutar.
    """
    texto = (crudo or "").strip()
    if not texto:
        return True
    # Comillas sin escapar impares -> la cadena quedo abierta.
    fuera, escapando, en_cadena = 0, False, False
    for ch in texto:
        if escapando:
            escapando = False
            continue
        if ch == "\\":
            escapando = True
        elif ch == '"':
            en_cadena = not en_cadena
        elif not en_cadena:
            if ch in "{[":
                fuera += 1
            elif ch in "}]":
                fuera -= 1
    return en_cadena or fuera > 0


def _corte_en_tool_call(resp, schemas) -> str:
    """Motivo si el turno se corto MIENTRAS emitia un tool call, o ''.

    Las dos caras del mismo fallo, segun donde caiga el corte dentro del JSON:

    1. El server no puede parsear los argumentos y devuelve HTTP 500
       ("Failed to parse tool call arguments as JSON ... missing closing
       quote"). Llega como resp.ok=False.
    2. El corte cae fuera de la cadena y el server devuelve un turno limpio
       con finish_reason='length' y CERO tool_calls. Esta cara es la peor: se
       parece a "el modelo decidio no usar herramientas" y el bucle culpaba al
       modelo de un problema de presupuesto.

    No se toca el caso legitimo de cerrar sin tools (finish_reason='stop'):
    eso es el contrato del regimen nativo y sigue intacto.
    """
    if not getattr(resp, "ok", False):
        err = str(getattr(resp, "error", "") or "").lower()
        if "parse tool call arguments" in err or "missing closing quote" in err:
            return "el server no pudo parsear el tool call (se corto a medias)"
        return ""
    if (schemas and getattr(resp, "finish_reason", "") == "length"
            and not getattr(resp, "tool_calls", None)):
        # ...PERO solo si no estaba escribiendo PROSA. Una respuesta final
        # larga que se trunca tambien llega como length + cero tool_calls, y
        # tratarla como "tool call cortado" la reintentaba tres veces y encima
        # le inyectaba al modelo un "escribe el fichero por partes" que no
        # venia a cuento. Con texto sustancial, lo que se corto es la
        # RESPUESTA, y de eso ya avisa el bucle mas abajo.
        if len((getattr(resp, "texto", "") or "").strip()) >= 200:
            return ""
        return "el turno se corto por max_tokens antes de emitir el tool call"
    # Tercera cara: el server DEVUELVE el tool call pero sus argumentos no son
    # JSON valido porque se cortaron a media cadena. chat_client lo marca.
    llamadas = getattr(resp, "tool_calls", None) or []
    rotas = [tc for tc in llamadas
             if getattr(tc, "argumentos_rotos", False)
             and _parece_cortado(getattr(tc, "argumentos_crudos", ""))]
    if rotas and len(rotas) == len(llamadas):
        # Solo si TODAS estan rotas. Si alguna llego sana, repetir el turno
        # tiraria trabajo bueno: se ejecutan las sanas y a la rota se le
        # contesta con el aviso (lo hace el bucle, mas abajo).
        return "los argumentos del tool call llegaron cortados"
    return ""


def _intencion_de(resp) -> str:
    """1 linea legible de que decidio el modelo en este paso (para el
    evento PasoIntencion): primera frase del razonamiento, o del contenido."""
    fuente = (resp.reasoning_content or resp.texto or "").strip()
    linea = fuente.splitlines()[0] if fuente else ""
    return linea[:160]


# Por debajo de esto recortar no compensa: se destroza contexto para liberar
# nada. Vale igual para el content de un turno tool y para el reasoning de un
# assistant.
_RECORTE_MIN = 400


def _recortar_mensajes(mensajes: list, n_ctx, prompt_tokens: int) -> int:
    """Presupuesto de contexto en TOKENS REALES (A4.3): si el ultimo prompt
    supero ~80% del n_ctx del server, recorta a un resumen corto los turnos
    MAS VIEJOS que pesan — el content de los turnos tool y el CoT de los turnos
    assistant (nunca el system ni el user del objetivo). Devuelve cuantos CHARS
    libero (0 = bajo el umbral o nada recortable), para que el llamador pueda
    iterar con un estimado actualizado. El descarte en bloque del contexto
    viejo era la causa de 'el agente olvida su objetivo'; aca el objetivo es
    intocable por diseno.

    POR QUE tambien el reasoning (fix A3-bucle 2026-08-13): chat_client
    .mensaje_assistant reinyecta reasoning_content en CADA turno assistant para
    preservar el CoT entre tool calls. Este recorte solo miraba role=='tool',
    asi que con AGENT_HARD_CAP=40 pasos el CoT acumulado —que puede ser el 80%
    del prompt con un razonador— NUNCA entraba al presupuesto: devolvia 0
    liberados y el prompt reventaba n_ctx en silencio (el server trunca por
    izquierda o tira 'context shift', y el agente pierde el objetivo sin que
    nadie lo diga). Reproducido en test_recorte_incluye_el_reasoning_de_los_
    assistant_viejos: 20 turnos x 5k chars de CoT -> 0 liberados.
    """
    if not n_ctx or prompt_tokens < int(n_ctx * 0.8):
        return 0
    # El CoT del ULTIMO turno assistant es el que el modelo esta usando AHORA
    # (los tool calls de ese mismo turno acaban de volver): se preserva
    # siempre. Los anteriores ya cumplieron su funcion.
    ultimo_assistant = -1
    for i, m in enumerate(mensajes):
        if m.get("role") == "assistant":
            ultimo_assistant = i

    recortados, liberados = 0, 0
    for i, m in enumerate(mensajes):
        rol = m.get("role")
        if rol == "tool" and len(m.get("content") or "") > _RECORTE_MIN:
            antes = len(m["content"])
            m["content"] = (m["content"][:200]
                            + "\n[... recortado por presupuesto de contexto ...]")
            liberados += antes - len(m["content"])
            recortados += 1
        elif (rol == "assistant" and i != ultimo_assistant
                and len(m.get("reasoning_content") or "") > _RECORTE_MIN):
            antes = len(m["reasoning_content"])
            m["reasoning_content"] = (
                m["reasoning_content"][:200]
                + "\n[... razonamiento recortado por presupuesto de contexto ...]")
            liberados += antes - len(m["reasoning_content"])
            recortados += 1
        if recortados >= 3:   # de a poco: 3 turnos por pasada alcanzan
            break
    return liberados


def _catalogo_para_ofertas() -> list:
    """El registry completo para buscar candidatas a ofrecer. [] si falla.

    Import perezoso y tolerante: esta funcion corre dentro del turno del agente
    y un fallo suyo no puede costar la tarea.
    """
    try:
        from cognia.agent.tools import catalogo_schemas
        return catalogo_schemas()
    except Exception:
        return []


# Comandos que CUENTAN como verificacion cuando el agente los ejecuta. La
# politica de parada (cognia/hermes/parada_verificada.py) solo decide; quien
# ejecuta es quien escribe la evidencia, y por eso el filtro vive aca. Correr
# el artefacto que acabas de escribir (python x.py, node x.js) SI es evidencia:
# el gate del camino feliz de este repo ya juzga esa tarea ejecutando el .py.
_RE_VERIFICACION = re.compile(
    r"\b(pytest|unittest|nosetests|tox|ruff|flake8|mypy|pylint|"
    r"npm\s+(run\s+)?test|yarn\s+test|jest|vitest|go\s+test|cargo\s+test|"
    r"dotnet\s+test|mvn\s+test|gradle\s+test)\b|"
    r"\b(python3?|py)\b[^|]*\.py\b|\bnode\b[^|]*\.(js|mjs|ts)\b",
    re.IGNORECASE)


def _es_verificacion(nombre_tool: str, args: str) -> bool:
    """True si esta llamada es un comando de verificacion ya ejecutado."""
    if nombre_tool == "tests":
        return True
    if nombre_tool not in ("ejecutar", "ejecutar_fondo"):
        return False
    try:
        return bool(_RE_VERIFICACION.search(str(args or "")))
    except Exception:
        return False


def bucle_nativo(task: str, system: str, completar, schemas: list,
                 args_legacy, mensaje_assistant, mensaje_tool,
                 run_tool, ctx: dict, perfil: dict, history: list,
                 trace: list, print_fn, max_turns: int) -> dict:
    """El bucle ReAct nativo. Devuelve
    ``{"texto", "pasos", "ok", "tokens", "finish"}``.

    - ``history`` y ``trace`` se APENDEAN con las mismas convenciones de
      strings del camino legacy ("RESULTADO <tool>: ..."), para que todo el
      post-procesado de cli.py (E8, goal_contract, skill_capture, adjuntos)
      siga funcionando sin enterarse del regimen.
    - Emite los eventos del turno (cognia.ux.events); sin suscriptores es
      no-op, y un fallo del bus jamas rompe el paso (contrato de emitir()).
    """
    try:
        from cognia.ux import events as _ev
    except Exception:
        _ev = None

    def _emitir(evento):
        if _ev is not None:
            try:
                _ev.emitir(evento)
            except Exception:
                pass

    # -- ARNES HERMES (2026-08-19) -----------------------------------------
    # Cinco mecanismos destilados del fuente de Hermes Agent 0.19.1 y cableados
    # AQUI, que es el bucle vivo (el while legacy de cli.py solo corre con el
    # perfil 3B o COGNIA_AGENT_LEGACY=1). Cada uno ataca una patologia MEDIDA:
    #   presupuesto+refund   la vuelta administrativa se comia el presupuesto
    #                        de la tarea (iteration_budget.py:37-49 + los
    #                        refunds de conversation_loop.py:1996/6257)
    #   RazonSalida          "Cognia degrada en silencio": todo break sella su
    #                        razon y se loguea SIEMPRE (_turn_exit_reason)
    #   GuardiaBucle         register_action solo caza A-A-A; el ping-pong
    #                        A-B-A-B y los ciclos A-B-C se le escapaban
    #   RegistroMutaciones   el modelo afirmaba haber escrito lo que fallo
    #                        (footer de mutaciones fallidas del turn_finalizer)
    #   parada_verificada    cerrar "listo" sin haber corrido nada; en el
    #                        analisis de 526 fallos de tareas largas el 99,6%
    #                        tenia senal de validacion disponible y no la uso
    # COGNIA_HERMES=0 apaga los cinco de golpe (una sola palanca para el A/B).
    _hermes = os.environ.get("COGNIA_HERMES", "1").strip().lower() not in (
        "0", "off", "false", "no")
    _pres = _salida = _guardia = _muta = None
    _hz_mod = None
    if _hermes:
        try:
            from cognia.hermes.presupuesto_turno import (
                PresupuestoTurno, RazonSalida, MOTIVO_REINTENTO_FORMATO,
                MOTIVO_REINTENTO_RED, RAZON_RESPUESTA_TEXTO,
                RAZON_PRESUPUESTO_AGOTADO, RAZON_ERROR_BACKEND,
                RAZON_BUCLE_DETECTADO, RAZON_INTERRUMPIDO)
            from cognia.hermes.guardia_bucle import GuardiaBucle, EXENTAS_COGNIA
            from cognia.hermes.mutaciones import (
                RegistroMutaciones, es_operacion_de_fichero, ruta_de_args)
            from cognia.hermes import parada_verificada as _hz_mod
            _pres = PresupuestoTurno(max_turns)
            _salida = RazonSalida(_pres, etiqueta="bucle_nativo")
            _guardia = GuardiaBucle(exentas=EXENTAS_COGNIA)
            _muta = RegistroMutaciones()
        except Exception as _e_hm:
            # El arnes es instrumentacion: si no carga, el bucle sigue igual.
            _hermes = False
            print_fn(f"[warn_cl]arnes hermes no disponible ({type(_e_hm).__name__}): "
                     f"sigo sin el[/warn_cl]")
    _nudges_verif = 0          # nudges de parada verificada ya inyectados
    _ts_1a_edicion = None      # epoch de la primera escritura del turno
    _reint_backend = 0         # reintentos por error transitorio del backend
    _pendiente_verif = ""      # respuesta ya compuesta, en rescate tras un nudge
    _aviso_guardia = ""        # mensaje del guardia de bucle para el modelo

    t0 = __import__("time").time()
    if _ev is not None:
        _emitir(_ev.TareaInicio(tarea=task[:300], modo="agente",
                                modelo=perfil.get("modelo", "")))

    mensajes: list = []
    if system:
        mensajes.append({"role": "system", "content": system})
    # El objetivo (+ guidance/pista que cli.py ya metio en history) es el
    # turno user inicial y NUNCA se recorta.
    mensajes.append({"role": "user", "content": "\n\n".join(history)})
    # Alias para el volcado de trazas (COGNIA_TRAZAS=1): apunta a la MISMA
    # lista viva, y sobrevive al `mensajes = None` del corte por
    # estancamiento (el rebind no toca el objeto ya referenciado).
    mensajes_dump = mensajes

    # Reintento por TOOL CALL CORTADO (2026-08-18). Cazado probando el CLI con
    # una tarea normal ("hazme una landing page de cafeteria"): el modelo emite
    # escribir_archivo con el HTML dentro, el presupuesto del turno se acaba a
    # mitad de la cadena JSON y el server responde
    #   HTTP 500 "Failed to parse tool call arguments as JSON ... column 860:
    #   invalid string: missing closing quote; last read: '"<!DOCTYPE html>...'
    # Segun donde caiga el corte, la otra cara es un turno con finish_reason
    # 'length' y CERO tool_calls, que el bucle interpretaba como "el agente
    # cerro sin usar herramientas" -- o sea, culpaba al modelo de un problema
    # de presupuesto. Las dos caras son el mismo fallo y ninguna se reintentaba:
    # la tarea moria con el workspace VACIO tras 100 segundos.
    # Es el bug numero 11 de la familia "presupuesto de tokens con razonadores"
    # que este repo ya tiene documentada.
    _MAX_REINTENTOS_CORTE = 2   # POR PASO: ver el reset dentro del bucle

    sampling = {
        "temperature": perfil.get("temperature", 1.0),
        "top_p": perfil.get("top_p", 1.0),
        "max_tokens": perfil.get("max_tokens", 4096),
        "reasoning_effort": perfil.get("reasoning_effort", ""),
        "url": perfil.get("url", ""),
    }
    # El techo es RELATIVO al presupuesto del perfil, no una constante: con un
    # perfil de 16384 o mas, un techo fijo de 16384 dejaba la rampa sin recorrido
    # y el aviso decia "no cabe ni con max_tokens=32768" sin haber probado nunca
    # con mas. Lo cazo la revision adversarial.
    _TECHO_REINTENTO = max(16384, int(sampling.get("max_tokens") or 4096) * 4)

    # Familias que controlan el razonamiento por otra clave del template
    # (Nemotron: enable_thinking). Ausente en Qwen/harmony -> body intacto.
    if perfil.get("kwargs_plantilla"):
        sampling["kwargs_plantilla"] = perfil["kwargs_plantilla"]

    sig_counts: dict = {}
    # Herramientas ya ofrecidas en ESTA tarea: ofrecer dos veces la misma es
    # ruido, y si no la uso la primera vez es que no la queria.
    _ofertas_hechas: set = set()
    tokens_total = 0
    pasos = 0
    fail_streak = 3
    result_text, finish, ok = "", "", False
    while pasos < max_turns:
        # CORTE COOPERATIVO (T4, 2026-08-18). ctx['_cancelado'] es un callable
        # que inyecta cli.py cuando la tarea corre en el carril de fondo: el
        # usuario apreto Ctrl-C en el prompt de espera o en la vista de
        # agentes. Sin esto, este bucle no tenia NINGUN hook de cancelacion y
        # el "corte pedido" que se imprimia era una mentira: el agente seguia
        # gastando pasos. Se comprueba ENTRE turnos, o sea que la tool en
        # curso (un build, un subprocess) termina antes de cerrar; eso se dice
        # en la linea que se imprime. Sin la clave, no existe.
        _cancelado = ctx.get("_cancelado") if isinstance(ctx, dict) else None
        if callable(_cancelado):
            try:
                _corta = bool(_cancelado())
            except Exception:
                _corta = False          # el hook jamas rompe el turno
            if _corta:
                print_fn(f"[warn_cl]Corte pedido: el agente se detiene tras "
                         f"el paso {pasos}.[/warn_cl]")
                result_text = (f"(corte pedido por el usuario: el agente se "
                               f"detuvo tras el paso {pasos})")
                finish = "cancelado"
                break
        if _pres is not None and not _pres.consume():
            # El contador de Hermes corre EN PARALELO al while: la guarda de
            # arriba es el corte blando; esto es el techo auditado, con los
            # refunds descontados (que es toda la diferencia).
            _salida.sellar(RAZON_PRESUPUESTO_AGOTADO, f"techo {max_turns}")
            result_text = result_text or (
                f"(presupuesto de {max_turns} pasos agotado sin cierre)")
            break
        pasos += 1
        resp = completar(mensajes, tools=schemas, **sampling)
        tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)

        # El cupo se renueva en CADA paso. Era global de la tarea, asi que un
        # paso que gastara los dos reintentos dejaba a todos los siguientes sin
        # rampa: el segundo fichero largo moria sin un solo reintento.
        _reintentos_corte = 0
        _presupuesto_base = sampling["max_tokens"]

        # ¿Se corto el turno mientras emitia un tool call? Entonces el problema
        # es el PRESUPUESTO, no el modelo: se sube y se repite el mismo turno.
        _motivo_corte = _corte_en_tool_call(resp, schemas)
        while (_motivo_corte and _reintentos_corte < _MAX_REINTENTOS_CORTE
               and sampling["max_tokens"] < _TECHO_REINTENTO):
            _antes = sampling["max_tokens"]
            sampling["max_tokens"] = min(_TECHO_REINTENTO, max(2048, _antes * 2))
            _reintentos_corte += 1
            if _pres is not None:
                # Repetir el MISMO paso con mas presupuesto no es razonamiento
                # nuevo: es administracion. Sin el refund, un fichero largo se
                # comia dos vueltas de la tarea (conversation_loop.py:1996).
                _pres.refund(MOTIVO_REINTENTO_FORMATO)
            print_fn(f"[warn_cl]{_motivo_corte}: repito el paso con "
                     f"max_tokens {_antes} -> {sampling['max_tokens']}"
                     f"[/warn_cl]")
            resp = completar(mensajes, tools=schemas, **sampling)
            tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)
            _motivo_corte = _corte_en_tool_call(resp, schemas)
        if _motivo_corte:
            # Ya no queda presupuesto que subir: en vez de morir en silencio, se
            # le DICE al modelo lo que pasa y como salir (escribir por partes).
            # El texto distingue "agote la rampa" de "no habia rampa": decir
            # "no cabe ni con N" sin haber probado con mas de N seria afirmar
            # algo que no se midio.
            if _reintentos_corte:
                print_fn("[warn_cl]el contenido no cabe en un solo tool call "
                         f"ni con max_tokens={sampling['max_tokens']}: le pido "
                         f"al modelo que lo escriba por partes[/warn_cl]")
            else:
                print_fn("[warn_cl]el tool call se corto y el presupuesto ya "
                         f"estaba en el techo ({sampling['max_tokens']}): le "
                         f"pido al modelo que lo escriba por partes[/warn_cl]")
            mensajes.append({
                "role": "user",
                "content": ("AVISO DEL SISTEMA: tu ultima llamada a una "
                            "herramienta se corto porque el contenido era "
                            "demasiado largo para un solo mensaje. Escribe el "
                            "fichero POR PARTES: primero escribir_archivo con "
                            "la primera mitad y luego apendar_archivo con el "
                            "resto. No repitas la llamada entera."),
            })
            resp = completar(mensajes, tools=schemas, **sampling)
            tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)

        # El presupuesto vuelve al del perfil: la subida era para ESTE paso. Si
        # se queda alta, el resto de la tarea paga un techo que no pidio nadie.
        sampling["max_tokens"] = _presupuesto_base

        if not resp.ok:
            # Server caido / respuesta rota: degradar con causa VISIBLE (la
            # degradacion silenciosa es el modo de fallo historico). Con el
            # arnes, ademas, se CLASIFICA: un timeout o un 503 "Loading model"
            # es transitorio y merece repetir la llamada; un contexto excedido
            # o un modelo ausente no (repetir da el mismo error, mas caro).
            _accion = "python scripts/servir_flota.py pensar"
            if _hermes:
                try:
                    from cognia.hermes.errores_backend import (
                        clasificar as _clas_err, accion_sugerida as _acc_err)
                    _diag = _clas_err(resp.error or "")
                    _accion = _acc_err(_diag)
                    _puede_reintentar = (_diag.get("reintentable")
                                         and _reint_backend < 2)
                    if _puede_reintentar and _diag.get("comprimir_contexto"):
                        # Contexto excedido: repetir la MISMA peticion da el
                        # mismo error. Solo se reintenta si el recorte libero
                        # algo de verdad (Hermes separa retryable de
                        # should_compress justo por esto).
                        _liberados = _recortar_mensajes(
                            mensajes, perfil.get("n_ctx"), 10 ** 9)
                        if not _liberados:
                            print_fn("[warn_cl]contexto excedido y no queda "
                                     "nada recortable: no reintento[/warn_cl]")
                            _puede_reintentar = False
                        else:
                            print_fn(f"[warn_cl]contexto excedido: recorte "
                                     f"{_liberados} chars y reintento[/warn_cl]")
                    if _puede_reintentar:
                        _reint_backend += 1
                        if _pres is not None:
                            _pres.refund(MOTIVO_REINTENTO_RED)
                        _espera = min(float(_diag.get("esperar_s") or 0.0), 5.0)
                        print_fn(f"[warn_cl]{_diag['razon']}: reintento "
                                 f"{_reint_backend}/2 en {_espera:.1f}s "
                                 f"({resp.error})[/warn_cl]")
                        if _espera > 0:
                            __import__("time").sleep(_espera)
                        continue
                    _salida.sellar(RAZON_ERROR_BACKEND, _diag.get("razon", ""))
                except Exception:
                    pass
            print_fn(f"[err_cl]Agente (nativo): {resp.error}[/err_cl]")
            print_fn(f"[warn_cl]{_accion}[/warn_cl]")
            if _ev is not None:
                _emitir(_ev.Degradado(
                    donde="agente.bucle_nativo", motivo=resp.error,
                    accion_sugerida=_accion))
            result_text = f"(el agente no pudo hablar con el modelo: {resp.error})"
            break

        if not resp.tool_calls:
            # FIN NATURAL: respuesta sin tool calls = respuesta final. Este es
            # el contrato del regimen nativo (adios "cierro con PROSA degradado")
            # PERO solo cuenta como cierre si hay TEXTO. Fix A3-bucle
            # 2026-08-13: un razonador que gasta todo el turno en el canal
            # analysis deja content vacio (chat_client devuelve texto='') y
            # esta rama devolvia {'texto': '', 'ok': True} — una tarea "OK" sin
            # una sola letra de respuesta. Es la degradacion silenciosa del
            # repo en su forma mas pura: el llamador (cli.py, bancos,
            # goal_contract) no tiene como distinguirla de un exito.
            finish = resp.finish_reason
            if resp.texto:
                result_text, ok = resp.texto, True
            elif resp.reasoning_content:
                # Rescate: el pensamiento SI existe; se entrega marcado y con
                # ok=False (no lo pidio nadie asi, no es una respuesta). La
                # COLA del CoT es donde vive la conclusion, no la cabeza.
                print_fn("[warn_cl]el modelo cerro con la respuesta vacia "
                         "(solo razonamiento): se entrega el razonamiento sin "
                         "marcar la tarea como cumplida[/warn_cl]")
                cola = resp.reasoning_content.strip()[-1200:]
                result_text = ("(el modelo no emitio respuesta final; esto es "
                               "su razonamiento) " + cola)
                ok = False
            else:
                # Ni texto ni pensamiento: no hay nada. Se DICE.
                print_fn("[err_cl]el modelo cerro con una respuesta vacia y "
                         "sin razonamiento que rescatar[/err_cl]")
                result_text = ("(el modelo cerro con una respuesta vacia y sin "
                               f"razonamiento; finish_reason={finish or '?'})")
                ok = False
            # GUARD DE SOSPECHA: cerrar en el PRIMER paso teniendo tools
            # ofrecidas es el sintoma exacto de un server que no parsea
            # tool_calls (llama-server sin --jinja): el modelo emite la llamada
            # como TEXTO, el bucle no ve tool_calls y lo toma por respuesta
            # final. Hasta hoy pasaba en silencio.
            # `pasos == 1` YA ES "sin ninguna tool ejecutada", no hace falta
            # contarlas: para llegar al paso 2 hay que haber pasado por la rama
            # de tool_calls de arriba, y esa rama o ejecuta al menos una tool o
            # sale del bucle por estancamiento. La primera version de este fix
            # llevaba un contador `tools_ejecutadas` en la condicion; era
            # codigo muerto (valia 0 SIEMPRE aca) y se borro el 2026-08-14.
            # Test que fija la equivalencia:
            # test_llegar_al_paso_2_exige_haber_ejecutado_una_tool.
            if pasos == 1 and schemas:
                print_fn("[warn_cl]el agente cerro sin usar herramientas en el "
                         "primer paso: si esperabas trabajo real, sospecha del "
                         "tool-calling del server (llama-server necesita "
                         "--jinja para parsear tool_calls)[/warn_cl]")
            if resp.finish_reason == "length":
                # Truncado por presupuesto: se DICE (los dos modos de fallo
                # —stop mal puesto vs presupuesto— se veian iguales antes).
                print_fn("[warn_cl]respuesta final truncada por max_tokens "
                         f"({sampling['max_tokens']})[/warn_cl]")
            # PUERTA DE PARADA VERIFICADA (Hermes: verification_stop.py).
            # El modelo no cierra un turno que EDITO CODIGO sin evidencia
            # fresca de haberlo corrido. No es un prompt: es una continuacion
            # ACOTADA del bucle (maximo 2 nudges) con la respuesta ya compuesta
            # en rescate, para que la compuerta nunca destruya trabajo hecho.
            if (_hermes and _hz_mod is not None and _muta is not None
                    and ok and _nudges_verif < 2 and _muta.ficheros_escritos()):
                _nudge = None
                try:
                    _nudge = _hz_mod.decidir({
                        "ficheros_editados": _muta.ficheros_escritos(),
                        "nudges_usados": _nudges_verif,
                        "superficie": "cli",
                        "workspace": os.getcwd(),
                        "ts_primera_edicion": _ts_1a_edicion,
                    })
                except Exception:
                    _nudge = None
                if _nudge:
                    _nudges_verif += 1
                    print_fn("[warn_cl]parada verificada: el turno edito ficheros "
                             "y no hay evidencia fresca de haberlos probado; "
                             "pido la verificacion[/warn_cl]")
                    _pendiente_verif = result_text or _pendiente_verif
                    mensajes.append({"role": "user", "content": _nudge})
                    result_text, ok = "", False
                    continue
            if _salida is not None:
                _salida.sellar(RAZON_RESPUESTA_TEXTO,
                               f"finish={finish or '?'}")
            break

        # La intencion se emite SOLO cuando hay tools que ejecutar: en el
        # turno final la "intencion" seria la primera linea de la respuesta
        # misma y saldria duplicada en pantalla (cazado en el e2e 2026-08-09).
        if _ev is not None:
            _emitir(_ev.PasoIntencion(paso=pasos, intencion=_intencion_de(resp)))

        idx_turno = len(mensajes)   # desde aca: lo apendeado en ESTE turno
        mensajes.append(mensaje_assistant(resp))
        for tc in resp.tool_calls:
            # ARGUMENTOS CORTADOS (2026-08-18). chat_client ya marcaba esto
            # (argumentos_rotos) y NADIE lo miraba: se llamaba a la tool con el
            # crudo sin parsear y la tool se quejaba de lo que le llegara. En la
            # corrida que lo cazo, el modelo mando
            #   {"path":"cafeteria.html","contenido":"<!DOCTYPE html>...
            # con el JSON cortado a media cadena, y el agente recibio
            #   "ERROR: path outside agent workspace"
            # o sea: se puso a arreglar la RUTA -- que era correcta -- mientras
            # el problema real era el TAMANO del contenido. Tres intentos
            # persiguiendo el sintoma equivocado y el workspace vacio.
            if (getattr(tc, "argumentos_rotos", False)
                    and _parece_cortado(getattr(tc, "argumentos_crudos", ""))):
                crudo = getattr(tc, "argumentos_crudos", "") or ""
                resultado = (
                    f"RESULTADO {tc.nombre} ERROR: los argumentos llegaron "
                    f"CORTADOS ({len(crudo)} chars, JSON incompleto). No es un "
                    f"problema de la ruta ni del formato: el contenido es "
                    f"demasiado largo para un solo mensaje. Escribelo POR "
                    f"PARTES: escribir_archivo con la primera parte y luego "
                    f"apendar_archivo con el resto.")
                print_fn(f"[warn_cl]{tc.nombre}: argumentos cortados a los "
                         f"{len(crudo)} chars; le pido al modelo que escriba "
                         f"por partes[/warn_cl]")
                history.append(resultado)
                trace.append({"action": tc.nombre, "args": crudo[:200],
                              "ok": False, "result_head": resultado[:160]})
                mensajes.append(mensaje_tool(tc.id, resultado))
                continue
            args_str = args_legacy(tc.nombre, tc.argumentos)
            if _ev is not None:
                _emitir(_ev.ToolInicio(tool=tc.nombre, args=args_str[:120],
                                       paso=pasos))
            t_tool = __import__("time").time()
            if _guardia is not None:
                # register_action solo caza A-A-A (mismo par tool+args 3 veces).
                # El guardia anade ping-pong A-B-A-B y ciclos A-B-C-A-B-C, que
                # es como se ve de verdad un agente atascado con dos ficheros.
                _vg = _guardia.registrar(tc.nombre, args_str)
                if _vg.get("estado") == "bloqueo":
                    print_fn(f"[warn_cl]{_vg.get('mensaje') or 'bucle detectado'}"
                             f"[/warn_cl]")
                    _salida.sellar(RAZON_BUCLE_DETECTADO, _vg.get("patron", ""))
                    result_text = ("(interrumpida: el agente entro en bucle -- "
                                   f"{_vg.get('patron', 'repeticion')})")
                    mensajes = None
                    break
                if _vg.get("estado") == "aviso":
                    _aviso_guardia = _vg.get("mensaje") or ""
            verdict = register_action(sig_counts, tc.nombre, args_str)
            if verdict == "stop":
                # Estancamiento (3ra vez el MISMO par tool+args): cierre
                # honesto con lo que hay, sin quemar mas presupuesto.
                print_fn("[warn_cl]Agente estancado (tool repetida 3 veces): "
                         "cierre honesto.[/warn_cl]")
                if _salida is not None:
                    _salida.sellar(RAZON_BUCLE_DETECTADO, f"repite {tc.nombre}")
                result_text = ("(interrumpida por estancamiento: repitio "
                               f"'{tc.nombre}' con los mismos argumentos)")
                mensajes = None
                break
            resultado = run_tool(tc.nombre, args_str, ctx)
            # Solo la PRIMERA linea clasifica: los errores del registry ponen
            # ERROR en la linea 1; el CONTENIDO de un exito (un log con
            # errores via ctx_grep/leer_archivo) no debe marcar fallo y
            # disparar el corte por no-progreso (fix 2026-08-11).
            tool_ok = not re.search(r"\bERROR\b",
                                    resultado.split("\n", 1)[0][:120])
            if _muta is not None and es_operacion_de_fichero(tc.nombre):
                # Se anota el INTENTO y su resultado MEDIDO. El footer del
                # epilogo hace imposible que el modelo afirme haber escrito
                # cinco ficheros cuando tres patches fallaron.
                _idm = _muta.intento(ruta_de_args(args_str), tc.nombre)
                _muta.resultado(_idm, tool_ok, resultado)
                if tool_ok and _ts_1a_edicion is None:
                    _ts_1a_edicion = __import__("time").time()
            if _hermes and _hz_mod is not None and _es_verificacion(tc.nombre, args_str):
                # Evidencia de verificacion: la escribe QUIEN EJECUTA, con el
                # resultado real. La politica (parada_verificada) no corre nada.
                try:
                    _hz_mod.registrar_verificacion(
                        os.getcwd(), args_str[:200], tool_ok, resultado[:600])
                except Exception:
                    pass
            history.append(resultado)
            trace.append({"action": tc.nombre, "args": args_str[:200],
                          "ok": tool_ok, "result_head": resultado[:160]})
            if _ev is not None:
                _emitir(_ev.ToolFin(
                    tool=tc.nombre, args=args_str[:120], ok=bool(tool_ok),
                    resumen=resultado[:200],
                    duracion_s=__import__("time").time() - t_tool, paso=pasos))
            # OFERTA PROACTIVA (opt-in COGNIA_TOOLS_PROACTIVAS, idea del dueno
            # 2026-08-13): el razonamiento del turno dice que esta intentando
            # hacer; si una tool NO anunciada lo resuelve, se le ofrece aqui —
            # pegada al resultado, que es lo ULTIMO que lee antes de volver a
            # decidir. Maximo 2 y sin repetir, porque el A/B del repo midio que
            # inflar el catalogo degrada. Apagado -> devuelve el resultado tal cual.
            try:
                from cognia.harness.sugerencia_proactiva import anexar as _ofrecer
                resultado_msg = _ofrecer(
                    resultado, resp.reasoning_content,
                    {s.get("function", {}).get("name") for s in (schemas or [])},
                    _catalogo_para_ofertas(), _ofertas_hechas,
                    intencion=_intencion_de(resp))
            except Exception:
                resultado_msg = resultado
            mensajes.append(mensaje_tool(tc.id, resultado_msg))
            if _aviso_guardia:
                mensajes.append({"role": "user", "content": _aviso_guardia})
                _aviso_guardia = ""
            if verdict == "warn":
                mensajes.append({
                    "role": "user",
                    "content": (f"AVISO: ya llamaste '{tc.nombre}' con esos "
                                "mismos argumentos y no avanzo. No la repitas: "
                                "proba otra herramienta o responde el cierre.")})
        if mensajes is None:      # corto por estancamiento adentro del for
            break

        # Corte por NO-PROGRESO: N tools seguidas fallando = el modelo no
        # avanza (misma cota dura que el camino legacy).
        recientes = trace[-fail_streak:]
        if len(recientes) >= fail_streak and not any(a["ok"] for a in recientes):
            print_fn(f"[warn_cl]Agente sin progreso ({fail_streak} tools "
                     "seguidas fallaron): cierre honesto.[/warn_cl]")
            if _salida is not None:
                _salida.sellar(RAZON_BUCLE_DETECTADO,
                               f"{fail_streak} tools fallidas")
            result_text = (f"(interrumpida: {fail_streak} herramientas seguidas "
                           "fallaron sin avanzar; el modelo no logro la tarea)")
            break

        # El prompt_tokens del usage NO incluye lo que este turno apendeo
        # (assistant + N turnos tool): con tool-calls paralelas de resultados
        # grandes el estimado rancio dejaba crecer el prompt por encima de
        # n_ctx sin recortar nada (fix 2026-08-11). Se suma lo agregado
        # (chars/4) y se itera hasta bajar del umbral o agotar recortables.
        est = int((resp.usage or {}).get("prompt_tokens") or 0)
        # Se cuenta TAMBIEN el reasoning_content: mensaje_assistant lo
        # reinyecta y con un razonador pesa mas que el content (parte del fix
        # A3-bucle: el CoT era invisible para el presupuesto de punta a punta).
        est += sum(len(str(m.get("content") or ""))
                   + len(str(m.get("reasoning_content") or ""))
                   for m in mensajes[idx_turno:]) // 4
        while True:
            liberados = _recortar_mensajes(mensajes, perfil.get("n_ctx"), est)
            if not liberados:
                break
            est -= liberados // 4
    else:
        # Presupuesto agotado sin cierre: redaccion final honesta con la
        # evidencia del history (no un volcado crudo).
        ultimo = next((h for h in reversed(history)
                       if h.startswith("RESULTADO ")), "")
        result_text = (f"(presupuesto de {max_turns} pasos agotado sin cierre) "
                       + ultimo[:300])

    # RESCATE de la respuesta pendiente: si la puerta de verificacion pidio un
    # nudge y despues se agoto el presupuesto, la respuesta que el modelo YA
    # habia compuesto no se puede perder (turn_finalizer.py:100-124).
    if _pendiente_verif and not (result_text or "").strip():
        result_text = _pendiente_verif
        ok = True
    # FOOTER DE MUTACIONES FALLIDAS: hecho medido, no resumen del modelo.
    if _muta is not None:
        try:
            _foot = _muta.footer()
        except Exception:
            _foot = None
        if _foot:
            result_text = (result_text or "") + "\n\n" + _foot
    _envelope = {}
    if _salida is not None:
        try:
            _hist_cierre = list(mensajes) if isinstance(mensajes, list) else []
            if (result_text or "").strip():
                # La respuesta final del turno NO se apendea a `mensajes` (el
                # bucle sale con el break), asi que sin esto el ultimo mensaje
                # siempre era un resultado de tool y la alarma saltaba en cada
                # turno sano -- una alarma que suena siempre no es una alarma.
                _hist_cierre.append({"role": "assistant",
                                     "content": result_text})
            _envelope = _salida.cerrar(_hist_cierre)
        except Exception:
            _envelope = {}

    if _ev is not None:
        _emitir(_ev.TareaFin(ok=ok, resumen=(result_text or "")[:300],
                             pasos=pasos, tokens_predichos=tokens_total,
                             duracion_s=__import__("time").time() - t0))
    # Volcado de traza chatml (COGNIA_TRAZAS=1): TODAS las salidas del bucle
    # (fin natural, estancamiento, no-progreso, infra, presupuesto) convergen
    # aca, fuera del camino caliente. volcar() devuelve el TASK_ID (no la
    # ruta): se publica en ctx para que los selladores (horizonte, bancos)
    # etiqueten por id. Best-effort total: jamas rompe el retorno.
    try:
        from cognia.agent import traza_chatml as _trz
        if _trz.habilitada():
            ctx["_traza_task_id"] = _trz.volcar(
                "", mensajes_dump, schemas, sampling, perfil,
                {"texto": result_text, "pasos": pasos, "ok": ok,
                 "tokens": tokens_total, "finish": finish})
    except Exception:
        pass
    return {"texto": result_text, "pasos": pasos, "ok": ok,
            "tokens": tokens_total, "finish": finish,
            "razon": (_envelope or {}).get("razon", ""),
            "envelope": _envelope}
