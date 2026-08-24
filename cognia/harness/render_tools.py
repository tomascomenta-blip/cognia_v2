"""
cognia/harness/render_tools.py -- RENDER de llamadas a herramienta (2026-08-12)
==============================================================================
POR QUE EXISTE: hoy Cognia imprime la actividad del agente como texto suelto
("<punto> Leyendo motor.py") y el RESULTADO de la tool se pierde o se vuelca entero.
El juicio visual de las capturas oficiales (galeria_cli, 2026-08-12) muestra un
patron convergente en Claude Code, Codex CLI y Crush, y Cognia no lo tiene:

    <glifo de estado>  tool(argumentos resumidos)
      |_ <resumen de UNA linea> (ctrl+o para ver todo)

Tres decisiones de diseno que este modulo fija:
 1. El GLIFO lleva el color (verde ok / rojo error / gris en curso) y el texto
    va neutro: un solo punto de color por linea, no una linea entera pintada.
 2. Los argumentos se resumen a UNA linea con elipsis EN EL MEDIO -- el final de
    una ruta ('.../cognia/agent/loop.py') es lo informativo y recortar por la
    derecha lo tira justo a la basura.
 3. El resultado NO se vuelca: se resume a una linea que dice QUE paso
    ("46 lineas", "3 resultados", "+12 -4 lineas", el mensaje de error) con la
    pista de como expandirlo. `resumir_resultado` es la funcion que decide que
    se ve, por eso es publica y esta testeada aparte.

QUE NO TOCA: la identidad de Cognia (gato Braille, logo COGNIA, marco con la
version) no vive aca y no se toca. Esto corrige DENSIDAD y JERARQUIA del flujo
de trabajo, no la marca. La UI sigue en espanol.

CONTRATO: funciones puras que devuelven strings/tuplas. NO imprimen, NO importan
rich, NO lanzan (salvo `estado` invalido, que es error del programador). El
integrador decide con que Console pinta y traduce el 'estilo logico' devuelto
(nombres del tema de cli.py: info_dim / ok_cl / err_cl / pensar / spinner) a su
markup.

FUENTE ASCII A PROPOSITO: el codigo fuente es ASCII puro y los glifos Unicode
van escapados (\\u00b7, \\u25cf, \\u2514, \\u2234, \\u2026), como en
console/diff_render.py -- leccion del repo: editar en Latin-1 corrompe acentos y
en Windows eso se detecta tarde. En tiempo de ejecucion se elige entre Unicode y
ASCII: COGNIA_ASCII=1 fuerza ASCII, COGNIA_ASCII=0 fuerza Unicode, y sin la
variable se decide por la codificacion REAL de stdout (una consola cp1252 o un
pipe no aguantan '\u25cf').

LIMITES DECLARADOS:
 - Es un FORMATEADOR: no sabe de eventos, ni de spinner vivo, ni de ctrl+o. La
   tecla de expansion es un TEXTO (el keybinding lo cablea el integrador).
 - `resumir_resultado` reconoce el formato REAL de agent/tools.py
   ("RESULTADO <tool> <obj>: <cuerpo>", "... ERROR: <msg>", buscar separando por
   ' | '). Una tool que invente otro formato cae al caso generico (primera linea
   util), nunca a vacio.
 - El ancho se mide en columnas VISUALES (east_asian_width), no en bytes; los
   cortes caen entre code points, asi que nunca parten un caracter.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

# Ancho comodo de linea (mismo tope que ux/estilo.ANCHO_MAX: la prosa de Cognia
# no se estira a toda la terminal).
ANCHO_MAX = 100
# Presupuesto por defecto para los argumentos dentro de 'tool(...)'.
ANCHO_ARGS = 56
SANGRIA = "  "

ESTADOS = ("curso", "ok", "error")

# Glifos: tres puntos seguros. El punto medio (U+00B7) para 'en curso' es el que
# ya usa ux/estilo.py; el circulo lleno (U+25CF) para terminado, y el COLOR
# distingue ok de error (igual que Claude Code). En ASCII el color puede no
# existir, asi que ahi si cambia la forma: o / + / x.
_GLIFOS_UNICODE = {"curso": "\u00b7", "ok": "\u25cf", "error": "\u25cf"}
_GLIFOS_ASCII = {"curso": "o", "ok": "+", "error": "x"}

# Estilos LOGICOS: nombres del tema de cognia/cli.py (_THEMES). Este modulo no
# elige colores concretos; nombra roles que el tema ya define.
ESTILOS_ESTADO = {"curso": "info_dim", "ok": "ok_cl", "error": "err_cl"}
ESTILO_RESULTADO = "info_dim"
ESTILO_RAZONAMIENTO = "pensar"
ESTILO_PROGRESO = "spinner"

_CONECTOR_UNICODE = "\u2514"        # esquina inferior izquierda
_CONECTOR_ASCII = "|_"
# El conector COLGANTE del resultado (\u23bf), el idioma de Claude Code/Codex:
# distinto del \u2514 historico a proposito -- la sublinea de resultado y la
# linea de colapso comparten glifo y se leen como un mismo bloque colgando.
_COLGANTE_UNICODE = "\u23bf"
_COLGANTE_ASCII = "|_"
_ELIPSIS_UNICODE = "\u2026"         # puntos suspensivos
_ELIPSIS_ASCII = "..."
_PENSAR_UNICODE = "\u2234"          # 'therefore', la marca del razonamiento
_PENSAR_ASCII = "*"
# "penso" sin acento en ASCII: el acento es lo primero que revienta
# en una consola cp437/ascii.
_PENSO_UNICODE = "pens" + chr(0xf3)   # "penso" con tilde, sin byte no-ASCII
_PENSO_ASCII = "penso"
_SEP_UNICODE = " \u00b7 "           # separador de atajos, como en Crush
_SEP_ASCII = " | "

PISTA_VER_TODO = "(ctrl+o para ver todo)"
# La pista del bloque colapsado: un COMANDO, no un keybinding -- /expandir
# existe en el REPL y reimprime el output crudo (patron 'raw view' de Codex).
PISTA_EXPANDIR = "/expandir"
PISTA_VER_RAZONAMIENTO = "(ctrl+o para ver el razonamiento)"
PISTA_OCULTAR_RAZONAMIENTO = "(ctrl+o para ocultar el razonamiento)"

# -- Familias de tools --------------------------------------------------------
# Los nombres salen del registry REAL (cognia/agent/tools.py); una tool que no
# este aca cae al resumen generico, nunca a un resumen mentiroso.
# Lecturas de CONTENIDO -> "N lineas".
TOOLS_LECTURA = {
    "leer_archivo", "repo_map", "code_grafo", "docs_repo", "docs_libreria",
    "preguntar_repo", "git_diff", "repo_a_prompt", "cuaderno",
}
# Listados -> "N entradas": contar las lineas de un 'listar' y llamarlas
# "lineas" miente sobre lo que se ve; son archivos, commits o cambios.
TOOLS_LISTADO = {"listar", "arbol", "git_estado", "git_log"}
# OJO: 'contar_lineas' NO es una lectura de contenido -- su resultado YA es la
# frase resumen ("660 lineas"). Contarle las lineas al resumen daba "1 linea"
# sobre un archivo de 660 (cazado en la verificacion e2e con tools reales,
# 2026-08-12). Cae al caso generico, que devuelve esa frase tal cual.
TOOLS_BUSQUEDA = {
    "buscar", "buscar_en_repo", "web_buscar", "kg_buscar", "recordar",
    "bitacora_buscar", "notas",
}
TOOLS_ESCRITURA = {
    "escribir_archivo", "editar_archivo", "apendar_archivo", "copiar_archivo",
    "borrar_archivo",
}
TOOLS_EJECUCION = {"ejecutar", "tests", "py_validar", "json_validar", "abrir"}

# Tools cuyos args son un COMANDO: no se parte por '|' (un pipe de shell es
# parte del comando) y se muestra solo la primera linea, jamas el cuerpo.
_ARGS_COMANDO = {"ejecutar", "tests"}
# Claves que nombran la ruta en unos args tipados: con un dict el ORDEN no es
# el del contrato ({'contenido': ..., 'path': ...} es igual de valido), asi que
# la ruta se busca por nombre antes que por posicion.
_CLAVES_RUTA = {"path", "ruta", "archivo", "fichero", "file", "destino", "dst"}
# Tools cuyo segundo arg es un PAYLOAD (contenido de archivo, bloques
# SEARCH/REPLACE, codigo): se muestra solo el primer argumento, la ruta.
_ARGS_SOLO_PRIMERO = {
    "escribir_archivo", "editar_archivo", "apendar_archivo", "generar_codigo",
    "crear_herramienta", "memorizar", "anotar", "kg_agregar",
}

# 'RESULTADO <tool> <objeto>: <cuerpo>' -- el ':' se busca seguido de espacio
# para no cortar en 'C:/ruta'. Tambien vale el ':' a FIN DE LINEA: 'arbol',
# 'code_grafo', 'recordar' y 'cuaderno consultar' abren con 'RESULTADO x:\n' y
# si ahi no se quita el prefijo, la cabecera se cuenta como una entrada mas
# (un arbol de 2 archivos se resumia como '3 entradas').
_RX_PREFIJO = re.compile(r"^RESULTADO\s+\S+[^\n]*?:(?=[ \t]|\n|$)")
_RX_SEPARADOR = re.compile(r"^[\s=_~*#\-]+$")
_RX_CHARS = re.compile(r"\((\d+)\s+chars\)")
# Una ruta: tiene separador de directorio, o es un 'nombre.ext' reconocible.
_RX_NOMBRE_EXT = re.compile(r"^[\w.\-]+\.[A-Za-z0-9]{1,8}$")


# ---------------------------------------------------------------------------
# Capacidades de la consola
# ---------------------------------------------------------------------------

def _soporta_unicode(s: str) -> bool:
    """Si la consola actual puede codificar `s`. Se decide a call-time: misma
    regla que harness/contexto_vivo.py (los pipes y las cp1252 de Windows no
    aguantan los glifos)."""
    enc = getattr(sys.stdout, "encoding", None) or ""
    try:
        s.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError, TypeError, AttributeError):
        return False


def usar_ascii() -> bool:
    """True si hay que pintar con glifos ASCII.

    COGNIA_ASCII manda: '1'/'true'/'si' fuerza ASCII, '0'/'false'/'no' fuerza
    Unicode (util para tests y para terminales modernas mal detectadas). Sin la
    variable, decide la codificacion real de stdout.
    """
    v = (os.environ.get("COGNIA_ASCII") or "").strip().lower()
    if v in ("1", "true", "si", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return not _soporta_unicode(_ELIPSIS_UNICODE + _CONECTOR_UNICODE
                                + _COLGANTE_UNICODE + _PENSAR_UNICODE
                                + "\u25cf")


def _elipsis() -> str:
    return _ELIPSIS_ASCII if usar_ascii() else _ELIPSIS_UNICODE


def conector() -> str:
    """El conector de la sublinea colgante: '\u2514' o su fallback '|_'."""
    return _CONECTOR_ASCII if usar_ascii() else _CONECTOR_UNICODE


def conector_colgante() -> str:
    """El conector del bloque de resultado colapsado: '\u23bf' o '|_'."""
    return _COLGANTE_ASCII if usar_ascii() else _COLGANTE_UNICODE


def glifo_estado(estado: str) -> str:
    """El glifo del estado ('curso' | 'ok' | 'error'), ya en el juego correcto."""
    est = _validar_estado(estado)
    tabla = _GLIFOS_ASCII if usar_ascii() else _GLIFOS_UNICODE
    return tabla[est]


def estilo_estado(estado: str) -> str:
    """El estilo LOGICO del estado (nombre del tema, no un color)."""
    return ESTILOS_ESTADO[_validar_estado(estado)]


def _validar_estado(estado: str) -> str:
    est = (estado or "").strip().lower()
    if est not in ESTADOS:
        raise ValueError(f"estado invalido: {estado!r} (usa {ESTADOS})")
    return est


# ---------------------------------------------------------------------------
# Ancho visual y recorte
# ---------------------------------------------------------------------------

def ancho_visual(texto: str) -> int:
    """Columnas que ocupa `texto` en terminal: los ideogramas y el ancho
    'Fullwidth' cuentan 2, los combinantes 0, el resto 1."""
    total = 0
    for ch in texto or "":
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _tomar_izq(texto: str, ancho: int) -> str:
    """Prefijo de `texto` que cabe en `ancho` columnas (corta entre caracteres)."""
    out, usado = [], 0
    for ch in texto:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if usado + w > ancho:
            break
        out.append(ch)
        usado += w
    return "".join(out)


def _tomar_der(texto: str, ancho: int) -> str:
    """Sufijo de `texto` que cabe en `ancho` columnas."""
    out, usado = [], 0
    for ch in reversed(texto):
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if usado + w > ancho:
            break
        out.append(ch)
        usado += w
    return "".join(reversed(out))


def truncar_medio(texto: str, ancho: int) -> str:
    """Recorta a `ancho` columnas poniendo la elipsis EN EL MEDIO.

    El final se conserva a proposito (y con un caracter mas que el principio
    cuando la cuenta es impar): en una ruta, un comando o un mensaje de error,
    la cola es lo que identifica de que se habla.
    """
    texto = _una_linea(texto)
    if ancho <= 0:
        return ""
    if ancho_visual(texto) <= ancho:
        return texto
    ell = _elipsis()
    resto = ancho - ancho_visual(ell)
    if resto < 2:
        # No queda sitio para elipsis + al menos una columna de cada lado: un
        # 'X<elipsis>' o '<elipsis>X' no informa, asi que se recorta en seco.
        return _tomar_izq(texto, ancho)
    cola = (resto + 1) // 2          # la cola se queda con el sobrante
    cabeza = resto - cola
    return _tomar_izq(texto, cabeza) + ell + _tomar_der(texto, cola)


def _una_linea(texto: str) -> str:
    """Colapsa saltos y espacios repetidos: todo lo que sale de aca es 1 linea."""
    return re.sub(r"\s+", " ", (texto or "").replace("\r", " ")).strip()


# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

def _parece_ruta(token: str) -> bool:
    t = token.strip().strip("\"'")
    if not t:
        return False
    if "/" in t or "\\" in t:
        return True
    return bool(_RX_NOMBRE_EXT.match(t))


def _relativizar(token: str, raiz: str) -> str:
    """Ruta relativa a `raiz` si esta debajo; si no, la ruta con '/' normalizado.

    Las rutas absolutas del repo son largas y todas comparten el mismo prefijo:
    mostrarlo entero gasta el ancho en lo unico que el usuario ya sabe.
    """
    t = token.strip().strip("\"'")
    if not _parece_ruta(t):
        return token
    try:
        p = os.path.normpath(t)
        r = os.path.normpath(raiz or os.getcwd())
        if os.path.isabs(p):
            comun = os.path.commonpath([p, r])
            if os.path.normcase(comun) == os.path.normcase(r):
                rel = os.path.relpath(p, r)
                return rel.replace("\\", "/")
    except (ValueError, OSError, TypeError):
        pass
    return t.replace("\\", "/")


def _relativizar_parte(parte: str, raiz: str) -> str:
    """Relativiza la parte entera si es una ruta; si no, token a token."""
    entera = _relativizar(parte, raiz)
    if entera != parte:
        return entera
    return " ".join(_relativizar(tok, raiz) for tok in parte.split(" "))


def _entrecomillar(parte: str) -> str:
    """Comillas si hay espacios (y no las tenia ya): sin ellas, 'buscar class
    Foo | cognia' se lee como tres argumentos y no como un patron y un ambito."""
    if not parte or " " not in parte:
        return parte
    if len(parte) > 1 and parte[0] == parte[-1] and parte[0] in "\"'":
        return parte
    return '"' + parte + '"'


