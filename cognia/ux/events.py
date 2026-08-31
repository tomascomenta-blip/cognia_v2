"""
cognia/ux/events.py
===================
El embudo UNICO de eventos del turno (2026-08-09).

POR QUE EXISTE: Cognia tenia CUATRO canales de salida sin coordinar
(_print_line/rich, logger a stderr, prints crudos [degradado]/[backend], y
prints sueltos de tools/modulos). El CLI mezclaba todo en pantalla y el remoto
lo re-clasificaba por regex sobre stdout — cualquier limpieza del CLI rompia
el movil. Este modulo invierte la dependencia: el loop del agente y el
fast-path EMITEN eventos tipados; quien decide que se ve es el consumidor
(renderer del CLI, sink JSONL para el remoto, nada para tests).

Contrato (acordado entre WP1/WP3/WP4 de la obra 2026-08-09):

- Los productores llaman ``emitir(<Evento>)`` y NUNCA imprimen directo.
- ``emitir`` es NO-LANZANTE por contrato: un suscriptor roto no puede romper
  un turno (misma regla que ux/estilo.py: el adorno jamas re-ejecuta ni
  aborta la sustancia).
- Los consumidores se registran con ``suscribir(fn)``; reciben el dataclass.
- El remoto consume el mismo bus via ``activar_sink_jsonl()`` (una linea JSON
  por evento) — mismo bus, otro sink; jamas volver al regex sobre stdout.

Solo stdlib. Sin dependencias de rich ni del CLI: este modulo esta DEBAJO de
todos y no importa nada de cognia (evita ciclos de import con cli.py).
"""
from __future__ import annotations

import contextvars
import dataclasses
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# La IDENTIDAD del agente en curso, sellada en TODOS los eventos que se emitan
# dentro de su contexto. POR QUE ambiental y no un campo mas en cada evento:
# el unico productor real de TokenTexto (node/llama_backend.py:1137) es el
# generador de streaming del backend y NO sabe nada de workflows — pedirle que
# arrastre un id seria cablear el motor de workflows dentro del backend. Un
# ContextVar se sella en agente() y viaja gratis a cada evento hijo.
# ContextVar y no threading.local a proposito: un hilo NUEVO de
# ThreadPoolExecutor arranca con contexto VACIO, asi que el id del hilo padre
# jamas se filtra a un thunk de paralelo() — que es exactamente la carrera que
# hay que evitar con cap=2.
# ---------------------------------------------------------------------------

_agente_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cognia_agente_id", default="")


def agente_actual() -> str:
    return _agente_ctx.get()


def marcar_agente(agente_id: str):
    """Sella el agente_id en el contexto. Devuelve el token para reset()."""
    return _agente_ctx.set(agente_id or "")


def desmarcar_agente(token) -> None:
    try:
        _agente_ctx.reset(token)
    except Exception:
        pass            # contrato del bus: el adorno jamas rompe el turno


# ---------------------------------------------------------------------------
# Los eventos del turno. Pocos y estables: agregar uno es tocar el contrato
# (avisar en el docstring y a los consumidores), no un cajon de sastre.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Evento:
    """Base: todos llevan timestamp; el tipo va implicito en la clase."""
    ts: float = field(default_factory=time.time, init=False)
    # Quien lo produjo, si se emitio dentro de un agente de workflow ("" si no).
    # init=False + default_factory: NINGUN productor cambia, y TokenTexto queda
    # correlacionado con su agente el dia que el panel lo pida.
    agente_id: str = field(default_factory=agente_actual, init=False)


@dataclass(frozen=True)
class TareaInicio(Evento):
    """Arranca una tarea del agente (/hacer) o un turno de chat."""
    tarea: str = ""
    modo: str = "agente"        # "agente" | "chat"
    modelo: str = ""            # el GGUF/alias que va a responder de verdad


