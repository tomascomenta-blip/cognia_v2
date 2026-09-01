# -*- coding: utf-8 -*-
"""
cognia/clases/mates.py
======================
Formulas y graficas para el cuaderno de clase: de un LaTeX o de una expresion
en texto a un PNG que cabe en la pagina.

POR QUE PNG Y NUNCA SVG (esto NO se "mejora" luego). El cuaderno es un solo
HTML con todo embebido y `tests/test_clases_vista.py` (~478) afirma
`"http://" not in doc and "https://" not in doc`: la pagina no puede llevar ni
una URL de red. El SVG que escribe matplotlib trae OCHO URLs en su cabecera
--- MEDIDO con matplotlib 3.11.1 en esta maquina: SIETE `http://` (el DOCTYPE
de la DTD de la W3C, los xmlns de svg/xlink y la metadata RDF/Dublin Core y
Creative Commons) mas UN `https://` (el enlace a matplotlib.org del campo
dc:title) ---, asi que un solo grafico en SVG rompe ese test por las dos
cadenas que vigila y, peor, convierte un cuaderno que hoy se abre sin red en
uno que lleva referencias a dominios ajenos. Por eso `formula_a_png` y
`graficar` RECHAZAN cualquier destino que no acabe en .png, en vez de fiarse
de que nadie pase un .svg por costumbre.
El PNG tambien lleva una https:// dentro (matplotlib firma el chunk 'Software'
con su web), pero eso NO llega al HTML: la vista embebe los adjuntos como
`data:<mime>;base64,...` (`vista.py:290`), o sea que los bytes del PNG entran
codificados y ninguna URL aparece como texto en la pagina.

SIN INSTALAR LaTeX. Las formulas se dibujan con `matplotlib.mathtext`
(math_to_image), que es el interprete de LaTeX matematico que matplotlib trae
dentro. No hace falta una distribucion de TeX en la maquina -- que en el
Windows del duenio significaria ~4 GB de MiKTeX para pintar "E = mc^2".
Lo que se paga: mathtext entiende el LaTeX de FORMULA (fracciones, raices,
sumatorios, matrices), no el de documento (\\begin{align}, \\text con
paquetes). Un comando que no conoce da un error legible, no un PNG mudo.

NUNCA eval() SOBRE TEXTO DEL MODELO. Lo que se grafica sale del profesor, del
duenio o del LLM: es entrada no confiable. Se valida ANTES de parsear con una
allowlist de identificadores (regla 9 de CLAUDE.md: scan estatico + allowlist)
y solo despues se pasa por `sympy.parse_expr`. El orden importa: parse_expr
llama internamente a eval() sobre el flujo de tokens transformado, asi que
"validar despues de parsear" seria validar despues de ejecutar. Con la
allowlist delante, un `__import__("os").system(...)` no llega nunca al parser
porque "__import__" y "os" no estan en la lista.

LA ALLOWLIST FILTRA EL CODIGO, NO EL PRECIO. Son dos fronteras distintas y
hacen falta las dos. "9**9**9" no nombra nada prohibido, mide cinco
caracteres y no termina NUNCA: sympy hace las cuentas al parsear, y eso es
pedirle 9^387420489, un entero de 370 millones de cifras. MEDIDO aqui antes
del arreglo: `expresion_segura("9**9**9")` seguia corriendo a los 60 s con el
proceso vivo quemando un nucleo, igual que `factorial(99999999)`. Quien
escribe estas expresiones es EL MODELO, dentro del proceso del widget del
duenio: colgarse ahi es colgar la grabacion de una clase entera. Por eso hay
topes de COSTE (`TOPE_POTENCIAS`, `TOPE_CIFRAS`, `TOPE_FACTORIAL`) que
impiden CONSTRUIR el numero, y detras una barrera de tiempo que solo alcanza
a lo que suelta el GIL. El orden no es decorativo: MEDIDO, un hilo con plazo
NO rescata al proceso de un `int.__pow__` gigante (el join no vuelve nunca),
asi que la defensa de verdad son los topes y la barrera es la red de lo que
se cuelga a base de bytecode. El detalle de cada uno esta junto a su
constante, en `_cota_cifras` y en `_con_tope_de_tiempo`.

IMPORTS PEREZOSOS Y RUIDOSOS. matplotlib y sympy se importan DENTRO de las
funciones (no estan en requirements.txt ni en el extra [clases]: el CI de
ubuntu no los trae) y con `matplotlib.use("Agg")` antes de tocar pyplot, que
en Windows sin display es la unica forma de que no intente abrir una ventana.
Si faltan, se levanta `FaltaDependencia` con el pip install exacto. NO se
traga el ImportError: el antipatron fichado de este repo es la capacidad
desconectada en silencio -- "no lo cablearon" y "se rompio" no pueden verse
igual desde fuera.

UNA IMAGEN NO ES BUSCABLE. Todas las funciones devuelven, ademas de la ruta
del PNG, el TEXTO CRUDO que lo genero (el latex, la expresion, o los pares
etiqueta/valor). Quien lo guarde en el cuaderno tiene que poder encontrar la
grafica buscando "sin(x)/x" seis meses despues; un adjunto sin texto al lado
es un agujero en el buscador del cuaderno.

Modulo PURO y SIN ESTADO: no toca el almacen, no sabe de jornadas y no se
registra en el CLI. La puerta (comando slash) la pone otra pieza.
"""

from __future__ import annotations

import logging
import math
import re
import struct
import threading
from functools import partial
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["disponible", "formula_a_png", "graficar", "graficar_expresion",
           "graficar_datos", "expresion_segura", "evaluar",
           "ErrorDeMates", "FaltaDependencia",
           "FIRMA_PNG", "ANCHO_PAGINA_PULGADAS", "DPI", "TOPE_BYTES", "TIPOS",
           "TOPE_POTENCIAS", "TOPE_CIFRAS", "TOPE_FACTORIAL", "TOPE_SEGUNDOS"]

# Los 8 primeros bytes de todo PNG (RFC 2083). Se comprueban al terminar: un
# fichero con la extension correcta y otro contenido es exactamente el fallo
# que el cuaderno no puede detectar por si solo.
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"

# ANCHO DE PAGINA. 6,3 pulgadas = 160 mm, que es un A4 (210 mm) con los
# margenes por defecto de Word/LibreOffice (25,4 mm por lado). Se toma el A4 y
# no el Letter (8,5" - 2" = 6,5") porque el estrecho de los dos es el que
# garantiza que la imagen no se reescale al imprimir: una grafica de 6,5" en
# un A4 sale reducida al 97% y las etiquetas de los ejes pierden nitidez.
ANCHO_PAGINA_PULGADAS = 6.3
# Alto en proporcion ~1,6:1. No es un capricho estetico: mas alto que esto y
# una grafica sola ocupa media pagina del cuaderno.
ALTO_GRAFICA_PULGADAS = 3.9

# 150 ppp: el doble de los 72 del PDF y por encima de los 96 de pantalla, asi
# que 6,3" x 150 = 945 px de ancho -- se ve nitido en el HTML del cuaderno
# (que lo escala a la caja) y aguanta una impresion a 300 ppp al 50% de
# tamanio sin que se vean los pixeles. Subir a 300 cuadruplica los bytes para
# algo que casi siempre se mira en pantalla.
DPI = 150
# Suelo al que se baja si el PNG no cabe en el tope. Por debajo de 72 el texto
# de los ejes deja de leerse, o sea que ya no es una grafica.
DPI_MINIMO = 72