def _primera_linea(texto: str) -> str:
    """La primera linea de un valor multilinea, marcada con elipsis si hay mas."""
    lineas = (texto or "").splitlines()
    if not lineas:
        return ""
    cabeza = lineas[0].strip()
    if len(lineas) > 1 and any(l.strip() for l in lineas[1:]):
        return cabeza + _elipsis()
    return cabeza


def _partes_args(tool: str, args) -> list:
    """Normaliza los args a una lista de partes de UNA linea.

    Acepta lo que hay hoy en el repo (el string 'a | b' de agent/tools.py) y lo
    que traeria un harness con tool-calls tipadas (dict o lista).
    """
    if args is None:
        return []
    if isinstance(args, dict):
        pares = [(k, v) for k, v in args.items()
                 if v is not None and str(v).strip() != ""]
        if len(pares) == 1:
            return [_primera_linea(str(pares[0][1]))]
        return [f"{k}={_primera_linea(str(v))}" for k, v in pares]
    if isinstance(args, (list, tuple)):
        return [_primera_linea(str(x)) for x in args if str(x).strip()]
    texto = str(args)
    if tool in _ARGS_COMANDO:
        # Un comando de shell puede llevar '|': no se parte.
        return [_primera_linea(texto)] if texto.strip() else []
    return [_primera_linea(p) for p in texto.split("|") if p.strip()]


