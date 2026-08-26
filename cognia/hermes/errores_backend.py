# -*- coding: utf-8 -*-
"""
cognia/hermes/errores_backend.py
================================
Clasificador TIPADO de errores de backend: UN solo sitio que traduce el texto
crudo de llama-server / Ollama / cualquier API OpenAI-compatible a un
diagnostico con FLAGS DE ACCION (reintentar, comprimir, cambiar de backend,
cuanto esperar) mas una instruccion accionable para el usuario.

POR QUE EXISTE
--------------
Desde que Cognia dejo de ser mono-familia (Qwen) los errores del backend son
heterogeneos y el codigo los maneja con if/else sobre strings dispersos. Dos
ejemplos VIVOS en el repo:

  * app/routes/chat.py:81 decide "no hay backend" con
    `any(x in err.lower() for x in ["ollama", "connection refused", "urlerror",
    "urlopen", "errno 111"])` -- cinco strings a mano en una ruta HTTP.
  * cognia/cli.py:12088 hace `except Exception as e:
    _print_fn("Agente: error LLM: ...")` y ROMPE el loop del agente sin
    distinguir un timeout (reintentable) de un ctx desbordado (hay que
    comprimir) o de un modelo ausente (hay que cambiar de backend).

El resultado es el fallo silencioso que ya cobro caro aqui: el sintoma aparece
tres capas mas abajo ("no hay backend") cuando la causa era otra. La averia
medida el 2026-08-17 (node/llama_backend.py:1345 y siguientes) es el caso
tipico: HTTP 400 `exceed_context_size` a mitad de una generacion larga que
llegaba al llamador convertido en "no hay backend".

DESTILADO DE HERMES (leido, no imaginado)
-----------------------------------------
  * hermes-agent/agent/error_classifier.py -- 25 razones tipadas
    (`FailoverReason`) y `ClassifiedError` con los flags de recuperacion
    (retryable / should_compress / should_rotate_credential / should_fallback)
    resueltos por un pipeline ORDENADO POR PRIORIDAD. La idea de fondo: el lazo
    de reintento NO vuelve a clasificar, solo LEE flags
    (conversation_loop.py:3737-3749 hace exactamente eso y loguea los cuatro).
  * hermes-agent/agent/model_metadata.py:1550 `is_output_cap_error()` -- LA
    separacion que este modulo copia: un error de `max_tokens` (OUTPUT) NO es un
    desborde de contexto (INPUT). Comprimir no arregla un max_tokens corto:
    reenvia el MISMO max_tokens, recibe el MISMO 400, y la sesion muere en bucle
    hasta "cannot compress further" (Hermes #55546, DashScope
    "Range of max_tokens should be [1, 65536]"). Por eso `tope_salida` y
    `contexto_excedido` son razones DISTINTAS y solo la segunda comprime.
  * hermes-agent/agent/error_classifier.py:308 y :475 -- por el mismo motivo la
    respuesta VACIA se intercepta ANTES que la lista de contexto: el aviso de
    "empty response" del proveedor menciona `max_tokens` como posible causa y
    mandaba sesiones sanas a la espiral de compresion.
  * hermes-agent/agent/conversation_loop.py:4220 -- el error de output-cap queda
    EXENTO de la guarda de compresion, otra vez porque comprimir no lo arregla.

Este modulo NO importa cognia/cli.py ni abre sockets: es texto -> dict. El
cableado lo hace el integrador (ver el informe de entrega).

API PUBLICA
-----------
    RAZONES                              tupla con las 11 razones posibles
    clasificar(exc_o_texto, contexto=None) -> Diagnostico (dict)
    accion_sugerida(diag)                -> str, UNA instruccion con el comando
                                            literal que arregla la cosa

Diagnostico = {
    "razon":              str,    # una de RAZONES
    "reintentable":       bool,   # ¿tiene sentido repetir la MISMA llamada?
    "comprimir_contexto": bool,   # ¿el arreglo es achicar el INPUT?
    "cambiar_backend":    bool,   # ¿el arreglo es otro modelo/puerto/proveedor?
    "esperar_s":          float,  # cuanto dormir antes de reintentar (0 = ya)
    "mensaje_humano":     str,    # una linea en espanol para logs y pantalla
}

`contexto` (todo opcional):
    "respuesta"      str   texto que devolvio el modelo (para respuesta_vacia)
    "finish_reason"  str   'stop' | 'length' | ...  (cognia/llm_local.py lo deja
                           en `ultimo_detalle`)
    "status"         int   codigo HTTP (alias: 'codigo_http', 'code')
    "cuerpo"         str   cuerpo de la respuesta de error, si se leyo
    "salud"          str   'ok' | 'cargando' | 'caido'  (lo que dice /health;
                           node/llama_backend.py:1053 ya lo consulta). Un
                           timeout con /health!='ok' es servidor_caido, no
                           "ocupado" -- ver el comentario de _clasificar.
    "backend_vivo"   bool  alias booleano de lo anterior
    "intento"        int   nro de reintento ya consumido -> backoff exponencial
    "backend"        str   'llama' | 'ollama' | ...   (solo informativo)
    "modelo"         str   nombre del modelo           (solo informativo)

REGLA DEL CAMINO CALIENTE: nada de aqui lanza. Cualquier sorpresa cae en
`desconocido` reintentable. Un clasificador que revienta seria peor que el
if/else que reemplaza.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

__all__ = ["RAZONES", "clasificar", "accion_sugerida"]


# Las 11 razones. Orden de la tupla = orden de prioridad conceptual, no de
# evaluacion (la evaluacion real esta en _clasificar_texto, comentada abajo).
RAZONES = (
    "contexto_excedido",
    "tope_salida",
    "servidor_caido",
    "timeout",
    "rate_limit",
    "json_invalido",
    "respuesta_vacia",
    "modelo_no_encontrado",
    "memoria_insuficiente",
    "cancelado",
    "desconocido",
)


# ── Patrones ────────────────────────────────────────────────────────────
# Todos en minusculas; el texto se normaliza antes de comparar. Cada bloque
# dice DE DONDE salio la cadena: repo de Cognia, Hermes, o la respuesta real
# del servidor. No se inventan variantes "por si acaso": un patron de mas
# roba errores a la razon de al lado (asi murio "too many tokens" en Hermes,
# que se comia los throttles de Bedrock).

_CANCELADO = (
    "keyboardinterrupt",
    "cancellederror",
    "operation cancelled",
    "operation canceled",
    "request cancelled",
    "request canceled",
    "cancelado por el usuario",
    "interrumpido por el usuario",
    "aborted by user",
)

# Hermes: _EMPTY_PROVIDER_RESPONSE_PATTERNS (error_classifier.py:475). Se miran
# ANTES que los de contexto porque el aviso de "empty response" menciona
# max_tokens y mandaba sesiones sanas a comprimir.
_RESPUESTA_VACIA = (
    "returned an empty response",
    "empty response despite retries",
    "provider returned an empty response",
    "model returning empty responses",
    "empty response stream",
    # Cognia: cli.py:12112 audita este degradado con este mismo texto.
    "respuesta vacia",
    # Cognia: cli.py:12085, el paso que se fue entero en razonamiento.
    "el modelo agoto el paso razonando",
)

# OOM. "CUDA out of memory" ya se maneja a mano en tests/test_tresd_tools.py:219
# y en cognia_x/construccion/xspeed_bench_kernel.py:649; Ollama devuelve el suyo
# con HTTP 500 ("model requires more system memory (X GiB) than is available").
_MEMORIA = (
    "out of memory",
    "outofmemoryerror",
    "requires more system memory",
    "cannot allocate memory",
    "failed to allocate",
    "insufficient memory",
    "not enough memory",
    "the paging file is too small",
)

# Contexto de ENTRADA desbordado. Hermes: _CONTEXT_OVERFLOW_PATTERNS
# (error_classifier.py:272) menos las entradas que alli mismo estan marcadas
# como ambiguas ("max_tokens" pelado vive en la deteccion de tope_salida, no
# aqui). Los tres primeros son los de llama-server / la averia medida del repo.
_CONTEXTO = (
    # llama-server: HTTP 400 type=exceed_context_size. Es LA averia medida en
    # node/llama_backend.py:113, :699 y :1354 (repro A/B del 2026-08-17).
    "exceed_context_size",
    "the request exceeds the available context size",
    "context shift is disabled",
    "n_ctx_slot",
    "slot context",
    # OpenAI / OpenAI-compatibles
    "context_length_exceeded",
    "context length",
    "maximum context",
    "context window",
    "reduce the length",
    "please reduce the length of the messages",
    "prompt is too long",
    "prompt too long",
    "input is too long",
    "prompt length",
    # vLLM / servidores locales
    "max_model_len",
    "maximum model length",
    "maximum allowed input length",
    # Ollama
    "context length exceeded",
    "truncating input",
    # 413
    "request entity too large",
    "payload too large",
    "request_too_large",
)

# Tope de SALIDA. Portado de model_metadata.py:1550 `is_output_cap_error`.
_TOPE_PARAM = ("max_tokens", "max_output_tokens", "max_completion_tokens",
               "num_predict")
_TOPE_SENAL = (
    "range of max_tokens should be",   # DashScope / Alibaba (Qwen)
    "available_tokens",                # Anthropic
    "available tokens",
    "should be",                       # "max_tokens should be <= N"
    "less than or equal",
    "must be",
    "too large",
)
# Si el error TAMBIEN describe un input gigante, gana contexto_excedido: ese si
# se puede comprimir. (Hermes: la guarda `input_overflow_signal`.)
_TOPE_ES_INPUT = (
    "prompt is too long",
    "prompt too long",
    "input is too long",
    "input token",
    "prompt length",
    "prompt contains",
    "reduce the length",
)

_MODELO = (
    "model not found",
    "model_not_found",
    "try pulling it first",          # Ollama 404
    "no such model",
    "unknown model",
    "unsupported model",
    "is not a valid model",
    "invalid model",
    "failed to load model",
    "unable to load model",
    "modelo no encontrado",
    "no se encontro el modelo",
)

_RATE_LIMIT = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "requests per minute",
    "tokens per minute",
    "resource_exhausted",
    "throttling",
    "throttled",
    "quota exceeded",
    "exceeded your current quota",
)

# Transporte MUERTO: no hay nadie escuchando. Los cinco primeros son
# literalmente los que app/routes/chat.py:81 lista a mano hoy.
_CAIDO_DURO = (
    "connection refused",
    "errno 111",
    "winerror 10061",
    "connectionrefusederror",
    "actively refused",
    "expresamente dicha conexi",     # Windows en espanol (sin la tilde final)
    "failed to establish a new connection",
    "no route to host",
    # Cognia: el aviso que el orquestador devuelve como TEXTO (cli.py:12095) y
    # el que deja llm_local cuando no responde ni :8080 ni :11434.
    "no inference backend available",
    "ni llama-server",
    "no hay backend",
    # Server vivo pero sin servicio
    "service unavailable",
    "http 503",
    "error 503",
    "loading model",
)

# Transporte que se corto a media conversacion: el server puede seguir vivo.
_CAIDO_BLANDO = (
    "connection reset",
    "connection aborted",
    "remote end closed connection",
    "server disconnected",
    "broken pipe",
    "incompleteread",
    "max retries exceeded",
    "urlopen error",
    "remoteprotocolerror",
)

# Hermes: _TIMEOUT_MESSAGE_PATTERNS (error_classifier.py:487). Se miran antes
# que _CAIDO_BLANDO porque el timeout real de urllib llega como
# "<urlopen error timed out>" -- los dos patrones matchean y el bueno es el
# timeout (evidencia: los WARNING de arbitro_visual en los .log del repo).
_TIMEOUT = (
    "timed out",
    "timeout",
    "deadline exceeded",
    "read timed out",
)

_JSON = (
    "expecting value",
    "expecting ',' delimiter",
    "expecting property name",
    "unterminated string",
    "extra data",
    "invalid json",
    "json decode error",
    "jsondecodeerror",
    "failed to parse json",
    "invalid \\escape",
)


# ── Flags por razon ─────────────────────────────────────────────────────
# (reintentable, comprimir_contexto, cambiar_backend, esperar_s_base)
#
# Los tres flags responden preguntas DISTINTAS y por eso no se deducen unos de
# otros: 'reintentable' = repetir la MISMA llamada sirve; 'comprimir_contexto' =
# hay que achicar el INPUT antes de repetir; 'cambiar_backend' = ninguna
# repeticion contra ESTE backend va a funcionar.
_FLAGS = {
    #                      reint. comp.  cambiar espera
    "contexto_excedido":  (True,  True,  False,  0.0),
    # tope_salida: reintentable SI, pero con otro max_tokens. Comprimir NO
    # (Hermes #55546: reenvia el mismo tope y muere en bucle).
    "tope_salida":        (True,  False, False,  0.0),
    "servidor_caido":     (True,  False, True,   2.0),
    # timeout con /health ok = slot ocupado (--parallel 1), no server muerto:
    # node/llama_backend.py:1053 ya lo documenta. No se cambia de backend.
    "timeout":            (True,  False, False,  1.0),
    "rate_limit":         (True,  False, True,   5.0),
    "json_invalido":      (True,  False, False,  0.0),
    "respuesta_vacia":    (True,  False, False,  0.0),
    "modelo_no_encontrado": (False, False, True, 0.0),
    # OOM: comprimir el prompt no salva un modelo que no entra en RAM/VRAM, y
    # reintentar igual vuelve a matar la maquina. La salida es un modelo mas
    # chico o menos ctx.
    "memoria_insuficiente": (False, False, True, 0.0),
    "cancelado":          (False, False, False,  0.0),
    "desconocido":        (True,  False, False,  1.0),
}

_MENSAJES = {
    "contexto_excedido": "el prompt no entra en la ventana del backend",
    "tope_salida": "el tope de salida (max_tokens) no lo acepta el backend",
    "servidor_caido": "no hay backend escuchando (o esta cargando el modelo)",
    "timeout": "el backend no contesto a tiempo (ocupado o generacion larga)",
    "rate_limit": "el proveedor esta limitando el ritmo de peticiones",
    "json_invalido": "la respuesta del backend no es JSON valido",
    "respuesta_vacia": "el backend contesto sin contenido",
    "modelo_no_encontrado": "el modelo pedido no esta en el backend",
    "memoria_insuficiente": "no hay memoria para este modelo/ventana",
    "cancelado": "la llamada se cancelo",
    "desconocido": "error de backend no reconocido",
}

_TOPE_BACKOFF_S = 30.0   # techo del backoff exponencial


# ── Utilidades internas ─────────────────────────────────────────────────

def _texto_de(exc_o_texto: Any) -> str:
    """Todo lo legible de la excepcion (o el texto) en una sola cadena.

    Hermes junta str(error) + body.message + metadata.raw porque el mensaje
    util a veces solo esta en el cuerpo (error_classifier.py:645). Aca la
    version chica: str(exc), el nombre del tipo, y `.reason` de urllib.
    """
    if exc_o_texto is None:
        return ""
    if isinstance(exc_o_texto, str):
        return exc_o_texto
    partes = []
    try:
        partes.append(type(exc_o_texto).__name__)
    except Exception:
        pass
    try:
        partes.append(str(exc_o_texto))
    except Exception:
        pass
    # urllib.error.URLError guarda el OSError real en .reason; HTTPError trae
    # el codigo aparte (lo lee _status_de).
    razon = getattr(exc_o_texto, "reason", None)
    if razon is not None and not isinstance(razon, str):
        try:
            partes.append(f"{type(razon).__name__}: {razon}")
        except Exception:
            pass
    elif isinstance(razon, str):
        partes.append(razon)
    return " ".join(p for p in partes if p)


def _status_de(exc_o_texto: Any, contexto: Dict[str, Any]) -> Optional[int]:
    for clave in ("status", "codigo_http", "code", "status_code"):
        valor = contexto.get(clave)
        if isinstance(valor, int):
            return valor
    for attr in ("status_code", "code", "status"):
        valor = getattr(exc_o_texto, attr, None)
        if isinstance(valor, int):
            return valor
    return None


def _hay(texto: str, patrones) -> bool:
    return any(p in texto for p in patrones)


def _es_tope_salida(texto: str) -> bool:
    """Puerto de model_metadata.py:1550 `is_output_cap_error`.

    Tres condiciones: menciona el PARAMETRO de salida, la frase habla de un
    tope/rango, y NO describe ademas un input gigante (si lo hace es un
    desborde de contexto de verdad que de paso nombra max_tokens, y ese si se
    arregla comprimiendo).
    """
    if not _hay(texto, _TOPE_PARAM):
        return False
    if not _hay(texto, _TOPE_SENAL):
        return False
    return not _hay(texto, _TOPE_ES_INPUT)


_RE_ESPERA = (
    re.compile(r"try again in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s\b|sec|second)"),
    re.compile(r"retry[- ]after[:\s]+([0-9]+(?:\.[0-9]+)?)"),
    re.compile(r"reintenta(?:r)? en\s+([0-9]+(?:\.[0-9]+)?)\s*s"),
)


def _espera_declarada(texto: str) -> Optional[float]:
    """Segundos que el propio proveedor pide esperar, si los dice."""
    for rx in _RE_ESPERA:
        m = rx.search(texto)
        if not m:
            continue
        try:
            valor = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if m.lastindex and m.lastindex >= 2 and m.group(2) == "ms":
            valor = valor / 1000.0
        if 0 < valor <= 3600:
            return valor
    return None


def _clasificar_texto(texto: str, status: Optional[int]) -> str:
    """Pipeline ORDENADO. El orden es la mitad del diseno; ver comentarios.

    Devuelve solo la razon. Hermes hace lo mismo en un embudo de 8 etapas
    (error_classifier.py:606-620); aca son menos etapas porque son 11 razones,
    pero las precedencias delicadas son LAS MISMAS.
    """
    # 1. Cancelacion: nunca es un fallo del backend.
    if _hay(texto, _CANCELADO):
        return "cancelado"
    # 2. Respuesta vacia ANTES que contexto: el aviso de "empty response" cita
    #    max_tokens y si no se intercepta aqui cae en la lista de contexto y
    #    dispara compresion de una sesion sana (Hermes error_classifier.py:475).
    if _hay(texto, _RESPUESTA_VACIA):
        return "respuesta_vacia"
    # 3. OOM antes que transporte: un llama-server que muere por memoria deja
    #    ademas un connection reset, y el reset no dice como arreglarlo.
    if _hay(texto, _MEMORIA):
        return "memoria_insuficiente"
    # 4. Tope de salida ANTES que contexto (la separacion de Hermes #55546).
    if _es_tope_salida(texto):
        return "tope_salida"
    # 5. Contexto de entrada desbordado.
    if _hay(texto, _CONTEXTO):
        return "contexto_excedido"
    # 6. Modelo ausente antes que "servidor caido": Ollama contesta 404 con el
    #    server perfectamente vivo, y arrancar la flota otra vez no lo arregla.
    if _hay(texto, _MODELO):
        return "modelo_no_encontrado"
    if _hay(texto, _RATE_LIMIT):
        return "rate_limit"
    # 7. Transporte muerto (nadie escucha) antes que timeout.
    if _hay(texto, _CAIDO_DURO):
        return "servidor_caido"
    # 8. Timeout antes que el transporte blando: urllib entrega el timeout como
    #    "<urlopen error timed out>" y los dos patrones matchean.
    if _hay(texto, _TIMEOUT):
        return "timeout"
    if _hay(texto, _CAIDO_BLANDO):
        return "servidor_caido"
    if _hay(texto, _JSON):
        return "json_invalido"
    # 9. Recien ahora el codigo HTTP pelado: es la senal mas pobre (un 400 sirve
    #    para ctx desbordado, para max_tokens y para un JSON mal armado), asi
    #    que solo decide cuando el texto no dijo nada.
    if status is not None:
        if status == 429:
            return "rate_limit"
        if status == 404:
            return "modelo_no_encontrado"
        if status == 413:
            return "contexto_excedido"
        if status in (502, 503, 504):
            return "servidor_caido"
        if 500 <= status < 600:
            return "servidor_caido"
    return "desconocido"


def _tipo_directo(exc_o_texto: Any) -> Optional[str]:
    """Razones que el TIPO de la excepcion ya resuelve sin mirar el texto."""
    if isinstance(exc_o_texto, str) or exc_o_texto is None:
        return None
    if isinstance(exc_o_texto, KeyboardInterrupt):
        return "cancelado"
    if isinstance(exc_o_texto, MemoryError):
        return "memoria_insuficiente"
    if isinstance(exc_o_texto, json.JSONDecodeError):
        return "json_invalido"
    if isinstance(exc_o_texto, ConnectionRefusedError):
        return "servidor_caido"
    # socket.timeout es alias de TimeoutError desde 3.10; ConnectionError es la
    # familia entera de resets/aborts. TimeoutError va PRIMERO porque
    # ConnectionError no lo cubre y el orden inverso no cambiaria nada.
    if isinstance(exc_o_texto, TimeoutError):
        return "timeout"
    if isinstance(exc_o_texto, ConnectionError):
        return "servidor_caido"
    return None


# ── API publica ─────────────────────────────────────────────────────────

def clasificar(exc_o_texto: Any, contexto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Traduce una excepcion (o un texto de error) a un Diagnostico.

    Acepta lo que sea: excepcion, string, None. NUNCA lanza -- el camino
    caliente no se rompe por el clasificador (si algo sale mal el resultado es
    'desconocido' reintentable, que es el comportamiento de hoy).

    Casos que decide el `contexto` y no el texto:

      * respuesta VACIA. `clasificar("", {"finish_reason": "length"})` es
        'respuesta_vacia' y **comprimir_contexto queda en False**: el modelo se
        gasto el presupuesto de salida razonando (medido en cognia/llm_local.py:
        6 de 6 sondas con gpt-oss murieron en finish=length con 22-53k chars de
        razonamiento y contenido 0). Comprimir el INPUT no devuelve ni un token
        de salida; lo que hay que subir es max_tokens o bajar el
        reasoning_effort. Es la misma separacion input/output que Hermes
        documenta en model_metadata.py:1550.
      * respuesta NO vacia con finish_reason='length' -> 'tope_salida': la
        generacion se corto por el tope, el input estaba bien.
    """
    try:
        ctx = dict(contexto or {})
    except Exception:
        ctx = {}
    try:
        return _clasificar(exc_o_texto, ctx)
    except Exception as exc:   # pragma: no cover - red de seguridad
        return _armar("desconocido", f"fallo el clasificador: {exc}", ctx)