# TOPE DE BYTES por PNG. MEDIDO 2026-08-31 en esta maquina con este modulo, a
# 150 ppp: la formula "E = mc^2" pesa 2.290 B, la grafica de sin(x)/x de -10 a
# 10 con 801 puntos 38.737 B, un diagrama de 4 barras con etiquetas 25.426 B y
# uno de 500 barras 15.833 B. O sea que lo tipico esta entre 15 y 40 KB y 1 MB
# deja un margen de ~26x, que hace falta porque una curva muy oscilante llena
# la caja de pixeles y sube a varios cientos de KB. El tope no es
# decorativo: el cuaderno embebe los adjuntos en base64 dentro del HTML
# (vista.TOPE_ADJUNTO = 4 MB por fichero, vista.TOPE_TOTAL = 64 MB de pagina),
# y una sola grafica que se comiera 4 MB gastaria el 6% del presupuesto de
# toda la jornada. Al pasarse se BAJA el dpi por escalones; si ni al minimo
# cabe, se borra el fichero y se lanza -- una grafica silenciosamente
# recortada seria peor que ninguna.
TOPE_BYTES = 1024 * 1024

# Tamanio de fuente de una formula suelta, en puntos. 18 pt sobre el cuerpo de
# 11 pt de un documento: una formula se lee de un vistazo, no en linea.
TAM_FUENTE_FORMULA = 18

# Puntos por defecto al muestrear una expresion. 801 sobre 945 px de ancho es
# algo menos de un punto por pixel: mas es dibujar detalle que no se ve y
# engordar el PNG; bastantes menos y un sin(20x) sale con picos falsos por
# aliasing.
PUNTOS = 801

# ── Topes de COSTE (ver la cabecera: la allowlist filtra el codigo, no el
#    precio). Todos estan calibrados sobre lo que cabe en una pizarra, no
#    sobre lo que aguanta la maquina: el tope tiene que dejar pasar TODO lo
#    que un profesor escribe, o acabara apagado. ────────────────────────────

# Cuantas potencias ('**' o '^') puede llevar una expresion. Un polinomio de
# clase gasta una por termino ("x^5+x^4+x^3+x^2+x" son cuatro) y la formula
# general de segundo grado, una. Doce deja sitio de sobra y a la vez acota
# cuantas operaciones caras puede pedir un texto de 500 caracteres. No es la
# defensa principal (una torre de dos potencias ya cuelga): es el mensaje
# rapido y legible antes de encender sympy.
TOPE_POTENCIAS = 12

# Cifras decimales que puede tener CUALQUIER numero que la expresion obligue
# a construir. 5.000 cifras son ~20 KB de entero y se calculan en
# microsegundos; caben 2^1000 (302 cifras) y factorial(500) (1.135), que es
# mas de lo que nadie escribe en clase. Este es el tope que de verdad mata la
# torre de potencias, porque mira el VALOR de cada subarbol y no solo los
# exponentes escritos a mano.
TOPE_CIFRAS = 5000

# Tope del argumento de factorial y gamma. Va aparte de TOPE_CIFRAS porque
# factorial no se deja acotar mirando el arbol: se calcula solo (ver
# `_acotar_factorial`). 500! ya tiene 1.135 cifras, o sea que 1000 deja el
# doble de margen del que hace falta y corta 99999999! de raiz.
TOPE_FACTORIAL = 1000

# Segundos que puede tardar el parseo antes de que la barrera corte. Una
# expresion legitima de <=500 caracteres tarda 0,0015 s MEDIDOS en esta
# maquina CON todos los topes puestos (0,0013 s sin ellos: los dos parseos y
# el hilo cuestan 0,0002 s): 5 s son mas de tres mil veces eso, y a la vez
# menos de lo que un profesor aguanta mirando un widget quieto. La barrera es
# el ultimo recurso, no el camino normal.
TOPE_SEGUNDOS = 5.0


class ErrorDeMates(ValueError):
    """Lo que el duenio (o el CLI) puede ENSENIAR tal cual.

    Existe para que una expresion mal escrita no salga como un TokenError de
    sympy o un ParseSyntaxException de mathtext: esos mensajes hablan de
    tokens y de columnas del parser, no de lo que hay que corregir. Se hereda
    de ValueError para que quien ya capturaba ValueError alrededor de una
    formula siga capturandola.
    """


class FaltaDependencia(ErrorDeMates):
    """Falta matplotlib o sympy. Lleva SIEMPRE el pip install exacto: sin el,
    el mensaje solo dice que algo no esta y el duenio tiene que ir a buscar
    como se llama el paquete."""


# ── Dependencias (perezosas y ruidosas) ──────────────────────────────────────

# matplotlib y sympy NO estan en requirements.txt ni en el extra [clases] de
# pyproject.toml (que hoy solo trae soundcard y faster-whisper). Mientras siga
# asi, el pip install que se le ensenia al duenio tiene que nombrar los
# paquetes uno a uno; poner aqui "pip install cognia-ai[clases]" seria mandarle
# a un extra que no los instala.
_PIP = {
    "matplotlib": "pip install matplotlib",
    "sympy": "pip install sympy",
}


def _faltante(nombre: str, exc: BaseException) -> FaltaDependencia:
    return FaltaDependencia(
        "falta '%s' (%s) y sin el no hay %s. Instalalo con:  %s"
        % (nombre, "%s: %s" % (type(exc).__name__, exc),
           "formulas ni graficas" if nombre == "matplotlib" else "expresiones",
           _PIP[nombre]))


def _cargar_pyplot():
    """(matplotlib, pyplot) con backend Agg YA fijado.

    El `use("Agg")` va antes de importar pyplot y no despues: una vez pyplot
    esta importado el backend ya esta elegido, y en un Windows sin display o
    dentro de pytest eso significa TkAgg intentando abrir una ventana desde un
    hilo que no es el principal.
    """
    try:
        import matplotlib
    except ImportError as exc:
        raise _faltante("matplotlib", exc) from exc
    matplotlib.use("Agg")
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:                       # backend roto, no ausente
        raise _faltante("matplotlib", exc) from exc
    return matplotlib, plt


def _cargar_mathtext():
    """(math_to_image, FontProperties). Separado de pyplot a proposito: pintar
    una formula no necesita la maquinaria de figuras, y mathtext solo carga la
    parte del parser."""
    try:
        import matplotlib
    except ImportError as exc:
        raise _faltante("matplotlib", exc) from exc
    matplotlib.use("Agg")
    try:
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
    except ImportError as exc:
        raise _faltante("matplotlib", exc) from exc
    return mathtext.math_to_image, FontProperties


def _cargar_sympy():
    try:
        import sympy
        from sympy.parsing import sympy_parser
    except ImportError as exc:
        raise _faltante("sympy", exc) from exc
    return sympy, sympy_parser


def _cargar_numpy():
    try:
        import numpy
    except ImportError as exc:                       # numpy si esta en requirements
        raise FaltaDependencia(
            "falta 'numpy' (%s: %s), que es dependencia de base de Cognia. "
            "Instalalo con:  pip install numpy" % (type(exc).__name__, exc)) from exc
    return numpy


