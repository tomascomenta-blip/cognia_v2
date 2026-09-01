"""
cognia/agent/chat_client.py
===========================
Cliente UNICO del agente sobre /v1/chat/completions (A1 de la obra 2026-08-09).

POR QUE EXISTE: cada paso del agente pasaba por una plantilla ChatML
hardcodeada + POST crudo a /completion con stops de Qwen. gpt-oss (harmony)
recibia los marcadores ChatML como texto plano y el loop no entendia su
respuesta — la causa raiz medida de "el mismo modelo rinde peor en Cognia"
(evidencia baseline 2026-08-09: 0/1 en una tarea trivial).

Aca el agente manda MENSAJES ESTRUCTURADOS (system/user/assistant/tool) y
TOOLS nativas; el server aplica la plantilla del modelo (llama-server con
--jinja parsea los tool calls de harmony gratis) y este cliente expone lo
que el arnes viejo tiraba: finish_reason, usage REAL y reasoning_content.

Verificado de primera mano (2026-08-09, :8080, build b10066): POST con
tools -> finish_reason='tool_calls' + message.tool_calls con arguments JSON;
turno role='tool' + reasoning_content en el assistant aceptados de vuelta;
chat_template_kwargs.reasoning_effort aceptado; cierre en prosa ->
finish_reason='stop' sin tool_calls.

Solo stdlib (urllib).

STREAMING (2026-08-17, T1): hay una rama SSE **opt-in** por callbacks
(on_token / on_reasoning / cancelado). Sin esos kwargs el body y el camino
son los historicos BYTE A BYTE (hay un test que lo fija) — nadie que no la
pida cambia de comportamiento. Ver `completar()` para el contrato completo.

Tres cosas que costaron sangre y estan fijadas por tests (2026-08-17, T3):

  * HTTPS. Sobre TLS "bloquearia" NO llega como None sino como
    ssl.SSLWantReadError: la rama SSE moria en el primer silencio del backend
    con COGNIA_LLM_URL=https://... Ver `_canal_no_bloqueante`.
  * El corte se decide y se ANOTA en UN solo lugar (`_Corte`), y los tool
    calls de un turno cortado se arman bajo otra clave (`_crudo_desde_stream`)
    en vez de vaciarse despues. Cortar y devolver tool calls ejecutables ya no
    es algo que se pueda escribir.
  * Con STREAM el timeout es de INACTIVIDAD: es el timeout de socket de
    urlopen y se rearma con cada frame, asi que lo dispara un SILENCIO y no
    una respuesta lenta. El stream agrega ADEMAS un tope de pared porque en
    no bloqueante el de urlopen deja de regir.
  * SIN STREAM ese mismo numero es un deadline de PARED, no de inactividad.
    Este renglon decia "en los dos caminos" y era FALSO (corregido
    2026-08-26): llama-server no escribe ni la linea de estado HTTP hasta
    terminar la generacion entera, asi que el unico recv del camino
    no-stream abarca connect + prefill + pensamiento + generacion y el
    timeout de socket los cubre a todos de una vez.
    MEDIDO con un server que tarda 6 s y un presupuesto de 3 s (mismo
    completar(), lo unico que cambia es pasar on_token):
        no-stream : ok=False  tardo=3,02 s  error='TimeoutError: timed out'
        stream SSE: ok=True   tardo=9,03 s  respuesta entregada entera
    Por eso el bucle del agente pasa siempre por la rama SSE desde el
    2026-08-26 (loop.py::_kwargs_stream); quien llame sin callbacks tiene que
    dimensionar `timeout` como PARED de la generacion completa.
"""
from __future__ import annotations

import json
import os
import select
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR, url_del_backend

# El agente puede tardar: un paso con pensamiento largo en CPU/GPU chica va
# por minutos, no segundos. Override por env para bancos/tests.
_TIMEOUT_S = float(os.environ.get("COGNIA_CHAT_TIMEOUT", "300"))

# 2026-08-15, MEDIDO en el e2e con Nemotron 30B-A3B: un paso del agente cuesta
# ~161 s y `/hacer` moria con TimeoutError; `/workflow` moria en 300,01 s
# EXACTOS (la firma de un timeout propio, no de un cuelgue). Con 900 s las
# mismas tareas salen 1/1 y 2/2. O sea: el 300 no protegia de nada, mataba
# tareas sanas.
#
# El numero no puede ser fijo porque depende del MODELO servido: 300 s le
# sobran a un 3B y le faltan a un 30B-A3B con expertos en CPU. Se deriva de la
# velocidad de generacion, que ya esta medida por familia, con un piso en el
# valor historico (nadie pierde timeout por esto) y un techo para que un
# cuelgue de verdad no se coma la sesion entera.
_TIMEOUT_PISO_S = 300.0
_TIMEOUT_TECHO_S = 1800.0
# tok/s de generacion medidos en esta maquina. El default (45) es el de un
# modelo chico; los lentos se declaran aca porque su latencia es estructural
# (MoE con expertos en RAM), no un mal dia.
#
# CORREGIDO el mismo 2026-08-15: el 14 de la primera version se midio con el
# server DEGRADADO (arrancaba con --n-gpu-layers 99, spilleaba a RAM y daba
# 113 tok/s de prefill). Con el arranque arreglado son 39,3 tok/s de
# generacion y 1.878 de prefill. Moraleja repetida: antes de declarar lenta a
# una familia, comprobar que el instrumento no este roto -- si no, se cablea
# una constante que documenta una averia propia.
# Nota: a profundidad extrema (1M de contexto) la generacion SI cae a ~14
# tok/s, pero eso es una tarea excepcional, no el caso comun del bucle.
# qwen3.8-27b (MEDIDO 2026-08-26, RTX 5060 Ti, ctx 65.536, KV q8_0, MTP n=2,
# 400 tokens generados contra el :8080 vivo): 24,7 tok/s de PUNTA A PUNTA
# vistos por el cliente -- el server reporta 35,8 tok/s de decode puro, pero
# lo que hay que presupuestar es lo que tarda la llamada, no lo que tarda el
# kernel. Con el default de 45 el presupuesto salia 1,8x optimista: para el
# techo de reintento (16.384 tokens) la cuenta daba 546 s y la generacion
# real cuesta 663 s. La entrada va por familia y no por gguf porque el nombre
# del fichero cambia con la cuantizacion.
_TOK_S_POR_FAMILIA = {"nemotron": 39.0, "qwen3.8-27b": 25.0}
_TOK_S_DEFECTO = 45.0


def _modelo_servido(url: str = "") -> str:
    """El gguf que sirve ese backend, o "". Usa el /props cacheado y nunca
    lanza: esto corre en el camino caliente de CADA turno del agente."""
    try:
        from cognia.backend_activo import props
        return (props(url or url_del_backend()) or {}).get("modelo") or ""
    except Exception:
        return ""


# RELOJ DE PARED del stream (2026-08-17, hallazgo #3). `timeout_para()` es un
# presupuesto de INACTIVIDAD — es lo que significa el timeout de urlopen, que
# es el del SOCKET (por lectura) y no de la respuesta entera. La rama SSE lo
# habia convertido en silencio en un deadline de PARED y mataba streams SANOS:
# MEDIDO, timeout=2,0 s contra un server que tokeniza 3 s sin callarse nunca
# mas de 0,1 s daba ok=False 'el stream no termino en 2s' y se tiraban los 20
# tokens ya entregados.
#
# Pero la pared NO puede desaparecer: con el socket en no bloqueante el
# timeout de urlopen deja de regir, y un proxy que manda un keepalive cada
# 50 ms tiene inactividad CERO para siempre. Asi que hay dos relojes.
#
# EL NUMERO. Lo que un stream sano necesita de pared es prefill + generacion:
#   * prefill medido en :8080 = 1.878 tok/s -> 150k tokens (la ventana eficaz
#     de la memoria del repo) son ~80 s, y el millon de Nemotron ~530 s;
#   * generacion 39-45 tok/s -> 4096 tokens son 91-105 s.
# El peor caso sano medible es entonces ~635 s contra un `espera` de 300 s
# (el piso): factor 2,1. Con x4 queda casi el doble de margen sobre ese peor
# caso y sigue siendo un tope. El techo absoluto de 1 h es lo que puede costar
# un server que pinguea eternamente — que hoy, por el camino no-stream,
# cuelga el turno PARA SIEMPRE (el timeout de socket tampoco lo salva).
_FACTOR_PARED_STREAM = 4.0
_PARED_TECHO_S = 3600.0