def _solo_la_ruta(partes: list) -> str:
    """De las partes de una escritura, la que es la RUTA (sin su clave).

    No se puede confiar en la POSICION: con args tipados el payload puede venir
    primero ({'contenido': ..., 'path': ...}) y entonces mostrar `partes[0]`
    volcaba el contenido en pantalla, justo lo que este modulo promete no hacer.
    Se busca por nombre de clave, luego por forma de ruta, y solo al final se
    cae en la primera parte (el caso del string 'ruta | payload' de tools.py).
    """
    sin_clave = [re.sub(r"^\w+=", "", p) for p in partes]
    for parte, valor in zip(partes, sin_clave):
        clave = parte[:len(parte) - len(valor)].rstrip("=").lower()
        if clave in _CLAVES_RUTA:
            return valor
    for valor in sin_clave:
        if _parece_ruta(valor):
            return valor
    return sin_clave[0]


def resumir_args(tool: str, args, ancho: int = ANCHO_ARGS,
                 raiz: str = "") -> str:
    """Los argumentos de una llamada, en UNA linea legible y acotada.

    Reglas: rutas relativas si estan bajo `raiz` (por defecto el cwd), comillas
    para lo que lleva espacios, elipsis EN EL MEDIO, y para las tools de comando
    ('ejecutar', 'tests') solo el comando -- nunca el cuerpo de un heredoc ni el
    payload de una escritura.
    """
    tool = (tool or "").strip()
    partes = _partes_args(tool, args)
    if not partes:
        return ""
    if tool in _ARGS_COMANDO:
        return truncar_medio(partes[0], ancho)
    if tool in _ARGS_SOLO_PRIMERO:
        # Solo la ruta; con args tipados se cae la clave ('path=x' -> 'x'):
        # el nombre del parametro no aporta nada que el nombre de la tool no
        # diga ya.
        partes = [_solo_la_ruta(partes)]
    raiz = raiz or os.getcwd()
    piezas = [_entrecomillar(_relativizar_parte(p, raiz)) for p in partes]
    return truncar_medio(", ".join(x for x in piezas if x), ancho)