@dataclass(frozen=True)
class PasoIntencion(Evento):
    """El agente decidio que va a hacer en este paso (1 linea legible)."""
    paso: int = 0
    intencion: str = ""         # p.ej. "Voy a leer motor.py para ver la firma"


@dataclass(frozen=True)
class ToolInicio(Evento):
    tool: str = ""
    args: str = ""              # forma corta legible (ruta, comando…)
    paso: int = 0


@dataclass(frozen=True)
class ToolFin(Evento):
    tool: str = ""
    args: str = ""
    ok: bool = True
    resumen: str = ""           # 1-3 lineas: "42 lineas", "exit 0", diff corto
    duracion_s: float = 0.0
    paso: int = 0


@dataclass(frozen=True)
class TokenTexto(Evento):
    """Trozo de la respuesta final en streaming (prosa del asistente)."""
    texto: str = ""


@dataclass(frozen=True)
class RazonamientoTick(Evento):
    """El modelo esta pensando (reasoning_content fluyendo): alimenta el
    indicador 'pensando… (Ns)'. chars acumulados, no el contenido entero."""
    chars: int = 0
    fragmento: str = ""         # ultimo trozo, por si el renderer lo muestra


@dataclass(frozen=True)
class TokensVivos(Evento):
    """Llegaron `chars` del stream y NO hay que pintarlos: solo contarlos.

    POR QUE EXISTE (2026-08-31, pedido del dueno: "que me aparezcan los tokens
    en el modo agente, no solo el chat normal"). El contador `~N tok` de la
    linea viva se alimenta de `TokenTexto` y `RazonamientoTick`, y los dos son
    eventos de PINTAR: el chat los emite porque ademas streamea esa prosa. El
    bucle del agente no puede emitirlos — su texto no se pinta token a token y
    sus tool calls no son prosa — asi que en modo agente el contador se quedaba
    en cero y el spinner solo decia los segundos. Este evento separa las dos
    cosas: es un pulso de CONTABILIDAD, sin contenido que mostrar.

    `fase` es informativa ('razonando' | 'escribiendo' | 'respondiendo'): el
    renderer no la usa hoy, pero el sink de telemetria distingue con ella un
    turno que se fue en pensar de uno que se fue escribiendo un fichero.
    """
    chars: int = 0
    fase: str = ""


@dataclass(frozen=True)
class Aviso(Evento):
    """Algo que el usuario deberia poder ver pero no rompe el turno."""
    texto: str = ""
    origen: str = ""            # modulo que lo emite, p.ej. "llama_backend"


@dataclass(frozen=True)
class Degradado(Evento):
    """Una via se degrado (backend caido, fallback a modelo menor…).
    SIEMPRE va tambien a telemetria: la degradacion silenciosa es el modo de
    fallo historico de Cognia."""
    donde: str = ""
    motivo: str = ""
    accion_sugerida: str = ""   # p.ej. "python scripts/servir_flota.py pensar"


@dataclass(frozen=True)
class TareaFin(Evento):
    ok: bool = True
    resumen: str = ""           # la respuesta final o el motivo del fallo
    pasos: int = 0
    tokens_predichos: int = 0   # usage REAL del backend, no len//4
    duracion_s: float = 0.0
    # Por que se cerro el turno cuando NO fue por respuesta ('parado: 3 tools
    # seguidas fallaron', 'presupuesto agotado: techo 12'); "" en el cierre
    # normal. Va al footer: UNA linea en vez de aviso + log + prosa
    # (juez 2026-08-24).
    motivo: str = ""


