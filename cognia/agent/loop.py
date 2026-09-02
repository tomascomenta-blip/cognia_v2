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

import json
import logging
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

# TOOLS EXPLORATORIAS: leen y no tocan nada. Se reusa la tabla de
# multiverso/reversibilidad (TOOLS_PURAS, la misma que autoriza a especular) y
# se le suma `recuperar`, que no esta alli porque no es una accion del mundo
# sino la via de recuperacion del propio offload -- y es, precisamente, la que
# mas pasos de lectura consume. Un paso cuyas tools son TODAS de esta lista no
# gasta credito de arranque en el gobernador de progreso (ver
# presupuesto_progreso.CREDITO_EXPLORACION).
try:
    from cognia.multiverso.reversibilidad import TOOLS_PURAS as _TOOLS_PURAS
    TOOLS_EXPLORATORIAS = frozenset(_TOOLS_PURAS) | {"recuperar"}
except Exception:      # pragma: no cover - tabla ausente: nada es exploratorio
    TOOLS_EXPLORATORIAS = frozenset({
        "leer_archivo", "leer_lote", "listar", "buscar", "recuperar", "arbol"})

# Techo al que puede llegar el presupuesto de pasos AMPLIANDOLO con progreso
# VERIFICADO (nunca por pedirlo). Ver la ampliacion en bucle_nativo.
AGENT_CAP_CON_PROGRESO = 120

# Pasos de solo lectura que no gastan credito de arranque (el defecto lo fija
# presupuesto_progreso; se importa aqui para no duplicar el numero).
try:
    from cognia.estado.presupuesto_progreso import (
        CREDITO_EXPLORACION as _CREDITO_EXPLORACION)
except Exception:      # pragma: no cover - el gobernador es opcional
    _CREDITO_EXPLORACION = 8

# Complexity rating (1-5) -> initial step budget.
_RATING_TO_BUDGET = {1: 2, 2: 4, 3: 8, 4: 16, 5: 28}

# Cheap keyword prior used when the model is unavailable or vague.
_SIMPLE_HINTS = (
    "hola", "gracias", "que es", "que hora", "fecha", "define", "calcula",
    "calcular", "suma", "resta", "cuanto es",
)


# Tools tras las que el lazo corto CORRE el fichero escrito.
_TOOLS_ESCRITURA_LAZO = frozenset({"escribir_archivo", "editar_archivo", "apendar_archivo"})
# A partir de aqui una escritura cuenta como "grande" y se aconseja trocear.
# ~9k chars son ~2.500 tokens de argumentos: con el razonamiento por delante
# ya roza el tope de salida de un turno con este modelo.
_TOPE_ESCRITURA_TROZO = 9000


_RE_FICHERO_SUELTO = re.compile(
    r"(?:^|[\\/])(?:debug|dbg|tmp|temp|prueba|pruebas|scratch|borrador|"
    r"verificar|verifica|check|chequeo|diag|diagnostico|sonda|probar|"
    r"repro|kk|foo|bar)(?:[_\-\d]\w*)?\.(?:js|mjs|py|sh|bat|ps1)$", re.I)
# (?:[_\-\d]\w*)? y no [_\-]?\w*: 'check' seguido de letras es otra palabra
# (checkout.js es producto), 'check_api.py' o 'debug7.js' si son sueltos.


def _es_fichero_suelto(ruta) -> bool:
    """Un script de usar-y-tirar, por su NOMBRE. test_*.py NO cuenta: los tests
    son producto; debug7.js no."""
    return bool(_RE_FICHERO_SUELTO.search(str(ruta or "")))


def _ruta_escrita(args_str) -> str:
    """La ruta de una tool de fichero, vengan los args como JSON nativo
    ({"ruta": ..., "contenido": ...}) o como legado ('ruta | contenido')."""
    texto = str(args_str or "").strip()
    if texto.startswith("{"):
        try:
            import json as _json
            d = _json.loads(texto)
            for k in ("ruta", "path", "archivo", "fichero", "file"):
                if isinstance(d, dict) and d.get(k):
                    return str(d[k]).strip()
        except Exception:
            pass
    return texto.split("|", 1)[0].strip().strip('"').strip("'")

_OBS_DIRS_FUERA = {"__pycache__", ".git", "node_modules", ".pytest_cache",
                   "venv", ".venv", "venv312", "venv312gpu", ".cognia", "dist",
                   "build", ".mypy_cache", "site-packages"}
_OBS_TOPE_FICHEROS = 4000


def _ficheros_tocados_desde(raiz, ts, tope=_OBS_TOPE_FICHEROS):
    """Ficheros bajo `raiz` con mtime posterior a `ts`. Nunca lanza.

    Es la deteccion de mutaciones por OBSERVACION: no pregunta como se llamaba
    la herramienta, mira el disco. El tope de ficheros existe porque el cwd
    puede ser un repo enorme y esto corre despues de cada tool call: pasado el
    tope se abandona y se devuelve lo visto, que es peor que nada pero no
    cuesta segundos.
    """
    fuera = []
    vistos = 0
    try:
        for base, dirs, ficheros in os.walk(str(raiz)):
            dirs[:] = [d for d in dirs if d not in _OBS_DIRS_FUERA
                       and not d.startswith(".")]
            for f in ficheros:
                vistos += 1
                if vistos > tope:
                    return fuera[:20]
                ruta = os.path.join(base, f)
                try:
                    if os.path.getmtime(ruta) >= ts - 0.05:
                        fuera.append(os.path.relpath(ruta, str(raiz)))
                except OSError:
                    continue
                if len(fuera) >= 20:
                    return fuera
    except Exception:
        pass
    return fuera


# Pared minima que tiene que quedar para que valga la pena retener un cierre y
# pedir otro ciclo de trabajo. Por debajo de esto el turno que se gana no cabe:
# con este modelo un paso util (generacion + tool) cuesta del orden de 30-60 s.
_PARED_MINIMA_TRABAJO = 120.0
ENV_PARED = "COGNIA_PARED_S"


def _pared_total():
    """El presupuesto de pared de la tarea en segundos, o None si nadie lo puso."""
    crudo = os.environ.get(ENV_PARED, "")
    try:
        total = float(crudo)
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None


def _pared_restante(t0):
    """Segundos de presupuesto de PARED que le quedan a la tarea, o None.

    El agente no sabia cuanto reloj le queda: quien lo mata es el de fuera (un
    runner, un cron, la paciencia del dueno) y el bucle se enteraba cuando ya
    estaba muerto. Con COGNIA_PARED_S puesto, las compuertas pueden decidir
    entre 'gasta otro ciclo' y 'entrega lo que hay'. Sin la variable, todo
    sigue como estaba.
    """
    crudo = os.environ.get(ENV_PARED, "")
    if not crudo:
        return None
    try:
        total = float(crudo)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return max(0.0, total - (__import__("time").time() - t0))


def techo_por_contrato(task: str, base: int = AGENT_HARD_CAP) -> int:
    """El techo de pasos que merece ESTE encargo, por el trabajo que enumera.

    POR QUE (2026-08-31). `AGENT_HARD_CAP` era una constante: 40 pasos para
    "resume este parrafo" y 40 para un encargo de doce sistemas. El presupuesto
    salia de la LONGITUD del texto y de la dificultad estimada, dos proxies que
    saturan: cualquier encargo largo da dificultad 1,0 y se lleva el mismo
    techo, tenga tres requisitos o quince.

    El numero de requisitos ENUMERADOS es una medida directa de cuanto trabajo
    distinto se pidio, y es la que usa el contrato para decidir si se puede
    cerrar. Que las dos decisiones -- cuanto presupuesto doy y cuando dejo
    cerrar -- salgan de la misma cuenta es lo que evita el caso absurdo de
    retener un cierre por requisitos pendientes sin dar pasos para hacerlos.

    Solo puede SUBIR el techo (nunca por debajo de `base`) y no pasa del tope
    que ya existia para la ampliacion ganada con evidencia, asi que ninguna
    tarea que hoy funciona pierde nada.
    """
    # CON RELOJ DE PARED, LOS PASOS NO SON EL RECURSO ESCASO (2026-09-01).
    # Medido con 20 min de presupuesto: una tarea agoto su techo de 40 pasos a
    # los 518 s, con once minutos de reloj sin usar y avanzando. Cuando alguien
    # de fuera pone el limite en segundos (COGNIA_PARED_S), el techo de pasos
    # sube al maximo que ya existia para la ampliacion por progreso: el reloj
    # manda y el gobernador de progreso sigue vigilando los bucles esteriles.
    if _pared_total() is not None:
        return AGENT_CAP_CON_PROGRESO
    try:
        from cognia.harness.contrato_tarea import derivar
        n = len(derivar(task or ""))
    except Exception:
        return base
    if n < 3:
        return base
    return max(base, min(AGENT_CAP_CON_PROGRESO, n * 6))


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

    # ESCALERA POR DIFICULTAD (2026-08-26). La escalera de arriba topa en 8 =
    # rating 3 de 5: los dos escalones altos de _RATING_TO_BUDGET (16 y 28)
    # eran INALCANZABLES sin el clasificador LLM, que esta apagado por
    # defecto desde el 2026-08-09. O sea que CUALQUIER tarea grande recibia
    # el mismo presupuesto que un "resume este parrafo": 8 pasos.
    #
    # MEDIDO con estimate_task_difficulty (cero LLM, ya calibrada, ya se
    # calcula en el camino -- cli.py:21654 la deja en ctx['hybrid']):
    #     tarea                                chars  dific  pasos
    #     hola                                     4  0,003      2
    #     abreme una pestana de chrome en yt      39  0,029      4
    #     crea una carpeta llamada pruebas        32  0,186      4
    #     arregla el bug del login y corre tests  52  0,226      4
    #     "desarrolla un videojuego de VOLEIBOL"  14.220  0,900   8  <--
    # La ultima es la tarea real del dueno del 2026-08-26 (chat_history id
    # 1018): 14.220 caracteres de especificacion, dificultad 0,900, y ocho
    # llamadas al modelo para construir un juego entero. No hay timeout que
    # arregle eso: la tarea se queda sin presupuesto antes de empezar.
    #
    # MONOTONO A PROPOSITO: se toma el MAXIMO con la escalera vieja, nunca el
    # nuevo valor a secas. Asi ninguna tarea que hoy funciona pierde pasos
    # (el 'abreme chrome' de 0,029 seguiria valiendo 4 y no 2), y el cambio
    # solo puede ABRIR presupuesto donde hoy falta. El techo sigue siendo
    # AGENT_HARD_CAP y las guardas de estancamiento siguen cortando antes si
    # el agente no avanza: esto da margen, no barra libre.
    try:
        from cognia.agent.hybrid_router import estimate_task_difficulty
        d = estimate_task_difficulty(task)
        rating = 1 if d < 0.15 else 2 if d < 0.35 else (
            3 if d < 0.55 else 4 if d < 0.75 else 5)
        heuristic = max(heuristic, _RATING_TO_BUDGET[rating])
    except Exception as e:
        # Degradacion VISIBLE (regla del repo: "no lo cablearon" y "se rompio"
        # no pueden verse igual). Sin la senal queda la escalera vieja.
        logging.getLogger(__name__).warning(
            "estimate_step_budget sin senal de dificultad (%s: %s); uso la "
            "escalera de longitud", type(e).__name__, e)

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


from cognia.harness.veredicto_tool import es_fallo as _es_fallo_tool
# El techo de generacion REAL es n_ctx - prompt, no max_tokens: ver el modulo
# (mide el caso que se llevo la tarea del Minecraft el 2026-08-30).
from cognia.agent import presupuesto_salida as _ps
from cognia.harness import telemetria as _tel


def _tel_turno(resp, paso, ms, n_tools=0):
    """Un renglon del diario por llamada al modelo. Apagado por defecto.

    Los numeros salen del usage que YA tiene el bucle: sin esto la unica forma
    de saber cuantos tokens costo un paso era estimarlos desde fuera con
    chars/4, que es justo la medida que este repo tiene documentado que miente.
    """
    if not _tel.activa():
        return
    try:
        u = (getattr(resp, "usage", None) or {})
        _tel.evento("turno", paso=paso,
                    tokens_entrada=int(u.get("prompt_tokens") or 0),
                    tokens_salida=int(u.get("completion_tokens") or 0),
                    estimado=bool(getattr(resp, "usage_estimado", False)),
                    finish=str(getattr(resp, "finish_reason", "") or ""),
                    n_tool_calls=int(n_tools),
                    ms=int(ms * 1000))
    except Exception:
        pass
from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR

# Tools cuyo trabajo ES repetirse: correr la suite tras cada arreglo, mirar la
# salida de un proceso de fondo, listar procesos. La lista vive en
# guardia_bucle.py (que ya las salta); se importa aca para que el corte de
# register_action tampoco las cuente. Fallback vacio: sin el modulo hermes el
# comportamiento es el historico, no un crash.
try:
    from cognia.hermes.guardia_bucle import EXENTAS_COGNIA as EXENTAS_TOOLS
except Exception as _e_exentas:      # pragma: no cover - wheel sin hermes
    logging.getLogger(__name__).warning(
        "guardia_bucle no disponible (%s): el corte por repeticion contara "
        "tambien las tools exentas", type(_e_exentas).__name__)
    EXENTAS_TOOLS = frozenset()

# Como se lee que la respuesta YA reporta un fallo: exit, excepcion,
# traceback, 'fallo', 'no se pudo'... Sirve para NO anexar el cierre E8 de
# error cuando el modelo ya lo conto (parafraseado: el substring literal de
# los 120 chars del error casi nunca esta) y para que el footer no diga ✓
# encima de un 'No se pudo completar' (juez 2026-08-24).
_RE_REPORTA_FALLO = re.compile(
    r"(?i)\b(traceback|\w*error\b|exit\s*(?:code\s*)?-?[1-9]\d*|"
    r"c[o\u00f3]digo de salida|fall[o\u00f3]|fallad[oa]|no se pudo|no pude|"
    r"excepci[o\u00f3]n|exception)\b")


def ya_reporta_fallo(texto: str) -> bool:
    """True si la respuesta final ya cuenta que algo fallo."""
    return bool(_RE_REPORTA_FALLO.search(texto or ""))


def anexo_fallo_final(result_text: str, err: str) -> str:
    """La respuesta + el cierre E8 de ERROR como bloque FENCED, no como
    prosa: el render Markdown se comia '<string>' y '<module>' del traceback
    (los tomaba por HTML) y lo aplastaba en una linea."""
    return (f"{result_text}\n\nNo se pudo completar: la \u00faltima "
            f"operaci\u00f3n fall\u00f3. Causa:\n\n```text\n{err[:400]}\n```")


# razon del envelope (hermes/presupuesto_turno) -> etiqueta del footer. Punto
# de extension: una razon nueva que merezca verse en el footer se agrega aca.
_MOTIVOS_CIERRE = {
    "bucle_detectado": "parado",
    "presupuesto_agotado": "presupuesto agotado",
    "error_backend": "backend",
    "excepcion": "excepcion",
    "interrumpido": "interrumpido",
    "estancado_sin_progreso": "sin progreso verificado",
}


def motivo_de_cierre(envelope) -> str:
    """'parado: 3 tools seguidas fallaron' o '' si el turno cerro normal."""
    env = envelope or {}
    etiqueta = _MOTIVOS_CIERRE.get(str(env.get("razon") or ""), "")
    if not etiqueta:
        return ""
    detalle = str(env.get("detalle") or "").strip()
    return f"{etiqueta}: {detalle}" if detalle else etiqueta


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
        # Veredicto compartido (harness/veredicto_tool): una lectura cuyo
        # contenido arranca con 'ERROR' NO es un fallo de la tool.
        if not _es_fallo_tool(h):
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


# El corte que cae ANTES de que el tool call empiece: el presupuesto se lo
# comio el RAZONAMIENTO, no el fichero. Es constante y no literal suelto
# porque el bucle decide con el (apagar el pensamiento) y una errata en la
# comparacion dejaria la intervencion muerta y muda.
CORTE_ANTES_DEL_TOOL_CALL = (
    "el turno se corto por max_tokens antes de emitir el tool call")


# Razonamiento (en chars) por encima del cual un tool call cortado ya no es
# "el fichero era grande" sino "el turno se lo comio pensando". Medido
# 2026-08-31 contra el 27B-Ridge del dueno con el MISMO prompt:
#   thinking ON,  2.500 tokens -> 10.359 chars de razonamiento y CERO de
#                 respuesta, finish='length'
#   thinking OFF, 1.115 tokens ->      0 chars de razonamiento y 4.691 de
#                 respuesta, finish='stop'
# En la corrida real que lo cazo (Vaelmark, 2026-08-31) el paso llevaba 20.000
# chars pensando y el tool call salio cortado a los 697. A nivel de modulo para
# que se pueda leer y calibrar sin abrir el bucle.
_RAZON_SE_LO_COMIO = 6000
# Techo VIVO de razonamiento por turno: a partir de aqui, un turno que no ha
# emitido ni un fragmento de respuesta ni de tool call se corta y se repite sin
# pensamiento. 12.000 chars son ~4.000 tokens, ~85 s de generacion con el
# modelo de esta casa: ya es caro y todavia deja pensar de sobra a un turno
# legitimo (la mediana de un paso sano medida esta noche es de 300-900 chars).
# COGNIA_TOPE_RAZON lo mueve; 0 lo apaga.
try:
    _TOPE_RAZON_VIVO = max(0, int(os.environ.get("COGNIA_TOPE_RAZON", "12000")))
except Exception:
    _TOPE_RAZON_VIVO = 12000
if _TOPE_RAZON_VIVO == 0:
    _TOPE_RAZON_VIVO = 10 ** 9


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
        return CORTE_ANTES_DEL_TOOL_CALL
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


def _tokens_prompt(mensajes: list) -> int:
    """Estimacion chars/4 de TODO lo que va a viajar en la peticion.

    Misma moneda que el presupuesto de contexto del final del bucle, con una
    diferencia que importa: aqui se cuentan tambien los ARGUMENTOS de los
    tool_calls. Un `escribir_archivo` de 40 KB deja ese fichero entero dentro
    del turno assistant y se reenvia en cada paso; el estimado que solo miraba
    content+reasoning lo daba por gratis, y con eso el hueco de salida que
    calculaba era mas grande que el real justo en las tareas que escriben
    ficheros grandes -- o sea, en las que fallaban.
    """
    total = 0
    for m in mensajes or ():
        total += len(str(m.get("content") or ""))
        total += len(str(m.get("reasoning_content") or ""))
        for tc in (m.get("tool_calls") or ()):
            f = tc.get("function") if isinstance(tc, dict) else None
            if isinstance(f, dict):
                total += len(str(f.get("arguments") or ""))
    return total // 4


_INTENCION_TOPE = 160


def recortar_en_palabra(texto: str, tope: int = _INTENCION_TOPE) -> str:
    """Recorta a `tope` chars en un LIMITE DE PALABRA y cierra con elipsis.
    Antes era `linea[:160]`: 'Could it be t' a secas, sin senal de corte."""
    texto = (texto or "").strip()
    if len(texto) <= tope:
        return texto
    corte = texto.rfind(" ", 0, tope)
    if corte < tope // 2:
        corte = tope - 1
    return texto[:corte].rstrip(" ,;:") + "\u2026"


def _intencion_de(resp) -> str:
    """1 linea legible de que decidio el modelo en este paso (para el
    evento PasoIntencion): primera frase del razonamiento, o del contenido."""
    fuente = (resp.reasoning_content or resp.texto or "").strip()
    linea = fuente.splitlines()[0] if fuente else ""
    return recortar_en_palabra(linea)


# Por debajo de esto recortar no compensa: se destroza contexto para liberar
# nada. Vale igual para el content de un turno tool y para el reasoning de un
# assistant.
_RECORTE_MIN = 400

# P2 (2026-08-24, deepagents 0.7.8, middleware/summarization.py::
# _truncate_tool_call): los ARGUMENTOS de las tools de escritura viejas son
# compresion SIN PERDIDA — el contenido ya esta en el fichero del disco — y
# eran lo unico que ni el recorte ni la compactacion tocaban: _recortar_
# mensajes solo miraba content/reasoning, compactacion._chars_msg los CUENTA
# y la cola retenida se quedaba con args de 40 KB. Umbral 2000 y cabeza de 20
# chars: los mismos de deepagents. Nombres reales de agent/tools.py.
_ARGS_TRUNCAR_MIN = 2000
_TOOLS_ESCRITURA = frozenset({"escribir_archivo", "editar_archivo",
                              "apendar_archivo"})