def disponible() -> tuple:
    """(bool, motivo). El motivo NO es decorativo: es lo que el CLI ensenia
    cuando no se puede dibujar, y 'falta un paquete' y 'el backend no arranca'
    son dos arreglos distintos."""
    try:
        _cargar_pyplot()
    except FaltaDependencia as exc:
        return False, str(exc)
    except Exception as exc:                          # backend mal instalado
        return False, ("matplotlib no arranca con el backend Agg: %s: %s"
                       % (type(exc).__name__, exc))
    try:
        _cargar_sympy()
    except FaltaDependencia as exc:
        return False, str(exc)
    except Exception as exc:
        return False, "sympy no carga: %s: %s" % (type(exc).__name__, exc)
    return True, "matplotlib (Agg) y sympy listos: formulas y graficas en PNG"


# ── PNG: destino y medidas ───────────────────────────────────────────────────

def _destino_png(destino) -> Path:
    """Path del PNG, con la carpeta creada. Rechaza cualquier otra extension.

    Ver la cabecera: el SVG de matplotlib lleva ocho cadenas http:// y
    romperia el invariante 'ni una URL de red' del cuaderno. Se comprueba aqui
    y no en cada funcion para que no haya una puerta trasera si maniana se
    aniade un tercer tipo de grafica.
    """
    ruta = Path(destino).expanduser()
    if ruta.suffix.lower() != ".png":
        raise ErrorDeMates(
            "el cuaderno solo admite PNG y '%s' es '%s'. En SVG no se puede: "
            "el SVG de matplotlib incluye URLs http:// (DTD, xmlns y metadata) "
            "y el cuaderno se abre sin red (tests/test_clases_vista.py exige "
            "que la pagina no tenga ni un http). Usa un destino .png."
            % (ruta.name, ruta.suffix or "sin extension"))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta


def _dimensiones_png(crudo: bytes) -> tuple:
    """(ancho, alto) en pixeles leyendo la cabecera IHDR.

    Se lee del fichero y no se calcula de figsize*dpi porque lo que importa es
    lo que de verdad se escribio: math_to_image dimensiona la figura segun lo
    largo que sea la formula, no segun un figsize que nosotros pongamos.
    """
    if len(crudo) < 24 or not crudo.startswith(FIRMA_PNG):
        raise ErrorDeMates("el fichero generado no es un PNG (firma %r)"
                           % crudo[:8])
    ancho, alto = struct.unpack(">II", crudo[16:24])
    return int(ancho), int(alto)


def _escalones_dpi(dpi: int) -> list:
    """Escalera de dpi a probar hasta caber en el tope: el pedido, 3/4, 1/2 y
    el suelo. Bajar el dpi (y no la resolucion logica) mantiene el tamanio
    fisico de la grafica en la pagina: sale igual de grande, con menos pixeles.

    Un dpi POR DEBAJO DEL SUELO se rechaza en vez de subirse en silencio. Un
    parametro que se ignora sin decirlo es el vacio silencioso de siempre con
    otra cara: quien pide 40 ppp para que le pese menos se lleva un PNG a 72 y
    cree que el parametro no sirve. Los escalones intermedios SI se topan al
    suelo, porque esos los elige este modulo y ya se cuentan en los avisos.
    """
    try:
        pedido = int(dpi)
    except (TypeError, ValueError) as exc:
        raise ErrorDeMates("el dpi tiene que ser un numero y es %r (%s)"
                           % (dpi, type(exc).__name__)) from exc
    if pedido < DPI_MINIMO:
        raise ErrorDeMates(
            "se han pedido %d ppp y el suelo son %d: por debajo, el texto de "
            "los ejes deja de leerse y lo que sale ya no es una grafica. Si lo "
            "que hace falta es que pese menos, baja 'tope_bytes' y el dpi se "
            "ajusta solo hasta %d." % (pedido, DPI_MINIMO, DPI_MINIMO))
    fuera = []
    for d in (int(dpi), int(dpi * 0.75), int(dpi * 0.5), DPI_MINIMO):
        d = max(DPI_MINIMO, int(d))
        if d not in fuera:
            fuera.append(d)
    return fuera


def _guardar_bajo_tope(escribir, ruta: Path, dpi: int, tope: int) -> dict:
    """Llama a `escribir(dpi)` bajando el dpi hasta caber en `tope` bytes.

    Si ni al dpi minimo cabe, BORRA el fichero y lanza. Devolver un PNG que
    revienta el presupuesto de adjuntos del cuaderno seria pasarle el problema
    a la vista, que ya solo puede enlazarlo con file:// -- o sea, una grafica
    que no viaja con el HTML sin que nadie lo haya decidido.
    """
    avisos = []
    for d in _escalones_dpi(dpi):
        escribir(d)
        crudo = ruta.read_bytes()
        ancho, alto = _dimensiones_png(crudo)
        if len(crudo) <= tope:
            return {"bytes": len(crudo), "dpi": d,
                    "ancho_px": ancho, "alto_px": alto, "avisos": avisos}
        avisos.append("a %d ppp el PNG pesaba %.0f KB (tope %.0f KB): se baja el dpi"
                      % (d, len(crudo) / 1024.0, tope / 1024.0))
        log.warning(avisos[-1])
    tam = ruta.stat().st_size
    try:
        ruta.unlink()
    except OSError as exc:                 # no callar: queda un PNG gigante
        log.warning("no se pudo borrar el PNG que excedia el tope %s: %s",
                    ruta, exc)
    raise ErrorDeMates(
        "el PNG pesa %.0f KB ni bajando a %d ppp y el tope son %.0f KB. "
        "Simplifica el dibujo (menos puntos, menos barras) o sube tope_bytes "
        "a sabiendas de que el cuaderno embebe los adjuntos en el HTML."
        % (tam / 1024.0, DPI_MINIMO, tope / 1024.0))


# ── Formulas ─────────────────────────────────────────────────────────────────

def _envolver_latex(latex: str) -> str:
    """mathtext solo interpreta lo que va entre $...$; fuera es texto plano.

    Se envuelve si no viene envuelto para que el duenio pueda escribir
    "\\frac{a}{b}" sin acordarse de los dolares, que es como lo escribe
    cualquiera que copie una formula de sus apuntes.
    """
    t = (latex or "").strip()
    if t.startswith("$") and t.endswith("$") and len(t) >= 2:
        return t
    return "$" + t + "$"