@dataclass(frozen=True)
class Confianza(Evento):
    """El nivel de confianza de UNA respuesta de chat (cognia/agent/
    confianza_chat.py), como DATO y no como prosa.

    POR QUE existe (paridad remota 2026-08-24): cli.py imprimia la linea
    '● confianza ALTA (0,90) · 2 fuentes: ...' con _print_line, y bajo
    COGNIA_REMOTO=1 todo el subsistema estaba APAGADO por un guard
    (_confianza_remoto) porque esa prosa llegaba al chat del movil como si
    fuera otra respuesta. Con el evento, el remoto pinta un chip bajo la
    burbuja y la investigacion vuelve a correr tambien desde el telefono.
    ``texto`` es la linea legible entera (la misma que ve el terminal), para
    un consumidor que no quiera armarla; los demas campos son para el que si."""
    nivel: str = ""             # alta | media | baja | nula
    glifo: str = ""             # ● ◐ ○ ✕
    valor: float = 0.0          # la confianza numerica [0, 1]
    fuentes: list = field(default_factory=list)   # dominios que sostienen
    texto: str = ""             # la linea completa, legible


@dataclass(frozen=True)
class FooterTurno(Evento):
    """El cierre de un turno de CHAT: lo que cli._show_footer pinta como
    '✓ 14.6s · 312 tokens · ctx 95% libre', como dato.

    Distinto de TareaFin a proposito: TareaFin es el cierre del AGENTE (pasos,
    resumen) y lo emite el loop; el chat no pasa por ahi y su footer vivia
    solo en el terminal. Bajo COGNIA_REMOTO el REPL sigue imprimiendo la
    version plana ('14.6s · 312 tokens', que sesiones.py de-duplica por
    _RE_FOOTER_RENDERER) y ADEMAS emite esto: el movil muestra la linea gris
    a partir del evento, no de la prosa. ``ctx_libre_pct`` None = no se sabe
    (sin n_ctx del backend), nunca un 0 inventado."""
    ok: bool = True
    segundos: float = 0.0
    tokens: int = 0             # usage REAL del backend; 0 = no se conoce
    ctx_libre_pct: Optional[float] = None
    motivo: str = ""            # por que se cerro si no fue por respuesta


# ---------------------------------------------------------------------------
# Los eventos del MOTOR DE WORKFLOWS (cognia/agent/workflows.py). Una tarea del
# agente puede contener varios workflows, y un workflow varios agentes: por eso
# son eventos aparte de TareaInicio/TareaFin y no un campo de estos.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowInicio(Evento):
    """Arranca una corrida de cognia/agent/workflows.py."""
    run_id: str = ""              # id de la corrida = nombre del dir del journal
    nombre: str = ""              # etiqueta logica: "repl", "agente", "e2e-smoke"
    total_agentes: int = 0        # cuantos se van a lanzar; 0 = no se sabe aun
    presupuesto_tokens: int = 0   # techo compartido; 0 = sin techo
    resume_de: str = ""           # run_id del que se resumio ("" si ninguno)
    cache_precargada: int = 0     # claves servidas sin pagar
    # True si la corrida acepta control por agente (cancelar / hablarle en
    # curso). El panel lo necesita para decidir si dibuja el boton
    # "interrumpir y decir": ofrecerlo en una corrida batch seria mentir, y
    # esconderlo en una interactiva seria enterrar la unica salida.
    interactivo: bool = False


@dataclass(frozen=True)
class AgenteInicio(Evento):
    """Arranca UN agente() del motor, ANTES de mirar la cache y el backend."""
    run_id: str = ""
    # "<run_id>#<fase>.<indice>@<n>" — la clave de correlacion. El sufijo
    # "@<n>" es el contador MONOTONO de la corrida y es lo que hace el id
    # UNICO: indice/fase se repiten (dos criticar() sobre la misma Corrida
    # usan indice=1..3 las dos veces), n no. Ver el comentario largo en
    # workflows.agente().
    agente_id: str = ""
    indice: int = 0         # 1-based, el numero LOGICO que se muestra ("2 de 6")
    total: int = 0          # cuantos en esta FASE; 0 = no se sabe
    fase: str = ""          # "pasos" | "critica" | "suelto"
    etiqueta: str = ""      # <=60 chars, UNA linea: el paso o el nombre de la lente
    rol: str = ""           # "" (cerebro) | "worker"
    clave: str = ""         # sha256 de _clave_cache: une con la linea del journal
    # True si el evento se emitio DESPUES de WorkflowFin: es un HUERFANO de
    # paralelo() (un thunk que sobrevivio al timeout y sigue vivo). El
    # consumidor tiene que saberlo para no colgarlo de un workflow que ya
    # cerro; sin este campo se enteraba por sorpresa. Ver AgenteFin.tardio.
    tardio: bool = False


