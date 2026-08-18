"""
cognia/console/diff_render.py
=============================
EL UNICO sitio que sabe pintar un diff en el CLI de Cognia.

POR QUE: el momento "el agente edito X" pintaba un unified diff plano linea a
linea; leer la INTENCION del cambio en 2 segundos exige ver la palabra exacta
que cambio. Esto pinta las lineas -/+ con FONDO a todo el ancho (banda verde
en las +, roja en las -) y ademas resalta los spans cambiados DENTRO de cada
par de lineas reemplazadas (delta-style), con SequenceMatcher a nivel de
palabra.

DECISION 12 DEL DUENO (2026-08-17): la linea entera pintada, con el + o el -
al margen. Antes se coloreaba el TEXTO (verde/rojo) y el unico fondo era el
'reverse' del resaltado intra-linea; el resultado medido era que en el tema por
defecto el rojo (#c50f1f, 3.12:1) era LO MAS APAGADO de la pantalla mientras
todo lo verde estaba entre 5.5 y 15.4 — la linea borrada, que es la mitad de la
informacion de un diff, era el texto mas tenue del CLI.

DOS IDIOMAS DE DIFF, UNIFICADOS (puntos 2 y 3 del juicio visual, 2026-08-17).
Hasta hoy este modulo solo lo usaba `/editar`. El preview que el agente emite
en CADA /hacer (ux/renderer.py) escribia '+ linea' / '- linea' como texto
pelado con los tokens 'escrito'/'borrado', o sea: el diff que el dueno ve en
TODA tarea autonoma era el que no tenia banda, y ahi sobrevivia intacta la
asimetria que la decision 12 vino a matar ('+' a 9,34:1 y '-' a 4,92:1 sobre
el fondo del tema — el DOBLE de contraste para lo agregado). Ahora el renderer
llama a `render_bloque()` de aca: una sola implementacion del pintado, dos
entradas (`render_diff` para un unified completo, `render_bloque` para un par
de listas -/+ ya extraidas, sin cabeceras).

LAS BANDAS SALEN DEL TEMA, NO DE UNA MEZCLA LOCAL (punto 3). Vivian calculadas
aqui como mezcla alfa sobre SUPERFICIE['fondo'] (#0d1117), asi que con '/tema
claro' el bloque quedaba NEGRO sobre una terminal blanca: 13,23:1 y 14,92:1
contra #fbfbfa, el elemento de mas peso de la pantalla, con las lineas de
contexto en negro-sobre-blanco justo encima. Ahora se leen de
`paleta.DIFF_FONDO[variante]`; las de 'oscuro' son EXACTAMENTE los hex que este
modulo calculaba (lo fija test_las_bandas_oscuras_son_las_historicas), y las
marcas de 'oscuro' tampoco se movieron.

LO UNICO QUE SI CAMBIA EN EL TEMA POR DEFECTO es el color del CONTENIDO de la
linea: era SEMANTICO['texto'] (#e6edf3, 11,59:1 sobre la banda verde) y pasa a
ser el token 'respuesta' de la variante, o sea el foreground de la terminal
(#cccccc en Campbell: 8,53:1). Se pierden 3 puntos de contraste y se gana la
unica forma de que el MISMO codigo sirva en claro, donde ese gris da 1,05:1 —
ilegible. Es ademas lo que pide la decision 17 (el contenido en color de texto)
y el aviso que la paleta dejo escrito para este consumidor. Limite declarado:
en una terminal con un foreground raro el numero deja de ser el de la tabla.

CONTRASTES MEDIDOS (scripts/contraste_tema.py; el texto de encima resuelto con
la tabla ANSI de cada variante: Campbell en los dos oscuros, terminal clara en
'claro'):

    variante         banda +   banda -   texto      marca +   marca -
    oscuro           1,38      1,22      8,53/9,62  5,39      4,61
    claro            1,20      1,22      12,8/12,6  5,51      4,83
    alto_contraste   1,43      1,22      11,8/13,8  5,19      4,61

  * "banda" es contra el fondo del tema: MENOS de 2:1 a proposito. Una banda
    que se despega mas que eso deja de ser un realce y vuelve a ser una isla.
  * El texto de la linea NO es verde ni rojo: es el token 'respuesta' del tema
    (decision 17 — el contenido en color de texto, el color para la interfaz).
    Tampoco es SEMANTICO['texto']: ese gris (#e6edf3) da 1,05:1 sobre la banda
    clara, o sea ILEGIBLE — es el aviso que dejo escrito la paleta.
  * Las dos marcas del margen miden PARECIDO en las tres variantes (razon
    1,13-1,17). Ese es el punto 2 del juicio visual: '+' y '-' son las dos
    mitades de la misma informacion y no pueden tener contrastes al doble.
  * Los dos fondos de linea tienen ~1,2:1 ENTRE SI (casi la misma luminancia,
    distinto tono): por eso la marca +/- del margen NO es decorativa — es el
    canal no-cromatico que distingue agregado de borrado (WCAG 1.4.1) y el
    unico que sobrevive a NO_COLOR y a un daltonismo rojo-verde.

Alcance PODADO a proposito (plan B3): SIN side-by-side, SIN tree-sitter,
cero dependencias nuevas. Solo render local del terminal: el string RESULTADO
que consume el modelo (mini_diff en agent/edit_block.py) NO pasa por aca y
no cambia; el remoto y los pipes conservan el texto plano de siempre.

EL PREFIJO ES CONTRATO CON EL MOVIL. cognia/remoto/sesiones.py clasifica el
chat del movil por el arranque de la linea: '+ ' (con espacio) es ACTIVIDAD y
'- ' seria vineta de respuesta. Por eso el separador entre el signo y el
contenido es un PARAMETRO y no una constante:
  * `render_diff` usa '' — el unified de siempre, '+contenido' pegado, que es
    lo que ya media test_prefijo_intacto_para_el_clasificador_del_movil;
  * `render_bloque` acepta separador=' ' y el renderer lo pide asi, porque el
    preview del agente YA emitia '+ linea' y esas lineas son actividad.
Los dos casos estan medidos contra las funciones REALES del remoto en
tests/test_diff_render.py y tests/test_renderer_estetica.py.

rich es opcional (mismo patron que cognia/cli.py y el resto de console/):
sin rich, render_diff/render_bloque devuelven None y el caller usa su fallback
plano — que sigue distinguiendo + de - por el signo.
"""

