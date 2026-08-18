"""
UNA fuente de verdad para el color (2026-08-17).

El color de Cognia vivia en tres sitios que no se hablaban: los tres rich.Theme
hardcodeados de cli.py, los hex a mano del marco del prompt y del gradiente del
banner, y el COLORS violeta de cognia/tui/theme.py. Resultado: abrir la TUI
parecia entrar en otra aplicacion. Ahora todo deriva de cognia/ux/paleta.py.

Una leccion en prosa no impide nada: estos tests son el chequeo que corre. Cada
uno falla si alguien vuelve a hardcodear un color o si las tres variantes del
tema se colapsan en una.
"""
import inspect
import re

import pytest

from cognia.ux import paleta


# ---------------------------------------------------------------------------
# 1. La paleta es datos planos y coherentes
# ---------------------------------------------------------------------------

_HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_todos_los_hex_de_la_paleta_son_hex_validos():
    tablas = [paleta.SEMANTICO, paleta.SUPERFICIE, paleta.MENU_PROMPT,
              paleta.FONDO_VARIANTE]
    tablas += list(paleta.RAMPA.values()) + list(paleta.DIFF_FONDO.values())
    for tabla in tablas:
        for clave, valor in tabla.items():
            assert _HEX.match(valor), f"{clave}={valor!r} no es un hex #rrggbb"


def test_las_tres_rampas_tienen_LOS_MISMOS_escalones():
    """Una rampa a la que le falta un escalon deja una pieza de identidad sin
    color en esa variante (y el consumidor revienta con KeyError en runtime,
    que es la peor forma de enterarse)."""
    escalones = {"profundo", "solido", "marco", "prompt", "texto", "estado",
                 "matrix"}
    assert set(paleta.RAMPA) == set(paleta.ORDEN_VARIANTES)
    for variante, verde in paleta.RAMPA.items():
        assert set(verde) == escalones, f"{variante} no tiene los 7 escalones"
    assert paleta.VERDE is paleta.RAMPA["oscuro"]


def test_cada_variante_tiene_sus_cuatro_bandas_de_diff():
    """Punto 3: el diff con fondo no obedecia a /tema (en terminal blanca era
    una isla negra). Las bandas las va a leer cognia/console/diff_render.py."""
    assert set(paleta.DIFF_FONDO) == set(paleta.ORDEN_VARIANTES)
    for variante in paleta.ORDEN_VARIANTES:
        bandas = paleta.diff_fondos(variante)
        assert set(bandas) == {"mas", "menos", "mas_intra", "menos_intra"}
    # y no son las mismas en oscuro y en claro: eso era el bug
    assert (paleta.diff_fondos("oscuro")["mas"]
            != paleta.diff_fondos("claro")["mas"])
    assert (paleta.diff_fondos("oscuro")["menos"]
            != paleta.diff_fondos("claro")["menos"])


def test_la_paleta_no_importa_frameworks():
    """Datos planos: si importa rich o textual deja de servir a los dos."""
    fuente = inspect.getsource(paleta)
    for prohibido in ("import rich", "from rich", "import textual",
                      "from textual"):
        assert prohibido not in fuente, f"paleta.py importa {prohibido}"


def test_el_ok_semantico_ES_el_verde_solido():
    # No son dos verdes parecidos: es el mismo, por construccion.
    assert paleta.SEMANTICO["ok"] == paleta.VERDE["solido"]


# ---------------------------------------------------------------------------
# 2. Las tres variantes existen y son DISTINGUIBLES
# ---------------------------------------------------------------------------

def test_las_tres_variantes_siguen_existiendo():
    assert paleta.ORDEN_VARIANTES == ["oscuro", "claro", "alto_contraste"]
    for nombre in paleta.ORDEN_VARIANTES:
        assert paleta.DESCRIPCION_VARIANTES[nombre].strip()


