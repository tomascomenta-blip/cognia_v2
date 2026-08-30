"""
cognia/enrutador.py
===================
Enrutado por INFERENCIA sobre todo el catalogo (goal 2026-07-21).

El dueño: "que Cognia infiera sobre TODAS sus herramientas y comandos; que
deje de depender de palabras clave y los use ella misma".

Antes: texto libre -> regex de intents (rapido pero ciego: solo casaba
patrones escritos a mano) -> si no casaba, CHAT. Los ~60 comandos "/" solo
se usaban si el usuario los tecleaba.

Ahora: cuando las reglas rapidas no reconocen una accion, el PROPIO MODELO
lee el mensaje + el catalogo completo (comandos "/" con sus descripciones y
las capacidades del agente) y ELIGE la ruta:

    CHAT               -> conversacion normal (respuesta directa)
    AGENTE             -> tarea de archivos/sistema/web (loop de tools)
    /comando <args>    -> un comando del catalogo, con sus argumentos

La decision del modelo se VALIDA (solo comandos que existen; formato
estricto; ante cualquier duda -> CHAT, que es el fallback inofensivo). El
comando elegido se reinyecta al REPL como si el usuario lo hubiera tecleado,
asi TODO el catalogo queda disponible por lenguaje natural.

Concreto: 3 funciones planas. Sin estado, sin clases. Kill-switch:
COGNIA_ENRUTADOR=0.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections import OrderedDict

# Comandos que el enrutador tiene PROHIBIDO elegir solo (destructivos, de
# salida, o que necesitan intencion explicita del usuario).
_VETADOS = {"/salir", "/exit", "/quit", "/limpiar", "/reset", "/borrar",
            "/apagar", "/shutdown", "/shell-kill"}


def activo() -> bool:
    return os.environ.get("COGNIA_ENRUTADOR", "1").strip().lower() not in (
        "0", "off", "false", "no")


_cache_catalogo: str | None = None


def catalogo_compacto(cmd_descriptions: dict) -> str:
    """El catalogo '/' en una linea por comando (nombre + descripcion corta),
    apto para el prompt del enrutador. Cacheado (el catalogo no cambia en
    runtime)."""
    global _cache_catalogo
    if _cache_catalogo is not None:
        return _cache_catalogo
    lineas = []
    for cmd, desc in sorted(cmd_descriptions.items()):
        if cmd in _VETADOS:
            continue
        d = re.sub(r"\s+", " ", str(desc)).strip()[:90]
        lineas.append(f"{cmd} — {d}")
    _cache_catalogo = "\n".join(lineas)
    return _cache_catalogo


def invalidar_catalogo() -> None:
    """Olvida el catalogo cacheado: la proxima llamada lo vuelve a armar.

    El cache de arriba se escribio cuando el catalogo era inmutable en runtime
    ("el catalogo no cambia en runtime"). Desde `/avanzado` y `/modo` (2026-08-29)
    SI cambia: `cli._cmds_visibles()` devuelve 80 comandos o los 280 segun el
    nivel, y `catalogo_compacto` recibe ese dict filtrado. Sin esta funcion el
    enrutador seguiria proponiendo (o dejando de proponer) comandos con el
    nivel del ARRANQUE hasta que el dueno reinicie: un cambio que "no hace
    nada" y ningun error que mirar.

    La llama `cli._invalidar_caches_de_nivel()`, junto a
    `cli_visibilidad.invalidar_cache()`. Son dos caches distintos en dos
    modulos distintos y hay que tirar los dos.
    """
    global _cache_catalogo
    _cache_catalogo = None


# -- Camino DETERMINISTA y telemetria (PLAN2, PEDIDO 2) --------------------
# MEDIDO (dossier f2_enrutador-chat-agente, backend real Qwen3.8-27B-Ridge):
# el enrutador acierta 10/10 pero cuesta 1.841-27.121 ms con varianza de 3x
# sobre el MISMO mensaje, y 2 de cada 10 mensajes del dueno pagan segundos de
# modelo para confirmar un chat que la capa de reglas ya sabia. Estas
# constantes son los topes del camino barato que va ANTES del modelo.
MAX_TOKENS_RUTA = 24        # la decision util son 4-12 tokens
MAX_TOKENS_PENSANDO = 400   # tope viejo: el unico seguro si NO se apaga pensar
_CACHE_MAX = 128
_CTX_TURNOS = 2
_CTX_CHARS_TURNO = 200
_CTX_TOPE = 600

_cache_decisiones = OrderedDict()
_contadores = {"chat": 0, "agente": 0, "comando": 0,
               "cache_hits": 0, "determinista": 0, "modelo": 0, "fallos": 0}
_ultimo = {"ruta": "", "extra": "", "ms": 0.0, "via": ""}


_PROMPT = """Eres el enrutador interno de Cognia. Lee el mensaje del usuario y elige UNA ruta:

