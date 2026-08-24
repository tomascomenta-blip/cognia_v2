# -*- coding: utf-8 -*-
"""
tests/test_harness_banner_adaptativo.py
=======================================
Regresion de cognia/harness/banner_adaptativo.py (2026-08-12).

QUE PROTEGE: el banner de arranque medido ocupa ~45 lineas y en una terminal
de 30-40 filas empuja la guia y el prompt fuera de pantalla. El modulo decide
QUE variante de banner corresponde al tamano real y reparte las filas; estos
tests fijan los umbrales, el recorte del arte REAL (leido del fuente de
cognia/cli.py, sin importarlo ni tocarlo) y el contrato de "devuelve datos,
nunca imprime".

Sin mocks: se usan una Console de rich de verdad, un subproceso real con la
salida redirigida (para el caso sin TTY) y el arte real del repo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata

import pytest

from cognia.harness import banner_adaptativo as ba

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTE_MODULO = os.path.join(RAIZ, "cognia", "harness", "banner_adaptativo.py")
FUENTE_CLI = os.path.join(RAIZ, "cognia", "cli.py")


def _arte_real() -> list:
    """Las lineas del banner REAL del CLI, leidas del fuente (no se importa
    cognia.cli: arrastra medio producto y el test debe ser barato)."""
    txt = open(FUENTE_CLI, encoding="utf-8").read()
    m = re.search(r'_BANNER_RAW = """(.*?)"""', txt, re.DOTALL)
    assert m, "no se encontro _BANNER_RAW en cognia/cli.py"
    return m.group(1).split("\n")


# ---------------------------------------------------------------------------
# medir_terminal
# ---------------------------------------------------------------------------
def test_medir_terminal_devuelve_tupla_desempaquetable():
    cols, filas = ba.medir_terminal()
    assert isinstance(cols, int) and isinstance(filas, int)
    assert cols > 0 and filas > 0
    m = ba.medir_terminal()
    assert (m.columnas, m.filas) == (m[0], m[1])
    assert isinstance(m.es_tty, bool) and isinstance(m.por_defecto, bool)


def test_medir_terminal_respeta_la_console_de_rich():
    # rich es dependencia dura del repo: se usa una Console REAL con tamano fijo.
    rich_console = pytest.importorskip("rich.console")
    c = rich_console.Console(width=123, height=41)
    m = ba.medir_terminal(console=c)
    # La Console MANDA: se compara contra su propio .size, que es lo que rich
    # va a usar para pintar (en la consola legacy de Windows rich reserva una
    # columna y reporta 122, no 123 — copiar ese numero es justamente el punto).
    assert (m.columnas, m.filas) == tuple(c.size)
    assert m.filas == 41 and 122 <= m.columnas <= 123
    assert m.por_defecto is False


def test_medir_terminal_sin_tty_marca_el_defecto():
    """Salida redirigida (subproceso real con stdout a un pipe): no hay TTY,
    asi que devuelve el defecto y lo MARCA en vez de inventar un tamano."""
    codigo = (
        "import json, sys;"
        "sys.path.insert(0, r'%s');"
        "from cognia.harness import banner_adaptativo as ba;"
        "m = ba.medir_terminal();"
        "print(json.dumps([m.columnas, m.filas, m.es_tty, m.por_defecto]))"
    ) % RAIZ
    env = dict(os.environ)
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                       text=True, env=env, cwd=RAIZ, timeout=120)
    assert r.returncode == 0, r.stderr
    cols, filas, es_tty, por_defecto = json.loads(r.stdout.strip().splitlines()[-1])
    assert es_tty is False and por_defecto is True
    assert (cols, filas) == (80, 24)


# ---------------------------------------------------------------------------
# elegir_variante: los umbrales son el corazon del modulo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filas,columnas,esperado", [
    (60, 120, "completo"),
    (48, 80, "completo"),      # el borde exacto entra
    (47, 120, "medio"),        # una fila menos ya no
    (48, 79, "medio"),         # alto de sobra pero ancho corto: no rompe el arte
    (40, 100, "medio"),        # el caso MEDIDO que hoy falla
    (34, 64, "medio"),
    (33, 100, "compacto"),
    (34, 63, "compacto"),      # el logo en bloques no entra: sin arte
    (24, 80, "compacto"),      # terminal por defecto
    (20, 30, "compacto"),
    (19, 200, "minimo"),
    (40, 29, "minimo"),
])
def test_elegir_variante_umbrales(filas, columnas, esperado):
    assert ba.elegir_variante(filas, columnas) == esperado


def test_forzado_manda_sobre_la_medida_y_la_basura_se_ignora():
    assert ba.elegir_variante(200, 200, "minimo") == "minimo"
    assert ba.elegir_variante(5, 5, "completo") == "completo"
    assert ba.elegir_variante(10, 10, "  MEDIO  ") == "medio"
    assert ba.elegir_variante(10, 10, "mínimo") == "minimo"   # con acento
    # basura -> se decide por la medida, no se rompe el arranque
    assert ba.elegir_variante(60, 120, "gigante") == "completo"
    assert ba.elegir_variante(60, 120, "") == "completo"


def test_variante_del_entorno_lee_cognia_banner_y_el_legacy_min():
    assert ba.variante_del_entorno({"COGNIA_BANNER": "compacto"}) == "compacto"
    # 'min' es lo que cli.py usa HOY para el arranque de ~5 lineas
    assert ba.variante_del_entorno({"COGNIA_BANNER": "min"}) == "compacto"
    assert ba.variante_del_entorno({}) == ""
    assert ba.variante_del_entorno({"COGNIA_BANNER": "cualquiera"}) == ""


# ---------------------------------------------------------------------------
# recortar_arte sobre el ARTE REAL del repo
# ---------------------------------------------------------------------------
def test_recortar_arte_es_un_tramo_contiguo_sin_bordes_en_blanco():
    arte = _arte_real()
    assert len(arte) > 30, "el banner real deberia tener mas de 30 lineas"
    for disp in range(1, len(arte) + 5):
        out = ba.recortar_arte(arte, disp)
        assert len(out) <= disp
        if out:
            assert out[0].strip() and out[-1].strip(), "borde en blanco"
            # tramo CONTIGUO del original (no se saltean lineas del medio)
            i = arte.index(out[0])
            assert arte[i:i + len(out)] == out


def test_recortar_arte_recorta_simetrico_y_conserva_el_centro():
    arte = ["", "a", "b", "c", "d", "e", "f", ""]
    assert ba.recortar_arte(arte, 6) == ["a", "b", "c", "d", "e", "f"]
    assert ba.recortar_arte(arte, 4) == ["b", "c", "d", "e"]
    # sobrante impar: la linea de mas cae abajo (no se descabeza el dibujo)
    assert ba.recortar_arte(arte, 3) == ["b", "c", "d"]
    assert ba.recortar_arte(arte, 0) == []
    assert ba.recortar_arte([], 10) == []
    assert ba.recortar_arte(["", "  ", ""], 10) == []


def test_mitad_superior_conserva_la_cabeza_del_gato():
    arte = _arte_real()
    mitad = ba.mitad_superior(arte)
    limpio = [l for l in arte if l.strip() or True]
    assert 0 < len(mitad) <= (len(arte) + 1) // 2
    # es el principio del arte, no el final: el logo en bloques queda fuera
    assert mitad[0].strip()
    assert "█" not in "".join(mitad), "la mitad superior no lleva el logo"


# ---------------------------------------------------------------------------
# cabecera_compacta
# ---------------------------------------------------------------------------
def test_cabecera_compacta_tres_o_cuatro_lineas_con_estilos_logicos():
    cab = ba.cabecera_compacta("4.6.3", "qwythos-9b (:8080)",
                               os.path.join(RAIZ), modo="flota", ancho=80)
    assert 3 <= len(cab) <= 4
    for texto, estilo in cab:
        assert isinstance(texto, str) and isinstance(estilo, str)
        assert estilo in ("marca", "acento", "atenuado")
        assert ba.ancho_visible(texto) <= 80
    assert cab[0][0] == "cognia v4.6.3" and cab[0][1] == "marca"
    assert "qwythos-9b" in cab[1][0] and cab[1][1] == "acento"
    assert cab[2][0].startswith("dir")
    assert cab[-1][0].startswith("modo") and "flota" in cab[-1][0]
    # sin modo: 3 lineas
    assert len(ba.cabecera_compacta("4.6.3", "m", RAIZ, ancho=80)) == 3


def test_cabecera_sin_backend_no_miente():
    cab = ba.cabecera_compacta("4.6.3", "", RAIZ, ancho=80)
    assert "sin backend" in cab[1][0]
    assert cab[1][1] == "atenuado"     # no se pinta como dato vivo


def test_acortar_ruta_usa_tilde_y_elipsis_en_el_medio():
    home = os.path.expanduser("~")
    ruta = os.path.join(home, "Desktop", "cognia_v2")
    corta = ba.acortar_ruta(ruta, 80)
    assert corta.startswith("~") and corta.endswith("cognia_v2")
    apretada = ba.acortar_ruta(ruta, 16)
    assert ba.ancho_visible(apretada) <= 16
    assert "…" in apretada or "..." in apretada
    assert apretada.endswith("cognia_v2"[-4:])   # la cola (el proyecto) sobrevive
    # con fallback ASCII no queda ningun caracter no imprimible en cp1252
    ascii_ = ba.acortar_ruta(ruta, 16, ascii_seguro=True)
    ascii_.encode("cp1252")
    assert "..." in ascii_


def test_acortar_ruta_no_desborda_con_directorios_de_doble_ancho():
    """Regresion: el corte iba por INDICE de caracter, asi que un directorio en
    CJK (dos columnas por glifo) devolvia el doble de ancho del pedido y la
    linea 'dir' se envolvia — rompiendo el reparto de filas de plan_arranque,
    que da por buena la altura de la cabecera."""
    ruta = "C:/Users/usuario/proyectos/" + ("\u6f22\u5b57" * 8) + "/cognia_v2"
    for ancho in range(6, 60):
        corta = ba.acortar_ruta(ruta, ancho)
        assert ba.ancho_visible(corta) <= ancho, (ancho, corta)
    # y la cola (el nombre del proyecto) sigue sobreviviendo al corte
    assert ba.acortar_ruta(ruta, 30).endswith("cognia_v2")


def test_cabecera_y_plan_caben_con_ruta_de_doble_ancho():
    ruta = "D:/" + ("\u6f22\u5b57" * 20) + "/proyecto"
    for ancho in (30, 40, 80):
        for texto, _ in ba.cabecera_compacta("4.6.3", "m", ruta, ancho=ancho):
            assert ba.ancho_visible(texto) <= ancho, (ancho, texto)
    plan = ba.plan_arranque(arte=_arte_real(), version="4.6.3", modelo="m",
                            directorio=ruta, filas=24, columnas=40, forzado="")
    for texto, _ in plan["cabecera"]:
        assert ba.ancho_visible(texto) <= plan["columnas"], texto


def test_truncar_no_parte_secuencias_ni_deja_combinantes_huerfanos():
    # el corte por ancho nunca se pasa, aunque el glifo mida 2 columnas
    for ancho in range(1, 25):
        assert ba.ancho_visible(ba.truncar("\u6f22\u5b57" * 10, ancho)) <= ancho
    # la tilde combinante viaja con su letra base (no queda suelta al inicio)
    con_tilde = "cafe\u0301" * 6
    for ancho in range(4, 30):
        corta = ba.acortar_ruta(con_tilde, ancho)
        assert ba.ancho_visible(corta) <= ancho
        cola = corta.split("\u2026")[-1] if "\u2026" in corta else corta
        assert not (cola and unicodedata.combining(cola[0])), corta


def test_linea_identidad_es_una_sola_linea():
    out = ba.linea_identidad("4.6.3", "qwythos-9b", ancho=60)
    assert len(out) == 1
    texto, estilo = out[0]
    assert "\n" not in texto and ba.ancho_visible(texto) <= 60
    assert "cognia v4.6.3" in texto and estilo == "marca"


# ---------------------------------------------------------------------------
# guia_rapida
# ---------------------------------------------------------------------------
def test_guia_rapida_alinea_columnas_y_cabe_en_el_ancho():
    guia = ba.guia_rapida(ancho=80)
    assert 6 <= len(guia) <= 8
    anchos = {ba.ancho_visible(cmd) for cmd, _ in guia}
    assert len(anchos) == 1, "la columna de comandos tiene que quedar alineada"
    for cmd, desc in guia:
        assert ba.ancho_visible(cmd + desc) <= 80
        assert desc.strip()
    textos = [c.strip() for c, _ in guia]
    assert "/hacer" in textos and "chat" in textos


def test_guia_rapida_respeta_el_ancho_real_y_no_inventa_entradas():
    guia = ba.guia_rapida(ancho=34)
    for cmd, desc in guia:
        assert ba.ancho_visible(cmd + desc) <= 34
    tres = ba.guia_rapida([("/uno", "desc uno"), ("/dos", "d"), ("/tres", "d")],
                          ancho=80)
    assert len(tres) == 3
    # dict tambien vale, y el tope se respeta
    d = {f"/c{i}": f"desc {i}" for i in range(20)}
    assert len(ba.guia_rapida(d, ancho=80, maximo=4)) == 4


def test_guia_rapida_vacia_no_resucita_los_defaults():
    """Una lista vacia es 'aca no va guia', no 'poneme las 8 de la casa': el
    integrador que decide no pintar guia no puede recibir 8 entradas de vuelta
    (y el presupuesto de filas de plan_arranque se iria al diablo)."""
    assert ba.guia_rapida([], ancho=80) == []
    assert ba.guia_rapida({}, ancho=80) == []
    assert ba.guia_rapida(ancho=80)          # sin argumento: los defaults
    assert ba.guia_rapida(None, ancho=80)    # None explicito: idem


def test_linea_atajos_una_tupla_que_cabe():
    texto, estilo = ba.linea_atajos(ancho=40)
    assert estilo == "atenuado" and ba.ancho_visible(texto) <= 40
    assert "Tab" in texto
    texto_ascii, _ = ba.linea_atajos(ancho=80, ascii_seguro=True)
    texto_ascii.encode("ascii")


# ---------------------------------------------------------------------------
# plan_arranque: el reparto de filas (el fallo medido)
# ---------------------------------------------------------------------------
def _lineas_del_layout(plan) -> int:
    """Cuenta las lineas que el integrador va a pintar SIGUIENDO el layout
    documentado en plan_arranque (las lineas en blanco cuentan: son las que
    hacian que el prompt naciera fuera de pantalla)."""
    n = len(plan["arte"]) + (1 if plan["arte"] else 0)      # arte + blanco
    n += len(plan["cabecera"])
    if plan["guia"]:
        n += 2 + len(plan["guia"])                          # blanco + titulo
    if plan["atajos"]:
        n += 2                                              # blanco + atajos
    return n


@pytest.mark.parametrize("forzado", ["", "completo", "medio", "compacto", "minimo"])
def test_plan_arranque_nunca_desborda_la_pantalla(forzado):
    """La regresion central: en NINGUN tamano (ni con la variante forzada) el
    banner puede pasarse de las filas de la terminal — hoy ~45 lineas en una
    de 30-40 empujan la guia y el prompt fuera de pantalla."""
    arte = _arte_real()
    for filas in range(10, 70, 2):
        for columnas in (40, 70, 80, 100, 140):
            plan = ba.plan_arranque(arte=arte, version="4.6.3",
                                    modelo="qwythos-9b (:8080)",
                                    directorio=RAIZ, modo="flota",
                                    filas=filas, columnas=columnas,
                                    forzado=forzado)
            assert plan["variante"] in ba.VARIANTES
            total = _lineas_del_layout(plan)
            assert total == plan["lineas_estimadas"], (filas, columnas, plan)
            assert total + ba.RESERVA_PROMPT <= filas, (
                filas, columnas, plan["variante"], total)


def test_plan_arranque_completo_dibuja_el_gato_entero():
    arte = _arte_real()
    plan = ba.plan_arranque(arte=arte, version="4.6.3", modelo="m",
                            directorio=RAIZ, filas=60, columnas=120,
                            forzado="")
    assert plan["variante"] == "completo"
    esperado = [l for l in arte]
    while esperado and not esperado[0].strip():
        esperado.pop(0)
    while esperado and not esperado[-1].strip():
        esperado.pop()
    assert plan["arte"] == esperado, "el gato completo no se toca"
    assert "█" in "".join(plan["arte"]), "el logo COGNIA sigue ahi"


def test_plan_arranque_medio_recorta_pero_conserva_al_gato():
    arte = _arte_real()
    plan = ba.plan_arranque(arte=arte, version="4.6.3", modelo="m",
                            directorio=RAIZ, filas=36, columnas=100,
                            forzado="")
    assert plan["variante"] == "medio"
    assert plan["arte"], "el gato NO se esconde: sigue habiendo arte"
    assert len(plan["arte"]) < len(arte)
    assert all(l in arte for l in plan["arte"])


def test_plan_arranque_compacto_y_minimo():
    arte = _arte_real()
    plan = ba.plan_arranque(arte=arte, version="4.6.3", modelo="m",
                            directorio=RAIZ, filas=24, columnas=80, forzado="")
    assert plan["variante"] == "compacto"
    assert plan["arte"] == []
    assert 3 <= len(plan["cabecera"]) <= 4
    assert 0 < len(plan["guia"]) <= 4

    mini = ba.plan_arranque(arte=arte, version="4.6.3", modelo="m",
                            directorio=RAIZ, filas=12, columnas=60, forzado="")
    assert mini["variante"] == "minimo"
    assert mini["arte"] == [] and mini["guia"] == [] and mini["atajos"] is None
    assert len(mini["cabecera"]) == 1


# ---------------------------------------------------------------------------
# Contrato del modulo
# ---------------------------------------------------------------------------
def test_nada_imprime(capsys):
    arte = _arte_real()
    ba.medir_terminal()
    ba.elegir_variante(40, 100)
    ba.recortar_arte(arte, 12)
    ba.mitad_superior(arte)
    ba.cabecera_compacta("4.6.3", "m", RAIZ, "flota", ancho=80)
    ba.guia_rapida(ancho=80)
    ba.linea_atajos(80)
    ba.plan_arranque(arte=arte, version="4.6.3", filas=40, columnas=100)
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == "", "el modulo devuelve datos, no pinta"


def test_estilos_logicos_existen_en_el_tema_del_cli():
    """Los nombres logicos tienen que traducir a estilos que el tema del CLI
    ya define (si no, el integrador pintaria en blanco).

    2026-08-17: se valida contra cognia/ux/paleta.py (los tokens del tema
    viven ahi desde que cli.py deriva su color de la paleta) en vez de buscar
    la clave como texto en el fuente de cli.py."""
    from cognia.ux import paleta
    for logico, real in ba.ESTILOS_TEMA.items():
        assert ba.a_estilo_rich(logico) == real
        assert real in paleta.TOKENS_CLI, f"el tema del CLI no define {real}"
    assert ba.a_estilo_rich("desconocido") == "desconocido"


def test_fuente_ascii_puro_y_sin_dependencias_de_pintado():
    """Leccion Latin-1 del repo: el fuente se verifica en BYTES. Y el modulo
    no debe importar rich/prompt_toolkit (devuelve datos: degrada solo)."""
    crudo = open(FUENTE_MODULO, "rb").read()
    crudo.decode("ascii")
    txt = crudo.decode("ascii")
    assert "import rich" not in txt and "from rich" not in txt
    assert "import prompt_toolkit" not in txt
    assert "from prompt_toolkit" not in txt
    assert "2026-08-12" in txt.split('"""')[1], "falta la fecha en el docstring"