from __future__ import annotations

import difflib
import os
import re

from cognia.ux import paleta
from cognia.ux.paleta import SEMANTICO

try:
    from rich.console import Group
    from rich.padding import Padding
    from rich.text import Text
    _HAS_RICH = True
except Exception:  # pragma: no cover - entorno sin rich
    Group = None    # type: ignore
    Padding = None  # type: ignore
    Text = None     # type: ignore
    _HAS_RICH = False


VARIANTE_DEFECTO = "oscuro"


def variante_activa(console=None) -> str:
    """El nombre de la variante de tema ACTIVA, para elegir las bandas.

    ORDEN, y por que (no es arbitrario):
      1. ``COGNIA_THEME``. Es lo que '/tema' escribe EN CALIENTE: pasa por
         first_run.set_config_value(), que ademas de guardar en config.env hace
         ``os.environ[key] = value``. Es la unica fuente que refleja un cambio
         de tema hecho a mitad de sesion.
      2. El tema de la ``console`` que llegue. cli._console SI se reconstruye
         con el tema nuevo, pero ux/renderer.activar() solo corre en el
         arranque, asi que el Renderer puede estar guardando una Console
         RANCIA: sirve de respaldo (escenas, arneses que arman su propia
         Console con tema), nunca de fuente principal.
      3. 'oscuro' — el defecto del CLI cuando COGNIA_THEME no existe o trae
         basura, exactamente lo que hace cli._theme_idx.

    Se sondea el token 'marca' (rol 'identidad') porque su hex es DISTINTO en
    las tres variantes (#4fd010 / #2c8400 / #7ee62a); la comparacion es
    paleta.mismo_color, nunca '==' (leccion del punto 10: los renderers
    truncan un canal).
    """
    nombre = os.environ.get("COGNIA_THEME", "").strip()
    if nombre in paleta.DIFF_FONDO:
        return nombre
    if console is not None:
        try:
            color = console.get_style("marca").color
            trip = color.get_truecolor()
            hexa = f"#{trip.red:02x}{trip.green:02x}{trip.blue:02x}"
            for var in paleta.DIFF_FONDO:
                if paleta.mismo_color(hexa, paleta.rampa(var)["marco"]):
                    return var
        except Exception:
            pass
    return VARIANTE_DEFECTO