- CHAT: conversacion, opinion, o pregunta que se responde hablando.
- AGENTE: tarea concreta sobre archivos, sistema, apps o web (el agente tiene herramientas: leer/escribir archivos, ejecutar comandos, abrir apps/URLs, buscar, capturar pantalla, click, teclear).
- Un comando del catalogo si encaja MEJOR que el chat y que el agente.

Catalogo de comandos:
{catalogo}

Reglas:
- Responde SOLO una linea: "RUTA: CHAT" o "RUTA: AGENTE" o "RUTA: /comando argumentos".
- Elige un /comando SOLO si el mensaje pide claramente esa capacidad.
- Preguntas de conocimiento general (historia, ciencia, definiciones) -> RUTA: CHAT. Los comandos de memoria (p.ej. /conocimiento-ver) consultan la memoria INTERNA de Cognia, no responden preguntas del mundo.
- Escribe los argumentos tal cual, SIN comillas alrededor.
- Ante la duda, RUTA: CHAT.

Ejemplos:
- "muestrame tus estadisticas" -> RUTA: /stats
- "piensa muy a fondo y resuelve: <problema>" -> RUTA: /pensar <problema>
- "investiga sobre X" -> RUTA: /investigar X
- "hazme un programa que ordene numeros" -> RUTA: /crear programa que ordena numeros
- "que es la fotosintesis?" -> RUTA: CHAT
- "borra la ultima linea del archivo notas.txt" -> RUTA: AGENTE
- "como estas hoy?" -> RUTA: CHAT

{contexto}Mensaje del usuario: {mensaje}
RUTA:"""


def _auditar_sin_modelo(detalle: str) -> None:
    """Deja en el backend-audit que el fallback a chat fue por AUSENCIA de
    inferencia, no por decision del modelo. Sin esta marca, un backend caido
    enruta TODO a chat y la corrida es indistinguible de una sana (auditoria
    2026-08-01). Nunca lanza: es instrumentacion."""
    try:
        from cognia import backend_activo
        backend_activo.sin_backend("enrutador", f"sin_modelo: {detalle}")
    except Exception:
        pass


def invalidar_cache() -> None:
    """Vacia la cache de decisiones del enrutador. Nunca lanza.

    La llama `cli._invalidar_caches_de_nivel()` (un cambio de nivel cambia
    los comandos validos, asi que las decisiones cacheadas dejan de valer) y
    el comando `/enrutador on|off`.
    """
    _cache_decisiones.clear()


def reset_contadores() -> None:
    """Pone a cero los contadores de `/enrutador estado`. Nunca lanza."""
    for k in _contadores:
        _contadores[k] = 0
    _ultimo.update({"ruta": "", "extra": "", "ms": 0.0, "via": ""})


def contadores() -> dict:
    """Copia de los contadores de sesion: chat / agente / comando /
    cache_hits / determinista / modelo / fallos.

    Existe para que `/enrutador estado` pueda ENSENAR si ensanchar los guards
    rompio rescates: sin telemetria, la regresion "una accion que se fue a
    chat" es invisible por definicion (dossier f2_enrutador-chat-agente)."""
    return dict(_contadores)


def ultimo_enrutado() -> dict:
    """Lo ultimo que decidio el enrutador: {ruta, extra, ms, via}.

    `via` es "cache" | "determinista" | "modelo": distingue los 0 ms de los
    ~900 ms, que es justo lo que hay que poder mirar para saber si el camino
    barato esta funcionando."""
    return dict(_ultimo)