def linea_llamada(tool: str, args="", estado: str = "curso",
                  ancho: int = ANCHO_MAX, raiz: str = "") -> tuple:
    """La linea de una llamada a herramienta.

    Devuelve `(glifo, texto, estilo_logico)`: el glifo es lo UNICO que lleva
    color (por eso el estilo devuelto es el suyo) y el texto es
    'tool(args_resumidos)'. El conjunto '<glifo> <texto>' cabe en `ancho`.
    """
    est = _validar_estado(estado)
    nombre = (tool or "").strip() or "tool"
    glifo = glifo_estado(est)
    # Presupuesto de los args: el ancho menos glifo, espacio, nombre y '()'.
    fijo = ancho_visual(glifo) + 1 + ancho_visual(nombre) + 2
    resumen = resumir_args(nombre, args, max(0, ancho - fijo), raiz)
    texto = f"{nombre}({resumen})"
    # El presupuesto del TEXTO es el ancho menos el glifo y su espacio: medir
    # aca contra `ancho` a secas dejaba la linea pintada 2 columnas mas ancha
    # de lo pedido cuando el nombre solo ya no cabia (el caso del nombre
    # absurdamente largo, el unico que llega hasta aca).
    disponible = ancho - ancho_visual(glifo) - 1
    if ancho_visual(texto) > disponible:
        texto = truncar_medio(texto, max(0, disponible))
    return glifo, texto, estilo_estado(est)


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