# Las MARCAS +/- del margen, por variante. Las dos NO salen del mismo rol de la
# paleta a proposito: el criterio es (a) las dos por encima de 4,5:1 sobre SU
# banda y (b) que midan PARECIDO entre si — el punto 2 del juicio visual era
# justamente que lo agregado tenia el doble de contraste que lo borrado.
# Lo medido, candidato por candidato (scripts/contraste_tema.py):
#   oscuro   sobre #173322/#371d20: SEMANTICO ok 5,39 / error 4,61  <- elegido
#                                   token escrito 6,76 / borrado 4,02 (bajo AA)
#   claro    sobre #ddeadc/#f4e0e1: rampa solido 5,51 / token err_cl 4,83 <-
#                                   SEMANTICO ok 2,04 (el verde oscuro-sobre-
#                                   claro no existe fuera de la rampa clara)
#   alto_c.  sobre #183624/#371d20: SEMANTICO ok 5,19 / error 4,61  <- elegido
#                                   rampa solido 7,64 y token escrito 8,32
#                                   pasan AA pero contra un '-' de 4,61 (techo
#                                   de esa banda: con el rojo mas claro la '-'
#                                   cae a 4,02) devolverian la asimetria 1,7-1,8
# 'claro' es la unica que usa un nombre ANSI ('red' del tema): la paleta no
# declara un rojo hex para fondo claro y #f85149 da 2,65 sobre su banda.
_MARCAS = {
    "oscuro":         (SEMANTICO["ok"], SEMANTICO["error"]),
    "claro":          (paleta.rampa("claro")["solido"],
                       paleta.tema_cli("claro")["err_cl"]),
    "alto_contraste": (SEMANTICO["ok"], SEMANTICO["error"]),
}

# Cabeceras ---/+++ , @@ y contexto: sin fondo. El bloque pintado tiene que ser
# exactamente lo que cambio.
_ST_HDR = "dim"


def _bold(estilo: str) -> str:
    """'bold' delante, sin duplicarlo (el tema ya puede traerlo)."""
    return estilo if "bold" in estilo.split() else "bold " + estilo


def _construir_estilos(variante: str) -> dict:
    banda = paleta.diff_fondos(variante)
    # El contenido va en color de TEXTO NORMAL de la variante, no en verde ni
    # rojo: el fondo ya lleva el signo (decision 17 + aviso de la paleta).
    contenido = paleta.tema_cli(variante)["respuesta"]
    marca_mas, marca_menos = _MARCAS[variante]
    return {
        "hdr": _ST_HDR,
        # El FONDO va en el Padding (pinta hasta el borde derecho); el Text de
        # dentro solo lleva colores de primer plano.
        "linea_mas":   f"on {banda['mas']}",
        "linea_menos": f"on {banda['menos']}",
        "contenido":   contenido,
        "marca_mas":   _bold(marca_mas),
        "marca_menos": _bold(marca_menos),
        # El enfasis intra-linea usa un fondo MAS FUERTE del mismo tono, no
        # 'reverse': con la linea ya pintada, invertir devolveria fondo claro
        # con texto oscuro y el span cambiado se leeria como un hueco.
        "mas_intra":   f"{_bold(contenido)} on {banda['mas_intra']}",
        "menos_intra": f"{_bold(contenido)} on {banda['menos_intra']}",
    }


_CACHE_ESTILOS: dict = {}


def estilos(variante: str = VARIANTE_DEFECTO) -> dict:
    """Los estilos del diff de una variante (cacheados). Variante desconocida
    -> la de defecto, nunca KeyError: esto es adorno y jamas rompe un turno."""
    if variante not in paleta.DIFF_FONDO:
        variante = VARIANTE_DEFECTO
    est = _CACHE_ESTILOS.get(variante)
    if est is None:
        est = _CACHE_ESTILOS[variante] = _construir_estilos(variante)
    return est