# ---------------------------------------------------------------------------
# Layout a dos columnas (juicio visual 2026-08-24: el logo partido a 100)
# ---------------------------------------------------------------------------
def test_ancho_arte_mide_la_columna_mas_ancha_en_columnas_visibles():
    assert ba.ancho_arte([]) == 0
    assert ba.ancho_arte(None) == 0
    assert ba.ancho_arte(["ab", "abcd", ""]) == 4
    assert ba.ancho_arte(["中文"]) == 4        # CJK: 2 columnas cada uno
    assert ba.ancho_arte(_arte_real()) == 63


def test_cabe_dos_columnas_exige_arte_y_guia_enteros():
    # Gato real (63) + guia real (44) + marco (4) + separacion (2) = 113.
    assert ba.cabe_dos_columnas(113, 63, 44) is True
    assert ba.cabe_dos_columnas(120, 63, 44) is True
    assert ba.cabe_dos_columnas(112, 63, 44) is False
    assert ba.cabe_dos_columnas(100, 63, 44) is False   # el caso del juez
    assert ba.cabe_dos_columnas(80, 63, 44) is False
    # Sin arte no hay nada que poner al lado; basura no lanza.
    assert ba.cabe_dos_columnas(200, 0) is False
    assert ba.cabe_dos_columnas("ancho", 63) is False
    # El default de ancho_guia es la guia real de cli.py.
    assert ba.ANCHO_GUIA == 44
    assert ba.cabe_dos_columnas(113, 63) is True