def _sin_prefijo(texto: str) -> str:
    """Quita el 'RESULTADO <tool> <objeto>: ' que antepone agent/tools.py."""
    t = (texto or "").lstrip()
    m = _RX_PREFIJO.match(t)
    return t[m.end():].lstrip() if m else t


def es_error(texto: str) -> bool:
    """Si el RESULTADO es un fallo. Mira solo la cabeza: un 'ERROR' a mitad de
    un volcado de logs no convierte en fallo una lectura que salio bien."""
    cabeza = (texto or "")[:200]
    if re.search(r"RESULTADO\s+\S+[^\n]{0,80}?\bERROR\b", cabeza):
        return True
    if re.match(r"\s*(ERROR|Error|Traceback)\b", cabeza):
        return True
    return bool(re.search(r"\(exit [1-9]\d*\)", cabeza))


def _mensaje_error(texto: str) -> str:
    """El mensaje de un error, RECORTADO pero jamas vacio."""
    cuerpo = (texto or "")
    m = re.search(r"\bERROR\b\s*:?\s*(.*)", cuerpo, re.DOTALL)
    if m and m.group(1).strip():
        msg = m.group(1)
    else:
        msg = _sin_prefijo(cuerpo)
    # Traceback: la ULTIMA linea es la excepcion, que es la que informa.
    lineas = [l.strip() for l in msg.splitlines() if l.strip()]
    if lineas and lineas[0].startswith("Traceback"):
        return lineas[-1]
    for l in lineas:
        if not _RX_SEPARADOR.match(l):
            return l
    return "fallo sin mensaje"