# Compat: los nombres que existian cuando el modulo tenia UN solo juego de
# estilos (el oscuro). Se conservan igual que paleta.VERDE = RAMPA['oscuro']:
# hay tests y consumidores que los importan, y en el tema por defecto valen
# exactamente lo mismo que antes.
_FONDO_MAS = paleta.DIFF_FONDO[VARIANTE_DEFECTO]["mas"]
_FONDO_MENOS = paleta.DIFF_FONDO[VARIANTE_DEFECTO]["menos"]
_FONDO_MAS_INTRA = paleta.DIFF_FONDO[VARIANTE_DEFECTO]["mas_intra"]
_FONDO_MENOS_INTRA = paleta.DIFF_FONDO[VARIANTE_DEFECTO]["menos_intra"]
_ST_LINEA_MAS = estilos(VARIANTE_DEFECTO)["linea_mas"]
_ST_LINEA_MENOS = estilos(VARIANTE_DEFECTO)["linea_menos"]
_ST_CONTENIDO = estilos(VARIANTE_DEFECTO)["contenido"]
_ST_MARCA_MAS = estilos(VARIANTE_DEFECTO)["marca_mas"]
_ST_MARCA_MENOS = estilos(VARIANTE_DEFECTO)["marca_menos"]
_ST_MAS_INTRA = estilos(VARIANTE_DEFECTO)["mas_intra"]
_ST_MENOS_INTRA = estilos(VARIANTE_DEFECTO)["menos_intra"]

# Tokens a nivel de PALABRA conservando los espacios: findall con esta regex
# reconstruye la linea byte a byte y el resaltado cae en palabras, no chars.
_RX_TOKEN = re.compile(r"\s+|\S+")

# Bajo este ratio de similitud entre el par -/+ NO se resalta intra-linea:
# en lineas casi disjuntas SequenceMatcher marcaria casi todo y seria ruido.
_UMBRAL_INTRA = 0.3

# Tope de longitud para el refinamiento intra (revision 2026-08-10): ratio() a
# nivel de char con autojunk=False es O(n^2) — un par de lineas minificadas de
# 100KB colgaria el pintado.
_TOPE_INTRA = 500


def _lineas_diff(viejo: str, nuevo: str, ruta: str, contexto: int) -> list:
    """unified_diff como lista de strings sin \\n; [] si no hay cambios."""
    nombre = (ruta or "").replace("\\", "/").split("/")[-1]
    fromf = f"a/{nombre}" if nombre else "antes"
    tof = f"b/{nombre}" if nombre else "despues"
    return list(difflib.unified_diff(
        viejo.splitlines(), nuevo.splitlines(),
        fromfile=fromf, tofile=tof, lineterm="", n=contexto))


def _pintada(texto, fondo):
    """Envuelve el Text de una linea -/+ para que el FONDO llegue al borde.

    Un Text con `style="on #..."` solo pinta hasta donde llega el texto. El
    Padding con expand=True (el defecto) renderiza a options.max_width con
    pad=True, o sea rellena cada linea fisica con espacios del mismo estilo:
    eso es "a todo el ancho" sin que diff_render tenga que adivinar el ancho
    de la terminal (que no conoce cuando se CONSTRUYE el Group; solo lo sabe
    la Console cuando lo IMPRIME).

    ANCHO (decision): las lineas mas largas que la terminal se PLIEGAN, no se
    recortan. Un diff que esconde la mitad derecha de una linea miente sobre
    lo que se cambio, y este render es lo que el dueno usa para aprobar
    ediciones; el fondo continuo hace evidente que las lineas fisicas de abajo
    son la misma linea logica. Los tramos plegados NO repiten la marca +/-:
    la marca marca la linea del diff, no el renglon de la pantalla. Terminal
    angosta: el Padding se encoge con options.max_width, asi que el fondo
    sigue llegando al borde sea cual sea el ancho (probado a 40, 56, 78, 90,
    100 y 200 columnas).

    El plegado es el de rich: corta en el hueco entre palabras y solo parte
    una palabra por la mitad si ella sola no entra (overflow 'fold'). Se deja
    asi a proposito aunque en una URL gigante deje un primer renglon casi
    vacio ("+URL =" y la URL entera abajo): partir identificadores por el
    medio para ganar media linea es peor cuando lo que se lee es codigo."""
    return Padding(texto, (0, 0, 0, 0), style=fondo)