def _pared_del_stream(espera: float) -> float:
    """Tope de PARED del stream a partir del presupuesto de inactividad.

    Nunca por debajo de `espera`: si el llamador pide un timeout enorme, el
    reloj que manda tiene que seguir siendo el suyo."""
    return max(espera, min(espera * _FACTOR_PARED_STREAM, _PARED_TECHO_S))


def timeout_para(modelo: str = "", max_tokens: int = 4096) -> float:
    """Segundos de espera razonables para UN turno con ese modelo.

    Se calcula sobre el peor caso real: generar `max_tokens` a la velocidad
    medida de la familia, con un x1,5 de holgura para el prefill y el
    pensamiento. Un timeout que corta antes de que el modelo pueda terminar
    no es una proteccion: es una tarea perdida y un diagnostico falso
    ("se colgo") sobre algo que solo iba lento.

    QUE MIDE ESTE NUMERO, y depende del CAMINO (corregido 2026-08-26; antes
    esta seccion decia "inactividad, no pared" a secas y era falso para la
    mitad de los llamadores):

      * CON stream (on_token/on_reasoning/cancelado) mide **inactividad**. Es
        el timeout de socket de urlopen y se rearma en cada lectura: una
        respuesta que tarda 10 minutos en salir entera no lo dispara mientras
        el server siga hablando. Lo dispara un silencio mas largo que el
        presupuesto (un prefill descomunal, un backend colgado). La rama SSE
        agrega ADEMAS un tope de pared (ver `_pared_del_stream`).
      * SIN stream mide **pared**. No porque el timeout sea distinto —es el
        mismo settimeout— sino porque en ese camino solo hay UN recv largo:
        llama-server no manda ni la linea de estado hasta haber generado
        todo, asi que ese unico silencio incluye la generacion completa. Un
        turno que tarde mas que el presupuesto muere aunque el server este
        perfectamente sano. Es lo que se llevo la tarea larga del 2026-08-26
        a las 12:01 con 'TimeoutError: timed out'.

    O sea: el numero de abajo esta calculado como presupuesto de GENERACION
    (max_tokens / tok_s * 1,5). Eso es lo correcto para el camino no-stream y
    holgado para el de stream.
    """
    if os.environ.get("COGNIA_CHAT_TIMEOUT"):
        return float(os.environ["COGNIA_CHAT_TIMEOUT"])
    bajo = (modelo or "").lower()
    tok_s = _TOK_S_DEFECTO
    for fam, v in _TOK_S_POR_FAMILIA.items():
        if fam in bajo:
            tok_s = v
            break
    estimado = (max_tokens / tok_s) * 1.5
    return max(_TIMEOUT_PISO_S, min(_TIMEOUT_TECHO_S, estimado))

# KV sucio tras un hot-swap de LoRA (plan LoRA Qwythos 2026-08-09).
# POR QUE: completar() postea DIRECTO a /v1/chat/completions sin pasar por
# node/llama_backend, asi que el _consume_lora_dirty del backend NO cubre el
# camino nativo — tras un POST /lora-adapters la primera request del agente
# reutilizaria KV calculado con otros pesos efectivos (llama.cpp NO lo
# invalida solo; medido 2026-07-07, FLEET_DESIGN). Dict mutable y no bool
# suelto para que el estado sea modulo-global de verdad (visible desde
# cualquier import del modulo, sin `global` fragil).
_KV_SUCIO = {"v": False}


def marcar_kv_sucio() -> None:
    """Marca el KV del server como invalido tras un swap real de LoRA.

    La PROXIMA completar() (y solo esa) mandara cache_prompt: false —
    extension del body que llama-server acepta en /v1/chat/completions —
    para reconstruir el KV con los pesos efectivos actuales. La llama quien
    hace el swap (guard A3 de cli.py tras activate_expert)."""
    _KV_SUCIO["v"] = True


@dataclass
class ToolCall:
    """Un tool call parseado por el server (arguments ya como dict)."""
    id: str = ""
    nombre: str = ""
    argumentos: dict = field(default_factory=dict)
    argumentos_crudos: str = ""   # el JSON original, para el round-trip
    # True cuando `argumentos_crudos` NO era JSON valido y `argumentos` es el
    # envoltorio de rescate {"args": <crudo>}. Sin esta marca, unos argumentos
    # TRUNCADOS ('{"ru') se ven exactamente igual que unos legitimos: quien
    # ejecute la tool tiene que poder distinguirlos (hallazgo #5).
    argumentos_rotos: bool = False


@dataclass
class RespuestaChat:
    """Lo que el paso del agente necesita ver de una respuesta, completo.

    El arnes viejo solo miraba .text y por eso los dos modos de fallo
    (truncado por presupuesto vs stop mal puesto) se veian iguales.
    """
    texto: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str = ""       # 'stop' | 'tool_calls' | 'length' | ...
    # USAGE VACIO SIGNIFICA "NO SE PUDO SABER", NUNCA "0 tokens". Pasa cuando
    # se corto a mitad, cuando el server ignora stream_options.include_usage
    # y tampoco manda timings, o cuando la peticion fallo. Sumar
    # `usage.get('completion_tokens') or 0` mezcla los dos casos y el
    # presupuesto se descuadra en silencio: usar .completion_tokens (None =
    # desconocido) para poder distinguirlos.
    usage: dict = field(default_factory=dict)
    reasoning_content: str = ""
    error: str = ""               # no-vacio => la peticion fallo (degradable)
    duracion_s: float = 0.0
    # MARCA DE CORTE (solo rama streaming): True cuando cancelado() pidio
    # parar y se dejo de leer. Lo de arriba (texto/reasoning) es lo que
    # alcanzo a llegar, NO la respuesta del modelo. Se distingue de "termino"
    # por los dos lados: `cortado is True` y `finish_reason == 'cancelado'`
    # (valor que el server nunca manda).
    cortado: bool = False
    # Al cortar, los tool calls rearmados de fragmentos van ACA y NO en
    # .tool_calls: pueden estar truncados a mitad de los arguments y, sobre
    # todo, el usuario ya dijo que pare — ejecutar una herramienta despues
    # de eso es exactamente lo que no puede pasar (hallazgo #5).
    tool_calls_parciales: list = field(default_factory=list)
    # True cuando el usage NO vino del chunk `usage` del server sino de
    # `timings.predicted_n` (la red del hallazgo #3) o de contar los frames de
    # contenido (defecto #5). El numero es real por otra via, pero puede venir
    # sin prompt_tokens.
    usage_estimado: bool = False
    # POR QUE VIA salio el usage: "" (no se pudo saber) | "server" (el chunk de
    # include_usage) | "timings" (predicted_n) | "frames" (los frames de
    # contenido contados al cortar). `usage_estimado` dice SI se estimo; esto
    # dice CON QUE, que es lo que permite juzgar cuanto vale el numero: las
    # timings las cuenta llama.cpp y los frames los contamos nosotros.
    usage_via: str = ""
    # Renglones `data:` que no parsearon como JSON. > 0 con frames validos =
    # el stream llego sucio pero utilizable; el contador existe para que se
    # pueda ver, no para escribirlo y olvidarlo.
    frames_malformados: int = 0

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def completion_tokens(self):
        """Tokens generados, o **None si no se pudo saber** (!= 0 tokens).

        La distincion existe porque quien lleva presupuesto tiene que poder
        elegir: un None es "no cuento este turno / lo estimo aparte", un 0 es
        "el modelo no genero nada". Con `usage.get(...) or 0` los dos casos
        se ven iguales y el presupuesto se cae para el lado equivocado."""
        v = (self.usage or {}).get("completion_tokens")
        return int(v) if isinstance(v, (int, float)) else None


