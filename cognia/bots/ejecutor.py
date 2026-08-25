# -*- coding: utf-8 -*-
"""
cognia/bots/ejecutor.py
=======================
Correr UN turno de un bot, una RUTINA de un bot, o vaciar su INBOX. Es la
pieza que junta el perfil en disco (registro.py) con la maquinaria real de
Cognia (el bucle del agente de cli.py y el orquestador de inferencia).

FUENTE DEL DISENO (Hermes Bot Mode, Nous Research 2026-08-14, leido en
codigo, docs/user-guide/bot-mode):
- Cada rutina y cada mensaje entrante corre como SESION FRESCA del bot, en su
  perfil (config, memoria, skills, cron aislados). Aqui: `contexto(bot)` aplica
  el entorno del bot sobre os.environ durante el turno y lo restaura despues.
- Todo cae en el CHAT CANONICO del bot (sesiones/canon.jsonl): lo que dijo el
  usuario, lo que trajo una rutina, lo que le escribio otro bot y lo que el
  bot respondio. El REPL (/bots chat) y el remoto (/bots) pintan ese fichero.
- message_agent es fire-and-forget: el bot emisor termina su turno y la
  respuesta LLEGA DESPUES, cuando el daemon procesa el inbox del destino.
  Por eso `procesar_inbox` reenvia la respuesta al emisor con hops+1, y el
  tope de saltos (max_hops) corta la conversacion entre bots.

DOS CARRILES (regla MEDIDA de cognia/system_prompt.py, A/B 2026-07-23: un
system largo baja al agente de 10/10 a 1/4 corridas perfectas):
- CEREBRO (chat): `orch.infer(prompt, system=ctx.system_cerebro)`; el ALMA
  del bot reemplaza al prompt de usuario y, en el chat canonico, lleva el
  protocolo de mensajeria. Sin tools.
- AGENTE (tarea con tools): `cli._run_agent_task(...)` con SOLO el sufijo
  corto del bot como `guidance` (<= 300 chars) y las tools permitidas del
  perfil. Las rutinas y los MENSAJES DE OTRO BOT siempre van por aqui
  (Hermes corre las rutinas como sesion de agente; y mensaje_bot solo existe
  aqui); el resto lo decide cognia.agent.intent.detect como en el REPL.

INSTANCIA HEADLESS (coste MEDIDO 2026-08-25 en esta maquina): construir la
maquinaria como lo hace el REPL es BARATO: `apply_config()` 0,25 s +
`Cognia(db_path=...)` 0,2 s, mas 1,7 s de `import cognia.cli` la primera vez
por proceso. Lo caro es la inferencia (82 s para 60 tokens con el 27B
ocupado). Por eso NO hay "via ligera" distinta: se construye Cognia() con la
memoria del bot (memoria/cognia_memory.db) y se cachea por nombre de bot en
el proceso. Sin `first_run.apply_config()` el orquestador no encuentra el
llama-server (LLAMA_SERVER_PATH vacio) y cae a simulacion: el REPL lo llama
en cognia/__main__.py y un script suelto no; aqui se llama siempre.

AGENTE FALSO (tests y ensayos SIN modelo): `AGENTE_FALSO` (callable
(bot, texto, ctx) -> str) o COGNIA_BOTS_AGENTE="modulo:funcion". Cuando esta
puesto se avisa por log en CADA turno: un daemon en produccion con el agente
falso activo es un fallo que tiene que verse, no un silencio.
"""

from __future__ import annotations

import contextlib
import contextvars
import importlib
import io
import logging
import os
import threading
import time

logger = logging.getLogger("cognia.bots.ejecutor")

# Prefijo con que mensajeria.formatear_entrante presenta a un companero. Solo
# INFORMATIVO: quien='bot' lo pone procesar_inbox, que sabe de donde viene el
# envelope; el texto NO decide (un usuario o la API podian hacerse pasar por
# otro bot escribiendo 'Mensaje de 🤖 beto (@beto): ...' y el canon lo anotaba
# como bot; revision adversarial 2026-08-25).
MARCA_ENTRANTE = "Mensaje de 🤖 "