@dataclass(frozen=True)
class AgenteFin(Evento):
    """Cierra UN agente(). Se emite SIEMPRE (finally), incluidos cache-hit,
    presupuesto agotado, error del backend, truncado y excepcion."""
    run_id: str = ""
    agente_id: str = ""
    # indice/total/fase/etiqueta se REPITEN a proposito: interpretar_evento()
    # del remoto es una funcion sin estado y no puede recordar el Inicio.
    indice: int = 0
    total: int = 0
    fase: str = ""
    etiqueta: str = ""
    ok: bool = True         # False si el resultado lleva "_error"
    # El "_error" tal cual; "" si ok. En el camino de EXCEPCION lleva el error
    # REAL ("RuntimeError: backend caido"), no un generico: "revento" y
    # "devolvio vacio" piden decisiones opuestas y el evento es la unica
    # constancia que le llega al consumidor.
    motivo: str = ""
    cache_hit: bool = False  # sirvio de cache: no se pago nada
    tokens: int = 0         # prompt+completion REALES sumando los reintentos
    intentos: int = 0       # llamadas al LLM que costo (0 = no se llamo)
    duracion_s: float = 0.0
    url: str = ""           # backend efectivo; "" si no se llego a resolver
    rol: str = ""
    resumen: str = ""       # cabecera del resultado, <=200 chars ("" si fallo)
    # True si el Fin llego DESPUES de WorkflowFin: el agente es un huerfano de
    # paralelo() que siguio vivo tras el timeout. No se puede esperar a los
    # huerfanos (por eso existen), asi que la salida honesta es DECLARARLOS:
    # el consumidor que reciba tardio=True sabe que esta fila no pertenece a
    # ningun workflow abierto y no debe re-abrir el que ya cerro.
    tardio: bool = False
    # CONTROL POR AGENTE (2026-08-17). NO se creo un evento terminal nuevo
    # (AgenteCancelado) a proposito: rompeia el invariante "un agente que
    # arranca termina con UN AgenteFin" que los dos renderers dan por bueno.
    # Un agente cancelado sale por aca, con ok=False y cancelado=True.
    cancelado: bool = False
    # Cuantas veces se le hablo en curso ("cortar y volver a preguntar"). >0
    # significa que su resultado NO se cacheo: en un resume se vuelve a pagar.
    repreguntas: int = 0
    # Chars de respuesta que se TIRARON al cortar. Es el coste visible de
    # interrumpir: el modelo no ve lo que ya habia escrito y puede repetirlo.
    descartado_chars: int = 0


@dataclass(frozen=True)
class MensajeAlAgente(Evento):
    """El usuario le habla a un agente EN CURSO. Lo emite decirle(), SIEMPRE:
    tambien cuando el mensaje se RECHAZA — un mensaje descartado en silencio
    es peor que uno rechazado a la vista."""
    run_id: str = ""
    destino: str = ""        # el agente_id al que va (NO es el emisor: el
                             # campo heredado agente_id sella QUIEN lo emitio,
                             # que normalmente es "" porque lo llama la UI)
    texto: str = ""
    aceptado: bool = False
    estado: str = ""         # conjunto cerrado: ver workflows.ESTADOS_CONTROL
    # MENSAJES en cola para ese agente, y NADA MAS. El envelope de control
    # usaba esta misma palabra para tres cosas (mensajes, agentes vivos,
    # corridas alcanzadas) hasta el defecto #4 del 2026-08-17; aca siempre
    # significo mensajes y ahora alla tambien.
    pendientes: int = 0


