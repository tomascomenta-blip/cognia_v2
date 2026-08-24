# -*- coding: utf-8 -*-
"""
cognia/harness/barra_estado.py
==============================
BARRA DE ESTADO INFERIOR y BARRA DE ATAJOS del REPL (2026-08-12).

POR QUE EXISTE
--------------
Cognia no tiene NINGUNA de las dos, y todos los CLI punteros tienen al menos la
primera (juicio visual de las capturas oficiales de esta noche, en
C:\\Users\\usuario\\Desktop\\galeria_cli): Claude Code cierra la pantalla con una
barra de UNA linea; Gemini CLI pone ruta + sandbox + modo abajo; Crush pinta la
linea de atajos ("esc cancel . tab focus chat . ctrl+p commands"); Codex CLI
recuerda el modelo y el directorio en su caja de cabecera. En Cognia, en cambio,
el estado (modelo activo, directorio, rama, contexto consumido, modo plan,
permisos) o no se ve nunca o solo aparecio una vez en el arranque - que ademas
se desborda del ancho. El resultado medido: el usuario no sabe con que modelo
esta hablando ni cuanto contexto le queda sin escribir un comando.

Esto es SOLO el constructor: arma texto (y la version por partes con estilo
logico para rich). NO imprime, NO toca la consola, NO conoce el REPL. El
cableado (llamarlo desde el prompt, elegir cada cuanto refrescar) lo hace el
integrador. Cero dependencias duras: rich y prompt_toolkit NO se importan aca
- la salida es texto plano o tuplas, y quien tenga rich las pasa a
Text.assemble con los nombres de estilo del tema.

JERARQUIA (lo que se corrige es la DENSIDAD, no la identidad del producto)
-------------------------------------------------------------------------
Una sola linea, secciones separadas por " \u00b7 ", izquierda y derecha ancladas:

    PLAN \u00b7 qwythos-9b \u00b7 ~/Desktop/cognia_v2 \u00b7 main*   ctx 12.4k/128k (90% libre) \u00b7 3.2k tok

- IZQUIERDA (quien soy y donde estoy): insignia de modo, modelo, directorio,
  rama (con '*' si el arbol esta sucio).
- DERECHA (cuanto me queda), pegada al borde: contexto y tokens de la sesion.
- UN solo acento, reservado a la RAMA ('mod' del tema, igual que Claude Code
  reserva el coral). El resto es tenue: la barra informa, no compite con la
  conversacion. El contexto cuenta hacia ABAJO ('% libre', receta Codex) sobre
  n_ctx MENOS un headroom fijo de 1024 tokens (receta CodeWhale), con una
  mini-barra de bloques opcional a partir de 100 columnas; se pone 'warn_cl'
  al cruzar el umbral REAL de compactacion (compactacion.umbral_frac, default
  80%, movible con /compactar umbral o COGNIA_CTX_AVISO) con sufijo
  '/compactar', y 'err_cl' al critico (default 90%, COGNIA_CTX_CRITICO): ahi
  si es una alarma. Sin n_ctx del backend la barra dice 'ctx ?', jamas un %
  inventado; con ocupacion ESTIMADA (datos['ctx_estimado'], chars/4 del
  camino de chat) el usado lleva '~' delante: 'ctx ~3.1k/65.5k (95% libre)'.
- Sin emojis (la consola de Windows por defecto no los renderiza). Los unicos
  glifos no-ASCII son '\u00b7', '\u2026', '\u2191\u2193' y los bloques de la mini-barra, todos con
  fallback ASCII.

PRIORIDAD DE RECORTE (cuando la linea no cabe en `ancho`)
--------------------------------------------------------
Escalones, en este orden exacto; se usa el PRIMERO que entra:

    0. completa    todo
    1. sin_bloques cae la mini-barra de bloques (el % del ctx queda)
    2. sin_tokens  cae tokens_sesion
    3. dir_corto   el directorio se acorta a su ULTIMO componente
    4. sin_rama    cae la rama
    5. sin_modo    cae la insignia de modo
    6. sin_dir     cae el directorio entero  (extension propia: los 4 escalones
                   pedidos son 2-5; si ni asi entra, antes de mutilar el
                   modelo se sacrifica el directorio, que es lo unico que
                   queda y no es ni modelo ni contexto)

El MODELO y el CONTEXTO no se caen nunca. Si ni el ultimo escalon entra, la
linea se trunca en duro con '\u2026' al final (el modelo, que va primero, sobrevive
como prefijo legible). OJO: una seccion vacia por FALTA DE DATO (no hay rama,
no hay total de contexto) no es un recorte - simplemente no existe.

API
---
    humano(n)                          -> "0" / "999" / "1.0k" / "12.4k" / "1.2M"
    barra_estado(datos, ancho)         -> str  (largo visual == ancho si entra)
    barra_estado_partes(datos, ancho)  -> [(texto, estilo_logico), ...]
    barra_atajos(contexto)             -> str
    barra_atajos_partes(contexto)      -> [(texto, estilo_logico), ...]
    indicador_modo(modo, permiso)      -> (texto, estilo_logico); ("", "") si nada
    toolbar_prompt_toolkit(proveedor)  -> callable sin argumentos para
                                          PromptSession(bottom_toolbar=...)

`datos` es un dict (o cualquier Mapping) con las claves: modelo, directorio,
rama, sucio, ctx_usado, ctx_total, tokens_sesion, modo, permiso. TODAS son
opcionales y tolerantes a None/basura: una barra que revienta por un dato feo
seria peor que no tener barra.

VOCABULARIO (calcado del repo, no inventado)
--------------------------------------------
- modo:    'ejecutar' | 'plan'                    (cognia/harness/modo_plan.py)
- permiso: 'automatico' | 'manual' | 'bypass'     (cognia/console/permissions.py)
- estilos logicos: 'mod', 'detail', 'info_dim', 'footer', 'pensar', 'warn_cl',
  'err_cl'
  (claves reales de los tres temas de cognia/cli.py; hay test que lo verifica)

LIMITES DECLARADOS
------------------
- Constructor puro: no imprime ni mide la terminal (salvo dentro del callable
  de prompt_toolkit, que si consulta el ancho por comodidad del integrador).
- El ancho se mide en CELDAS aproximadas (east_asian_width): CJK cuenta 2. No
  se intenta resolver anchos de emoji ni ZWJ - por eso no hay emojis.
- El `ancho` se acota a [1, 10000]: ninguna terminal es mas ancha, y sin tope
  un ancho absurdo intenta materializar ese relleno de espacios.
- El estado no se guarda: cada llamada pinta lo que le pasan. Quien tenga el
  estado real (modelo activo, tokens de la sesion) es el CLI.
"""
from __future__ import annotations