# Saltos del envelope que se esta procesando en ESTE hilo/contexto (None
# fuera de procesar_inbox). La tool mensaje_bot lo lee para que su envelope
# salga con hops+1: los hops son saltos de una CONVERSACION (Hermes: 3
# rondas), no una cuota temporal por par de bots (eso es el freno por
# ventana de la tool, que queda como freno ADICIONAL).
_HOPS_EN_CURSO: contextvars.ContextVar = contextvars.ContextVar(
    "cognia_bots_hops_en_curso", default=None)
# RESPALDO de proceso: (bot, hops) del turno en curso, puesto DENTRO de
# contexto(bot) (o sea, bajo registro.CANDADO_TURNO). Hace falta porque la
# tool NO corre en el hilo del turno: agent/tools.run_tool la manda por
# harness/timeout_tool.correr_con_deadline, que abre un Thread sin
# copy_context(), y ahi la ContextVar vale None. Medido en el e2e real
# 2026-08-25: beta respondio a alfa con hops 0 en vez de 1 mientras el test
# con agente falso (mismo hilo) pasaba. Bajo el candado solo hay un turno de
# bot en el proceso, asi que el respaldo es exacto mientras bot_en_turno()
# sea ese bot.
_HOPS_TURNO: list = [None]


def hops_en_curso():
    """Hops del envelope entrante que este turno esta respondiendo, o None si
    el turno no viene del inbox (usuario, API, rutina). Primero la ContextVar
    (hilo del turno o hijo con copy_context); si no, el respaldo del turno
    serializado (hilos de timeout_tool)."""
    v = _HOPS_EN_CURSO.get()
    if v is not None:
        return v
    par = _HOPS_TURNO[0]
    if par is None:
        return None
    from cognia.bots import registro as R
    nombre, hops = par
    return hops if R.bot_en_turno() == nombre else None

# Presupuestos del carril cerebro. nothink=True porque el 27B razonador se
# come max_tokens pensando y devuelve content vacio (nemotron-en-hermes.md,
# medido); _sin_pensamiento() es la red por si aun asi piensa.
MAX_TOKENS_CHAT = 1500
HISTORIAL_CHAT = 12          # eventos del canon que ve el cerebro

# Callable (bot, texto, ctx) -> str que reemplaza al modelo. Solo tests.
AGENTE_FALSO = None

_INSTANCIAS: dict = {}       # nombre de bot -> Cognia (headless, por proceso)
_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _bot(bot):
    """Bot desde un Bot o un nombre. ValueError ruidoso si no existe."""
    from cognia.bots import registro as R
    if isinstance(bot, R.Bot):
        return bot
    b = R.resolver(str(bot))
    if b is None:
        raise ValueError("bot desconocido: %r (ver /bots)" % (bot,))
    return b


def _agente_inyectado():
    """El agente falso, si lo hay. Un COGNIA_BOTS_AGENTE mal escrito es un
    error de CONFIGURACION: ValueError/ImportError/AttributeError ruidosos,
    nunca caer en silencio al modelo real (el test creeria que probo algo)."""
    if AGENTE_FALSO is not None:
        return AGENTE_FALSO
    spec = os.environ.get("COGNIA_BOTS_AGENTE", "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise ValueError(
            "COGNIA_BOTS_AGENTE debe ser 'modulo:funcion' (recibido %r)." % spec)
    mod, fn = spec.split(":", 1)
    modulo = importlib.import_module(mod)           # ImportError ruidoso
    return getattr(modulo, fn)                      # AttributeError ruidoso


def _max_hops(explicito=None) -> int:
    """Tope de saltos: parametro > COGNIA_BOTS_MAX_HOPS > mensajeria.MAX_HOPS.
    (El CLI siembra el env desde su config `bots_max_hops`.)"""
    from cognia.bots import mensajeria as M
    if explicito is not None:
        return int(explicito)
    crudo = os.environ.get("COGNIA_BOTS_MAX_HOPS", "").strip()
    if not crudo:
        return M.MAX_HOPS
    try:
        return max(0, int(crudo))
    except ValueError:
        raise ValueError("COGNIA_BOTS_MAX_HOPS debe ser un entero (recibido %r)." % crudo)


_CONFIG_APLICADA = False