_MARCA_ARG_TRUNCADO = "… (argumento truncado: el contenido ya esta en el fichero)"
# Cabeza que se conserva de cada VALOR largo (deepagents: value[:20]).
_ARGS_CABEZA = 20

# P5b (deepagents 0.7.8, middleware/_overflow_clip.py: los read_file finales
# se recortan a 4000 chars con puntero al path). El generico de 200 chars le
# quitaba al modelo el fichero Y la forma de recuperarlo; este conserva 4000
# y le dice donde sigue (leer_archivo <ruta> offset=N).
_RECORTE_LEER = 4000
_RE_CABECERA_LEER = re.compile(r"^RESULTADO leer_archivo (.+?): ")


def _truncar_valores_args(args: str) -> str:
    """Trunca POR VALOR, como deepagents 0.7.8 (summarization.py::
    _truncate_tool_call recorre args.items() y corta cada str largo a
    value[:20]): el JSON sigue siendo JSON y la ruta sobrevive. La version
    anterior cortaba el STRING entero a 20 chars y dejaba
    '{"path": "src/app.py… (argumento truncado...' sin cierre: ese assistant
    se reenvia en cada turno y llama-server (Qwen3.8-27B en :8080) responde
    HTTP 500 "Failed to parse tool call arguments as JSON" a TODA la
    peticion: el agente moria tras la primera compactacion (revision
    adversarial 2026-08-24, reproducido con curl). Ademas compactacion.
    _ruta_de_args ya no puede sacar la ruta de un JSON roto y ARTEFACTOS
    mostraba el blob. Args no JSON (protocolo texto 'ruta | contenido'): se
    conserva la ruta (lo que va antes del primer '|') y se marca el resto."""
    try:
        d = json.loads(args)
    except ValueError:
        d = None
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, str) and len(v) > _ARGS_TRUNCAR_MIN:
                d[k] = v[:_ARGS_CABEZA] + _MARCA_ARG_TRUNCADO
        return json.dumps(d, ensure_ascii=False)
    ruta = args.split("|", 1)[0].strip()[:200]
    return ruta + " | " + _MARCA_ARG_TRUNCADO


def _lleva_marca_truncado(tc) -> bool:
    """True si algun argumento del tool call ES el marcador de truncado.

    Mira los VALORES ya parseados y no el JSON crudo: `json.dumps` escapa el
    '…' del marcador como '\\u2026', asi que buscar la marca en el serializado
    no acierta nunca. El crudo se mira ademas por si los argumentos no vinieron
    como JSON (protocolo texto 'ruta | contenido'), donde no hay escapes."""
    args = getattr(tc, "argumentos", None)
    if isinstance(args, dict):
        for v in args.values():
            if isinstance(v, str) and _MARCA_ARG_TRUNCADO in v:
                return True
    elif isinstance(args, str) and _MARCA_ARG_TRUNCADO in args:
        return True
    return _MARCA_ARG_TRUNCADO in str(getattr(tc, "argumentos_crudos", "") or "")


def _tool_calls_con_parciales(resp):
    """Los tool calls del turno, VENGAN DE DONDE VENGAN.

    Un turno que termino bien los deja en `.tool_calls`. Uno que se corto
    -- por cancelacion, por caida de red o porque el server devolvio 500 al no
    poder parsear unos argumentos cortados a media cadena -- los deja en
    `.tool_calls_parciales`, que hasta hoy no leia NADIE en el repo. Justo el
    caso del 500 es el que trae dentro el fichero a medio escribir, o sea los
    KB por los que ya se pago la generacion.
    """
    salida = list(getattr(resp, "tool_calls", None) or ())
    if str(getattr(resp, "finish_reason", "")) == "cancelado":
        # UN TURNO QUE CORTO EL USUARIO NO SE RESCATA. chat_client vacia
        # .tool_calls a proposito en ese caso (su docstring: "la respuesta
        # cortada NUNCA tiene la clave 'tool_calls'"); leer aqui los parciales
        # reabriria por la puerta de atras justo lo que ese diseno cierra:
        # escribir ficheros despues del Esc.
        return salida
    salida.extend(getattr(resp, "tool_calls_parciales", None) or ())
    return salida


def _hay_parcial_rescatable(resp) -> bool:
    """True si el turno cortado trae DENTRO un fichero que se puede escribir.

    Existe para decidir el ORDEN, que resulto ser lo que importaba: cuando el
    corte llega con los argumentos a medias, reintentar cuesta una generacion
    entera (~6 min con el modelo del dueno) y puede volver a cortarse en la
    misma columna, mientras que rescatar es gratis y conserva los bytes que ya
    se pagaron. Con este check la rampa deja pasar ese caso al camino del
    rescate en vez de tirarlo para repetir el paso.
    """
    try:
        from cognia.agent import rescate_parcial as _rp
    except ImportError:
        return False
    for tc in _tool_calls_con_parciales(resp):
        if not getattr(tc, "argumentos_rotos", False):
            continue
        if getattr(tc, "nombre", "") not in _TOOLS_ESCRITURA:
            continue
        if getattr(tc, "nombre", "") == "editar_archivo":
            continue
        if _rp.partes(getattr(tc, "argumentos_crudos", "") or ""):
            return True
    return False


def _rescatar_escritura(tc, crudo: str, ctx, run_tool, print_fn):
    """Escribe el TROZO que si llego de un tool call cortado. None si no hay
    nada que rescatar (y entonces manda el aviso de "por partes" de siempre).

    POR QUE (medido 2026-08-30). El aviso de "escribelo por partes" es
    correcto y NO ALCANZA: el modelo vuelve a empezar por el principio con el
    mismo presupuesto y se corta en la misma columna. En la corrida del dueno
    el aviso salio cuatro veces seguidas, se tiraron ~2.100 chars de HTML
    valido cada vez y el fichero nunca llego a existir.

    Escribiendo el trozo, el turno siguiente ya no reescribe: CONTINUA. El
    corte deja de costar una vuelta entera y pasa a costar un tramo, que es
    lo unico que convierte "tarea larga" en algo que termina.

    La escritura va por `run_tool`, o sea con las mismas guardas de workspace,
    codificacion y diff que cualquier otra: aqui no se toca el disco a mano.
    """
    try:
        from cognia.agent import rescate_parcial as _rp
        from cognia.agent.tool_schemas import args_legacy
    except ImportError as exc:                 # el bucle no puede morir por esto
        logging.getLogger(__name__).warning("rescate parcial no disponible: %s", exc)
        return None
    if tc.nombre not in _TOOLS_ESCRITURA:
        return None
    trozo = _rp.partes(crudo)
    if not trozo:
        return None
    # editar_archivo necesita el bloque VIEJO ademas del nuevo: media edicion
    # no es media escritura, es una edicion que no aplica. Solo se rescata lo
    # que es "poner contenido al final de un fichero".
    if tc.nombre == "editar_archivo":
        return None
    seguro, descartados = _rp.recortar_a_frontera(trozo["parcial"])
    if len(seguro) < _rp.MINIMO_RESCATABLE:
        return None
    # EL RESCATE NO PUEDE COMERSE UN FICHERO YA ESCRITO. `escribir_archivo`
    # SOBRESCRIBE: si el modelo repite la llamada sobre un fichero que ya
    # estaba entero (porque un paso anterior si cupo) y esta se corta,
    # rescatar el parcial cambiaria un fichero completo por su principio. Es
    # la misma clase de fallo que el marcador de truncado del 2026-08-26, y
    # aqui la escribiria el propio arreglo. Si en el disco hay MAS de lo que
    # traigo, no toco nada y se lo digo al modelo.
    if tc.nombre == "escribir_archivo":
        try:
            from cognia.agents.workers.dev_tools import resolve_write_path
            _dest = resolve_write_path(trozo["ruta"])
            if _dest.exists() and _dest.stat().st_size > len(seguro.encode("utf-8")):
                print_fn(f"[warn_cl]no rescato el parcial de {trozo['ruta']}: "
                         f"en el disco ya hay mas de lo que traia el trozo "
                         f"cortado (no se machaca)[/warn_cl]")
                return (f"RESULTADO {tc.nombre} ERROR: tu llamada se corto, y "
                        f"{trozo['ruta']} YA tiene mas contenido del que "
                        f"alcanzaste a mandar. No se sobrescribio nada. Si "
                        f"querias AGREGAR, usa apendar_archivo; si querias "
                        f"cambiar una parte, usa editar_archivo. No reescribas "
                        f"el fichero entero: no cabe en un mensaje.")
        except Exception:
            return None                        # ruta rara: mejor no tocar disco
    # Un corte sobre escribir_archivo se escribe entero (crea/sobrescribe);
    # sobre apendar_archivo se apenda, que es lo que el modelo pedia.
    res = run_tool(tc.nombre,
                   args_legacy(tc.nombre, {"path": trozo["ruta"],
                                           "contenido": seguro,
                                           "texto": seguro}),
                   ctx)
    if "ERROR" in (res or "")[:120]:
        # La tool se nego (ruta fuera del workspace, permisos): no se inventa
        # un exito. Vuelve None y manda el aviso de siempre.
        print_fn(f"[warn_cl]el rescate del parcial no pudo escribir: "
                 f"{(res or '')[:120]}[/warn_cl]")
        return None
    cola = _rp.ancla(seguro)
    print_fn(f"[warn_cl]{tc.nombre}: los argumentos se cortaron a los "
             f"{len(crudo)} chars; RESCATADOS {len(seguro)} chars a "
             f"{trozo['ruta']} — el modelo continua desde ahi[/warn_cl]")
    return (f"RESULTADO {tc.nombre} {trozo['ruta']}: PARCIAL. Tu llamada se "
            f"corto a media cadena porque el contenido no cabia en un solo "
            f"mensaje, pero NO se perdio: se escribieron los primeros "
            f"{len(seguro)} chars"
            + (f" (se descarto una linea a medias de {descartados} chars)"
               if descartados else "")
            + f".\nEl fichero termina AHORA MISMO asi:\n---\n{cola}\n---\n"
            f"NO reescribas el fichero ni repitas nada de eso. Sigue con "
            f"apendar_archivo {trozo['ruta']} | <lo que va DESPUES>, en "
            f"trozos de como mucho 100 lineas cada uno, hasta terminarlo.")


def _truncar_args_escritura(mensajes: list, ultimo_assistant: int) -> int:
    """Trunca los arguments > _ARGS_TRUNCAR_MIN de escribir/editar/apendar en
    los assistant ANTERIORES al ultimo (el ultimo es el turno en curso: sus
    tools acaban de correr y el server puede reintentarlo). Devuelve chars
    liberados. Idempotente: un arg ya truncado mide < 2000 (solo se
    reemplaza si de verdad achica: un JSON de valores cortos pero > 2000 en
    total se deja como esta)."""
    liberados = 0
    for i, m in enumerate(mensajes):
        if m.get("role") != "assistant" or i == ultimo_assistant:
            continue
        for tc in (m.get("tool_calls") or []):
            f = tc.get("function") if isinstance(tc, dict) else None
            if not isinstance(f, dict) or f.get("name") not in _TOOLS_ESCRITURA:
                continue
            args = f.get("arguments")
            if isinstance(args, str) and len(args) > _ARGS_TRUNCAR_MIN:
                nuevo = _truncar_valores_args(args)
                if len(nuevo) < len(args):
                    f["arguments"] = nuevo
                    liberados += len(args) - len(nuevo)
    return liberados


def _offset_de_call(mensajes: list, tool_call_id) -> int:
    """El offset= con el que se pidio ese leer_archivo (1 si no lo dijo):
    el RESULTADO no lo repite, solo los arguments del assistant lo saben."""
    for m in mensajes:
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                args = str((tc.get("function") or {}).get("arguments") or "")
                mo = re.search(r"offset\W{0,3}(\d+)", args)
                return max(1, int(mo.group(1))) if mo else 1
    return 1


def _recortar_leer_archivo(content: str, offset: int) -> str:
    """Recorte DIRIGIDO de un RESULTADO leer_archivo: conserva hasta
    _RECORTE_LEER chars (en linea completa: el modelo copia lo que ve en
    bloques SEARCH) y anexa el puntero de continuacion con la ruta y la
    linea siguiente a la ultima conservada. Si el resultado no supera los
    4000 con margen, la cabeza es la generica de 200 pero el puntero se
    conserva igual: la ruta es lo que permite recuperar el fichero."""
    mo = _RE_CABECERA_LEER.match(content)
    ruta = mo.group(1)
    cabecera = content[:mo.end()]
    cuerpo = content[mo.end():]
    cap = (_RECORTE_LEER if len(content) > _RECORTE_LEER + _RECORTE_MIN
           else 200)
    cabeza = cuerpo[:cap]
    corte = cabeza.rfind("\n")
    if corte > 0:
        cabeza = cabeza[:corte]
    siguiente = offset + cabeza.count("\n") + 1
    return (cabecera + cabeza
            + f"\n[... recortado; el fichero completo esta en {ruta}: "
              f"leer_archivo {ruta} offset={siguiente} ...]")


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
    # El umbral es el MISMO de la compactacion y de la barra (capacidad util
    # x umbral_frac): tres aritmeticas distintas discrepaban en el mismo
    # turno (revision adversarial 2026-08-24). Sin el modulo (roto) se cae a
    # la cuenta de siempre y se deja rastro.
    try:
        from cognia.harness.compactacion import umbral_tokens as _umbral
        umbral = _umbral(n_ctx)
    except ImportError as exc:
        logging.getLogger(__name__).warning(
            "compactacion no importable (%s): umbral 0.8*n_ctx", exc)
        umbral = int(n_ctx * 0.8) if n_ctx else 0
    if not n_ctx or prompt_tokens < umbral:
        return 0
    # El CoT del ULTIMO turno assistant es el que el modelo esta usando AHORA
    # (los tool calls de ese mismo turno acaban de volver): se preserva
    # siempre. Los anteriores ya cumplieron su funcion.
    ultimo_assistant = -1
    for i, m in enumerate(mensajes):
        if m.get("role") == "assistant":
            ultimo_assistant = i

    # P2 primero y ENTERO (no de a 3): es sin perdida, asi que no hay motivo
    # para racionarlo, y cada arg truncado es contenido que el recorte con
    # perdida de abajo ya no tiene que pagar.
    recortados, liberados = 0, _truncar_args_escritura(mensajes, ultimo_assistant)
    for i, m in enumerate(mensajes):
        rol = m.get("role")
        if rol == "tool" and len(m.get("content") or "") > _RECORTE_MIN:
            antes = len(m["content"])
            if _RE_CABECERA_LEER.match(m["content"]):
                # P5b: leer_archivo conserva mas y dice donde sigue.
                nuevo = _recortar_leer_archivo(
                    m["content"], _offset_de_call(mensajes, m.get("tool_call_id")))
            else:
                nuevo = (m["content"][:200]
                         + "\n[... recortado por presupuesto de contexto ...]")
            if len(nuevo) >= antes:
                # Ya recortado y no achica mas (un leer_archivo recortado a
                # 200 + puntero mide 430-540 chars con una ruta larga, por
                # encima de _RECORTE_MIN): contarlo como recortado gastaba
                # las 3 plazas de la pasada en 0 chars y el llamador cortaba
                # su while con el ejecutar de 9 KB y el reasoning intactos:
                # overflow SILENCIOSO, la clase A3 que esta funcion documenta
                # haber curado (revision adversarial 2026-08-24). Se salta
                # sin gastar plaza.
                continue
            m["content"] = nuevo
            liberados += antes - len(nuevo)
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


def _parchear_huerfanos(mensajes) -> int:
    """P1 (deepagents PatchToolCallsMiddleware): antes de un corte a mitad
    del for de tool_calls, cada call sin su turno tool recibe uno sintetico
    (traza_chatml.parchear_huerfanos). Sin el modulo se sigue y se deja
    rastro: el bucle no puede depender de la captura de trazas."""
    try:
        from cognia.agent.traza_chatml import parchear_huerfanos
        return parchear_huerfanos(mensajes) if isinstance(mensajes, list) else 0
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "tool_calls huerfanos sin parchear: %s: %s", type(exc).__name__, exc)
        return 0


def _degradado_compactacion(print_fn, motivo: str) -> None:
    """El fallo del resumen se VE (regla del repo: prohibido el vacio mudo) y
    el turno cae al truncado de siempre. El import de cli es a call-time y
    best-effort (mismo patron que harness/interceptor): sin CLI, el aviso sale
    igual por print_fn."""
    motivo = f"{motivo}; caigo al modo truncado en este turno"
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado("compactacion", motivo)
    except Exception:
        print_fn(f"[warn_cl]compactacion degradada: {motivo}[/warn_cl]")


def _compactar_por_resumen(mensajes, n_ctx, prompt_tokens, estado, print_fn):
    """F4: compactacion por RESUMEN estructurado en UNA pasada
    (harness/compactacion): [system, objetivo, resumen, cola intacta], una
    sola invalidacion de la KV cache en vez de una por mordisco.

    Devuelve los CHARS liberados (0 = bajo el umbral o nada que fundir), o
    None si toca usar el modo truncado: porque el modo configurado es
    'truncado' (COGNIA_COMPACT o config de /compactar), porque el modulo no
    carga, o porque construir el resumen FALLO en este turno. compactar()
    no muta nada antes de lanzar, asi que el fallback trabaja sobre el
    historial byte-identico."""
    try:
        from cognia.harness import compactacion as comp
    except Exception as exc:
        _degradado_compactacion(print_fn, f"modulo no importable: {exc}")
        return None
    try:
        if comp.modo() != "resumen":
            return None
        # P2 tambien aqui: la cola que compactar() retiene intacta conservaba
        # los args de 40 KB de escribir_archivo (los cuenta _chars_msg). Solo
        # por encima del umbral, como el resto de la funcion.
        liberados_args = 0
        if n_ctx and int(prompt_tokens or 0) >= comp.umbral_tokens(n_ctx):
            ultimo = max((i for i, m in enumerate(mensajes)
                          if m.get("role") == "assistant"), default=-1)
            liberados_args = _truncar_args_escritura(mensajes, ultimo)
        info = comp.compactar(mensajes, n_ctx, prompt_tokens - liberados_args // 4,
                              estado=estado)
    except Exception as exc:
        motivo = f"{type(exc).__name__}: {exc}"
        try:
            comp.anotar_error(motivo)
        except Exception:
            pass
        _degradado_compactacion(print_fn, motivo)
        return None
    if info.get("aplicada"):
        print_fn(f"[detail]compactado por resumen: ~{info['tokens_antes']} -> "
                 f"~{info['tokens_despues']} tokens ({info['descartados']} "
                 f"mensajes viejos fundidos en un resumen)[/detail]")
    return int(info.get("liberados") or 0) + liberados_args


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


def _escape_seguro(texto) -> str:
    """El motivo del veredicto va a un print con markup: se neutralizan los
    corchetes para que un '[algo]' no se coma la linea entera."""
    return str(texto or "").replace("[", "(").replace("]", ")")


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


def _anotar_uso_vivo(resp, n_ctx, mensajes, print_fn) -> None:
    """Alimenta harness/contexto_vivo con el usage REAL del turno (tokens de
    la sesion del footer) y fija la ocupacion de la ventana: prompt+salida
    si el server dijo prompt_tokens; si no (stream sin chunk de usage), el
    historial a chars/4 MARCADO estimado — la barra lo pinta con '~'.
    Best-effort CON aviso: la barra no puede costar el turno, pero un fallo
    mudo aqui es justo lo que dejo el footer en '0/65.5k (100% libre)' toda
    la sesion (cazado TECLEANDO 2026-08-24: registrar_uso no tenia NINGUN
    llamador en el repo)."""
    try:
        from cognia.harness import contexto_vivo as _cv
        u = (resp.usage or {}) if resp is not None else {}
        entrada = int(u.get("prompt_tokens") or 0)
        salida = int(u.get("completion_tokens") or 0)
        estimado = bool(getattr(resp, "usage_estimado", False))
        _cv.registrar_uso(entrada, salida, estimado=estimado)
        if not entrada:
            entrada = sum(len(str(m.get("content") or ""))
                          + len(str(m.get("reasoning_content") or ""))
                          for m in (mensajes or [])) // 4
            estimado = True
        _cv.registrar_contexto(entrada + salida, n_ctx, estimado=estimado)
    except Exception as exc:
        print_fn(f"[warn_cl]contexto vivo no anotado (uso): {exc}[/warn_cl]")