def contexto_de_history(history, turnos: int = _CTX_TURNOS,
                        chars_turno: int = _CTX_CHARS_TURNO,
                        tope: int = _CTX_TOPE) -> str:
    """Los ULTIMOS turnos de `cli._history` en un bloque acotado para el prompt.

    EL TOPE ES PARTE DEL CAMBIO, no un extra: el prefill del prompt del
    enrutador esta MEDIDO en 219 ms y tres turnos largos lo duplican. Por eso
    2 turnos, 200 chars cada uno y un tope duro de 600 chars -- el mismo tope
    que ya tenia el mensaje.

    Acepta la forma real de `_history` (lista de dicts role/content) y tolera
    basura: nunca lanza, devuelve "" si no hay nada utilizable.
    """
    try:
        ultimos = [m for m in (history or []) if isinstance(m, dict)][-turnos:]
    except Exception:
        return ""
    lineas = []
    for m in ultimos:
        rol = str(m.get("role") or "")
        txt = " ".join(str(m.get("content") or "").split())[:chars_turno]
        if not txt:
            continue
        lineas.append(("usuario: " if rol == "user" else "cognia: ") + txt)
    return "\n".join(lineas)[:tope]


def kwargs_sin_pensar() -> dict:
    """`{"kwargs_plantilla": {...}}` para APAGAR el razonamiento, o `{}`.

    Se PREGUNTA AL PERFIL por la clave correcta en vez de mandar
    `enable_thinking` a ciegas: la clave que apaga el pensamiento es distinta
    por familia y mandarsela a un modelo cuya plantilla no la conoce no apaga
    nada y no avisa. Es el mismo helper que ya usa el editor de flujos
    (`flujo_ia._kwargs_sin_pensar`), reusado; si ese devuelve {} porque el
    editor tiene el pensamiento encendido a proposito (COGNIA_FLUJO_PENSAR),
    aqui se le pregunta al perfil igual: la decision del enrutador son 4
    tokens y no se razona nunca.

    MEDIDO (dossier f2_enrutador-chat-agente, backend real): con el
    pensamiento en su default el enrutador genera 51-354 tokens por decision y
    cuesta 1.841-27.121 ms con varianza de 3x sobre el mismo mensaje; apagado,
    20/20 rutas correctas en 874-986 ms planos.
    """
    try:
        from cognia.agent.flujo_ia import _kwargs_sin_pensar
        extra = _kwargs_sin_pensar()
        if extra.get("kwargs_plantilla"):
            return extra
    except Exception:
        pass
    try:
        from cognia.agent.model_profiles import perfil_del_agente
        kw = dict(perfil_del_agente().get("kwargs_plantilla") or {})
    except Exception:
        return {}
    if "enable_thinking" in kw:
        kw["enable_thinking"] = False
        return {"kwargs_plantilla": kw}
    return {}


def presupuesto_ruta():
    """(extra_para_completar, max_tokens) para UNA decision de ruta.

    EL TOPE CORTO VA ATADO AL PENSAMIENTO APAGADO, y esa atadura es el cambio:
    un tope de 24 tokens con el razonador encendido devuelve `content` VACIO
    (el presupuesto entero se lo come el bloque de razonamiento),
    `decidir()` lo lee como "no hubo inferencia" y cae a CHAT en silencio --
    exactamente el fallo que el dueno describe como "no hace nada". Si el
    perfil no sabe apagar el pensamiento, se paga el tope largo.
    """
    extra = kwargs_sin_pensar()
    return extra, (MAX_TOKENS_RUTA if extra else MAX_TOKENS_PENSANDO)