def asegurar_config() -> None:
    """first_run.apply_config() UNA vez por proceso y FUERA de contexto(bot).
    Fuera a proposito: aunque contexto() hoy restaura SOLO las claves que
    toco (antes restauraba un snapshot entero y LLAMA_SERVER_PATH y compania
    desaparecian al terminar el primer turno: el segundo iba a simulacion),
    la config del proceso no es del bot y no tiene por que correr bajo su
    candado ni con su cwd."""
    global _CONFIG_APLICADA
    if _CONFIG_APLICADA:
        return
    from cognia.first_run import apply_config
    apply_config()
    _CONFIG_APLICADA = True


@contextlib.contextmanager
def entorno_rutinas(bot, lectura: bool = False):
    """El almacen de rutinas del bot (hermes/rutinas lee COGNIA_RUTINAS_DIR
    en cada llamada). Dos modos, porque os.environ es de todo el proceso:

    - lectura=False (tickear/ejecutar): entorno COMPLETO del bot serializado
      por registro.CANDADO_TURNO. Completo a proposito: rutinas.llamar_agente
      corre el agente en un HILO hijo, y ese hilo, al abrir contexto(bot),
      tiene que encontrar el bot ya en turno (registro._PILA) para no
      esperar un candado que tiene su propio padre.
    - lectura=True (listar/pendientes/ejecuciones, crear/borrar una rutina):
      solo COGNIA_RUTINAS_DIR, milisegundos, SIN esperar a CANDADO_TURNO.
      El roster, /api/bots y `estado` no pueden quedarse minutos detras de
      un turno del 27B (ver registro.entorno_lectura y su ventana asumida).
    """
    from cognia.bots import registro as R
    bot = _bot(bot)
    cm = R.entorno_lectura(bot) if lectura else R.entorno_aplicado(bot)
    with cm:
        yield bot


def instancia(bot, ai=None):
    """La Cognia headless del bot (o `ai` si el llamante trae la suya, p.ej.
    el REPL). Cache por nombre de bot: el daemon vuelve cada 60 s y no tiene
    que reconstruir nada. Debe llamarse DENTRO de contexto(bot) para que los
    subsistemas que leen COGNIA_DB_PATH/COGNIA_RUTINAS_DIR al construirse
    vean los almacenes del bot (asegurar_config() ya corrio fuera)."""
    if ai is not None:
        return ai
    from cognia.bots import registro as R
    bot = _bot(bot)
    with _LOCK:
        if bot.nombre in _INSTANCIAS:
            return _INSTANCIAS[bot.nombre]
        t0 = time.time()
        asegurar_config()
        from cognia.cognia import Cognia
        db_dir = R.ruta(bot, R.DIR_MEMORIA)
        db_dir.mkdir(parents=True, exist_ok=True)
        # Cognia() escribe su banner de init por stdout; en un daemon o en el
        # servidor remoto eso es ruido, igual que hace repl() con su buffer.
        with contextlib.redirect_stdout(io.StringIO()):
            ai = Cognia(db_path=str(db_dir / "cognia_memory.db"))
        logger.info("bots: Cognia headless de %s construida en %.2fs",
                    bot.nombre, time.time() - t0)
        _INSTANCIAS[bot.nombre] = ai
        return ai


def olvidar_instancias() -> None:
    """Vacia la cache (tests que cambian COGNIA_BOTS_DIR entre casos)."""
    with _LOCK:
        _INSTANCIAS.clear()


# ---------------------------------------------------------------------------
# Los dos carriles
# ---------------------------------------------------------------------------

def _via(texto: str, quien: str) -> str:
    """'agente' o 'cerebro'. Las rutinas siempre agente; los mensajes de OTRO
    bot tambien: la tool mensaje_bot solo existe en el carril agente, y en el
    cerebro el 27B escribia `mensaje_bot("alfa", ...)` como texto y
    procesar_inbox lo reenviaba tal cual (e2e 2026-08-25). Lo demas como el
    REPL (cognia.agent.intent.detect). Si el detector no carga se avisa y se
    conversa: preferible a inventar una accion."""
    if quien in ("rutina", "bot"):
        return "agente"
    try:
        from cognia.agent.intent import detect
        return "agente" if detect(texto).needs_agent else "cerebro"
    except Exception as exc:
        logger.warning("bots: intent.detect no disponible (%s: %s); va por chat",
                       type(exc).__name__, exc)
        return "cerebro"


