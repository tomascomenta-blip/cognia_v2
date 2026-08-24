# -*- coding: utf-8 -*-
"""
cognia/harness/contexto_vivo.py
===============================
Contador EN VIVO de contexto y coste de la sesion: cuanta ventana queda y
cuantos tokens se llevan gastados, con los numeros REALES del backend.

POR QUE EXISTE (2026-08-12): el `/costo` de hoy miente. Suma
`len(salida) // 4` sobre el log de sesion, o sea (a) estima cuando el `usage`
real YA viene en la respuesta del backend — `loop.py` lo lee para recortar
mensajes (`_recortar_mensajes`) y lo tira despues —, (b) ignora por completo la
ENTRADA, que en un agente con historial es 10-20x la salida, y (c) no dice
absolutamente nada de lo unico que el usuario necesita saber antes de que se le
caiga la sesion: cuanto queda de ventana. Todos los CLIs punteros muestran ese
estado permanentemente (Claude Code "Context left until auto-compact", la barra
de estado de Gemini CLI, opencode, los tokens y coste por mensaje de Aider).
Aca se implementa el acumulador de proceso equivalente, y la mentira se corta de
raiz: si un numero no viene del `usage` del backend, el estado sale marcado
`estimado=True` y la barra lleva un `~` delante. Preferimos un numero feo y
honesto a uno bonito e inventado.

API publica (lo que el integrador cablea; este modulo NO toca el CLI):

    registrar_uso(prompt_tokens, completion_tokens, modelo="", cached=0,
                  estimado=False) -> dict
        Un turno con `usage` REAL. Suma al acumulado, cuenta un turno, recuerda
        el modelo y ADEMAS fija la ocupacion de ventana en
        prompt_tokens + completion_tokens: eso es exactamente lo que arrastrara
        el proximo prompt, asi que la barra ya es util sin cablear nada mas.
        Llamar desde donde hoy se descarta `resp.usage` (loop.py / cli.py).

    registrar_contexto(tokens_en_ventana, n_ctx, estimado=False) -> dict
        Fija ocupacion y tamano de ventana explicitamente (pisa lo que dedujo
        `registrar_uso`). `n_ctx` sale del backend/perfil, nunca de una
        constante de este modulo.

    estado() -> dict
        {entrada, salida, total, cacheados, n_ctx, ocupacion, porcentaje,
         restante, modelo, turnos, estimado, nivel}. Copia: mutarla no afecta
        al acumulador.

    barra(ancho=None, con_color=True) -> str
        La linea corta para la barra de estado inferior:
        "<modelo> · ctx 12.4k/32k (38%) · 1.2k tok". Sin emojis; separador ASCII
        '|' si la consola no codifica '·' (misma regla que tasks_board).
        `ancho` por defecto = min(ancho de terminal, 80). Si no cabe, degrada
        por prioridad — se recorta el MODELO primero, el ctx despues:
            1. modelo completo · ctx X/Y (P%) · N tok
            2. modelo abreviado (12 chars) · ctx X/Y (P%) · N tok
            3. ctx X/Y (P%) · N tok
            4. ctx P% · N tok
            5. N tok
        Color ANSI (amarillo/rojo) solo a partir del umbral de aviso; por
        debajo la barra va en el color del terminal, que es lo que uno quiere
        de un indicador permanente.

    aviso_umbral() -> "" | "aviso" | "critico"
        Para que el CLI sugiera compactar. Aviso al umbral REAL de
        compactacion (umbral_aviso_pct: COGNIA_CTX_AVISO > umbral_frac de
        harness/compactacion > 80), critico a umbral_critico_pct
        (COGNIA_CTX_CRITICO > 90), CON
        histeresis: un aviso ya emitido no se repite hasta que el porcentaje
        baja 5 puntos por debajo de su umbral (85 / 70). Solo avisa al
        ESCALAR: bajar de critico a aviso no vuelve a hablar. Es una funcion
        con efecto (arma/desarma), pensada para llamarse una vez por turno.

    estimar_tokens(texto) -> int
        FALLBACK explicito para cuando no hay `usage` (backends que no lo
        mandan). ~4 chars/token en alfabeto latino, ~1 token por caracter CJK.

    registrar_uso_estimado(texto_entrada="", texto_salida="", modelo="") -> dict
        Azucar de lo anterior: estima y registra marcando estimado=True.

    reiniciar() -> None
        Para /limpiar: borra acumulado, ventana, modelo e histeresis.

LIMITES DECLARADOS (lo que este modulo NO hace):
  - No hay dinero. Los modelos de la flota son LOCALES: un precio por token
    seria una constante inventada (y el repo prohibe hardcodear modelo). Si
    alguna vez se cablea un backend de pago, el precio entra por el llamador
    con el catalogo, no por aca.
  - No persiste NADA: es memoria de proceso, muere con el REPL. Sin BD, sin
    fichero, sin `os.replace`. La sesion vieja no se compara con la nueva.
  - `cached` es informativo (los tokens cacheados YA vienen dentro de
    `prompt_tokens` en la convencion OpenAI): se acumula aparte y NO se suma
    al total, para no contar dos veces.
  - La ocupacion es la del ultimo turno REGISTRADO. Si el CLI recorta el
    historial y no vuelve a registrar, la barra queda vieja hasta el proximo
    turno; no espia la lista de mensajes.
  - `estimado` es pegajoso a proposito: una vez que entro un numero estimado,
    el TOTAL de la sesion queda marcado hasta `reiniciar()`. Mezclar real y
    estimado y presentarlo como real es justo el bug que esto viene a matar.
    `ocupacion_estimada` NO es pegajosa: dice si la OCUPACION vigente (la del
    ultimo registro) salio de chars/4 o del usage real; es la que la barra
    pinta con '~'. Con la pegajosa, un solo turno de chat marcaba '~' todos los
    turnos posteriores del agente con usage real (revision adversarial
    2026-08-24).
  - `porcentaje` es 0 mientras no se conozca `n_ctx` (no se adivina la ventana).
  - LA UNICA ARITMETICA (2026-08-24): el porcentaje se calcula sobre
    capacidad_util(n_ctx) = n_ctx - HEADROOM_TOKENS (1024, receta CodeWhale: el
    server necesita margen para la respuesta en curso). La barra
    (barra_estado.nivel_contexto), el disparo de compactacion
    (compactacion.umbral_tokens) y el recorte legacy del bucle usan ESTA
    funcion: antes la barra restaba el headroom y la compactacion no, y la
    barra decia 'aviso · /compactar' al 78,75% del n_ctx mientras compactar()
    seguia 'bajo el umbral'.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading

# Umbrales FALLBACK de ocupacion de ventana (en % de n_ctx) y ancho de la
# histeresis. Los vigentes los dan umbral_aviso_pct()/umbral_critico_pct():
# el de aviso sigue al umbral REAL de compactacion (compactacion.umbral_frac,
# default 0.8) para que la barra y el disparo de compactar digan lo mismo —
# el 75 hardcodeado de antes mentia por 5 puntos (2026-08-23). Las env
# COGNIA_CTX_AVISO / COGNIA_CTX_CRITICO (que el CLI siembra desde la config
# contexto_umbral_aviso/critico) ganan a todo.
UMBRAL_AVISO = 80
UMBRAL_CRITICO = 90
HISTERESIS = 5
# Headroom fijo restado SIEMPRE del n_ctx antes de cualquier porcentaje o
# umbral (ver 'LA UNICA ARITMETICA' arriba). barra_estado lo importa de aqui.
HEADROOM_TOKENS = 1024


def capacidad_util(n_ctx) -> int:
    """Tokens realmente disponibles: n_ctx menos el headroom (minimo 1).
    0 si n_ctx es desconocido (<= 0): nadie inventa un porcentaje."""
    n = _entero(n_ctx)
    if n <= 0:
        return 0
    return max(1, n - HEADROOM_TOKENS)


def porcentaje_uso(ocupacion, n_ctx) -> int:
    """% de uso sobre la capacidad util, 0..100, redondeado (es lo que se
    PINTA); 0 sin n_ctx. El NIVEL no se decide con este numero redondeado
    sino en tokens (nivel_uso): a 320 tokens del umbral el % ya dice 80 y
    la compactacion todavia no dispara."""
    util = capacidad_util(n_ctx)
    if util <= 0:
        return 0
    return min(100, max(0, int(round(_entero(ocupacion) * 100.0 / util))))


def tokens_del_pct(n_ctx, pct) -> int:
    """Tokens de ocupacion a partir de los cuales se esta AL `pct`% de la
    capacidad util (redondeo hacia arriba: es la misma cuenta que
    compactacion.umbral_tokens). 0 sin n_ctx."""
    import math
    util = capacidad_util(n_ctx)
    if util <= 0:
        return 0
    return int(math.ceil(util * float(pct) / 100.0))


def nivel_uso(ocupacion, n_ctx) -> str:
    """'' | 'aviso' | 'critico', decidido en TOKENS contra los umbrales
    vigentes (umbral_aviso_pct sigue a /compactar umbral): asi la barra
    pinta amarillo y el sufijo '/compactar' exactamente cuando compactar()
    dispara, ni un token antes."""
    o = _entero(ocupacion)
    if capacidad_util(n_ctx) <= 0:
        return ""
    if o >= tokens_del_pct(n_ctx, umbral_critico_pct()):
        return "critico"
    if o >= tokens_del_pct(n_ctx, umbral_aviso_pct()):
        return "aviso"
    return ""


def _pct_env(var: str):
    """Umbral por env como % entero 1-100, o None si no esta/ es basura (la
    basura se dice por logging, no se calla)."""
    crudo = (os.environ.get(var) or "").strip()
    if not crudo:
        return None
    try:
        v = int(float(crudo))
    except ValueError:
        logging.getLogger("cognia.harness.contexto_vivo").warning(
            "%s=%r no es un porcentaje: lo ignoro", var, crudo)
        return None
    return min(100, max(1, v))


def umbral_aviso_pct() -> int:
    """% de uso que enciende el aviso (amarillo). Prioridad: COGNIA_CTX_AVISO
    > umbral REAL de compactacion (se mueve con /compactar umbral) > 80."""
    v = _pct_env("COGNIA_CTX_AVISO")
    if v is not None:
        return v
    try:
        from cognia.harness.compactacion import umbral_frac
        return min(99, max(1, int(round(umbral_frac() * 100))))
    except Exception:
        return UMBRAL_AVISO


def umbral_critico_pct() -> int:
    """% de uso critico (rojo). COGNIA_CTX_CRITICO o el default 90."""
    v = _pct_env("COGNIA_CTX_CRITICO")
    return v if v is not None else UMBRAL_CRITICO


_ANCHO_MAX = 80          # la barra tiene que caber en 80 columnas
_MODELO_MAX = 12         # chars del nombre de modelo en la variante abreviada
_SEP_UNICODE = " · "
_SEP_ASCII = " | "
_ELIPSIS_UNICODE = "…"
# NO usar '~' de elipsis: ese caracter ya significa "este numero es estimado" en
# esta misma linea, y en consola cp1252/pipe (donde cae el fallback) el nombre de
# modelo recortado le robaria el sentido a la unica marca de honestidad que hay.
_ELIPSIS_ASCII = "."
_UNIDADES = ((1000.0, "k"), (1000000.0, "M"), (1000000000.0, "G"))

_ANSI = {"aviso": "\x1b[33m", "critico": "\x1b[31m"}
_ANSI_RESET = "\x1b[0m"

# El acumulador es de PROCESO y lo tocan hilos distintos (streaming del backend
# vs render de la barra), asi que las mutaciones van bajo lock.
_LOCK = threading.Lock()


def _vacio() -> dict:
    return {
        "entrada": 0,
        "salida": 0,
        "cacheados": 0,
        "turnos": 0,
        "modelo": "",
        "ocupacion": 0,
        "n_ctx": 0,
        "estimado": False,
        "ocupacion_estimada": False,
        # Nivel de aviso ya emitido; lo consume la histeresis de aviso_umbral().
        "armado": "",
    }


_ACUM = _vacio()


# -- Acumulacion --------------------------------------------------------------

def reiniciar() -> None:
    """Vuelve a cero (para /limpiar): acumulado, ventana, modelo e histeresis."""
    with _LOCK:
        _ACUM.clear()
        _ACUM.update(_vacio())


def registrar_uso(prompt_tokens, completion_tokens, modelo: str = "",
                  cached: int = 0, estimado: bool = False) -> dict:
    """Suma un turno con el `usage` del backend. Devuelve `estado()`.

    Ademas de acumular, fija la ocupacion de ventana en entrada+salida del
    turno: eso es lo que el proximo prompt va a arrastrar. `cached` se guarda
    aparte porque ya viene DENTRO de prompt_tokens (convencion OpenAI) y
    sumarlo lo contaria dos veces.
    """
    entrada = _entero(prompt_tokens)
    salida = _entero(completion_tokens)
    with _LOCK:
        _ACUM["entrada"] += entrada
        _ACUM["salida"] += salida
        _ACUM["cacheados"] += _entero(cached)
        _ACUM["turnos"] += 1
        if modelo:
            _ACUM["modelo"] = str(modelo)
        if entrada or salida:
            _ACUM["ocupacion"] = entrada + salida
            _ACUM["ocupacion_estimada"] = bool(estimado)
        if estimado:
            _ACUM["estimado"] = True
    return estado()


def registrar_contexto(tokens_en_ventana, n_ctx, estimado: bool = False) -> dict:
    """Fija la ocupacion actual de la ventana y su tamano. Devuelve `estado()`.

    Pisa la ocupacion deducida por `registrar_uso`: el llamador sabe mejor
    (p.ej. despues de recortar el historial). Un `n_ctx` <= 0 significa
    "desconocido" y deja el porcentaje en 0 en vez de inventarlo.
    """
    ocupacion = _entero(tokens_en_ventana)
    ventana = _entero(n_ctx)
    with _LOCK:
        _ACUM["ocupacion"] = ocupacion
        _ACUM["n_ctx"] = ventana
        _ACUM["ocupacion_estimada"] = bool(estimado)
        if estimado:
            _ACUM["estimado"] = True
    return estado()


def registrar_uso_estimado(texto_entrada: str = "", texto_salida: str = "",
                           modelo: str = "") -> dict:
    """Registra un turno SIN `usage` real, estimando por texto. Marca estimado."""
    return registrar_uso(estimar_tokens(texto_entrada),
                         estimar_tokens(texto_salida),
                         modelo=modelo, estimado=True)


def estimar_tokens(texto) -> int:
    """Estimacion de tokens de un texto. FALLBACK, no verdad.

    ~4 chars por token en alfabeto latino (regla de OpenAI) y ~1 token por
    caracter CJK/emoji, que con la regla de 4 se subestimaba a la cuarta parte.
    Error tipico +-25%: por eso lo que pasa por aca sale marcado `estimado`.
    """
    if not texto:
        return 0
    texto = str(texto)
    anchos = sum(1 for ch in texto if ord(ch) > 0x2E80)   # CJK, kana, emoji
    latinos = len(texto) - anchos
    return max(1, anchos + (latinos + 3) // 4)


# -- Lectura ------------------------------------------------------------------

def estado() -> dict:
    """Foto del acumulador (copia). Ver el docstring del modulo para las claves."""
    with _LOCK:
        entrada = _ACUM["entrada"]
        salida = _ACUM["salida"]
        ocupacion = _ACUM["ocupacion"]
        n_ctx = _ACUM["n_ctx"]
        datos = {
            "entrada": entrada,
            "salida": salida,
            "total": entrada + salida,
            "cacheados": _ACUM["cacheados"],
            "n_ctx": n_ctx,
            "ocupacion": ocupacion,
            "modelo": _ACUM["modelo"],
            "turnos": _ACUM["turnos"],
            "estimado": _ACUM["estimado"],
            "ocupacion_estimada": _ACUM["ocupacion_estimada"],
        }
    datos["porcentaje"] = _porcentaje(ocupacion, n_ctx)
    datos["restante"] = max(0, n_ctx - ocupacion) if n_ctx > 0 else 0
    datos["nivel"] = nivel_uso(ocupacion, n_ctx)
    return datos


def aviso_umbral() -> str:
    """"" | "aviso" | "critico". Con histeresis; ver docstring del modulo.

    Tiene efecto de lado (arma/desarma el nivel ya avisado), asi que se llama
    UNA vez por turno. Para pintar sin avisar esta `estado()["nivel"]`.
    """
    est = estado()
    pct, nivel = est["porcentaje"], est["nivel"]
    with _LOCK:
        armado = _ACUM["armado"]
        # Desarmar hacia abajo: un aviso se re-arma recien 5 puntos por debajo
        # de su umbral, para no parpadear cuando el porcentaje oscila sobre el.
        while armado and pct < _umbral(armado) - HISTERESIS:
            armado = "aviso" if armado == "critico" else ""
        emitir = nivel if _orden(nivel) > _orden(armado) else ""
        _ACUM["armado"] = nivel if emitir else armado
    return emitir


def barra(ancho=None, con_color: bool = True) -> str:
    """Linea compacta para la barra de estado inferior. Ver docstring del modulo."""
    if ancho is None:
        ancho = min(_columnas_terminal(), _ANCHO_MAX)
    ancho = int(ancho)
    if ancho <= 0:
        return ""

    est = estado()
    sep = _SEP_UNICODE if _soporta_unicode(_SEP_UNICODE) else _SEP_ASCII
    marca = _ELIPSIS_UNICODE if _soporta_unicode(_ELIPSIS_UNICODE) else _ELIPSIS_ASCII

    modelo = est["modelo"].split("/")[-1]
    modelo_corto = modelo
    if len(modelo) > _MODELO_MAX:
        modelo_corto = modelo[:_MODELO_MAX - 1] + marca

    ctx_largo, ctx_corto = _piezas_ctx(est)
    # El '~' delante del total avisa de que ahi dentro hay numeros estimados.
    tok = ("~" if est["estimado"] else "") + _fmt_tokens(est["total"]) + " tok"

    # De mas a menos completa: se cede el modelo antes que el ctx, y el ctx
    # absoluto antes que el porcentaje.
    variantes = [
        (modelo, ctx_largo, tok),
        (modelo_corto, ctx_largo, tok),
        ("", ctx_largo, tok),
        ("", ctx_corto, tok),
        ("", "", tok),
    ]
    for modelo_v, ctx_v, tok_v in variantes:
        texto = sep.join([p for p in (modelo_v, ctx_v, tok_v) if p])
        if len(texto) <= ancho:
            return _colorear(texto, ctx_v, est["nivel"], con_color)
    return tok[:ancho]


# -- Interno ------------------------------------------------------------------

def _entero(valor) -> int:
    """Los `usage` llegan como int, str o None segun el backend; nunca negativo.

    Degrada a 0 con basura de verdad (`None`, "", listas, dicts) y ADEMAS con
    los `Infinity`/`NaN` que `json.loads` acepta por defecto: `int(inf)` tira
    OverflowError, que no es ni TypeError ni ValueError y reventaba el registro
    del turno entero. Segundo intento por `float` para rescatar el usage
    serializado como float en texto ("1000.0"), que si no se perdia ENTERO y
    contaba 0 tokens en silencio — justo la mentira que este modulo viene a matar.
    """
    if valor is None:
        return 0
    try:
        return max(0, int(valor))
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return max(0, int(float(valor)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _porcentaje(ocupacion: int, n_ctx: int) -> int:
    return porcentaje_uso(ocupacion, n_ctx)


def _umbral(nivel: str) -> int:
    return umbral_critico_pct() if nivel == "critico" else umbral_aviso_pct()


def _orden(nivel: str) -> int:
    return {"": 0, "aviso": 1, "critico": 2}[nivel]


def _piezas_ctx(est: dict) -> tuple:
    """(version larga, version corta) del trozo de ventana. Vacias si no hay dato."""
    if est["n_ctx"] > 0:
        largo = (f"ctx {_fmt_tokens(est['ocupacion'])}/{_fmt_tokens(est['n_ctx'])}"
                 f" ({est['porcentaje']}%)")
        return largo, f"ctx {est['porcentaje']}%"
    if est["ocupacion"] > 0:
        # Sin n_ctx no hay porcentaje que mostrar, pero la ocupacion es real.
        largo = f"ctx {_fmt_tokens(est['ocupacion'])}"
        return largo, largo
    return "", ""


def _fmt_tokens(n: int) -> str:
    """1234 -> '1.2k', 32000 -> '32k', 1500000 -> '1.5M'. Compacto y sin ruido.

    La unidad se elige DESPUES de redondear, no antes: 999_999 sale '1M' y no
    '1000k'. Mirando solo el rango se colaba 'ctx 1000k/1M' — dos unidades
    distintas en el mismo campo de una barra que existe para leerse de un vistazo.
    """
    n = _entero(n)
    if n < 1000:
        return str(n)
    for divisor, sufijo in _UNIDADES:
        valor = n / divisor
        if round(valor, 1) < 1000:
            return _sin_cero(valor) + sufijo
    divisor, sufijo = _UNIDADES[-1]
    return _sin_cero(n / divisor) + sufijo


def _sin_cero(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _colorear(texto: str, ctx: str, nivel: str, con_color: bool) -> str:
    """Tine SOLO el trozo de ctx, y solo a partir del umbral de aviso."""
    if not con_color or not nivel or not ctx or ctx not in texto:
        return texto
    return texto.replace(ctx, _ANSI[nivel] + ctx + _ANSI_RESET, 1)


def _soporta_unicode(s: str) -> bool:
    """Si la consola actual codifica `s`. Se decide a call-time: los pipes y las
    consolas cp1252 de Windows no aguantan '·' (misma regla que tasks_board)."""
    enc = getattr(sys.stdout, "encoding", None) or ""
    try:
        s.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


def _columnas_terminal() -> int:
    try:
        return max(1, shutil.get_terminal_size(fallback=(_ANCHO_MAX, 24)).columns)
    except (OSError, ValueError):
        return _ANCHO_MAX