def inferir_ruta(prompt: str, url: str = "", timeout: float = None) -> str:
    """`infer_fn` lista para `decidir()`: el modelo del agente SIN pensar y
    con presupuesto de 24 tokens. Nunca lanza; devuelve "" si el backend
    fallo (y entonces `decidir` audita `sin_modelo` y cae a chat con rastro).
    """
    try:
        from cognia.agent import chat_client
    except Exception as exc:      # pragma: no cover - sin cliente no hay ruta
        _auditar_sin_modelo(f"sin chat_client: {exc}")
        return ""
    extra, tope = presupuesto_ruta()
    resp = chat_client.completar(
        [{"role": "user", "content": prompt}], url=url,
        temperature=0.2, max_tokens=tope, timeout=timeout,
        via="enrutador", **extra)
    if getattr(resp, "error", ""):
        return ""
    return str(getattr(resp, "texto", "") or "")


def _clave(mensaje: str, contexto: str) -> str:
    return hashlib.sha1(
        (mensaje.lower().strip() + "|" + str(hash(contexto))).encode(
            "utf-8", "replace")).hexdigest()


def ruta_determinista(mensaje: str, turno_previo_agente: bool = False):
    """La ruta SIN modelo, o None si de verdad hay que preguntarle.

    OJO con `turno_previo_agente`: el REPL NO lo pasa (ver el contrato entero
    en `intent.detect`). Desde `cli.py` este parametro es siempre False, asi
    que el escalon 3 NO esta activo en produccion. Lo usan el banco
    (`scripts/banco_rutas.py`, brazo `escalon3`, etiquetado) y los tests.

    Escalones 1-3 del camino determinista (PLAN2, PEDIDO 2): reusa
    `intent.detect`, que ya es la capa que resuelve 6 de cada 10 mensajes del
    dueno en <=2 ms, con los guards ensanchados y la regla de continuacion.

      - `needs_agent`               -> ("agente", "")   [accion obvia]
      - `reason == "conversacional"` -> ("chat", "")     [charla obvia]
      - cualquier otra cosa          -> None, que es el RESCATE: los dos casos
        medidos que solo el modelo salva ("arregla el bug de X", "lee mis
        notas y resumelas en un fichero") caen aqui con reason="chat".

    Por que "agente" y no un /comando: desde el CLI un mensaje con
    `needs_agent` NI SIQUIERA llega a `decidir()` (el gate de cli.py lo manda
    al agente antes), asi que este atajo no le quita una ruta de comando a
    nadie; solo evita pagar el modelo cuando a `decidir()` la llama otro
    (el banco, los tests, `/enrutador`).
    """
    try:
        from cognia.agent.intent import detect
    except Exception:
        return None
    try:
        it = detect(mensaje, turno_previo_agente=turno_previo_agente)
    except Exception:
        return None
    if it.needs_agent:
        return "agente", ""
    if it.reason == "conversacional":
        return "chat", ""
    return None