@dataclass(frozen=True)
class AgenteProgreso(Evento):
    """Latido de un agente que esta generando. THROTTLEADO (250 ms / 400
    chars). Existe para el sink stdout, que salta TokenTexto por una razon
    MEDIDA (2026-08-09: la linea-evento pegada a media frase del renderer en
    el mismo stdout): sin esto el movil no puede saber que hay algo que
    interrumpir. Regla general: se throttlea el PROGRESO, jamas el CONTENIDO."""
    run_id: str = ""
    chars: int = 0           # acumulados de content en ESTA llamada
    chars_razonamiento: int = 0
    intento: int = 0


@dataclass(frozen=True)
class WorkflowFin(Evento):
    """Cierra la corrida. Lo emite Corrida.cerrar(), una sola vez.

    SEMANTICA DE LOS CONTADORES (cambiada 2026-08-17, ver workflows.cerrar()):
    ``agentes`` es el DENOMINADOR HONESTO —max(arrancados, declarados)— y no
    "cuantos AgenteInicio se emitieron". Con la semantica vieja, una corrida de
    4 pasos donde 3 futuros murieron por timeout sin llegar a arrancar salia
    como ``agentes=1 fallidos=0`` y el consumidor pintaba "1 de 1": exito sobre
    una corrida que perdio el 75%. Los que no arrancaron y los que quedaron
    colgando cuentan como fallidos, de modo que ``agentes - fallidos`` sigue
    siendo "cuantos terminaron BIEN" en las dos formulas de presentacion
    (ux/renderer.py y remoto/sesiones.py).
    """
    run_id: str = ""
    nombre: str = ""
    ok: bool = True
    agentes: int = 0        # denominador honesto: max(arrancados, declarados)
    fallidos: int = 0       # AgenteFin ok=False + no_arrancados + colgando
    cache_hits: int = 0
    tokens: int = 0         # presupuesto.gastado() REAL
    # Cuantos de `tokens` NO los dijo el server sino que se estimaron
    # (timings.predicted_n, o los frames de contenido de una llamada cortada).
    # Se cobran igual —son tokens que se pagaron— pero un consumidor que
    # presente el gasto tiene que poder decir cuanto del numero es medido.
    # Antes de esto (defecto #5, 2026-08-17) los cortes valian CERO: medido
    # con /tokenize, ~88 tokens por corte y una sub-cuenta del 56%.
    tokens_estimados: int = 0
    presupuesto_tokens: int = 0
    duracion_s: float = 0.0
    resumen: str = ""       # motivo del cierre si no ok; "" si ok
    # El desglose, para el consumidor que quiera decir MAS que "0 de 4".
    total_agentes: int = 0  # lo que el caller declaro en corrida(); 0 = no dijo
    arrancados: int = 0     # cuantos AgenteInicio se emitieron (la cuenta vieja)
    no_arrancados: int = 0  # declarados que nunca llegaron a emitir AgenteInicio
    colgando: int = 0       # arrancaron y al cerrar no habian emitido AgenteFin
    # Cancelados por el usuario. Si > 0 el cierre va con ok=False y el motivo
    # en `resumen`: mismo criterio que colgando/no_arrancados — las dos
    # formulas de presentacion ya cortan por ok y no hay que ensenarles un
    # campo nuevo para que dejen de pintar exito.
    cancelados: int = 0


# ---------------------------------------------------------------------------
# El bus: modulo-global, thread-safe, no-lanzante.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_suscriptores: list[Callable[[Evento], None]] = []


def suscribir(fn: Callable[[Evento], None]) -> None:
    with _lock:
        if fn not in _suscriptores:
            _suscriptores.append(fn)


def desuscribir(fn: Callable[[Evento], None]) -> None:
    with _lock:
        if fn in _suscriptores:
            _suscriptores.remove(fn)