def _turno_agente(bot, ctx, texto: str, ai, headless: bool, max_steps: int,
                  latir=None) -> str:
    from cognia import cli as _cli
    ai = instancia(bot, ai)

    def _mudo(linea):
        # Cada linea del agente es senal de vida para el timeout por
        # INACTIVIDAD de hermes/rutinas (no por reloj de pared).
        if latir:
            latir()

    print_fn = _mudo if headless else _cli._print_line
    permitidas = ctx.allowed_tools
    if permitidas is not None:
        # ROLE_TOOLS del implementador no conoce mensaje_bot (se registra solo
        # con COGNIA_BOT puesto): sin esto el bot no podria escribir a nadie.
        permitidas = set(permitidas) | {"mensaje_bot", "responder"}
    return _cli._run_agent_task(
        ai, texto, print_fn, max_steps=max_steps,
        guidance=ctx.sufijo_agente,          # <= 300 chars: respeta el A/B
        allowed_tools=permitidas) or ""


def _historial_chat(bot, saltar_ultimo: bool = True) -> str:
    """Los ultimos eventos del canon como texto plano (sin el que se acaba de
    anotar). Es el UNICO estado entre turnos del carril cerebro: la sesion es
    fresca (Hermes) y el canon es la memoria conversacional."""
    from cognia.bots import mensajeria as M
    # Los 'meta' se filtran ANTES de saltar el ultimo: los avisos del
    # contexto se anotan despues del texto del turno y, sin esto, el mensaje
    # nuevo entraria dos veces (en el historial y como "Mensaje nuevo").
    eventos = [e for e in M.transcripcion(bot, limite=HISTORIAL_CHAT * 2 + 1)
               if e.get("quien") != "meta"]
    if saltar_ultimo and eventos:
        eventos = eventos[:-1]
    lineas = []
    for e in eventos[-HISTORIAL_CHAT:]:
        quien = e.get("quien", "")
        etiqueta = "Tu" if quien == "cognia" else "Usuario" if quien == "usuario" else quien
        lineas.append("%s: %s" % (etiqueta, str(e.get("texto", ""))[:1500]))
    return "\n".join(lineas)