def test_las_tres_variantes_no_se_colapsaron():
    """Derivar de una paleta comun no puede volverlas el mismo tema: 'claro'
    tiene que seguir siendo legible sobre fondo blanco y 'alto_contraste'
    tiene que seguir gritando."""
    temas = {n: paleta.tema_cli(n) for n in paleta.ORDEN_VARIANTES}
    pares = [("oscuro", "claro"), ("oscuro", "alto_contraste"),
             ("claro", "alto_contraste")]
    for a, b in pares:
        distintos = sum(1 for k in temas[a] if temas[a][k] != temas[b][k])
        assert distintos >= 10, (
            f"'{a}' y '{b}' solo difieren en {distintos} tokens: se estan "
            f"colapsando en un tema unico")


def test_cada_variante_cubre_todos_los_tokens():
    for nombre in paleta.ORDEN_VARIANTES:
        tema = paleta.tema_cli(nombre)
        assert set(tema) == set(paleta.TOKENS_CLI)
        assert all(v.strip() for v in tema.values())


def test_spinner_y_pensar_son_el_MISMO_verde_en_las_tres():
    """El fix de 2026-08-10 (la actividad tambien en verde) no puede volver a
    romperse en una sola variante: comparten rol en TOKENS_CLI."""
    assert paleta.TOKENS_CLI["spinner"] == paleta.TOKENS_CLI["pensar"]
    for nombre in paleta.ORDEN_VARIANTES:
        tema = paleta.tema_cli(nombre)
        assert tema["spinner"] == tema["pensar"] == tema["escrito"]


# ---------------------------------------------------------------------------
# 3. El gradiente del banner
# ---------------------------------------------------------------------------

def test_el_gradiente_es_una_rampa_monotona_sin_saltos():
    """Decision 18 cambio el ARRANQUE (#003300 -> #00701c), no la mecanica:
    el degradado sigue siendo una rampa continua entre los dos extremos de la
    paleta. Lo que se verifica es la forma, no el hex de antes."""
    n = 47
    tonos = paleta.gradiente_banner(n)
    assert len(tonos) == n
    verdes = [int(t[3:5], 16) for t in tonos]
    azules = [int(t[5:7], 16) for t in tonos]
    assert verdes == sorted(verdes) and azules == sorted(azules)
    assert all(t.startswith("#00") for t in tonos), "la rampa deja de ser verde"
    # sin escalones: entre dos lineas contiguas nunca hay un salto grande
    assert max(b - a for a, b in zip(verdes, verdes[1:])) <= 6
    # y en las tres variantes el canal VERDE manda sobre el rojo y el azul en
    # todos los escalones: un degradado que se vuelve gris no es la marca
    for variante in paleta.ORDEN_VARIANTES:
        for t in paleta.gradiente_banner(n, variante):
            r, g, b = (int(t[i:i + 2], 16) for i in (1, 3, 5))
            assert g > r and g > b, f"{variante}: {t} ya no es verde"


def test_el_gradiente_con_una_sola_linea_no_revienta():
    # El banner recortado (variante 'medio') puede quedar en 1 linea; el
    # calculo viejo daba t=0 -> el color de arranque.
    assert paleta.gradiente_banner(1) == [paleta.VERDE["profundo"]]
    assert paleta.gradiente_banner(0) == []
    for variante in paleta.ORDEN_VARIANTES:
        assert (paleta.gradiente_banner(1, variante)
                == [paleta.rampa(variante)["profundo"]])


def test_el_gradiente_arranca_y_termina_en_la_paleta():
    for variante in paleta.ORDEN_VARIANTES:
        tonos = paleta.gradiente_banner(30, variante)
        assert tonos[0] == paleta.rampa(variante)["profundo"]
        assert tonos[-1] == paleta.rampa(variante)["matrix"]
    # y el defecto sigue siendo el oscuro (compatibilidad de la firma vieja)
    assert paleta.gradiente_banner(30) == paleta.gradiente_banner(30, "oscuro")


