# -*- coding: utf-8 -*-
"""
cognia/harness/banner_adaptativo.py
===================================
La DECISION del banner de arranque segun el tamano REAL de la terminal
(2026-08-12).

POR QUE EXISTE
--------------
El arranque de Cognia mide ~45 lineas (banner del gato Braille + logo en
bloques + marco + "Para empezar" + pie). Medido en la captura oficial de
2026-08-12: en una terminal de 30-40 filas el usuario NO llega a ver ni la
guia de "Para empezar" ni el prompt - el saludo se come la pantalla y el
scroll arranca ya perdido. Los CLI punteros (Claude Code, Codex CLI) resuelven
la identidad en 4-6 lineas: mascota/marca + version + modelo + directorio, con
reglas finas en vez de marcos y UN color de acento.

Lo que este modulo NO hace (identidad reclamada por el dueno, intocable):
- No esconde ni sustituye el gato Braille: sigue siendo el default.
- No toca el logo "COGNIA" en bloques ni el titulo "COGNIA vX.Y.Z".
- El texto de la UI sigue en espanol.
Lo que SI corrige es la DENSIDAD y la JERARQUIA: cuanto banner cabe, en que
orden, y que se muestra cuando no cabe todo.

CONTRATO
--------
Todo devuelve DATOS (listas de lineas, tuplas (texto, estilo), dicts) y NADA
imprime. El dibujo del gato vive en cognia/cli.py y no se toca: el integrador
le pasa el arte a este modulo y pinta el resultado con el tema que ya existe.
Los nombres de estilo son LOGICOS ("marca", "acento", "atenuado") y se
traducen a los estilos reales del tema con ``ESTILOS_TEMA`` / ``a_estilo_rich``.

Este modulo a proposito NO importa rich ni prompt_toolkit: al devolver datos
puros no los necesita, asi que degrada limpio por construccion (funciona igual
en un pipe, en un log o en un test). El fichero es ASCII puro: los glifos no
ASCII van como escapes \\uXXXX (leccion Latin-1 del repo: verificar en bytes),
y ademas hay fallback ASCII para consolas de Windows que no los renderizan.
"""
from __future__ import annotations

import os
import shutil
import sys
import unicodedata

# ---------------------------------------------------------------------------
# Umbrales (justificados con la MEDIDA del banner real de cli.py)
# ---------------------------------------------------------------------------
# El banner real ocupa: gato Braille 25 filas + separador punteado 1 + logo en
# bloques 6 + 2 lineas de texto = 34; mas el marco del Panel (2) y la linea de
# modelo/modo/tema (1) = 37. Para que ademas se vean la guia "Para empezar"
# (~10 filas en la columna derecha) y quede aire + prompt (3) hacen falta ~48
# filas: por debajo de eso el prompt nace fuera de pantalla, que es
# exactamente el fallo medido.
FILAS_COMPLETO = 48
# El gato mide ~63 columnas y el logo en bloques ~60; con el marco y el padding
# del Panel, dos columnas (arte + guia) piden ~100, pero apilado el minimo
# honesto para no romper el dibujo es 80.
COLUMNAS_COMPLETO = 80

# MEDIO: gato recortado a su mitad superior (~12 filas) + separador + logo (6)
# + guia (8) + cabecera (4) + aire/prompt (3) ~= 34.
FILAS_MEDIO = 34
# Sin 64 columnas el logo en bloques (60) se parte: por debajo se va a
# compacto, que no dibuja arte.
COLUMNAS_MEDIO = 64

# COMPACTO: cabecera de identidad (4) + guia corta (4) + atajos (1) + aire (2)
# ~= 11; con 20 filas todavia queda historial visible arriba del prompt.
FILAS_COMPACTO = 20
# Por debajo de 30 columnas ni la cabecera de dos columnas cabe: una linea.
COLUMNAS_COMPACTO = 30