def formula_a_png(latex: str, destino, tam_fuente: float = TAM_FUENTE_FORMULA,
                  dpi: int = DPI, color: str = "black",
                  tope_bytes: int = TOPE_BYTES) -> dict:
    """Un LaTeX matematico -> PNG. Devuelve ruta Y el latex crudo.

    Sin instalacion de LaTeX: lo dibuja `matplotlib.mathtext`. El ancho lo
    manda la formula (una formula corta da un PNG corto), y si al dpi pedido
    se pasara del ancho de pagina se recalcula el dpi para que quepa: una
    imagen mas ancha que la caja del documento sale reescalada y borrosa.

    Devuelve dict con 'ruta', 'texto' (el latex tal cual lo escribio quien
    sea, que es por lo que se busca en el cuaderno), 'tipo', 'bytes', 'dpi',
    'ancho_px', 'alto_px' y 'avisos'.
    """
    crudo_texto = (latex or "").strip()
    if not crudo_texto:
        raise ErrorDeMates("no hay formula que dibujar (latex vacio)")
    ruta = _destino_png(destino)
    math_to_image, FontProperties = _cargar_mathtext()
    envuelto = _envolver_latex(crudo_texto)
    prop = FontProperties(size=float(tam_fuente))

    def _escribir(d):
        try:
            math_to_image(envuelto, str(ruta), prop=prop, dpi=d, format="png")
        except ErrorDeMates:
            raise
        except Exception as exc:
            # mathtext lanza ValueError/ParseSyntaxException con un mensaje
            # multilinea que apunta al caracter. Se conserva (dice DONDE esta
            # el fallo) pero envuelto en algo que se entienda sin saber que
            # existe un parser detras.
            raise ErrorDeMates(
                "no se pudo dibujar la formula %r: %s. mathtext entiende el "
                "LaTeX de formula (\\frac, \\sqrt, \\sum, ^, _), no el de "
                "documento (\\begin{...}, \\text de paquetes). Detalle: %s"
                % (crudo_texto, type(exc).__name__,
                   str(exc).strip().replace("\n", " | "))) from exc

    medidas = _guardar_bajo_tope(_escribir, ruta, int(dpi), int(tope_bytes))

    # Si la formula sale mas ancha que la pagina, se rebaja el dpi lo justo
    # para que entre. Se hace DESPUES del tope de bytes porque bajar el dpi
    # solo puede reducir los bytes: el resultado sigue cumpliendo el tope.
    max_px = int(ANCHO_PAGINA_PULGADAS * DPI)
    if medidas["ancho_px"] > max_px:
        nuevo = max(DPI_MINIMO,
                    int(medidas["dpi"] * max_px / float(medidas["ancho_px"])))
        if nuevo < medidas["dpi"]:
            _escribir(nuevo)
            crudo = ruta.read_bytes()
            ancho, alto = _dimensiones_png(crudo)
            medidas.update({"dpi": nuevo, "bytes": len(crudo),
                            "ancho_px": ancho, "alto_px": alto})
            medidas["avisos"].append(
                "formula larga: bajada a %d ppp para no pasar de %d px "
                "(el ancho util de un A4 con margenes)" % (nuevo, max_px))
        if medidas["ancho_px"] > max_px:
            # No se baja por debajo de DPI_MINIMO ni aunque asi cupiera: una
            # formula a 40 ppp no se lee, y entregar algo ilegible sin decirlo
            # es el vacio silencioso de siempre. Se entrega y se avisa de que
            # el documento la va a reducir.
            medidas["avisos"].append(
                "la formula mide %d px de ancho y en la pagina caben %d ni "
                "bajando al minimo de %d ppp: se entrega igual, pero el "
                "documento la reducira. Partela en varias lineas si tiene que "
                "verse nitida." % (medidas["ancho_px"], max_px, DPI_MINIMO))
            log.warning(medidas["avisos"][-1])

    fuera = {"ruta": str(ruta), "texto": crudo_texto, "latex": crudo_texto,
             "tipo": "formula"}
    fuera.update(medidas)
    return fuera


# ── Expresiones: validacion ANTES de parsear ─────────────────────────────────

# Funciones y constantes que se pueden nombrar. Es una allowlist CERRADA: lo
# que no esta aqui no llega al parser. Se mapean a objetos de sympy en
# `expresion_segura` (los alias ln/abs/ceil existen porque es como los escribe
# un alumno, no como los llama sympy).
_FUNCIONES = ("sin", "cos", "tan", "asin", "acos", "atan", "atan2",
              "sinh", "cosh", "tanh", "exp", "log", "ln", "log10", "sqrt",
              "abs", "Abs", "floor", "ceil", "ceiling", "sign", "factorial",
              "max", "min", "Max", "Min", "re", "im", "gamma", "erf")
_CONSTANTES = ("pi", "E", "e", "I")

# Caracteres admitidos. Sin comillas, sin corchetes, sin llaves, sin ':', sin
# '=' y sin '\\': ninguno hace falta para una expresion de una variable y
# todos son piezas de sintaxis que abren caminos que no queremos (indexado,
# lambdas, diccionarios, asignaciones, continuacion de linea).
_CARACTERES = re.compile(r"^[0-9A-Za-z_+\-*/^%(). ,]*$")
_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
# Largo maximo. No es un limite de seguridad sino de sensatez: una expresion
# de mas de 500 caracteres en el cuaderno de una clase es texto pegado por
# error, y el mensaje de error hay que poder leerlo.
_MAX_LARGO = 500

# Una potencia escrita a mano: '**' o '^'. Se usa para contarlas y para leer
# el exponente literal que venga detras (con un parentesis por medio o sin el).
_POTENCIA = re.compile(r"\*\*|\^")
_EXPONENTE_LITERAL = re.compile(r"(?:\*\*|\^)\s*\(?\s*([0-9]+)")


def _topes_de_texto(crudo: str) -> None:
    """Topes de COSTE que se pueden decidir mirando solo el texto.

    No son la defensa completa --- de eso se encarga `_cota_cifras` sobre el
    arbol, que es lo unico que ve a traves de los parentesis --- sino la
    rapida y la que da el mensaje bueno: aqui todavia sabemos que numero
    escribio la persona, asi que se le puede decir "99999999 es demasiado"
    en vez de "un subarbol de tu expresion pide 10^8 cifras". Y corta antes
    de encender sympy, que es donde esta el peligro.
    """
    potencias = len(_POTENCIA.findall(crudo))
    if potencias > TOPE_POTENCIAS:
        raise ErrorDeMates(
            "la expresion %r tiene %d potencias y el tope son %d. Un polinomio "
            "de clase gasta una por termino; tantas es una expresion generada, "
            "no escrita." % (crudo, potencias, TOPE_POTENCIAS))
    tope_cifras = len(str(TOPE_CIFRAS))
    for texto_exp in _EXPONENTE_LITERAL.findall(crudo):
        # el len() va delante para no construir un entero de 400 cifras solo
        # para descubrir que era enorme
        if len(texto_exp) > tope_cifras or int(texto_exp) > TOPE_CIFRAS:
            raise ErrorDeMates(
                "la expresion %r eleva a %s y el tope de exponente es %d: el "
                "resultado tendria mas de %d cifras y calcularlo cuelga el "
                "proceso. En una pizarra no cabe."
                % (crudo, texto_exp, TOPE_CIFRAS, TOPE_CIFRAS))


def _cifras(numero) -> int:
    """Cuantas cifras decimales tiene |numero|, como COTA (nunca menos).

    Los enteros y racionales se miden por su representacion (vienen de
    literales de un texto de <=500 caracteres, o sea que el str es barato);
    lo demas se pasa por complex() para que `I`, `pi` o un infinito no se
    cuenten como enormes: no ocupan memoria.
    """
    if getattr(numero, "is_Integer", False):
        return max(1, len(str(abs(int(numero)))))
    if getattr(numero, "is_Rational", False):
        return max(1, len(str(abs(int(numero.p)))))
    try:
        valor = abs(complex(numero))
    except (TypeError, ValueError, OverflowError) as exc:
        log.debug("no se pudo medir %r como numero (%s: %s): se cuenta como 1 "
                  "cifra", numero, type(exc).__name__, exc)
        return 1
    if not math.isfinite(valor):
        return 1
    return 1 if valor < 10 else int(math.log10(valor)) + 1