def emitir(evento: Evento) -> None:
    """Reparte el evento a todos los suscriptores. Nunca lanza: un consumidor
    roto se ignora (el turno del usuario vale mas que el adorno)."""
    with _lock:
        actuales = list(_suscriptores)
    for fn in actuales:
        try:
            fn(evento)
        except Exception:
            pass


def a_dict(evento: Evento) -> dict:
    """Serializa un evento a dict plano con su tipo, listo para JSON."""
    d = dataclasses.asdict(evento)
    d["tipo"] = type(evento).__name__
    return d


# ---------------------------------------------------------------------------
# Sink JSONL (el canal del remoto y de la telemetria de sesion).
# ---------------------------------------------------------------------------

_sink_jsonl: Optional[object] = None

# Prefijo de las lineas-evento en el modo stdout ('1'). POR QUE: el stdout del
# CLI mezcla la prosa (respuesta final, ecos de tools) con los eventos, y una
# linea que empieza en '{' NO basta para distinguirlos — el agente lee y
# muestra ficheros JSON con toda naturalidad (proyectos.json, transcripciones)
# y esas lineas se reinterpretarian como eventos. El prefijo hace la
# clasificacion determinista. Consumidor: cognia/remoto/sesiones.py.
# El modo archivo NO lleva prefijo: ahi el fichero entero es JSONL puro.
PREFIJO_STDOUT = "@EV "

# Candado PROPIO del canal stdout (no se reusa _lock, que gobierna la lista de
# suscriptores: anidarlos abre un interbloqueo el dia que un sink suscriba).
# RLock y no Lock: si algun suscriptor llegara a emitir DENTRO del reparto, un
# Lock se auto-bloquearia y congelaria el turno entero — precio absurdo para un
# candado que solo esta para que dos hilos no partan una linea. El anidamiento
# no rompe la atomicidad: cada write() completo pasa antes de volver.
_lock_stdout = threading.RLock()