def _parse_tool_calls(crudos: list) -> list:
    calls = []
    for tc in crudos or []:
        fn = tc.get("function") or {}
        crudo = fn.get("arguments") or ""
        rotos = False
        try:
            args = json.loads(crudo) if crudo else {}
            if not isinstance(args, dict):
                args = {"args": args}
        except ValueError:
            # JSON roto: no se pierde — la tool vera el crudo y su error de
            # formato volvera al modelo como turno tool (señal correcta) —
            # pero SI se marca: en el stream, un arguments a medio llegar
            # degradaba a {"args": '{"ru'} sin que nada lo dijera.
            args = {"args": crudo}
            rotos = True
        calls.append(ToolCall(id=tc.get("id") or "", nombre=fn.get("name") or "",
                              argumentos=args, argumentos_crudos=crudo,
                              argumentos_rotos=rotos))
    return calls


# --- rama streaming (opt-in) -------------------------------------------
# Bytes por lectura del socket.
_STREAM_CHUNK_B = 16384
# Cada cuanto se despierta el lector para volver a consultar cancelado()
# cuando el socket esta callado. MEDIDO 2026-08-17 con el server mudo: la
# bandera puesta en 0,30 s vuelve de completar() en ~0,35 s (pedido: <0,5 s).
_PASO_CANCELADO_S = 0.05


def _avisar(msg: str) -> None:
    """Aviso a stderr de algo raro EN el stream que no justifica abortar.

    Existe para no repetir el `except Exception: pass` del parser viejo de
    node/llama_backend.py: una linea SSE ilegible o un callback roto tienen
    que VERSE. Silenciable con COGNIA_BACKEND_LOG=0, igual que la constancia
    de backend_activo. NO se llama derecho desde el bucle del stream: va por
    _Avisos, que le pone tope (abajo)."""
    if os.environ.get("COGNIA_BACKEND_LOG") == "0":
        return
    try:
        print(f"[chat_client] {msg}", file=sys.stderr)
    except Exception:
        pass


class _Avisos:
    """Tope de ruido para los avisos de UN stream.

    Sin tope, un on_token roto avisaba UNA VEZ POR TOKEN: 4.000 lineas de
    stderr dentro del CLI en una respuesta larga, que es justo la guerra que
    el repo tiene contra los logs. Aca se avisa la PRIMERA vez de cada clase
    y al cerrar sale una sola linea con las repeticiones (contar es la mitad
    del aviso: "paso 4.000 veces" es mas informativo que 4.000 lineas)."""

    def __init__(self):
        self.cuentas: dict = {}

    def avisar(self, clave: str, msg: str) -> None:
        n = self.cuentas.get(clave, 0) + 1
        self.cuentas[clave] = n
        if n == 1:
            _avisar(msg)

    def resumen(self) -> None:
        rep = [f"{k} x{n}" for k, n in sorted(self.cuentas.items()) if n > 1]
        if rep:
            _avisar("avisos repetidos (solo se mostro el primero de cada "
                    "clase): " + ", ".join(rep))


def _seguro(cb, frag: str, avisos: "_Avisos") -> None:
    """Un callback del llamador no puede matar el turno del agente."""
    if cb is None:
        return
    try:
        cb(frag)
    except Exception as e:
        avisos.avisar("callback",
                      f"callback de stream fallo: {type(e).__name__}: {e}")


def _corte_pedido(cancelado, avisos: "_Avisos") -> bool:
    """cancelado(), bajo la MISMA politica que los otros callbacks.

    Antes se llamaba pelado, fuera de _seguro: un cancelado() que lanzaba
    (cerro sobre un widget destruido, una cola ya cerrada) mataba el turno con
    error='RuntimeError: ...' y loop.py cortaba la tarea.

    DECISION: un cancelado() roto **no cancela y no aborta**. Se avisa una
    vez y se sigue como si hubiera dicho False. Cancelar seria inventarle al
    usuario una intencion que no expreso; abortar es peor todavia, porque
    mata un turno sano por un bug del observador. El precio es que un
    cancelado() permanentemente roto vuelve la respuesta incancelable, y por
    eso el aviso sale igual."""
    if cancelado is None:
        return False
    try:
        return bool(cancelado())
    except Exception as e:
        avisos.avisar("cancelado", "cancelado() fallo y NO se corta: "
                                   f"{type(e).__name__}: {e}")
        return False


class _Corte:
    """EL UNICO sitio donde se decide — y se ANOTA — que el usuario corto.

    POR QUE UNA CLASE Y NO TRES `if`: el bucle del stream consulta el corte en
    tres puntos (arriba de cada vuelta, antes de despachar cada frame, y antes
    de procesar el ultimo renglon sin \\n). Con la consulta suelta, uno de los
    tres — el de la cola — descartaba el frame pero NO marcaba `cortado`, asi
    que el vaciado de tool_calls de mas abajo NO corria: MEDIDO 2026-08-17,
    cancelar justo en esa consulta devolvia cortado=False,
    finish_reason='tool_calls' y .tool_calls con un 'borrar_todo' EJECUTABLE
    despues de que el usuario apreto Esc (y sin tools, una respuesta TRUNCADA
    con finish_reason='' que se ve igual que una completa).

    Aca la bandera vive DENTRO del mismo metodo que la consulta: "preguntar y
    no anotar" dejo de ser algo que se pueda escribir. `acc["cortado"]` se
    asigna en UNA sola linea de todo el modulo, la de abajo.

    Es ademas un LATCH: una vez pedido el corte no se vuelve a llamar a
    cancelado() (un cancelado() que oscila no puede "descancelar" un turno que
    ya dejo de leer).
    """

    def __init__(self, acc: dict, cancelado, avisos: "_Avisos"):
        self._acc = acc
        self._cancelado = cancelado
        self._avisos = avisos

    def pedido(self) -> bool:
        if self._acc["cortado"]:
            return True
        if _corte_pedido(self._cancelado, self._avisos):
            self._acc["cortado"] = True
        return self._acc["cortado"]