def _revienta_el_tope(cifras: int, crudo: str, nodo) -> int:
    """Deja pasar la cota o lanza. Separado para que el mensaje sea uno solo."""
    if cifras <= TOPE_CIFRAS:
        return cifras
    try:
        trozo = str(nodo)[:60]
    except Exception as exc:              # el printer de sympy tambien falla
        log.warning("no se pudo describir el subarbol que revienta el tope de "
                    "cifras: %s: %s", type(exc).__name__, exc)
        trozo = crudo[:60]
    raise ErrorDeMates(
        "la expresion %r obliga a construir el numero %s, que tiene del orden "
        "de %d cifras cuando el tope son %d. Eso no se calcula: se cuelga. Una "
        "torre como 9**9**9 pide un entero de 370 millones de cifras. Escribe "
        "numeros que quepan en una pizarra."
        % (crudo, trozo, cifras, TOPE_CIFRAS))


def _cota_cifras(nodo, crudo: str) -> int:
    """Cota SUPERIOR de las cifras del valor de `nodo`; -1 si es simbolico.

    Se recorre el arbol que devuelve `parse_expr(evaluate=False)`, o sea SIN
    haber hecho ninguna cuenta, y se corta en cuanto un subarbol numerico se
    pasa de TOPE_CIFRAS. Mirar solo los exponentes escritos a mano NO basta:
    en "9**9**9" el exponente no es un literal sino otro Pow, y en
    "9**(99999*99999)" es una multiplicacion. Hay que acotar el VALOR de cada
    subarbol numerico, y eso es lo que hace esto.

    Lo simbolico devuelve -1 y no se mira: `x**1000` no construye ningun
    numero (sympy lo deja en Pow y numpy lo evalua a inf, que ya es un hueco).

    ES UNA COTA, NO EL VALOR, y a proposito: para un exponente compuesto se
    usa 10^cifras(exponente) en vez de calcularlo, porque calcularlo seria
    justo lo que queremos evitar. O sea que rechaza de mas: "2**(500+500)" se
    cuenta como 10^4 cifras aunque valga 302. Se prefiere ese falso positivo
    --- que se arregla escribiendo "2**1000" --- a materializar un entero
    para averiguar si era peligroso.
    """
    if getattr(nodo, "is_Symbol", False):
        return -1
    if getattr(nodo, "is_Number", False):
        return _cifras(nodo)
    args = list(getattr(nodo, "args", ()) or ())
    if not args:
        return -1                          # atomo simbolico: I, oo, un Dummy
    cotas = [_cota_cifras(a, crudo) for a in args]
    if any(c < 0 for c in cotas):
        return -1                          # depende de la variable: no se crea
    if getattr(nodo, "is_Pow", False) and len(args) == 2:
        # El exponente manda. Si es un literal se usa tal cual (asi "2**1000"
        # sale con sus 302 cifras y pasa); si es una cuenta se acota por
        # 10^sus_cifras, que es lo que caza la torre.
        if getattr(args[1], "is_Integer", False):
            veces = abs(int(args[1]))
        else:
            veces = 10 ** cotas[1]
        return _revienta_el_tope(max(1, cotas[0]) * max(1, veces), crudo, nodo)
    if getattr(nodo, "is_Add", False):
        return _revienta_el_tope(max(cotas) + 1, crudo, nodo)
    if getattr(nodo, "is_Mul", False):
        return _revienta_el_tope(sum(cotas), crudo, nodo)
    # Cualquier otra cosa (una funcion sobre numeros): el resultado no puede
    # ser mayor que su argumento mas grande en ordenes de magnitud utiles, y
    # de todas formas el argumento hay que construirlo antes de llamarla.
    return _revienta_el_tope(max(cotas), crudo, nodo)


def _acotar_factorial(sympy, nombre: str):
    """factorial/gamma con tope, para meter en el local_dict.

    Va aqui y no en `_cota_cifras` porque factorial NO se deja mirar sin
    ejecutarse: MEDIDO, `parse_expr("factorial(99999999)", evaluate=False)` se
    cuelga igual que con evaluate=True, o sea que el arbol "sin evaluar" ni
    siquiera se llega a construir y no hay nada que recorrer. El local_dict es
    el UNICO camino por el que estos nombres llegan al parser (la allowlist se
    encarga de eso), asi que envolverlos aqui los cubre todos.

    Solo se mira el argumento cuando YA es un entero. Si es un subarbol sin
    evaluar no se toca --- llamar a int() sobre el seria evaluarlo, que es el
    colgado que estamos evitando ---: en la pasada de verdad llegara ya como
    entero y se topara entonces.
    """
    real = getattr(sympy, nombre)

    def _acotado(argumento, *resto):
        valor = None
        if isinstance(argumento, int):
            valor = argumento
        elif getattr(argumento, "is_Integer", False):
            valor = int(argumento)
        if valor is not None and abs(valor) > TOPE_FACTORIAL:
            raise ErrorDeMates(
                "%s(%d) no se puede calcular: el tope del argumento es %d "
                "porque el resultado crece mas rapido que cualquier otra cosa "
                "que se escriba en clase (500! ya tiene 1.135 cifras) y "
                "calcularlo cuelga el proceso."
                % (nombre, valor, TOPE_FACTORIAL))
        return real(argumento, *resto)

    _acotado.__name__ = nombre
    return _acotado


