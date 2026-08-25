# -*- coding: utf-8 -*-
"""
cognia/harness/compactacion.py
==============================
COMPACTACION por RESUMEN ESTRUCTURADO en UNA pasada (F4, numeros de
deepseek-harness), en vez de mordiscos de truncado.

POR QUE EXISTE (2026-08-23): el recorte de hoy (`agent/loop._recortar_mensajes`)
trunca contents viejos a 200 chars DE A 3 POR PASADA — mordiscos repetidos que
ademas MUTAN el principio del contexto una vez por pasada, y cada mutacion
invalida la KV cache del server (leccion medida del repo: el cache de llama.cpp
solo reusa los ultimos 512 tokens; mutar el principio se paga ~24x por ciclo).
deepseek-harness compacta distinto y este modulo copia esos numeros:

  - disparo al 80% del contexto (umbral_frac, configurable),
  - retencion de la cola reciente (retencion_frac 0.16 del n_ctx),
  - UN resumen estructurado con cap de chars,
  - UNA sola reescritura del historial => UNA sola invalidacion de cache.

El resumen NO llama al modelo: se deriva del canal de estado si esta activo
(objetivo, restricciones, hecho-hasta-ahora: cognia/estado/canal.render) mas
una linea por cada turno tool descartado (nombre, args clave, exito/fallo y la
referencia de spill de F3 si existe: lo descartado sigue siendo RECUPERABLE
via la tool `recuperar` o `leer_archivo` sobre la ruta).

Secciones FIJAS del resumen (2026-08-24, deepagents 0.7.8 summarization.py:
su prompt exige SESSION INTENT / SUMMARY / ARTIFACTS / NEXT STEPS y un "None"
explicito por seccion vacia — una seccion ausente no se distingue de una
olvidada): OBJETIVO DE LA SESION (el user del objetivo), ARTEFACTOS (rutas
unicas tocadas por escribir/editar/borrar, fundidas entre pasadas), PROXIMOS
PASOS (los pendientes del canal de estado o "ninguno registrado"). Y el
HISTORIAL CRUDO descartado se vuelca ENTERO a disco antes del splice
(offloading.guardar, tool="compactacion"; deepagents _offload_to_backend anexa
lo evictado a /conversation_history/session_{uuid}.md y lo dice en el
resumen): el encabezado lleva handle y ruta; si el volcado falla, lo dice.

Forma del historial tras compactar:

    [system intacto, user del objetivo intacto,
     UN mensaje-resumen (role user, empieza por _MARCA),
     cola reciente INTACTA (~retencion_frac del n_ctx)]

La cola NO se toca (los mordiscos de 200 chars desaparecen en este modo) y el
corte nunca deja un turno tool huerfano de su assistant: un tool sin el
assistant que lo pidio rompe el template del chat en el server.

IDEMPOTENCIA: compactar dos veces no duplica resumenes. El resumen previo (se
reconoce por _MARCA, y vive siempre pegado al objetivo) cae dentro de la zona
vieja de la siguiente pasada y se FUNDE: sus lineas de tools descartadas pasan
al resumen nuevo sin repetirse.

SEGURIDAD DE FALLO: compactar() construye el resumen ENTERO antes de tocar la
lista — una excepcion a mitad de camino deja `mensajes` byte-identico, y el
llamador (agent/loop) la sube a _aviso_degradado('compactacion', ...) y cae al
modo truncado en ese turno. Nada muta a medias y nada falla en silencio.

Config (el CLI propaga config->env en el arranque, patron de offloading; los
knobs se leen a call-time para que /compactar y los tests cambien en caliente):

    COGNIA_COMPACT           resumen (default) | truncado (fuerza el viejo)
    COGNIA_COMPACT_UMBRAL    fraccion de n_ctx que dispara (default 0.8)
    COGNIA_COMPACT_RETENCION fraccion de n_ctx retenida de cola (default 0.16)
    COGNIA_COMPACT_CAP       chars maximos del resumen (default 4000)

API publica:

    modo() -> 'resumen' | 'truncado'
    umbral_frac() / retencion_frac() / cap_chars()
    compactar(mensajes, n_ctx, prompt_tokens, estado=None, ...) -> dict
        Muta `mensajes` EN SITIO (una sola vez) y devuelve la telemetria:
        {aplicada, liberados (chars), tokens_antes, tokens_despues,
         descartados, motivo, historial_handle, historial_ruta,
         historial_error} (los tres ultimos solo si aplico: el volcado crudo).
    anotar_truncado(liberados, prompt_tokens, n_ctx)
        Telemetria del modo viejo, para que /compactar tambien lo muestre.
    anotar_error(motivo)
        Registra el ultimo fallo del subsistema (lo llama agent/loop al caer
        al truncado; /compactar lo muestra).
    estado_puerta() -> dict   (la foto entera para /compactar)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger("cognia.harness.compactacion")

# Defaults de deepseek-harness: disparo al 80%, cola retenida 0.16 del n_ctx.
MODO_DEFECTO = "resumen"
UMBRAL_FRAC = 0.8
RETENCION_FRAC = 0.16
CAP_RESUMEN = 4000

# La primera linea del mensaje-resumen. Es el contrato de idempotencia: la
# siguiente pasada reconoce el resumen previo por este prefijo y lo FUNDE en
# vez de apilar otro. No cambiarla sin migrar los historiales vivos.
_MARCA = "[RESUMEN DE COMPACTACION]"

# La referencia de spill que deja offloading (F3) dentro del content de un
# turno tool: "[COMPLETO en res:3f2a1b (... bytes exactos) -> fichero: RUTA. "
# Se extraen handle y ruta para que lo descartado siga siendo recuperable.
_RE_SPILL = re.compile(r"\[COMPLETO en (res:[0-9a-f]{6,40})")
_RE_SPILL_RUTA = re.compile(r"-> fichero: (.+?)\. Para ver mas")

# Telemetria para la puerta /compactar: la ultima compactacion (de cualquiera
# de los dos modos) y el ultimo fallo. Solo memoria de proceso, nada en disco.
_ULTIMA: dict = {}
_ULTIMO_ERROR: dict = {}


# ── Knobs (a call-time, patron de offloading.umbral_bytes) ────────────────────

def modo() -> str:
    """'resumen' (default F4) o 'truncado' (el comportamiento viejo intacto).
    COGNIA_COMPACT gana; un valor desconocido se DICE y cae al default."""
    crudo = (os.environ.get("COGNIA_COMPACT") or "").strip().lower()
    if crudo in ("resumen", "truncado"):
        return crudo
    if crudo:
        logger.warning("COGNIA_COMPACT=%r no es resumen|truncado: uso %s",
                       crudo, MODO_DEFECTO)
    return MODO_DEFECTO


def _frac(var: str, defecto: float, lo: float, hi: float) -> float:
    crudo = (os.environ.get(var) or "").strip()
    if not crudo:
        return defecto
    try:
        v = float(crudo)
    except ValueError:
        logger.warning("%s=%r no es un numero: uso %s", var, crudo, defecto)
        return defecto
    return min(hi, max(lo, v))


def umbral_frac() -> float:
    """Fraccion de n_ctx que dispara la compactacion (0.3-0.99)."""
    return _frac("COGNIA_COMPACT_UMBRAL", UMBRAL_FRAC, 0.3, 0.99)


def retencion_frac() -> float:
    """Fraccion de n_ctx que se retiene de cola reciente (0.02-0.5)."""
    return _frac("COGNIA_COMPACT_RETENCION", RETENCION_FRAC, 0.02, 0.5)


def cap_chars() -> int:
    """Chars maximos del mensaje-resumen (>= 600: menos no aloja ni el bloque
    de estado con su cabecera)."""
    crudo = (os.environ.get("COGNIA_COMPACT_CAP") or "").strip()
    try:
        return max(600, int(crudo)) if crudo else CAP_RESUMEN
    except ValueError:
        logger.warning("COGNIA_COMPACT_CAP=%r no es un entero: uso %d",
                       crudo, CAP_RESUMEN)
        return CAP_RESUMEN


# ── Telemetria ────────────────────────────────────────────────────────────────

def anotar_truncado(liberados: int, prompt_tokens: int, n_ctx=None) -> None:
    """La pasada del modo viejo tambien se anota: /compactar muestra la ultima
    compactacion venga del modo que venga."""
    _ULTIMA.clear()
    _ULTIMA.update({
        "ts": time.time(), "modo": "truncado",
        "tokens_antes": int(prompt_tokens or 0),
        "tokens_despues": max(0, int(prompt_tokens or 0) - int(liberados) // 4),
        "liberados": int(liberados), "n_ctx": int(n_ctx or 0),
    })


def anotar_error(motivo) -> None:
    """El ultimo fallo del subsistema, visible en /compactar. El aviso al REPL
    (_aviso_degradado) lo emite el llamador; aca queda la constancia."""
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update({
        "motivo": str(motivo)[:300],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    logger.warning("harness.compactacion: %s", motivo)


def estado_puerta() -> dict:
    """La foto entera para la puerta /compactar del CLI."""
    return {
        "modo": modo(),
        "umbral": umbral_frac(),
        "retencion": retencion_frac(),
        "cap": cap_chars(),
        "ultima": dict(_ULTIMA),
        "ultimo_error": dict(_ULTIMO_ERROR),
    }


# ── La compactacion ───────────────────────────────────────────────────────────

def _chars_msg(m: dict) -> int:
    """Peso en chars de un mensaje: content + reasoning + args de tool_calls
    (misma moneda chars/4 ~ tokens que usa el presupuesto del bucle)."""
    n = len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
    for tc in (m.get("tool_calls") or []):
        try:
            n += len(str((tc.get("function") or {}).get("arguments") or "")) + 40
        except AttributeError:
            n += 40
    return n


def _linea_tool(nombre: str, args: str, contenido: str) -> str:
    """UNA linea por tool descartada: nombre, args clave, exito/fallo y la
    referencia de spill de F3 si el content la trae. El veredicto usa la
    heuristica compartida es_fallo_primera_linea (ERROR *o* exit != 0 en la
    linea 1): aca ya no hay ctx con el exit medido, y mirar solo \bERROR\b
    contaba un "RESULTADO ejecutar (exit 1): FFF" como OK — el mismo bug P0-1
    (pytest en rojo = victoria) reintroducido en la capa del resumen. Para lo
    spilleado por F3 la cabecera del offload propaga el marcador ERROR."""
    try:
        from cognia.harness.offloading import es_fallo_primera_linea as _fallo
        fallo = _fallo(contenido, nombre)
    except Exception:
        primera = contenido.split("\n", 1)[0]
        fallo = bool(re.search(r"\bERROR\b|\(exit -?[1-9]\d*\)", primera[:200]))
    veredicto = "FALLO" if fallo else "OK"
    extra = ""
    mh = _RE_SPILL.search(contenido)
    if mh:
        mr = _RE_SPILL_RUTA.search(contenido)
        extra = " | spill " + mh.group(1)
        if mr:
            extra += " -> " + mr.group(1)
    args_c = re.sub(r"\s+", " ", str(args or "")).strip()[:80]
    return "  * %s(%s) -> %s%s" % (nombre, args_c, veredicto, extra)


# Tools cuyo primer argumento es la RUTA que tocan (artefacto en el sentido de
# deepagents: fichero creado/modificado). leer_archivo no cuenta: leer no deja
# artefacto y listaria medio repo.
_TOOLS_ARTEFACTO = ("escribir_archivo", "editar_archivo", "borrar_archivo")
_PREFIJO_ARTEFACTO = "  ~ "


def _reserva_volcado() -> int:
    """Chars que ocupara la linea del volcado (se escribe DESPUES de decidir
    si el resumen libera): prefijo fijo + la ruta del almacen + sesion/handle."""
    try:
        from cognia.harness.offloading import dir_offload
        return 110 + len(str(dir_offload()))
    except Exception:
        return 260


def _ruta_de_args(args) -> str:
    """La ruta de un tool_call de escritura: JSON nativo {"ruta": ...} o el
    protocolo texto 'ruta | contenido'. "" si no se reconoce."""
    a = str(args or "").strip()
    if a.startswith("{"):
        try:
            d = json.loads(a)
            if isinstance(d, dict):
                return str(d.get("ruta") or d.get("path") or
                           d.get("archivo") or "").strip()
        except ValueError:
            pass                 # args no JSON: se intenta como texto
    return a.split("|", 1)[0].strip().strip("\"'")


def _volcar_historial(viejos: list) -> tuple:
    """Guarda los mensajes descartados (JSON) en el almacen del offload y
    devuelve (handle, ruta, error). Se llama JUSTO antes del splice: el
    volcado es la red de seguridad de un resumen que no llama al modelo, y
    va aunque el offload este apagado como tool (COGNIA_OFFLOAD): apagado
    significa 'no espillear observaciones', no 'tirar el historial'."""
    from cognia.harness import offloading as _off
    try:
        crudo = json.dumps(viejos, ensure_ascii=False, default=str)
        handle = _off.guardar(crudo, tool="compactacion",
                              args="historial descartado (%d mensajes)" % len(viejos))
        return handle, _off.ruta_de(handle), ""
    except Exception as exc:      # noqa: BLE001 - se reporta, no se traga
        motivo = "%s: %s" % (type(exc).__name__, exc)
        logger.warning("compactacion: volcado del historial FALLO: %s", motivo)
        return "", "", motivo


def umbral_tokens(n_ctx, umbral=None) -> int:
    """Tokens de prompt a partir de los cuales se compacta: la fraccion
    (umbral_frac, /compactar umbral) de la CAPACIDAD UTIL (n_ctx menos el
    headroom de contexto_vivo). Es la misma cuenta de la barra: antes la
    barra restaba el headroom y esto no, y decian cosas distintas en el
    mismo turno (revision adversarial 2026-08-24). 0 sin n_ctx."""
    import math
    from cognia.harness.contexto_vivo import capacidad_util
    umb = float(umbral) if umbral is not None else umbral_frac()
    util = capacidad_util(n_ctx)
    if util <= 0:
        return 0
    # ceil: 'tokens >= umbral' coincide con 'porcentaje_uso (truncado) >=
    # umbral_pct' token a token (ver contexto_vivo.porcentaje_uso).
    return int(math.ceil(util * umb))


def compactar(mensajes: list, n_ctx, prompt_tokens: int, estado=None,
              umbral=None, retencion=None, cap=None) -> dict:
    """UNA pasada: funde el historial viejo en un mensaje-resumen estructurado
    y deja la cola reciente INTACTA. Muta `mensajes` en sitio (un solo splice
    = una sola invalidacion de la KV cache) y devuelve la telemetria.

    No aplica (aplicada=False, con motivo) si: bajo el umbral, historial con
    forma inesperada, nada viejo que fundir, o el resumen no libera chars.
    Un fallo construyendo el resumen LANZA sin haber tocado la lista: el
    llamador degrada al modo truncado con aviso.
    """
    res = {"aplicada": False, "liberados": 0,
           "tokens_antes": int(prompt_tokens or 0),
           "tokens_despues": int(prompt_tokens or 0),
           "descartados": 0, "motivo": ""}
    if not n_ctx:
        res["motivo"] = "sin n_ctx"
        return res
    if int(prompt_tokens or 0) < umbral_tokens(n_ctx, umbral):
        res["motivo"] = "bajo el umbral"
        return res
    ret = float(retencion) if retencion is not None else retencion_frac()
    tope = int(cap) if cap is not None else cap_chars()

    # Cabeza protegida: system (si hay) + el PRIMER user (el objetivo). Es la
    # misma garantia de _recortar_mensajes: el objetivo es intocable por
    # diseno ("el agente olvida su objetivo" era el descarte en bloque).
    inicio = 0
    if mensajes and mensajes[0].get("role") == "system":
        inicio = 1
    if inicio < len(mensajes) and mensajes[inicio].get("role") == "user":
        inicio += 1
    else:
        # Forma inesperada (no hay user de objetivo donde el bucle lo pone):
        # mejor no tocar nada que adivinar que proteger.
        res["motivo"] = "historial sin user de objetivo: no toco nada"
        return res

    # Corte de la cola: se camina desde el final sumando chars hasta agotar
    # ~retencion*n_ctx tokens. El ultimo mensaje se retiene SIEMPRE aunque
    # solo el reviente el presupuesto (una cola vacia dejaria al modelo sin
    # el resultado que acaba de pedir).
    presupuesto = int(n_ctx * ret) * 4
    corte, usado = len(mensajes), 0
    while corte > inicio:
        c = _chars_msg(mensajes[corte - 1])
        if usado and usado + c > presupuesto:
            break
        usado += c
        corte -= 1
    # El corte nunca cae en mitad de un grupo assistant+tools: si la cola
    # arrancaria en un turno tool, se retrocede hasta incluir al assistant
    # que emitio esas tool_calls (huerfanos = template roto en el server).
    while corte > inicio and mensajes[corte].get("role") == "tool":
        corte -= 1

    viejos = mensajes[inicio:corte]
    if not viejos:
        res["motivo"] = "nada viejo que fundir"
        return res

    # -- construir el resumen ENTERO antes de tocar la lista ----------------
    lineas_previas: list = []    # del resumen previo (idempotencia)
    lineas_nuevas: list = []     # de las tools descartadas en ESTA pasada
    artefactos: list = []        # rutas unicas tocadas (previas + nuevas)
    id2call: dict = {}
    for m in viejos:
        rol = m.get("role")
        if rol == "assistant":
            for tc in (m.get("tool_calls") or []):
                f = tc.get("function") or {}
                nombre_tc = f.get("name") or "?"
                id2call[tc.get("id")] = (nombre_tc, f.get("arguments") or "")
                if nombre_tc in _TOOLS_ARTEFACTO:
                    ruta = _ruta_de_args(f.get("arguments"))
                    if ruta and ruta not in artefactos:
                        artefactos.append(ruta)
        elif rol == "tool":
            nombre, args = id2call.get(m.get("tool_call_id"), ("?", ""))
            lineas_nuevas.append(
                _linea_tool(nombre, args, str(m.get("content") or "")))
        elif rol == "user" and str(m.get("content") or "").startswith(_MARCA):
            # El resumen de la pasada anterior se FUNDE: sus lineas de tools
            # y sus artefactos pasan tal cual (mas viejos primero), sin
            # duplicar.
            for ln in str(m["content"]).split("\n"):
                if ln.startswith("  * ") and ln not in lineas_previas:
                    lineas_previas.append(ln)
                elif ln.startswith(_PREFIJO_ARTEFACTO):
                    ruta = ln[len(_PREFIJO_ARTEFACTO):].strip()
                    if ruta and ruta not in artefactos:
                        artefactos.insert(0, ruta)
    todas = lineas_previas + [ln for ln in lineas_nuevas
                              if ln not in lineas_previas]

    partes = [_MARCA + " el historial viejo de esta tarea se fundio aca; lo "
              "descartado sigue recuperable (tool recuperar sobre los handles "
              "res:, o leer_archivo sobre las rutas)."]
    # Secciones fijas (deepagents summarization.py: INTENT / ARTIFACTS /
    # NEXT STEPS, con su "None" explicito). Van ANTES del canal: el objetivo
    # es lo primero que el modelo tiene que releer tras perder el historial.
    # El primer user es [memoria][indice de skills][contexto previo]TAREA:
    # <tarea> (cli._history_inicial_agente): con el indice real delante
    # (13 skills, 2758 chars el 2026-08-24) la TAREA quedaba fuera de los
    # 400 y la seccion mostraba el indice, que ademas sigue intacto arriba.
    # Se arranca en la ULTIMA linea 'TAREA: ' (la tarea es lo ultimo del
    # user); sin marca, el user entero como hasta ahora.
    primer_user = str(mensajes[inicio - 1].get("content") or "")
    marcas = [mo.start() for mo in re.finditer(r"(?m)^TAREA: ", primer_user)]
    if marcas:
        primer_user = primer_user[marcas[-1]:]
    objetivo = re.sub(r"\s+", " ", primer_user).strip()
    if len(objetivo) > 400:
        objetivo = objetivo[:400] + " ... [objetivo recortado; el user original sigue intacto arriba]"
    partes.append("OBJETIVO DE LA SESION: " + (objetivo or "(user del objetivo vacio)"))
    if artefactos:
        partes.append("ARTEFACTOS (%d rutas tocadas por escribir/editar/borrar):"
                      % len(artefactos))
        partes.extend(_PREFIJO_ARTEFACTO + r for r in artefactos)
    else:
        partes.append("ARTEFACTOS: ninguno registrado")
    pendientes = list(estado.get("pendientes") or []) if isinstance(estado, dict) else []
    if pendientes:
        partes.append("PROXIMOS PASOS (%d):" % len(pendientes))
        partes.extend("  - " + str(x) for x in pendientes)
    else:
        partes.append("PROXIMOS PASOS: ninguno registrado")
    if estado is not None:
        # El canal de estado (goal, restricciones, hecho-hasta-ahora) YA es la
        # version estructurada de lo hecho: entra rendido, sin llamada al
        # modelo. Si render falla, la excepcion sube: el llamador degrada.
        from cognia.estado import canal as _canal
        bloque = _canal.render(estado, tope_chars=1200)
        if bloque:
            partes.append(bloque)

    if todas:
        # Cap HONESTO: el bloque de estado no se recorta (ya viene capado a
        # 1200 y con sus propias prioridades); se recortan las lineas de tools
        # MAS VIEJAS y se dice cuantas quedaron fuera.
        cab = "TOOLS DESCARTADAS (%d):" % len(todas)
        base = sum(len(p) + 1 for p in partes) + len(cab) + 1 + 80 + _reserva_volcado()
        disponible = max(0, tope - base)
        vivas, usado_l = [], 0
        for ln in reversed(todas):          # las mas nuevas sobreviven
            if usado_l + len(ln) + 1 > disponible:
                break
            vivas.append(ln)
            usado_l += len(ln) + 1
        vivas.reverse()
        partes.append(cab)
        partes.extend(vivas)
        if len(vivas) < len(todas):
            partes.append("  (... %d lineas mas viejas omitidas por cap=%d ...)"
                          % (len(todas) - len(vivas), tope))
    chars_viejos = sum(_chars_msg(m) for m in viejos)
    # La linea del volcado todavia no esta: se reserva su sitio en la cuenta
    # para no decidir 'libera' y despues no liberar.
    if chars_viejos - (len("\n".join(partes)) + _reserva_volcado()) <= 0:
        # Zona vieja chica: reescribirla AGRANDARIA el prompt e invalidaria la
        # cache para nada. No aplicar es la unica jugada que no pierde.
        res["motivo"] = "el resumen no libera chars: no toco nada"
        return res

    # -- volcado CRUDO de lo que se descarta, justo antes del splice --------
    # No se ha tocado la lista todavia: si esto lanza (no deberia: _volcar
    # captura), el llamador degrada sobre un historial intacto.
    handle_v, ruta_v, error_v = _volcar_historial(viejos)
    if handle_v:
        partes.insert(1, "El historial completo de lo compactado (%d mensajes, "
                         "JSON) esta en %s: recuperar %s o leer_archivo esa ruta."
                         % (len(viejos), ruta_v or handle_v, handle_v))
    else:
        partes.insert(1, "AVISO: el volcado del historial compactado a disco "
                         "FALLO (%s): lo descartado solo sobrevive en las "
                         "lineas de abajo." % error_v)
    resumen = "\n".join(partes)
    liberados = chars_viejos - len(resumen)
    if liberados <= 0:
        res["motivo"] = "el resumen no libera chars: no toco nada"
        return res

    # -- el UNICO punto que muta: un splice = una invalidacion de cache -----
    mensajes[inicio:corte] = [{"role": "user", "content": resumen}]
    res.update(aplicada=True, liberados=liberados, descartados=len(viejos),
               tokens_despues=max(0, int(prompt_tokens) - liberados // 4),
               motivo="compactado", historial_handle=handle_v,
               historial_ruta=ruta_v, historial_error=error_v)
    _ULTIMA.clear()
    _ULTIMA.update({
        "ts": time.time(), "modo": "resumen",
        "tokens_antes": res["tokens_antes"],
        "tokens_despues": res["tokens_despues"],
        "liberados": liberados, "mensajes_descartados": len(viejos),
        "n_ctx": int(n_ctx),
        "historial_handle": handle_v, "historial_ruta": ruta_v,
        "historial_error": error_v,
    })
    return res