class _Deschunker:
    """Saca el framing `Transfer-Encoding: chunked` del cuerpo.

    POR QUE A MANO SI http.client YA LO HACE: su parser solo sirve con
    lecturas BLOQUEANTES, y aca las lecturas tienen que ser no bloqueantes
    (unica forma medida de que el corte no dependa de que el backend hable).
    MEDIDO 2026-08-17 sobre un server SSE real:

      * con timeout corto en el socket, la primera lectura vencida deja el
        SocketIO en `OSError: cannot read from timed out object`;
      * forzandolo (`raw._timeout_occurred = False`), `_get_chunk_left()`
        vuelve a descartar el CRLF del chunk anterior que YA habia descartado
        y el frame siguiente sale `IncompleteRead(0 bytes read)`.

    O sea: no es que quede mas lindo aca abajo, es que por arriba no se
    puede. El deschunkeo en si son cuatro estados y esta cubierto por tests
    con el cuerpo partido en pedazos de un byte.
    """

    def __init__(self, activo: bool):
        self.activo = activo
        self.fin = False
        self._buf = b""
        self._resta = 0
        self._estado = "tam"        # tam -> cuerpo -> crlf -> tam

    def alimentar(self, datos: bytes) -> bytes:
        if not self.activo:
            return datos
        self._buf += datos
        salida = []
        while not self.fin:
            if self._estado == "tam":
                i = self._buf.find(b"\r\n")
                if i < 0:
                    break
                linea = self._buf[:i].split(b";")[0].strip()   # extensiones
                self._buf = self._buf[i + 2:]
                try:
                    self._resta = int(linea, 16)
                except ValueError:
                    raise ValueError(
                        f"framing chunked roto: tamaño {linea[:40]!r}")
                if self._resta == 0:
                    self.fin = True      # los trailers no nos interesan
                    break
                self._estado = "cuerpo"
            elif self._estado == "cuerpo":
                if not self._buf:
                    break
                n = min(self._resta, len(self._buf))
                salida.append(self._buf[:n])
                self._buf = self._buf[n:]
                self._resta -= n
                if self._resta == 0:
                    self._estado = "crlf"
            else:
                if len(self._buf) < 2:
                    break
                self._buf = self._buf[2:]
                self._estado = "tam"
        return b"".join(salida)


# "Bloquearia" tiene DOS formas segun el transporte. Sobre TCP pelado
# socket.SocketIO.readinto mapea EAGAIN/EWOULDBLOCK a None y no hay excepcion;
# sobre TLS, SSLSocket.recv_into LANZA ssl.SSLWantReadError, cuyo errno es
# ssl.SSL_ERROR_WANT_READ (2) y por eso NO esta en el `_blocking_errnos` de
# SocketIO: la excepcion sube tal cual. MEDIDO 2026-08-17 con un server SSE
# real sobre TLS autofirmado (un token y pausa):
#   HTTPS stream:  tardo=0,01s ok=False error='SSLWantReadError: The operation
#                  did not complete (read)'  texto='t0'
#   mismo server, camino no-stream: ok=True texto='t0hola'
# O sea: sobre HTTPS la rama de streaming estaba 100% rota y encima el
# fallback degradado NO se activaba, porque setblocking(False) SI funciona
# sobre un SSLSocket y el canal salia "valido".
_BLOQUEARIA = (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError)


