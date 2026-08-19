# -*- coding: utf-8 -*-
"""Detector de BUCLES del agente: la misma accion (o el mismo texto) una y otra vez.

QUÉ RESUELVE
    El agente entra en un ciclo y quema el presupuesto entero repitiendo lo
    mismo. Hay tres formas reales, no una:
      1. repeticion consecutiva ......... A A A
      2. ping-pong ...................... A B A B
      3. ciclo de periodo mayor ......... A B C A B C
    Y una cuarta que no pasa por las tools: el modelo escupiendo el MISMO texto
    en el stream hasta llenar la ventana.
    Este modulo las mira todas sobre una VENTANA deslizante y escala aviso ->
    bloqueo: primero se le habla AL MODELO (texto que se le inyecta, nombrando
    la accion prohibida), y solo si insiste se corta el turno.

POR QUÉ EXISTE (y por que no basta lo que ya hay)
    Cognia ya tiene `cognia/agent/loop.py:register_action` (linea 110): cuenta
    ocurrencias del par (action, args) COMPLETO en TODA la tarea y devuelve
    warn a la 2da y stop a la 3ra. Eso caza 1 y 2 por acumulacion, pero:
      - no tiene ventana: dos usos legitimos separados por 20 pasos suman igual;
      - no tiene tools exentas: `ver_salida` sobre un proceso en marcha es
        POLLING LEGITIMO y hoy se cuenta como estancamiento a la 3ra llamada;
      - no distingue el patron, asi que el aviso no puede decirle al modelo
        "estas ALTERNANDO entre A y B" (leccion medida del repo, +62pp:
        concreto >> abstracto; el aviso generico no desviaba al 3B —
        bench_estancamiento, pasos identicos post-aviso).
    Este modulo es la pieza completa; el cableado decide si sustituye o
    complementa a register_action (ver informe de cableado).

DE DÓNDE SE DESTILÓ (fuentes REALES, leidas)
    (a) Hermes Agent, `agent/tool_guardrails.py`
        - `ToolCallSignature.from_call` (linea ~176) + `canonical_tool_args`
          (~215): la identidad de una llamada es hash estable de
          (nombre, args canonicos) — JSON con `sort_keys=True`,
          `separators=(",",":")`, `default=str`. Aqui se copia tal cual.
        - `_sha256` (linea final): encode con `"surrogatepass"`. El comentario
          original dice por que: resultados scrapeados de la web traen
          subrogados UTF-16 sueltos y un encode estricto TIRA ABAJO el loop de
          conversacion entero. Se respeta.
        - `ToolCallGuardrailConfig` (~60): la escalada tiene DOS umbrales
          separados, `*_warn_after` (2/3/2) y `*_block_after` (5/8/5), y los
          avisos van encendidos por defecto mientras el corte duro es opt-in
          ("interactive CLI/TUI sessions keep flowing"). Aqui eso se traduce en
          `max_avisos`: N avisos y recien el (N+1) bloquea.
        - `IDEMPOTENT_TOOL_NAMES` / `_is_idempotent` (~19): Hermes clasifica
          las tools en vez de tratarlas a todas igual. La lectura para Cognia es
          la lista de EXENTAS: hay tools cuyo trabajo ES repetirse.
        - `ToolGuardrailController.before_call/after_call`: NUNCA lanzan y
          NUNCA ejecutan nada; devuelven una decision y el runtime decide.
          Este modulo cumple el mismo contrato (ver CONTRATO abajo).
    (b) `loopDetectionService` de Gemini CLI, constantes publicas:
        - 5 tool calls IDENTICAS seguidas = bucle de herramienta.
        - contenido: chunks de 50 chars, 10 apariciones del mismo chunk = bucle
          de texto, con un control de DISTANCIA para no marcar una frase comun
          que reaparece muy lejos.
        `GuardiaContenido` implementa (b); el umbral 5 de (b) queda como el
        default duro de `GuardiaBucle` cuando se suman umbral(3) + max_avisos(2):
        la 3ra repeticion avisa, la 5ta bloquea.

CONTRATO (camino caliente: instrumentacion que NUNCA rompe el turno)
    `registrar(...)` no lanza JAMAS. Ante cualquier fallo interno devuelve un
    veredicto 'ok' — un guardia roto no puede matar una tarea sana. Tampoco
    ejecuta ni cancela nada: devuelve un dict y el que llama decide.

VEREDICTO (dict plano, stdlib):
    {
      'estado':       'ok' | 'aviso' | 'bloqueo',
      'patron':       '' | 'repeticion' | 'ping_pong' | 'ciclo_N' | 'contenido_repetido',
      'mensaje':      '' | texto PARA EL MODELO (aviso) / para el log (bloqueo),
      'razon':        '' | 'bucle_detectado',   # solo en bloqueo
      'tool':         nombre de la tool registrada (o '' en contenido),
      'firma':        hash corto de la llamada,
      'repeticiones': cuantas veces se repitio el patron,
      'avisos':       cuantos avisos lleva emitidos este guardia,
    }
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Mapping

# Tools de Cognia cuyo trabajo ES repetirse: mirar la salida de un proceso en
# marcha, listar procesos, correr la suite. Llamarlas N veces seguidas es
# polling legitimo, no un bucle. (Equivalente a IDEMPOTENT_TOOL_NAMES de
# Hermes, pero al reves: alli se marcan las que SI se vigilan por no-progreso;
# aca se marcan las que se ignoran.) Los nombres existen en el registry:
# cognia/agent/tools.py lineas 1860 (ver_salida), 1946 (procesos), 2006 (tests).
EXENTAS_COGNIA = frozenset({"ver_salida", "procesos", "tests"})

# Constantes publicas del loopDetectionService de Gemini CLI (fuente (b)).
CHUNK_CONTENIDO = 50
UMBRAL_CONTENIDO = 10
# Gemini exige ademas que las apariciones esten CERCA entre si: si el mismo
# fragmento de 50 chars reaparece 10 veces pero repartido por un texto largo,
# es una frase comun, no un bucle. 1.5x el chunk es el factor de la fuente.
FACTOR_DISTANCIA = 1.5


# --------------------------------------------------------------------------
# Firma estable de una llamada
# --------------------------------------------------------------------------

def _canonico(args: Any) -> str:
    """Forma canonica y estable de los argumentos.

    Destilado de `canonical_tool_args` (Hermes): JSON ordenado y compacto para
    mappings, de modo que {"a":1,"b":2} y {"b":2,"a":1} den la MISMA firma.
    Extendido para el caso de Cognia, donde el agente ReAct pasa los args como
    UNA cadena ('ACCION: leer_archivo cognia/cli.py'): ahi la normalizacion es
    colapsar espacios en blanco, para que un salto de linea de mas no disfrace
    la misma llamada de llamada nueva.
    """
    if args is None:
        return ""
    if isinstance(args, str):
        return " ".join(args.split())
    if isinstance(args, Mapping):
        try:
            return json.dumps(dict(args), ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return " ".join(str(sorted(args.items())).split())
    if isinstance(args, (list, tuple)):
        try:
            return json.dumps(list(args), ensure_ascii=False,
                              separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return " ".join(str(list(args)).split())
    return " ".join(str(args).split())


def _sha(texto: str) -> str:
    # surrogatepass: la salida de una tool puede traer subrogados UTF-16 sueltos
    # (media pareja de un caracter matematico, texto scrapeado). Un encode
    # estricto LANZA y se lleva puesto el turno entero. El hash solo necesita
    # bytes deterministas, no UTF-8 valido. (Copiado de _sha256 en Hermes.)
    return hashlib.sha256(texto.encode("utf-8", "surrogatepass")).hexdigest()


def firma_llamada(nombre_tool: str, args: Any) -> str:
    """Hash estable y corto de (nombre + args normalizados).

    16 hex (64 bits) alcanzan de sobra para una ventana de decenas de llamadas
    y hacen legible la traza.
    """
    return _sha(f"{nombre_tool}\x00{_canonico(args)}")[:16]


def _resumen_args(args: Any, tope: int = 80) -> str:
    """Args recortados para METERLOS EN EL MENSAJE al modelo (concreto > abstracto)."""
    texto = _canonico(args)
    return texto if len(texto) <= tope else texto[:tope] + "..."


def _techo(a: int, b: int) -> int:
    return -(-a // b)


def _veredicto(estado: str = "ok", patron: str = "", mensaje: str = "",
               razon: str = "", tool: str = "", firma: str = "",
               repeticiones: int = 0, avisos: int = 0) -> dict:
    return {"estado": estado, "patron": patron, "mensaje": mensaje,
            "razon": razon, "tool": tool, "firma": firma,
            "repeticiones": repeticiones, "avisos": avisos}


# --------------------------------------------------------------------------
# Guardia de bucles de HERRAMIENTA
# --------------------------------------------------------------------------

class GuardiaBucle:
    """Vigila la secuencia de llamadas a tools sobre una ventana deslizante.

    Parametros
      ventana ..... cuantas llamadas recientes se miran (las viejas caducan; un
                    uso legitimo repetido a 20 pasos de distancia NO suma).
      umbral ...... cuantas repeticiones del patron hacen falta. Para la
                    repeticion consecutiva (periodo 1) son literalmente
                    `umbral` llamadas iguales; para un ciclo de periodo p el
                    minimo de vueltas es `max(2, techo(umbral/p))`, es decir:
                    un ciclo NUNCA se declara con una sola vuelta (una vuelta
                    no es un ciclo, es una secuencia), pero A-B-A-B y
                    A-B-C-A-B-C ya son evidencia suficiente.
      max_avisos .. avisos antes de bloquear. Igual que Hermes, que separa
                    `warn_after` de `hard_stop_after`: primero se le habla al
                    modelo, se corta solo si insiste.
      exentas ..... tools que NO entran en la ventana (polling legitimo). El
                    default es vacio a proposito, para que el guardia no
                    invente politica; el cableado de Cognia debe pasar
                    `EXENTAS_COGNIA`.
    """

    def __init__(self, ventana: int = 10, umbral: int = 3, max_avisos: int = 2,
                 exentas: frozenset = frozenset()):
        # Saneo defensivo: valores absurdos degradan al minimo utilizable en vez
        # de reventar en el primer registrar().
        try:
            self.ventana = max(2, int(ventana))
        except (TypeError, ValueError):
            self.ventana = 10
        try:
            self.umbral = max(2, int(umbral))
        except (TypeError, ValueError):
            self.umbral = 3
        try:
            self.max_avisos = max(0, int(max_avisos))
        except (TypeError, ValueError):
            self.max_avisos = 2
        try:
            self.exentas = frozenset(str(t) for t in (exentas or ()))
        except TypeError:
            self.exentas = frozenset()
        self.reiniciar()

    # -- estado ------------------------------------------------------------

    def reiniciar(self) -> None:
        """Borra el estado. Se llama al empezar una tarea (equivalente a
        `reset_for_turn` de Hermes: los contadores son POR TAREA, no de por
        vida, para que una sesion larga y sana nunca herede un bucle viejo)."""
        self._ventana = deque(maxlen=self.ventana)
        self._meta: dict = {}          # firma -> (nombre, args_resumidos)
        self._avisos = 0
        self._nuevas_seguidas = 0      # contador de REINICIO (ver registrar)
        self._bloqueo: dict | None = None

    @property
    def bloqueado(self) -> bool:
        return self._bloqueo is not None

    # -- camino caliente ---------------------------------------------------

    def registrar(self, nombre_tool: str, args: Any = None) -> dict:
        """Registra una llamada y devuelve el veredicto. NUNCA lanza."""
        try:
            return self._registrar(nombre_tool, args)
        except Exception:
            # Un guardia roto no puede matar una tarea sana: degrada a 'ok'.
            return _veredicto()

    def _registrar(self, nombre_tool: str, args: Any) -> dict:
        nombre = str(nombre_tool or "").strip()

        # Exentas: ni cuentan ni resetean. `ver_salida` en bucle sobre un
        # proceso vivo es POLLING; si ademas reseteara el contador de reinicio,
        # intercalarla limpiaria un bucle real gratis.
        if nombre in self.exentas:
            return _veredicto(tool=nombre, avisos=self._avisos)

        # Bloqueo pegajoso: si el que llama ignora el corte y sigue registrando,
        # el veredicto se mantiene (no se "des-bloquea" solo).
        if self._bloqueo is not None:
            return dict(self._bloqueo)

        firma = firma_llamada(nombre, args)
        nueva = firma not in self._ventana

        self._ventana.append(firma)
        self._meta[firma] = (nombre, _resumen_args(args))
        self._podar_meta()

        # CONTADOR DE REINICIO: `umbral` acciones seguidas GENUINAMENTE nuevas
        # (que no estaban en la ventana) significan que el agente esta
        # avanzando, asi que la escalada vuelve a cero y se le vuelve a hablar
        # con un aviso antes de cortar.
        # OJO: se reinician los AVISOS, no la ventana. Vaciar la ventana aqui
        # dejaria CIEGO al detector de ciclos: en A-B-C-A-B-C las tres primeras
        # son nuevas y el borrado se comeria justamente la primera vuelta.
        if nueva:
            self._nuevas_seguidas += 1
            if self._nuevas_seguidas >= self.umbral:
                self._avisos = 0
                self._nuevas_seguidas = 0
        else:
            self._nuevas_seguidas = 0

        hallazgo = self._detectar()
        if hallazgo is None:
            return _veredicto(tool=nombre, firma=firma, avisos=self._avisos)

        patron, periodo, vueltas, bloque = hallazgo
        self._avisos += 1
        descripcion = self._describir(bloque)

        if self._avisos > self.max_avisos:
            ver = _veredicto(
                estado="bloqueo", patron=patron, razon="bucle_detectado",
                tool=nombre, firma=firma, repeticiones=vueltas,
                avisos=self._avisos,
                mensaje=(
                    f"Bucle detectado ({patron}): {descripcion} se repitio "
                    f"{vueltas} veces y el agente ignoro {self.max_avisos} "
                    f"aviso(s). Se corta la tarea."))
            self._bloqueo = dict(ver)
            return ver

        return _veredicto(
            estado="aviso", patron=patron, tool=nombre, firma=firma,
            repeticiones=vueltas, avisos=self._avisos,
            mensaje=self._mensaje_al_modelo(patron, vueltas, descripcion))

    # -- deteccion ---------------------------------------------------------

    def _detectar(self):
        """Busca el ciclo mas CORTO al final de la ventana.

        Un unico barrido cubre las tres formas: periodo 1 = repeticion
        consecutiva, periodo 2 = ping-pong A-B-A-B, periodo p>=3 = ciclo
        A-B-C-A-B-C. Se prueba de menor a mayor periodo para que A-A-A-A se
        reporte como 'repeticion' y no como un ping-pong de A consigo mismo.
        """
        seq = list(self._ventana)
        n = len(seq)
        for periodo in range(1, self.ventana // 2 + 1):
            minimo = self.umbral if periodo == 1 else max(2, _techo(self.umbral, periodo))
            if periodo * minimo > n:
                continue
            bloque = seq[n - periodo:]
            vueltas = 0
            # Cuenta cuantos bloques identicos hay pegados al final: el numero
            # que se le dice al modelo tiene que ser el REAL, no el umbral.
            while (vueltas + 1) * periodo <= n and \
                    seq[n - (vueltas + 1) * periodo: n - vueltas * periodo] == bloque:
                vueltas += 1
            if vueltas >= minimo:
                if periodo == 1:
                    patron = "repeticion"
                elif periodo == 2:
                    patron = "ping_pong"
                else:
                    patron = f"ciclo_{periodo}"
                return patron, periodo, vueltas, bloque
        return None

    def _describir(self, bloque) -> str:
        """Nombra la accion (o la secuencia) prohibida.

        Medicion del repo (+62pp, bench_estancamiento): el aviso generico NO
        desvia al modelo chico; hay que decirle textualmente que accion dejo de
        estar permitida.
        """
        partes = []
        for firma in bloque:
            nombre, resumen = self._meta.get(firma, ("?", ""))
            partes.append(f"'{nombre} {resumen}'" if resumen else f"'{nombre}'")
        return " -> ".join(partes)

    def _mensaje_al_modelo(self, patron: str, vueltas: int, descripcion: str) -> str:
        """Texto que se INYECTA al modelo. Sin acentos, como el resto de los
        avisos que ya viajan en el historial del agente (cli.py)."""
        if patron == "repeticion":
            cabeza = (f"AVISO DE BUCLE: ya ejecutaste {descripcion} {vueltas} "
                      "veces y no avanzo.")
        elif patron == "ping_pong":
            cabeza = (f"AVISO DE BUCLE: estas alternando entre {descripcion} "
                      f"({vueltas} vueltas) sin avanzar.")
        else:
            cabeza = (f"AVISO DE BUCLE: estas repitiendo el ciclo {descripcion} "
                      f"({vueltas} vueltas) sin avanzar.")
        return cabeza + (
            " PROHIBIDO repetir esa misma secuencia. Proba una herramienta "
            "DISTINTA, cambia los argumentos, o cerra declarando que NO PODES "
            "y por que — decirlo es un final valido; repetir no.")

    def _podar_meta(self) -> None:
        # El diccionario de metadatos solo sirve para redactar el mensaje: si
        # crece, se queda con lo que hay en la ventana. Cota barata para una
        # sesion larga.
        if len(self._meta) > 256:
            vivas = set(self._ventana)
            self._meta = {k: v for k, v in self._meta.items() if k in vivas}


# --------------------------------------------------------------------------
# Guardia de bucles de CONTENIDO
# --------------------------------------------------------------------------

class GuardiaContenido:
    """Detecta al modelo repitiendo el MISMO texto (el otro patron de bucle).

    Mecanismo de `loopDetectionService` (Gemini CLI): se hashea una ventana
    deslizante de `chunk` caracteres en CADA posicion del texto acumulado; si
    un mismo hash aparece `umbral` veces Y las apariciones estan cerca entre si
    (distancia media <= 1.5 * chunk), es un bucle de contenido.

    El control de distancia es lo que separa "el modelo se trabo" de "esa frase
    de 50 chars es comun en un documento largo": sin el, un encabezado repetido
    a lo largo de un informe entero daria falso positivo.

    No tiene estado 'aviso': un stream que se repite ya esta quemando tokens y
    no lee ningun aviso hasta terminar. Es ok o bloqueo.
    """

    def __init__(self, chunk: int = CHUNK_CONTENIDO, umbral: int = UMBRAL_CONTENIDO):
        try:
            self.chunk = max(1, int(chunk))
        except (TypeError, ValueError):
            self.chunk = CHUNK_CONTENIDO
        try:
            self.umbral = max(2, int(umbral))
        except (TypeError, ValueError):
            self.umbral = UMBRAL_CONTENIDO
        self.distancia_maxima = max(1, int(self.chunk * FACTOR_DISTANCIA))
        # Cota del buffer: solo hace falta el tramo reciente. Con margen de 4x
        # el texto minimo que podria formar un bucle.
        self._tope_buffer = max(self.chunk * 8, self.chunk * self.umbral * 4)
        self.reiniciar()

    def reiniciar(self) -> None:
        """Borra el estado. El cableado la llama entre turnos (y tras cada tool,
        igual que Gemini, que resetea el detector de contenido cuando el agente
        hace una llamada: el texto de antes y el de despues no son el mismo
        discurso)."""
        self._buffer = ""
        self._base = 0        # indice absoluto del primer char del buffer
        self._siguiente = 0   # proxima posicion absoluta por hashear
        self._indices: dict = {}
        self._bloqueo: dict | None = None

    @property
    def bloqueado(self) -> bool:
        return self._bloqueo is not None

    def registrar(self, texto: str) -> dict:
        """Acumula un trozo de salida del modelo y devuelve el veredicto. NUNCA lanza."""
        try:
            return self._registrar(texto)
        except Exception:
            return _veredicto()

    def _registrar(self, texto: str) -> dict:
        if self._bloqueo is not None:
            return dict(self._bloqueo)
        if not texto:
            return _veredicto()
        self._buffer += str(texto)

        limite = self._base + len(self._buffer) - self.chunk
        while self._siguiente <= limite:
            ini = self._siguiente - self._base
            h = _sha(self._buffer[ini:ini + self.chunk])
            posiciones = self._indices.setdefault(h, [])
            posiciones.append(self._siguiente)
            # Solo interesan las ultimas `umbral` apariciones: la lista no
            # puede crecer con el stream.
            if len(posiciones) > self.umbral:
                del posiciones[:-self.umbral]
            self._siguiente += 1

            if len(posiciones) >= self.umbral and self._cerca(posiciones):
                ver = _veredicto(
                    estado="bloqueo", patron="contenido_repetido",
                    razon="bucle_detectado", repeticiones=len(posiciones),
                    mensaje=(
                        f"Bucle de contenido: el mismo fragmento de "
                        f"{self.chunk} caracteres aparecio {len(posiciones)} "
                        "veces seguidas. El modelo se esta repitiendo; se corta "
                        "la generacion."))
                self._bloqueo = dict(ver)
                return ver

        self._podar()
        return _veredicto()

    def _cerca(self, posiciones) -> bool:
        """Las apariciones tienen que estar pegadas: distancia MEDIA entre
        consecutivas <= 1.5 * chunk (regla de la fuente)."""
        distancia = (posiciones[-1] - posiciones[0]) / float(len(posiciones) - 1)
        return distancia <= self.distancia_maxima

    def _podar(self) -> None:
        if len(self._buffer) <= self._tope_buffer:
            return
        # Nunca se recorta por delante de lo que falta hashear.
        corte = min(len(self._buffer) - self._tope_buffer,
                    max(0, self._siguiente - self._base))
        if corte <= 0:
            return
        self._buffer = self._buffer[corte:]
        self._base += corte
        # El diccionario de hashes tambien tiene que caducar, o una generacion
        # larga lo hace crecer sin techo.
        if len(self._indices) > self._tope_buffer * 2:
            vivos = self._base
            self._indices = {k: v for k, v in self._indices.items()
                             if v and v[-1] >= vivos}