def decidir(mensaje: str, infer_fn, catalogo_txt: str,
            contexto: str = "", turno_previo_agente: bool = False) -> tuple:
    """
    ("chat"|"agente"|"comando", extra) -- extra es la linea "/cmd args" cuando
    la ruta es comando. infer_fn(prompt) -> str (el modelo residente); si es
    None se usa `inferir_ruta` (el modelo sin pensar, 24 tokens).
    Cualquier fallo o salida rara -> ("chat", "").

    CUATRO ESCALONES ANTES DEL MODELO (PLAN2, PEDIDO 2; el modelo acierta
    10/10 pero cuesta 1.841-27.121 ms, y 2 de cada 10 turnos del dueno son
    PEAJE INUTIL: segundos para confirmar un chat que ya se sabia):
      1. cache LRU de 128 decisiones (<=0,01 ms), clave
         sha1(mensaje.lower().strip() + "|" + hash(contexto));
      2. `intent.detect` con los guards ensanchados (<=2 ms);
      3. la regla de continuacion con contexto (`turno_previo_agente`, 0 ms)
         -- SIN CABLEAR: `cli.py` no pasa este parametro, asi que en el
         producto el escalon 3 nunca dispara. Lo que falta esta escrito paso
         a paso en el docstring de `intent.detect`;
      4. y solo si nada de eso decidio, el modelo.

    `contexto`: los ultimos turnos, armados con `contexto_de_history()`
    (2 turnos, 200 chars, TOPE DURO 600). Entra en el prompt bajo el
    encabezado "Ultimos turnos:" y forma parte de la clave de la cache, para
    que el mismo mensaje en otra conversacion no reuse la decision vieja.
    """
    t0 = time.perf_counter()
    msg = (mensaje or "").strip()
    ctx = (contexto or "").strip()[:_CTX_TOPE]

    def _cerrar(ruta: str, extra: str, via: str, cachear: bool = True):
        if cachear:
            _cache_decisiones[_clave(msg, ctx)] = (ruta, extra)
            while len(_cache_decisiones) > _CACHE_MAX:
                _cache_decisiones.popitem(last=False)
        _contadores[ruta] = _contadores.get(ruta, 0) + 1
        _contadores["cache_hits" if via == "cache" else via] += 1
        _ultimo.update({"ruta": ruta, "extra": extra, "via": via,
                        "ms": (time.perf_counter() - t0) * 1000.0})
        return ruta, extra

    # 1. CACHE: este mismo mensaje en este mismo contexto ya se decidio
    clave = _clave(msg, ctx)
    if clave in _cache_decisiones:
        _cache_decisiones.move_to_end(clave)
        ruta, extra = _cache_decisiones[clave]
        return _cerrar(ruta, extra, "cache", cachear=False)

    # 2-3. CAMINO DETERMINISTA (guards ensanchados + continuacion)
    det = ruta_determinista(msg, turno_previo_agente=turno_previo_agente)
    if det is not None:
        return _cerrar(det[0], det[1], "determinista")

    # 4. el modelo, que es lo caro
    if infer_fn is None:
        infer_fn = inferir_ruta
    try:
        crudo = infer_fn(_PROMPT.format(
            catalogo=catalogo_txt,
            contexto=(f"Ultimos turnos:\n{ctx}\n\n" if ctx else ""),
            mensaje=msg[:600])) or ""
    except Exception as exc:
        _auditar_sin_modelo(f"infer_fn lanzo {type(exc).__name__}: {exc}")
        _contadores["fallos"] += 1
        return _cerrar("chat", "", "modelo", cachear=False)
    if not crudo.strip():
        # salida vacia = no hubo inferencia real (modelo mudo o ausente);
        # basura no-vacia si es decision del modelo y cae a chat sin audit
        _auditar_sin_modelo("inferencia vacia")
        _contadores["fallos"] += 1
        return _cerrar("chat", "", "modelo", cachear=False)
    # primera linea util; tolera que el modelo repita "RUTA:" o no
    linea = ""
    for l in crudo.splitlines():
        l = l.strip()
        if l:
            linea = re.sub(r"^RUTA\s*:\s*", "", l, flags=re.I).strip()
            break
    if not linea:
        return _cerrar("chat", "", "modelo")
    if re.fullmatch(r"chat\.?", linea, re.I):
        return _cerrar("chat", "", "modelo")
    if re.fullmatch(r"agente\.?", linea, re.I):
        return _cerrar("agente", "", "modelo")
    # el modelo a veces omite la barra ("RUTA: stats"): si el primer token
    # con "/" delante existe en el catalogo, se acepta igual (medido 2026-07-21)
    if not linea.startswith("/"):
        tok = linea.split()[0].rstrip(".,;:").lower()
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,24}", tok) and \
                re.search(rf"^/{re.escape(tok)} —", catalogo_txt, re.M):
            linea = "/" + linea
    if linea.startswith("/"):
        cmd = linea.split()[0].rstrip(".,;:")
        # VALIDACION dura: el comando debe existir en el catalogo y no estar
        # vetado -- el modelo no puede inventar ni elegir destructivos.
        if cmd in _VETADOS:
            return _cerrar("chat", "", "modelo")
        if re.search(rf"^{re.escape(cmd)} —", catalogo_txt, re.M):
            resto = linea[len(cmd):].strip().rstrip(".")
            # el modelo entrecomilla los argumentos ("RUTA: /crear \"un juego\"")
            # y /crear terminaba creando el programa con comillas en la idea
            resto = resto.strip("\"'“”‘’").strip()
            return _cerrar("comando", cmd + (" " + resto if resto else ""),
                           "modelo")
    return _cerrar("chat", "", "modelo")