import os
import shutil
import sys
import unicodedata

# ---------------------------------------------------------------------------
# Glifos y estilos
# ---------------------------------------------------------------------------
_SEP_UNI = " \u00b7 "        # punto medio: el separador de la casa (estilo.py)
_SEP_ASCII = " | "
_ELIP_UNI = "\u2026"
_ELIP_ASCII = ".."
_FLECHAS_UNI = "\u2191\u2193"
_FLECHAS_ASCII = "arriba/abajo"
_SUCIO = "*"                 # ASCII siempre: la marca de arbol sucio no negocia

# Mini-barra de bloques (Aider usa '█░'; aca 8 celdas y solo con terminal
# ancha). Fallback ASCII para consolas cp1252, que no codifican los bloques.
_BLOQUE_LLENO_UNI = "█"     # bloque lleno
_BLOQUE_VACIO_UNI = "░"     # sombra ligera
_BLOQUE_LLENO_ASCII = "#"
_BLOQUE_VACIO_ASCII = "."
CELDAS_BLOQUES = 8

# Estilos logicos (claves de los temas de cli.py). Se exponen para que el
# integrador pueda mapearlos y para el test de regresion contra el tema real.
EST_MODELO = "detail"
EST_DIR = "info_dim"
EST_RAMA = "mod"             # el UNICO acento de la barra
EST_SUCIO = "warn_cl"
EST_SEP = "footer"
EST_CTX = "info_dim"
EST_CTX_ALTO = "warn_cl"     # >= umbral de aviso (el de compactacion)
EST_CTX_CRITICO = "err_cl"   # >= umbral critico (default 90%)
EST_TOKENS = "footer"
EST_ATAJO_TECLA = "mod"
EST_ATAJO_ACCION = "footer"
# La insignia PLAN NO usa el acento (que es de la rama): toma el verde de
# 'pensar', el color que el dueno reservo al razonamiento. Planificar es
# pensar en voz alta, y asi la barra sigue teniendo UN solo acento.
EST_PLAN = "pensar"
EST_PERMISO_AUTO = "warn_cl"
EST_PERMISO_MANUAL = "info_dim"

