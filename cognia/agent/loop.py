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

    sampling = {
        "temperature": perfil.get("temperature", 1.0),
        "top_p": perfil.get("top_p", 1.0),
        "max_tokens": perfil.get("max_tokens", 4096),
        "reasoning_effort": perfil.get("reasoning_effort", ""),
        "url": perfil.get("url", ""),
    }

    sig_counts: dict = {}
    # Herramientas ya ofrecidas en ESTA tarea: ofrecer dos veces la misma es
    # ruido, y si no la uso la primera vez es que no la queria.
    _ofertas_hechas: set = set()
    tokens_total = 0
    pasos = 0
    # Cuantas tools corrio el bucle en TODA la tarea: alimenta el guard de
    # sospecha del cierre (un cierre sin una sola tool no es lo mismo que un
    # cierre tras trabajar).
    tools_ejecutadas = 0
    fail_streak = 3
    result_text, finish, ok = "", "", False
    while pasos < max_turns:
        pasos += 1
        resp = completar(mensajes, tools=schemas, **sampling)
        tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)

        if not resp.ok:
            # Server caido / respuesta rota: degradar con causa VISIBLE (la
            # degradacion silenciosa es el modo de fallo historico).
            print_fn(f"[err_cl]Agente (nativo): {resp.error}[/err_cl]")
            if _ev is not None:
                _emitir(_ev.Degradado(
                    donde="agente.bucle_nativo", motivo=resp.error,
                    accion_sugerida="python scripts/servir_flota.py pensar"))
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
            # GUARD DE SOSPECHA: cerrar en el PRIMER paso sin haber llamado
            # NINGUNA tool, teniendo tools ofrecidas, es el sintoma exacto de
            # un server que no parsea tool_calls (llama-server sin --jinja):
            # el modelo emite la llamada como TEXTO, el bucle no ve tool_calls
            # y lo toma por respuesta final. Hasta hoy pasaba en silencio.
            if pasos == 1 and not tools_ejecutadas and schemas:
                print_fn("[warn_cl]el agente cerro sin usar herramientas en el "
                         "primer paso: si esperabas trabajo real, sospecha del "
                         "tool-calling del server (llama-server necesita "
                         "--jinja para parsear tool_calls)[/warn_cl]")
            if resp.finish_reason == "length":
                # Truncado por presupuesto: se DICE (los dos modos de fallo
                # —stop mal puesto vs presupuesto— se veian iguales antes).
                print_fn("[warn_cl]respuesta final truncada por max_tokens "
                         f"({sampling['max_tokens']})[/warn_cl]")
            break

        # La intencion se emite SOLO cuando hay tools que ejecutar: en el
        # turno final la "intencion" seria la primera linea de la respuesta
        # misma y saldria duplicada en pantalla (cazado en el e2e 2026-08-09).
        if _ev is not None:
            _emitir(_ev.PasoIntencion(paso=pasos, intencion=_intencion_de(resp)))

        idx_turno = len(mensajes)   # desde aca: lo apendeado en ESTE turno
        mensajes.append(mensaje_assistant(resp))
        for tc in resp.tool_calls:
            args_str = args_legacy(tc.nombre, tc.argumentos)
            if _ev is not None:
                _emitir(_ev.ToolInicio(tool=tc.nombre, args=args_str[:120],
                                       paso=pasos))
            t_tool = __import__("time").time()
            verdict = register_action(sig_counts, tc.nombre, args_str)
            if verdict == "stop":
                # Estancamiento (3ra vez el MISMO par tool+args): cierre
                # honesto con lo que hay, sin quemar mas presupuesto.
                print_fn("[warn_cl]Agente estancado (tool repetida 3 veces): "
                         "cierre honesto.[/warn_cl]")
                result_text = ("(interrumpida por estancamiento: repitio "
                               f"'{tc.nombre}' con los mismos argumentos)")
                mensajes = None
                break
            resultado = run_tool(tc.nombre, args_str, ctx)
            tools_ejecutadas += 1
            # Solo la PRIMERA linea clasifica: los errores del registry ponen
            # ERROR en la linea 1; el CONTENIDO de un exito (un log con
            # errores via ctx_grep/leer_archivo) no debe marcar fallo y
            # disparar el corte por no-progreso (fix 2026-08-11).
            tool_ok = not re.search(r"\bERROR\b",
                                    resultado.split("\n", 1)[0][:120])
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
            "tokens": tokens_total, "finish": finish}