def _stdout_real():
    """A donde escribe el sink stdout: el stdout REAL cuando es un PIPE (el
    canal del movil), y el ``sys.stdout`` del momento cuando es un TERMINAL.

    POR QUE (medido 2026-08-17 sobre textual 8.2.8): con una App de Textual
    corriendo, ``sys.stdout`` es un ``textual.app._PrintCapture`` cuyo write()
    va a ``App._print()``. Ahi (textual/app.py:2097-2105) el texto solo
    sobrevive si el modo es HEADLESS (reenvio de cortesia del arnes de tests) o
    si algun widget pidio ``begin_capture_print``. En la app real no pasa ni
    una cosa ni la otra: el texto se DESCARTA. Y ``_PrintCapture.flush()``
    tampoco llega al stream real (``App._flush`` solo avisa a devtools), asi
    que el flush por linea se perdia igual.

    Quien lo paga: ``cognia/remoto/sesiones.py`` lanza el REPL con
    COGNIA_EVENTS_JSONL=1 y lee ESTE stdout linea a linea — es su UNICO canal.
    Con la vista de agentes abierta el telefono se quedaba ciego, y esa vista
    existe justamente para que el telefono vea el progreso por agente.

    ``sys.__stdout__`` puede ser None (pythonw, algunos empaquetados): se cae a
    ``sys.stdout``, que es exactamente a donde escribia el print() de antes —
    nunca peor que hoy. Si tampoco hay, devuelve None y no se escribe nada.

    LO QUE ESTO CUESTA, declarado: escribir al stdout real ignora TODA
    redireccion del proceso, incluida la de ``contextlib.redirect_stdout`` que
    cli.py:1558 pone alrededor de cada comando (ahi los eventos tambien se
    perdian: mismo bug, otra tapadera).

    ── EL CORTE POR TTY (T4, 2026-08-18) ────────────────────────────────────
    El T3 escribia SIEMPRE a ``sys.__stdout__``, y eso choca de frente con el
    carril de fondo del REPL: con la vista de agentes abierta esas lineas
    "@EV {...}" se pintan crudas ENCIMA de la pantalla alterna (el spike midio
    6 lineas de suciedad). La tentacion es escribir a ``sys.stdout`` y dejar
    que el ``_PrintCapture`` de Textual las recoja, pero eso deja CIEGO al
    telefono, que es una restriccion dura.

    Los dos mundos NO son una preferencia: son distinguibles por una razon
    FISICA y MEDIDA (2026-08-18, mismo ConPTY del spike T4):

        mundo PIPE (el del movil)  sys.__stdout__.isatty() -> False
                                   remoto/sesiones.py:712 lanza el REPL con
                                   stdout=subprocess.PIPE, JAMAS un tty.
        mundo CONSOLA (el humano)  sys.__stdout__.isatty() -> True
                                   la pantalla alterna solo existe aca.

    Y la implicacion va en las dos direcciones: donde hay pantalla alterna NO
    hay telefono escuchando (el telefono solo llega por el pipe), y donde hay
    telefono NO hay pantalla alterna que ensuciar. Por eso:

      * stdout real NO es un tty -> se escribe al stdout REAL. El movil ve
        todo, tambien con la vista abierta, y sigue escapando del
        redirect_stdout de cli.py:1558. Es el comportamiento del T3, intacto.
      * stdout real SI es un tty -> se escribe al ``sys.stdout`` DEL MOMENTO.
        Sin Textual es el mismo terminal de siempre (nadie nota nada); con
        Textual abierto es su ``_PrintCapture``, y la vista lo recoge con
        ``begin_capture_print`` en vez de dejar que se pinte sobre la pantalla.

    ``sys.__stdout__`` puede ser None (pythonw, algunos empaquetados): se cae a
    ``sys.stdout``, que es exactamente a donde escribia el print() de antes —
    nunca peor que hoy. Si tampoco hay, devuelve None y no se escribe nada.
    """
    real = sys.__stdout__
    if real is None:
        return sys.stdout
    try:
        es_tty = bool(real.isatty())
    except Exception:
        # Un stream sin isatty() (StringIO viejo, doble de test) se trata como
        # NO-tty: el default se inclina hacia el canal del movil, que es la
        # restriccion dura. Perder un evento del telefono es un fallo; pintar
        # una linea de mas en un terminal es cosmetico.
        es_tty = False
    if not es_tty:
        return real
    return sys.stdout if sys.stdout is not None else real


def _escribir_stdout_real(linea: str) -> None:
    """Escribe UNA linea-evento en el stdout real. Formato IDENTICO al de
    ``print(PREFIJO_STDOUT + linea, flush=True)`` — mismo prefijo, mismo salto,
    mismo flush: es un contrato con remoto/sesiones.py y no se toca.

    UN solo ``write()`` bajo candado en vez de print(), que hace DOS (el texto
    y el salto) y deja una rendija por la que dos hilos pueden colarse. La
    medicion de ~29.000 eventos con 1/2/3/4/6 hilos NO produjo una sola linea
    pegada, asi que esto vale como SEGURO, no como arreglo de un bug
    reproducido."""
    stream = _stdout_real()
    if stream is None:
        return
    with _lock_stdout:
        stream.write(PREFIJO_STDOUT + linea + "\n")
        stream.flush()


def _saltar_pedido() -> tuple:
    """Tipos de evento que el sink NO escribe, por env.

    COGNIA_EVENTS_SALTAR="TokenTexto,RazonamientoTick" -> el sink de ARCHIVO
    tambien los salta (el de stdout ya los saltaba por una razon medida). La
    telemetria completa sigue siendo el default: apagarla es una decision
    explicita de quien paga el disco, no un filtro que se cuela por defecto.
    """
    crudo = os.environ.get("COGNIA_EVENTS_SALTAR", "")
    return tuple(x.strip() for x in crudo.split(",") if x.strip())


