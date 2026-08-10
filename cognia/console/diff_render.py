"""
cognia/console/diff_render.py
=============================
Diff delta-style MINIMAL para la capa de presentacion del CLI (plan B3).

POR QUE: el momento "el agente edito X" pintaba un unified diff plano linea a
linea; leer la INTENCION del cambio en 2 segundos exige ver la palabra exacta
que cambio. Esto colorea el unified diff (+ verde / - rojo / @@ dim) y ademas
resalta los spans cambiados DENTRO de cada par de lineas reemplazadas
(delta-style), con SequenceMatcher a nivel de palabra.

Alcance PODADO a proposito (plan B3): SIN side-by-side, SIN tree-sitter,
cero dependencias nuevas. Solo render local del terminal: el string RESULTADO
que consume el modelo (mini_diff en agent/edit_block.py) NO pasa por aca y
no cambia; el remoto y los pipes conservan el texto plano de siempre.

rich es opcional (mismo patron que cognia/cli.py y el resto de console/):
sin rich, render_diff devuelve None y el caller usa su fallback plano.
"""

from __future__ import annotations

import difflib
import re

try:
    from rich.console import Group
    from rich.text import Text
    _HAS_RICH = True
except Exception:  # pragma: no cover - entorno sin rich
    Group = None  # type: ignore
    Text = None   # type: ignore
    _HAS_RICH = False

# Estilos: el enfasis intra-linea usa reverse (delta-style) para que el span
# cambiado se lea de un golpe sea cual sea el tema de la terminal.
_ST_HDR = "dim"
_ST_MAS = "green"
_ST_MENOS = "red"
_ST_MAS_INTRA = "bold green reverse"
_ST_MENOS_INTRA = "bold red reverse"

# Tokens a nivel de PALABRA conservando los espacios: findall con esta regex
# reconstruye la linea byte a byte y el resaltado cae en palabras, no chars.
_RX_TOKEN = re.compile(r"\s+|\S+")

# Bajo este ratio de similitud entre el par -/+ NO se resalta intra-linea:
# en lineas casi disjuntas SequenceMatcher marcaria casi todo y seria ruido.
_UMBRAL_INTRA = 0.3


def _lineas_diff(viejo: str, nuevo: str, ruta: str, contexto: int) -> list:
    """unified_diff como lista de strings sin \\n; [] si no hay cambios."""
    nombre = (ruta or "").replace("\\", "/").split("/")[-1]
    fromf = f"a/{nombre}" if nombre else "antes"
    tof = f"b/{nombre}" if nombre else "despues"
    return list(difflib.unified_diff(
        viejo.splitlines(), nuevo.splitlines(),
        fromfile=fromf, tofile=tof, lineterm="", n=contexto))


def _linea_simple(prefijo: str, contenido: str, estilo: str):
    return Text(prefijo + contenido, style=estilo)


def _linea_intra(prefijo: str, toks: list, ops: list, lado: str,
                 base: str, fuerte: str):
    """Una linea -/+ con los spans cambiados en estilo fuerte.

    lado 'a' consume los indices i (linea vieja, tags replace/delete);
    lado 'b' consume los j (linea nueva, tags replace/insert). El tag que
    no aporta texto en ese lado produce un segmento vacio y se salta.
    """
    t = Text(prefijo, style=base)
    for tag, i1, i2, j1, j2 in ops:
        seg = "".join(toks[i1:i2] if lado == "a" else toks[j1:j2])
        if not seg:
            continue
        t.append(seg, style=base if tag == "equal" else fuerte)
    return t


def _render_reemplazo(menos: list, mas: list) -> list:
    """Bloque de lineas - seguidas de lineas +: los pares adyacentes (indice
    k con k) se comparan token a token y se resalta el span cambiado; las
    lineas sin par (borrado o insercion neta) van en color base. El orden
    del unified diff (todas las - y despues todas las +) se conserva."""
    par = min(len(menos), len(mas))
    ops_por_par: list = []
    for k in range(par):
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
            out.append(_linea_intra("-", ops_por_par[k][0], ops_por_par[k][2],
                                    "a", _ST_MENOS, _ST_MENOS_INTRA))
        else:
            out.append(_linea_simple("-", linea, _ST_MENOS))
    for k, linea in enumerate(mas):
        if k < par and ops_por_par[k][2] is not None:
            out.append(_linea_intra("+", ops_por_par[k][1], ops_por_par[k][2],
                                    "b", _ST_MAS, _ST_MAS_INTRA))
        else:
            out.append(_linea_simple("+", linea, _ST_MAS))
    return out


def render_diff(viejo: str, nuevo: str, ruta: str = "", contexto: int = 2,
                console=None):
    """Diff unified coloreado con resaltado intra-linea, como rich renderable.

    Devuelve un rich Group (de Text) listo para console.print(), o None si
    no hay rich instalado o no hay cambios (el caller decide su fallback;
    None nunca debe pintarse). `console` se acepta para que el caller pase
    su Console (ancho/tema) sin cambiar la firma a futuro; hoy no se usa.
    """
    if not _HAS_RICH:
        return None
    lineas = _lineas_diff(viejo, nuevo, ruta, contexto)
    if not lineas:
        return None
    # Las dos primeras lineas son SIEMPRE las cabeceras ---/+++: se pintan
    # por posicion, no por prefijo, para no confundirlas con una linea
    # borrada cuyo contenido empiece por '--'.
    partes = [Text(lineas[0], style=_ST_HDR), Text(lineas[1], style=_ST_HDR)]
    i = 2
    n = len(lineas)
    while i < n:
        ln = lineas[i]
        if ln.startswith("@@"):
            partes.append(Text(ln, style=_ST_HDR))
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
            partes.extend(_render_reemplazo(menos, mas))
        elif ln.startswith("+"):
            partes.append(_linea_simple("+", ln[1:], _ST_MAS))
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
    # \u2212 es el signo menos tipografico; va escapado para que el fuente
    # quede ASCII puro (leccion Latin-1 del repo: verificar en bytes)
    return f"+{mas} \u2212{menos}"