def _turno_cerebro(bot, ctx, texto: str, ai, headless: bool, latir=None) -> str:
    from cognia import cli as _cli
    ai = instancia(bot, ai)
    orch = getattr(ai, "_orchestrator", None)
    previo = _historial_chat(bot)
    prompt = texto if not previo else (
        "Conversacion previa (la mas reciente al final):\n%s\n\n"
        "Mensaje nuevo:\n%s" % (previo, texto))
    if latir:
        latir()
    respuesta = ""
    if orch is not None:
        try:
            crudo = orch.infer(prompt, system=ctx.system_cerebro,
                               max_tokens=MAX_TOKENS_CHAT, nothink=True).text
            respuesta = _cli._sin_pensamiento(crudo or "")
        except Exception as exc:
            logger.warning("bots: orch.infer fallo para %s (%s: %s); pruebo llm_local",
                           bot.nombre, type(exc).__name__, exc)
            respuesta = ""
    if latir:
        latir()
    if not respuesta or any(m in respuesta for m in _cli._SIN_BACKEND):
        # Mismo respaldo que _inferir_para_agente: el orquestador busca shards
        # u Ollama; el backend real de esta maquina lo detecta llm_local.
        from cognia.llm_local import generar
        alt = generar(prompt, system=ctx.system_cerebro, temperature=0.4,
                      max_tokens=MAX_TOKENS_CHAT)
        respuesta = _cli._sin_pensamiento(alt or "")
    if not respuesta:
        # Visible en el canon y para quien llamo; jamas un "" que parezca que
        # el bot decidio callarse.
        respuesta = ("[%s no pudo responder: sin backend LLM vivo o el modelo "
                     "gasto el presupuesto razonando]" % bot.nombre)
    return respuesta


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def correr_turno(bot, texto: str, ai=None, headless: bool = True,
                 max_steps: int = 8, quien: str | None = None,
                 etiqueta: str = "", texto_canon: str | None = None,
                 latir=None, agente=None, hops_entrante: int | None = None) -> str:
    """UN turno del bot en su contexto. Anota entrada y salida en el canon.

    hops_entrante: hops del envelope que se responde (solo procesar_inbox);
           durante el turno lo expone hops_en_curso() y la tool mensaje_bot
           manda con hops+1. None = turno que no viene del inbox.

    quien: 'usuario' (default: usuario, REPL o API, AUNQUE el texto empiece
           por 'Mensaje de 🤖'), 'bot' (SOLO lo pone procesar_inbox, que
           tiene el envelope) o 'rutina'. etiqueta: se antepone entre
           corchetes en el canon ("[rutina vigia] ..."). texto_canon: lo que
           se anota en vez del texto integro (una rutina anota su
           instruccion, no el prompt con el preambulo). headless=False: el
           llamante es el REPL y quiere ver el agente (y los avisos del
           contexto) en pantalla. agente: callable falso (bot, texto, ctx)
           -> str (tests); tambien via COGNIA_BOTS_AGENTE.
    """
    from cognia.bots import registro as R, mensajeria as M
    bot = _bot(bot)
    texto = (texto or "").strip()
    if not texto:
        return ""
    quien = (quien or "usuario").strip() or "usuario"
    visible = (texto_canon if texto_canon is not None else texto).strip()
    if etiqueta:
        visible = "[%s] %s" % (etiqueta, visible)
    M.anotar_canon(bot, quien, visible)

    t0 = time.time()
    falso = agente or _agente_inyectado()
    if falso is None:
        asegurar_config()                 # fuera del contexto: ver docstring
    with R.contexto(bot, canon=True) as ctx:
        for aviso in ctx.avisos:
            M.anotar_canon(bot, "meta", "aviso: %s" % aviso)
            if not headless:
                # El REPL tiene que VER el aviso (p.ej. 'modelo pinneado X no
                # esta servido'), no solo encontrarlo luego en el canon.
                from cognia import cli as _cli
                _cli._print_line("[warn_cl]@%s: %s[/warn_cl]"
                                 % (bot.nombre, _cli._escape(aviso)))
        # Los hops del envelope: ContextVar (este hilo) + respaldo de proceso
        # (hilos de timeout_tool), ambos DENTRO del contexto = bajo el candado.
        token_hops = _HOPS_EN_CURSO.set(hops_entrante)
        _HOPS_TURNO[0] = (bot.nombre, hops_entrante) if hops_entrante is not None else None
        try:
            if falso is not None:
                logger.warning("bots: turno de %s con AGENTE FALSO (%s)",
                               bot.nombre, getattr(falso, "__name__", falso))
                respuesta = falso(bot, texto, ctx)
            elif _via(texto, quien) == "agente":
                respuesta = _turno_agente(bot, ctx, texto, ai, headless,
                                          max_steps, latir=latir)
            else:
                respuesta = _turno_cerebro(bot, ctx, texto, ai, headless,
                                           latir=latir)
        except Exception as exc:               # visible en el canon, no propaga
            logger.exception("bots: el turno de %s rompio", bot.nombre)
            respuesta = "[error del turno de %s: %s: %s]" % (
                bot.nombre, type(exc).__name__, exc)
        finally:
            _HOPS_TURNO[0] = None
            _HOPS_EN_CURSO.reset(token_hops)
    respuesta = (respuesta or "").strip() if isinstance(respuesta, str) else str(respuesta or "")
    M.anotar_canon(bot, "cognia", respuesta or "(sin respuesta)")
    logger.info("bots: turno de %s (%s) en %.1fs", bot.nombre, quien, time.time() - t0)
    return respuesta


def correr_rutina(bot, prompt: str, rutina, latir=None, ai=None) -> str:
    """Contrato fn(prompt, rutina[, latir]) -> str de cognia.hermes.rutinas.
    `prompt` es el prompt EFECTIVO (con el preambulo de rutina y el stdout del
    script); en el canon se anota la instruccion original de la rutina."""
    nombre = rutina.get("nombre", "?") if isinstance(rutina, dict) else str(rutina)
    original = rutina.get("prompt") if isinstance(rutina, dict) else None
    return correr_turno(bot, prompt, ai=ai, headless=True, quien="rutina",
                        etiqueta="rutina %s" % nombre,
                        texto_canon=original or prompt, latir=latir)


def agente_de_rutina(bot, ai=None):
    """El correr_agente_fn que se le inyecta a rutinas.tick para este bot."""
    bot = _bot(bot)

    def _fn(prompt, rutina, latir=None):
        return correr_rutina(bot, prompt, rutina, latir=latir, ai=ai)
    return _fn