def activar_sink_jsonl(ruta: str = "") -> None:
    """Suscribe un sink que escribe una linea JSON por evento. Con ruta vacia
    usa COGNIA_EVENTS_JSONL (ruta de archivo) o stdout-linea si vale '1'
    (el remoto lanza el proceso con esto y consume el stream tipado; cada
    linea va prefijada con PREFIJO_STDOUT para separarla de la prosa)."""
    global _sink_jsonl
    if _sink_jsonl is not None:
        return
    destino = ruta or os.environ.get("COGNIA_EVENTS_JSONL", "")
    if not destino:
        return

    if destino == "1":
        # RazonamientoTick NO va por stdout: alta frecuencia y el remoto no
        # lo consume (el indicador 'pensando…' del movil sale de
        # AgenteProgreso, que ya viene throttleado).
        #
        # TokenTexto SI pasa desde la paridad remota (2026-08-24), salvo
        # COGNIA_REMOTO_STREAM=0. La razon por la que se saltaba era MEDIDA
        # (e2e 2026-08-09: "¡Hola! ¿En qué puedo @EV {TokenTexto...}", la
        # linea-evento pegada a una frase a medias) y hoy ya no se da, por
        # DOS piezas y no una: (1) bajo COGNIA_REMOTO el renderer arranca con
        # _sin_stream=True (ux/renderer.py:201) y no pinta TokenTexto; (2) el
        # fast-path del CLI, que tiene su PROPIO FlujoSuave, tampoco pinta
        # cuando cli._remoto_stream_vivo() es True — sin la pieza (2) el
        # entrelazado VOLVIO tal cual en la corrida real del 2026-08-25
        # ('  Según los datos de hoy, @EV {"texto": " Ac"...}'). La respuesta
        # llega entera y plana por _show_response al terminar. Sin nadie
        # escribiendo prosa a medias en el mismo stdout, cada "@EV" queda en
        # su propia linea y el consumidor (remoto/sesiones.py) puede agrupar
        # los trozos en una burbuja viva.
        # La palanca deja volver al comportamiento anterior si un renderer
        # nuevo vuelve a escribir a medias: es un kill-switch, no un tuning.
        _saltar = ("RazonamientoTick",) + _saltar_pedido()
        if os.environ.get("COGNIA_REMOTO_STREAM", "").strip() == "0":
            _saltar = ("TokenTexto",) + _saltar

        # Al stdout REAL, no al sys.stdout del momento: ver _stdout_real().
        _escribir = _escribir_stdout_real
    else:
        # PALANCA, NO THROTTLE (2026-08-17). El modo archivo guarda TODO a
        # proposito (es la telemetria), pero con tokens en vivo eso son ~9.200
        # eventos por criticar() de 3 lentes x 3072 tokens ≈ 1,1 MB por
        # critica, con flush por linea. Quien no quiera pagarlo lo apaga por
        # env; lo que NO se hace es coalescer TokenTexto por tiempo, porque el
        # trabajo de ese evento es SER el texto y un buffer con tick introduce
        # un modo de fallo nuevo (el ultimo fragmento se queda dentro) para
        # resolver un coste que no esta medido.
        _saltar = _saltar_pedido()

        f = open(destino, "a", encoding="utf-8")

        def _escribir(linea: str) -> None:
            f.write(linea + "\n")
            f.flush()

    def _sink(evento: Evento) -> None:
        if type(evento).__name__ in _saltar:
            return
        _escribir(json.dumps(a_dict(evento), ensure_ascii=False))

    _sink_jsonl = _sink
    # El sink va PRIMERO en la lista de suscriptores: el consumidor remoto
    # necesita ver la linea-evento ANTES de que el renderer imprima su version
    # humana en el mismo stdout — asi el clasificador registra el eco y puede
    # saltarse la linea pintada cuando llegue (si no, el eco del renderer
    # entra al chat como prosa antes de que el evento lo anuncie; medido en
    # el e2e 2026-08-09 con un Aviso duplicado).
    with _lock:
        if _sink not in _suscriptores:
            _suscriptores.insert(0, _sink)