def _con_tope_de_tiempo(trabajo, segundos: float, que: str):
    """Corre `trabajo()` en un hilo demonio y no espera mas de `segundos`.

    HASTA DONDE LLEGA ESTA BARRERA, MEDIDO Y NO SUPUESTO. Un hilo solo se
    puede abandonar si suelta el GIL. Midiendo el mismo `join(2 s)` sobre dos
    trabajos en esta maquina:
      - bucle de bytecode de Python: el join vuelve a los 2,03 s y el hilo
        principal reacciona en 0,00 s. La barrera FUNCIONA.
      - `int.__pow__(9, 387420489)`, que es una sola llamada de C: el join NO
        VUELVE. Se mato el proceso a los 400 s sin que el principal ejecutara
        una linea. La barrera NO FUNCIONA.
    O sea que esto cubre lo que se cuelga a base de bytecode (la recursion de
    sympy sobre un arbol patologico, una simplificacion que no acaba) y NO
    cubre el entero gigante. Contra el entero gigante lo unico que sirve son
    los topes de coste de arriba, y por eso van PRIMERO y son la defensa, no
    el adorno. Decirlo importa: creerse protegido por una barrera que en el
    caso estrella no se dispara es peor que no tenerla.

    POR QUE UN HILO Y NO UN PROCESO, en Windows. `signal.alarm` es POSIX y
    aqui no existe. Un subproceso si se puede matar de verdad --- seria una
    barrera de las que valen tambien para el pow --- pero sin fork hay que
    hacer spawn: un interprete nuevo que reimporta sympy en CADA formula,
    MEDIDO en 0,26-0,30 s por llamada frente a los 0,0015 s que cuesta el
    trabajo real, o sea 180x de peaje permanente para cubrir un caso que los
    topes ya cierran. Ademas multiprocessing dentro de un ejecutable
    congelado necesita `freeze_support()`, y el widget del duenio no es un
    script. La leccion cara de este repo es que un gate que no deja hacer
    nada acaba apagado. Si algun dia aparece un colgado que los topes no
    vean y el GIL no suelte, el arreglo es el subproceso, no subir el plazo.

    LO OTRO QUE SE PAGA: a un hilo de Python no se le puede dar muerte, y
    `PyThreadState_SetAsyncExc` no interrumpe una llamada de C larga. Cuando
    el plazo salta, el hilo sigue quemando un nucleo hasta que salga el
    proceso (es demonio, o sea que no impide salir).
    """
    caja = {}

    def _correr():
        try:
            caja["valor"] = trabajo()
        except BaseException as exc:       # se re-lanza en el hilo que llamo
            caja["fallo"] = exc

    hilo = threading.Thread(target=_correr, name="mates-tope", daemon=True)
    hilo.start()
    hilo.join(float(segundos))
    if hilo.is_alive():
        log.warning("%s paso de %.1f s: se abandona el hilo, que seguira "
                    "gastando CPU hasta que termine el proceso", que, segundos)
        raise ErrorDeMates(
            "%s tardo mas de %.0f s y se ha cortado para no colgar el "
            "programa. Casi siempre es un numero gigante escondido: una torre "
            "de potencias o un factorial grande. Simplifica la expresion."
            % (que, segundos))
    if "fallo" in caja:
        raise caja["fallo"]
    return caja.get("valor")


def expresion_segura(texto: str, var: str = "x"):
    """Texto -> expresion de sympy, validando ANTES de parsear.

    Es la frontera de seguridad del modulo y por eso es publica: se prueba
    directamente. El orden (validar -> parsear) no es opinable: `parse_expr`
    llama a eval() sobre el flujo de tokens transformado, asi que validar
    despues seria validar despues de ejecutar. Aqui no se acepta ningun
    identificador que no este en la allowlist -- ni `__import__`, ni `os`, ni
    `open` -- y ademas se prohiben los caracteres con los que se construye
    cualquier cosa que no sea aritmetica.

    Y ADEMAS SE FILTRA EL PRECIO, que es una frontera distinta: "9**9**9" pasa
    la allowlist entera y cuelga el proceso. El parseo va en tres pasos --- en
    seco (`evaluate=False`, que construye el arbol sin hacer las cuentas),
    acotar el coste de cada subarbol numerico, y solo entonces de verdad ---
    y todo eso dentro de una barrera de tiempo. Ver la cabecera del modulo.

    Se permite la multiplicacion implicita ("2x", "3sin(x)") porque es como se
    escribe una formula a mano, pero NO se parten los simbolos de varias
    letras: con split_symbols, "vx" se convertiria en v*x a espaldas del
    duenio.
    """
    crudo = (texto or "").strip()
    if not crudo:
        raise ErrorDeMates("no hay expresion que graficar (texto vacio)")
    if len(crudo) > _MAX_LARGO:
        raise ErrorDeMates("la expresion tiene %d caracteres y el tope son %d: "
                           "eso no es una formula, es texto pegado"
                           % (len(crudo), _MAX_LARGO))
    if not _CARACTERES.match(crudo):
        malos = sorted({c for c in crudo if not _CARACTERES.match(c)})
        raise ErrorDeMates(
            "la expresion %r usa caracteres que no se admiten: %s. Solo se "
            "aceptan numeros, letras, %s y parentesis."
            % (crudo, " ".join(repr(c) for c in malos), "+ - * / ^ % . ,"))
    if "__" in crudo:
        raise ErrorDeMates("la expresion %r contiene '__', que no aparece en "
                           "ninguna formula de clase" % crudo)
    _topes_de_texto(crudo)          # el precio, antes de encender sympy

    sympy, parser = _cargar_sympy()
    nombre_var = (var or "x").strip() or "x"
    if not _IDENTIFICADOR.fullmatch(nombre_var):
        raise ErrorDeMates("%r no es un nombre de variable" % nombre_var)

    permitidos = set(_FUNCIONES) | set(_CONSTANTES) | {nombre_var}
    usados = set(_IDENTIFICADOR.findall(crudo))
    prohibidos = sorted(u for u in usados if u not in permitidos)
    if prohibidos:
        raise ErrorDeMates(
            "la expresion %r nombra %s, que no esta permitido. La variable es "
            "'%s' y las funciones que se pueden usar son: %s"
            % (crudo, ", ".join(repr(p) for p in prohibidos), nombre_var,
               ", ".join(sorted(_FUNCIONES))))

    simbolo = sympy.Symbol(nombre_var)
    local = {nombre_var: simbolo,
             "ln": sympy.log, "log10": lambda a: sympy.log(a, 10),
             "abs": sympy.Abs, "Abs": sympy.Abs,
             "ceil": sympy.ceiling, "ceiling": sympy.ceiling,
             "floor": sympy.floor, "sign": sympy.sign,
             "pi": sympy.pi, "E": sympy.E, "e": sympy.E, "I": sympy.I}
    for nombre in _FUNCIONES:
        if nombre not in local and hasattr(sympy, nombre):
            local[nombre] = getattr(sympy, nombre)
    # Estas dos van DESPUES del bucle a proposito: tienen que pisar a las de
    # sympy. Son las unicas que se calculan solas al construir el arbol, o sea
    # que ningun recorrido posterior llega a tiempo de pararlas.
    for nombre in ("factorial", "gamma"):
        if hasattr(sympy, nombre):
            local[nombre] = _acotar_factorial(sympy, nombre)

    transformaciones = (parser.standard_transformations
                        + (parser.convert_xor, parser.implicit_multiplication))

    def _parsear():
        # 1) EN SECO: construye el arbol sin hacer ninguna cuenta. Es lo que
        #    permite mirar "9**9**9" sin calcularlo (MEDIDO: 0,0000 s).
        seco = parser.parse_expr(crudo, local_dict=local,
                                 transformations=transformaciones,
                                 evaluate=False)
        # 2) ACOTAR el coste de cada subarbol numerico. Si aqui no se corta,
        #    el paso 3 es el que se cuelga.
        _cota_cifras(seco, crudo)
        # 3) Ahora si, con las cuentas hechas. Se vuelve a llamar a
        #    parser.parse_expr (y no se reutiliza `seco`) porque un arbol sin
        #    evaluar no se puede derivar, simplificar ni pasar a lambdify.
        return parser.parse_expr(crudo, local_dict=local,
                                 transformations=transformaciones)

    try:
        expr = _con_tope_de_tiempo(_parsear, TOPE_SEGUNDOS,
                                   "parsear la expresion %r" % crudo)
    except ErrorDeMates:
        raise                       # ya es legible: tope de coste o de tiempo
    except Exception as exc:
        # sympy dice "TokenError: ('unexpected EOF in multi-line statement',
        # (1, 0))", que no le dice nada a nadie. El mensaje util es cual es la
        # expresion y que hay que mirar.
        raise ErrorDeMates(
            "no se entiende la expresion %r (%s). Revisa los parentesis y "
            "escribe la multiplicacion con '*' si hace falta. Detalle: %s"
            % (crudo, type(exc).__name__, str(exc).strip().replace("\n", " | "))
        ) from exc

    libres = {str(s) for s in getattr(expr, "free_symbols", set())}
    if libres - {nombre_var}:
        raise ErrorDeMates(
            "la expresion %r depende de %s ademas de '%s', y aqui solo se "
            "grafica una variable"
            % (crudo, ", ".join(repr(s) for s in sorted(libres - {nombre_var})),
               nombre_var))
    return expr