def _anotar_ocupacion_viva(est, n_ctx, estimado: bool, print_fn) -> None:
    """Fija la ocupacion de la ventana en contexto_vivo con la MISMA cuenta
    que acaba de decidir la compactacion (`est` post-recorte): footer y
    disparo de /compactar dicen el mismo numero, o el amarillo miente."""
    try:
        from cognia.harness import contexto_vivo as _cv
        _cv.registrar_contexto(est, n_ctx, estimado=estimado)
    except Exception as exc:
        print_fn(f"[warn_cl]contexto vivo no anotado (ocupacion): {exc}"
                 f"[/warn_cl]")


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
    # CANAL DE ESTADO + GOBERNADOR POR PROGRESO (2026-08-19). El canal es el
    # registro estructurado de lo que se hizo, medido del disco y no de lo que
    # el modelo dice; el gobernador mide COSTE POR AVANCE VERIFICADO. Medido
    # sobre trazas reales de este repo: una corrida de promptevo de 2,69 h que
    # acabo en +0,000 se habria cortado tras el 12% del tiempo, y 314 de 318
    # intentos de tool_rota (churn puro, cero verificaciones) se habrian
    # ahorrado. COGNIA_ESTADO=0 apaga los dos.
    _estado_on = os.environ.get("COGNIA_ESTADO", "1").strip().lower() not in (
        "0", "off", "false", "no")
    _canal = _estado = _prog = None
    # El interruptor se lee UNA vez y fuera del bloque opcional de abajo: si el
    # gobernador no carga, `_largas` tiene que seguir existiendo (lo mira la
    # ampliacion del presupuesto). Un NameError aqui mataria el turno entero.
    try:
        from cognia.harness.offloading import tareas_largas as _tl
        _largas = _tl()
    except Exception:
        _largas = True
    if _estado_on:
        try:
            from cognia.estado import canal as _canal
            from cognia.estado.presupuesto_progreso import Progreso as _Progreso
            _estado = _canal.EstadoVerificado(objetivo=task)
            # umbral_arranque 6 y no 4: la calibracion de 4 salio de tareas de
            # reparacion, que verifican temprano. Aqui hay tareas que leen
            # mucho antes de producir el primer avance verificable.
            #
            # Y ESCALA CON EL PRESUPUESTO (2026-08-26). Un 6 fijo significa
            # cosas distintas segun el tamano de la tarea: con 8 pasos es el
            # 75% del presupuesto (razonable), pero con 28 es el 21% -- se le
            # concede a la tarea grande el presupuesto que merece y se la mata
            # antes de gastar un cuarto. MEDIDO en la corrida real del
            # videojuego: 28 pasos concedidos, cerrada por 'sin_arranque' a
            # los 9, con CERO ficheros escritos, tras gastar los primeros
            # pasos en cortes de max_tokens y en comprobar que pygame estaba
            # instalado -- trabajo legitimo de arranque que no deja "avance
            # verificado" ninguno.
            # max(6, ...) para que ninguna tarea pierda margen: con 8 o menos
            # pasos el umbral sigue siendo exactamente el de hoy.
            # umbral_estancado (la MESETA, ya habiendo avanzado) no se toca:
            # ahi si hubo arranque y 6 pasos sin un avance nuevo es senal.
            # COGNIA_TAREAS_LARGAS=0 devuelve el gobernador al arnes de
            # antes del 2026-08-30 (sin credito de exploracion y sin contar
            # el crecimiento del artefacto), para poder medir el A/B.
            _prog = _Progreso(nombre="bucle_nativo",
                              umbral_arranque=max(6, max_turns // 2),
                              umbral_estancado=6,
                              credito_exploracion=(
                                  _CREDITO_EXPLORACION if _largas else 0),
                              contar_crecimiento=_largas)
        except Exception:
            _estado_on = False
    _ext_sin_avance = 0        # ampliaciones concedidas antes del 1er avance
    _nudges_verif = 0          # nudges de parada verificada ya inyectados
    _ts_1a_edicion = None      # epoch de la primera escritura del turno
    _reint_backend = 0         # reintentos por error transitorio del backend
    # REVISION PROFUNDA ANTES DE ENTREGAR (harness/revision_profunda.py). La
    # compuerta de arriba (parada_verificada) es POLITICA: mira si hay evidencia
    # y, si no, le pide al MODELO que verifique. Esta EJECUTA: cuando el turno
    # produjo un trabajo complejo, el arnes compila lo escrito, corre los tests
    # que lo cubren y ARRANCA el producto de verdad (teclado guionado + brazo B,
    # o navegador real y contrato de clics para una pagina) antes de dejar
    # entregar. Corre PRIMERO a proposito: si sella con exito, registra la
    # evidencia en el ledger y la compuerta de politica ya no gasta un turno del
    # modelo pidiendo lo que esto acaba de hacer. COGNIA_REVISION=0 la apaga.
    _rev_mod = None
    _rondas_rev = 0            # rondas de reparacion pedidas por la revision
    _informe_rev = None        # ultimo informe, para el footer del turno
    try:
        from cognia.harness import revision_profunda as _rev_mod
    except Exception as _e_rev:
        print_fn(f"[warn_cl]revision profunda no disponible "
                 f"({type(_e_rev).__name__}: {_e_rev}); entrego sin ella[/warn_cl]")
    # ESPECULACION (multiverso/especulacion.py). El predictor por defecto es
    # deterministico (bigramas sobre la traza) y no cuesta un token: si tras
    # 'listar' este agente pidio 'leer_archivo' el 70% de las veces, adelantarlo
    # mientras el modelo piensa es gratis. Solo acciones PURAS, comprobado dos
    # veces (al predecir y al ejecutar).
    _especular = os.environ.get("COGNIA_ESPECULAR", "0").strip().lower() in (
        "1", "on", "true", "yes")
    _espec = None
    _cache_espec = None
    if _especular:
        try:
            from cognia.multiverso import especulacion as _espec
        except Exception:
            _especular = False
    _pendiente_verif = ""      # respuesta ya compuesta, en rescate tras un nudge
    _aviso_guardia = ""        # mensaje del guardia de bucle para el modelo
    # P12: BUCLE POR FICHERO (harness/repeticion.ContadorFichero). Los cuatro
    # detectores de arriba cuentan por tool+args; N ediciones al MISMO fichero
    # con args distintos no las ve ninguno. Uno por tarea; COGNIA_REPETICION=0
    # lo apaga con el resto del subsistema.
    _cont_fich = None
    _rep_mod = None
    try:
        from cognia.harness import repeticion as _rep_mod
        from cognia.hermes.mutaciones import ruta_de_args as _ruta_fich
        if _rep_mod.activo():
            _cont_fich = _rep_mod.ContadorFichero()
    except Exception as _e_rf:
        print_fn(f"[warn_cl]deteccion de bucle por fichero no disponible "
                 f"({type(_e_rf).__name__}: {_e_rf}); sigo sin ella[/warn_cl]")
    _aviso_fichero = ""        # nudge de reconsideracion por fichero

    t0 = __import__("time").time()
    if _ev is not None:
        _emitir(_ev.TareaInicio(tarea=task[:300], modo="agente",
                                modelo=perfil.get("modelo", "")))
    # Buffer de outputs COMPLETOS del turno (ux/tool_buffer): /expandir y el
    # render colapsado hablan siempre de ESTA tarea, asi que se vacia aca.
    try:
        from cognia.ux import tool_buffer as _tbuf
        _tbuf.nuevo_turno()
    except Exception:
        _tbuf = None

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

    # -- STREAMING (2026-08-26) --------------------------------------------
    # POR QUE. chat_client tiene rama SSE desde el 2026-08-17, con 55 tests
    # verdes... y NADIE la usaba: `grep -rn "on_token=" cognia/` devolvia UN
    # solo resultado, la propia firma de completar(). Todo el agente iba por
    # el camino NO-stream, y ahi el docstring de completar() ("el timeout es
    # de INACTIVIDAD, no de pared -- en los DOS caminos") es FALSO: sin
    # stream, llama-server no manda un solo byte hasta terminar la generacion
    # entera, asi que la PRIMERA lectura del socket ya espera la respuesta
    # completa y el timeout de urlopen se comporta como un deadline de PARED.
    #
    # MEDIDO 2026-08-26 con un server falso que tarda 6 s en responder y un
    # presupuesto de 3 s (mismo binario, mismo completar(), lo unico que
    # cambia es on_token):
    #     no-stream : ok=False  tardo=3,02 s  error='TimeoutError: timed out'
    #     stream SSE: ok=True   tardo=9,03 s  texto entregado entero
    # Ese error literal es el que se llevo la tarea del dueno el 2026-08-26 a
    # las 12:01 ("(el agente no pudo hablar con el modelo: TimeoutError:
    # timed out)", chat_history id 1019): una tarea LARGA y sana muerta por
    # un reloj que medi lo que no debia. Es exactamente el sintoma "Cognia no
    # responde a tareas largas": las cortas caben en el presupuesto de pared
    # y las largas no.
    #
    # QUE CAMBIA. Con on_token/on_reasoning el socket se lee por frames, asi
    # que el timeout vuelve a medir SILENCIO (que es lo que dice medir) y una
    # generacion de 20 minutos que va entregando tokens no muere. Ademas
    # `cancelado` pasa a consultarse DURANTE la generacion y no solo entre
    # pasos: el Ctrl-C del carril de fondo deja de ser una promesa.
    #
    # Los callbacks son de CONTABILIDAD, no de render: no imprimen nada, asi
    # que la pantalla del CLI es la de antes. Lo que aportan es que el socket
    # se mantenga leyendo y que un corte deje de ser mudo (el aviso dice
    # cuantos tokens habian llegado ya). COGNIA_STREAM=0 vuelve al camino
    # historico.
    _stream_on = os.environ.get("COGNIA_STREAM", "1").strip().lower() not in (
        "0", "off", "false", "no")
    _vivo = {"tokens": 0, "razonamiento": 0, "chars_razon": 0,
             "chars_tool": 0}

    # VIGILANTE DEL CANAL DE RAZONAMIENTO (2026-08-31). Los cuatro detectores
    # de bucle del repo cuentan LLAMADAS; un razonador que da vueltas sin
    # llamar a nada es invisible para todos ellos. Ver harness/razonamiento.py.
    try:
        from cognia.harness import razonamiento as _rz_mod
        _vig = _rz_mod.Vigilante()
    except Exception as _e_rz:
        _rz_mod, _vig = None, None
        print_fn(f"[detail]vigilante de razonamiento no disponible "
                 f"({type(_e_rz).__name__}): sigo sin el[/detail]")

    # TOKENS EN VIVO EN MODO AGENTE (2026-08-31, pedido del dueno). El `~N tok`
    # de la linea viva se alimentaba solo de TokenTexto y RazonamientoTick, que
    # son eventos de PINTAR y el agente no emite: su texto no se pinta token a
    # token y sus tool calls no son prosa. Resultado: en /hacer el spinner
    # decia los segundos y nada mas, durante minutos. `TokensVivos` es el pulso
    # de contabilidad que separa contar de mostrar.
    #
    # SE ACUMULA Y SE EMITE POR TIEMPO, no por fragmento: un evento por token
    # son miles de pasadas por el bus para mover un numero que el ojo lee 4
    # veces por segundo.
    _PULSO_S = 0.25
    _pulso = {"chars": 0, "tokens": 0, "t": 0.0, "fase": ""}

    def _pulso_tokens(n_chars: int, fase: str, forzar: bool = False,
                      n_tokens: int = 1) -> None:
        _pulso["chars"] += max(0, int(n_chars or 0))
        # Un delta SSE de llama-server es un token: contarlos da la cifra
        # REAL, y la linea viva la pinta sin '~' (2026-09-02).
        _pulso["tokens"] += max(0, int(n_tokens or 0))
        _pulso["fase"] = fase
        _ahora = __import__("time").monotonic()
        if not forzar and _ahora - _pulso["t"] < _PULSO_S:
            return
        _pulso["t"] = _ahora
        if _pulso["chars"] and _ev is not None:
            _emitir(_ev.TokensVivos(chars=_pulso["chars"],
                                    tokens=_pulso["tokens"], fase=fase))
            _pulso["chars"] = 0
            _pulso["tokens"] = 0

    _ver_razon = {"on": False}

    def _paso_arranca() -> None:
        """El modelo va a generar: la linea viva del renderer arranca aqui
        (PasoInicio) y se alimenta con los pulsos de abajo. Antes la
        pantalla estaba muda entre el prompt y la primera tool."""
        # /pensar ver (COGNIA_PENSAR=ver) se lee UNA vez por paso, no por
        # token: en modo agente el razonamiento tambien se streamea (2026-09-02).
        _ver_razon["on"] = (os.environ.get("COGNIA_PENSAR", "").strip().lower()
                            == "ver")
        if _ev is not None:
            _emitir(_ev.PasoInicio(paso=pasos))

    def _progreso_rev(m) -> None:
        """Actividad de la revision profunda: linea viva, no transcript."""
        if _ev is not None:
            _emitir(_ev.Progreso(texto=str(m or "")))
        else:
            print_fn(f"[info_dim]{_escape_seguro(m)}[/info_dim]")

    def _suma_token(_frag):
        _vivo["tokens"] += 1
        _pulso_tokens(len(_frag or ""), "respondiendo")
        # La prosa del agente se PINTA entera y en vivo (pedido del dueno
        # 2026-09-02): el renderer la streamea como la respuesta del chat y
        # PasoIntencion deja de resumirla en una linea cortada.
        if _frag and _ev is not None:
            _emitir(_ev.TextoAgente(texto=str(_frag), paso=pasos))

    def _suma_fragmento_tool(_frag):
        """Argumentos de un tool call llegando: el UNICO latido de un paso que
        esta escribiendo un fichero (ahi no hay content ni razonamiento)."""
        _vivo["chars_tool"] += len(_frag or "")
        _pulso_tokens(len(_frag or ""), "escribiendo")

    def _suma_razonamiento(_frag):
        _vivo["razonamiento"] += 1
        _vivo["chars_razon"] += len(_frag or "")
        _pulso_tokens(len(_frag or ""), "razonando")
        # Con /pensar ver el razonamiento del agente sale en vivo como prosa
        # (mismo evento y mismo renderer que el chat). Sin ver, solo cuenta.
        if _ver_razon["on"] and _frag and _ev is not None:
            _emitir(_ev.RazonamientoTick(chars=len(_frag), fragmento=str(_frag)))
        # Aviso EN VIVO: el dueno ve que el modelo lleva 20.000 chars pensando
        # en vez de mirar un spinner mudo. Cada hito se dice una vez por paso.
        if _vig is not None:
            try:
                _av = _vig.vivo(_vivo["chars_razon"])
            except Exception:
                _av = ""
            if _av:
                print_fn(f"[warn_cl]{_av}[/warn_cl]")

    def _corte_razon_armable() -> bool:
        """¿Tiene sentido siquiera vigilar el razonamiento en este turno?

        Si el modelo no lee `enable_thinking`, o el dueno pidio el pensamiento
        encendido, o el tope esta apagado, el vigilante no puede disparar nunca
        y colgar un `cancelado` solo por tenerlo seria INVENTAR una via de
        cancelacion donde no hay ninguna -- justo lo que prohibe
        test_sin_cancelado_en_el_ctx_no_se_inventa_uno.
        """
        if _pensamiento["apagado"] or not _lleva_thinking():
            return False
        if os.environ.get("COGNIA_THINKING", "").strip().lower() in (
                "on", "1", "true", "si"):
            return False
        return _TOPE_RAZON_VIVO < 10 ** 9

    def _razonamiento_desbocado() -> bool:
        """True cuando ESTE turno se esta yendo entero en pensar.

        POR QUE CORTAR Y NO SOLO AVISAR (2026-08-31). La palanca del
        pensamiento de abajo ya sabe que apagar `enable_thinking` arregla el
        caso; el problema es CUANDO se entera: solo si el turno se CORTA
        (rampa de max_tokens o 500 del server). Un turno que piensa sin
        parar y no llega a cortarse nunca no dispara nada, y ahi la tarea no
        muere por un tope: muere por el RELOJ. Medido esta noche con el banco
        de tareas largas, encargo de 4.785 chars: 8.002 chars de razonamiento
        en el paso 1, cero tool calls, y la tarea entera consumida sin un solo
        byte escrito en disco.

        El corte es la unica intervencion barata: el stream ya lee `cancelado`
        entre frames, asi que se para en el acto en vez de esperar minutos a
        una generacion que ya se sabe esteril. El paso se repite con el
        pensamiento apagado, que es lo que este repo tiene MEDIDO que produce
        el fichero (52.535 chars pensando y cero tools con thinking on, contra
        10.160 chars de tool call con thinking off).

        General, no especifico: no mira que dice la tarea, solo la proporcion
        entre lo pensado y lo producido en el turno en curso. Con el
        pensamiento ya apagado, o en un modelo sin la palanca, es transparente.
        """
        if _pensamiento["apagado"] or not _lleva_thinking():
            return False
        if os.environ.get("COGNIA_THINKING", "").strip().lower() in (
                "on", "1", "true", "si"):
            return False
        if _vivo["chars_tool"] or _vivo["tokens"]:
            return False        # ya esta produciendo: pensar antes valio
        return _vivo["chars_razon"] >= _TOPE_RAZON_VIVO

    def _kwargs_stream() -> dict:
        """Los kwargs que encienden la rama SSE, o {} si esta apagada."""
        if not _stream_on:
            return {}
        k = {"on_token": _suma_token, "on_reasoning": _suma_razonamiento,
             "on_tool_frag": _suma_fragmento_tool}
        _cc = ctx.get("_cancelado") if isinstance(ctx, dict) else None
        _armable = _corte_razon_armable()
        if not callable(_cc) and not _armable:
            return k          # sin motivo real para cancelar, no se cuelga hook
        if not _armable:
            # Nada que anadir: el hook del ctx viaja TAL CUAL. Envolverlo por
            # envolver rompe la identidad que el llamador puede comprobar
            # (test_el_cancelado_del_ctx_viaja_a_completar) y esconde de quien
            # lee el codigo que aqui no hay ninguna politica extra.
            k["cancelado"] = _cc
            return k

        def _cancelar_turno() -> bool:
            if callable(_cc):
                try:
                    if _cc():
                        return True
                except Exception:
                    pass            # un hook roto no vuelve incancelable el turno
            if _razonamiento_desbocado():
                _corte_razon["pedido"] = True
                return True
            return False

        k["cancelado"] = _cancelar_turno
        return k

    _aviso_ventana = {"dicho": 0}

    # -- PALANCA DEL PENSAMIENTO (2026-08-30) -------------------------------
    # Un razonador al que se le pide "escribe un juego HTML completo" puede no
    # terminar de pensar NUNCA: medido, 52.535 chars de razonamiento y cero
    # tool calls con 20.000 tokens de presupuesto y el contexto vacio. La
    # misma peticion con enable_thinking=false emite el fichero con 4.000.
    # Se apaga SOLO cuando el turno ya demostro que se le va en pensar, y
    # queda apagado el resto del turno: si esta tarea hace espiralar a este
    # modelo una vez, lo va a volver a hacer, y cada descubrimiento cuesta una
    # generacion entera (~7 min con este modelo). Es el mismo argumento con el
    # que el bucle ya conserva `_piso_tokens`.
    #
    # LIMITE HONESTO: lo medido es que apagarlo arregla el paso que ESCRIBE un
    # fichero grande. No esta medido que un paso posterior de diagnostico
    # razone igual de bien sin pensamiento. Por eso hay knob: COGNIA_THINKING
    # =on lo impide, y el default solo se mueve cuando el turno se corto.
    _pensamiento = {"apagado": False}
    # Bandera que pone el hook de cancelacion cuando el turno se fue en pensar.
    _corte_razon = {"pedido": False, "veces": 0}

    # -- CONTRATO DEL ENCARGO (2026-08-31) ---------------------------------
    # La lista de lo que se pidio, viva mientras dura la tarea. Existe porque
    # el cierre de este bucle era puramente sintactico ("el modelo no pidio
    # herramientas en este turno") y por tanto un turno de prosa cerraba con
    # exito un encargo de diez sistemas del que se habian hecho dos. Ver
    # cognia/harness/contrato_tarea.py para lo que mide y lo que NO mide.
    _contrato = None
    _ids_contrato = None
    _lazo_mod = None
    try:
        from cognia.harness import lazo_corto as _lazo_mod
        if not _lazo_mod.activo():
            _lazo_mod = None
    except Exception as _e_lz0:
        _lazo_mod = None
        print_fn(f"[warn_cl]degradado: sin lazo corto "
                 f"({type(_e_lz0).__name__}: {_e_lz0})[/warn_cl]")
    try:
        from cognia.harness import contrato_tarea as _ct_mod
        _contrato = _ct_mod.Contrato(task)
        _ids_contrato = _ct_mod.identificadores(task)
        if _contrato.activo:
            print_fn(f"[detail]contrato del encargo: {len(_contrato)} "
                     f"requisitos a cubrir[/detail]")
            if _tel.activa():
                _tel.evento("contrato", requisitos=len(_contrato))
            # ARRANQUE POR HITOS (2026-09-01): con un encargo grande, el
            # metodo se dice UNA vez, como turno de usuario, antes del primer
            # paso. Va aqui y no en el system prompt porque el repo tiene
            # medido que texto extra en el system del agente baja el gate
            # (A/B 2026-07-23); esto solo aparece cuando hay >= 3 requisitos,
            # y una tarea corta no lo ve nunca.
            if os.environ.get("COGNIA_ARRANQUE_HITOS", "1").strip() not in ("0", "off"):
                mensajes.append({"role": "user",
                                 "content": _contrato.arranque_para_modelo()})
        if isinstance(ctx, dict):
            ctx["_contrato"] = _contrato
    except Exception as _e_ct:
        _ct_mod = None
        print_fn(f"[warn_cl]degradado: sin contrato del encargo "
                 f"({type(_e_ct).__name__}: {_e_ct}); el cierre vuelve a ser "
                 f"el de siempre[/warn_cl]")

    def _lleva_thinking() -> bool:
        """True si la plantilla de ESTE modelo lee enable_thinking. Sin eso la
        palanca no existe y mandarla seria fingir un control que no hay."""
        kw = perfil.get("kwargs_plantilla") or {}
        return isinstance(kw, dict) and "enable_thinking" in kw

    def _puede_apagar_pensamiento(resp, motivo: str) -> bool:
        # CUALQUIER corte en el tool call vale, no solo el de ANTES de
        # empezarlo (2026-08-31). El guard exigia CORTE_ANTES_DEL_TOOL_CALL, y
        # por eso la cara mas comun — el server devuelve HTTP 500 porque los
        # argumentos se cortaron a media cadena — se iba derecha a la rampa
        # 8192 -> 16384 -> 32768: tres generaciones enteras dandole MAS SITIO
        # PARA PENSAR a un turno que ya se habia gastado 20.000 chars
        # pensando. Subir el tope no podia curarlo; apagar el pensamiento si.
        if _pensamiento["apagado"] or not motivo:
            return False
        if not _lleva_thinking():
            return False
        if os.environ.get("COGNIA_THINKING", "").strip().lower() in (
                "on", "1", "true", "si"):
            return False               # el dueno lo pidio encendido: manda el
        # Solo si el turno se fue DE VERDAD en razonar. Sin reasoning el corte
        # es otra cosa y apagar el pensamiento no viene a cuento.
        if (getattr(resp, "reasoning_content", "") or "").strip():
            return True
        # ...y cuando el server contesta 500, `completar` vuelve SIN el
        # reasoning acumulado (solo con .error): ahi la evidencia es el
        # contador vivo del stream, que sigue siendo del MISMO paso.
        if motivo == CORTE_ANTES_DEL_TOOL_CALL:
            return False               # sin reasoning y sin haber empezado: no
        return _vivo["chars_razon"] >= _RAZON_SE_LO_COMIO

    def _apagar_pensamiento() -> None:
        kw = dict(sampling.get("kwargs_plantilla") or
                  perfil.get("kwargs_plantilla") or {})
        kw["enable_thinking"] = False
        sampling["kwargs_plantilla"] = kw
        _pensamiento["apagado"] = True

    def _sampling_ventana() -> dict:
        """`sampling` con max_tokens recortado a lo que la VENTANA deja.

        El recorte no le quita nada al modelo -- eso ya lo cortaba n_ctx -- pero
        arregla lo que el BUCLE cree: sin el, `sampling['max_tokens']` decia
        32768 mientras el server entregaba 2258, y de esa mentira salian la
        rampa inutil, el piso aprendido inflado y el aviso "no cabe ni con
        max_tokens=32768" sobre un numero que nunca se pidio de verdad.

        Nunca baja de MIN_TOKENS_RAZONADOR: con menos, un razonador no puede
        cerrar ni la frase, y mandar 200 seria pedir un fallo garantizado.
        """
        s = dict(sampling)
        _mt, _motivo = _ps.clamp(sampling["max_tokens"], perfil.get("n_ctx"),
                                 _tokens_prompt(mensajes))
        if _motivo:
            s["max_tokens"] = max(MIN_TOKENS_RAZONADOR, _mt)
            # Una vez por turno: el aviso es util, repetirlo en cada paso es
            # ruido sobre una condicion que ya se dijo.
            if not _aviso_ventana["dicho"]:
                _aviso_ventana["dicho"] = 1
                print_fn(f"[detail]{_motivo}: pido {s['max_tokens']}[/detail]")
        return s

    def _continuar_final(texto0: str):
        """Completa una RESPUESTA FINAL que el tope corto a media frase.

        La maquinaria de arriba (apagar pensamiento, compactar, rampa) cubre el
        turno que se corta ANTES o DENTRO de un tool call. Esta rama es la otra
        mitad: el modelo decidio contestar en prosa y el tope le corto la
        respuesta — y hasta hoy eso se entregaba truncado y marcado como OK,
        que es como el dueno acabo con "la tarea se corto antes de finalizar"
        cinco veces seguidas en la misma tarea.

        Se reusa agent/salida_continua tal cual: alli el tramo llega token a
        token y aqui de una pieza, pero el contrato (pedir/parada) es el mismo.
        La continuacion va SIN tools a proposito: el modelo ya eligio cerrar en
        texto, y ofrecerle herramientas a mitad de frase lo saca del cierre.

        Devuelve ``(texto, tokens_extra, tramos)``; con la puerta apagada o sin
        nada que continuar devuelve el texto igual y 0 tramos extra.
        """
        try:
            from cognia.agent import salida_continua as _sc
        except Exception as exc:                      # nunca calla
            print_fn(f"[detail]salida continua no disponible ({exc}): la "
                     f"respuesta se entrega como llego[/detail]")
            return texto0, 0, 0
        if not _sc.activa():
            return texto0, 0, 0
        _est = {"finish": "length", "tokens": 0, "tramos": 0}

        def _pedir(cola, chunk):
            if cola is None:
                return [texto0]           # el primer tramo ya esta generado
            _est["tramos"] += 1
            r = completar(_sc.continuacion_mensajes(mensajes, cola),
                          **_sampling_ventana(), **_kwargs_stream())
            _est["finish"] = r.finish_reason if r.ok else "error"
            _est["tokens"] += int((r.usage or {}).get("completion_tokens") or 0)
            return [r.texto or ""]

        rondas_max, tope_tot = _sc.limites()
        texto = "".join(_sc.stream_continuo(
            _pedir, lambda: "limit" if _est["finish"] == "length" else "fin",
            sampling["max_tokens"], rondas_max=rondas_max,
            tope_total=tope_tot))
        return texto, _est["tokens"], _est["tramos"]

    def _insistir_final():
        """El turno se cerro con SOLO razonamiento: pedir la respuesta ya.

        Es el sintoma de chat_history id 1071 (2026-08-31): el modelo gasta el
        turno pensando, cierra con content vacio y el bucle entrega el CoT
        marcado como no-cumplido. Con el corte por TOPE (no por ventana) queda
        sitio para escribir: lo que falta no son mas tokens para pensar sino
        una peticion de que escriba. Se pide una vez, sin tools, y si esa
        respuesta tambien se corta se continua con _continuar_final.

        Devuelve ``(texto, tokens_extra)``; texto vacio = no hubo rescate.
        """
        try:
            from cognia.agent import salida_continua as _sc
        except Exception as exc:                      # nunca calla
            print_fn(f"[detail]salida continua no disponible ({exc}): no se "
                     f"insiste[/detail]")
            return "", 0
        if not _sc.activa():
            return "", 0
        r = completar(_sc.continuacion_mensajes(mensajes, ""),
                      **_sampling_ventana(), **_kwargs_stream())
        _tk = int((r.usage or {}).get("completion_tokens") or 0)
        if not r.ok or not r.texto:
            return "", _tk
        _txt = r.texto
        if r.finish_reason == "length":
            _txt, _tk2, _ = _continuar_final(_txt)
            _tk += _tk2
        return _txt, _tk

    # Un transporte que NO respeta stream:true (un proxy delante, un backend
    # que no es llama-server) contesta 200 sin un solo frame SSE. chat_client
    # lo devuelve como error CON causa; aca se degrada UNA vez al camino
    # historico en vez de dar la tarea por perdida. Sin esta red, encender el
    # stream romperia a quien sirva el modelo por otra via.
    _RE_SIN_SSE = re.compile(r"(?i)sin SSE|no lo respeta|ni un frame")

    # Piso de max_tokens APRENDIDO en este turno: arranca en el del perfil y
    # solo sube cuando un paso demuestra que hacia falta (ver el reset del
    # presupuesto, mas abajo). Vive FUERA del while a proposito: es lo unico
    # que el turno averigua sobre lo que esta tarea le cuesta a este modelo, y
    # tirarlo en cada paso era pagar la misma rampa una y otra vez.
    _piso_tokens = int(sampling["max_tokens"])

    sig_counts: dict = {}
    # Herramientas ya ofrecidas en ESTA tarea: ofrecer dos veces la misma es
    # ruido, y si no la uso la primera vez es que no la queria.
    _ofertas_hechas: set = set()
    tokens_total = 0
    pasos = 0
    fail_streak = 3
    result_text, finish, ok = "", "", False
    # EL REFUND TIENE QUE DEVOLVER LA VUELTA DE VERDAD (2026-08-26).
    # Habia DOS contadores: esta guarda (`pasos`, que sube en cada vuelta y
    # NUNCA baja) y el auditado `_pres` (que si baja con cada refund). Como
    # `_pres.max_total == max_turns` y el gastado neto nunca supera a `pasos`,
    # `_pres.consume()` no podia devolver False jamas: el corte lo daba
    # SIEMPRE `pasos < max_turns`. O sea que presupuesto_turno —el modulo que
    # existe justo para que "la infraestructura no se coma el presupuesto de
    # la tarea"— movia un numero en el log y nada mas. El turno del voleibol
    # lo enseña: vueltas=5, refunds=3, pasos=2 -> habia quemado 5 de sus 8
    # vueltas para hacer 2 pasos de trabajo real.
    #
    # Ahora el corte real lo da `_pres.consume()` (ya estaba escrito unas
    # lineas mas abajo, y era codigo muerto) y esta guarda queda de FUSIBLE.
    # El fusible no sobra: los refunds no estan acotados globalmente (los de
    # formato se resetean por paso), asi que sin un techo bruto una patologia
    # que devolviera una vuelta por vuelta dejaria el bucle girando para
    # siempre. x3 es holgado para lo administrativo y sigue siendo finito.
    _techo_bruto = max_turns if _pres is None else max_turns * 3
    # PASOS ILIMITADOS (2026-09-02, pedido del dueno: "que pueda tener los
    # pasos que quiera aunque salgan de su presupuesto, y que se detenga
    # unicamente cuando el modelo piense que su trabajo esta bien"). Con
    # ctx['_pasos_ilimitados'] (config 'pasos_ilimitados', /pasos) el bucle
    # NO cierra por techo, presupuesto, gobernador de progreso, guardia de
    # bucle ni racha de fallos: esas guardas siguen AVISANDO al modelo (el
    # nudge es informacion util) pero no matan la tarea. Cierra el modelo
    # (respuesta sin tool calls), el dueno (Ctrl-C), el reloj de pared si
    # alguien lo puso (COGNIA_PARED_S) o el backend caido.
    _ilimitado = bool(ctx.get("_pasos_ilimitados")) if isinstance(ctx, dict) else False
    if _ilimitado:
        _techo_bruto = 10 ** 9
    # LA VALVULA DEL CICLO DEGENERADO (medido 2026-09-02 con el 9B y --pasos
    # 2: 60 apendices seguidos sobre c.txt, el mismo patron A-B-C repetido
    # durante 10 minutos con el aviso del guardia ignorado cada vez). Un
    # modelo asi no esta "pensando que su trabajo esta bien": esta girando.
    # Con pasos ilimitados se toleran los bloqueos del guardia y las rachas
    # de fallos, pero SEGUIDOS y sin cambiar nada, hasta este tope; despues
    # se cierra con motivo claro. Un paso sin bloqueo resetea la cuenta.
    _TOPE_BLOQUEOS_SEGUIDOS = 6
    _TOPE_REAVISOS_RACHA = 3
    _bloqueos_seguidos = [0]
    _reavisos_racha = [0]

    def _ampliar_ilimitado() -> bool:
        """Con pasos ilimitados el techo se corre solo: True si ya hay vuelta."""
        if not _ilimitado or _pres is None:
            return False
        try:
            _pres.ampliar(max(4, max_turns // 2), "pasos_ilimitados")
        except Exception:
            return False
        return _pres.consume()
    # Estado ADVERTIDO del gobernador de progreso: 0 = nunca avisado,
    # 1 = avisado y en ventana de gracia, 2 = ventana consumida (el proximo
    # veredicto de estancamiento ya cierra).
    _advertido_prog = 0
    _prog_pausado = None
    _fin_ventana_prog = 0
    _aviso_pared = {"dado": False}
    # Ficheros de usar-y-tirar escritos en la tarea (debug3.js, prueba_x.py...).
    # Ver la ESPIRAL DE DEPURACION en el hook del lazo corto.
    _sueltos = []
    _aviso_sueltos = {"dado": False}

    def _en_scratch(ruta) -> bool:
        """Un fichero de prueba en el scratchpad NO es 'suelto': ahi es donde
        el arnes le pide al modelo que pruebe (agent/scratchpad.py)."""
        _scr = ctx.get("_scratchpad") if isinstance(ctx, dict) else None
        if not _scr:
            return False
        try:
            from cognia.agent import scratchpad as _spad
            return _spad.es_del_scratch(ruta, _scr)
        except Exception:
            return False
    # Racha de tools fallidas: el primer aviso y desde que paso del trace se dio.
    _aviso_racha = {"dado": False, "desde": 0}
    while pasos < _techo_bruto:
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
        # EL RELOJ CAMBIA EL ORDEN DE LO QUE QUEDA POR HACER (2026-09-01).
        # Medido con el banco: una tarea de tablero kanban gasto sus ultimos
        # minutos escribiendo el README que DESCRIBE su contrato -- y murio por
        # reloj sin haber abierto nunca la pagina, que no exponia el objeto del
        # contrato. Quedo un producto de 30 KB con toda la documentacion y cero
        # funcionamiento. El harness sabe abrir la pagina y ejecutarla, pero esa
        # fase vive en el CIERRE y el cierre no llego.
        #
        # Con presupuesto de pared conocido se avisa UNA vez, al entrar en el
        # ultimo cuarto: deja de producir y comprueba lo que ya hay. No corta
        # nada ni prohibe nada -- reordena. Sin COGNIA_PARED_S es transparente.
        if (not _aviso_pared["dado"] and _muta is not None
                and _muta.ficheros_escritos()):
            _tot_pared = _pared_total()
            _resto_pared = _pared_restante(t0)
            if (_tot_pared and _resto_pared is not None
                    and _resto_pared <= max(_PARED_MINIMA_TRABAJO, 0.25 * _tot_pared)):
                _aviso_pared["dado"] = True
                _n_fich = len(_muta.ficheros_escritos())
                print_fn(f"[warn_cl]quedan {int(_resto_pared)}s de "
                         f"presupuesto: pido comprobar lo hecho antes de "
                         f"seguir produciendo[/warn_cl]")
                if _tel.activa():
                    _tel.evento("aviso_pared", paso=pasos,
                                restante=int(_resto_pared), ficheros=_n_fich)
                mensajes.append({"role": "user", "content": (
                    "AVISO DE TIEMPO: quedan unos %d segundos de presupuesto y "
                    "ya hay %d fichero(s) escritos. Deja de producir material "
                    "nuevo (nada de documentacion, nada de ficheros extra) y "
                    "dedica lo que queda a COMPROBAR lo que ya existe: "
                    "ejecutalo o abrelo, mira el error real y arregla lo que "
                    "impida que funcione lo principal. Si algo no se puede "
                    "comprobar, dilo en una linea en vez de darlo por bueno."
                    % (int(_resto_pared), _n_fich))})
        if _prog is not None:
            _v = _prog.veredicto()
            if _v.get("estado") == "estancado":
                # LA SUGERENCIA SE ENVIA ANTES DE MATAR (2026-08-31).
                #
                # Hasta hoy este bloque appendeaba la sugerencia a `mensajes`
                # y hacia `break` en la linea siguiente: el texto nunca salia
                # en una llamada al modelo. `_SUGERENCIAS` (presupuesto_progreso
                # .py:178-207) esta escrito PARA EL MODELO -- le dice como salir
                # del estancamiento -- y el modelo no lo leyo jamas. El
                # `_prog = None  # una sola vez por tarea` prometia una segunda
                # oportunidad que el break hacia inalcanzable.
                #
                # Ahora hay un estado ADVERTIDO con ventana propia: la primera
                # vez se manda la sugerencia y se le da al modelo una ventana
                # exenta para cambiar de tactica; el gobernador se apaga durante
                # esa ventana (no durante la tarea) y vuelve a mirar al salir.
                # Si al volver sigue estancado, ahi si se cierra.
                #
                # POR QUE ES GENERAL, no un parche para tareas grandes: un corte
                # que no da la oportunidad que su propio texto anuncia es un
                # falso positivo en CUALQUIER tarea; solo que en una corta el
                # coste es un turno y en una larga es el trabajo entero. La
                # ventana escala con el presupuesto por el mismo motivo por el
                # que ya escala umbral_arranque (ver la construccion del
                # Progreso): un numero fijo significa cosas distintas segun el
                # tamano de la tarea.
                if _advertido_prog == 0:
                    _advertido_prog = 1
                    _ventana_prog = max(3, max_turns // 4)
                    _fin_ventana_prog = pasos + _ventana_prog
                    mensajes.append({"role": "user",
                                     "content": _v.get("sugerencia") or ""})
                    print_fn(f"[warn_cl]sin progreso verificado "
                             f"({_v.get('motivo')}): te doy {_ventana_prog} "
                             f"pasos para cambiar de tactica[/warn_cl]")
                    if _tel.activa():
                        _tel.evento("advertencia_progreso", motivo=str(_v.get("motivo")),
                                    paso=pasos, ventana=_ventana_prog)
                    _prog_pausado = _prog
                    _prog = None      # el gobernador calla DURANTE la ventana
                elif _ilimitado or ((_pared_restante(t0) is None
                       or _pared_restante(t0) > 0.25 * (_pared_total() or 0))
                      and _advertido_prog < 4):
                    # Sin reloj externo (REPL, `cognia hacer` a secas) el
                    # reloj es el humano con su Ctrl-C: tambien ahi se avisa
                    # hasta cuatro veces antes de cerrar. Matar una tarea que
                    # el dueno esta mirando "por estancamiento" era justo la
                    # queja: el harness no termina lo que se le pide.
                    # CON RELOJ CONOCIDO, EL GOBERNADOR AVISA, NO MATA
                    # (2026-09-01). El gobernador de progreso nacio porque no
                    # habia reloj de pared: era la unica forma de que un bucle
                    # esteril no girase para siempre. Con COGNIA_PARED_S ya hay
                    # limite duro. Medido en el A/B de 20 min: la version
                    # publicada cerro el juego por "estancado_sin_progreso" a
                    # los 581 s con diez minutos de reloj sin usar, en mitad de
                    # un ciclo de arreglos sobre el mismo fichero (que no
                    # "avanza" para el gobernador porque no crea ficheros ni
                    # pone tests en verde). Mientras quede mas de un cuarto del
                    # reloj se le vuelve a mandar la sugerencia con ventana
                    # nueva; solo se cierra en el ultimo cuarto o tras cuatro
                    # avisos, que ya es girar en vacio.
                    _advertido_prog += 1
                    _ventana_prog = max(3, max_turns // 4)
                    _fin_ventana_prog = pasos + _ventana_prog
                    mensajes.append({"role": "user",
                                     "content": _v.get("sugerencia") or ""})
                    print_fn(f"[warn_cl]sin progreso verificado "
                             f"({_v.get('motivo')}), aviso {_advertido_prog}: "
                             + ("pasos ilimitados, sigo" if _ilimitado else
                                f"queda reloj, sigo {_ventana_prog} pasos mas")
                             + "[/warn_cl]")
                    if _tel.activa():
                        _tel.evento("advertencia_progreso", motivo=str(_v.get("motivo")),
                                    paso=pasos, ventana=_ventana_prog,
                                    aviso=_advertido_prog)
                    _prog_pausado = _prog
                    _prog = None
                else:
                    if _salida is not None:
                        _salida.sellar("estancado_sin_progreso", _v.get("motivo", ""))
                    result_text = result_text or (
                        "(cerrada sin progreso verificado: " + str(_v.get("motivo")) + ")")
                    _prog = None
                    break
        elif _prog_pausado is not None and pasos >= _fin_ventana_prog:
            # Fin de la ventana de gracia: el gobernador vuelve. Si en esos
            # pasos hubo un avance verificado, su propio contador ya lo sabe y
            # el veredicto sale 'avanza'; si no, la proxima vuelta cierra.
            _prog = _prog_pausado
            _prog_pausado = None
            _advertido_prog = 2
        if _pres is not None and not _pres.consume() and not _ampliar_ilimitado():
            # AMPLIACION GANADA CON EVIDENCIA (2026-08-30). El presupuesto de
            # pasos es un PRIOR sacado del texto de la tarea, y el texto no
            # sabe cuanto trabajo hay: "arregla el juego" son 267 caracteres,
            # dificultad 0,351 -> 8 pasos, y el fichero a arreglar tenia 32 KB.
            # Ninguna heuristica sobre el enunciado puede acertar eso.
            #
            # Asi que el techo deja de ser solo un prior: se AMPLIA cuando el
            # gobernador de progreso dice que la corrida avanza de verdad
            # (>=1 avance verificado y ninguno de los cortes por estancamiento
            # disparado). No se puede pedir ni declarar -- se gana con
            # evidencia observada, y la ampliacion muere en cuanto el progreso
            # se para, porque entonces corta la guarda de arriba. Techo duro
            # AGENT_CAP_CON_PROGRESO para que siga siendo finito.
            _ampliado = False
            # QUINTO CORTE, encontrado CORRIENDO (2026-08-30). Con los cuatro
            # arreglos de lectura la misma tarea ya no muere por
            # 'sin_arranque'... y muere por el techo de 8 pasos igual, porque
            # la ampliacion exigia un avance verificado y una tarea cuyo
            # objeto es un fichero de 32 KB gasta sus primeros pasos LEYENDO.
            # Medido: brazo A del A/B, 119 s, 8 pasos, 0 bytes escritos,
            # '(presupuesto de 8 pasos agotado sin cierre)'.
            #
            # Asi que se concede UNA ampliacion antes del primer avance, y
            # solo mientras el gobernador diga que la corrida esta sana. No es
            # barra libre: el credito de exploracion es finito, asi que una
            # corrida que solo lee acaba en 'sin_arranque' y deja de ampliar.
            # A partir del primer avance, las ampliaciones las paga la
            # evidencia.
            _puede_ampliar = bool(_prog is not None
                                  and (_prog.avances or _ext_sin_avance < 1))
            if (_prog is not None and _largas and _puede_ampliar
                    and _pres.max_total < AGENT_CAP_CON_PROGRESO):
                _vv = _prog.veredicto()
                if _vv.get("estado") == "avanza":
                    if not _prog.avances:
                        _ext_sin_avance += 1
                    _extra = min(max(4, max_turns // 2),
                                 AGENT_CAP_CON_PROGRESO - _pres.max_total)
                    # El motivo NO miente: una ampliacion sin avances no es
                    # "progreso verificado", es margen de arranque.
                    _techo_nuevo = _pres.ampliar(
                        _extra, "progreso_verificado" if _prog.avances
                        else "arranque_sano")
                    _techo_bruto = _techo_nuevo * 3
                    _porque = (f"{len(_prog.avances)} avances verificados "
                               f"(ultimo: {_prog.avances[-1]['detalle'][:60]})"
                               if _prog.avances else
                               "la corrida sigue sana y aun no ha podido "
                               "producir su primer avance (una vez)")
                    print_fn(f"[detail]presupuesto ampliado a {_techo_nuevo} "
                             f"pasos: {_porque}[/detail]")
                    # Se cobra AQUI la vuelta que el consume() de la guarda no
                    # pudo cobrar; no se hace `continue` a proposito, porque
                    # volver al principio del while cobraria una segunda.
                    _ampliado = _pres.consume()
            if not _ampliado:
                # ESTE es el corte por presupuesto desde el 2026-08-26: el
                # techo auditado, con los refunds descontados (que es toda la
                # diferencia). Antes era codigo muerto -- `pasos < max_turns`
                # cortaba siempre primero -- y por eso el refund no devolvia
                # nada. Cierra con la EVIDENCIA del history, igual que el
                # while/else de abajo: sin esto, mover el corte a esta rama se
                # llevaba por delante el ultimo RESULTADO y la tarea acababa
                # en un parentesis vacio.
                _techo_final = _pres.max_total
                _salida.sellar(RAZON_PRESUPUESTO_AGOTADO, f"techo {_techo_final}")
                _ultimo = next((h for h in reversed(history)
                                if h.startswith("RESULTADO ")), "")
                result_text = result_text or (
                    f"(presupuesto de {_techo_final} pasos agotado sin cierre) "
                    + _ultimo[:300])
                break
        pasos += 1
        if _especular and _espec is not None:
            # El hilo corre DURANTE completar(): la pared que se ahorra es la
            # del modelo pensando, no la de la tool.
            try:
                _acc = _espec.predecir({"historial": trace}, k=2)
                _cache_espec = (_espec.ejecutar_especulativo(
                    _acc, lambda n, a: run_tool(n, a, ctx), ctx) if _acc else None)
            except Exception:
                _cache_espec = None
        # VALVULA ANTES DE LLAMAR (2026-08-30). La compactacion de este bucle
        # vive al FINAL de la vuelta y se alimenta del usage de la respuesta,
        # asi que en el camino del corte no llegaba a correr NUNCA: el paso
        # se cortaba, la rampa lo repetia, el 500 salia por la rama de error y
        # el turno moria con la ventana al 96% sin que nadie hubiera liberado
        # un byte. Aqui se mira ANTES: si lo que queda de ventana no da ni
        # para que el turno cierre algo (MINIMO_UTIL), se compacta primero.
        #
        # No es una optimizacion: es la diferencia entre gastar una generacion
        # entera (~6 min con este modelo) en un turno que ya se sabe que no
        # puede terminar, y gastarla en uno que si.
        if not _ps.hay_sitio_para_trabajar(perfil.get("n_ctx"),
                                           _tokens_prompt(mensajes)):
            _cabe = _ps.disponible(perfil.get("n_ctx"), _tokens_prompt(mensajes))
            _lib = (_compactar_por_resumen(mensajes, perfil.get("n_ctx"),
                                           10 ** 9, _estado, print_fn)
                    or _recortar_mensajes(mensajes, perfil.get("n_ctx"), 10 ** 9))
            if _lib:
                print_fn(f"[warn_cl]la ventana solo dejaba {_cabe} tokens de "
                         f"salida (hacen falta {_ps.MINIMO_UTIL}): compacto "
                         f"{_lib} chars ANTES de llamar[/warn_cl]")
            else:
                # Sin nada que liberar se llama igual: puede que el modelo
                # cierre con una respuesta corta. Lo que no se hace es callar.
                print_fn(f"[warn_cl]la ventana solo deja {_cabe} tokens de "
                         f"salida y no hay nada compactable: este paso puede "
                         f"no cerrar[/warn_cl]")
        # El razonamiento se cuenta POR PASO (reintentos de ese paso incluidos:
        # repetir la generacion es mas pensamiento sobre el mismo problema).
        _vivo["chars_razon"] = 0
        _vivo["chars_tool"] = 0
        _pulso["chars"] = 0
        if _vig is not None:
            try:
                _vig.nuevo_turno()
            except Exception:
                pass
        _av_antes = len(_prog.avances) if _prog is not None else 0
        _t_paso = __import__("time").time()
        _paso_arranca()
        resp = completar(mensajes, tools=schemas, **_sampling_ventana(),
                         **_kwargs_stream())
        tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)
        _tel_turno(resp, pasos, __import__("time").time() - _t_paso,
                   len(getattr(resp, "tool_calls", None) or []))
        if _corte_razon["pedido"]:
            # El turno se corto POR PENSAR de mas, no por el usuario ni por el
            # tope. Se apaga el pensamiento y se repite el MISMO paso: la
            # vuelta se devuelve al presupuesto porque no gasto trabajo util,
            # que es exactamente el caso para el que existe el refund.
            _corte_razon["pedido"] = False
            _corte_razon["veces"] += 1
            _apagar_pensamiento()
            print_fn(f"[warn_cl]el paso {pasos} llevaba "
                     f"{_vivo['chars_razon']} chars pensando sin producir "
                     f"nada: corto y lo repito con el pensamiento apagado"
                     f"[/warn_cl]")
            if _tel.activa():
                _tel.evento("corte", motivo="razonamiento_desbocado",
                            paso=pasos, chars_razon=_vivo["chars_razon"])
            if _pres is not None:
                try:
                    _pres.refund("razonamiento_desbocado")
                except Exception:
                    pass
            continue
        if _prog is not None:
            try:
                _u = resp.usage or {}
                # SOLO LOS TOKENS GENERADOS cuentan como coste del progreso
                # (2026-09-01). Antes sumaba prompt+completion, y el prompt de
                # una tarea larga son 30-40k tokens POR PASO: el "coste desde
                # el ultimo avance" crecia 35k por vuelta hiciera lo que
                # hiciera el modelo, y la regla de meseta_de_coste (5x la
                # mediana, calibrada con los primeros avances baratos, de
                # prompt corto) disparaba por construccion cuanto mas larga
                # era la tarea. Medido en el repro del juego: 57 pasos, 1,96 M
                # tokens contados, cerrada por meseta_de_coste con 143 s de
                # reloj sin usar. El prompt es el precio de RECORDAR, no de
                # trabajar: el esfuerzo desde el ultimo avance es lo generado.
                _prog.gastar(tokens=int(_u.get("completion_tokens") or 0),
                             segundos=__import__("time").time() - _t_paso,
                             pasos=1)
            except Exception:
                pass

        # El cupo se renueva en CADA paso. Era global de la tarea, asi que un
        # paso que gastara los dos reintentos dejaba a todos los siguientes sin
        # rampa: el segundo fichero largo moria sin un solo reintento.
        _reintentos_corte = 0

        # ¿Se corto el turno mientras emitia un tool call? Entonces el problema
        # es el PRESUPUESTO, no el modelo: se sube y se repite el mismo turno.
        #
        # ...PERO HAY DOS PRESUPUESTOS, y solo uno se sube (2026-08-30). El
        # turno se corta o porque se agoto el max_tokens que se pidio, o porque
        # se lleno la VENTANA (n_ctx). Los dos llegan como finish_reason
        # 'length' y son indistinguibles a simple vista, pero piden acciones
        # OPUESTAS: el primero se cura subiendo el tope; el segundo NO se cura
        # con eso ni en el mejor de los casos, porque el server corta en n_ctx
        # y el tope ya no manda.
        #
        # MEDIDO contra el llama-server del dueno (Qwen3.8-27B, n_ctx=65536):
        # con un prompt de 63.277 tokens y max_tokens=32768 llegaron 2258
        # tokens y total_tokens=65535, o sea n_ctx MENOS UNO. Subir el tope de
        # 8192 a 16384 a 32768 en ese estado regenera el mismo razonamiento y
        # muere en la misma columna: son dos generaciones enteras (~6 min con
        # este modelo) tiradas por vuelta. Asi murio la tarea del Minecraft:
        # 8 vueltas, 7 refunds, 48 minutos, cero ficheros.
        #
        # Cuando el corte es de VENTANA lo unico que ayuda es liberar
        # contexto, asi que eso es lo que se hace: compactar y repetir. Y si
        # no se libero nada, se sale del bucle sin gastar la vuelta.
        # Ultimo pulso del paso: lo que quedo sin emitir por el throttle (el
        # tramo final es justo el que cierra el fichero, y sin este flush el
        # contador se quedaba corto en cada paso).
        _pulso_tokens(0, _pulso.get("fase") or "respondiendo", forzar=True)
        _motivo_corte = _corte_en_tool_call(resp, schemas)
        # EL RESCATE VA ANTES QUE EL REINTENTO (2026-08-30). Si el turno
        # cortado trae dentro un fichero rescatable, repetir el paso TIRA esos
        # bytes para volver a jugarselos. Se deja pasar al camino del rescate,
        # que los escribe y hace que el turno siguiente continue en vez de
        # reempezar. El reintento sigue mandando cuando no hay nada dentro (el
        # 500 del server, el corte antes de emitir la llamada).
        if _motivo_corte and _hay_parcial_rescatable(resp):
            _motivo_corte = ""
        while (_motivo_corte and _reintentos_corte < _MAX_REINTENTOS_CORTE):
            _por_ventana = _ps.es_corte_por_contexto(
                resp.usage, perfil.get("n_ctx"))
            if _puede_apagar_pensamiento(resp, _motivo_corte):
                # LA PRIMERA INTERVENCION ES APAGAR EL PENSAMIENTO, no subir
                # ningun tope (2026-08-30). Cuando el corte cae ANTES de que
                # el tool call empiece, el presupuesto no se lo comio el
                # fichero: se lo comio el razonamiento, y darle mas tokens es
                # darle mas sitio para seguir pensando.
                #
                # MEDIDO contra el server del dueno con la MISMA peticion
                # ("escribe un juego HTML completo") y un prompt de 369
                # tokens, o sea SIN ninguna presion de contexto:
                #
                #   thinking ON,  max_tokens 20000 -> 52.535 chars de
                #                 razonamiento y CERO tool calls
                #   enable_thinking=false, max_tokens 4000 -> 0 chars de
                #                 razonamiento y 10.160 chars de tool call
                #   reasoning_effort=low,  max_tokens 4000 -> 821 chars de
                #                 razonamiento y 9.965 chars de tool call
                #
                # O sea: con el pensamiento encendido el modelo NO TERMINA de
                # pensar ni con cinco veces el presupuesto, y con el apagado
                # escribe el fichero con la quinta parte. Por eso la rampa de
                # max_tokens no podia funcionar nunca en este caso: subia lo
                # que no faltaba.
                # Va ANTES de la rama de la VENTANA a proposito: apagar el
                # pensamiento es una intervencion de efecto medido y coste
                # cero, y solo se hace UNA vez por tarea. Si el corte era de
                # verdad de ventana, la vuelta siguiente ya cae en compactar.
                _apagar_pensamiento()
                _donde = ("sin llegar a llamar la herramienta"
                          if _motivo_corte == CORTE_ANTES_DEL_TOOL_CALL
                          else f"y la herramienta salio cortada a medias "
                               f"({_vivo['chars_razon']} chars pensando)")
                print_fn(f"[warn_cl]el turno se fue en razonar {_donde}: "
                         f"repito el paso con el pensamiento APAGADO "
                         f"(COGNIA_THINKING=on lo impide)[/warn_cl]")
            elif _por_ventana:
                _liberados = (_compactar_por_resumen(
                    mensajes, perfil.get("n_ctx"), 10 ** 9, _estado, print_fn)
                    or _recortar_mensajes(mensajes, perfil.get("n_ctx"), 10 ** 9))
                if not _liberados:
                    print_fn("[warn_cl]el turno se corto porque la VENTANA de "
                             f"{perfil.get('n_ctx')} tokens esta llena y no "
                             "queda nada que compactar: subir max_tokens no "
                             "cambiaria nada[/warn_cl]")
                    break
                print_fn(f"[warn_cl]{_motivo_corte}, pero por la VENTANA "
                         f"(no por max_tokens): libero {_liberados} chars de "
                         f"contexto y repito[/warn_cl]")
            elif sampling["max_tokens"] < _TECHO_REINTENTO:
                _antes = sampling["max_tokens"]
                sampling["max_tokens"] = min(_TECHO_REINTENTO,
                                             max(2048, _antes * 2))
                print_fn(f"[warn_cl]{_motivo_corte}: repito el paso con "
                         f"max_tokens {_antes} -> {sampling['max_tokens']}"
                         f"[/warn_cl]")
            else:
                break                       # ni ventana ni rampa: no hay que subir
            _reintentos_corte += 1
            if _pres is not None:
                # Repetir el MISMO paso con mas presupuesto no es razonamiento
                # nuevo: es administracion. Sin el refund, un fichero largo se
                # comia dos vueltas de la tarea (conversation_loop.py:1996).
                _pres.refund(MOTIVO_REINTENTO_FORMATO)
            _paso_arranca()
            resp = completar(mensajes, tools=schemas, **_sampling_ventana(),
                             **_kwargs_stream())
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
                # "la primera mitad" era el consejo equivocado y por eso el
                # aviso salia cuatro veces seguidas: la mitad de un fichero
                # que no cabe TAMPOCO cabe. El numero tiene que ser chico y
                # absoluto, no relativo a lo que fallo. Y el presupuesto real
                # se le dice, porque es el dato que el modelo no tiene y que
                # decide cuanto puede escribir de una vez.
                "content": ("AVISO DEL SISTEMA: tu ultima llamada a una "
                            "herramienta se corto porque el contenido era "
                            "demasiado largo para un solo mensaje. En este "
                            f"turno te caben ~{_ps.disponible(perfil.get('n_ctx'), _tokens_prompt(mensajes))} "
                            "tokens de salida, y en ellos entra tambien tu "
                            "razonamiento: PIENSA POCO Y ESCRIBE YA. Manda el "
                            "fichero POR PARTES, en TROZOS DE COMO MUCHO 100 LINEAS: "
                            "escribir_archivo con el primer trozo y luego un "
                            "apendar_archivo por cada trozo siguiente. No "
                            "repitas la llamada entera ni intentes la mitad "
                            "del fichero: no cabe."),
            })
            _paso_arranca()
            resp = completar(mensajes, tools=schemas, **_sampling_ventana(),
                             **_kwargs_stream())
            tokens_total += int((resp.usage or {}).get("completion_tokens") or 0)

        # EL PISO APRENDIDO NO SE OLVIDA (2026-08-26). Antes el presupuesto
        # volvia SIEMPRE al del perfil ("la subida era para ESTE paso"), y eso
        # tiraba lo unico que el turno habia averiguado: que a este modelo,
        # con esta tarea, 4096 no le alcanzan. Cada paso volvia a empezar en
        # 4096, se volvia a cortar y se volvia a pagar la rampa.
        #
        # MEDIDO en la corrida real del videojuego (2026-08-26, 28,2 min):
        # "el turno se corto por max_tokens antes de emitir el tool call:
        # repito el paso con max_tokens 4096 -> 8192" sale CUATRO veces en el
        # mismo turno. Cada una son dos llamadas al modelo tiradas, y ninguna
        # deja un avance verificado: la tarea acabo cerrando por
        # 'sin_arranque' sin haber escrito un solo fichero.
        #
        # Solo se conserva el nivel que FUNCIONO: si tras la rampa el turno
        # sigue cortado, no se aprende nada (subirlo mas no era la solucion,
        # por eso existe el aviso de "escribelo por partes"). Y max_tokens es
        # un TOPE, no una reserva: un piso alto no cuesta tokens si el modelo
        # termina antes, solo alarga el peor caso.
        if _reintentos_corte and not _corte_en_tool_call(resp, schemas):
            _piso_tokens = max(_piso_tokens, int(sampling["max_tokens"]))
            print_fn(f"[detail]presupuesto de salida aprendido para el resto "
                     f"del turno: {_piso_tokens} tokens[/detail]")
        sampling["max_tokens"] = _piso_tokens
        # FOOTER de contexto (barra_estado): tokens reales del turno y
        # ocupacion de la ventana (la refina el hook post-compactacion).
        _anotar_uso_vivo(resp, perfil.get("n_ctx"), mensajes, print_fn)

        if (not resp.ok and _corte_en_tool_call(resp, schemas)
                and _hay_parcial_rescatable(resp)):
            # RESCATAR ANTES DE RENDIRSE (2026-09-01). El 500 "Failed to parse
            # tool call arguments as JSON" llega con el fichero a medio escribir
            # DENTRO de la peticion, y hasta hoy se cerraba el turno tirandolo:
            # el rescate existia (`_rescatar_escritura`) pero solo miraba
            # `resp.tool_calls`, que en este camino viene vacia. Se escriben las
            # partes que estan completas y el turno SIGUE: el modelo continua
            # desde lo que ya hay en disco en vez de reempezar el fichero.
            _rescatados = []
            for _tc_p in _tool_calls_con_parciales(resp):
                if not getattr(_tc_p, "argumentos_rotos", False):
                    continue
                if getattr(_tc_p, "nombre", "") not in _TOOLS_ESCRITURA:
                    continue
                if getattr(_tc_p, "nombre", "") == "editar_archivo":
                    continue
                _crudo_p = getattr(_tc_p, "argumentos_crudos", "") or ""
                try:
                    _res_p = _rescatar_escritura(_tc_p, _crudo_p, ctx,
                                                 run_tool, print_fn)
                except Exception as _e_rp:
                    _res_p = None
                    print_fn(f"[warn_cl]rescate parcial fallido: "
                             f"{type(_e_rp).__name__}: {_e_rp}[/warn_cl]")
                if _res_p:
                    _rescatados.append(str(_res_p)[:200])
            if _tel.activa():
                _tel.evento("rescate", motivo="tool_call_cortado_500",
                            paso=pasos, rescatados=len(_rescatados))
            if _rescatados:
                print_fn(f"[ok_cl]rescatados {len(_rescatados)} fichero(s) del "
                         f"turno cortado: sigo desde ahi en vez de "
                         f"reempezar[/ok_cl]")
                _lista_resc = "\n- ".join(_rescatados)
                mensajes.append({"role": "user", "content":
                                 "La llamada anterior se corto a media cadena, "
                                 "pero el arnes rescato y ESCRIBIO en disco lo "
                                 "que ya habias generado:\n- " + _lista_resc
                                 + "\n\nNo reempieces esos ficheros: leelos si "
                                   "hace falta y continua por donde ibas, "
                                   "escribiendo en trozos mas cortos."})
                continue
        if (not resp.ok and _corte_en_tool_call(resp, schemas)
                and not _hay_parcial_rescatable(resp)):
            # UN TOOL CALL CORTADO NO ES UN BACKEND CAIDO (2026-08-30).
            # llama-server devuelve HTTP 500 "Failed to parse tool call
            # arguments as JSON ... missing closing quote" cuando la
            # generacion muere a media cadena. Ese 500 caia en la rama de
            # abajo, Hermes lo clasificaba como 'desconocido', se reintentaba
            # DOS veces la misma peticion (mismo error, tres generaciones
            # pagadas) y el turno cerraba con razon=error_backend. Ese es
            # literalmente el final de la corrida del dueno del 2026-08-30:
            # "Agente (nativo): HTTP 500 ..." y ni una linea de salida final.
            #
            # El sintoma es del PRESUPUESTO y ya tiene dueno mas arriba (la
            # rampa, la ventana, el pensamiento). Si se llego hasta aqui es
            # que todo eso se agoto: se cierra HONESTO y con lo que haya en el
            # workspace, en vez de acusar al backend de algo que no hizo.
            _pendiente = next((h for h in reversed(history)
                               if h.startswith("RESULTADO ")), "")
            print_fn("[warn_cl]el modelo no consiguio emitir la llamada "
                     "entera ni por partes: cierro con lo que si quedo "
                     "escrito[/warn_cl]")
            if _salida is not None:
                _salida.sellar(RAZON_ERROR_BACKEND, "tool call cortado sin salida")
            result_text = (
                "(el modelo no logro emitir el fichero completo: la llamada a "
                "la herramienta se corto a media cadena y el presupuesto de "
                "esta ventana ya estaba agotado. Lo que SI quedo hecho:"
                + ("\n\n" + _pendiente[:400] if _pendiente
                   else " nada todavia.")
                + "\n\nSugerencia: pideselo por partes explicitamente ('escribe "
                  "primero el HTML y el CSS, luego el JS en otro fichero'), o "
                  "arranca el backend con mas ventana.)")
            break

        if not resp.ok:
            # RED DEL STREAM (2026-08-26). Un transporte que no respeta
            # stream:true contesta 200 sin un solo frame SSE. Eso NO es un
            # backend caido y no se arregla reintentando igual: se apaga el
            # stream para el RESTO del turno y se repite el paso por el
            # camino historico. Una sola vez, y con refund para no cobrarle
            # a la tarea una vuelta administrativa.
            if _stream_on and _RE_SIN_SSE.search(resp.error or ""):
                _stream_on = False
                print_fn("[warn_cl]el server no respeta stream:true: sigo "
                         "por el camino no-stream (COGNIA_STREAM=0 lo "
                         "fija)[/warn_cl]")
                if _pres is not None:
                    _pres.refund(MOTIVO_REINTENTO_RED)
                continue
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
                        # F4: primero la compactacion por resumen (una sola
                        # pasada); None o 0 -> el truncado de siempre.
                        _liberados = _compactar_por_resumen(
                            mensajes, perfil.get("n_ctx"), 10 ** 9,
                            _estado, print_fn) or 0
                        if not _liberados:
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
            # NO TIRAR LO YA GENERADO (2026-08-26). Con la rama SSE, un
            # socket que muere a mitad vuelve con `error` Y con lo acumulado
            # hasta ahi (contrato de completar()). Perderlo era el peor caso
            # de una tarea larga: veinte minutos de generacion tirados porque
            # el ultimo tramo no llego. Se entrega marcado y con ok=False --
            # no es una respuesta terminada y nadie debe tomarla por tal.
            _parcial = (resp.texto or "").strip()
            _ya = ""
            if _vivo["tokens"] or _vivo["razonamiento"]:
                _ya = (f" [habian llegado {_vivo['tokens']} fragmentos de "
                       f"respuesta y {_vivo['razonamiento']} de razonamiento]")
            _cabecera = f"(el agente no pudo hablar con el modelo: {resp.error}{_ya})"
            if _parcial:
                print_fn(f"[warn_cl]el corte llego a mitad de la respuesta: "
                         f"entrego los {len(_parcial)} caracteres que si "
                         f"salieron[/warn_cl]")
                result_text = (_cabecera + "\n\nLo que alcanzo a generar "
                               "antes del corte:\n\n" + _parcial)
            else:
                result_text = _cabecera
            break

        # RACHA, NO CUPO DE POR VIDA (2026-08-26). Llegar aca es `resp.ok`, o
        # sea que el backend contesto bien: la racha de fallos transitorios se
        # termino y el contador vuelve a cero. Antes se inicializaba UNA vez
        # fuera del while y nunca bajaba, asi que los 2 reintentos eran POR
        # TAREA: en una tarea de media hora, tres timeouts sueltos separados
        # por trabajo exitoso la mataban igual que tres seguidos. Dos fallos
        # SEGUIDOS si son senal de que el backend esta mal; dos baches en
        # veinte minutos no lo son. (El otro contador de reintentos del bucle,
        # _MAX_REINTENTOS_CORTE, ya era por paso por este mismo motivo.)
        _reint_backend = 0

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
                if finish == "length":
                    # El tope corto la respuesta final a media frase: se
                    # continua en vez de entregarla truncada.
                    _antes = len(result_text)
                    result_text, _tk_cont, _tramos_cont = \
                        _continuar_final(result_text)
                    tokens_total += _tk_cont
                    if _tramos_cont:
                        print_fn(f"[detail]la respuesta se corto por el tope: "
                                 f"la completo en {_tramos_cont} tramo(s) mas "
                                 f"({_antes} -> {len(result_text)} chars)"
                                 f"[/detail]")
            elif resp.reasoning_content:
                # ANTES DE RENDIRSE: si el corte lo dio el TOPE y no la
                # VENTANA, no falta sitio para pensar — falta que escriba. Se
                # le pide la respuesta una vez. Con la ventana llena no se
                # insiste: ahi lo unico que ayuda es liberar contexto, y
                # gastar otra generacion entera para comprobarlo es justo la
                # rampa inutil que este fichero ya documenta.
                _rescate, _tk_ins = "", 0
                if (finish == "length" and not _ps.es_corte_por_contexto(
                        resp.usage, perfil.get("n_ctx"))):
                    print_fn("[warn_cl]el turno se fue entero en razonar sin "
                             "escribir la respuesta: se la pido "
                             "directamente[/warn_cl]")
                    _rescate, _tk_ins = _insistir_final()
                    tokens_total += _tk_ins
                if _rescate:
                    result_text, ok = _rescate, True
                    print_fn(f"[detail]respondio al insistir "
                             f"({len(_rescate)} chars)[/detail]")
                else:
                    # Rescate: el pensamiento SI existe; se entrega marcado y
                    # con ok=False (no lo pidio nadie asi, no es una
                    # respuesta). La COLA del CoT es donde vive la conclusion,
                    # no la cabeza.
                    print_fn("[warn_cl]el modelo cerro con la respuesta vacia "
                             "(solo razonamiento): se entrega el razonamiento "
                             "sin marcar la tarea como cumplida[/warn_cl]")
                    cola = resp.reasoning_content.strip()[-1200:]
                    result_text = ("(el modelo no emitio respuesta final; esto "
                                   "es su razonamiento) " + cola)
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
            # COMPUERTA DE COMPLETITUD (2026-08-31). La primera pregunta no es
            # "¿lo que hiciste corre?" sino "¿HICISTE lo que te pidieron?".
            # Esta compuerta la hace: si el encargo enumeraba requisitos y de
            # varios no hay ni rastro en lo que se produjo, el turno NO cierra;
            # se le devuelve al modelo la lista literal de lo que falta y sigue
            # trabajando.
            #
            # DOS DIFERENCIAS DELIBERADAS con las dos compuertas de abajo:
            #  1. NO exige `_muta.ficheros_escritos()`. Ese registro conoce
            #     cinco nombres de tool, asi que un producto escrito por
            #     generar_codigo, por copiar_archivo o por un sub-agente lo
            #     deja vacio y apaga las dos compuertas de golpe. La evidencia
            #     de esta sale del DISCO: da igual quien lo escribiera.
            #  2. El tope de insistencias escala con lo que falta (2 a 6).
            #     Retener una sola vez un encargo de doce puntos no sirve.
            #
            # Lo que mide es cobertura lexica, no funcionamiento, y por eso
            # solo puede RETENER un cierre, nunca declarar un exito.
            if ok and _contrato is not None and _contrato.activo and _ct_mod:
                try:
                    _contrato.actualizar(
                        _ct_mod.evidencia_de_disco(os.getcwd(), t0))
                except Exception as _e_cev:
                    print_fn(f"[warn_cl]contrato: no pude leer la evidencia "
                             f"del disco ({type(_e_cev).__name__}); no retengo "
                             f"el cierre[/warn_cl]")
                else:
                    # NO SE RETIENE UN CIERRE SIN RELOJ PARA TRABAJAR
                    # (2026-09-01). Medido con el banco: la compuerta hace que
                    # el agente trabaje mucho mas (8,6 -> 15,7 pasos de media)
                    # y eso sube completitud y entregabilidad... pero en las
                    # tareas que YA iban a cerrar bien, seguir trabajando las
                    # dejo sin tiempo y entregaron menos que sin compuerta
                    # (web-kanban 0,96 -> 0,49). Retener un cierre solo tiene
                    # sentido si queda pared para hacer algo con el turno que
                    # se gana: si no, la compuerta convierte una entrega buena
                    # en una a medias.
                    _resto = _pared_restante(t0)
                    if _resto is not None and _resto < _PARED_MINIMA_TRABAJO:
                        print_fn(f"[warn_cl]quedan {int(_resto)}s de "
                                 f"presupuesto: entrego lo que hay en vez de "
                                 f"empezar otro ciclo[/warn_cl]")
                        if _tel.activa():
                            _tel.evento("compuerta_contrato", paso=pasos,
                                        pendientes=len(_contrato.pendientes()),
                                        omitida_por_pared=int(_resto))
                    elif _contrato.puede_insistir():
                        _falta = _contrato.pendientes()
                        print_fn(f"[warn_cl]el encargo tenia "
                                 f"{len(_contrato)} requisitos y de "
                                 f"{len(_falta)} no hay rastro en lo "
                                 f"producido: sigo trabajando "
                                 f"({_contrato.nudges + 1}/"
                                 f"{_contrato.tope_nudges()})[/warn_cl]")
                        if _tel.activa():
                            _tel.evento("compuerta_contrato", paso=pasos,
                                        pendientes=len(_falta),
                                        requisitos=len(_contrato),
                                        nudge=_contrato.nudges + 1)
                        _pendiente_verif = result_text or _pendiente_verif
                        mensajes.append({"role": "user",
                                         "content": _contrato.bloque_para_modelo()})
                        result_text, ok = "", False
                        continue
            # REVISION PROFUNDA (harness/revision_profunda.py): el arnes CORRE
            # lo construido antes de dejarlo entregar. Va ANTES de la parada
            # verificada porque un exito suyo registra evidencia fresca en el
            # ledger, y entonces la compuerta de politica de abajo deja salir
            # sin gastar un turno del modelo. Un fallo vuelve como turno de
            # usuario con la EVIDENCIA real (traceback, exit code, cola de
            # pytest), con la respuesta ya compuesta en rescate: igual que el
            # nudge de abajo, la compuerta nunca destruye trabajo hecho.
            if (_rev_mod is not None and ok and _muta is not None
                    and _muta.ficheros_escritos()):
                try:
                    _informe_rev = _rev_mod.revisar({
                        "ficheros_editados": _muta.ficheros_escritos(),
                        "workspace": os.getcwd(),
                        "pasos": pasos,
                        "rondas_usadas": _rondas_rev,
                        "superficie": "cli",
                        "on_evento": _progreso_rev,
                    })
                except Exception as _e_rv:
                    # Contrato: revisar() no lanza. Si igual lanzo, la revision
                    # no puede matar el turno que venia a proteger -- pero
                    # tampoco puede callarse (el fallo tipico de esta casa es el
                    # vacio silencioso).
                    _informe_rev = None
                    print_fn(f"[warn_cl]revision profunda: {type(_e_rv).__name__}: "
                             f"{_e_rv}; entrego sin ella[/warn_cl]")
                if _informe_rev and _informe_rev.get("nudge"):
                    _rondas_rev += 1
                    # El primer fallo es el titular; la lista nunca esta vacia
                    # aca (sin fallos no hay nudge), pero el default va igual:
                    # un IndexError en el camino caliente mataria el turno.
                    _tit = ((_informe_rev.get("fallos") or [{}])[0]
                            .get("detalle") or "")
                    print_fn("[warn_cl]revision profunda: lo construido NO pasa "
                             f"({_escape_seguro(_tit[:120])}); "
                             f"pido la reparacion (ronda {_rondas_rev}/"
                             f"{_rev_mod.max_rondas()})[/warn_cl]")
                    _pendiente_verif = result_text or _pendiente_verif
                    mensajes.append({"role": "user",
                                     "content": _informe_rev["nudge"]})
                    result_text, ok = "", False
                    continue
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
        # ¿Fue este paso de PURA LECTURA? Se decide con los nombres de las
        # tools que de verdad corrieron, no con la intencion del modelo.
        _paso_solo_lectura = True
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
                # RESCATE ANTES QUE AVISO (2026-08-30). Pedir "por partes" es
                # correcto pero no basta: el modelo reempieza por el principio
                # con el mismo presupuesto y se corta en la misma columna
                # (cuatro veces seguidas en la corrida que lo cazo). Si el
                # trozo que llego se puede escribir, se escribe: a partir de
                # ahi el turno siguiente CONTINUA en vez de reescribir.
                resultado = _rescatar_escritura(tc, crudo, ctx, run_tool, print_fn)
                if resultado is None:
                    resultado = (
                        f"RESULTADO {tc.nombre} ERROR: los argumentos llegaron "
                        f"CORTADOS ({len(crudo)} chars, JSON incompleto). No es un "
                        f"problema de la ruta ni del formato: el contenido es "
                        f"demasiado largo para un solo mensaje. Escribelo POR "
                        f"PARTES: escribir_archivo con la primera parte (como "
                        f"mucho 100 lineas) y luego apendar_archivo con el resto.")
                    print_fn(f"[warn_cl]{tc.nombre}: argumentos cortados a los "
                             f"{len(crudo)} chars; le pido al modelo que escriba "
                             f"por partes[/warn_cl]")
                history.append(resultado)
                # Un rescate SI es progreso: hay bytes nuevos en el disco. Con
                # ok=False el detector de racha lo contaba como fallo y a las
                # tres cortaba la tarea justo cuando estaba avanzando tramo a
                # tramo, que es exactamente el modo en que las tareas largas
                # tienen que terminar.
                _rescatado = resultado.startswith(f"RESULTADO {tc.nombre} ") \
                    and ": PARCIAL." in resultado[:200]
                trace.append({"action": tc.nombre, "args": crudo[:200],
                              "ok": _rescatado, "result_head": resultado[:160]})
                if _rescatado:
                    # Y CUENTA COMO AVANCE. Este `continue` se salta el camino
                    # normal de la tool, donde vive `observar_fichero`; sin
                    # esto, escribir un fichero por rescate no aparecia en el
                    # presupuesto por progreso, o sea que la tarea que MAS
                    # necesita que le amplien los pasos -- la que va tramo a
                    # tramo -- era justo la que no los conseguia.
                    try:
                        _rr = getattr(tc, "argumentos_crudos", "")
                        from cognia.agent import rescate_parcial as _rp_av
                        _pz = _rp_av.partes(_rr)
                        if _pz and _canal is not None and _estado_on:
                            _canal.anotar_fichero(_estado, _pz["ruta"],
                                                  tc.nombre, ok=True)
                        if _pz and _prog is not None:
                            _prog.observar_fichero(_pz["ruta"])
                    except Exception as _exc_av:
                        logging.getLogger(__name__).warning(
                            "rescate sin anotar en el progreso: %s", _exc_av)
                mensajes.append(mensaje_tool(tc.id, resultado))
                continue
            # LA COMPACTACION NO PUEDE COMERSE UN FICHERO (2026-08-26).
            # `_truncar_valores_args` sustituye los valores largos de los
            # assistant viejos por `v[:20] + _MARCA_ARG_TRUNCADO`, para que la
            # cola del historial no arrastre 40 KB de codigo. El problema es
            # que ese texto VUELVE al modelo dentro de su propio tool call, y
            # el modelo lo lee como si fuera el contenido del fichero: lo
            # copia y lo reescribe al disco, machacando lo que ya habia.
            #
            # PASO DE VERDAD, y se reprodujo byte a byte: en la corrida del
            # videojuego, `voleibol/game/ai.py` quedo con exactamente esto y
            # nada mas:
            #     # -*- coding: utf-8 … (argumento truncado: el contenido ya
            #     esta en el fichero)
            # que es el output literal de _truncar_valores_args sobre un
            # fichero que empezaba por la linea de encoding. Un modulo entero
            # perdido, y en silencio: la escritura "salio bien".
            #
            # Un aviso en el marcador no basta -- el modelo ya tenia uno
            # delante y lo copio igual. Esto es una guarda DETERMINISTA en el
            # camino de escritura: si el contenido lleva la marca, no se
            # escribe y se le dice al modelo que relea el fichero.
            # Se mira el dict YA PARSEADO y no `argumentos_crudos`: json.dumps
            # escapa el '…' del marcador como '\\u2026', asi que buscarlo en el
            # JSON serializado no acierta nunca (lo cazo el test al primer
            # intento). El crudo se mira ademas, por si los argumentos no
            # vinieron como JSON (protocolo texto 'ruta | contenido').
            if tc.nombre in _TOOLS_ESCRITURA and _lleva_marca_truncado(tc):
                resultado = (
                    f"RESULTADO {tc.nombre} ERROR: el contenido que mandaste "
                    f"es el MARCADOR DE TRUNCADO del historial, no codigo. "
                    f"Ese texto aparece porque el contenido viejo se recorto "
                    f"para ahorrar contexto: el fichero de verdad sigue "
                    f"entero en el disco. NO lo copies. Si necesitas su "
                    f"contenido, leelo con leer_archivo; si querias cambiar "
                    f"una parte, usa editar_archivo con el bloque exacto.")
                print_fn(f"[warn_cl]{tc.nombre}: bloqueada una escritura que "
                         f"habria machacado el fichero con el marcador de "
                         f"truncado del historial[/warn_cl]")
                history.append(resultado)
                trace.append({"action": tc.nombre,
                              "args": str(tc.argumentos_crudos or "")[:200],
                              "ok": False, "result_head": resultado[:160]})
                mensajes.append(mensaje_tool(tc.id, resultado))
                continue
            _args_tc = tc.argumentos
            if perfil.get("harness"):
                # P8 (deepagents NemotronToolCallShim): la familia renombra
                # alias y rellena defaults ANTES de traducir al protocolo
                # texto. Sin "harness" en el perfil no se importa ni se copia.
                try:
                    from cognia.agent.model_profiles import aplicar_shim
                    _args_tc = aplicar_shim(perfil, tc.nombre, tc.argumentos)
                except Exception as _exc_shim:
                    print_fn(f"[warn_cl]shim de tool-calls de la familia no "
                             f"aplicado ({type(_exc_shim).__name__}: "
                             f"{_exc_shim}); args intactos[/warn_cl]")
            args_str = args_legacy(tc.nombre, _args_tc)
            if _ev is not None:
                _emitir(_ev.ToolInicio(tool=tc.nombre, args=args_str[:120],
                                       paso=pasos))
            t_tool = __import__("time").time()
            if _guardia is not None:
                # register_action solo caza A-A-A (mismo par tool+args 3 veces).
                # El guardia anade ping-pong A-B-A-B y ciclos A-B-C-A-B-C, que
                # es como se ve de verdad un agente atascado con dos ficheros.
                _vg = _guardia.registrar(tc.nombre, args_str)
                if _vg.get("estado") == "bloqueo" and _ilimitado and \
                        _bloqueos_seguidos[0] + 1 < _TOPE_BLOQUEOS_SEGUIDOS:
                    # pasos ilimitados: el patron se le dice al modelo y se
                    # sigue; cerrar por bucle seria decidir por el.
                    _bloqueos_seguidos[0] += 1
                    _aviso_guardia = (_vg.get("mensaje") or "bucle detectado") + \
                        " Cambia de enfoque: no repitas la misma accion."
                    print_fn(f"[warn_cl]bucle detectado ({_vg.get('patron', 'repeticion')}): "
                             f"aviso al modelo {_bloqueos_seguidos[0]}/{_TOPE_BLOQUEOS_SEGUIDOS}, "
                             f"sigo (pasos ilimitados)[/warn_cl]")
                elif _vg.get("estado") == "bloqueo":
                    if _ilimitado:
                        print_fn(f"[warn_cl]ciclo degenerado: {_TOPE_BLOQUEOS_SEGUIDOS} bloqueos "
                                 f"seguidos del guardia ignorados; cierro (pasos ilimitados "
                                 f"no es girar en vacio)[/warn_cl]")
                    print_fn(f"[warn_cl]{_vg.get('mensaje') or 'bucle detectado'}"
                             f"[/warn_cl]")
                    _salida.sellar(RAZON_BUCLE_DETECTADO, _vg.get("patron", ""))
                    result_text = ("(interrumpida: el agente entro en bucle -- "
                                   f"{_vg.get('patron', 'repeticion')})")
                    _parchear_huerfanos(mensajes)   # P1: la traza sin calls colgando
                    mensajes = None
                    break
                if _vg.get("estado") == "aviso":
                    _aviso_guardia = _vg.get("mensaje") or ""
                if _vg.get("estado") != "bloqueo":
                    _bloqueos_seguidos[0] = 0      # un paso sano resetea la valvula
            # EL CORTE TONTO, ACOTADO (2026-08-26). register_action cuenta el
            # par (tool, args) en TODA la tarea: sin ventana, sin caducidad y
            # sin mirar las EXENTAS. A la 3ra vez mata el turno. En una tarea
            # larga y legitima eso es un falso positivo garantizado: correr
            # `tests` despues de cada arreglo, o `ver_salida <pid>` para
            # seguir un proceso, es LITERALMENTE el bucle de desarrollo, y a
            # la tercera se cerraba la tarea. El propio repo ya lo tenia
            # diagnosticado en guardia_bucle.py:20 ("no tiene ventana: dos
            # usos legitimos separados por 20 pasos suman igual") y escribio
            # GuardiaBucle para reemplazarlo... pero lo cableo ADEMAS del
            # roto, no EN SU LUGAR, asi que el corte peor seguia mandando.
            #
            # HUELLA EN PRODUCCION (2026-08-26): dos turnos muertos con
            # 'razon=bucle_detectado detalle=repite ejecutar' (11:00:59
            # pasos=6 y 12:45:49 pasos=7), y el mensaje que le llego al dueno
            # —chat_history id 1033— es palabra por palabra el literal de
            # abajo: "(interrumpida por estancamiento: repitio 'ejecutar' con
            # los mismos argumentos)".
            #
            # Con el arnes activo (default) manda GuardiaBucle, que cubre lo
            # mismo Y MAS (A-A-A con ventana 10, ping-pong A-B-A-B, ciclos
            # A-B-C) respetando las exentas. Sin arnes queda este, pero al
            # menos ya no cuenta las tools cuyo trabajo ES repetirse.
            if _guardia is not None or tc.nombre in EXENTAS_TOOLS:
                verdict = "ok"
            else:
                verdict = register_action(sig_counts, tc.nombre, args_str)
            if verdict == "stop" and _ilimitado:
                _aviso_guardia = (f"Repetiste '{tc.nombre}' con los mismos argumentos "
                                  "tres veces. No lo repitas: lee el resultado y "
                                  "cambia de enfoque.")
                print_fn(f"[warn_cl]tool repetida 3 veces ({tc.nombre}): aviso al "
                         f"modelo, sigo (pasos ilimitados)[/warn_cl]")
            elif verdict == "stop":
                # Estancamiento (3ra vez el MISMO par tool+args): cierre
                # honesto con lo que hay, sin quemar mas presupuesto.
                print_fn("[warn_cl]Agente estancado (tool repetida 3 veces): "
                         "cierre honesto.[/warn_cl]")
                if _salida is not None:
                    _salida.sellar(RAZON_BUCLE_DETECTADO, f"repite {tc.nombre}")
                result_text = ("(interrumpida por estancamiento: repitio "
                               f"'{tc.nombre}' con los mismos argumentos)")
                _parchear_huerfanos(mensajes)   # P1: la traza sin calls colgando
                mensajes = None
                break
            _servido = None
            if _especular and _cache_espec is not None and _espec is not None:
                try:
                    _hit = _espec.aceptar({"tool": tc.nombre, "args": args_str},
                                          _cache_espec)
                    if _hit.get("aceptada"):
                        _servido = _hit.get("resultado")
                        print_fn(f"[detail]especulacion aceptada por "
                                 f"{_hit.get('via')}: {tc.nombre}[/detail]")
                except Exception:
                    _servido = None
            if isinstance(ctx, dict):
                # El veredicto del turno ANTERIOR no puede sobrevivir a este:
                # un resultado servido por la especulacion no pasa por run_tool
                # y heredaria su exit ("evento sellado con el reloj rancio").
                ctx.pop("_ultimo_exit", None)
                ctx.pop("_ultimo_ok", None)
            _t_tool = __import__("time").time()
            resultado = (_servido if _servido is not None
                         else run_tool(tc.nombre, args_str, ctx))
            # LAZO CORTO (2026-09-01): lo que se acaba de escribir se CORRE
            # aqui, no en el cierre. Ver harness/lazo_corto.py. El texto va
            # pegado al resultado de la tool, asi que el modelo lo lee en el
            # mismo turno en que escribio el fichero.
            # ESPIRAL DE DEPURACION (medida en el A/B de 20 min, 2026-09-01):
            # el modelo escribio debug2.js, debug3.js ... debug7.js, siete
            # scripts sueltos persiguiendo un bug de movimiento, y el juego
            # se quedo sin arreglar. El guardia de "bucle por fichero" no lo
            # ve porque cada fichero tiene otro nombre. Aqui se cuentan los
            # ficheros de usar-y-tirar por su NOMBRE y al tercero se avisa
            # UNA vez: mira el error en el producto, no en otro script mas.
            if (tc.nombre == "escribir_archivo" and not _aviso_sueltos["dado"]
                    and _es_fichero_suelto(_ruta_escrita(args_str))
                    and not _en_scratch(_ruta_escrita(args_str))):
                _sueltos.append(_ruta_escrita(args_str))
                if len(_sueltos) >= 3:
                    _aviso_sueltos["dado"] = True
                    resultado = str(resultado or "") + (
                        "\n[ARNES] llevas %d scripts sueltos de depuracion (%s). "
                        "Escribir otro no acerca el producto: reproduce el fallo "
                        "EN el producto (abrelo o ejecutalo, mira el error real) "
                        "y arregla el fichero principal. Para una prueba rapida "
                        "usa ejecutar con python -c o node -e, sin crear ficheros."
                        % (len(_sueltos), ", ".join(os.path.basename(s) for s in _sueltos[-3:])))
                    print_fn(f"[warn_cl]espiral de depuracion: {len(_sueltos)} "
                             f"scripts sueltos[/warn_cl]")
                    if _tel.activa():
                        _tel.evento("espiral_depuracion", paso=pasos, n=len(_sueltos))
            if _lazo_mod is not None and tc.nombre in _TOOLS_ESCRITURA_LAZO:
                try:
                    _r_lazo = _ruta_escrita(args_str)
                    _ev_lazo = _lazo_mod.tras_escritura(
                        _r_lazo, raiz=os.getcwd(), contrato=_ids_contrato)
                except Exception as _e_lz:
                    _ev_lazo = "[LAZO CORTO] no se pudo comprobar (%s)" % type(_e_lz).__name__
                # ESCRITURA POR TROZOS (2026-09-01). Una llamada de escritura
                # muy larga es la que se corta a media cadena JSON (el 500 del
                # server). El rescate de parciales salva lo que cabe, pero lo
                # barato es no llegar: al primer fichero grande se le dice
                # como seguir. Es un aviso pegado al resultado, no un veto.
                if len(args_str or "") > _TOPE_ESCRITURA_TROZO:
                    _ev_lazo = ((_ev_lazo + "\n") if _ev_lazo else "") + (
                        "[ARNES] esta escritura fue de %d caracteres. Las llamadas "
                        "muy largas se cortan a mitad y se pierde el resto: para "
                        "ficheros grandes escribe el esqueleto con escribir_archivo "
                        "y anade el resto con apendar_archivo en bloques de como "
                        "mucho 120 lineas." % len(args_str))
                if _ev_lazo:
                    resultado = str(resultado or "") + "\n" + _ev_lazo
                    print_fn(f"[detail]{_escape_seguro(_ev_lazo[:200])}[/detail]")
                    # El lazo corto es una VERIFICACION observada por la
                    # maquina: un fichero que pasa de FALLA a OK es un avance
                    # real para el gobernador de progreso (observar_* solo
                    # cuenta la transicion rojo->verde, no el verde repetido).
                    if _prog is not None and "[LAZO CORTO" in _ev_lazo and \
                            "no se pudo comprobar" not in _ev_lazo:
                        try:
                            _prog.observar_verificacion(
                                "lazo:" + str(_r_lazo), ok=("[LAZO CORTO OK]" in _ev_lazo),
                                evidencia=_ev_lazo[:200])
                        except Exception:
                            pass
                    if _tel.activa():
                        _tel.evento("lazo_corto", paso=pasos, fichero=str(_r_lazo)[:120],
                                    ok=("[LAZO CORTO OK]" in _ev_lazo),
                                    detalle=_ev_lazo[:300])
            if _tel.activa():
                try:
                    _tel.evento("tool", nombre=tc.nombre, paso=pasos,
                                ok=(ctx.get("_ultimo_ok") if isinstance(ctx, dict) else None),
                                exit=(ctx.get("_ultimo_exit") if isinstance(ctx, dict) else None),
                                bytes_args=len(args_str or ""),
                                bytes_resultado=len(str(resultado or "")),
                                servido_por_especulacion=_servido is not None,
                                ms=int((__import__("time").time() - _t_tool) * 1000))
                except Exception:
                    pass
            # P0-1: EL EXIT REAL MANDA SOBRE LA REGEX. `run_tool` ya corrigio
            # su `ok` con el returncode del proceso y lo deja en el ctx; usar
            # aqui la regex otra vez hacia que un pytest en rojo
            # ("RESULTADO ejecutar (exit 1): F ...", sin ERROR en los 120
            # primeros chars) se contase como victoria en el canal de estado,
            # en el presupuesto por progreso y en la parada verificada.
            # Solo la PRIMERA linea clasifica cuando NO hay exit: los errores
            # del registry ponen ERROR en la linea 1; el CONTENIDO de un exito
            # (un log con errores via ctx_grep/leer_archivo) no debe marcar
            # fallo y disparar el corte por no-progreso (fix 2026-08-11).
            _exit_real = ctx.get("_ultimo_exit") if isinstance(ctx, dict) else None
            _exit_medido = isinstance(_exit_real, int) and not isinstance(_exit_real, bool)
            if isinstance(ctx, dict) and "_ultimo_ok" in ctx:
                tool_ok = bool(ctx["_ultimo_ok"])
            else:
                tool_ok = not _es_fallo_tool(resultado, tc.nombre)
            if tc.nombre not in TOOLS_EXPLORATORIAS:
                _paso_solo_lectura = False
            if _muta is not None and es_operacion_de_fichero(tc.nombre):
                # Se anota el INTENTO y su resultado MEDIDO. El footer del
                # epilogo hace imposible que el modelo afirme haber escrito
                # cinco ficheros cuando tres patches fallaron.
                _idm = _muta.intento(ruta_de_args(args_str), tc.nombre)
                _muta.resultado(_idm, tool_ok, resultado)
                if tool_ok and _ts_1a_edicion is None:
                    _ts_1a_edicion = __import__("time").time()
            elif _muta is not None and tool_ok and tc.nombre not in TOOLS_EXPLORATORIAS:
                # LA MUTACION SE OBSERVA, NO SE DEDUCE DEL NOMBRE (2026-08-31).
                # `es_operacion_de_fichero` conoce CINCO nombres de tool. Todo
                # lo que escriba fuera de esa lista -- generar_codigo,
                # copiar_archivo, una tool sintetizada, un `ejecutar` que corre
                # un script que genera ficheros, o un sub-agente delegado --
                # dejaba el registro vacio, y con el vacio se apagan de golpe
                # la revision profunda, la parada verificada y el bloque
                # ENTREGA: las tres exigen `_muta.ficheros_escritos()`. El
                # cierre llegaba a afirmar "ningun fichero escrito" sobre
                # trabajo real.
                #
                # Aqui se mira el DISCO: que ficheros del workspace cambiaron
                # mientras corria esta tool. Una lista de nombres en otro
                # modulo se desincroniza; el mtime no.
                for _r_obs in _ficheros_tocados_desde(os.getcwd(), _t_tool):
                    _idm = _muta.intento(_r_obs, tc.nombre + " (observado)")
                    _muta.resultado(_idm, True, "cambio detectado en disco")
                    if _ts_1a_edicion is None:
                        _ts_1a_edicion = __import__("time").time()
            if _cont_fich is not None and tc.nombre in _rep_mod.TOOLS_EDICION:
                # P12: cuenta la edicion por fichero normalizado; al umbral,
                # el nudge va como turno user tras el resultado (abajo, junto
                # al aviso del guardia). Config invalida -> aviso UNA vez y
                # el contador se apaga (patron del propio modulo).
                try:
                    _aviso_fichero = _cont_fich.registrar(
                        _ruta_fich(args_str), tc.nombre) or ""
                except _rep_mod.ConfigInvalida as _exc_cf:
                    _rep_mod._avisar(f"config invalida, bucle por fichero "
                                     f"apagado: {_exc_cf}")
                    _cont_fich = None
                if _aviso_fichero:
                    # Solo la PRIMERA frase del nudge: el resto es la
                    # instruccion al modelo, y en pantalla salia cortada a
                    # mitad de palabra ('...enuncia la').
                    _frase = _aviso_fichero[len(_rep_mod.MARCA):].strip()
                    _frase = re.split(r"(?<=[.!?])\s", _frase, maxsplit=1)[0]
                    print_fn(f"[warn_cl]bucle por fichero: {_frase[:140]}"
                             f"[/warn_cl]")
            if _estado_on and _canal is not None:
                # Hechos MEDIDOS: anotar_fichero le lee el sha256 y los bytes al
                # disco, no le cree al resultado de la tool.
                try:
                    if es_operacion_de_fichero(tc.nombre):
                        _r = ruta_de_args(args_str)
                        _canal.anotar_fichero(_estado, _r, tc.nombre, ok=tool_ok)
                        if _prog is not None and tool_ok:
                            _prog.observar_fichero(_r)
                    elif tc.nombre in ("ejecutar", "ejecutar_fondo", "tests"):
                        # El exit REAL, no `0 if tool_ok else 1`: el docstring
                        # de anotar_comando dice literalmente "su exit code
                        # REAL", y `commit._fuzzy` lee este canal desde TX. Sin
                        # exit medido (bloqueado por el sentinel, timeout,
                        # ejecutar_fondo) NO se anota: inventar un 0 seria
                        # afirmar que corrio y salio bien, e inventar un 1 que
                        # corrio y fallo. Las dos son mentira; la constancia de
                        # que se intento queda en el LIBRO con origen derivado.
                        if _exit_medido:
                            _canal.anotar_comando(_estado, args_str[:200],
                                                  _exit_real, resultado)
                    if _es_verificacion(tc.nombre, args_str):
                        _canal.anotar_verificacion(_estado, args_str[:200], tool_ok)
                        if _prog is not None:
                            _prog.observar_verificacion(args_str[:120], ok=tool_ok,
                                                        evidencia=resultado[:200])
                except Exception:
                    pass
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
            # Observabilidad opt-in (COGNIA_TRACE=1), la MISMA linea que el
            # bucle legacy de cli.py imprime: sin ella el regimen nativo (el
            # que corre de verdad) no dejaba ver que accion se repite. Print
            # plano a proposito, y si la observacion lleva un recordatorio de
            # repeticion (harness/repeticion, va al FINAL del texto) se
            # imprime aparte: la cabeza de 100 chars jamas lo mostraria.
            if os.environ.get("COGNIA_TRACE") == "1":
                print(f"TRAZA paso {len(trace)}: ACCION {tc.nombre} "
                      f"{args_str[:100]!r} -> {resultado[:100]!r}", flush=True)
                if "[RECORDATORIO DE REPETICION]" in resultado:
                    _i_rec = resultado.rfind("[RECORDATORIO DE REPETICION]")
                    print(f"TRAZA recordatorio: {resultado[_i_rec:][:300]!r}",
                          flush=True)
            # El output COMPLETO va al buffer ANTES de emitir ToolFin: el
            # renderer casa evento y entrada por resultado[:200] == resumen
            # (el evento solo lleva el recorte). Fallo del buffer -> Degradado
            # visible y el render cae al camino viejo; el turno sigue.
            if _tbuf is not None:
                try:
                    _tbuf.registrar(tc.nombre, args_str[:120], resultado,
                                    bool(tool_ok))
                except Exception as _exc_buf:
                    if _ev is not None:
                        _emitir(_ev.Degradado(
                            donde="render_tools.buffer",
                            motivo=f"{type(_exc_buf).__name__}: {_exc_buf}"))
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
            if _aviso_fichero:
                mensajes.append({"role": "user", "content": _aviso_fichero})
                _aviso_fichero = ""
            if verdict == "warn":
                mensajes.append({
                    "role": "user",
                    "content": (f"AVISO: ya llamaste '{tc.nombre}' con esos "
                                "mismos argumentos y no avanzo. No la repitas: "
                                "proba otra herramienta o responde el cierre.")})
        if _prog is not None and _paso_solo_lectura and resp.tool_calls:
            # LEER NO ES ESTAR ATASCADO. El paso ya se cobro (tokens y
            # segundos siguen contando); lo unico que cambia es que no gasta
            # credito de arranque hasta CREDITO_EXPLORACION pasos.
            try:
                _prog.marcar_exploratorio()
            except Exception:
                pass
        if mensajes is None:      # corto por estancamiento adentro del for
            break

        # Corte por NO-PROGRESO: N tools seguidas fallando = el modelo no
        # avanza (misma cota dura que el camino legacy).
        #
        # ...SALVO QUE TODA LA RACHA SEA DE EJECUCION (2026-08-26). El `ok`
        # sale del EXIT REAL del proceso, asi que un `ejecutar python
        # juego.py` que termina en traceback cuenta como fallo. Pero eso NO
        # es el agente sin saber operar: es el ciclo escribir/ejecutar/
        # corregir haciendo su trabajo, y el error es justamente la
        # informacion que el agente fue a buscar. Con el umbral de 3, tres
        # intentos de correr algo que todavia no compila mataban la tarea --
        # es la tercera muerte del log del 2026-08-26 ('razon=bucle_detectado
        # detalle=3 tools seguidas fallaron pasos=5', 11:04:43).
        # No se quita el corte: se le da el DOBLE de margen a la racha que
        # es solo de ejecucion. Y no queda a la intemperie, porque las otras
        # guardas siguen mirando: GuardiaBucle si repite lo mismo, el
        # gobernador por progreso si no hay un solo avance verificado, y el
        # presupuesto de pasos como techo.
        # (El camino legacy tiene su propia constante en cli.py:_FAIL_STREAK;
        # ese bucle solo corre con el perfil 3B o COGNIA_AGENT_LEGACY=1.)
        _racha = fail_streak
        _ultimas = trace[-fail_streak:]
        if (len(_ultimas) >= fail_streak
                and all(a.get("action") in EXENTAS_TOOLS or
                        a.get("action") == "ejecutar" for a in _ultimas)):
            _racha = fail_streak * 2
        recientes = trace[-_racha:]
        if len(recientes) >= _racha and not any(a["ok"] for a in recientes):
            # PRIMERO SE AVISA, DESPUES SE CORTA (2026-09-01). Tres tools
            # fallidas seguidas es lo NORMAL cuando se depura: un comando
            # que no encuentra el fichero, el segundo con la ruta mal, el
            # tercero con el flag equivocado. Con 20 min de reloj, este corte
            # mato una CLI de tareas a los 252 s (borrar_archivo + ejecutar
            # x2) y un juego a los 410 s (tres `mcp` seguidos), las dos con
            # tres cuartos del reloj sin usar. Ahora la primera racha manda
            # un aviso con los errores literales y exige cambiar de enfoque;
            # solo la racha DOBLE seguida (2x, o sea 6 fallos sin uno bueno)
            # cierra, que si es girar en vacio.
            _ultimos_err = " | ".join(
                str(a.get("result_head") or "")[:140].replace("\n", " ")
                for a in recientes[-3:])
            if not _aviso_racha["dado"]:
                _aviso_racha["dado"] = True
                _aviso_racha["desde"] = len(trace)
                mensajes.append({"role": "user", "content": (
                    "ALTO: las ultimas %d herramientas fallaron seguidas:\n%s\n\n"
                    "No repitas la misma accion. Lee el error literal, comprueba "
                    "que la ruta/comando existe (listar, leer_archivo) y cambia "
                    "de enfoque. Si algo no se puede hacer en este entorno, dilo "
                    "en una linea y sigue con lo demas." % (_racha, _ultimos_err))})
                print_fn(f"[warn_cl]{_racha} herramientas seguidas fallaron: "
                         f"aviso al modelo, sigo[/warn_cl]")
                if _tel.activa():
                    _tel.evento("aviso_racha", paso=pasos, racha=_racha)
            elif _ilimitado and _reavisos_racha[0] < _TOPE_REAVISOS_RACHA and \
                    len(trace) - _aviso_racha["desde"] >= _racha and \
                    not any(a["ok"] for a in trace[-(_racha * 2):]):
                # pasos ilimitados: se repite el ALTO con los errores nuevos
                # y se sigue; el modelo decide cuando esta bien. Tras
                # _TOPE_REAVISOS_RACHA re-avisos ignorados cae a la rama de
                # abajo, que cierra: eso ya no es trabajar, es girar.
                _reavisos_racha[0] += 1
                _aviso_racha["desde"] = len(trace)
                mensajes.append({"role": "user", "content": (
                    "ALTO otra vez: %d herramientas seguidas fallaron:\n%s\n\n"
                    "Para y piensa que esta fallando de verdad antes de la "
                    "siguiente accion." % (_racha * 2, _ultimos_err))})
                print_fn(f"[warn_cl]{_racha * 2} herramientas seguidas fallaron: "
                         f"aviso al modelo, sigo (pasos ilimitados)[/warn_cl]")
            elif len(trace) - _aviso_racha["desde"] >= _racha and \
                    not any(a["ok"] for a in trace[-(_racha * 2):]):
                # Sin aviso aparte: el hecho va UNA vez, en el footer del
                # turno ('parado: 6 tools seguidas fallaron') via el motivo
                # del envelope (juez 2026-08-24: un hecho, un mensaje).
                if _salida is not None:
                    _salida.sellar(RAZON_BUCLE_DETECTADO,
                                   f"{_racha * 2} tools seguidas fallaron")
                result_text = (f"(interrumpida: {_racha * 2} herramientas seguidas "
                               "fallaron sin avanzar; el modelo no logro la tarea)")
                break

        # El prompt_tokens del usage NO incluye lo que este turno apendeo
        # (assistant + N turnos tool): con tool-calls paralelas de resultados
        # grandes el estimado rancio dejaba crecer el prompt por encima de
        # n_ctx sin recortar nada (fix 2026-08-11). Se suma lo agregado
        # (chars/4) y se itera hasta bajar del umbral o agotar recortables.
        est = int((resp.usage or {}).get("prompt_tokens") or 0)
        if not est:
            # Stream SIN chunk de usage (F4, 2026-08-23, cazado TECLEANDO en
            # el REPL): el usage estimado por timings/frames trae solo
            # completion_tokens, y con prompt_tokens=0 este presupuesto
            # contaba SOLO lo apendeado en este turno — dos leer_archivo de
            # 97 KB daban est~24k contra un umbral de 26k y la compactacion
            # (la nueva Y el truncado de siempre) no disparaba NUNCA bajo
            # streaming. El estimado honesto es el historial entero a chars/4,
            # la misma moneda del resto de la funcion.
            est = sum(len(str(m.get("content") or ""))
                      + len(str(m.get("reasoning_content") or ""))
                      for m in mensajes[:idx_turno]) // 4
        # Se cuenta TAMBIEN el reasoning_content: mensaje_assistant lo
        # reinyecta y con un razonador pesa mas que el content (parte del fix
        # A3-bucle: el CoT era invisible para el presupuesto de punta a punta).
        est += sum(len(str(m.get("content") or ""))
                   + len(str(m.get("reasoning_content") or ""))
                   for m in mensajes[idx_turno:]) // 4
        _libero_algo = False
        # F4 (2026-08-23): modo 'resumen' = UNA pasada que funde el historial
        # viejo en un resumen estructurado (canal de estado + 1 linea por tool
        # descartada con su spill de F3) y deja la cola reciente INTACTA: una
        # sola invalidacion de la KV cache por compactacion, contra una por
        # mordisco del modo viejo. None = modo 'truncado' o fallo del resumen
        # en este turno: el camino de abajo sigue byte-identico de fallback.
        _lib_resumen = _compactar_por_resumen(
            mensajes, perfil.get("n_ctx"), est, _estado, print_fn)
        if _lib_resumen:
            _libero_algo = True
            est -= _lib_resumen // 4
        else:
            # None (modo truncado / fallo del resumen) *y tambien 0*: cuando
            # compactar() devuelve aplicada=False por encima del umbral
            # ('nada viejo que fundir', 'el resumen no libera chars'...), no
            # tratarlo como atendido — sin este fallback el prompt seguia por
            # encima de n_ctx y el server hacia context-shift EN SILENCIO (la
            # clase de fallo A3 de _recortar_mensajes; el camino de retry ya
            # caia al truncado con su `or 0`, este no. Revision 2026-08-23).
            # Bajo el umbral es inocuo: _recortar_mensajes devuelve 0 solo.
            _est_antes, _lib_trunc = est, 0
            while True:
                liberados = _recortar_mensajes(mensajes, perfil.get("n_ctx"), est)
                if not liberados:
                    break
                _libero_algo = True
                _lib_trunc += liberados
                est -= liberados // 4
            if _lib_trunc:
                # Telemetria para /compactar (el modo viejo tambien se anota).
                # Best-effort CON aviso: la telemetria no puede costar el turno,
                # pero su fallo tampoco puede ser mudo.
                try:
                    from cognia.harness import compactacion as _comp_t
                    _comp_t.anotar_truncado(_lib_trunc, _est_antes,
                                            perfil.get("n_ctx"))
                except Exception as _exc_ct:
                    print_fn(f"[warn_cl]telemetria de compactacion no anotada: "
                             f"{_exc_ct}[/warn_cl]")
        # La reinyeccion del canal es solo para el TRUNCADO: en modo resumen
        # el bloque de estado ya viaja DENTRO del propio resumen. `not
        # _lib_resumen` (no `is None`): si el resumen devolvio 0 y libero el
        # truncado, el estado tambien se perdio por el camino truncado.
        if (_libero_algo and not _lib_resumen
                and _estado_on and _canal is not None):
            # AQUI es donde se pierde el estado: el recorte resume o tira los
            # turnos viejos y con ellos que ficheros se tocaron y que
            # restricciones habia. El canal vuelve a entrar ENTERO, y nunca
            # pasa por el resumidor (esa es toda la inmunidad).
            try:
                _bloque = _canal.render(_estado, tope_chars=1200)
                if _bloque:
                    mensajes.append({"role": "user", "content": _bloque})
                    print_fn("[detail]contexto recortado: reinyecto el canal de "
                             "estado verificado[/detail]")
            except Exception:
                pass
        # FOOTER de contexto: la ocupacion que ve la barra es ESTA `est`
        # (post-compactacion), la misma que decidio compactar o no. Estimada
        # si el stream no trajo prompt_tokens (chars/4) o el usage se dedujo.
        _anotar_ocupacion_viva(
            est, perfil.get("n_ctx"),
            estimado=(not (resp.usage or {}).get("prompt_tokens")
                      or bool(getattr(resp, "usage_estimado", False))),
            print_fn=print_fn)
        # RECORDATORIO DE RAZONAMIENTO EN BUCLE (2026-08-31). Al cerrar el
        # paso: ¿se fue en pensar y no dejo un avance verificado detras? El
        # nudge entra como turno de usuario, igual que el del guardia y el del
        # bucle por fichero, y al cruzar la racha dura se apaga el pensamiento
        # (la unica intervencion con medicion: ver la palanca de arriba).
        if _vig is not None:
            _chars_razon = 0
            try:
                _razon_paso = (getattr(resp, "reasoning_content", "") or "")
                _chars_razon = _vivo["chars_razon"] or len(_razon_paso)
                _avanzo = (len(_prog.avances) > _av_antes if _prog is not None
                           else bool(resp.tool_calls))
                _vr = _vig.turno(_chars_razon, _avanzo, _razon_paso)
            except Exception as _e_vr:
                _vr = {}
                print_fn(f"[detail]vigilante de razonamiento: "
                         f"{type(_e_vr).__name__}: {_e_vr}[/detail]")
            if _vr.get("apagar_pensamiento") and not _pensamiento["apagado"]:
                if _lleva_thinking() and os.environ.get(
                        "COGNIA_THINKING", "").strip().lower() not in (
                        "on", "1", "true", "si"):
                    _apagar_pensamiento()
                    print_fn(f"[warn_cl]{_vr['racha']} pasos seguidos pensando "
                             "mucho y sin un solo avance: apago el pensamiento "
                             "extendido (COGNIA_THINKING=on lo impide)"
                             "[/warn_cl]")
            if _vr.get("nudge"):
                mensajes.append({"role": "user", "content": _vr["nudge"]})
                print_fn(f"[detail]razonamiento en bucle ({_chars_razon} chars, "
                         f"racha {_vr.get('racha', 0)}"
                         + (", repetido" if _vr.get("repetido") else "")
                         + "): recordatorio inyectado[/detail]")
    else:
        # Presupuesto agotado sin cierre: redaccion final honesta con la
        # evidencia del history (no un volcado crudo).
        # Este era el UNICO punto de salida sin sellar, y por eso una tarea
        # compleja real (paquete + tests) cerraba con razon='desconocida' y el
        # WARNING de "ningun punto del bucle sello". Lo cazo la primera tarea
        # que agoto el presupuesto de verdad, no la revision.
        if _salida is not None:
            _salida.sellar(RAZON_PRESUPUESTO_AGOTADO,
                           f"{max_turns} pasos sin cierre")
        ultimo = next((h for h in reversed(history)
                       if h.startswith("RESULTADO ")), "")
        result_text = (f"(presupuesto de {max_turns} pasos agotado sin cierre) "
                       + ultimo[:300])
        # REVISION PROFUNDA en SOLO-REPORTE. Agotar el presupuesto tambien es
        # una entrega: el dueno se queda con lo que haya en disco y merece
        # saber si ARRANCA. No se pide reparacion (no queda presupuesto con
        # que repararlo: `rondas_usadas` va al tope a proposito), solo se
        # corre y se cuenta. Sin esto, la primera tarea real que se paso de
        # pasos entrego un main.py sin que nadie lo hubiera ejecutado.
        if _rev_mod is not None and _muta is not None and _muta.ficheros_escritos():
            try:
                _informe_rev = _rev_mod.revisar({
                    "ficheros_editados": _muta.ficheros_escritos(),
                    "workspace": os.getcwd(),
                    "pasos": pasos,
                    "rondas_usadas": _rev_mod.max_rondas(),   # solo reporte
                    "superficie": "cli",
                    "on_evento": _progreso_rev,
                })
            except Exception as _e_rv2:
                _informe_rev = None
                print_fn(f"[warn_cl]revision profunda: {type(_e_rv2).__name__}: "
                         f"{_e_rv2}; entrego sin ella[/warn_cl]")

    # REVISION PROFUNDA EN **TODOS** LOS CIERRES (2026-08-31). Hasta hoy solo
    # corria en dos: el cierre natural con respuesta y el presupuesto agotado.
    # Los otros — estancamiento del gobernador ('sin progreso verificado:
    # meseta_de_coste' / 'sin_arranque'), racha de tools fallidas, corte del
    # usuario — salian por `break` sin que NADIE mirara lo que habia quedado en
    # disco. Y son justo los cierres de la traza del dueno del 2026-08-31: tres
    # tareas seguidas, media hora cada una, y el index.html de 32 KB cortado a
    # mitad de una clase se entrego sin que se abriera ni una vez.
    # Va en solo-reporte (rondas al tope): en un cierre por estancamiento no
    # queda presupuesto con que reparar, pero saber si ARRANCA es gratis.
    if (_informe_rev is None and _rev_mod is not None and _muta is not None
            and _muta.ficheros_escritos()):
        try:
            _informe_rev = _rev_mod.revisar({
                "ficheros_editados": _muta.ficheros_escritos(),
                "workspace": os.getcwd(),
                "pasos": pasos,
                "rondas_usadas": _rev_mod.max_rondas(),   # solo reporte
                "superficie": "cli",
                "on_evento": _progreso_rev,
            })
        except Exception as _e_rv3:
            _informe_rev = None
            print_fn(f"[warn_cl]revision profunda: {type(_e_rv3).__name__}: "
                     f"{_e_rv3}; entrego sin ella[/warn_cl]")

    # RESCATE de la respuesta pendiente: si la puerta de verificacion pidio un
    # nudge y despues se agoto el presupuesto, la respuesta que el modelo YA
    # habia compuesto no se puede perder (turn_finalizer.py:100-124).
    if _pendiente_verif and not (result_text or "").strip():
        result_text = _pendiente_verif
        ok = True
    # FOOTER DE LA REVISION PROFUNDA: lo que el arnes CORRIO, con su veredicto.
    # Se pega tambien cuando PASA, a proposito: "revisado y arranca" y "nadie lo
    # miro" son dos estados distintos y el dueno tiene que poder distinguirlos.
    if _informe_rev is not None:
        try:
            _pie_rev = _rev_mod.footer_de(_informe_rev) if _rev_mod else ""
        except Exception:
            _pie_rev = ""
        if _pie_rev and (result_text or "").strip():
            result_text = (result_text or "") + "\n\n" + _pie_rev
        try:
            ctx["_revision_profunda"] = _informe_rev
        except Exception:
            pass
    # FOOTER DE MUTACIONES FALLIDAS: hecho medido, no resumen del modelo.
    if _muta is not None:
        try:
            _foot = _muta.footer()
        except Exception:
            _foot = None
        if _foot:
            result_text = (result_text or "") + "\n\n" + _foot
    # ENTREGA (2026-08-31): el turno no cierra sin decir QUE quedo en disco.
    # Un cierre que dice "(cerrada sin progreso verificado: meseta_de_coste)"
    # y pega el stdout de la ultima tool no le entrega nada al dueno; este
    # bloque le dice, fichero a fichero, tamano y si esta ENTERO — y cuando no
    # se escribio nada, lo dice tambien, que es el dato mas importante que
    # puede dar un turno que no entrego. Determinista: sale del disco, no del
    # modelo. Se salta en el cierre 'ok' SIN ficheros (una pregunta contestada
    # en prosa no necesita inventario).
    if _muta is not None:
        try:
            from cognia.harness import entrega as _entr
            _escritos = _muta.ficheros_escritos()
            # Lo escrito en el SCRATCHPAD es temporal (se borra al cerrar):
            # no es entrega ni puede salir como "no existe en disco".
            _scr = ctx.get("_scratchpad") if isinstance(ctx, dict) else None
            if _scr:
                try:
                    from cognia.agent import scratchpad as _spad
                    _escritos = [f for f in _escritos
                                 if not _spad.es_del_scratch(f, _scr)]
                except Exception:
                    pass
            if _escritos or not ok:
                result_text = _entr.anexar(result_text, _escritos,
                                           _muta.rutas_fallidas())
        except Exception as _e_en:
            print_fn(f"[detail]bloque de entrega no compuesto: "
                     f"{type(_e_en).__name__}: {_e_en}[/detail]")
    if _prog is not None or _estado is not None:
        try:
            ctx["_progreso"] = _prog.informe() if _prog is not None else {}
            ctx["_estado_verificado"] = _estado
        except Exception:
            pass
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

    # CIERRE COHERENTE (juez 2026-08-24): el glifo del footer y el veredicto
    # E8 de cli.py ('No se pudo completar') salen de la MISMA variable. Si la
    # ultima tool fallo y la respuesta no lo cuenta, el turno NO fue exito.
    if ok and (result_text or "").strip():
        try:
            _err_final = error_accionable_de_ejecucion(history)
        except Exception:
            _err_final = ""
        if _err_final and not ya_reporta_fallo(result_text):
            ok = False
    if _ev is not None:
        _emitir(_ev.TareaFin(ok=ok, resumen=(result_text or "")[:300],
                             pasos=pasos, tokens_predichos=tokens_total,
                             duracion_s=__import__("time").time() - t0,
                             motivo=motivo_de_cierre(_envelope)))
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
    if _tel.activa():
        try:
            _tel.evento("cierre", ok=bool(ok), pasos=pasos, tokens=tokens_total,
                        finish=str(finish or ""),
                        razon=str((_envelope or {}).get("razon", "")),
                        motivo=motivo_de_cierre(_envelope),
                        chars_respuesta=len(result_text or ""))
        except Exception:
            pass
    return {"texto": result_text, "pasos": pasos, "ok": ok,
            "tokens": tokens_total, "finish": finish,
            # True si el `content` del ultimo paso salio por TextoAgente
            # (streaming): quien pinte la respuesta puede saltarse esa prosa.
            "prosa_emitida": bool(_stream_on and _ev is not None
                                  and _vivo["tokens"] > 0),
            "razon": (_envelope or {}).get("razon", ""),
            "envelope": _envelope}