def _primera_util(texto: str) -> str:
    """La primera linea con informacion: ni vacia ni una regla de separacion."""
    for l in (texto or "").splitlines():
        s = l.strip()
        if s and not _RX_SEPARADOR.match(s):
            return s
    return ""


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _contar_diff(texto: str) -> tuple:
    """(agregadas, quitadas) de un unified diff embebido; (0, 0) si no hay."""
    mas = menos = 0
    for l in (texto or "").splitlines():
        if l.startswith("+++") or l.startswith("---"):
            continue
        if l.startswith("+"):
            mas += 1
        elif l.startswith("-"):
            menos += 1
    return mas, menos


def resumir_resultado(tool: str, texto: str) -> str:
    """QUE se ve de un resultado: UNA linea, nunca vacia.

    - lecturas   -> 'N lineas'
    - busquedas  -> 'N resultados' (o 'sin resultados')
    - escrituras -> '+A -B lineas' si el resultado trae el diff; si no, lo que
                    la tool declaro (chars escritos)
    - ejecucion  -> la primera linea util de la salida
    - errores    -> el mensaje de error recortado, JAMAS vacio

    Es la funcion que decide la jerarquia de la pantalla, por eso es publica:
    un resumen mentiroso es peor que no resumir (un vacio silencioso hace
    concluir en falso, leccion del repo).
    """
    tool = (tool or "").strip()
    bruto = texto if texto is not None else ""
    if es_error(bruto):
        return truncar_medio(_mensaje_error(bruto), 120)
    cuerpo = _sin_prefijo(bruto)
    if not cuerpo.strip():
        return "sin salida"

    if tool in TOOLS_BUSQUEDA:
        return _resumen_busqueda(cuerpo)
    if tool in TOOLS_ESCRITURA:
        return _resumen_escritura(cuerpo)
    if tool in TOOLS_LECTURA:
        return _resumen_lectura(cuerpo)
    if tool in TOOLS_LISTADO:
        return _resumen_listado(cuerpo)
    if tool in TOOLS_EJECUCION:
        return truncar_medio(_primera_util(cuerpo) or "sin salida", 120)
    # Tool desconocida: la primera linea util, que nunca miente.
    return truncar_medio(_primera_util(cuerpo) or _una_linea(cuerpo)
                         or "sin salida", 120)


def _resumen_lectura(cuerpo: str) -> str:
    # El marcador de archivo vacio se busca al PRINCIPIO: buscarlo en cualquier
    # parte hacia que leer un fuente que MENCIONA '(archivo vacio)' se
    # resumiera como archivo vacio (cazado leyendo este mismo modulo con la
    # tool real, 2026-08-12). El contenido no puede dictar el veredicto.
    if cuerpo.lstrip().startswith("(archivo vacio)"):
        return "archivo vacio"
    lineas = [l for l in cuerpo.splitlines()]
    # El marcador de truncado que agrega leer_archivo no es contenido leido.
    lineas = [l for l in lineas if not l.lstrip().startswith("... [TRUNCADO")]
    n = len(lineas) if lineas else 0
    if n == 0:
        return "sin contenido"
    return _plural(n, "linea", "lineas")


def _resumen_listado(cuerpo: str) -> str:
    """Un listado se cuenta en ENTRADAS (archivos, commits, cambios)."""
    filas = [l for l in cuerpo.splitlines()
             if l.strip() and not _RX_SEPARADOR.match(l.strip())]
    if not filas:
        return "sin entradas"
    return _plural(len(filas), "entrada", "entradas")


def _resumen_busqueda(cuerpo: str) -> str:
    bajo = cuerpo.lower()
    if ("sin coincidencias" in bajo or "sin resultados" in bajo
            or bajo.startswith("nada en los archivos")):
        return "sin resultados"
    # 'buscar' devuelve los hits en UNA linea separados por ' | '; el resto de
    # las busquedas devuelve una linea por hit.
    if " | " in cuerpo and "\n" not in cuerpo.strip():
        piezas = [p for p in cuerpo.split(" | ") if p.strip()]
    else:
        piezas = [l for l in cuerpo.splitlines()
                  if l.strip() and not _RX_SEPARADOR.match(l.strip())]
    n = len(piezas)
    if n == 0:
        return "sin resultados"
    return _plural(n, "resultado", "resultados")


def _resumen_escritura(cuerpo: str) -> str:
    mas, menos = _contar_diff(cuerpo)
    if mas or menos:
        return f"+{mas} -{menos} lineas"
    if "sin cambios" in cuerpo.lower():
        return "sin cambios"
    m = _RX_CHARS.search(cuerpo)
    if m:
        return f"{m.group(1)} chars escritos"
    return truncar_medio(_primera_util(cuerpo) or "escrito", 120)