def test_partir_arte_y_logo_separa_el_gato_del_logo_real():
    arte = _arte_real()
    gato, logo = ba.partir_arte_y_logo(arte)
    assert gato + logo == arte
    assert not any("█" in l for l in gato)
    assert sum(1 for l in logo if "█" in l or "╗" in l) == 5
    # El separador punteado y sus blancos viajan con el logo (aire intacto).
    assert any("·" in l for l in logo)
    assert not any("·" in l for l in gato)
    # Sin bloques: todo es gato.
    assert ba.partir_arte_y_logo(["a", "b"]) == (["a", "b"], [])
    assert ba.partir_arte_y_logo([]) == ([], [])


# ---------------------------------------------------------------------------
# P7 (2026-08-24): las variantes por ALTURA siguen mandando sobre el registro
# de estilos (banner.arte.animacion, alineacion...): con COGNIA_BANNER=compacto
# no hay arte y no hay Live; con 'medio' el gato se recorta y el logo sale
# entero aunque el arte este animado y centrado.
# ---------------------------------------------------------------------------

def _cli_con_consola(monkeypatch, alto: int, ancho: int = 120):
    """cognia.cli con una Console truecolor grabadora de `alto` filas, sin
    backend ni bus (los monkeypatch de siempre) y con el registro limpio."""
    import io
    import cognia.cli as cli
    from rich.console import Console
    from cognia import backend_activo
    from cognia.ux import aspecto as A
    from cognia.ux import glow as G
    for k in ("COGNIA_BANNER", "COGNIA_ANIMACION", "COGNIA_THEME", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    G.vaciar_memo()
    con = Console(file=io.StringIO(), width=ancho, height=alto, force_terminal=True,
                  color_system="truecolor", legacy_windows=False,
                  theme=cli._THEMES[cli._THEME_ORDER[cli._theme_idx]], highlight=False)
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_arranque_ux", lambda: None)
    monkeypatch.setattr(backend_activo, "estado",
                        lambda: {"url": "http://127.0.0.1:8080", "modelo": "m.gguf",
                                 "puerto": 8080, "avisos": []})
    return cli, con, A, G


@pytest.fixture
def _limpiar_registro():
    from cognia.ux import aspecto as A
    from cognia.ux import glow as G
    yield
    A.reset()
    G.forzar_capacidades(None)
    G.vaciar_memo()


def _grabar_live(monkeypatch) -> list:
    from rich import live as rich_live
    abiertas = []
    original = rich_live.Live.start

    def _start(self, *a, **k):
        abiertas.append(self)
        return original(self, *a, **k)
    monkeypatch.setattr(rich_live.Live, "start", _start)
    return abiertas


_BRAILLE = re.compile("[⠁-⣿]")
_CURSOR_UP = re.compile(r"\x1b\[\d*A")


def test_compacto_y_minimo_no_pintan_arte_ni_abren_live_aunque_el_registro_anime(
        monkeypatch, _limpiar_registro):
    cli, con, A, G = _cli_con_consola(monkeypatch, alto=24)
    assert not A.poner("banner.arte", "animacion.activa", True)
    G.forzar_capacidades(G.Caps("truecolor", True, ""))
    abiertas = _grabar_live(monkeypatch)
    for variante in ("compacto", "minimo"):
        monkeypatch.setattr(cli, "_variante_banner", lambda v=variante: v)
        con.file.seek(0)
        con.file.truncate()
        cli._print_startup_panel()
        salida = con.file.getvalue()
        assert not _BRAILLE.search(salida) and "█" not in salida, variante
        assert not abiertas and not _CURSOR_UP.search(salida)
        assert "cognia" in salida and "m.gguf" in salida


def test_medio_recorta_el_gato_conserva_el_logo_y_anima_si_cabe(monkeypatch, _limpiar_registro):
    """A 40 filas la variante 'medio' deja un banner que CABE, asi que la
    animacion del registro si corre (Live abierta) y el frame final tiene el
    logo entero y menos gato; la alineacion centro no rompe el recorte."""
    cli, con, A, G = _cli_con_consola(monkeypatch, alto=40)
    for prop, valor in (("animacion.activa", True), ("animacion.solo_al_llegar", True),
                        ("animacion.velocidad", 5), ("alineacion", "centro")):
        assert not A.poner("banner.arte", prop, valor)
    G.forzar_capacidades(G.Caps("truecolor", True, ""))
    monkeypatch.setattr(cli, "_variante_banner", lambda: "medio")
    abiertas = _grabar_live(monkeypatch)
    cli._print_startup_panel()
    salida = con.file.getvalue()
    assert len(abiertas) == 1 and _CURSOR_UP.search(salida)
    # el frame FINAL (lo que queda en el scrollback): tras el ultimo cursor-up
    final = _CURSOR_UP.split(salida)[-1]
    limpio = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", final)
    lineas = limpio.splitlines()
    assert len([l for l in lineas if "█" in l or "╗" in l]) == 5
    gato = [l for l in lineas if _BRAILLE.search(l)]
    assert 6 <= len(gato) < 25, len(gato)
    assert len(lineas) <= 40 - 3, len(lineas)
    assert lineas[0].startswith(" ") and "COGNIA" in lineas[0]      # centrado