def test_el_gradiente_del_banner_APUNTA_al_lado_correcto_en_cada_variante():
    """Decision 18 pedia que el gato se vea DESDE ARRIBA. En fondo oscuro eso
    es arrancar oscuro y subir; en fondo claro es exactamente lo contrario, y
    hasta hoy 'claro' heredaba la rampa oscura: el logotipo COGNIA cerraba en
    el verde matrix, 1,32:1 sobre #fbfbfa -- la marca era lo MENOS visible de
    la pantalla. Lo que se comprueba es la LUMINANCIA, no el hex."""
    def lum(hexa):
        def lin(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    for variante in paleta.ORDEN_VARIANTES:
        tonos = paleta.gradiente_banner(40, variante)
        fondo = lum(paleta.FONDO_VARIANTE[variante])
        # el arranque siempre es el extremo mas cercano al fondo, el cierre el
        # mas lejano: eso es "arrancar visible y ganar peso" en los dos casos
        assert abs(lum(tonos[0]) - fondo) < abs(lum(tonos[-1]) - fondo), (
            f"{variante}: el degradado del banner va al reves")
        if fondo > 0.5:   # terminal clara: de claro a OSCURO
            assert lum(tonos[0]) > lum(tonos[-1])
        else:             # terminal oscura: de oscuro a BRILLANTE
            assert lum(tonos[0]) < lum(tonos[-1])


# ---------------------------------------------------------------------------
# 4. cli.py DERIVA (no vuelve a hardcodear)
# ---------------------------------------------------------------------------

def test_los_temas_del_cli_salen_de_la_paleta():
    pytest.importorskip("rich")
    from rich.style import Style
    import cognia.cli as C
    assert list(C._THEME_ORDER) == paleta.ORDEN_VARIANTES
    for nombre in paleta.ORDEN_VARIANTES:
        esperado = paleta.tema_cli(nombre)
        estilos = C._THEMES[nombre].styles
        for token, valor in esperado.items():
            # comparacion por Style parseado: rich normaliza el orden de los
            # modificadores ('italic dim white' -> 'dim italic white')
            assert estilos[token] == Style.parse(valor), (
                f"{nombre}.{token}: el CLI pinta {estilos[token]!r} y la "
                f"paleta dice {valor!r}")


def test_el_marco_del_prompt_sale_de_la_paleta_Y_DE_LA_VARIANTE():
    """El bloqueante del 2026-08-17: el marco, el 'cognia' y el texto que se
    escribe eran hex resueltos al IMPORTAR contra la rampa oscura, y
    prompt_toolkit no pasa por el tema de rich. Con '/tema claro' el prompt
    quedaba en 1,19:1 sobre blanco. Ahora el estilo se arma con la rampa de la
    variante que se le pida, y las tres dan tres marcos distintos."""
    pytest.importorskip("prompt_toolkit")
    import cognia.cli as C
    vistos = {}
    for variante in paleta.ORDEN_VARIANTES:
        verde = paleta.rampa(variante)
        reglas = dict(C._estilo_prompt(variante).style_rules)
        assert reglas["marco"] == verde["marco"]
        assert reglas["cognia"].startswith(verde["prompt"])
        assert reglas[""].startswith(verde["texto"])
        assert verde["estado"] in reglas["estado"]
        vistos[variante] = reglas["marco"]
    assert len(set(vistos.values())) == 3, (
        f"dos variantes comparten el marco del prompt: {vistos}")


def test_el_verde_de_los_caminos_crudos_sigue_a_la_variante():
    """Los caminos sin rich (input() pelado, banner de emergencia) escriben el
    escape a mano. Era una constante de import: en 'claro' el 'cognia> ' de
    respaldo salia en lima a 1,53:1 sobre blanco."""
    import cognia.cli as C
    previo = C._theme_idx
    try:
        escapes = set()
        for i, variante in enumerate(paleta.ORDEN_VARIANTES):
            C._theme_idx = i
            assert C._variante_actual() == variante
            r, g, b = (int(paleta.rampa(variante)["prompt"][j:j + 2], 16)
                       for j in (1, 3, 5))
            assert C._g() == f"\033[38;2;{r};{g};{b}m"
            escapes.add(C._g())
        assert len(escapes) == 3
    finally:
        C._theme_idx = previo


def test_cli_no_reescribe_los_hex_de_la_identidad():
    """El guardian de verdad: ningun hex de la paleta puede aparecer como
    literal en cli.py, o volvemos a tener dos fuentes de verdad."""
    import cognia.cli as C
    from pathlib import Path
    fuente = Path(inspect.getfile(C)).read_text(encoding="utf-8",
                                                errors="replace")
    tablas = list(paleta.RAMPA.values()) + list(paleta.DIFF_FONDO.values())
    tablas.append(paleta.MENU_PROMPT)
    for tabla in tablas:
        for clave, valor in tabla.items():
            assert valor not in fuente, (
                f"cli.py hardcodea {valor} ({clave}): tiene que pedirlo a "
                f"cognia/ux/paleta.py")


def test_el_acento_por_defecto_es_el_TOKEN_de_texto_normal():
    """Decision 17 del dueno (2026-08-17): la respuesta del modelo va en color
    de texto NORMAL; el color queda para la interfaz. El defecto es un TOKEN
    del tema (no un color) para que /tema lo pueda cambiar."""
    import cognia.cli as C
    assert paleta.ACENTO_DEFECTO == "respuesta"
    assert paleta.ACENTO_DEFECTO in paleta.TOKENS_CLI
    assert C._DEFAULT_ACCENT == paleta.ACENTO_DEFECTO
    # 'texto normal' de verdad en los dos temas que se leen en terminal comun
    for variante in ("oscuro", "claro"):
        assert paleta.tema_cli(variante)["respuesta"] == "default"


def test_un_COGNIA_ACCENT_guardado_NO_se_pisa():
    """El defecto cambio; la config del usuario no. Quien tenga cyan guardado
    en ~/.cognia/config.env sigue viendo cyan (el env var se lee primero).

    En SUBPROCESO a proposito: _ACCENT se resuelve en el import de cognia.cli
    y un importlib.reload dentro de la suite depende de que otro test no haya
    tocado sys.modules (falla real, cazada al correr los 65 archivos juntos).
    Medido: 0,5 s."""
    import os
    import subprocess
    import sys
    entorno = dict(os.environ, COGNIA_ACCENT="cyan", PYTHONUTF8="1")
    r = subprocess.run(
        [sys.executable, "-c",
         "import cognia.cli as C; print(C._ACCENT, C._DEFAULT_ACCENT)"],
        capture_output=True, text=True, timeout=120, env=entorno,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    assert r.returncode == 0, r.stderr[-1500:]
    acento, defecto = r.stdout.split()[:2]
    assert acento == "cyan", "se piso la configuracion del usuario"
    assert defecto == "respuesta"


def test_alto_contraste_TAMBIEN_sube_la_respuesta():
    """Punto C del juicio visual: 'alto_contraste' subia todo (detalle, verbo
    de tool...) menos el bloque de texto mas grande de la pantalla, porque el
    acento vivia FUERA del tema. Ahora es un rol del tema y tambien cambia."""
    normal = paleta.tema_cli("oscuro")["respuesta"]
    alto = paleta.tema_cli("alto_contraste")["respuesta"]
    assert normal != alto, "alto_contraste deja la respuesta igual que oscuro"


# ---------------------------------------------------------------------------
# 5. La TUI hereda el verde (decision del dueno)
# ---------------------------------------------------------------------------

def test_la_tui_hereda_el_verde_y_no_vuelve_al_violeta():
    pytest.importorskip("textual")
    from cognia.tui.theme import COLORS
    assert COLORS["accent"] == paleta.ACENTO_HEX
    assert COLORS["accent"] != "#a371f7", "la TUI volvio al violeta"
    # y el resto de la superficie tambien sale de la paleta
    assert COLORS["bg"] == paleta.SUPERFICIE["fondo"]
    assert COLORS["err"] == paleta.SEMANTICO["error"]


def test_el_theme_de_textual_usa_el_accent_de_la_paleta():
    pytest.importorskip("textual")
    from cognia.tui.theme import cognia_theme
    tema = cognia_theme()
    assert tema.primary == paleta.ACENTO_HEX
    assert tema.accent == paleta.ACENTO_HEX