def _entregar(bot, corridas: list) -> list:
    """Entrega de las corridas de rutinas: el canon ya tiene la respuesta
    (correr_turno la anoto); aqui va lo que correr_turno NO vio: fallos que
    rutinas cerro por su cuenta (timeout de inactividad, excepcion) y el
    canal 'inbox' (NotificationCenter user_id 'bot:<n>', como los mensajes
    entre bots). Devuelve las lineas para consola."""
    from cognia.bots import mensajeria as M
    lineas = []
    for c in corridas:
        salida = (c.get("salida") or "").strip()
        if not salida:
            continue
        if c.get("estado") == "fallida":
            M.anotar_canon(bot, "meta", "rutina %s: %s" % (c.get("rutina"), salida))
        lineas.append("[%s] rutina %s: %s" % (bot.nombre, c.get("rutina"), salida))
        if c.get("entregar") == "inbox":
            if os.environ.get("COGNIA_BOTS_NOTIF", "").strip().lower() in ("0", "off", "no"):
                continue
            try:
                from cognia.notifications.notification_center import NotificationCenter
                NotificationCenter().create(
                    user_id="bot:%s" % bot.nombre,
                    title="Rutina %s de @%s" % (c.get("rutina"), bot.nombre),
                    body=salida[:500], level="info", source="system")
            except Exception as exc:
                M.anotar_canon(bot, "meta", "aviso: notificacion no creada (%s: %s)"
                               % (type(exc).__name__, exc))
    return lineas


def tick_bot(bot, ahora=None, ai=None) -> dict:
    """Una vuelta del reloj de rutinas de ESTE bot (en su contexto: rutinas
    lee COGNIA_RUTINAS_DIR en cada llamada). Devuelve el informe de tick con
    la clave extra 'lineas' (entregas para consola)."""
    from cognia.hermes import rutinas
    with entorno_rutinas(bot) as bot:
        informe = rutinas.tick(ahora, agente_de_rutina(bot, ai))
    informe["lineas"] = _entregar(bot, informe.get("corridas", []))
    return informe


def correr_rutina_ahora(bot, nombre: str, ai=None) -> dict:
    """Corre YA una rutina del bot (fuera de horario) y re-arma la siguiente.
    Es lo que usan '/bots rutina ahora <n>', la API y `daemon --forzar`.
    ValueError si no existe."""
    from cognia.hermes import rutinas
    with entorno_rutinas(bot) as bot:
        r = rutinas.obtener(nombre)
        if r is None:
            raise ValueError("el bot %s no tiene una rutina %r" % (bot.nombre, nombre))
        informe = rutinas.ejecutar(r, agente_de_rutina(bot, ai))
        rutinas.marcar_corrida(nombre, informe["estado"], detalle=informe.get("detalle"))
    informe["lineas"] = _entregar(bot, [informe] if informe.get("entregado") else [])
    return informe


def crear_rutina_bot(bot, horario: str, prompt: str, nombre: str | None = None,
                     **extra) -> dict:
    """Crea una rutina EN EL ALMACEN DEL BOT con nombre unico y el workdir
    del bot. Es la API para /bots rutina add y la API remota:
      - nombre: el pedido, o rutinas.nombre_libre() ('rutina-<max+1>'; el
        'rutina-{len+1}' de antes colisionaba tras un rm: revision
        adversarial 2026-08-25).
      - workdir: bot.workdir salvo que `extra` traiga otro (rutinas.ejecutar
        corre el script ahi y avisa si la carpeta ya no existe).
      - bot=bot.nombre (etiqueta informativa que sale en listar()).
    ValueError ruidoso de rutinas.crear si el horario/prompt no sirven."""
    from cognia.hermes import rutinas
    with entorno_rutinas(bot, lectura=True) as bot:
        if not nombre:
            nombre = rutinas.nombre_libre()
        extra.setdefault("workdir", bot.workdir or None)
        return rutinas.crear(nombre, horario, prompt, bot=bot.nombre, **extra)


# '(pass)' es la marca de los GRUPOS de Hermes; el protocolo pide [SILENT]
# pero un modelo que aprendio '(pass)' no puede gastar un turno del otro bot.
_MARCAS_PASS = frozenset({"(pass)", "pass", "(paso)", "paso"})