def _linea_simple(prefijo: str, contenido: str, marca: str, fondo: str,
                  est: dict):
    # Text() SIN estilo base y todo por spans: con Text(prefijo, style=marca)
    # el 'bold' de la marca se hereda al contenido (rich compone base+span) y
    # la linea entera salia en negrita.
    t = Text()
    t.append(prefijo, style=marca)
    t.append(contenido, style=est["contenido"])
    return _pintada(t, fondo)


def _linea_intra(prefijo: str, toks: list, ops: list, lado: str,
                 marca: str, fondo: str, fuerte: str, est: dict):
    """Una linea -/+ con los spans cambiados en estilo fuerte.

    lado 'a' consume los indices i (linea vieja, tags replace/delete);
    lado 'b' consume los j (linea nueva, tags replace/insert). El tag que
    no aporta texto en ese lado produce un segmento vacio y se salta.
    """
    t = Text()
    t.append(prefijo, style=marca)
    for tag, i1, i2, j1, j2 in ops:
        seg = "".join(toks[i1:i2] if lado == "a" else toks[j1:j2])
        if not seg:
            continue
        t.append(seg, style=est["contenido"] if tag == "equal" else fuerte)
    return _pintada(t, fondo)


def _render_reemplazo(menos: list, mas: list, est: dict,
                      separador: str = "") -> list:
    """Bloque de lineas - seguidas de lineas +: los pares adyacentes (indice
    k con k) se comparan token a token y se resalta el span cambiado; las
    lineas sin par (borrado o insercion neta) van en color base. El orden
    del unified diff (todas las - y despues todas las +) se conserva."""
    par = min(len(menos), len(mas))
    ops_por_par: list = []
    for k in range(par):
        # Lineas largas: sin refinamiento intra (el diff de linea completa ya
        # informa) — ver _TOPE_INTRA.
        if len(menos[k]) > _TOPE_INTRA or len(mas[k]) > _TOPE_INTRA:
            ops_por_par.append((None, None, None))
            continue
        # El umbral se mide a nivel de CHAR: a nivel de token los espacios
        # (que casi siempre coinciden) inflan el ratio y lineas disjuntas
        # pasaban la puerta con todo marcado (ruido puro).
        parecido = difflib.SequenceMatcher(
            None, menos[k], mas[k], autojunk=False).ratio()
        if parecido < _UMBRAL_INTRA:
            ops_por_par.append((None, None, None))
            continue
        ta = _RX_TOKEN.findall(menos[k])
        tb = _RX_TOKEN.findall(mas[k])
        sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
        ops_por_par.append((ta, tb, sm.get_opcodes()))
    out = []
    for k, linea in enumerate(menos):
        if k < par and ops_por_par[k][2] is not None:
            out.append(_linea_intra("-" + separador, ops_por_par[k][0],
                                    ops_por_par[k][2], "a",
                                    est["marca_menos"], est["linea_menos"],
                                    est["menos_intra"], est))
        else:
            out.append(_linea_simple("-" + separador, linea,
                                     est["marca_menos"], est["linea_menos"],
                                     est))
    for k, linea in enumerate(mas):
        if k < par and ops_por_par[k][2] is not None:
            out.append(_linea_intra("+" + separador, ops_por_par[k][1],
                                    ops_por_par[k][2], "b",
                                    est["marca_mas"], est["linea_mas"],
                                    est["mas_intra"], est))
        else:
            out.append(_linea_simple("+" + separador, linea,
                                     est["marca_mas"], est["linea_mas"], est))
    return out