def linea_resultado(texto_resultado: str, ancho: int = ANCHO_MAX,
                    expandible: bool = True, tool: str = "") -> str:
    """La sublinea colgante del resultado:

        '  \u2514 46 lineas (ctrl+o para ver todo)'   ('  |_ ...' en ASCII)

    `tool` decide el tipo de resumen (ver `resumir_resultado`); sin tool se usa
    el resumen generico. Si la pista no cabe en `ancho`, se cae la PISTA, nunca
    el resumen: el resumen es la informacion, la pista es la comodidad.
    """
    resumen = resumir_resultado(tool, texto_resultado)
    prefijo = SANGRIA + conector() + " "
    pista = PISTA_VER_TODO if expandible else ""
    libre = ancho - ancho_visual(prefijo)
    if libre <= 0:
        return prefijo.rstrip()
    if pista:
        hueco = libre - ancho_visual(pista) - 1
        if hueco >= 8:
            return prefijo + truncar_medio(resumen, hueco) + " " + pista
    return prefijo + truncar_medio(resumen, libre)


# ---------------------------------------------------------------------------
# Razonamiento y progreso
# ---------------------------------------------------------------------------

def _fmt_segundos(segundos) -> str:
    try:
        s = float(segundos)
    except (TypeError, ValueError):
        s = 0.0
    if s < 0:
        s = 0.0
    if s < 10:
        # Bajo 10s el decimal informa (0.4s vs 4s); un entero se muestra entero.
        return f"{s:.0f}s" if abs(s - round(s)) < 0.05 else f"{s:.1f}s"
    if round(s) < 60:
        # Se compara el valor YA REDONDEADO: con 's < 60' un 59,6 se pintaba
        # como '60s', un reloj que nunca marca el minuto.
        return f"{s:.0f}s"
    m, r = divmod(int(round(s)), 60)
    return f"{m}m {r}s" if r else f"{m}m"


def linea_razonamiento(segundos, visible: bool = False,
                       ancho: int = ANCHO_MAX) -> str:
    """El razonamiento PLEGADO en su propia linea:

        '\u2234 penso 4s (ctrl+o para ver el razonamiento)'

    Con `visible=True` la pista invita a ocultarlo. En modo ASCII el verbo
    pierde la tilde ('penso'): el acento es lo primero que revienta en una
    consola cp437, y una mojibake en la UI es peor que una tilde de menos.
    """
    marca = _PENSAR_ASCII if usar_ascii() else _PENSAR_UNICODE
    pista = PISTA_OCULTAR_RAZONAMIENTO if visible else PISTA_VER_RAZONAMIENTO
    penso = _PENSO_ASCII if usar_ascii() else _PENSO_UNICODE
    base = f"{marca} {penso} {_fmt_segundos(segundos)}"
    if ancho_visual(base + " " + pista) <= ancho:
        return base + " " + pista
    return truncar_medio(base, ancho)


def linea_progreso(gerundio: str, atajos=("esc para interrumpir",),
                   siguiente: str = "", ancho: int = ANCHO_MAX) -> tuple:
    """La linea del spinner y, si la hay, su sublinea 'Siguiente: ...'.

        ('\u00b7 Pensando\u2026 (esc para interrumpir)', '  \u2514 Siguiente: correr los tests')

    Devuelve SIEMPRE una tupla (1 o 2 lineas), asi el caller no ramifica.
    """
    marca = glifo_estado("curso")
    verbo = _una_linea(gerundio) or "Trabajando"
    linea = f"{marca} {verbo}{_elipsis()}"
    lista = [a for a in (atajos or ()) if str(a).strip()]
    if lista:
        sep = _SEP_ASCII if usar_ascii() else _SEP_UNICODE
        cola = "(" + sep.join(_una_linea(str(a)) for a in lista) + ")"
        if ancho_visual(linea + " " + cola) <= ancho:
            linea = linea + " " + cola
    else:
        linea = truncar_medio(linea, ancho)
    if ancho_visual(linea) > ancho:
        linea = truncar_medio(linea, ancho)
    sig = _una_linea(siguiente)
    if not sig:
        return (linea,)
    prefijo = SANGRIA + conector() + " Siguiente: "
    libre = max(0, ancho - ancho_visual(prefijo))
    return (linea, prefijo + truncar_medio(sig, libre))


# ---------------------------------------------------------------------------
# Comodidad para el integrador
# ---------------------------------------------------------------------------

def con_estilo(texto: str, estilo: str) -> str:
    """El texto envuelto en markup de rich ('[info_dim]...[/info_dim]').

    Los corchetes del contenido se escapan para que una ruta con '[' no se
    coma el resto de la linea. Sin estilo devuelve el texto tal cual.
    """
    plano = (texto or "").replace("[", "\\[")
    if not estilo:
        return plano
    return f"[{estilo}]{plano}[/{estilo}]"


