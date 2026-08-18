"""
cognia/tui/puente.py
====================
El PUENTE del bus de eventos (cognia/ux/events.py) a una App de Textual.

QUE HACE: se suscribe al bus, encola lo que llega desde CUALQUIER hilo, y en el
hilo de la UI aplica esos eventos a un modelo de estado (corridas -> agentes)
que una pantalla puede pintar. No dibuja nada: no conoce un solo widget.

POR QUE ASI (las tres restricciones que mandan en el diseno):

1. ``events.emitir()`` reparte EN EL HILO DEL EMISOR. Ese hilo es el que esta
   generando tokens: si el suscriptor hace trabajo ahi, el motor se frena por
   un adorno. El puente hace lo minimo del lado del emisor -- un append a un
   deque bajo candado -- y NUNCA lanza (mismo contrato que el bus).
   Por eso tampoco se usa ``app.call_from_thread``: esa BLOQUEA al emisor hasta
   que la UI atiende (textual/app.py:1788, devuelve el resultado). Se usa
   ``app.post_message``, que es thread-safe y no espera
   (message_pump.py:882-887: ``loop.call_soon_threadsafe``).

2. El despertador va COALESCIDO. No se postea un mensaje por evento (serian
   4.000 wakeups del loop por agente): se postea UNO cuando la cola pasa de
   dormida a con-trabajo, y el drenaje de la UI se lleva un lote entero. El
   mensaje es ``textual.events.Callback``, que MessagePump ya sabe atender
   (message_pump.py:890 ``on_callback``): la App no tiene que declarar ningun
   handler ni saber que este modulo existe.

3. La cola es ACOTADA y el descarte SE VE. Un evento perdido en silencio es el
   modo de fallo que este repo persigue. Las reglas:
     * Los eventos de FLUJO (TokenTexto/RazonamientoTick/AgenteProgreso) son
       los unicos descartables: son de alta frecuencia y su perdida degrada la
       vista, no la corrompe. Se tira el MAS VIEJO (el usuario mira el final de
       un stream, no el principio).
     * Los ESTRUCTURALES (Workflow*/Agente*/Tool*/Tarea*/Aviso/Degradado/
       MensajeAlAgente) NO se descartan por backpressure normal: cada uno mueve
       la maquina de estados y perder un AgenteFin deja un agente "corriendo"
       para siempre. Su cola vale ``cap_estructural`` (4x la de flujo) porque su
       cardinalidad la fija el workflow (agentes x pasos), no el modelo
       generando: llegar a ese techo NO es backpressure, es que NADIE esta
       drenando (App muerta y puente sin desconectar). Ahi se tira el mas viejo
       igual --memoria acotada antes que modelo perfecto en una vista que ya no
       existe-- y se cuenta aparte, en ``descartes.por_tipo``, con su WARNING.
     * Todo descarte queda contado en ``estado.descartes``, se atribuye al
       agente que lo sufrio (``AgenteVista.chars_perdidos`` -> ``completo``
       pasa a False: el texto de ese agente TIENE AGUJEROS y quien lo pinte
       tiene que poder decirlo) y se loguea en WARNING (que con la TUI abierta
       cae en el LogsPanel via TuiLogHandler).

Techo de memoria: el texto acumulado por agente se recorta por la CABEZA a
``cap_texto`` chars (se conserva la cola, que es lo que se esta leyendo) y lo
recortado se cuenta en ``chars_truncados``. Las corridas viejas se olvidan
(``max_corridas``) y los agentes por corrida tienen tope (``max_agentes``).

Enchufar/desenchufar: ``conectar_puente(app)`` devuelve el puente UNICO del
proceso; llamarla dos veces (abrir la vista dos veces) NO deja dos suscriptores
ni duplica el estado. ``desconectar_puente()`` lo saca del bus.

Convencion del repo: comentarios en espanol sin acentos; solo stdlib + textual.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from textual.events import Callback as _CallbackTextual

from ..ux import events

log = logging.getLogger("cognia.tui.puente")


# Los tipos de evento DESCARTABLES. Todo lo que no este aca es estructural y
# viaja por la cola que no se recorta. La lista es por NOMBRE de clase (igual
# que el _saltar del sink de events.py) para no acoplarse a la jerarquia.
TIPOS_FLUJO: tuple[str, ...] = ("TokenTexto", "RazonamientoTick", "AgenteProgreso")

CAP_COLA = 4096          # eventos de flujo en vuelo antes de empezar a tirar
CAP_TEXTO = 32768        # chars de respuesta guardados POR AGENTE
MAX_CORRIDAS = 8         # corridas recordadas (se olvidan las cerradas mas viejas)
MAX_AGENTES = 512        # agentes por corrida
TOPE_POR_PASADA = 256    # eventos aplicados por drenaje: no acaparar el hilo de UI
MAX_AVISOS = 200         # anillo de Aviso/Degradado


# ---------------------------------------------------------------------------
# El modelo de estado. Dataclasses planas: la pantalla lee atributos, no llama
# metodos. Lo escribe SOLO el hilo de la UI (dentro de drenar()).
# ---------------------------------------------------------------------------

@dataclass
class AgenteVista:
    """Lo que se sabe de UN agente de una corrida, listo para pintar."""

    agente_id: str
    run_id: str = ""
    indice: int = 0
    total: int = 0
    fase: str = ""
    etiqueta: str = ""
    rol: str = ""
    # "corriendo" | "ok" | "fallo" | "cancelado". Conjunto cerrado: el que
    # pinte no tiene que interpretar combinaciones de bools.
    estado: str = "corriendo"
    motivo: str = ""
    resumen: str = ""
    cache_hit: bool = False
    tardio: bool = False
    # True si el agente se creo al ver un evento suyo SIN haber visto su
    # AgenteInicio (puente enchufado a mitad de corrida). No es un error: es
    # una fila cuyos metadatos (indice/etiqueta) estan vacios y hay que decirlo.
    sintetico: bool = False

    tokens: int = 0          # los REALES que declaro AgenteFin
    intentos: int = 0
    intento: int = 0         # el intento en curso, segun AgenteProgreso
    repreguntas: int = 0
    descartado_chars: int = 0

    # chars segun el LATIDO (AgenteProgreso): es la cuenta del motor, llega
    # throttleada y sirve aunque los TokenTexto se hayan descartado.
    chars_progreso: int = 0
    chars_razonamiento: int = 0

    mensajes: int = 0            # MensajeAlAgente recibidos (aceptados o no)
    mensajes_aceptados: int = 0
    pendientes: int = 0          # mensajes en cola, ultimo valor visto
    estado_control: str = ""     # ver workflows.ESTADOS_CONTROL

    paso: int = 0
    intencion: str = ""
    tool_actual: str = ""        # tool corriendo ahora ("" si ninguna)
    tools: int = 0               # ToolFin vistos
    ultima_tool: str = ""

    inicio_ts: float = 0.0
    fin_ts: float = 0.0
    duracion_s: float = 0.0      # la que declaro AgenteFin (0 mientras corre)
    ultimo_ts: float = 0.0       # ts del ultimo evento suyo

    # Texto acumulado, con techo. Se guarda en fragmentos para que el recorte
    # por la cabeza sea O(1) amortizado y no una copia del string entero por
    # cada token.
    _frag: deque = field(default_factory=deque, repr=False)
    _largo: int = field(default=0, repr=False)
    chars_texto: int = 0         # chars de TokenTexto que pasaron DE VERDAD
    chars_truncados: int = 0     # tirados por el techo de memoria (la cabeza)
    chars_perdidos: int = 0      # tirados por la COLA llena: agujeros EN MEDIO

    @property
    def texto(self) -> str:
        """La respuesta acumulada (los ultimos ``cap_texto`` chars)."""
        return "".join(self._frag)

    @property
    def completo(self) -> bool:
        """False si al texto le falta algo: por el techo o por descarte.

        Quien lo pinte tiene que poder decir "esto no es todo": un stream con
        agujeros que se presenta como entero es exactamente la mentira que este
        modulo evita."""
        return self.chars_truncados == 0 and self.chars_perdidos == 0

    @property
    def viva(self) -> bool:
        return self.estado == "corriendo"

    @property
    def segundos(self) -> float:
        """Duracion declarada si termino; si sigue vivo, lo que lleva."""
        if self.duracion_s:
            return self.duracion_s
        if self.fin_ts:
            return max(0.0, self.fin_ts - self.inicio_ts)
        if self.inicio_ts:
            return max(0.0, time.time() - self.inicio_ts)
        return 0.0

    def anotar_texto(self, texto: str, cap: int) -> None:
        """Suma un fragmento respetando el techo (conserva la COLA)."""
        if not texto:
            return
        self.chars_texto += len(texto)
        self._frag.append(texto)
        self._largo += len(texto)
        exceso = self._largo - cap
        while exceso > 0 and self._frag:
            cabeza = self._frag[0]
            if len(cabeza) <= exceso:
                self._frag.popleft()
                self._largo -= len(cabeza)
                self.chars_truncados += len(cabeza)
                exceso -= len(cabeza)
            else:
                # Recorte PARCIAL: el techo es exacto, no "el fragmento entero".
                self._frag[0] = cabeza[exceso:]
                self._largo -= exceso
                self.chars_truncados += exceso
                exceso = 0


@dataclass
class CorridaVista:
    """Una corrida del motor de workflows (un run_id)."""

    run_id: str
    nombre: str = ""
    interactivo: bool = False
    total_agentes: int = 0
    presupuesto_tokens: int = 0
    cache_precargada: int = 0
    resume_de: str = ""

    abierta: bool = True
    ok: bool = True
    resumen: str = ""
    # True si la corrida se invento al ver un evento de un agente sin haber
    # visto su WorkflowInicio.
    sintetica: bool = False

    inicio_ts: float = 0.0
    fin_ts: float = 0.0
    duracion_s: float = 0.0

    # Los numeros de WorkflowFin (los oficiales, cuando llega).
    agentes: int = 0
    fallidos: int = 0
    cache_hits: int = 0
    cancelados: int = 0
    tokens: int = 0
    tokens_estimados: int = 0
    arrancados: int = 0
    no_arrancados: int = 0
    colgando: int = 0

    # Lo contado EN VIVO por el puente (sirve mientras la corrida esta abierta,
    # que es justo cuando no hay WorkflowFin).
    tokens_vistos: int = 0
    fallidos_vistos: int = 0
    cache_hits_vistos: int = 0
    agentes_omitidos: int = 0    # no creados por el tope de memoria

    # agente_id -> AgenteVista, en orden de aparicion (dict preserva insercion).
    agentes_vista: dict = field(default_factory=dict)

    @property
    def vivos(self) -> list:
        return [a for a in self.agentes_vista.values() if a.viva]

    @property
    def segundos(self) -> float:
        if self.duracion_s:
            return self.duracion_s
        if self.fin_ts:
            return max(0.0, self.fin_ts - self.inicio_ts)
        if self.inicio_ts:
            return max(0.0, time.time() - self.inicio_ts)
        return 0.0


@dataclass
class TareaVista:
    """El turno del agente/chat que envuelve a las corridas (TareaInicio/Fin)."""

    tarea: str = ""
    modo: str = ""
    modelo: str = ""
    abierta: bool = False
    ok: bool = True
    resumen: str = ""
    pasos: int = 0
    tokens: int = 0
    duracion_s: float = 0.0
    inicio_ts: float = 0.0
    fin_ts: float = 0.0


@dataclass
class Descartes:
    """La contabilidad del descarte. Si esto no es cero, la vista MIENTE si no
    lo dice: por eso vive en el estado y no en un log que nadie mira."""

    total: int = 0
    chars: int = 0                   # chars de texto que se perdieron
    ultimo_ts: float = 0.0
    por_tipo: dict = field(default_factory=dict)

    @property
    def hubo(self) -> bool:
        return self.total > 0

    def anotar(self, tipo: str, chars: int, ts: float) -> None:
        self.total += 1
        self.chars += chars
        self.ultimo_ts = ts
        self.por_tipo[tipo] = self.por_tipo.get(tipo, 0) + 1


@dataclass
class EstadoPuente:
    """Todo lo que la pantalla necesita. Lo escribe solo el hilo de la UI."""

    corridas: dict = field(default_factory=dict)     # run_id -> CorridaVista
    tarea: TareaVista = field(default_factory=TareaVista)
    # Bolsa de los eventos SIN agente_id (chat suelto, prosa fuera de workflow).
    suelto: AgenteVista = field(default_factory=lambda: AgenteVista(agente_id=""))
    avisos: deque = field(default_factory=lambda: deque(maxlen=MAX_AVISOS))
    descartes: Descartes = field(default_factory=Descartes)

    # Sube 1 por cada drenaje que aplico al menos un evento: la pantalla puede
    # comparar y saltarse el repintado si no cambio nada.
    version: int = 0
    aplicados: int = 0
    corridas_olvidadas: int = 0

    # Indice global agente_id -> AgenteVista (routing O(1) de TokenTexto, que
    # solo trae el agente_id sellado por el ContextVar).
    _indice: dict = field(default_factory=dict, repr=False)

    def agente(self, agente_id: str) -> Optional[AgenteVista]:
        if not agente_id:
            return self.suelto
        return self._indice.get(agente_id)

    def corrida(self, run_id: str) -> Optional[CorridaVista]:
        return self.corridas.get(run_id)

    @property
    def ultima_corrida(self) -> Optional[CorridaVista]:
        for c in reversed(list(self.corridas.values())):
            return c
        return None

    @property
    def agentes(self) -> list:
        """Todos los agentes conocidos, en orden de aparicion."""
        salida = []
        for c in self.corridas.values():
            salida.extend(c.agentes_vista.values())
        return salida


# ---------------------------------------------------------------------------
# El puente.
# ---------------------------------------------------------------------------

class PuenteBus:
    """Suscriptor del bus que alimenta un ``EstadoPuente`` desde el hilo de UI.

    Uso tipico (desde ``on_mount`` de la pantalla, o sea el hilo de la UI):

        p = conectar_puente(self.app)
        p.al_cambiar(self.repintar)
        ...
        desconectar_puente()

    Sin App (tests, headless): ``PuenteBus()`` + ``drenar()`` a mano.
    """

    def __init__(self, app=None, *, cap_cola: int = CAP_COLA,
                 cap_texto: int = CAP_TEXTO, max_corridas: int = MAX_CORRIDAS,
                 max_agentes: int = MAX_AGENTES,
                 tope_por_pasada: int = TOPE_POR_PASADA,
                 cap_estructural: int = 0) -> None:
        self._app = app
        self._cap_estructural = max(1, int(cap_estructural or cap_cola * 4))
        self._cap_cola = max(1, int(cap_cola))
        self._cap_texto = max(1, int(cap_texto))
        self._max_corridas = max(1, int(max_corridas))
        self._max_agentes = max(1, int(max_agentes))
        self._tope = max(1, int(tope_por_pasada))

        self.estado = EstadoPuente()

        # --- lo que comparten emisor y UI, todo bajo _lock -------------------
        self._lock = threading.Lock()
        # (seq, evento). Dos colas y un contador comun: el flujo se recorta en
        # O(1) sin escanear, y el seq permite re-mezclarlas EN ORDEN al drenar
        # (si no, un AgenteFin podria aplicarse antes que los tokens que lo
        # preceden y el agente aparecerira cerrado mientras sigue escribiendo).
        self._flujo: deque = deque()
        self._estructural: deque = deque()
        self._seq = 0
        self._despierto = False
        # agente_id -> chars perdidos, pendientes de atribuir en el proximo
        # drenaje. El emisor NO toca el modelo: solo deja la nota aca.
        self._perdidos: dict = {}
        self._descartes_nuevos = 0

        # --- metricas (ints: se leen sin candado a proposito) ----------------
        self._encolados = 0
        self._pasadas = 0
        self._wakeups = 0
        self._wakeups_fallidos = 0
        self._pico_pendientes = 0

        self._conectado = False
        self._al_cambiar: Optional[Callable[[EstadoPuente], None]] = None

        self._manejadores = {
            "WorkflowInicio": self._on_workflow_inicio,
            "AgenteInicio": self._on_agente_inicio,
            "AgenteProgreso": self._on_agente_progreso,
            "MensajeAlAgente": self._on_mensaje,
            "AgenteFin": self._on_agente_fin,
            "WorkflowFin": self._on_workflow_fin,
            "TokenTexto": self._on_token,
            "RazonamientoTick": self._on_razonamiento,
            "Aviso": self._on_aviso,
            "Degradado": self._on_degradado,
            "ToolInicio": self._on_tool_inicio,
            "ToolFin": self._on_tool_fin,
            "PasoIntencion": self._on_paso,
            "TareaInicio": self._on_tarea_inicio,
            "TareaFin": self._on_tarea_fin,
        }

    # -- enchufe ------------------------------------------------------------

    @property
    def conectado(self) -> bool:
        return self._conectado

    @property
    def app(self):
        return self._app

    def conectar(self, app=None) -> "PuenteBus":
        """Suscribe al bus. IDEMPOTENTE: llamarla dos veces (la vista abierta
        dos veces) no deja dos suscriptores ni aplica cada evento dos veces."""
        if app is not None:
            self._app = app
        if self._conectado:
            # Puede haber cambiado la App (vista reabierta en otra): si quedo
            # trabajo pendiente, se re-arma el despertador contra la nueva.
            self._quizas_despertar()
            return self
        events.suscribir(self)
        self._conectado = True
        self._quizas_despertar()
        return self

    def desconectar(self) -> None:
        """Saca el puente del bus y suelta lo encolado. Idempotente."""
        if self._conectado:
            events.desuscribir(self)
            self._conectado = False
        with self._lock:
            self._flujo.clear()
            self._estructural.clear()
            self._perdidos.clear()
            self._despierto = False
        self._app = None
        self._al_cambiar = None

    def al_cambiar(self, fn: Optional[Callable[[EstadoPuente], None]]) -> None:
        """Callback que corre en el hilo de la UI despues de cada drenaje que
        cambio algo. Es el UNICO punto donde la pantalla se entera; el puente
        no conoce widgets. Si el callback lanza, se traga (contrato del bus)."""
        self._al_cambiar = fn

    # -- lado EMISOR: lo mas barato posible, y no lanza ----------------------

    def __call__(self, evento) -> None:
        """Suscriptor del bus. Corre en el HILO DEL EMISOR: solo encola."""
        try:
            self._encolar(evento)
        except Exception:
            # Contrato del bus: un adorno jamas rompe el turno.
            pass

    def _encolar(self, evento) -> None:
        tipo = type(evento).__name__
        flujo = tipo in TIPOS_FLUJO
        despertar = False
        with self._lock:
            self._seq += 1
            if flujo:
                if len(self._flujo) >= self._cap_cola:
                    # La UI no da abasto: muere el fragmento MAS VIEJO. Se anota
                    # aca (contadores + nota por agente) y se atribuye al modelo
                    # en el proximo drenaje, que corre en el hilo de la UI.
                    _viejo_seq, viejo = self._flujo.popleft()
                    self._anotar_descarte(viejo)
                self._flujo.append((self._seq, evento))
            else:
                if len(self._estructural) >= self._cap_estructural:
                    # No es backpressure: es que NADIE drena (App muerta y el
                    # puente sin desconectar). Memoria acotada antes que un
                    # modelo perfecto para una vista que ya no existe.
                    _viejo_seq, viejo = self._estructural.popleft()
                    self._anotar_descarte(viejo)
                self._estructural.append((self._seq, evento))
            self._encolados += 1
            pend = len(self._flujo) + len(self._estructural)
            if pend > self._pico_pendientes:
                self._pico_pendientes = pend
            if not self._despierto:
                self._despierto = True
                despertar = True
        if despertar:
            self._postear()

    def _anotar_descarte(self, evento) -> None:
        """Bajo _lock, en el HILO DEL EMISOR.

        Toca ``estado.descartes`` (contadores enteros y un dict de conteos) a
        proposito: si el descarte solo se anotara al drenar, una UI colgada
        --el unico caso en que hay descarte-- tendria el contador en cero justo
        cuando hay que mirarlo. Lo que NO toca es la parte del modelo con
        estructura (corridas/agentes): la atribucion por agente se deja en
        ``_perdidos`` y la aplica el hilo de la UI en drenar()."""
        tipo = type(evento).__name__
        chars = len(getattr(evento, "texto", "") or "") if tipo == "TokenTexto" else 0
        self.estado.descartes.anotar(tipo, chars, getattr(evento, "ts", 0.0))
        self._descartes_nuevos += 1
        if chars:
            aid = getattr(evento, "agente_id", "") or ""
            self._perdidos[aid] = self._perdidos.get(aid, 0) + chars

    def _postear(self) -> None:
        """Despierta a la UI SIN esperarla. Un solo mensaje por rafaga."""
        app = self._app
        if app is None:
            # Sin App el estado se aplica con drenar() a mano (tests/headless):
            # se deja dormido para no perder el proximo despertar.
            with self._lock:
                self._despierto = False
            return
        ok = False
        try:
            # Callback lo atiende MessagePump.on_callback: la App no declara
            # nada. post_message es thread-safe y no bloquea al emisor.
            ok = bool(app.post_message(_CallbackTextual(self._drenar_ui)))
        except Exception:
            ok = False
        if ok:
            self._wakeups += 1
        else:
            # App cerrandose o aun sin loop: se vuelve a dormir para que el
            # PROXIMO evento reintente en vez de quedarse encallado.
            with self._lock:
                self._despierto = False
            self._wakeups_fallidos += 1

    def _quizas_despertar(self) -> None:
        despertar = False
        with self._lock:
            if (self._flujo or self._estructural) and not self._despierto:
                self._despierto = True
                despertar = True
        if despertar:
            self._postear()

    # -- lado UI: drenaje ----------------------------------------------------

    @property
    def pendientes(self) -> int:
        with self._lock:
            return len(self._flujo) + len(self._estructural)

    def _tomar(self, tope: int):
        """Saca un lote EN ORDEN de emision mezclando las dos colas."""
        lote = []
        with self._lock:
            self._despierto = False   # antes de drenar: si entra algo mientras
                                      # aplicamos, ese emisor vuelve a postear
            flujo, estr = self._flujo, self._estructural
            while len(lote) < tope and (flujo or estr):
                if not flujo:
                    lote.append(estr.popleft()[1])
                elif not estr:
                    lote.append(flujo.popleft()[1])
                elif estr[0][0] < flujo[0][0]:
                    lote.append(estr.popleft()[1])
                else:
                    lote.append(flujo.popleft()[1])
            perdidos = self._perdidos
            self._perdidos = {}
            nuevos_descartes = self._descartes_nuevos
            self._descartes_nuevos = 0
            quedan = len(flujo) + len(estr)
        return lote, perdidos, nuevos_descartes, quedan

    def drenar(self, tope: int = 0) -> int:
        """Aplica hasta ``tope`` eventos al estado. CORRE EN EL HILO DE LA UI.

        Devuelve cuantos aplico. Publico a proposito: sin App (headless, tests)
        este es el unico motor, y con App sirve para forzar un drenaje."""
        lote, perdidos, nuevos_descartes, quedan = self._tomar(tope or self._tope)
        if not lote and not perdidos:
            return 0
        for evento in lote:
            try:
                self._aplicar(evento)
            except Exception:
                # Un evento raro no puede tumbar la vista ni frenar el lote.
                log.debug("puente: evento no aplicado", exc_info=True)
        for aid, chars in perdidos.items():
            vista = self.estado.agente(aid)
            if vista is not None:
                # El texto de este agente ya no es el que genero el modelo.
                vista.chars_perdidos += chars
        if nuevos_descartes:
            d = self.estado.descartes
            log.warning(
                "puente TUI: %d eventos descartados en esta pasada "
                "(total %d, %d chars perdidos) -- la vista va detras del motor",
                nuevos_descartes, d.total, d.chars)
        self._pasadas += 1
        self.estado.aplicados += len(lote)
        self.estado.version += 1
        self._avisar()
        if quedan:
            # Quedo cola: se re-arma el despertador (nunca se drena todo de una
            # para no acaparar el hilo de la UI con una rafaga de tokens).
            self._quizas_despertar()
        return len(lote)

    def _drenar_ui(self) -> None:
        """Lo que corre dentro del Callback posteado a la App."""
        try:
            self.drenar()
        except Exception:
            log.debug("puente: drenaje fallido", exc_info=True)

    def _avisar(self) -> None:
        fn = self._al_cambiar
        if fn is None:
            return
        try:
            fn(self.estado)
        except Exception:
            log.debug("puente: al_cambiar fallo", exc_info=True)

    def metricas(self) -> dict:
        """Numeros del puente mismo (no del modelo). Para la barra de estado y
        para el informe: si hay descarte, esto lo dice."""
        d = self.estado.descartes
        return {
            "encolados": self._encolados,
            "aplicados": self.estado.aplicados,
            "pendientes": self.pendientes,
            "pico_pendientes": self._pico_pendientes,
            "pasadas": self._pasadas,
            "wakeups": self._wakeups,
            "wakeups_fallidos": self._wakeups_fallidos,
            "descartados": d.total,
            "chars_perdidos": d.chars,
            "descartes_por_tipo": dict(d.por_tipo),
            "corridas_olvidadas": self.estado.corridas_olvidadas,
        }

    # -- modelo: altas y topes de memoria ------------------------------------

    def _corrida(self, run_id: str, *, sintetica: bool = False) -> CorridaVista:
        c = self.estado.corridas.get(run_id)
        if c is not None:
            return c
        self._olvidar_corridas()
        c = CorridaVista(run_id=run_id, sintetica=sintetica, inicio_ts=time.time())
        self.estado.corridas[run_id] = c
        return c

    def _olvidar_corridas(self) -> None:
        """Deja sitio para una corrida nueva: se van primero las CERRADAS mas
        viejas; si todas siguen abiertas, la mas vieja igual (el techo manda)."""
        while len(self.estado.corridas) >= self._max_corridas:
            objetivo = None
            for rid, c in self.estado.corridas.items():
                if not c.abierta:
                    objetivo = rid
                    break
            if objetivo is None:
                objetivo = next(iter(self.estado.corridas))
            vieja = self.estado.corridas.pop(objetivo)
            for aid in vieja.agentes_vista:
                self.estado._indice.pop(aid, None)
            self.estado.corridas_olvidadas += 1

    def _agente(self, agente_id: str, run_id: str = "",
                *, sintetico: bool = False) -> Optional[AgenteVista]:
        """Ubica (o crea) la vista de un agente. Devuelve None si el tope de
        agentes de esa corrida ya se alcanzo (queda contado en la corrida)."""
        if not agente_id:
            return self.estado.suelto
        vista = self.estado._indice.get(agente_id)
        if vista is not None:
            return vista
        # El agente_id es "<run_id>#<fase>.<indice>@<n>": si no vino run_id
        # (TokenTexto solo trae el id sellado por el ContextVar) se saca de ahi.
        rid = run_id or (agente_id.split("#", 1)[0] if "#" in agente_id else "")
        c = self._corrida(rid, sintetica=True)
        if len(c.agentes_vista) >= self._max_agentes:
            c.agentes_omitidos += 1
            return None
        vista = AgenteVista(agente_id=agente_id, run_id=rid,
                            sintetico=sintetico, inicio_ts=time.time())
        c.agentes_vista[agente_id] = vista
        self.estado._indice[agente_id] = vista
        return vista

    # -- modelo: aplicacion de cada evento -----------------------------------

    def _aplicar(self, evento) -> None:
        fn = self._manejadores.get(type(evento).__name__)
        if fn is not None:
            fn(evento)

    def _on_workflow_inicio(self, ev) -> None:
        c = self._corrida(ev.run_id)
        c.sintetica = False
        c.nombre = ev.nombre
        c.total_agentes = ev.total_agentes
        c.presupuesto_tokens = ev.presupuesto_tokens
        c.cache_precargada = ev.cache_precargada
        c.resume_de = ev.resume_de
        c.interactivo = ev.interactivo
        c.abierta = True
        c.inicio_ts = ev.ts

    def _on_agente_inicio(self, ev) -> None:
        c = self._corrida(ev.run_id)
        c.sintetica = False
        a = self._agente(ev.agente_id, ev.run_id)
        if a is None:
            return
        a.sintetico = False
        a.run_id = ev.run_id or a.run_id
        a.indice = ev.indice
        a.total = ev.total
        a.fase = ev.fase
        a.etiqueta = ev.etiqueta
        a.rol = ev.rol
        a.tardio = ev.tardio
        a.estado = "corriendo"
        a.inicio_ts = ev.ts
        a.ultimo_ts = ev.ts

    def _on_agente_progreso(self, ev) -> None:
        a = self._agente(ev.agente_id, ev.run_id, sintetico=True)
        if a is None:
            return
        # El latido trae ACUMULADOS de la llamada, no incrementos: max() y no
        # suma (sumar contaria cada latido otra vez).
        a.chars_progreso = max(a.chars_progreso, ev.chars)
        a.chars_razonamiento = max(a.chars_razonamiento, ev.chars_razonamiento)
        a.intento = ev.intento
        a.ultimo_ts = ev.ts

    def _on_mensaje(self, ev) -> None:
        # El destinatario va en `destino`; el agente_id heredado es QUIEN lo
        # emitio (normalmente "" porque lo manda la UI).
        a = self._agente(ev.destino, ev.run_id, sintetico=True)
        if a is None:
            return
        a.mensajes += 1
        if ev.aceptado:
            a.mensajes_aceptados += 1
        a.estado_control = ev.estado
        a.pendientes = ev.pendientes
        a.ultimo_ts = ev.ts

    def _on_agente_fin(self, ev) -> None:
        c = self._corrida(ev.run_id)
        a = self._agente(ev.agente_id, ev.run_id, sintetico=True)
        if a is None:
            return
        a.indice = ev.indice or a.indice
        a.total = ev.total or a.total
        a.fase = ev.fase or a.fase
        a.etiqueta = ev.etiqueta or a.etiqueta
        a.rol = ev.rol or a.rol
        a.estado = "cancelado" if ev.cancelado else ("ok" if ev.ok else "fallo")
        a.motivo = ev.motivo
        a.resumen = ev.resumen
        a.cache_hit = ev.cache_hit
        a.tokens = ev.tokens
        a.intentos = ev.intentos
        a.duracion_s = ev.duracion_s
        a.tardio = ev.tardio
        a.repreguntas = ev.repreguntas
        a.descartado_chars = ev.descartado_chars
        a.fin_ts = ev.ts
        a.ultimo_ts = ev.ts
        a.tool_actual = ""
        c.tokens_vistos += ev.tokens
        if ev.cache_hit:
            c.cache_hits_vistos += 1
        if not ev.ok:
            c.fallidos_vistos += 1

    def _on_workflow_fin(self, ev) -> None:
        c = self._corrida(ev.run_id)
        c.nombre = ev.nombre or c.nombre
        c.abierta = False
        c.ok = ev.ok
        c.resumen = ev.resumen
        c.agentes = ev.agentes
        c.fallidos = ev.fallidos
        c.cache_hits = ev.cache_hits
        c.cancelados = ev.cancelados
        c.tokens = ev.tokens
        c.tokens_estimados = ev.tokens_estimados
        c.presupuesto_tokens = ev.presupuesto_tokens or c.presupuesto_tokens
        c.arrancados = ev.arrancados
        c.no_arrancados = ev.no_arrancados
        c.colgando = ev.colgando
        c.total_agentes = ev.total_agentes or c.total_agentes
        c.duracion_s = ev.duracion_s
        c.fin_ts = ev.ts

    def _on_token(self, ev) -> None:
        a = self._agente(ev.agente_id, sintetico=True)
        if a is None:
            return
        a.anotar_texto(ev.texto, self._cap_texto)
        a.ultimo_ts = ev.ts

    def _on_razonamiento(self, ev) -> None:
        a = self._agente(ev.agente_id, sintetico=True)
        if a is None:
            return
        a.chars_razonamiento = max(a.chars_razonamiento, ev.chars)
        a.ultimo_ts = ev.ts

    def _on_aviso(self, ev) -> None:
        self.estado.avisos.append(
            {"ts": ev.ts, "nivel": "aviso", "texto": ev.texto,
             "origen": ev.origen, "agente_id": ev.agente_id})

    def _on_degradado(self, ev) -> None:
        self.estado.avisos.append(
            {"ts": ev.ts, "nivel": "degradado",
             "texto": f"{ev.donde}: {ev.motivo}".strip(": "),
             "origen": ev.donde, "accion": ev.accion_sugerida,
             "agente_id": ev.agente_id})

    def _on_tool_inicio(self, ev) -> None:
        a = self._agente(ev.agente_id, sintetico=True)
        if a is None:
            return
        a.tool_actual = ev.tool
        a.paso = ev.paso or a.paso
        a.ultimo_ts = ev.ts

    def _on_tool_fin(self, ev) -> None:
        a = self._agente(ev.agente_id, sintetico=True)
        if a is None:
            return
        a.tool_actual = ""
        a.tools += 1
        a.ultima_tool = f"{ev.tool} {'ok' if ev.ok else 'fallo'}".strip()
        a.paso = ev.paso or a.paso
        a.ultimo_ts = ev.ts

    def _on_paso(self, ev) -> None:
        a = self._agente(ev.agente_id, sintetico=True)
        if a is None:
            return
        a.paso = ev.paso
        a.intencion = ev.intencion
        a.ultimo_ts = ev.ts

    def _on_tarea_inicio(self, ev) -> None:
        t = self.estado.tarea
        t.tarea, t.modo, t.modelo = ev.tarea, ev.modo, ev.modelo
        t.abierta, t.inicio_ts = True, ev.ts
        t.ok, t.resumen, t.pasos, t.tokens, t.duracion_s = True, "", 0, 0, 0.0

    def _on_tarea_fin(self, ev) -> None:
        t = self.estado.tarea
        t.abierta = False
        t.ok, t.resumen = ev.ok, ev.resumen
        t.pasos, t.tokens = ev.pasos, ev.tokens_predichos
        t.duracion_s, t.fin_ts = ev.duracion_s, ev.ts


# ---------------------------------------------------------------------------
# El puente UNICO del proceso. Abrir la vista dos veces tiene que dar el MISMO
# puente: dos instancias suscritas aplicarian cada evento dos veces (y el
# segundo estado, el que nadie pinta, se comeria la memoria igual).
# ---------------------------------------------------------------------------

_lock_modulo = threading.Lock()
_puente: Optional[PuenteBus] = None


def puente_activo() -> Optional[PuenteBus]:
    return _puente


def conectar_puente(app=None, **kwargs) -> PuenteBus:
    """Devuelve el puente del proceso, ya suscrito al bus.

    Si ya habia uno para OTRA App (la TUI se cerro y se abrio de nuevo), el
    viejo se desconecta y se crea uno limpio: postear a una App muerta seria
    tirar los eventos en silencio, que es justo lo que este modulo evita."""
    global _puente
    with _lock_modulo:
        p = _puente
        if p is not None and app is not None and p.app is not None and p.app is not app:
            p.desconectar()
            p = None
        if p is None:
            p = PuenteBus(app, **kwargs)
            _puente = p
    return p.conectar(app)


def desconectar_puente() -> None:
    """Saca el puente del bus. Idempotente: llamarla sin puente no hace nada."""
    global _puente
    with _lock_modulo:
        p, _puente = _puente, None
    if p is not None:
        p.desconectar()
