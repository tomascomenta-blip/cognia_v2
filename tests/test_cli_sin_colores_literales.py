# -*- coding: utf-8 -*-
"""NI UN COLOR ESCRITO A MANO EN cognia/cli.py (2026-08-17, segunda pasada).

QUE MIDE. Que ningun estilo de rich escrito en cli.py sea un COLOR: ni como
literal ("cyan", "dim cyan", "bold magenta"), ni como etiqueta de markup
([cyan]...[/cyan], [dim]...[/dim]). Todo tiene que ser un TOKEN de
paleta.TOKENS_CLI, que es lo unico que /tema sabe repintar.

POR QUE EXISTE. La causa raiz que se corrigio en la rampa verde -- "hex y
nombres fijos que no dependen de la variante" -- seguia viva en el resto del
fichero: 104 colores a mano que la tabla del tema no veia. Medido con
scripts/contraste_tema.py sobre los fondos reales (#0d1117 / #fbfbfa):

    estilo literal   usos   oscuro  claro  alto_contraste
    "cyan"             87     5.94   2.96   5.94   <- el cuerpo de ~30 comandos
    "magenta"           7     2.36   4.87   2.36
    "dim cyan"          1     2.75   1.88   2.75   <- en TODOS los arranques
    "bright_cyan"       2    10.90   1.96  10.90
    "yellow"            7     7.23   3.98   7.23
    "dim" (sin color)   5     4.73   4.27   4.73

O sea: '/tema claro' no era usable (860 caracteres seguidos a 2.96 en el cuerpo
de los comandos slash) y el tema POR DEFECTO tenia DOS cosas peores que el rojo
3.12 que origino todo el trabajo -- magenta 2.36 y 'dim cyan' 2.75.

Se arreglaron marco, prompt, banner y diff -- las superficies que el juicio
nombro -- y quedo intacta la superficie MAS GRANDE del producto: lo que los
comandos imprimen. Una leccion en prosa no impide nada; esto es la leccion
convertida en un chequeo que corre.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from cognia.ux import paleta

# Tokens legitimos: los del tema, mas 'none' (Style.null explicito) y 'default'
# (el color de texto de la terminal, que es justo lo contrario de un color a
# mano). 'bold'/'italic'/'underline' son ESTRUCTURA, no color, y pasan.
TOKENS = set(paleta.TOKENS_CLI)
NEUTROS = {"none", "default", "bold", "italic", "underline", "reverse",
           "strike", "blink", "not bold"}
# 'dim' NO esta en NEUTROS a proposito: no es estructura. Es una mezcla al 40%
# contra el fondo (asi lo renderiza rich) y por eso hunde el contraste -- el
# 4.27 de la tabla de arriba es 'dim' pelado en el tema claro.


def _cli_fuente() -> str:
    import cognia.cli as C
    return Path(inspect.getfile(C)).read_text(encoding="utf-8", errors="replace")


def _es_color(texto: str) -> bool:
    """True si rich leeria `texto` como un estilo CON color propio.

    Se descarta primero todo lo que no puede ser un estilo (frases, rutas,
    literales largos) para no llamar a Style.parse sobre cada cadena del
    fichero, y se dejan pasar los tokens del tema: 'listado' no es un color
    para rich, pero tampoco tiene por que llegar a Style.parse."""
    from rich.style import Style
    t = (texto or "").strip()
    if not t or len(t) > 40 or "\n" in t:
        return False
    palabras = t.split()
    if len(palabras) > 3:
        return False
    if any(p in TOKENS or p in NEUTROS for p in palabras):
        return False
    try:
        st = Style.parse(t)
    except Exception:
        return False
    if st.dim:
        return True                      # 'dim' pelado tambien cuenta
    return st.color is not None and not st.color.is_default


# ---------------------------------------------------------------------------
# 1. Ningun literal de color como argumento de estilo
# ---------------------------------------------------------------------------
# Los sitios donde cli.py pinta: _show_response(txt, COLOR), _run(..., color=),
# console.print(..., style=), Panel(border_style=), rule(style=), Text(style=).
_ARG_ESTILO = {"color", "style", "border_style", "title_style",
               "subtitle_style", "header_style", "row_styles"}
_POSICIONAL = {"_show_response": 1, "_print_line": None}


def _nombre_llamada(nodo: ast.Call) -> str:
    f = nodo.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def test_cli_no_pasa_ningun_color_literal_como_estilo():
    pytest.importorskip("rich")
    arbol = ast.parse(_cli_fuente())
    culpables = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = _nombre_llamada(nodo)
        # argumentos con nombre (style=, color=, border_style=...)
        for kw in nodo.keywords:
            if kw.arg in _ARG_ESTILO and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                if _es_color(kw.value.value):
                    culpables.append(
                        f"linea {kw.value.lineno}: {nombre}({kw.arg}="
                        f"{kw.value.value!r})")
        # el color POSICIONAL de _show_response(texto, color)
        pos = _POSICIONAL.get(nombre)
        if pos is not None and len(nodo.args) > pos:
            a = nodo.args[pos]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                    and _es_color(a.value):
                culpables.append(
                    f"linea {a.lineno}: {nombre}(..., {a.value!r})")
    assert not culpables, (
        "cognia/cli.py vuelve a tener colores escritos a mano; usa un token de "
        "paleta.TOKENS_CLI (" + ", ".join(sorted(TOKENS)) + "):\n  "
        + "\n  ".join(culpables))


# ---------------------------------------------------------------------------
# 2. Ninguna etiqueta de markup que sea un color
# ---------------------------------------------------------------------------
_ETIQUETA = re.compile(r"\[/?([a-z][a-z0-9_ ]{0,30})\]")


def test_cli_no_usa_etiquetas_de_markup_con_color():
    pytest.importorskip("rich")
    culpables = []
    for n, linea in enumerate(_cli_fuente().split("\n"), 1):
        if linea.lstrip().startswith("#"):
            continue          # los comentarios CITAN los colores viejos
        for etiqueta in _ETIQUETA.findall(linea):
            if _es_color(etiqueta):
                culpables.append(f"linea {n}: [{etiqueta}] -> {linea.strip()[:80]}")
    assert not culpables, (
        "cognia/cli.py vuelve a tener markup de color; usa un token del tema:\n  "
        + "\n  ".join(culpables))


# ---------------------------------------------------------------------------
# 3. Los tokens nuevos existen en LAS TRES variantes y pasan el piso AA
# ---------------------------------------------------------------------------
# Un token que solo existe en 'oscuro' revienta con KeyError al hacer /tema, y
# uno que existe pero mide 2.96 es el bug que este fichero persigue.
NUEVOS = ("listado", "titulo", "borde")
AA = 4.5


def test_los_tokens_nuevos_estan_en_las_tres_variantes():
    for token in NUEVOS:
        assert token in paleta.TOKENS_CLI, f"{token} no esta en TOKENS_CLI"
        for variante in paleta.ORDEN_VARIANTES:
            assert token in paleta.tema_cli(variante), \
                f"{token} falta en la variante {variante}"


def test_ningun_token_del_tema_baja_del_piso_AA():
    """El piso de la entrega: 4.5:1 en las TRES variantes, sin excepciones.

    Los elementos GRAFICOS que WCAG deja en 3:1 (el arranque del degradado del
    banner) no son tokens del tema y se defienden en
    test_contraste_por_variante.py; aca todo es texto."""
    medidor = _medidor()
    flojos = []
    for variante, fila in medidor.medir().items():
        for token, d in fila.items():
            if token.startswith(("=", "~")):
                continue      # bandas del diff y piezas fuera del tema
            if d["contraste"] < AA:
                flojos.append(f"{variante}.{token} = {d['contraste']} "
                              f"({d['estilo']})")
    assert not flojos, "por debajo de AA:\n  " + "\n  ".join(flojos)


def _medidor():
    """scripts/contraste_tema.py, el MISMO instrumento de la entrega."""
    import importlib.util
    pytest.importorskip("rich")
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "contraste_tema.py"
    spec = importlib.util.spec_from_file_location("contraste_tema", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 4. El cuerpo de un listado NO es el acento configurable
# ---------------------------------------------------------------------------
def test_el_cuerpo_del_listado_no_sigue_al_acento_del_usuario():
    """/color tine lo que CONTESTA EL MODELO. Elegir un acento para las
    respuestas no es elegir de que color sale /stats: por eso 'listado' es un
    rol aparte y no un alias de 'respuesta'."""
    assert paleta.TOKENS_CLI["listado"] != paleta.TOKENS_CLI["respuesta"]
    assert paleta.ACENTO_DEFECTO == "respuesta"