# Layout a DOS columnas del banner completo/medio (arte a la izquierda, guia
# "Para empezar" a la derecha). MEDIDO 2026-08-24 sobre la captura del juez:
# a 100 columnas cli.py repartia el grid por RATIO (3:2) y la columna del
# arte quedaba en ~56 para un logo COGNIA de 63 -> cada fila del logo
# envolvia y la 'A' caia sola a la linea siguiente (10 lineas para un logo
# de 5). La regla honesta: dos columnas SOLO si el arte ENTERO y la guia
# ENTERA caben lado a lado; si no, se apila (logo bajo el gato, como a 80).
#   MARCO_PANEL          bordes del Panel (2) + padding (0,1) a cada lado (2)
#   SEPARACION_COLUMNAS  padding (0,2) entre las dos columnas del grid
#   ANCHO_GUIA           la linea mas ancha de la guia real de cli.py (la de
#                        atajos: 'Tab completar  ^v historial  /ayuda todo',
#                        44 columnas). El integrador pasa la medida REAL.
MARCO_PANEL = 4
SEPARACION_COLUMNAS = 2
ANCHO_GUIA = 44

VARIANTES = ("completo", "medio", "compacto", "minimo")

# Aire + linea del prompt que SIEMPRE se reservan al repartir filas.
RESERVA_PROMPT = 3

# Alias tolerados en COGNIA_BANNER. 'min' es el valor LEGACY que hoy usa
# cli.py para el arranque de ~5 lineas: equivale al compacto de aca.
_ALIAS = {
    "min": "compacto", "compact": "compacto", "corto": "compacto",
    "full": "completo", "max": "completo", "largo": "completo",
    "medium": "medio", "half": "medio",
    "mini": "minimo", "none": "minimo", "off": "minimo", "nada": "minimo",
}

# Estilos LOGICOS -> nombres del tema real (cognia/cli.py _THEMES). El
# integrador puede usar este mapa tal cual con rich: console.print(t, style=...)
ESTILOS_TEMA = {
    "marca": "ok",         # bold bright_green: el nombre del producto
    "acento": "mod",       # bold cyan: el dato vivo (modelo, comando)
    "atenuado": "info_dim",  # dim: contexto (directorio, descripciones)
}

# Glifos: version Unicode segura y fallback ASCII para consolas viejas de
# Windows (cp850/cp1252 no tienen ni la elipsis ni las flechas).
GLIFOS = {
    "elipsis": "\u2026",     # elipsis tipografica
    "flechas": "\u2191\u2193",  # flechas del historial
    "regla": "\u2500",       # regla horizontal fina (no marcos)
    "punto": "\u00b7",       # punto medio: el separador de la casa
}
GLIFOS_ASCII = {
    "elipsis": "...",
    "flechas": "^v",
    "regla": "-",
    "punto": "*",
}

# La guia curada de arranque (la misma que hoy vive en el banner de cli.py).
COMANDOS_ARRANQUE = [
    ("chat", "escribe y conversa"),
    ("/hacer", "<tarea> agente autonomo"),
    ("/crear", "<idea> genera un programa"),
    ("/modelo", "elegir modelo o flota"),
    ("/memoria", "estado de memoria"),
    ("/grafo", "<concepto> del saber"),
    ("/tutor", "aprende cualquier tema"),
    ("/doctor", "diagnostico del sistema"),
]

ATAJOS = [("Tab", "completar"), ("{flechas}", "historial"), ("/ayuda", "todo")]


# ---------------------------------------------------------------------------
# Glifos y ancho visible
# ---------------------------------------------------------------------------
def glifos(ascii_seguro=None) -> dict:
    """El juego de glifos a usar. ``ascii_seguro=None`` decide solo: COGNIA_ASCII=1
    fuerza ASCII, y si no, se prueba a codificar los glifos en la codificacion
    real de stdout (una consola cp850 no puede con la elipsis)."""
    if ascii_seguro is None:
        if str(os.environ.get("COGNIA_ASCII", "")).strip().lower() in ("1", "true", "si", "yes"):
            ascii_seguro = True
        else:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            try:
                "".join(GLIFOS.values()).encode(enc)
                ascii_seguro = False
            except Exception:
                ascii_seguro = True
    return dict(GLIFOS_ASCII if ascii_seguro else GLIFOS)