ESTILOS = frozenset({
    EST_MODELO, EST_DIR, EST_RAMA, EST_SUCIO, EST_SEP, EST_CTX, EST_CTX_ALTO,
    EST_CTX_CRITICO, EST_TOKENS, EST_ATAJO_TECLA, EST_ATAJO_ACCION, EST_PLAN,
    EST_PERMISO_AUTO, EST_PERMISO_MANUAL, "",
})

# Headroom fijo (receta CodeWhale): se resta SIEMPRE del n_ctx antes de
# calcular el porcentaje. El server necesita margen para la respuesta en
# curso, y un 100% "matematico" que en la practica ya no admite ni un turno
# mas es un numero mentiroso.
HEADROOM_TOKENS = 1024

# Umbrales de alarma FALLBACK (porcentaje consumido). Los vigentes los da
# _umbrales(): salen de contexto_vivo, que a su vez lee el umbral REAL de
# compactacion (harness/compactacion.umbral_frac) — si el dueno lo mueve con
# /compactar umbral, el amarillo de esta barra se mueve con el. Estos dos
# numeros solo mandan si el harness no importa (y coinciden con los defaults
# de compactacion, no son un segundo umbral distinto que mienta).
PCT_ALTO = 80
PCT_CRITICO = 90


def _umbrales() -> tuple:
    """(aviso, critico) vigentes en % de uso, leidos a call-time para que
    /compactar umbral y las env muevan la barra en caliente."""
    try:
        from cognia.harness import contexto_vivo as _cv
        return _cv.umbral_aviso_pct(), _cv.umbral_critico_pct()
    except Exception:
        return PCT_ALTO, PCT_CRITICO


def bloques_activos() -> bool:
    """Mini-barra de bloques on/off. COGNIA_BARRA_BLOQUES=0|off la apaga (el
    CLI siembra la config 'barra_bloques' ahi); default ENCENDIDA — pero solo
    se pinta con terminal ancha (>= _ANCHO_BLOQUES), decision del integrador
    via _grupos."""
    crudo = (os.environ.get("COGNIA_BARRA_BLOQUES") or "").strip().lower()
    return crudo not in ("0", "off", "no", "false")


# Ancho minimo de terminal para que la mini-barra de bloques entre sin robarle
# celdas a nada (con menos de 100 columnas cae ELLA primero, el % queda).
_ANCHO_BLOQUES = 100

# Topes de las secciones que pueden venir larguisimas.
_TOPE_MODELO = 28
_TOPE_DIR = 40
_TOPE_RAMA = 28              # las ramas de feature son largas de verdad

# Escalones de recorte, en orden. Ver la seccion PRIORIDAD DE RECORTE.
# 'sin_bloques' es el primer sacrificio: la mini-barra de bloques es adorno
# del %, y el % (que es el dato) queda.
ESCALONES = ("completa", "sin_bloques", "sin_tokens", "dir_corto", "sin_rama",
             "sin_modo", "sin_dir")

# Ancho minimo con el que se intenta armar algo; por debajo se trunca en duro.
_ANCHO_MIN = 8
# Tope de cordura: ninguna terminal tiene 10.000 columnas, y sin tope un ancho
# absurdo (o basura numerica que casteo bien) intenta construir el relleno de
# espacios y revienta con OverflowError/MemoryError.
_ANCHO_MAX = 10000