def _clasificar(exc_o_texto: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    finish = str(ctx.get("finish_reason") or "").strip().lower()
    tiene_respuesta = "respuesta" in ctx or "texto" in ctx
    respuesta = ctx.get("respuesta", ctx.get("texto", ""))
    respuesta = "" if respuesta is None else str(respuesta)

    texto_bruto = _texto_de(exc_o_texto)
    cuerpo = ctx.get("cuerpo", ctx.get("body", ""))
    if cuerpo:
        texto_bruto = f"{texto_bruto} {cuerpo}"
    texto = texto_bruto.strip().lower()

    # ── Camino "el backend contesto, pero mal" ───────────────────────
    # Se resuelve por finish_reason y no por patrones: aca no hay error que
    # parsear, hay una respuesta pobre. Va primero porque una respuesta vacia
    # con un contexto vacio no tiene NINGUN texto que clasificar.
    if tiene_respuesta or not texto:
        vacia = (not respuesta.strip()) if tiene_respuesta else (not texto)
        if vacia:
            if finish == "length":
                # NO se marca comprimir_contexto: ver el docstring de clasificar.
                return _armar(
                    "respuesta_vacia",
                    "el modelo agoto el presupuesto de salida (finish_reason="
                    "length) sin emitir contenido: hay que subir max_tokens o "
                    "bajar el esfuerzo de razonamiento, NO comprimir el prompt",
                    ctx)
            return _armar("respuesta_vacia", "", ctx)
        if finish == "length":
            return _armar(
                "tope_salida",
                "la generacion se corto en el tope de salida (finish_reason="
                "length) con el input dentro de la ventana",
                ctx)

    if not texto:
        return _armar("desconocido", "", ctx)

    razon = _tipo_directo(exc_o_texto)
    if razon is None:
        razon = _clasificar_texto(texto, _status_de(exc_o_texto, ctx))
    elif razon in ("servidor_caido", "timeout"):
        # El tipo dice "transporte", pero el texto puede ser mas especifico
        # (p.ej. un ConnectionError cuyo cuerpo trae 'exceed_context_size'
        # porque el server murio al desbordar). Se le da la palabra al texto y
        # el tipo queda de respaldo.
        preciso = _clasificar_texto(texto, _status_de(exc_o_texto, ctx))
        if preciso != "desconocido":
            razon = preciso

    # Un timeout NO dice por si solo si el server esta ocupado o si no hay
    # nadie. MEDIDO en esta maquina (Windows 11, 2026-08-18): un puerto de
    # loopback SIN nadie escuchando da `TimeoutError: timed out` —el firewall
    # descarta el SYN en vez de contestar RST—, no "connection refused". O sea
    # que aqui la ausencia de backend llega DISFRAZADA de timeout, y la lista
    # de app/routes/chat.py:81 (que no tiene ningun patron de timeout) la deja
    # pasar entera. Quien llama SI sabe la diferencia: node/llama_backend.py:1053
    # ya consulta /health y documenta "timeout con /health ok = OCUPADO
    # (--parallel 1), no falta de backend". Ese dato entra por `contexto`.
    if razon == "timeout":
        salud = str(ctx.get("salud") or "").strip().lower()
        vivo = ctx.get("backend_vivo")
        if salud in ("caido", "muerto", "sin_respuesta", "cargando") or vivo is False:
            detalle = ("el backend no contesto y /health dice '%s': no esta "
                       "sirviendo" % (salud or "sin respuesta"))
            return _armar("servidor_caido", detalle, ctx, texto_bruto)

    # Un 4xx de peticion mal armada SIN cuerpo que lo explique (llm_local.py:167
    # imprime "[llm] HTTP 400 en <url>" y tira el cuerpo) sigue siendo
    # 'desconocido' —no hay nada que nombrar— pero NO es reintentable: repetir
    # la misma peticion recibe el mismo 400. Hermes documenta ese bucle como
    # "request flood" en _REQUEST_VALIDATION_PATTERNS.
    if razon == "desconocido":
        status = _status_de(exc_o_texto, ctx)
        if status in (400, 401, 403, 422):
            return _armar(razon, "", ctx, texto_bruto, reintentable=False)
    return _armar(razon, "", ctx, texto_bruto)


def _armar(razon: str, detalle: str, ctx: Dict[str, Any],
           texto_bruto: str = "",
           reintentable: Optional[bool] = None) -> Dict[str, Any]:
    if razon not in _FLAGS:
        razon = "desconocido"
    por_defecto, comprimir, cambiar, base = _FLAGS[razon]
    if reintentable is None:
        reintentable = por_defecto

    esperar = base
    if razon == "rate_limit":
        pedido = _espera_declarada((texto_bruto or detalle).lower())
        if pedido is not None:
            esperar = pedido
    # Backoff exponencial acotado: el que llama pasa cuantos reintentos ya
    # gasto y no tiene que llevar la cuenta del sleep por su cuenta.
    intento = ctx.get("intento")
    if isinstance(intento, int) and intento > 0 and esperar > 0:
        esperar = min(esperar * (2 ** intento), _TOPE_BACKOFF_S)

    mensaje = detalle or _MENSAJES[razon]
    modelo = str(ctx.get("modelo") or "").strip()
    if modelo and razon in ("modelo_no_encontrado", "memoria_insuficiente"):
        mensaje = f"{mensaje} ({modelo})"
    if texto_bruto:
        recorte = " ".join(texto_bruto.split())[:160]
        if recorte:
            mensaje = f"{mensaje}: {recorte}"

    return {
        "razon": razon,
        "reintentable": bool(reintentable),
        "comprimir_contexto": bool(comprimir),
        "cambiar_backend": bool(cambiar),
        "esperar_s": float(esperar),
        "mensaje_humano": mensaje,
    }


def _orden_arrancar() -> str:
    """La orden literal que levanta el cerebro de hoy.

    Se LEE de cognia.backend_activo (que a su vez la lee de flota.COMBO_DEFAULT)
    para no volver a divergir cuando el dueno cambie de cerebro: ese modulo ya
    documenta que sugerir 'flota arrancar pensar' manda a levantar gpt-oss-20b
    cuando el cerebro es Qwythos-9B. Import perezoso y con red: este modulo se
    usa en el camino caliente y no puede depender de que el paquete entero
    importe.
    """
    try:
        from cognia.backend_activo import orden_arrancar
        orden = str(orden_arrancar() or "").strip()
        if orden:
            return orden
    except Exception:
        pass
    return "python -m cognia flota arrancar pensar-qwen38"


def accion_sugerida(diag: Dict[str, Any]) -> str:
    """UNA instruccion accionable en espanol, con el comando literal.

    Regla del repo: un aviso sin el comando que lo arregla obliga al usuario a
    ir a buscarlo (arranque.py:421-424 y backend_activo.py:222 ya la aplican; la
    lista de fallbacks de cli.py:12100 tambien). Aca se cumple igual: una sola
    linea, imperativa, y si hay comando va literal y completo.

    Devuelve "" nunca: una razon desconocida cae en el diagnostico generico.
    """
    try:
        razon = str((diag or {}).get("razon") or "desconocido")
    except Exception:
        razon = "desconocido"
    if razon not in _FLAGS:
        razon = "desconocido"

    if razon == "servidor_caido":
        return ("No hay backend escuchando: arrancalo con  " + _orden_arrancar())
    if razon == "contexto_excedido":
        return ("El prompt no entra: recorta el contexto y reintenta; si se "
                "repite, levanta el server con mas ventana  "
                "(set LLAMA_CTX_SIZE=32768 && " + _orden_arrancar() + ")")
    if razon == "tope_salida":
        return ("Comprimir NO arregla esto: baja el tope de salida con  "
                "set COGNIA_MAX_TOKENS=2048  y reintenta")
    if razon == "timeout":
        # COGNIA_CHAT_TIMEOUT y no LLAMA_SERVER_TIMEOUT (corregido
        # 2026-08-26): la segunda solo la lee node/llama_backend.py:106, y
        # alli NO es el timeout de una peticion sino cuanto se espera a que
        # el server TERMINE DE ARRANCAR. Quien llega a este mensaje viene del
        # camino del agente (chat_client), que lee COGNIA_CHAT_TIMEOUT y
        # ninguna otra. Un consejo que nombra una palanca muerta es PEOR que
        # no dar consejo: el usuario lo prueba, no cambia nada, y descarta la
        # hipotesis correcta.
        return ("El server esta ocupado o la generacion no entra en el "
                "presupuesto (--parallel 1 sirve un pedido a la vez): espera "
                "y reintenta, o dale mas margen con  "
                "set COGNIA_CHAT_TIMEOUT=900")
    if razon == "rate_limit":
        espera = 0.0
        try:
            espera = float((diag or {}).get("esperar_s") or 0.0)
        except (TypeError, ValueError):
            espera = 0.0
        return (f"El proveedor limita el ritmo: espera {espera:.0f}s y "
                f"reintenta, o pasate al backend local con  "
                + _orden_arrancar())
    if razon == "modelo_no_encontrado":
        return ("Ese modelo no esta en el backend: instalalo con  "
                "python -m cognia install-model  (o con Ollama: "
                "ollama pull qwen2.5-coder && set "
                "COGNIA_OLLAMA_MODEL=qwen2.5-coder)")
    if razon == "memoria_insuficiente":
        return ("No hay memoria para este modelo: usa uno mas chico o menos "
                "ventana  (set LLAMA_CTX_SIZE=8192 && " + _orden_arrancar() + ")")
    if razon == "json_invalido":
        return ("El backend devolvio algo que no es JSON: reintenta; si sigue, "
                "revisa que responde el server con  python -m cognia doctor")
    if razon == "respuesta_vacia":
        return ("El modelo no emitio contenido: reintenta con mas presupuesto "
                "de salida  (set COGNIA_MAX_TOKENS=4096)")
    if razon == "cancelado":
        return "Cancelado a pedido: no hay nada que arreglar."
    return ("Error de backend no reconocido: diagnostica con  "
            "python -m cognia doctor  (y pega el mensaje completo)")