def ancho_visible(texto: str) -> int:
    """Columnas que ocupa el texto en terminal: los CJK/emoji anchos cuentan 2
    y los combinantes 0. len() miente en esos casos y descuadra las columnas."""
    total = 0
    for ch in texto or "":
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def ancho_arte(lineas_arte) -> int:
    """La columna mas ancha del arte (en columnas VISIBLES). 0 sin arte."""
    return max((ancho_visible(str(l)) for l in (lineas_arte or [])),
               default=0)


def cabe_dos_columnas(columnas, ancho_del_arte, ancho_guia=ANCHO_GUIA) -> bool:
    """Si en una terminal de ``columnas`` entran, LADO A LADO y sin envolver
    ni recortar, un arte de ``ancho_del_arte`` y una guia de ``ancho_guia``
    dentro del Panel del banner. Sin arte (0) no hay nada que poner al lado.

    Con el gato real (63) y la guia real (44): 4 + 63 + 2 + 44 = 113. A 100
    columnas devuelve False y el banner se apila; a 120, True.
    """
    try:
        columnas = int(columnas)
        ancho_del_arte = int(ancho_del_arte)
        ancho_guia = int(ancho_guia)
    except Exception:
        return False
    if ancho_del_arte <= 0:
        return False
    return columnas >= (MARCO_PANEL + ancho_del_arte + SEPARACION_COLUMNAS
                        + max(0, ancho_guia))