def evaluar(texto: str, var: str = "x", desde: float = -10.0,
            hasta: float = 10.0, puntos: int = PUNTOS) -> tuple:
    """(xs, ys, expresion) muestreando la expresion en el rango.

    Los puntos donde la expresion no vale un numero real (division por cero en
    sin(x)/x, raiz de negativo, log de cero) salen como NaN y matplotlib deja
    el hueco. Es lo correcto: unir por encima del agujero dibujaria una curva
    que no existe, y saltarse los puntos desplazaria el resto de la grafica.
    """
    sympy, _ = _cargar_sympy()
    np = _cargar_numpy()
    expr = expresion_segura(texto, var)
    desde, hasta = float(desde), float(hasta)
    if not (hasta > desde):
        raise ErrorDeMates("el rango va de %g a %g y tiene que ser creciente"
                           % (desde, hasta))
    puntos = int(puntos)
    if puntos < 2:
        raise ErrorDeMates("hacen falta al menos 2 puntos para una curva, no %d"
                           % puntos)

    simbolo = sympy.Symbol((var or "x").strip() or "x")
    xs = np.linspace(desde, hasta, puntos)
    try:
        f = sympy.lambdify(simbolo, expr, modules=["numpy"])
        with np.errstate(all="ignore"):     # 0/0 y log(0) son NaN, no un crash
            crudo = f(xs)
    except Exception as exc:
        raise ErrorDeMates(
            "la expresion %r se entiende pero no se puede evaluar entre %g y "
            "%g (%s: %s)" % (texto, desde, hasta, type(exc).__name__, exc)
        ) from exc

    ys = np.asarray(crudo)
    if ys.ndim == 0 or ys.size == 1:        # una constante: lambdify da escalar
        # Se difunde CONSERVANDO EL TIPO, no con float(). El float() de antes
        # convertia esta rama en la primera que veia una constante compleja
        # ("I", "sqrt(-1)") y reventaba con el TypeError crudo de
        # float(complex) --- justo la excepcion sin traducir que este modulo
        # dice no dejar salir --- y dejaba la rama de complejos de abajo como
        # codigo muerto. Difundiendo con el dtype de origen, una constante
        # compleja llega entera al where() de abajo y acaba en el error
        # legible "no da ningun valor real".
        ys = np.full(xs.shape, ys.reshape(-1)[0], dtype=ys.dtype)
    if np.iscomplexobj(ys):
        # sqrt(x) en los negativos sale complejo. Se queda la parte real donde
        # la imaginaria es despreciable y NaN en el resto: dibujar el modulo
        # seria pintar otra funcion.
        ys = np.where(np.abs(ys.imag) < 1e-9, ys.real, np.nan)
    ys = np.asarray(ys, dtype=float)
    with np.errstate(all="ignore"):
        ys = np.where(np.isfinite(ys), ys, np.nan)
    if not np.any(np.isfinite(ys)):
        raise ErrorDeMates(
            "la expresion %r no da ningun valor real entre %g y %g: la grafica "
            "saldria en blanco" % (texto, desde, hasta))
    return xs, ys, expr


# ── Graficas ─────────────────────────────────────────────────────────────────

def _figura(plt, dpi: int, alto: float = ALTO_GRAFICA_PULGADAS):
    fig = plt.figure(figsize=(ANCHO_PAGINA_PULGADAS, float(alto)), dpi=dpi)
    ax = fig.add_subplot(111)
    ax.grid(True, linewidth=0.4, alpha=0.35)   # cuadricula de cuaderno, suave
    return fig, ax


def _pintar(plt, fig, ruta: Path, dpi: int) -> None:
    """savefig + close SIEMPRE. Sin el close, cada grafica deja la figura viva
    en el registro de pyplot: una jornada con 40 graficas son 40 figuras en
    memoria y un aviso de matplotlib por cada una."""
    try:
        fig.savefig(str(ruta), format="png", dpi=dpi,
                    bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)


def graficar_expresion(expresion: str, destino, var: str = "x",
                       desde: float = -10.0, hasta: float = 10.0,
                       puntos: int = PUNTOS, titulo: str = "",
                       dpi: int = DPI, tope_bytes: int = TOPE_BYTES) -> dict:
    """Una expresion en una variable sobre un rango -> PNG.

    El caso del contrato: "sin(x)/x" de -10 a 10. El texto que se devuelve es
    la expresion tal cual, con su rango, para que la grafica se pueda buscar
    en el cuaderno por lo que dibuja.
    """
    ruta = _destino_png(destino)
    _, plt = _cargar_pyplot()
    xs, ys, _expr = evaluar(expresion, var=var, desde=desde, hasta=hasta,
                            puntos=puntos)
    crudo = (expresion or "").strip()
    rotulo = (titulo or "").strip() or crudo

    def _escribir(d):
        fig, ax = _figura(plt, d)
        ax.plot(xs, ys, linewidth=1.6)
        ax.set_title(rotulo)
        ax.set_xlabel(var)
        ax.set_ylabel("f(%s)" % var)
        ax.axhline(0.0, linewidth=0.6, color="0.4")
        ax.axvline(0.0, linewidth=0.6, color="0.4")
        _pintar(plt, fig, ruta, d)

    medidas = _guardar_bajo_tope(_escribir, ruta, int(dpi), int(tope_bytes))
    fuera = {"ruta": str(ruta),
             "texto": "%s  (%s de %g a %g)" % (crudo, var, desde, hasta),
             "expresion": crudo, "tipo": "expresion",
             "var": var, "desde": float(desde), "hasta": float(hasta),
             "puntos": int(puntos)}
    fuera.update(medidas)
    return fuera


def _como_lista(datos, nombre: str) -> list:
    """list(datos) SIN pasar por `datos or []`.

    `y or []` parece defensivo y es una bomba: sobre un numpy array llama a
    `__bool__` y numpy contesta "the truth value of an array with more than
    one element is ambiguous", una excepcion cruda del backend en la forma mas
    natural de llamar a esta funcion --- pasarle la salida de otro calculo.
    """
    if datos is None:
        return []
    try:
        return list(datos)
    except TypeError as exc:
        raise ErrorDeMates(
            "la serie %r tiene que ser una lista de numeros y es un %s (%s)"
            % (nombre, type(datos).__name__, exc)) from exc


def _hay_datos(datos) -> bool:
    """Si `datos` trae algo, sin llamar a bool() encima (ver `_como_lista`).
    Un iterable sin len() se da por bueno aqui y se decide al convertirlo:
    consumirlo para contarlo lo dejaria vacio para quien venga detras."""
    if datos is None:
        return False
    try:
        return len(datos) > 0
    except TypeError:
        return True