def es_silencio_bot(respuesta) -> bool:
    """True si la respuesta pide NO reenviar: [SILENT]/NO_REPLY de
    hermes/rutinas.es_silencio, o un '(pass)' que ocupa la respuesta entera
    (o su primera/ultima linea)."""
    from cognia.hermes.rutinas import es_silencio
    if not isinstance(respuesta, str) or not respuesta.strip():
        return False
    if es_silencio(respuesta):
        return True
    lineas = [l.strip().lower() for l in respuesta.strip().splitlines() if l.strip()]
    return bool(lineas) and (lineas[0] in _MARCAS_PASS or lineas[-1] in _MARCAS_PASS)


# Prefijos con que un turno FALLIDO vuelve como texto: el propio correr_turno
# ('[error del turno de x: ...]') y el cierre por presupuesto del bucle del
# agente (cli/agent: '(cerrada sin progreso verificado: ...)').
_PREFIJOS_FALLO = ("[error del turno de ", "(cerrada sin progreso verificado")


def es_fallo_de_turno(respuesta) -> bool:
    """True si la 'respuesta' es en realidad el informe de un turno que no
    corrio (no se reenvia a otro bot; queda en el canon como meta)."""
    if not isinstance(respuesta, str):
        return False
    r = respuesta.strip()
    return any(r.startswith(p) for p in _PREFIJOS_FALLO)


def procesar_inbox(bot, ai=None, max_hops=None, agente=None) -> int:
    """Corre un turno por cada envelope pendiente y lo marca entregado. Si el
    emisor es un bot, la respuesta se le reenvia con hops+1 (salvo que el bot
    ya le haya escrito durante el turno con la tool mensaje_bot, o que la
    respuesta sea [SILENT], o que se toque max_hops: entonces se anota el
    motivo en el canon y la conversacion termina ahi). Devuelve cuantos
    proceso."""
    from cognia.bots import registro as R, mensajeria as M
    bot = _bot(bot)
    tope = _max_hops(max_hops)
    n = 0
    for m in M.pendientes(bot):
        emisor = (m.get("de") or "").strip()
        emisor_bot = R.resolver(emisor) if emisor else None
        antes = set()
        if emisor_bot is not None:
            antes = {e.get("id") for e in M.pendientes(emisor_bot)}
        # Los hops del envelope entran al turno (hops_en_curso): la tool
        # mensaje_bot responde con hops+1, igual que el reenvio de abajo.
        hops_m = int(m.get("hops", 0) or 0)
        respuesta = correr_turno(bot, M.formatear_entrante(m), ai=ai, quien="bot",
                                 agente=agente, hops_entrante=hops_m)
        M.marcar_entregado(bot, m["id"])
        n += 1
        if emisor_bot is None:
            continue                      # el usuario lee el canon; nada que reenviar
        ya_escrito = any(e.get("de") == bot.nombre and e.get("id") not in antes
                         for e in M.pendientes(emisor_bot))
        if ya_escrito:
            M.anotar_canon(bot, "meta", "(ya le escribio a @%s en el turno)" % emisor_bot.nombre)
            continue
        if not respuesta or es_silencio_bot(respuesta):
            M.anotar_canon(bot, "meta", "(sin respuesta para @%s)" % emisor_bot.nombre)
            continue
        if es_fallo_de_turno(respuesta):
            # e2e 2026-08-25: un turno cerrado por el presupuesto del agente
            # ('(cerrada sin progreso verificado: sin_arranque)') viajaba como
            # mensaje al otro bot, que gastaba SU turno contestando a un error.
            M.anotar_canon(bot, "meta", "(turno fallido, no se reenvia a @%s: %s)"
                           % (emisor_bot.nombre, respuesta[:120].replace("\n", " ")))
            continue
        r = M.enviar(de=bot.nombre, para=emisor_bot.nombre, texto=respuesta,
                     hops=int(m.get("hops", 0)) + 1, max_hops=tope)
        if r.get("ok"):
            M.anotar_canon(bot, "meta", "-> @%s (id %s, hops %d)"
                           % (emisor_bot.nombre, r.get("id"), int(m.get("hops", 0)) + 1))
        else:
            M.anotar_canon(bot, "meta", "(no reenviado a @%s: %s)"
                           % (emisor_bot.nombre, r.get("motivo")))
    return n