def _ancho_char(ch: str) -> int:
    """Columnas de UN caracter (0 combinante, 2 ancho, 1 el resto)."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _trozo_por_ancho(texto: str, ancho: int, desde_el_final: bool = False) -> str:
    """El trozo de ``texto`` que ocupa como mucho ``ancho`` columnas VISIBLES.

    Cortar por INDICE no sirve: un solo CJK/emoji ocupa dos columnas, asi que
    ``ruta[:8]`` puede medir 16 y desbordar la linea. Por el final se descartan
    ademas los combinantes que quedarian huerfanos (sin su letra base) al
    principio del trozo: renderizan encima del caracter anterior.
    """
    if ancho <= 0 or not texto:
        return ""
    if desde_el_final:
        out, usado = [], 0
        for ch in reversed(texto):
            w = _ancho_char(ch)
            if usado + w > ancho:
                break
            out.append(ch)
            usado += w
        while out and unicodedata.combining(out[-1]):
            out.pop()
        return "".join(reversed(out))
    out, usado = [], 0
    for ch in texto:
        w = _ancho_char(ch)
        if usado + w > ancho:
            break
        out.append(ch)
        usado += w
    return "".join(out)


def truncar(texto: str, ancho: int, ascii_seguro=None) -> str:
    """Recorta a ``ancho`` columnas VISIBLES, cerrando con elipsis."""
    texto = texto or ""
    ancho = int(ancho)
    if ancho <= 0:
        return ""
    if ancho_visible(texto) <= ancho:
        return texto
    elipsis = glifos(ascii_seguro)["elipsis"]
    tope = ancho - ancho_visible(elipsis)
    if tope <= 0:
        return elipsis[:ancho]
    return _trozo_por_ancho(texto, tope) + elipsis


# ---------------------------------------------------------------------------
# Medida de la terminal
# ---------------------------------------------------------------------------
class Medida(tuple):
    """(columnas, filas) desempaquetable, con la procedencia como atributo.

    Se desempaqueta como la tupla de siempre -``cols, filas = medir_terminal()``-
    y ademas expone ``es_tty`` y ``por_defecto`` para que el caller sepa si la
    medida es REAL o el fallback (arranque redirigido a un pipe/archivo, CI,
    scripts). Marcar el defecto importa: sin TTY no hay que decidir por
    tamano, hay que ir a la variante compacta y no adivinar.
    """

    def __new__(cls, columnas, filas, es_tty=True, por_defecto=False):
        obj = super().__new__(cls, (int(columnas), int(filas)))
        obj.es_tty = bool(es_tty)
        obj.por_defecto = bool(por_defecto)
        return obj

    @property
    def columnas(self) -> int:
        return self[0]

    @property
    def filas(self) -> int:
        return self[1]

    def __repr__(self) -> str:  # pragma: no cover - solo para depurar
        return (f"Medida(columnas={self[0]}, filas={self[1]}, "
                f"es_tty={self.es_tty}, por_defecto={self.por_defecto})")


def medir_terminal(console=None, defecto=(80, 24)) -> Medida:
    """Tamano de la terminal como ``Medida`` (columnas, filas).

    - Si el caller pasa una Console de rich (o cualquier objeto con ``.size``
      o ``.width``/``.height``), esa medida MANDA: es la que rich va a usar
      para pintar, y puede estar fijada por el propio CLI.
    - Si no, shutil.get_terminal_size, que ya respeta COLUMNS/LINES.
    - Tolerante a redireccion: sin TTY (o con una medida absurda: 0 o negativa,
      que algunas terminales reportan) devuelve ``defecto`` y lo MARCA con
      ``por_defecto=True`` / ``es_tty=False``. Nunca lanza.
    """
    cols = filas = 0
    if console is not None:
        try:
            size = getattr(console, "size", None)
            if size is not None:
                cols, filas = int(size[0]), int(size[1])
            else:
                cols = int(getattr(console, "width", 0) or 0)
                filas = int(getattr(console, "height", 0) or 0)
        except Exception:
            cols = filas = 0
    if cols <= 0 or filas <= 0:
        try:
            t = shutil.get_terminal_size(fallback=(int(defecto[0]), int(defecto[1])))
            cols, filas = int(t.columns), int(t.lines)
        except Exception:
            cols, filas = int(defecto[0]), int(defecto[1])
    try:
        es_tty = bool(sys.stdout.isatty())
    except Exception:
        es_tty = False
    if cols <= 0 or filas <= 0:
        cols, filas = int(defecto[0]), int(defecto[1])
    por_defecto = (not es_tty) and console is None
    if por_defecto:
        # Sin TTY la medida no significa nada (un pipe no tiene tamano): se
        # devuelve el defecto explicito para que la decision sea reproducible.
        cols, filas = int(defecto[0]), int(defecto[1])
    return Medida(cols, filas, es_tty=es_tty, por_defecto=por_defecto)


# ---------------------------------------------------------------------------
# Eleccion de variante
# ---------------------------------------------------------------------------
def normalizar_variante(valor: str) -> str:
    """Normaliza un nombre de variante: minusculas, sin acentos y con alias
    ('min' legacy -> 'compacto'). Devuelve "" si no es una variante valida -
    un COGNIA_BANNER con basura NO debe romper el arranque ni forzar nada."""
    v = str(valor or "").strip().lower()
    if not v:
        return ""
    v = "".join(c for c in unicodedata.normalize("NFD", v)
                if not unicodedata.combining(c))
    v = _ALIAS.get(v, v)
    return v if v in VARIANTES else ""


def variante_del_entorno(entorno=None) -> str:
    """COGNIA_BANNER=completo|medio|compacto|minimo (o "" si no aplica)."""
    env = os.environ if entorno is None else entorno
    return normalizar_variante(env.get("COGNIA_BANNER", ""))


def elegir_variante(filas, columnas, forzado: str = "") -> str:
    """Que banner corresponde a una terminal de ``filas`` x ``columnas``.

    Escalera (los umbrales y su medida estan arriba, en las constantes):
      completo  >= 48 filas y >= 80 columnas -> gato entero + logo + guia
      medio     >= 34 filas y >= 64 columnas -> logo + guia, gato a la mitad
      compacto  >= 20 filas y >= 30 columnas -> identidad (3-4) + guia corta
      minimo    por debajo                   -> una sola linea

    ``forzado`` (tipicamente COGNIA_BANNER) MANDA sobre la medida; un valor
    invalido se ignora en vez de romper. Las filas y columnas se evaluan
    JUNTAS: 60 filas en una terminal de 70 columnas dan 'medio', porque el
    problema ahi no es el alto sino que el dibujo no entra a lo ancho.
    """
    forz = normalizar_variante(forzado)
    if forz:
        return forz
    try:
        filas, columnas = int(filas), int(columnas)
    except Exception:
        return "compacto"
    if filas >= FILAS_COMPLETO and columnas >= COLUMNAS_COMPLETO:
        return "completo"
    if filas >= FILAS_MEDIO and columnas >= COLUMNAS_MEDIO:
        return "medio"
    if filas >= FILAS_COMPACTO and columnas >= COLUMNAS_COMPACTO:
        return "compacto"
    return "minimo"


# ---------------------------------------------------------------------------
# Recorte del arte (el dibujo NO se toca: solo se decide que lineas caben)
# ---------------------------------------------------------------------------
def _sin_bordes_en_blanco(lineas: list) -> list:
    """Quita lineas vacias del principio y del final."""
    ini, fin = 0, len(lineas)
    while ini < fin and not lineas[ini].strip():
        ini += 1
    while fin > ini and not lineas[fin - 1].strip():
        fin -= 1
    return lineas[ini:fin]


def recortar_arte(lineas_arte, filas_disponibles: int) -> list:
    """Las lineas del arte que caben en ``filas_disponibles``.

    Recorta por ARRIBA y por ABAJO de forma simetrica (el sobrante impar cae
    abajo) para no descabezar el dibujo: en el gato Braille las filas de los
    extremos son casi todas relleno, y el centro es la cara. El resultado es
    siempre un TRAMO CONTIGUO del original (nunca se saltean lineas del medio,
    que partiria el dibujo) y nunca deja lineas en blanco en los bordes: una
    fila vacia arriba o abajo se ve como banner desalineado y ademas gasta
    presupuesto.

    Devuelve [] si no cabe nada. Nunca devuelve mas de ``filas_disponibles``.
    """
    lineas = [str(l) for l in (lineas_arte or [])]
    try:
        disp = int(filas_disponibles)
    except Exception:
        disp = 0
    if disp <= 0:
        return []
    lineas = _sin_bordes_en_blanco(lineas)
    if not lineas:
        return []
    if len(lineas) <= disp:
        return lineas
    sobra = len(lineas) - disp
    arriba = sobra // 2
    abajo = sobra - arriba
    trozo = lineas[arriba:len(lineas) - abajo]
    # El recorte pudo dejar relleno vacio justo en el borde nuevo.
    return _sin_bordes_en_blanco(trozo)


def partir_arte_y_logo(lineas_arte) -> tuple:
    """(gato, logo): el arte del CLI trae el gato Braille, un separador
    punteado y el logo COGNIA en bloques, todo en un mismo bloque de texto.
    El logo es IDENTIDAD (no se toca): cuando hay que recortar por altura se
    recorta el GATO y el logo queda entero. Antes recortar_arte iba sobre el
    bloque completo y, al ser simetrico, se comia el logo (a 80x40 y, tras
    apilar el layout, tambien a 100x40: cazado 2026-08-24).

    El logo empieza en la primera linea con bloques (U+2588 o los bordes
    U+2550-U+256C); el separador (lineas vacias o de puntos) que lo precede
    va CON el logo, para que el aire entre gato y logo se conserve. Sin
    bloques devuelve (arte entero, [])."""
    lineas = [str(l) for l in (lineas_arte or [])]
    bloques = "\u2588\u2550\u2551\u2554\u2557\u255a\u255d\u2560\u2563\u2566\u2569\u256c"
    ini = None
    for i, l in enumerate(lineas):
        if any(ch in bloques for ch in l):
            ini = i
            break
    if ini is None:
        return lineas, []
    j = ini
    while j > 0 and not lineas[j - 1].strip().replace("\u00b7", "").strip():
        j -= 1
    return lineas[:j], lineas[j:]


def mitad_superior(lineas_arte) -> list:
    """La mitad de ARRIBA del arte, sin bordes en blanco.

    Es lo que pide la variante 'medio': del gato se conserva la cabeza (arriba)
    y se deja caer el cuerpo, en vez del recorte simetrico de recortar_arte.
    """
    lineas = _sin_bordes_en_blanco([str(l) for l in (lineas_arte or [])])
    if not lineas:
        return []
    mitad = max(1, (len(lineas) + 1) // 2)
    return _sin_bordes_en_blanco(lineas[:mitad])


# ---------------------------------------------------------------------------
# Cabecera compacta: la identidad en 3-4 lineas
# ---------------------------------------------------------------------------
def acortar_ruta(directorio: str, ancho: int, ascii_seguro=None) -> str:
    """La ruta como la muestran los CLI punteros: ``~`` por el home y elipsis
    en el MEDIO si no cabe (el final de la ruta -el proyecto- es lo que el
    usuario necesita leer; cortar por el final lo esconderia).

    Conserva el separador nativo: en Windows el usuario espera ver '\\'.
    """
    ruta = str(directorio or "")
    if not ruta:
        return ""
    try:
        home = os.path.expanduser("~")
    except Exception:
        home = ""
    if home and len(home) > 1:
        base = ruta
        if base.lower().startswith(home.lower()):
            resto = base[len(home):]
            if not resto or resto[0] in ("\\", "/"):
                ruta = "~" + resto
    ancho = int(ancho)
    if ancho <= 0 or ancho_visible(ruta) <= ancho:
        return ruta
    elipsis = glifos(ascii_seguro)["elipsis"]
    hueco = ancho - ancho_visible(elipsis)
    if hueco <= 1:
        return truncar(ruta, ancho, ascii_seguro)
    # La cola pesa mas que la cabeza: ahi esta el nombre del proyecto. El corte
    # va por ANCHO VISIBLE, no por indice: con un directorio en CJK/emoji el
    # slice por caracteres media el doble y desbordaba la linea (y con ella el
    # reparto de filas de plan_arranque, que da la cabecera por buena).
    der = (hueco + 1) // 2
    izq = hueco - der
    return (_trozo_por_ancho(ruta, izq) + elipsis +
            _trozo_por_ancho(ruta, der, desde_el_final=True))


def cabecera_compacta(version: str, modelo: str, directorio: str,
                      modo: str = "", ancho: int = 0,
                      ascii_seguro=None) -> list:
    """Las 3-4 lineas de identidad, como lista de tuplas ``(texto, estilo)``.

    Una tupla POR LINEA (el integrador imprime una linea por tupla, en orden):
        [("cognia v4.6.3",                    "marca"),
         ("modelo  qwythos-9b (:8080)",       "acento"),
         ("dir     ~/Desktop/cognia_v2",      "atenuado"),
         ("modo    flota",                    "atenuado")]

    El estilo es LOGICO ("marca" / "acento" / "atenuado"); ESTILOS_TEMA lo
    traduce a los nombres del tema que ya existe en el CLI. Las etiquetas van
    alineadas en columna y ninguna linea excede el ancho: la ruta se acorta con
    ~ y elipsis en el medio. Sin modelo la linea lo dice y baja a 'atenuado' -
    el banner viejo mentia con un modelo que no era el servido.
    """
    if not ancho or int(ancho) <= 0:
        ancho = medir_terminal().columnas
    ancho = max(20, int(ancho))
    ver = str(version or "").strip().lstrip("vV") or "?"
    lineas = [(truncar(f"cognia v{ver}", ancho, ascii_seguro), "marca")]

    etiquetas = ["modelo", "dir"]
    if str(modo or "").strip():
        etiquetas.append("modo")
    pad = max(len(e) for e in etiquetas)
    sangria = pad + 2          # etiqueta + dos espacios de separacion

    mod = str(modelo or "").strip()
    if mod:
        lineas.append((f"{'modelo':<{pad}}  " +
                       truncar(mod, ancho - sangria, ascii_seguro), "acento"))
    else:
        lineas.append((f"{'modelo':<{pad}}  " +
                       truncar("sin backend - arranca: cognia flota arrancar",
                               ancho - sangria, ascii_seguro), "atenuado"))
    lineas.append((f"{'dir':<{pad}}  " +
                   acortar_ruta(directorio, ancho - sangria, ascii_seguro),
                   "atenuado"))
    if str(modo or "").strip():
        lineas.append((f"{'modo':<{pad}}  " +
                       truncar(str(modo).strip(), ancho - sangria, ascii_seguro),
                       "atenuado"))
    return lineas


def linea_identidad(version: str, modelo: str = "", ascii_seguro=None,
                    ancho: int = 0) -> list:
    """La variante 'minimo': UNA linea y nada mas.

    'cognia v4.6.3 . qwythos-9b . /ayuda'. Misma forma de retorno que
    cabecera_compacta (lista de tuplas) para que el integrador no ramifique.
    """
    if not ancho or int(ancho) <= 0:
        ancho = medir_terminal().columnas
    g = glifos(ascii_seguro)
    ver = str(version or "").strip().lstrip("vV") or "?"
    partes = [f"cognia v{ver}"]
    if str(modelo or "").strip():
        partes.append(str(modelo).strip())
    partes.append("/ayuda")
    return [(truncar(f" {g['punto']} ".join(partes), max(20, int(ancho)),
                     ascii_seguro), "marca")]


# ---------------------------------------------------------------------------
# Guia rapida: "Para empezar" en columnas alineadas
# ---------------------------------------------------------------------------
def guia_rapida(comandos=None, ancho: int = 0, maximo: int = 8,
                sangria: int = 2, ascii_seguro=None) -> list:
    """Las entradas de "Para empezar" ya alineadas, como lista de tuplas
    ``(columna_comando, descripcion)``.

    La primera columna viene con la sangria y el relleno YA aplicados, asi el
    integrador solo concatena y pinta: comando en "acento", descripcion en
    "atenuado" (los dos estilos que ya usa el banner de hoy). Las descripciones
    se truncan al ancho REAL de la terminal para que ninguna entrada se
    desborde - el desborde del pie es uno de los defectos medidos.

    ``comandos`` acepta lista de pares o dict {comando: descripcion}; solo con
    ``None`` (o sin argumento) usa COMANDOS_ARRANQUE, las 8 curadas del banner
    actual. No inventa entradas: si le pasan 3 devuelve 3, y si le pasan una
    lista VACIA devuelve [] - una guia vacia es una decision del integrador
    ("aca no va guia"), no una peticion de los defaults.
    """
    if comandos is None:
        comandos = COMANDOS_ARRANQUE
    if isinstance(comandos, dict):
        pares = list(comandos.items())
    else:
        pares = []
        for item in comandos:
            if isinstance(item, (list, tuple)):
                pares.append((str(item[0]), str(item[1]) if len(item) > 1 else ""))
            else:
                pares.append((str(item), ""))
    pares = pares[:max(0, int(maximo))]
    if not pares:
        return []
    if not ancho or int(ancho) <= 0:
        ancho = medir_terminal().columnas
    ancho = max(20, int(ancho))
    sangria = max(0, int(sangria))
    # La columna de comandos no puede comerse mas de la mitad del ancho.
    ancho_cmd = min(max(ancho_visible(c) for c, _ in pares),
                    max(6, ancho // 2 - sangria - 2))
    col = sangria + ancho_cmd + 2          # sangria + comando + separacion
    salida = []
    for cmd, desc in pares:
        cmd_rec = truncar(cmd, ancho_cmd, ascii_seguro)
        relleno = " " * max(0, ancho_cmd - ancho_visible(cmd_rec))
        salida.append((" " * sangria + cmd_rec + relleno + "  ",
                       truncar(desc, max(1, ancho - col), ascii_seguro)))
    return salida


def linea_atajos(ancho: int = 0, ascii_seguro=None) -> tuple:
    """La linea de atajos al pie, estilo barra de estado: una sola tupla
    ``(texto, estilo)`` con 'Tab completar . ^v historial . /ayuda todo'."""
    if not ancho or int(ancho) <= 0:
        ancho = medir_terminal().columnas
    g = glifos(ascii_seguro)
    trozos = [f"{k.format(**g)} {v}" for k, v in ATAJOS]
    return (truncar("  " + f" {g['punto']} ".join(trozos),
                    max(20, int(ancho)), ascii_seguro), "atenuado")


# ---------------------------------------------------------------------------
# Plan completo (lo que el integrador consume de una)
# ---------------------------------------------------------------------------
def plan_arranque(arte=None, version: str = "", modelo: str = "",
                  directorio: str = "", comandos=None, modo: str = "",
                  filas: int = 0, columnas: int = 0, forzado=None,
                  ascii_seguro=None) -> dict:
    """Todo el arranque ya decidido y repartido, sin imprimir nada.

    Devuelve un dict:
        variante   -> "completo" | "medio" | "compacto" | "minimo"
        arte       -> lineas del dibujo que caben ([] en compacto/minimo)
        cabecera   -> [(texto, estilo)]
        guia       -> [(columna_comando, descripcion)]
        atajos     -> (texto, estilo) o None
        filas/columnas, medida_por_defecto, lineas_estimadas

    LAYOUT que el reparto asume (el integrador debe pintar EXACTAMENTE esto,
    o ``lineas_estimadas`` deja de valer):

        <arte>                      len(plan["arte"])
        (linea en blanco)           solo si hay arte
        <cabecera>                  len(plan["cabecera"])
        (linea en blanco)           solo si hay guia
        Para empezar                titulo, solo si hay guia
        <guia>                      len(plan["guia"])
        (linea en blanco)           solo si hay atajos
        <atajos>                    1

    El reparto es el punto del modulo: primero se reservan cabecera, titulo,
    guia, atajos, las lineas EN BLANCO del layout y el aire del prompt
    (RESERVA_PROMPT); lo que SOBRA es el presupuesto del arte. Contar el aire
    no es un detalle: sin contarlo, en 36 filas el banner medio pintaba
    exactamente 36 lineas y el prompt volvia a nacer fuera de pantalla -
    verificado pintando con rich a 60/36/24/14 filas el 2026-08-12.

    ``lineas_estimadas`` es el total REAL que se va a pintar (aire incluido),
    y siempre deja RESERVA_PROMPT filas libres.
    """
    med = None
    if not filas or not columnas:
        med = medir_terminal()
    filas = int(filas) if filas else med.filas
    columnas = int(columnas) if columnas else med.columnas
    if forzado is None:
        forzado = variante_del_entorno()
    variante = elegir_variante(filas, columnas, forzado)

    if variante == "minimo":
        cab = linea_identidad(version, modelo, ascii_seguro, ancho=columnas)
        return {"variante": variante, "arte": [], "cabecera": cab, "guia": [],
                "atajos": None, "filas": filas, "columnas": columnas,
                "medida_por_defecto": bool(med.por_defecto) if med else False,
                "lineas_estimadas": len(cab)}

    cab = cabecera_compacta(version, modelo, directorio, modo,
                            ancho=columnas, ascii_seguro=ascii_seguro)
    # La guia y los atajos tambien se recortan por presupuesto: con una
    # variante FORZADA (COGNIA_BANNER=completo en una terminal chica) el plan
    # tiene que seguir cabiendo, aunque quede en los huesos.
    libre = filas - len(cab) - RESERVA_PROMPT
    atajos = linea_atajos(columnas, ascii_seguro) if libre >= 2 else None
    tope_guia = 4 if variante == "compacto" else 8
    tope_guia = max(0, min(tope_guia, libre - (2 if atajos else 0) - 2))
    guia = guia_rapida(comandos, ancho=columnas, maximo=tope_guia,
                       ascii_seguro=ascii_seguro) if tope_guia else []

    # Todo lo que NO es arte, contando las lineas en blanco del layout:
    #   cabecera + [blanco + titulo] + guia + [blanco] + atajos
    # y el blanco que separa el arte de la cabecera (solo si va a haber arte).
    fijo = len(cab)
    if guia:
        fijo += 2 + len(guia)          # blanco + "Para empezar" + entradas
    if atajos:
        fijo += 2                      # blanco + linea de atajos
    lineas_arte = []
    if variante in ("completo", "medio"):
        fuente = list(arte or [])
        if variante == "medio":
            fuente = mitad_superior(fuente)
        # -1: el blanco que separa el arte de la cabecera.
        lineas_arte = recortar_arte(fuente, filas - fijo - RESERVA_PROMPT - 1)
    total = fijo + (len(lineas_arte) + 1 if lineas_arte else 0)
    return {"variante": variante, "arte": lineas_arte, "cabecera": cab,
            "guia": guia, "atajos": atajos, "filas": filas,
            "columnas": columnas,
            "medida_por_defecto": bool(med.por_defecto) if med else False,
            "lineas_estimadas": total}


def a_estilo_rich(estilo_logico: str) -> str:
    """Traduce un estilo logico al nombre del tema real del CLI ('marca' ->
    'ok'). Un nombre desconocido vuelve tal cual: rich lo resuelve o lo ignora,
    nunca rompe el pintado."""
    return ESTILOS_TEMA.get(str(estilo_logico or "").strip(),
                            str(estilo_logico or ""))