def _canal_no_bloqueante(r):
    """(leer, esperar) para consumir el cuerpo SIN bloquear, o (None, None).

    `leer(n)` devuelve bytes si hay datos, None si todavia no llego nada, y
    b"" en EOF. `esperar(t)` duerme hasta t segundos o hasta que haya algo que
    leer. Cuatro cosas medidas obligan a esta forma exacta:

    * Cerrar (o shutdown) el socket desde otro hilo NO desbloquea un recv en
      Windows: el hilo lector siguio 27 s bloqueado y el close() del
      BufferedReader se colgo esperando su lock. Por eso NO hay hilo lector:
      no habria forma de rescatarlo.
    * `BufferedReader.read1()` devuelve b"" tanto en EOF como en "bloquearia"
      (el -2 del raw se colapsa a 0). El SocketIO crudo si los distingue
      (None vs b"") **sobre TCP pelado**, asi que primero se DRENA lo que
      quedo en el buffer al parsear las cabeceras — que puede traer frames
      enteros pegados a la respuesta — y recien despues se lee del raw.
    * Sobre TLS eso no alcanza: "bloquearia" viene como EXCEPCION y hay que
      atraparla (ver _BLOQUEARIA arriba). Con read1() la distincion vuelve a
      ser limpia — datos / b"" en EOF / SSLWantReadError si bloquearia — asi
      que en TLS el camino se queda en el BufferedReader y no pasa al raw.
    * `select()` NO ve el buffer de descifrado del SSLSocket: OpenSSL entrega
      de a un record, y si en un segmento TCP llegaron varios quedan bytes YA
      DESCIFRADOS que el socket no reporta. Dormir ahi seria colgarse con
      datos en la mano, asi que `esperar()` pregunta primero por
      `sock.pending()`.
      HONESTIDAD SOBRE ESE GUARD: **hoy no dispara nunca** y esta medido. Con
      un stream TLS de 60 frames mandado (a) en UNA rafaga y (b) goteado de a
      7 bytes, `pending()` se consulto 0 y 507 veces y devolvio >0 CERO veces
      (sonda 2026-08-17). La razon es el ORDEN del bucle: siempre se llama a
      `leer()` antes que a `esperar()`, y `leer()` solo devuelve None cuando
      la capa SSL ya no tiene nada descifrado. O sea: es defensa en
      profundidad para que un futuro "optimicemos con un select primero" no
      reintroduzca el cuelgue, no el arreglo de un cuelgue reproducido.
    * Poner un timeout corto y reintentar corrompe el parser chunked de
      http.client (ver _Deschunker).
    """
    fp = getattr(r, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if fp is None or raw is None or sock is None:
        return None, None
    try:
        sock.setblocking(False)
    except OSError:
        return None, None
    # Solo el SSLSocket tiene pending(); sobre TCP pelado queda en None y el
    # camino es exactamente el de antes. Ver el docstring: este guard NO
    # dispara con el orden de bucle actual (medido), es un seguro.
    pendientes_tls = getattr(sock, "pending", None)
    pendiente = {"buffer": True}

    def leer(n: int):
        try:
            if pendiente["buffer"]:
                d = fp.read1(n)
                if d:
                    return d
                # b"" del BufferedReader es ambiguo sobre TCP (EOF o
                # bloquearia): se pasa al raw, que si los distingue. Sobre TLS
                # no se llega aca cuando bloquearia — salta la excepcion —
                # asi que un b"" de verdad es EOF y el raw lo confirma.
                pendiente["buffer"] = False
            return raw.read(n)
        except _BLOQUEARIA:
            return None

    def esperar(t: float) -> None:
        if pendientes_tls is not None:
            try:
                if pendientes_tls():
                    return          # hay bytes descifrados: no dormir
            except Exception:
                pass
        try:
            select.select([sock], [], [], t)
        except (OSError, ValueError):
            # Socket ya cerrado / fd invalido: dormir igual, para no convertir
            # el bucle en un busy-loop que se coma un core.
            time.sleep(t)

    return leer, esperar


def _acumular_tool_calls(acc: dict, deltas: list) -> None:
    """Los tool calls llegan TROCEADOS por indice: el id y el name en el
    primer delta y los arguments en pedazos. Se rearman al vuelo para que la
    rama stream entregue exactamente la misma forma que la no-stream."""
    for d in deltas or []:
        try:
            idx = int(d.get("index") or 0)
        except (TypeError, ValueError):
            idx = 0
        slot = acc.setdefault(idx, {"type": "function", "id": "",
                                    "function": {"name": "", "arguments": ""}})
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


def _procesar_linea(linea: bytes, acc: dict, on_token, on_reasoning,
                    avisos: "_Avisos", on_tool_frag=None) -> bool:
    """Un renglon del SSE. Devuelve True si el stream termino ([DONE])."""
    linea = linea.strip()
    if linea.startswith(b":"):
        # COMENTARIO SSE (el keepalive ": ping" de cualquier proxy). No trae
        # datos, pero PRUEBA que el transporte habla SSE — y eso importa: sin
        # contarlo, un backend muerto en el prefill detras de un proxy que
        # pinguea salia con el diagnostico "el server contesto 200 sin SSE" y
        # la muestra que el propio mensaje imprimia lo desmentia
        # (b': ping\n\n: ping\n\n'). Error correcto, causa falsa.
        acc["comentarios"] += 1
        return False
    if not linea.startswith(b"data:"):
        return False              # renglones vacios entre frames
    crudo = linea[5:].strip()
    if crudo == b"[DONE]":
        acc["frames"] += 1        # [DONE] TAMBIEN prueba que esto era SSE
        return True
    try:
        data = json.loads(crudo)
    except ValueError:
        acc["malformados"] += 1
        avisos.avisar("ilegible", f"linea SSE ilegible (ignorada): {crudo[:120]!r}")
        return False
    acc["frames"] += 1
    # El chunk de usage viene con choices=[] (include_usage). Se queda el
    # ULTIMO no vacio: sin esto usage vuelve None y el presupuesto de tokens
    # sumaria 0 en silencio.
    u = data.get("usage")
    if isinstance(u, dict) and u:
        acc["usage"] = u
    # RED por si el server ignora include_usage: llama.cpp manda las timings
    # en el frame final igual (ver _usage_del_stream).
    t = data.get("timings")
    if isinstance(t, dict) and t:
        acc["timings"] = t
    eleccion = (data.get("choices") or [{}])[0]
    delta = eleccion.get("delta") or {}
    frag = delta.get("reasoning_content") or delta.get("reasoning") or ""
    if frag:
        acc["razon"].append(frag)
        _seguro(on_reasoning, frag, avisos)
    tok = delta.get("content") or ""
    if tok:
        acc["texto"].append(tok)
        _seguro(on_token, tok, avisos)
    if delta.get("tool_calls"):
        _acumular_tool_calls(acc["tcs"], delta["tool_calls"])
        # El unico latido de un turno que esta ESCRIBIENDO: aqui no hay
        # `content` ni razonamiento, solo los argumentos del tool call
        # llegando de a trozos. Sin esto el agente se ve mudo mientras manda
        # un fichero de 30 KB (2026-08-31).
        if on_tool_frag is not None:
            _frag_tc = "".join(
                str(((t or {}).get("function") or {}).get("arguments") or "")
                for t in delta["tool_calls"] if isinstance(t, dict))
            if _frag_tc:
                _seguro(on_tool_frag, _frag_tc, avisos)
    if eleccion.get("finish_reason"):
        acc["finish"] = eleccion["finish_reason"]
    return False


def _leer_stream(r, acc: dict, on_token, on_reasoning, cancelado,
                 inactividad: float, pared: float, on_tool_frag=None) -> None:
    """Consume el SSE de /v1/chat/completions dentro de `acc` (mutable).

    `acc` se pasa desde afuera A PROPOSITO: si el socket se corta a mitad, la
    excepcion sube (no se traga) y el llamador igual tiene lo acumulado hasta
    ese punto para reportarlo junto al error.

    El parser sale del de node/llama_backend.py (probado en vivo contra
    b10066): maneja [DONE], reasoning_content/reasoning y el chunk final con
    finish_reason. Agrega tool_calls troceados, el chunk de usage de
    stream_options.include_usage y las timings como red.

    EL CORTE. cancelado() se consulta (a) cada `_PASO_CANCELADO_S` mientras
    no llegan datos y (b) ANTES de despachar cada frame. Lo primero es lo que
    hace que apretar Esc corte en ~0,35 s aunque el backend este mudo: la
    version anterior solo miraba arriba del bucle y despues se quedaba
    bloqueada en read1(), asi que el corte llegaba cuando el backend volvia a
    hablar — o nunca, hasta el timeout de 1800 s. Lo segundo es lo que impide
    entregar a on_token un token que llego DESPUES de que el usuario corto.
    Quien decide y ANOTA el corte es `_Corte`, uno solo para los tres puntos.

    LOS DOS RELOJES (hallazgo #3). `inactividad` es el presupuesto del turno
    tal como significaba en el camino no-stream: el timeout de urlopen es el
    del SOCKET, se rearma en cada lectura, y por eso un stream lento pero vivo
    nunca lo dispara. `pared` es el tope del stream ENTERO, que hace falta
    solo porque con el socket en no bloqueante el timeout de urlopen deja de
    regir: sin el, un proxy que manda un keepalive cada 50 ms tiene
    inactividad cero para siempre y cuelga el turno. Los dos relojes son
    `time.monotonic()` (convencion del repo, cognia/harness/limites.py): un
    ajuste de hora del sistema no puede matar un turno sano.
    """
    avisos = _Avisos()
    corte = _Corte(acc, cancelado, avisos)
    leer, esperar = _canal_no_bloqueante(r)
    if leer is None:
        # No deberia pasar con urllib. Si pasa, se lee BLOQUEANDO y el corte
        # vuelve a depender de que el backend hable: es una perdida de
        # garantia, se dice en voz alta en vez de degradar en silencio.
        avisos.avisar("bloqueante",
                      "no se pudo leer el stream sin bloquear: el corte va a "
                      "esperar a que el backend hable")
        leer_crudo = getattr(r, "read1", None) or r.read
        dch = _Deschunker(False)          # de eso se encarga http.client
        restante = None

        def leer(n):                      # noqa: F811  (misma firma, bloquea)
            return leer_crudo(n)
    else:
        dch = _Deschunker(bool(getattr(r, "chunked", False)))
        # Sin chunked el cuerpo termina donde diga Content-Length: sin esto,
        # una respuesta keep-alive no daria EOF nunca (el caso del hallazgo
        # #1, un 200 con JSON entero, entra por aca).
        restante = None if dch.activo else getattr(r, "length", None)
    tope_pared = time.monotonic() + pared
    ultimo = time.monotonic()             # cuando llegaron los ultimos bytes
    buf = b""
    trunco = ""
    try:
        while True:
            if corte.pedido():
                return
            ahora = time.monotonic()
            if ahora - ultimo >= inactividad:
                raise TimeoutError(
                    f"el stream se callo {ahora - ultimo:.0f}s (presupuesto "
                    f"de inactividad {inactividad:.0f}s; recibidos "
                    f"{acc['frames']} frames)")
            if ahora >= tope_pared:
                raise TimeoutError(
                    f"el stream no cerro en {pared:.0f}s de pared (recibidos "
                    f"{acc['frames']} frames y {acc['comentarios']} "
                    "keepalives: el transporte habla pero no termina)")
            datos = leer(_STREAM_CHUNK_B)
            if datos is None:
                # Todavia no hay nada: se espera POCO y se vuelve a preguntar
                # por el corte. El esperar despierta apenas llegue un byte, o
                # sea que esperar poco no cuesta latencia de tokens.
                if esperar is not None:
                    esperar(_PASO_CANCELADO_S)
                continue
            if not datos:
                # EOF. Si el cuerpo declaraba su largo (chunked con
                # terminador, o Content-Length) y no llego entero, la
                # conexion MURIO a mitad: eso no es un stream que termina, es
                # un fallo de transporte y tiene que volver como error (antes
                # lo detectaba el IncompleteRead de http.client, que ya no
                # esta en el camino).
                if dch.activo and not dch.fin:
                    trunco = "el stream chunked se corto sin terminador"
                elif restante is not None and restante > 0:
                    trunco = f"faltaron {restante} bytes del Content-Length"
                break
            ultimo = time.monotonic()     # llegaron bytes: reloj de silencio a cero
            if restante is not None:
                restante -= len(datos)
            cuerpo = dch.alimentar(datos)
            if len(acc["muestra"]) < 200:
                acc["muestra"] += cuerpo[:200]
            buf += cuerpo
            while b"\n" in buf:
                if corte.pedido():
                    return
                linea, buf = buf.split(b"\n", 1)
                if _procesar_linea(linea, acc, on_token, on_reasoning, avisos,
                                   on_tool_frag):
                    return
            if dch.fin or (restante is not None and restante <= 0):
                break
        # El ultimo renglon puede venir SIN \n final si el server cierra mal:
        # se descartaba junto con su finish_reason. llama-server cierra bien,
        # pero un proxy o un backend no conforme no tienen por que.
        if buf.strip() and not corte.pedido():
            _procesar_linea(buf, acc, on_token, on_reasoning, avisos,
                            on_tool_frag)
        if trunco:
            raise ConnectionError(f"{trunco} ({acc['frames']} frames "
                                  "recibidos antes del corte)")
    finally:
        avisos.resumen()


def _usage_del_stream(acc: dict) -> dict:
    """El usage del stream, con RED cuando el server ignora include_usage.

    include_usage es un PEDIDO, no una garantia: si el server no manda el
    chunk de usage, `usage` volvia {} y el presupuesto del motor sumaba 0 EN
    SILENCIO. llama.cpp manda `timings.predicted_n` en el frame final AUNQUE
    NO se pida include_usage (verificado en el build b10434: usage en algun
    frame = False, timings en algun frame = True, predicted_n = 16) y el
    parser de node/llama_backend.py:1143 ya lo lee. Se marca
    acc["usage_estimado"] para que el llamador sepa por que via salio.

    SOLO se recupera completion_tokens. `timings.prompt_n` NO es
    prompt_tokens: cuenta los tokens del prompt que se PROCESARON, y con el
    KV cacheado eso no es el prompt. MEDIDO 2026-08-17 en :8080/b10434 sobre
    el mismo prompt: el chunk de usage dice prompt_tokens=40 y las timings
    dicen prompt_n=1. Poner ese 1 como prompt_tokens seria cambiar un cero
    silencioso por un numero silenciosamente MAL, que es peor.

    TERCERA VIA, SOLO AL CORTAR (defecto #5, 2026-08-17). Cuando el usuario
    corta, el cliente deja de leer: el chunk de usage y las timings viajan en
    el frame FINAL, que ya nunca llega. El usage volvia {} y el presupuesto
    del motor —que es COMPARTIDO— sumaba 0 por un corte que si se pago.
    MEDIDO con /tokenize contra :8080, tres cortes: prompt 23 + generados 65
    = ~88 tokens por corte contabilizados como CERO; con presupuesto.gastado()
    en 111 contra ~253 generados de verdad, una sub-cuenta del 56%. El techo
    del agujero era max_repreguntas(8) x (prompt + max_tokens) por agente.
    Los frames de contenido recibidos SON la cuenta de tokens generados (en
    SSE, un frame = un token del delta), asi que se cuentan y se marca la via.

    Lo que sigue SIN contarse es el PROMPT del turno cortado: no llega del
    server y estimarlo desde el cliente seria cambiar un cero silencioso por
    un numero silenciosamente MAL (misma razon que prompt_n). Queda declarado
    en el contrato y contado aparte por PresupuestoTokens.sin_prompt().

    La estimacion por frames NO se aplica a un stream que termino bien: ahi el
    contrato de "{} = no se pudo saber" sigue tal cual, porque un final sano
    sin usage ni timings es un server raro y el numero no tendria red que lo
    confirme. Al cortar no hay alternativa: o se estima, o se cuenta cero.

    Si no hay ninguna de las tres, el usage queda {} = NO SE PUDO SABER, que
    no es cero tokens (ver RespuestaChat.completion_tokens).
    """
    if acc["usage"]:
        acc["usage_via"] = "server"
        return acc["usage"]
    pred = (acc["timings"] or {}).get("predicted_n")
    if isinstance(pred, (int, float)):
        acc["usage_estimado"] = True
        acc["usage_via"] = "timings"
        return {"completion_tokens": int(pred)}
    if acc["cortado"]:
        frames = len(acc["texto"]) + len(acc["razon"])
        if frames:
            acc["usage_estimado"] = True
            acc["usage_via"] = "frames"
            return {"completion_tokens": frames}
    return {}


def _crudo_desde_stream(acc: dict) -> dict:
    """Rearma la forma NO-stream para que el parseo de abajo sea uno solo.

    AL CORTAR los tool calls se arman DIRECTO bajo otra clave y el
    finish_reason ya sale 'cancelado'. No es cosmetica: antes el vaciado de
    .tool_calls vivia en un `if` aguas abajo que dependia de que alguien
    hubiera marcado acc["cortado"], y el camino del ultimo renglon sin \\n no
    lo marcaba — salian tool calls EJECUTABLES despues del Esc del usuario
    (hallazgo #2). Aca la respuesta cortada NUNCA tiene la clave 'tool_calls',
    asi que ningun camino aguas abajo puede olvidarse de vaciarla.
    """
    msg: dict = {"content": "".join(acc["texto"])}
    if acc["razon"]:
        msg["reasoning_content"] = "".join(acc["razon"])
    if acc["tcs"]:
        clave = "tool_calls_parciales" if acc["cortado"] else "tool_calls"
        msg[clave] = [acc["tcs"][i] for i in sorted(acc["tcs"])]
    return {"choices": [{"message": msg,
                         "finish_reason": ("cancelado" if acc["cortado"]
                                           else acc["finish"])}],
            "usage": _usage_del_stream(acc)}


def completar(mensajes: list, tools: list = None, url: str = "",
              temperature: float = 1.0, top_p: float = 1.0,
              max_tokens: int = 4096, reasoning_effort: str = "",
              razonador: bool = True, timeout: float = None,
              via: str = "agente_chat",
              response_format: dict = None,
              kwargs_plantilla: dict = None,
              on_token=None, on_reasoning=None, cancelado=None,
              on_tool_frag=None) -> RespuestaChat:
    """UN turno de chat completions contra el server del agente.

    Nunca lanza: cualquier fallo vuelve como RespuestaChat(error=...) para
    que el bucle degrade con causa visible en vez de morir.

    response_format: salida estructurada — el server la fuerza por gramatica
    desde b9391 (probado en vivo en :8080); None = body identico al de antes.

    EL TIMEOUT ES DE INACTIVIDAD **SOLO CON STREAM**. `timeout` (o lo que
    devuelva `timeout_para()`) es el timeout del SOCKET y se rearma en cada
    lectura, asi que con la rama SSE lo dispara un SILENCIO mas largo que el
    presupuesto (un prefill descomunal, un backend colgado) y NO una
    respuesta lenta que sigue saliendo: una generacion de 10 minutos con un
    presupuesto de 300 s no muere mientras el server hable.

    SIN stream ese mismo numero es un deadline de PARED sobre la generacion
    entera, y este parrafo decia lo contrario hasta el 2026-08-26 ("en los
    DOS caminos"). El motivo no es el timeout sino el camino: en no-stream
    hay UN solo recv largo —llama-server no escribe nada hasta terminar— asi
    que ese silencio unico cubre connect + prefill + pensamiento +
    generacion. Medido: server que tarda 6 s, presupuesto 3 s, mismo
    completar(); sin on_token da 'TimeoutError: timed out' a los 3,02 s y con
    on_token entrega la respuesta entera a los 9,03 s. Quien llame sin
    callbacks debe dimensionar `timeout` como pared de la generacion completa
    (o pasar on_token, que es lo que hace el bucle del agente).
    Con stream hay ADEMAS un tope de pared, porque en no bloqueante el timeout
    de urlopen deja de regir y un proxy que pinguea cada 50 ms tiene
    inactividad cero para siempre: `max(timeout, min(timeout*4, 3600 s))`. Un
    stream sano cabe holgado (prefill medido 1.878 tok/s -> 150k tokens en
    ~80 s; generacion 39-45 tok/s -> 4096 tokens en ~100 s: ~180 s contra los
    1.200 s que da el piso de 300). Si dispara la pared el mensaje lo dice con
    esa palabra, para no confundirlo con el silencio.

    STREAMING (opt-in, 2026-08-17). Tres kwargs opcionales; con CUALQUIERA de
    los tres se usa la rama SSE, sin ninguno el body y el camino son los
    historicos byte a byte (tests/test_chat_client_stream.py lo fija):

      on_token(str)      -> cada fragmento de `content` segun sale.
      on_reasoning(str)  -> cada fragmento de pensamiento del razonador.
      on_tool_frag(str)  -> cada fragmento de los ARGUMENTOS de un tool call
                            segun sale. Es el unico canal por el que se ve
                            avanzar un turno del agente que esta escribiendo
                            un fichero: ahi no hay `content` ni razonamiento,
                            solo argumentos, y sin este callback el turno se
                            veia mudo durante minutos (2026-08-31).
      cancelado() -> bool: True corta y cierra la conexion.

    EL CORTE ES FUERA DE BANDA. cancelado() se consulta cada ~50 ms aunque el
    backend este mudo, y otra vez antes de despachar cada frame: apretar Esc
    en otro hilo vuelve de completar() en ~0,35 s y NO se entrega ningun
    token que haya llegado despues (medido 2026-08-17 contra un server que
    manda un token y se calla 5 s). Un cancelado() que LANZA no cancela y no
    mata el turno: se avisa una vez y se sigue (ver _corte_pedido).

    Con stream el body lleva SIEMPRE stream:true Y
    stream_options.include_usage:true. Lo segundo no es opcional: sin eso
    llama-server no manda el chunk de usage (medido 2026-08-17 en :8080 con
    qwen2.5-coder-14b; con include_usage el usage del stream coincide exacto
    con el del no-stream). Igual es un PEDIDO, no una garantia: si el server
    lo ignora se usa `timings.predicted_n` del frame final, y si tampoco hay,
    `usage` queda {} = NO SE PUDO SABER (que no es 0 tokens: ver
    RespuestaChat.completion_tokens y .usage_estimado).

    Cortado vs terminado: si cancelado() corto, la respuesta trae
    `cortado=True` y `finish_reason='cancelado'`, con lo acumulado en
    .texto/.reasoning_content, los tool calls en .tool_calls_parciales (NUNCA
    en .tool_calls) y normalmente sin usage. `ok` sigue True: cortar no es
    fallar. Esas tres cosas se deciden en UN solo lugar (`_Corte` +
    `_crudo_desde_stream`): no hay camino que corte y se olvide de marcarlo.
    Si el socket muere a mitad, vuelve `error` con el tipo de excepcion Y lo
    acumulado hasta ahi. Y si el server contesta 200 sin un solo frame SSE
    vuelve `error`, distinguiendo dos causas: sin NINGUNA señal SSE (ni
    comentarios) el sospechoso es el transporte — un proxy, otro backend —, y
    con keepalives pero sin datos el transporte esta bien y el que no contesto
    es el backend de atras.

    HTTPS: soportado de verdad. Sobre TLS "bloquearia" llega como
    ssl.SSLWantReadError en vez de None y el SSLSocket guarda bytes ya
    descifrados que select() no ve; las dos cosas estan contempladas (ver
    _canal_no_bloqueante). Sin eso la rama SSE moria en el primer silencio del
    backend con COGNIA_LLM_URL=https://...
    """
    url = (url or url_del_backend()).rstrip("/")
    # Chequeo que CORRE (no leccion en prosa): con un razonador, max_tokens
    # tiene que cubrir el pensamiento. 9 bugs identicos en la memoria del
    # repo por presupuestos de 16-256 tokens que degollaban el canal analysis.
    if razonador and max_tokens < MIN_TOKENS_RAZONADOR:
        max_tokens = MIN_TOKENS_RAZONADOR

    cuerpo: dict = {
        "messages": mensajes,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if _KV_SUCIO["v"]:
        # Una sola vez: se consume al armar el body (misma semantica que
        # _consume_lora_dirty del backend). cache_prompt: false fuerza el
        # re-prefill completo; las siguientes vuelven al cache normal.
        cuerpo["cache_prompt"] = False
        _KV_SUCIO["v"] = False
    if tools:
        cuerpo["tools"] = tools
    if response_format:
        # Tal cual lo pase el llamador: la forma exacta (json_schema anidado)
        # es contrato entre quien arma el schema y llama-server, no de aca.
        cuerpo["response_format"] = response_format
    if reasoning_effort:
        # El esfuerzo REAL se fija aca, no recortando tokens (memoria:
        # presupuesto-tokens-razonamiento).
        cuerpo["chat_template_kwargs"] = {"reasoning_effort": reasoning_effort}
    if kwargs_plantilla:
        # Otras familias controlan el razonamiento por OTRA clave del mismo
        # canal: Nemotron 3.5 usa enable_thinking (su template lo lee y
        # arranca en True). Se MERGEA con reasoning_effort en vez de pisarlo
        # porque son ejes distintos y un modelo podria aceptar ambos; sin
        # kwargs_plantilla el body es byte-identico al historico.
        kw = dict(cuerpo.get("chat_template_kwargs") or {})
        kw.update(kwargs_plantilla)
        cuerpo["chat_template_kwargs"] = kw

    # OPT-IN: la rama SSE se enciende solo si el llamador pide algo que solo
    # el stream da (ver el texto salir, o poder cortar). Las claves se
    # agregan AL FINAL para que el body sin streaming quede byte-identico.
    stream = (on_token is not None or on_reasoning is not None
              or cancelado is not None or on_tool_frag is not None)
    if stream:
        cuerpo["stream"] = True
        cuerpo["stream_options"] = {"include_usage": True}

    # Acumulador vivo del stream: si el socket se corta a mitad, el except de
    # abajo lo lee para devolver lo que SI llego junto al error.
    acc = {"texto": [], "razon": [], "tcs": {}, "finish": "",
           "usage": {}, "cortado": False, "malformados": 0,
           # frames SSE VALIDOS vistos: 0 con un 200 en la mano significa que
           # el transporte no hablo SSE (hallazgo #1), no que el modelo se
           # haya quedado callado. muestra = primeros bytes del cuerpo, para
           # que el error diga QUE contesto en vez de solo que no era SSE.
           # comentarios = keepalives ': ping': no son datos pero SI prueban
           # que el transporte habla SSE, y cambian el sospechoso.
           "frames": 0, "comentarios": 0, "muestra": b"", "timings": {},
           "usage_estimado": False, "usage_via": ""}
    # Reloj MONOTONICO (convencion del repo, cognia/harness/limites.py): la
    # duracion y los deadlines no los puede mover un ajuste de hora del
    # sistema ni un salto de NTP.
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            url + "/v1/chat/completions",
            data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        # Sin timeout explicito, el que corresponde al MODELO servido: el
        # 300 fijo mataba tareas sanas de un 30B-A3B (medido en el e2e).
        # `espera` es INACTIVIDAD: es lo que significa el timeout de urlopen
        # (timeout de socket, por lectura), y la rama SSE le respeta ese
        # significado en vez de convertirlo en un deadline de pared.
        espera = timeout or timeout_para(_modelo_servido(url), max_tokens)
        with urllib.request.urlopen(req, timeout=espera) as r:
            if stream:
                _leer_stream(r, acc, on_token, on_reasoning, cancelado,
                             espera, _pared_del_stream(espera),
                             on_tool_frag=on_tool_frag)
                crudo = _crudo_desde_stream(acc)
            else:
                crudo = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            detalle = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detalle = ""
        # LO ACUMULADO TAMBIEN VUELVE (2026-08-31). Esta rama devolvia SOLO el
        # error, y el caso mas comun que cae aqui es el 500 de llama-server
        # cuando los argumentos del tool call se cortaron a media cadena — o
        # sea, justo un turno que YA habia generado. Perder ahi el
        # reasoning_content dejaba ciego al bucle: `_puede_apagar_pensamiento`
        # pregunta si el turno se fue en razonar, leia vacio y respondia que
        # no, y el paso se iba a la rampa 8192 -> 16384 -> 32768 en vez de
        # apagar el pensamiento (corrida Vaelmark: 20.000 chars pensando, tool
        # call cortado a los 697, tres vueltas y 448 s para nada).
        # Nota: el 500 llega DESPUES del stream, asi que `acc` ya tiene lo que
        # paso por el socket; con el camino no-stream viene vacio y no se
        # afirma nada.
        return RespuestaChat(error=f"HTTP {e.code} de {url}: {detalle}",
                             texto="".join(acc["texto"]).strip(),
                             reasoning_content="".join(acc["razon"]),
                             # LOS PARCIALES SALEN TAMBIEN POR AQUI (2026-09-01).
                             # El 500 mas comun de este server es "Failed to
                             # parse tool call arguments as JSON": el turno se
                             # corto a mitad de los argumentos, o sea a mitad
                             # del FICHERO que el modelo estaba escribiendo.
                             # Esos KB ya pasaron por el socket y estaban en
                             # `acc`, y este return los tiraba: el bucle tiene
                             # rescate de escrituras parciales (loop.
                             # _rescatar_escritura) y no podia verlos, asi que
                             # se pagaba otra generacion entera para volver a
                             # cortarse en la misma columna. Medido con el banco
                             # de tareas largas: tres de diez tareas mueren asi.
                             tool_calls_parciales=_parse_tool_calls(
                                 [acc["tcs"][i] for i in sorted(acc["tcs"])]),
                             usage=_usage_del_stream(acc),
                             usage_estimado=acc["usage_estimado"],
                             usage_via=acc["usage_via"],
                             frames_malformados=acc["malformados"],
                             duracion_s=time.monotonic() - t0)
    except Exception as e:
        # Corte de red a mitad del stream: la conexion ya se cerro al salir
        # del `with` y la excepcion NO se traga — vuelve con lo acumulado
        # para que el llamador vea que hubo texto parcial y por que paro.
        return RespuestaChat(error=f"{type(e).__name__}: {e}",
                             texto="".join(acc["texto"]).strip(),
                             reasoning_content="".join(acc["razon"]),
                             tool_calls_parciales=_parse_tool_calls(
                                 [acc["tcs"][i] for i in sorted(acc["tcs"])]),
                             usage=_usage_del_stream(acc),
                             usage_estimado=acc["usage_estimado"],
                             usage_via=acc["usage_via"],
                             frames_malformados=acc["malformados"],
                             duracion_s=time.monotonic() - t0)

    if stream and not acc["frames"] and not acc["cortado"]:
        # UN 200 SIN UN SOLO FRAME DE DATOS. Por el camino de arriba saldria
        # ok=True con texto='' — o sea "el modelo no dijo nada", la
        # degradacion silenciosa de siempre disfrazada de exito. Vuelve como
        # error para que loop.py:434 lo vea como lo que es. `malformados`
        # deja de ser un contador que nadie lee: entra en el mensaje.
        #
        # DOS CAUSAS DISTINTAS y hay que decir cual (hallazgo #4): si no llego
        # NINGUNA señal SSE el sospechoso es el transporte, pero si llegaron
        # comentarios de keepalive el transporte SI habla SSE y el que no
        # contesto es el backend de atras. Antes las dos salian con el mismo
        # "¿un proxy delante, u otro backend?" y la muestra del propio mensaje
        # (b': ping\n\n') lo desmentia.
        muestra = bytes(acc["muestra"])[:160]
        if acc["comentarios"]:
            causa = (f"el transporte habla SSE ({acc['comentarios']} "
                     f"comentarios de keepalive) pero no llego NI UN frame de "
                     f"datos ni [DONE]: el proxy/servidor de {url} esta vivo y "
                     f"quien no contesto es el backend de atras (¿murio en el "
                     f"prefill?)")
        else:
            causa = (f"el server contesto 200 sin SSE: 0 frames validos y "
                     f"ninguna señal SSE. Se pidio stream:true y el transporte "
                     f"no lo respeta (¿un proxy delante, u otro backend en "
                     f"{url}?)")
        return RespuestaChat(
            error=(f"{causa}. {acc['malformados']} renglones ilegibles. "
                   f"Primeros bytes: {muestra!r}"),
            frames_malformados=acc["malformados"],
            duracion_s=time.monotonic() - t0)

    try:
        eleccion = (crudo.get("choices") or [{}])[0]
        msg = eleccion.get("message") or {}
        resp = RespuestaChat(
            texto=(msg.get("content") or "").strip(),
            tool_calls=_parse_tool_calls(msg.get("tool_calls")),
            # NADA de tool calls al cortar. Pueden estar truncados a mitad de
            # los arguments (el stream los manda troceados) y, aunque
            # estuvieran completos, el usuario ya pidio parar: un llamador con
            # la forma de loop.py los ejecutaria igual. _crudo_desde_stream ya
            # los puso bajo esta clave — no hay un "vaciar despues" que se
            # pueda saltear un camino (hallazgo #2).
            tool_calls_parciales=_parse_tool_calls(
                msg.get("tool_calls_parciales")),
            finish_reason=eleccion.get("finish_reason") or "",
            usage=crudo.get("usage") or {},
            reasoning_content=(msg.get("reasoning_content") or ""),
            duracion_s=time.monotonic() - t0,
        )
    except Exception as e:
        return RespuestaChat(error=f"respuesta inesperada del server: {e}",
                             duracion_s=time.monotonic() - t0)

    resp.usage_estimado = acc["usage_estimado"]
    # El camino NO-stream nunca pasa por _usage_del_stream: si el server mando
    # usage, la via es el server igual. Sin este `or`, la unica respuesta con
    # usage REAL y via "" seria la mas comun de todas.
    resp.usage_via = acc["usage_via"] or ("server" if resp.usage else "")
    resp.frames_malformados = acc["malformados"]
    # UNA sola verdad sobre el corte: la bandera que anoto _Corte. El
    # finish_reason 'cancelado' (valor que el server nunca manda) ya viene de
    # _crudo_desde_stream.
    resp.cortado = bool(acc["cortado"])

    # Constancia de quien atendio (backend_activo): auditoria jsonl + linea
    # stderr (silenciable con COGNIA_BACKEND_LOG=0). Best-effort.
    try:
        from cognia import backend_activo
        backend_activo.registrar(via, url, rol="pensar",
                                 finish=resp.finish_reason,
                                 tokens=resp.usage.get("completion_tokens"))
    except Exception:
        pass
    return resp


def mensaje_assistant(resp: RespuestaChat) -> dict:
    """El turno assistant para devolver al server en el siguiente paso.

    Preserva el CoT entre tool calls (reasoning_content round-trip verificado)
    y re-serializa los arguments con el JSON original del server."""
    msg: dict = {"role": "assistant", "content": resp.texto or ""}
    if resp.reasoning_content:
        msg["reasoning_content"] = resp.reasoning_content
    if resp.tool_calls:
        msg["tool_calls"] = [
            {"type": "function", "id": tc.id,
             "function": {"name": tc.nombre,
                          "arguments": tc.argumentos_crudos
                          or json.dumps(tc.argumentos, ensure_ascii=False)}}
            for tc in resp.tool_calls]
    return msg


def mensaje_tool(tool_call_id: str, contenido: str) -> dict:
    """El turno tool con el resultado de una herramienta."""
    return {"role": "tool", "tool_call_id": tool_call_id,
            "content": contenido or "(sin output)"}