def render_bloque(menos, mas, *, variante: str = "", console=None,
                  sangria: int = 0, separador: str = ""):
    """Las lineas -/+ pintadas como bandas, SIN cabeceras de unified diff.

    Es la mitad de `render_diff` que sabe pintar, expuesta sola para el preview
    del agente (ux/renderer.py): ahi no hay un "antes" y un "despues" completos
    sino los trozos que la tool declaro (el bloque SEARCH/REPLACE, o las
    primeras lineas de lo escrito), y una cabecera '--- a/x.py' encima de dos
    lineas seria mas ruido que informacion.

    `menos` y `mas` son listas de lineas SIN el signo. Los pares adyacentes
    (menos[k] con mas[k]) reciben el resaltado intra-linea, igual que en el
    unified: en una edicion de una linea eso es exactamente la palabra que
    cambio.

    `sangria` sangra el bloque entero sin pintar el margen izquierdo (el
    Padding de fuera no lleva estilo; el de dentro es el que pinta), asi el
    preview cuelga debajo de la linea de la tool y la banda sigue llegando al
    borde derecho.

    `separador` es lo que va entre el signo y el contenido: '' para el unified
    de siempre, ' ' para el preview del agente (contrato con el clasificador
    del movil — ver la cabecera del modulo).

    Devuelve None sin rich o si no hay ni una linea que pintar.
    """
    if not _HAS_RICH:
        return None
    menos = [l for l in (menos or [])]
    mas = [l for l in (mas or [])]
    if not menos and not mas:
        return None
    est = estilos(variante or variante_activa(console))
    partes = _render_reemplazo(menos, mas, est, separador)
    grupo = Group(*partes)
    if sangria > 0:
        return Padding(grupo, (0, 0, 0, sangria))
    return grupo


def render_diff(viejo: str, nuevo: str, ruta: str = "", contexto: int = 2,
                console=None, variante: str = ""):
    """Diff unified pintado a todo el ancho, como rich renderable.

    Devuelve un rich Group (Text para cabeceras/@@/contexto, Padding con
    fondo para las lineas -/+) listo para console.print(), o None si no hay
    rich instalado o no hay cambios (el caller decide su fallback; None nunca
    debe pintarse).

    `console` NO se usa para el ancho a proposito — lo resuelve el Padding en
    tiempo de impresion, que es lo unico correcto si la terminal cambia de
    tamano entre construir el Group e imprimirlo. Si sirve para desempatar la
    variante de tema cuando COGNIA_THEME no dice nada (ver variante_activa).
    """
    if not _HAS_RICH:
        return None
    lineas = _lineas_diff(viejo, nuevo, ruta, contexto)
    if not lineas:
        return None
    est = estilos(variante or variante_activa(console))
    # Las dos primeras lineas son SIEMPRE las cabeceras ---/+++: se pintan
    # por posicion, no por prefijo, para no confundirlas con una linea
    # borrada cuyo contenido empiece por '--'. Las cabeceras y el contexto NO
    # llevan fondo: el bloque pintado tiene que ser exactamente lo que cambio.
    partes = [Text(lineas[0], style=est["hdr"]),
              Text(lineas[1], style=est["hdr"])]
    i = 2
    n = len(lineas)
    while i < n:
        ln = lineas[i]
        if ln.startswith("@@"):
            partes.append(Text(ln, style=est["hdr"]))
            i += 1
        elif ln.startswith("-"):
            menos = []
            while i < n and lineas[i].startswith("-"):
                menos.append(lineas[i][1:])
                i += 1
            mas = []
            while i < n and lineas[i].startswith("+"):
                mas.append(lineas[i][1:])
                i += 1
            partes.extend(_render_reemplazo(menos, mas, est))
        elif ln.startswith("+"):
            partes.append(_linea_simple("+", ln[1:], est["marca_mas"],
                                        est["linea_mas"], est))
            i += 1
        else:
            # linea de contexto (arranca con espacio en unified)
            partes.append(Text(" " + (ln[1:] if ln.startswith(" ") else ln)))
            i += 1
    return Group(*partes)


def resumen_diff(viejo: str, nuevo: str) -> str:
    """Resumen compacto del cambio: '+3 -1' (con U+2212 como signo menos).

    Para las lineas de una sola linea del modo remoto/pipe, donde el render
    rico no aplica. Sin cambios devuelve '' (el caller no pinta nada: un
    '+0 -0' seria ruido). No usa rich: cuenta sobre el unified con n=0."""
    lineas = _lineas_diff(viejo, nuevo, "", 0)
    if not lineas:
        return ""
    mas = menos = 0
    # lineas[2:]: saltar las cabeceras ---/+++ por POSICION (ver render_diff)
    for ln in lineas[2:]:
        if ln.startswith("@@"):
            continue
        if ln.startswith("+"):
            mas += 1
        elif ln.startswith("-"):
            menos += 1
    # − es el signo menos tipografico; va escapado para que el fuente
    # quede ASCII puro (leccion Latin-1 del repo: verificar en bytes)
    return f"+{mas} \u2212{menos}"