def bloque_llamada(tool: str, args="", estado: str = "ok",
                   resultado: str = "", ancho: int = ANCHO_MAX,
                   expandible: bool = True, raiz: str = "") -> tuple:
    """Las dos lineas juntas (llamada + resultado colgante), ya como texto.

    Atajo para el caso comun; devuelve `(lineas, estilos)` en paralelo para que
    el integrador pinte cada una con su estilo logico.
    """
    glifo, texto, estilo = linea_llamada(tool, args, estado, ancho, raiz)
    lineas = [f"{glifo} {texto}"]
    estilos = [estilo]
    if resultado:
        lineas.append(linea_resultado(resultado, ancho, expandible, tool))
        estilos.append(ESTILO_RESULTADO)
    return tuple(lineas), tuple(estilos)


def bloque_colapsado(tool: str, args="", ok: bool = True, resultado: str = "",
                     max_lineas: int = 3, ancho: int = ANCHO_MAX,
                     raiz: str = "", indice: int = 0) -> tuple:
    """El bloque estilo Claude Code: vineta de estado + resultado COLAPSADO.

        <glifo> leer_archivo(cognia/cli.py)
          <colgante> 200 lineas                  <- resumen de UNA linea
            primera linea del cuerpo
            segunda
            tercera
          <colgante> ... +197 lineas (/expandir) <- solo si quedo cuerpo oculto

    (<glifo> es el circulo U+25CF con el color del estado; <colgante> es
    U+23BF, el mismo que usa Claude Code, gris.) Devuelve `(lineas, estilos)` en paralelo, como `bloque_llamada`. El cuerpo
    son las primeras `max_lineas` lineas del resultado SIN el prefijo
    'RESULTADO tool obj:'; la linea de colapso dice cuantas quedan y como
    verlas (`indice` > 0 la vuelve '/expandir N', el enesimo tool del turno).
    Con `max_lineas=0` no se muestra cuerpo, solo el resumen y el colapso.
    """
    est = "ok" if ok else "error"
    glifo, texto, estilo = linea_llamada(tool, args, est, ancho, raiz)
    lineas = [f"{glifo} {texto}"]
    estilos = [estilo]
    resumen = resumir_resultado(tool, resultado)
    prefijo = SANGRIA + conector_colgante() + " "
    libre = max(0, ancho - ancho_visual(prefijo))
    lineas.append(prefijo + truncar_medio(resumen, libre))
    # El resumen de un fallo se pinta como fallo: la degradacion silenciosa
    # es el enemigo, y un error en gris se lee como un dato mas.
    estilos.append(ESTILO_RESULTADO if ok else ESTILOS_ESTADO["error"])
    cuerpo = _sin_prefijo(resultado or "")
    filas = cuerpo.splitlines() if cuerpo.strip() else []
    if max_lineas is None or max_lineas < 0:
        max_lineas = 0
    vistas = filas[:max_lineas]
    # La primera linea del cuerpo igual al resumen no se repite (el caso de
    # 'ejecutar', cuyo resumen ES la primera linea util) -- y lo deduplicado
    # NO se cuenta como oculto: un '... +1 linea' que /expandir no agranda es
    # un resumen mentiroso (cazado TECLEANDO en el REPL real, 2026-08-23:
    # 'ejecutar(ls tests | wc -l)' pintaba '643' y debajo '+1 linea').
    ya_visto = 0
    if vistas and max_lineas > 0 and _una_linea(vistas[0]) == resumen:
        ya_visto = 1
        vistas = filas[1:1 + max_lineas]
    sangria_cuerpo = SANGRIA + " " * ancho_visual(conector_colgante() + " ")
    hueco = max(0, ancho - ancho_visual(sangria_cuerpo))
    for fila in vistas:
        lineas.append(sangria_cuerpo + truncar_medio(fila, hueco))
        estilos.append(ESTILO_RESULTADO)
    ocultas = len(filas) - ya_visto - len(vistas)
    if ocultas > 0:
        pista = PISTA_EXPANDIR + (f" {indice}" if indice > 0 else "")
        cola = (prefijo + _elipsis() + " +"
                + _plural(ocultas, "linea", "lineas") + f" ({pista})")
        if ancho_visual(cola) > ancho:
            cola = truncar_medio(cola, ancho)
        lineas.append(cola)
        estilos.append(ESTILO_RESULTADO)
    return tuple(lineas), tuple(estilos)
