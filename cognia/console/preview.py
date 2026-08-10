"""
cognia/console/preview.py
=========================
Preview bat-style de archivos y fragmentos de codigo para el REPL.

POR QUE existe: `cat` (y el /leer del REPL) vuelcan texto plano sin
estructura; para "solo mirar" un archivo el usuario viaja al editor.
bat demostro que el 80% de esas miradas se resuelven en terminal si el
archivo se muestra BELLO por defecto: sintaxis por extension, numeros
de linea y las lineas relevantes resaltadas. Aca se replica eso con
rich.Syntax, que ya es dependencia del REPL.

Contrato (mismo patron que cognia/cli.py y este paquete):
- rich es OPCIONAL: sin rich cada funcion devuelve None y el caller cae
  a su texto plano de siempre. Nunca se lanza por archivo ilegible.
- Estas funciones DEVUELVEN el renderable; el caller decide donde y
  como imprimirlo (el render rico es solo de la capa terminal — el
  string que ve el modelo/remoto no pasa por aca, contrato intacto).
- theme='ansi_dark': usa los 16 colores ANSI del terminal, asi el
  preview hereda la paleta/tema del usuario en vez de imponer una.
- Leccion Latin-1 del repo: los bytes se decodifican SOLO para mostrar
  (utf-8 estricto y fallback latin-1); jamas se re-escribe el archivo
  con esa decodificacion.
"""

from __future__ import annotations

# rich es opcional (mismo patron que cognia/cli.py): sin rich todo
# devuelve None y el caller imprime su texto plano de siempre.
try:
    from rich.syntax import Syntax
    _HAS_RICH = True
except ImportError:  # pragma: no cover - depende del entorno
    Syntax = None
    _HAS_RICH = False

# Tope duro de bytes leidos del disco. POR QUE: un preview muestra ~24
# lineas; cargar un archivo de cientos de MB entero para eso es un DoS
# autoinfligido. Se lee a lo sumo este prefijo y alcanza para cualquier
# rango razonable de /cat.
_MAX_BYTES = 2_000_000


def _leer_bytes(ruta: str) -> bytes | None:
    """Prefijo de bytes del archivo, o None si no se puede leer o es
    binario. El chequeo de NUL es la heuristica estandar (git/grep):
    un preview de sintaxis sobre binario es ruido, no informacion."""
    try:
        with open(ruta, "rb") as f:
            raw = f.read(_MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    return raw


def _decodificar(raw: bytes) -> str:
    # utf-8 estricto primero; latin-1 SOLO para mostrar (leccion
    # Latin-1: verificar en bytes, no re-escribir con esta decodificacion)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _construir_syntax(texto: str, lexer, resaltar: tuple,
                      max_lineas: int, desde: int):
    """Arma el rich.Syntax acotado. line_range recorta el RENDER (no el
    texto): asi un archivo de 5000 lineas pinta solo las pedidas."""
    if not _HAS_RICH:
        return None
    # el \n final no abre una linea fantasma: mismo conteo que
    # contar_lineas, asi la cabecera 'de N' y el gutter coinciden
    total = texto.count("\n") + (0 if texto.endswith("\n") else 1)
    total = max(1, total)
    desde = max(1, int(desde))
    max_lineas = max(1, int(max_lineas))
    if desde > total:
        # pedir mas alla del final muestra la cola, no un vacio mudo
        desde = max(1, total - max_lineas + 1)
    hasta = min(total, desde + max_lineas - 1)
    try:
        lineas_res = {int(n) for n in resaltar} or None
    except (TypeError, ValueError):
        lineas_res = None
    try:
        return Syntax(
            texto,
            lexer,
            theme="ansi_dark",       # hereda la paleta del terminal
            line_numbers=True,
            line_range=(desde, hasta),
            highlight_lines=lineas_res,
            word_wrap=False,
        )
    except Exception:
        # un lexer roto o una version vieja de rich no deben tirar el
        # REPL: el caller cae a texto plano
        return None


def preview_archivo(ruta: str, resaltar: tuple = (), max_lineas: int = 24,
                    console=None, desde: int = 1) -> object | None:
    """Renderable rich.Syntax del archivo real, o None (sin rich, ruta
    inexistente, binario o ilegible — nunca lanza).

    - resaltar: numeros de linea (1-based) a resaltar (p.ej. las lineas
      que el agente acaba de editar).
    - max_lineas/desde: ventana del render; el resto del archivo no se
      pinta (paginado simple del caller via desde).
    - console: reservado por firma del plan — el renderable NO se
      imprime aca; el caller decide (asi el contrato remoto/pipe queda
      intacto: rich solo en la capa terminal).
    """
    raw = _leer_bytes(ruta)
    if raw is None:
        return None
    texto = _decodificar(raw)
    if _HAS_RICH:
        try:
            lexer = Syntax.guess_lexer(ruta, code=texto)
        except Exception:
            lexer = "text"
    else:
        return None
    return _construir_syntax(texto, lexer, resaltar, max_lineas, desde)


def preview_texto(texto: str, lenguaje: str = "python", **kw) -> object | None:
    """Renderable rich.Syntax de un texto directo (sin archivo), o None.
    kw acepta resaltar/max_lineas/desde con los mismos defaults que
    preview_archivo — POR QUE **kw: la firma corta es la del plan y los
    extras comparten una sola implementacion."""
    if not isinstance(texto, str) or not _HAS_RICH:
        return None
    return _construir_syntax(
        texto,
        lenguaje or "text",
        kw.get("resaltar", ()),
        kw.get("max_lineas", 24),
        kw.get("desde", 1),
    )


def contar_lineas(ruta: str) -> int | None:
    """Total de lineas del archivo (sobre el prefijo _MAX_BYTES), o None
    si no es legible. POR QUE: el caller de /cat necesita el total para
    la cabecera 'lineas X-Y de N' y la pista de paginado sin duplicar
    la lectura tolerante a errores."""
    raw = _leer_bytes(ruta)
    if raw is None:
        return None
    n = raw.count(b"\n")
    if raw and not raw.endswith(b"\n"):
        n += 1
    return n