def _numeros(datos, nombre: str) -> list:
    """La serie como floats, diciendo QUE elemento no lo era.

    Un hueco escrito como None es la otra forma natural de equivocarse (la
    salida de un calculo que no dio valor en un punto) y float(None) sale como
    un TypeError crudo que no dice ni cual de los 500 valores fue.
    """
    fuera = []
    for i, valor in enumerate(_como_lista(datos, nombre)):
        try:
            fuera.append(float(valor))
        except (TypeError, ValueError) as exc:
            raise ErrorDeMates(
                "el valor %d de la serie %r es %r y no es un numero (%s). Un "
                "hueco en la serie se escribe como float('nan'), que la "
                "grafica deja en blanco; None no vale."
                % (i, nombre, valor, type(exc).__name__)) from exc
    return fuera


# Pares etiqueta/valor que se listan en el texto buscable. 30 entradas son ~2
# lineas de nota en el cuaderno; una serie mas larga se resume por rango,
# porque listar 800 numeros no lo busca nadie y engorda el JSONL de la
# jornada.
_MAX_PARES = 30


def _texto_datos(titulo: str, etiquetas, xs, ys) -> str:
    """El texto CRUDO por el que se buscara la grafica. Una imagen no es
    buscable: si esto sale vacio, la grafica desaparece del buscador del
    cuaderno aunque el PNG este perfecto."""
    cabeza = (titulo or "").strip() or "serie de datos"
    if etiquetas:
        pares = ["%s: %g" % (e, v) for e, v in zip(etiquetas, ys)]
    else:
        pares = ["%g: %g" % (a, b) for a, b in zip(xs, ys)]
    if len(pares) > _MAX_PARES:
        return ("%s (%d puntos, x de %g a %g; y de %g a %g)"
                % (cabeza, len(pares), min(xs), max(xs), min(ys), max(ys)))
    return "%s -- %s" % (cabeza, "; ".join(pares))


def graficar_datos(destino, y, x=None, etiquetas=None, tipo: str = "linea",
                   titulo: str = "", eje_x: str = "", eje_y: str = "",
                   dpi: int = DPI, tope_bytes: int = TOPE_BYTES) -> dict:
    """Una serie de datos (x, y) o barras con etiquetas -> PNG.

    `etiquetas` manda sobre `x`: cuando hay etiquetas ("1a eval", "2a eval")
    el eje X es categorico y los numeros que hubiera en `x` no significan
    nada. Con tipo='barras' y sin etiquetas se numeran las barras, que es
    mejor que dejarlas mudas.
    """
    ruta = _destino_png(destino)
    _, plt = _cargar_pyplot()
    ys = _numeros(y, "y")
    if not ys:
        raise ErrorDeMates("no hay datos que graficar (la serie 'y' esta vacia)")
    etiquetas = [str(e) for e in _como_lista(etiquetas, "etiquetas")] or None
    if etiquetas is not None and len(etiquetas) != len(ys):
        raise ErrorDeMates("hay %d etiquetas y %d valores: no cuadran"
                           % (len(etiquetas), len(ys)))
    if x is not None and etiquetas is None:
        xs = _numeros(x, "x")
        if len(xs) != len(ys):
            raise ErrorDeMates("hay %d valores de x y %d de y: no cuadran"
                               % (len(xs), len(ys)))
    else:
        xs = list(range(len(ys)))
    if tipo not in ("linea", "barras", "dispersion"):
        raise ErrorDeMates("tipo de grafica %r desconocido: %s"
                           % (tipo, "linea, barras, dispersion"))

    def _escribir(d):
        fig, ax = _figura(plt, d)
        if tipo == "barras":
            ax.bar(range(len(ys)), ys)
            ax.set_xticks(range(len(ys)))
            ax.set_xticklabels(etiquetas or [str(v) for v in xs],
                               rotation=0 if len(ys) <= 8 else 45,
                               ha="center" if len(ys) <= 8 else "right")
        elif tipo == "dispersion":
            ax.scatter(xs, ys, s=18)
        else:
            ax.plot(xs, ys, marker="o" if len(ys) <= 40 else None,
                    markersize=3.5, linewidth=1.6)
            if etiquetas:
                ax.set_xticks(range(len(ys)))
                ax.set_xticklabels(etiquetas,
                                   rotation=0 if len(ys) <= 8 else 45,
                                   ha="center" if len(ys) <= 8 else "right")
        if titulo:
            ax.set_title(titulo)
        if eje_x:
            ax.set_xlabel(eje_x)
        if eje_y:
            ax.set_ylabel(eje_y)
        _pintar(plt, fig, ruta, d)

    medidas = _guardar_bajo_tope(_escribir, ruta, int(dpi), int(tope_bytes))
    fuera = {"ruta": str(ruta),
             "texto": _texto_datos(titulo, etiquetas, xs, ys),
             "tipo": tipo, "n": len(ys),
             "etiquetas": etiquetas or [], "valores": ys}
    fuera.update(medidas)
    return fuera


def _puerta_expresion(destino, expresion=None, y=None, x=None, etiquetas=None,
                      **kw) -> dict:
    if expresion is None:
        raise ErrorDeMates("tipo='expresion' sin expresion que graficar")
    return graficar_expresion(expresion, destino, **kw)


def _puerta_datos(destino, tipo, expresion=None, y=None, x=None,
                  etiquetas=None, **kw) -> dict:
    if y is None:
        raise ErrorDeMates("tipo=%r necesita la serie 'y' de valores" % tipo)
    return graficar_datos(destino, y, x=x, etiquetas=etiquetas, tipo=tipo, **kw)


# Punto de extension: para aniadir un tipo de grafica se registra aqui su
# funcion y `graficar` lo acepta sin tocar nada mas. Es la tabla que se
# DESPACHA de verdad (no una lista de nombres al lado de un if-chain): todas
# las entradas comparten la firma (destino, expresion, y, x, etiquetas, **kw).
TIPOS = {
    "expresion": _puerta_expresion,
    "linea": partial(_puerta_datos, tipo="linea"),
    "barras": partial(_puerta_datos, tipo="barras"),
    "dispersion": partial(_puerta_datos, tipo="dispersion"),
}


def graficar(destino, expresion: str = None, y=None, x=None, etiquetas=None,
             tipo: str = None, **kw) -> dict:
    """Puerta unica: expresion o serie de datos -> PNG. Devuelve el mismo dict
    (ruta + texto crudo) que las funciones concretas.

    El tipo se deduce de lo que se pasa (una expresion es una curva; unas
    etiquetas, barras) para que quien llame no tenga que decirlo dos veces;
    darlo explicito manda sobre la deduccion.
    """
    if tipo is None:
        # `if etiquetas` (a secas) revienta con un numpy array de etiquetas:
        # ver `_hay_datos`. La deduccion del tipo no puede ser el sitio donde
        # se cae una llamada que graficar_datos habria aceptado.
        tipo = ("expresion" if expresion is not None
                else "barras" if _hay_datos(etiquetas) else "linea")
    if tipo not in TIPOS:
        raise ErrorDeMates("tipo de grafica %r desconocido: los que hay son %s"
                           % (tipo, ", ".join(sorted(TIPOS))))
    return TIPOS[tipo](destino, expresion=expresion, y=y, x=x,
                       etiquetas=etiquetas, **kw)