# ---------------------------------------------------------------------------
# Utilidades de ancho y glifos
# ---------------------------------------------------------------------------
def _ancho_visual(texto: str) -> int:
    """Celdas que ocupa el texto en una terminal: CJK cuenta 2, los
    combinantes 0. Aproximacion deliberada (ver LIMITES)."""
    total = 0
    for ch in texto:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _encodable(texto: str) -> bool:
    """True si la consola actual puede escribir estos glifos. Es la prueba
    REAL (codec de stdout), no una lista de terminales conocidas: en Windows
    con cp1252 el '\u00b7' pasa y las flechas no, y eso es exactamente lo que
    hay que distinguir."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        texto.encode(enc)
        return True
    except Exception:
        return False


def _glifos(unicode_ok: bool | None) -> dict:
    """Juego de glifos a usar. None = autodetectar POR GLIFO (el separador y
    las flechas no tienen la misma suerte en cp1252)."""
    if unicode_ok is True:
        return {"sep": _SEP_UNI, "elip": _ELIP_UNI, "flechas": _FLECHAS_UNI,
                "lleno": _BLOQUE_LLENO_UNI, "vacio": _BLOQUE_VACIO_UNI}
    if unicode_ok is False:
        return {"sep": _SEP_ASCII, "elip": _ELIP_ASCII,
                "flechas": _FLECHAS_ASCII,
                "lleno": _BLOQUE_LLENO_ASCII, "vacio": _BLOQUE_VACIO_ASCII}
    return {
        "sep": _SEP_UNI if _encodable(_SEP_UNI) else _SEP_ASCII,
        "elip": _ELIP_UNI if _encodable(_ELIP_UNI) else _ELIP_ASCII,
        "flechas": (_FLECHAS_UNI if _encodable(_FLECHAS_UNI)
                    else _FLECHAS_ASCII),
        # cp1252 no codifica los bloques: se autodetecta POR GLIFO, igual que
        # el separador (los dos van juntos porque se prueban juntos).
        "lleno": (_BLOQUE_LLENO_UNI if _encodable(_BLOQUE_LLENO_UNI)
                  else _BLOQUE_LLENO_ASCII),
        "vacio": (_BLOQUE_VACIO_UNI if _encodable(_BLOQUE_VACIO_UNI)
                  else _BLOQUE_VACIO_ASCII),
    }


def _acortar(texto: str, tope: int, elip: str, por_izquierda: bool = False) -> str:
    """Acorta a `tope` celdas metiendo la elipsis. `por_izquierda` conserva el
    FINAL (lo util de una ruta es la cola), como hace estilo.objeto_de."""
    if tope <= 0 or _ancho_visual(texto) <= tope:
        return texto
    cupo = tope - _ancho_visual(elip)
    if cupo <= 0:
        return elip[:tope]
    if por_izquierda:
        acc, ancho = [], 0
        for ch in reversed(texto):
            w = _ancho_visual(ch)
            if ancho + w > cupo:
                break
            acc.append(ch)
            ancho += w
        return elip + "".join(reversed(acc))
    acc, ancho = [], 0
    for ch in texto:
        w = _ancho_visual(ch)
        if ancho + w > cupo:
            break
        acc.append(ch)
        ancho += w
    return "".join(acc) + elip


# ---------------------------------------------------------------------------
# Numeros humanos
# ---------------------------------------------------------------------------
def humano(n) -> str:
    """12400 -> '12.4k', 1250000 -> '1.2M'. Por debajo de 1000 va el entero
    tal cual (999 -> '999'); de 1000 en adelante SIEMPRE con un decimal
    ('1.0k'), asi el ancho de la seccion es estable y la barra no baila
    mientras se llena. Basura o None -> '' (nunca revienta)."""
    try:
        v = float(n)
    except (TypeError, ValueError, OverflowError):   # 10**400 no cabe en float
        return ""
    if v != v or v in (float("inf"), float("-inf")):   # NaN / infinitos
        return ""
    signo = "-" if v < 0 else ""
    v = abs(v)
    if v < 1000:
        return signo + str(int(v))
    k = v / 1000.0
    if k < 999.95:                     # 999_999 no puede salir '1000.0k'
        return signo + "{:.1f}k".format(k)
    return signo + "{:.1f}M".format(v / 1000000.0)


def _entero(x):
    """int tolerante: None/basura/infinito/enorme -> None, negativos -> 0.

    OverflowError entra en la lista a proposito: `float('inf')` y `10**400`
    revientan en `int(float(x))` con OverflowError, que NO es ValueError, y la
    barra tiene contrato de no lanzar nunca."""
    try:
        v = int(float(x))
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, v)


# ---------------------------------------------------------------------------
# Insignia de modo / permisos
# ---------------------------------------------------------------------------
def indicador_modo(modo: str = "", permiso: str = "") -> tuple:
    """El trocito destacado del estado del agente, como (texto, estilo).

    Devuelve ("", "") cuando NO hay nada que destacar - es decir, en el caso
    normal (modo 'ejecutar' + permisos 'automatico'): una insignia que esta
    siempre no destaca nada.

    Mapa (vocabulario real del repo):
        modo 'plan'         -> ("PLAN", 'pensar')   MANDA sobre el permiso: es
                               lo mas fuerte que puede estar pasando (el agente
                               no puede escribir).
        permiso 'bypass'    -> ("auto", 'warn_cl')  aprueba solo: se avisa.
        permiso 'manual'    -> ("manual", 'info_dim')
        cualquier otra cosa -> ("", "")
    """
    m = str(modo or "").strip().lower()
    p = str(permiso or "").strip().lower()
    if m == "plan":
        return ("PLAN", EST_PLAN)
    if p == "bypass":
        return ("auto", EST_PERMISO_AUTO)
    if p == "manual":
        return ("manual", EST_PERMISO_MANUAL)
    return ("", "")


# ---------------------------------------------------------------------------
# Secciones de la barra de estado
# ---------------------------------------------------------------------------
def _dato(datos, clave, defecto=None):
    try:
        return datos.get(clave, defecto)
    except Exception:
        return defecto


def _sec_modelo(datos, g) -> list:
    """El modelo, sin la parafernalia del path ni la extension .gguf: lo que
    el usuario dice en voz alta ('qwythos-9b')."""
    bruto = str(_dato(datos, "modelo", "") or "").strip()
    if not bruto:
        return []
    nombre = bruto.replace("\\", "/").split("/")[-1] or bruto
    for ext in (".gguf", ".bin", ".safetensors"):
        if nombre.lower().endswith(ext):
            nombre = nombre[:-len(ext)]
            break
    nombre = _acortar(nombre, _TOPE_MODELO, g["elip"])
    return [(nombre, EST_MODELO)]


def _sec_directorio(datos, g, corto: bool) -> list:
    bruto = str(_dato(datos, "directorio", "") or "").strip()
    d = bruto.replace("\\", "/").rstrip("/")
    if not d:
        return []
    if corto:
        d = d.split("/")[-1] or d
    else:
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        if home and (d.lower() == home.lower()
                     or d.lower().startswith(home.lower() + "/")):
            d = "~" + d[len(home):]
        d = _acortar(d, _TOPE_DIR, g["elip"], por_izquierda=True)
    return [(d, EST_DIR)]


def _sec_rama(datos, g) -> list:
    rama = str(_dato(datos, "rama", "") or "").strip()
    if not rama:
        return []
    partes = [(_acortar(rama, _TOPE_RAMA, g["elip"]), EST_RAMA)]
    if bool(_dato(datos, "sucio", False)):
        partes.append((_SUCIO, EST_SUCIO))
    return partes


def nivel_contexto(usado, total) -> dict:
    """La cuenta HONESTA del contexto, la misma que pinta la barra — expuesta
    para que la puerta /compactar estado diga lo mismo que el footer (nada de
    dos aritmeticas que discrepen).

    Devuelve {pct_usado, libre, nivel, aviso, critico, headroom}. Con el
    headroom fijo restado del total; sin total conocido, pct_usado y libre son
    None (jamas un % inventado) y nivel es ''."""
    u = _entero(usado) or 0
    t = _entero(total) or 0
    aviso, critico = _umbrales()
    base = {"aviso": aviso, "critico": critico, "headroom": HEADROOM_TOKENS}
    if t <= 0:
        return dict(base, pct_usado=None, libre=None, nivel="")
    util = max(1, t - HEADROOM_TOKENS)
    pct = min(100, max(0, int(round(u * 100.0 / util))))
    nivel = ("critico" if pct >= critico
             else "aviso" if pct >= aviso else "")
    return dict(base, pct_usado=pct, libre=100 - pct, nivel=nivel)


def _bloques(pct_usado: int, g) -> str:
    """'█░░░░░░░' de CELDAS_BLOQUES celdas: lleno = usado (estandar Aider)."""
    llenas = int(round(pct_usado * CELDAS_BLOQUES / 100.0))
    llenas = min(CELDAS_BLOQUES, max(0, llenas))
    return g["lleno"] * llenas + g["vacio"] * (CELDAS_BLOQUES - llenas)


def _sec_ctx(datos, g, con_bloques: bool = False) -> list:
    """'ctx 12.4k/128k (90% libre)': el % cuenta hacia ABAJO (receta Codex,
    'context left') sobre el n_ctx MENOS el headroom. Sin total conocido no se
    inventa porcentaje: 'ctx 12.4k' si hay ocupacion real, 'ctx ?' si no hay
    ni eso (flota apagada). Sin dato cableado (usado y total None) no hay
    seccion. Al nivel de aviso se suma el sufijo '/compactar' (receta
    CodeWhale: High sugiere compactar) y el estilo pasa a amarillo/rojo."""
    usado = _entero(_dato(datos, "ctx_usado"))
    total = _entero(_dato(datos, "ctx_total"))
    # '~' delante del usado cuando la ocupacion es ESTIMADA (chars/4, +-25%):
    # un numero estimado con aspecto de medida es peor que decir que lo es.
    tilde = "~" if _dato(datos, "ctx_estimado") else ""
    if usado is None and total is None:
        return []
    if not total:
        if usado:
            return [("ctx " + tilde + humano(usado), EST_CTX)]
        return [("ctx ?", EST_CTX)]
    nc = nivel_contexto(usado, total)
    estilo = {"critico": EST_CTX_CRITICO, "aviso": EST_CTX_ALTO}.get(
        nc["nivel"], EST_CTX)
    partes = [("ctx {}{}/{} ({}% libre)".format(
        tilde, humano(usado or 0), humano(total), nc["libre"]), estilo)]
    if con_bloques:
        partes.append((" " + _bloques(nc["pct_usado"], g), estilo))
    if nc["nivel"]:
        partes.append((g["sep"], EST_SEP))
        partes.append(("/compactar", estilo))
    return partes


def _sec_tokens(datos) -> list:
    n = _entero(_dato(datos, "tokens_sesion"))
    if not n:
        return []
    return [(humano(n) + " tok", EST_TOKENS)]


def _sec_modo(datos) -> list:
    texto, estilo = indicador_modo(_dato(datos, "modo", ""),
                                  _dato(datos, "permiso", ""))
    return [(texto, estilo)] if texto else []


def _grupos(datos, escalon: str, g, ancho: int = 0) -> tuple:
    """(secciones_izquierda, secciones_derecha) para un escalon de recorte.
    Cada seccion es una lista de fragmentos (texto, estilo) - la rama son dos
    (nombre y '*') porque llevan estilos distintos."""
    i = ESCALONES.index(escalon)
    izq = []
    if i < 5:
        izq.append(_sec_modo(datos))
    izq.append(_sec_modelo(datos, g))
    if i < 6:
        izq.append(_sec_directorio(datos, g, corto=i >= 3))
    if i < 4:
        izq.append(_sec_rama(datos, g))
    # La mini-barra de bloques solo en el escalon completo Y con terminal
    # ancha: en angosto cae ELLA primero (el % del ctx queda siempre).
    con_bloques = (i < 1 and ancho >= _ANCHO_BLOQUES and bloques_activos())
    der = [_sec_ctx(datos, g, con_bloques)]
    if i < 2:
        der.append(_sec_tokens(datos))
    return ([s for s in izq if s], [s for s in der if s])


def _juntar(secciones: list, sep: str) -> list:
    """Intercala el separador entre secciones y aplana a fragmentos."""
    out = []
    for k, sec in enumerate(secciones):
        if k:
            out.append((sep, EST_SEP))
        out.extend(sec)
    return out


def _truncar(partes: list, ancho: int, elip: str) -> list:
    """Ultimo recurso: corta los fragmentos hasta entrar en `ancho`.

    Si ya entra, se devuelve tal cual: la elipsis es la marca de que FALTA
    texto, y ponerla cuando no se corto nada miente y ademas gasta una celda."""
    if sum(_ancho_visual(t) for t, _ in partes) <= ancho:
        return [p for p in partes if p[0]]
    if _ancho_visual(elip) > ancho:
        elip = ""            # ancho ridiculo: ni la elipsis entra
    cupo = max(0, ancho - _ancho_visual(elip))
    out, usado = [], 0
    for texto, estilo in partes:
        w = _ancho_visual(texto)
        if usado + w <= cupo:
            out.append((texto, estilo))
            usado += w
            continue
        resto = cupo - usado
        if resto > 0:
            out.append((_acortar(texto, resto, ""), estilo))
        break
    if elip:
        out.append((elip, EST_SEP))
    return [p for p in out if p[0]]


def barra_estado_partes(datos, ancho: int = 80,
                        unicode_ok: bool | None = None) -> list:
    """La barra como lista de (texto, estilo_logico) - para rich:

        Text.assemble(*barra_estado_partes(datos, console.width))

    El texto concatenado es EXACTAMENTE lo que devuelve barra_estado(), relleno
    incluido, para que la version con color y la plana no se separen nunca."""
    g = _glifos(unicode_ok)
    sep = g["sep"]
    try:
        ancho = int(ancho)
    except (TypeError, ValueError, OverflowError):
        ancho = 80
    ancho = min(_ANCHO_MAX, max(1, ancho))

    ultimo = None
    for escalon in ESCALONES:
        izq_secs, der_secs = _grupos(datos, escalon, g, ancho)
        if not izq_secs and not der_secs:
            # Este escalon ya no muestra NADA. Si algun escalon anterior si
            # tenia contenido, ese es el candidato a truncar en duro; cortar
            # aca con [] borraba datos que entraban (una barra de solo modo
            # desaparecia entera porque 'sin_modo' queda vacio).
            break
        izq = _juntar(izq_secs, sep)
        der = _juntar(der_secs, sep)
        w_izq = sum(_ancho_visual(t) for t, _ in izq)
        w_der = sum(_ancho_visual(t) for t, _ in der)
        # Al menos un espacio separa los dos grupos, pero solo si hay DOS
        # grupos: sin grupo izquierdo no hay nada de lo que separarse, y sin
        # grupo derecho el relleno solo empuja el borde (la linea igual mide
        # `ancho`).
        minimo = 1 if (izq and der) else 0
        relleno = ancho - w_izq - w_der
        ultimo = (izq, der, relleno)
        if relleno >= minimo and ancho >= _ANCHO_MIN:
            partes = list(izq)
            if relleno > 0:
                partes.append((" " * relleno, ""))
            partes.extend(der)
            return [p for p in partes if p[0]]
    if ultimo is None:
        return []            # sin un solo dato no hay barra (ni una de espacios)
    izq, der, _ = ultimo
    # Ni el ultimo escalon entra: se trunca en duro, pero los dos grupos siguen
    # separados por un espacio (pegados, 'qwythos-9bctx 12.4k' es ilegible).
    crudo = [p for p in izq if p[0]]
    if crudo and der:
        crudo.append((" ", ""))
    crudo += [p for p in der if p[0]]
    return _truncar(crudo, ancho, g["elip"])


def barra_estado(datos, ancho: int = 80,
                 unicode_ok: bool | None = None) -> str:
    """La linea COMPLETA de estado, izquierda y derecha ancladas.

    Mide exactamente `ancho` celdas cuando el contenido entra (la derecha queda
    pegada al borde); si no entra en ningun escalon de recorte, sale truncada y
    mide `ancho` o menos. Nunca lanza y nunca se pasa del ancho.
    """
    return "".join(t for t, _ in barra_estado_partes(datos, ancho, unicode_ok))


# ---------------------------------------------------------------------------
# Barra de atajos
# ---------------------------------------------------------------------------
# {F} lo reemplaza el juego de glifos (flechas Unicode o su fallback ASCII).
_ATAJOS = {
    # 'f2 agentes' va ULTIMO (es el primero que se cae cuando la terminal es
    # angosta) pero va: hasta 2026-08-18 la UNICA forma de enterarse de que F2
    # existe era lanzar una corrida, porque el prompt de espera del carril de
    # fondo lo nombra en su marco y esta barra no. F2 abre la vista de agentes
    # SIEMPRE, con corrida o sin ella (sin corrida dice "Sin corrida ·
    # esperando eventos del bus"), asi que en el contexto 'repl' no miente.
    "repl": (("tab", "completa"), ("{F}", "historial"), ("@", "archivo"),
             ("/", "comandos"), ("f2", "agentes")),
    "generando": (("esc", "interrumpe"), ("ctrl+c", "corta")),
    "permiso": (("s", "permite"), ("n", "rechaza"), ("a", "permite siempre"),
                ("esc", "cancela")),
    "selector": (("{F}", "navega"), ("enter", "elige"), ("esc", "cancela")),
}
CONTEXTOS = tuple(_ATAJOS)


def barra_atajos_partes(contexto: str, ancho: int = 0,
                        unicode_ok: bool | None = None) -> list:
    """Los atajos del contexto como (texto, estilo): la TECLA con acento, la
    accion tenue. Contexto desconocido -> [] (mejor nada que mentir).

    `ancho` > 0 recorta por la DERECHA (se caen los atajos menos importantes,
    que estan al final de cada lista) hasta que entra."""
    g = _glifos(unicode_ok)
    pares = _ATAJOS.get(str(contexto or "").strip().lower())
    if not pares:
        return []
    try:
        ancho = int(ancho)
    except (TypeError, ValueError):
        ancho = 0

    def armar(n):
        out = []
        for k, (tecla, accion) in enumerate(pares[:n]):
            if k:
                out.append((g["sep"], EST_SEP))
            out.append((tecla.replace("{F}", g["flechas"]), EST_ATAJO_TECLA))
            out.append((" " + accion, EST_ATAJO_ACCION))
        return out

    partes = armar(len(pares))
    if ancho <= 0:
        return partes
    n = len(pares)
    while n > 1 and sum(_ancho_visual(t) for t, _ in partes) > ancho:
        n -= 1
        partes = armar(n)
    if sum(_ancho_visual(t) for t, _ in partes) > ancho:
        partes = _truncar(partes, ancho, g["elip"])
    return partes


def barra_atajos(contexto: str, ancho: int = 0,
                 unicode_ok: bool | None = None) -> str:
    """'tab completa \u00b7 \u2191\u2193 historial \u00b7 @ archivo \u00b7 / comandos \u00b7 f2 agentes'
    (contexto 'repl').
    Cadena vacia si el contexto no es uno de CONTEXTOS."""
    return "".join(t for t, _ in
                   barra_atajos_partes(contexto, ancho, unicode_ok))


# ---------------------------------------------------------------------------
# Enganche con prompt_toolkit
# ---------------------------------------------------------------------------
def toolbar_prompt_toolkit(proveedor_datos, ancho: int | None = None,
                           contexto_atajos: str = "",
                           unicode_ok: bool | None = None):
    """Devuelve una funcion SIN argumentos apta para:

        session = PromptSession(bottom_toolbar=toolbar_prompt_toolkit(estado))

    prompt_toolkit la llama en cada redibujado, asi que la barra sigue viva
    sin que el REPL tenga que refrescar nada. `proveedor_datos` es un callable
    que devuelve el dict de datos (el CLI es el que sabe el modelo activo y los
    tokens de la sesion).

    TOLERANTE POR CONTRATO: si el proveedor lanza, devuelve algo que no es un
    Mapping, o cualquier cosa falla al armar la barra, devuelve "" - un
    adorno JAMAS puede romper el prompt (misma regla que ux/renderer.py).

    prompt_toolkit NO se importa aca: la funcion devuelve str plano, que es un
    bottom_toolbar valido. Con `contexto_atajos` la barra sale de DOS lineas
    (estado arriba, atajos abajo), como el pie de Crush.
    """
    def _toolbar() -> str:
        try:
            datos = proveedor_datos() if callable(proveedor_datos) else proveedor_datos
            if not hasattr(datos, "get"):
                return ""
            w = ancho
            if not w:
                try:
                    w = shutil.get_terminal_size().columns
                except Exception:
                    w = 80
            w = max(_ANCHO_MIN, int(w))
            linea = barra_estado(datos, w, unicode_ok)
            if contexto_atajos:
                atajos = barra_atajos(contexto_atajos, w, unicode_ok)
                # Sin estado (dict vacio) la barra es "": concatenar igual
                # dejaba una PRIMERA LINEA EN BLANCO en el pie del prompt.
                if atajos:
                    linea = (linea + "\n" + atajos) if linea else atajos
            return linea
        except Exception:
            return ""
    return _toolbar
