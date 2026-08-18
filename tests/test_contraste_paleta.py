# -*- coding: utf-8 -*-
"""El juicio visual del 2026-08-17, convertido en chequeo que corre.

Una leccion en prosa no impide nada. El dueno midio hex por hex la pantalla
del CLI y encontro cuatro cosas; estos tests son las cuatro, ejecutables:

  A. SIETE verdes, dos fuera de la paleta. 'green' (#13a10e) y 'bright_green'
     (#16c60c) son verde PASTO y la rampa de Cognia es LIMA; encima los 32
     literales de cli.py no obedecian a /tema (el banner salia igual en claro).
  B. EL ROJO ERA LO MAS APAGADO de la pantalla por defecto: 3,12:1 contra un
     verde que iba de 5,5 a 15,4. Las lineas '-' de un diff y el 'fallo:' de
     una tool eran el texto mas tenue del terminal.
  C. 'alto_contraste' no cambiaba la RESPUESTA del modelo ni un hex, porque
     COGNIA_ACCENT vivia fuera del tema.
  18. El gato del banner arrancaba en 1,33:1 (invisible).

La medicion la hace scripts/contraste_tema.py -- el MISMO instrumento que
produjo la tabla de la entrega, no una copia. Esta calibrado: reproduce al
segundo decimal los numeros del juicio visual para todo token sin 'dim'
(marco 9,34 · '+' 5,53 · rojo 3,12 · banner 1,33 -> 13,86).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from cognia.ux import paleta

REPO = Path(__file__).resolve().parent.parent
MINIMO_AA = 4.5


def _medidor():
    """Carga scripts/contraste_tema.py por ruta (scripts/ no es paquete)."""
    pytest.importorskip("rich")
    ruta = REPO / "scripts" / "contraste_tema.py"
    spec = importlib.util.spec_from_file_location("contraste_tema", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 18. El gato del banner sube a VISIBLE
# ---------------------------------------------------------------------------

def test_el_banner_arranca_en_un_verde_que_se_ve():
    """Decision 18: el degradado arranca en un verde oscuro VISIBLE (~3:1),
    no en el #003300 de 1,33:1 que dejaba las primeras filas del gato en la
    nada. Se mantiene el efecto de rampa: sigue siendo el tono mas oscuro."""
    m = _medidor()
    fondo = m.FONDO["oscuro"]
    inicio = m.contraste(paleta.VERDE["profundo"], fondo)
    fin = m.contraste(paleta.VERDE["matrix"], fondo)
    assert inicio >= 2.9, f"el arranque del banner sigue invisible ({inicio:.2f}:1)"
    assert inicio < fin, "sin rampa: el arranque no puede ser mas claro que el fin"
    # y sigue siendo el escalon mas OSCURO de la identidad verde
    otros = [m.contraste(v, fondo) for k, v in paleta.VERDE.items()
             if k != "profundo"]
    assert inicio < min(otros)


# ---------------------------------------------------------------------------
# B. El rojo del tema por defecto
# ---------------------------------------------------------------------------

def test_el_rojo_del_tema_oscuro_pasa_AA():
    """3,12:1 era el elemento mas tenue de la pantalla. Piso: 4,5:1."""
    m = _medidor()
    tema = paleta.tema_cli("oscuro")
    fondo = m.FONDO["oscuro"]
    for token in ("err_cl", "borrado"):
        hexa = m.resolver(tema[token], "oscuro")
        c = m.contraste(hexa, fondo)
        assert c >= MINIMO_AA, f"{token} = {hexa} da {c:.2f}:1 (minimo {MINIMO_AA})"


def test_el_rojo_SIGUE_leyendose_rojo_y_no_es_el_ambar():
    """Subir el contraste no puede volverlo rosa ni acercarlo al aviso: un
    error y una advertencia tienen que distinguirse SIN leer el texto."""
    m = _medidor()
    import colorsys
    tema = paleta.tema_cli("oscuro")
    rojo = m.resolver(tema["err_cl"], "oscuro")
    ambar = m.resolver(tema["warn_cl"], "oscuro")

    def hsv(hexa):
        r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        return h * 360, s, v

    h_rojo, s_rojo, _ = hsv(rojo)
    h_ambar, _, _ = hsv(ambar)
    assert h_rojo > 330 or h_rojo < 20, f"{rojo} ya no es un rojo (hue {h_rojo:.0f})"
    assert s_rojo > 0.4, f"{rojo} esta desaturado: se lee gris rosado"
    sep = min(abs(h_rojo - h_ambar), 360 - abs(h_rojo - h_ambar))
    assert sep > 30, f"error ({h_rojo:.0f}) y aviso ({h_ambar:.0f}) casi el mismo tono"


def test_el_rojo_ya_no_es_lo_mas_tenue_de_la_pantalla():
    """El sintoma exacto que reporto el dueno: todo lo verde entre 5,5 y 15,4
    y el rojo debajo de todos. El error tiene que ganarle al menos al verde
    mas apagado del tema."""
    m = _medidor()
    tema = paleta.tema_cli("oscuro")
    fondo = m.FONDO["oscuro"]
    rojo = m.contraste(m.resolver(tema["err_cl"], "oscuro"), fondo)
    verde_mas_apagado = min(
        m.contraste(m.resolver(tema[t], "oscuro"), fondo)
        for t in ("ok", "ok_cl", "escrito", "spinner"))
    assert rojo >= verde_mas_apagado - 3.0, (
        f"el rojo ({rojo:.2f}) sigue muy por debajo del verde mas apagado "
        f"({verde_mas_apagado:.2f})")


# ---------------------------------------------------------------------------
# A. Un solo idioma de verde
# ---------------------------------------------------------------------------

# Los dos verdes PASTO que no salian de la paleta (Campbell).
PASTO = {"#13a10e", "#16c60c"}


def test_en_los_temas_oscuros_no_queda_verde_PASTO():
    """El 'cognia>' de respaldo quedaba dos lineas encima del 'cognia➤' del
    marco y eran visiblemente distintos. Ahora el verde de los temas oscuros
    ES la rampa (lima) y el pasto no aparece."""
    m = _medidor()
    for variante in ("oscuro", "alto_contraste"):
        tema = paleta.tema_cli(variante)
        for token, estilo in tema.items():
            hexa = m.resolver(estilo, variante)
            assert hexa not in PASTO, (
                f"{variante}.{token} ({estilo}) resuelve a {hexa}: verde pasto, "
                f"otro idioma que la rampa de la paleta")


def test_el_verde_de_LAS_TRES_variantes_SALE_de_su_rampa():
    """No basta con que no sea pasto: tiene que ser un escalon declarado de la
    rampa de ESA variante, o manana hay un octavo verde inventado.

    2026-08-17: antes esto solo miraba los dos temas oscuros porque 'claro'
    usaba 'dark_green' -- un nombre del cubo de 256, o sea el hex fijo #005f00,
    que no era ninguno de los verdes que el marco del prompt pintaba dos lineas
    mas abajo. Ahora las tres variantes tienen rampa propia y las tres se
    comprueban."""
    for variante in paleta.ORDEN_VARIANTES:
        rampa = set(paleta.rampa(variante).values())
        for rol in ("exito", "exito_fuerte", "actividad", "identidad",
                    "identidad_fuerte", "identidad_tenue"):
            valor = paleta.VARIANTES[variante][rol].replace("bold ", "")
            assert valor in rampa, (
                f"{variante}.{rol} = {valor!r} no es un escalon de la rampa "
                f"de '{variante}'")


def test_claro_NO_usa_la_rampa_lima_y_tiene_la_suya():
    """La rampa lima es ilegible sobre blanco (marco 1,96:1). Antes eso se
    'resolvia' mandando el tema claro a dark_green y dejando las piezas de
    identidad -- marco, prompt, texto escrito, banner -- en lima igual. Ahora
    'claro' tiene rampa propia: ningun escalon de la lima puede aparecer ahi,
    y todo lo que se lee pasa AA."""
    m = _medidor()
    fondo = m.FONDO["claro"]
    lima = set(paleta.VERDE.values())
    assert m.contraste(paleta.VERDE["marco"], fondo) < 3.0
    for nombre, hexa in paleta.rampa("claro").items():
        assert hexa not in lima, f"claro.{nombre} volvio a la lima ({hexa})"
    tema = paleta.tema_cli("claro")
    for token in ("ok", "ok_cl", "escrito", "spinner"):
        hexa = m.resolver(tema[token], "claro")
        assert hexa not in lima
        c = m.contraste(hexa, fondo)
        assert c >= MINIMO_AA, f"claro.{token} = {hexa} da {c:.2f}:1"


# ---------------------------------------------------------------------------
# A (segunda mitad). Los literales de cli.py obedecen al tema
# ---------------------------------------------------------------------------

FUENTES = ("cognia/cli.py", "cognia/ux/renderer.py", "cognia/ux/estilo.py")


def _fuente(rel):
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


def test_cli_no_vuelve_a_hardcodear_bright_green():
    """Eran 32 apariciones y NINGUNA obedecia a /tema: el banner salia verde
    pasto tambien en 'claro'. Los comentarios pueden nombrarlo (explican el
    bug); el codigo no."""
    for rel in FUENTES:
        for n, linea in enumerate(_fuente(rel).splitlines(), 1):
            codigo = linea.split("#", 1)[0]
            for prohibido in ('"bright_green"', "'bright_green'",
                              "[bright_green]", '"green"', "'green'"):
                assert prohibido not in codigo, (
                    f"{rel}:{n} usa el literal {prohibido}: tiene que pasar "
                    f"por un token del tema (paleta.TOKENS_CLI)")


def test_los_caminos_SIN_rich_tampoco_inventan_un_verde():
    """El 'cognia> ' de respaldo (input() pelado) escribia '\\033[92m' a mano:
    verde PASTO dos lineas encima del 'cognia➤' lima del marco. Los escapes
    crudos tienen que derivarse de la paleta, no ser literales."""
    src = _fuente("cognia/cli.py")
    crudos = re.findall(r'"\\033\[((?:\d+;)*\d+)m"', src)
    for sgr in crudos:
        assert sgr in ("0", "2"), (
            f"cli.py escribe el color ANSI crudo \\033[{sgr}m: tiene que salir "
            f"de paleta (ver _ansi_24bit)")
    import cognia.cli as C
    r, g, b = (int(paleta.VERDE["prompt"][i:i + 2], 16) for i in (1, 3, 5))
    # _g() (antes la constante _G) resuelve contra la variante ACTIVA; por
    # defecto 'oscuro'. Que siga a /tema lo comprueba test_paleta_identidad.
    assert C._g() == f"\033[38;2;{r};{g};{b}m"


def test_el_banner_cambia_con_el_tema():
    """Verificacion de punta a punta de la queja concreta: '/tema claro' tiene
    que cambiar el banner. Se pinta el banner REAL en dos temas y se comparan
    los ANSI, no la intencion."""
    pytest.importorskip("rich")
    from rich.console import Console
    import cognia.cli as C

    def _pintar(tema):
        """(texto plano, colores usados). Los colores se leen de los SEGMENTOS
        grabados, no de los bytes ANSI: rich baja a 16 colores cuando cree que
        corre en una consola Windows legacy (y esa deteccion la puede envenenar
        cualquier test previo que reemplace stdout), asi que un assert sobre
        '\\x1b[92m' pasa o falla segun el ORDEN de la suite. Cazado corriendo
        test_escenas_cli.py antes que este archivo."""
        con = Console(theme=C._THEMES[tema], record=True, width=110,
                      force_terminal=True, color_system="truecolor",
                      highlight=False)
        previa = C._console
        C._console = con
        try:
            C._print_banner_completo()
        finally:
            C._console = previa
        colores = set()
        for seg in con._record_buffer:
            if seg.style is not None and seg.style.color is not None:
                colores.add(seg.style.color.name)
        return con.export_text(styles=False), colores

    texto_osc, col_osc = _pintar("oscuro")
    _texto_cl, col_cl = _pintar("claro")
    assert "COGNIA" in texto_osc
    assert col_osc != col_cl, "el banner sale con los mismos colores en 'claro'"
    # el pasto no aparece en NINGUNO de los dos
    for nombre in ("bright_green", "green"):
        assert nombre not in col_osc and nombre not in col_cl, (
            f"el banner sigue pintando '{nombre}' (verde pasto)")
    # y en oscuro los verdes que quedan son los de la rampa
    assert paleta.VERDE["marco"] in col_osc


# ---------------------------------------------------------------------------
# La trampa que casi se cuela: 'bold <token>' se pinta SIN estilo
# ---------------------------------------------------------------------------

def test_ningun_estilo_mezcla_un_token_con_modificadores():
    """rich NO combina un token del tema con modificadores: 'bold marca' no
    lanza -- se pinta SIN NINGUN estilo, en silencio. Medido:

        Text.append('hola', 'bold marca')  ->  'hola\\n'   (cero ANSI)
        console.print('x', style='marca')  ->  '\\x1b[38;2;79;208;16mx'

    O sea que el fallo se ve exactamente igual que 'el color no se aplico
    porque el tema lo dice'. Los modificadores van DENTRO del valor del rol
    en paleta.VARIANTES ('identidad_fuerte' = 'bold #7ee62a')."""
    tokens = set(paleta.TOKENS_CLI)
    sospechosos = []
    for rel in FUENTES:
        src = _fuente(rel)
        candidatos = set(re.findall(r"\[(/?[a-z_0-9 ]+)\]", src))
        candidatos |= set(re.findall(r"style=[\"']([a-z_0-9 ]+)[\"']", src))
        candidatos |= set(re.findall(r",\s*[\"']([a-z_0-9 ]+)[\"']\)", src))
        for cand in candidatos:
            palabras = cand.lstrip("/").split()
            if len(palabras) > 1 and any(p in tokens for p in palabras):
                sospechosos.append(f"{rel}: {cand!r}")
    assert not sospechosos, (
        "estilos que mezclan un token del tema con modificadores (rich los "
        "descarta EN SILENCIO): " + "; ".join(sorted(sospechosos)))


# ---------------------------------------------------------------------------
# Piso general: ningun token de texto queda por debajo de AA
# ---------------------------------------------------------------------------

# Excepciones DECLARADAS, con su motivo. No son texto de lectura.
#
# 2026-08-17: se VACIA. Las cuatro que habia (footer e info_dim en oscuro y en
# claro) eran el punto 8 del juicio visual -- 3,15 y 2,38 sobre #0d1117, las
# dos ultimas cosas del tema por defecto por debajo del rojo que motivo todo el
# trabajo. Ahora miden 6,15 / 4,86 (oscuro) y 6,43 / 4,67 (claro) y siguen
# siendo lo mas apagado de su tema. Si vuelve a hacer falta una excepcion, va
# aca CON el numero y el motivo, no en silencio.
BAJO_AA_ACEPTADO: set = set()


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_los_tokens_de_texto_pasan_AA(variante):
    m = _medidor()
    tema = paleta.tema_cli(variante)
    fondo = m.FONDO[variante]
    flojos = []
    for token, estilo in sorted(tema.items()):
        if (variante, token) in BAJO_AA_ACEPTADO:
            continue
        hexa = m.resolver(estilo, variante)
        c = m.contraste(hexa, fondo)
        if c < MINIMO_AA:
            flojos.append(f"{token}={estilo} ({hexa}) {c:.2f}:1")
    assert not flojos, f"{variante}: " + "; ".join(flojos)
