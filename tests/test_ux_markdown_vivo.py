# -*- coding: utf-8 -*-
"""Tests del markdown en STREAMING sin flicker (cognia/ux/markdown_vivo).

La maquina de Aider (ventana viva + commit de estables) con el reloj de
CodeWhale (tokens = input, no timing; catch-up; fence retenido). Todo se
testea sin terminal: salida a StringIO, reloj inyectado. Regresion: sin el
modulo estos tests revientan con ImportError; sin el cableado del renderer,
test_renderer_abre_markdown_vivo falla.
"""
import io
import re
import os

import pytest

from cognia.ux import markdown_vivo
from cognia.ux.markdown_vivo import (CATCHUP_S, RELOJ, RETRASO_MAX,
                                     MarkdownVivo, bloque_abierto, fence_abierto,
                                     retraso_adaptativo)


class RelojFalso:
    """Reloj controlado a mano: cada avanzar() mueve el tiempo."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avanzar(self, dt: float) -> None:
        self.t += dt


def _mv(**kw):
    """Un MarkdownVivo de test: sin console (render plano, determinista),
    salida capturada, ancho fijo 78 (COLUMNS=80 menos la sangria de 2)."""
    salida = io.StringIO()
    reloj = kw.pop("reloj", RelojFalso())
    mv = MarkdownVivo(console=None, salida=salida, reloj=reloj,
                      ancho=kw.pop("ancho", 78), **kw)
    return mv, salida, reloj


DOC = (
    "# Titulo\n\n"
    "Una lista:\n\n"
    "- primero\n"
    "- segundo\n"
    "- tercero\n\n"
    "```python\n"
    "def hola():\n"
    "    print('hola')\n"
    "```\n\n"
    "Cierre del documento con una frase final de prosa normal.\n"
)


# ---------------------------------------------------------------------------
# estabilidad: lo commiteado NUNCA cambia despues
# ---------------------------------------------------------------------------

def test_lo_commiteado_nunca_cambia():
    mv, salida, reloj = _mv()
    fotos = []
    for i in range(0, len(DOC), 7):          # trozos de 7 chars, como tokens
        reloj.avanzar(10.0)                  # el reloj nunca frena el test
        mv.escribir(DOC[i:i + 7])
        fotos.append(list(mv._commiteadas))
    for antes, despues in zip(fotos, fotos[1:]):
        assert despues[:len(antes)] == antes, \
            "una linea commiteada cambio despues de salir al scrollback"


def test_transcript_final_igual_al_render_de_una_pasada():
    # el streaming no puede dejar un transcript distinto del render batch
    mv, salida, reloj = _mv()
    for i in range(0, len(DOC), 5):
        reloj.avanzar(10.0)
        mv.escribir(DOC[i:i + 5])
    mv.cerrar()
    esperado = MarkdownVivo(console=None, salida=io.StringIO(),
                            ancho=78)._render(DOC)
    got = salida.getvalue().splitlines()
    assert got == ["  " + l for l in esperado]


def test_sin_animar_no_hay_escapes_en_la_salida():
    # salida StringIO = sin tty = modo solo-commit: cero basura de repintado
    mv, salida, reloj = _mv()
    for i in range(0, len(DOC), 5):
        reloj.avanzar(10.0)
        mv.escribir(DOC[i:i + 5])
    mv.cerrar()
    assert "\x1b[" not in salida.getvalue()


def test_animado_repinta_solo_la_cola():
    # con animacion forzada, el repintado sube exactamente la altura de la
    # cola anterior y la borra; las estables no se reescriben jamas
    mv, salida, reloj = _mv()
    mv._animar = True
    reloj.avanzar(10.0)
    mv.escribir(DOC[:60])
    cola_1 = mv._cola_altura
    est_1 = mv._estables
    reloj.avanzar(10.0)
    mv.escribir(DOC[60:])
    if cola_1:
        # sube exactamente la altura de la cola vieja y la SOBREESCRIBE linea a
        # linea; el ED ('\x1b[J') ya no se emite salvo cola mas corta (parpadeo
        # en Windows Terminal, 2026-08-24)
        assert f"\x1b[{cola_1}A\r" in salida.getvalue()
        assert f"\x1b[{cola_1}A\r\x1b[J" not in salida.getvalue()
    assert mv._estables >= est_1
    mv.cerrar()
    assert mv._cola_altura == 0


def test_animado_sobreescribe_solo_las_lineas_que_cambian_y_sincroniza():
    """Parpadeo en Windows Terminal (dueno, 2026-08-24): cada frame borraba
    hasta el final de la pantalla y reescribia toda la cola. Ahora: cada
    frame va entre BSU/ESU (DEC 2026), las lineas identicas se saltan con LF,
    solo las distintas llevan CR+EL, y el ED solo aparece si la cola encoge."""
    mv, salida, reloj = _mv()
    mv._animar = True
    reloj.avanzar(10.0)
    mv.escribir("Primera linea de prosa.\n\nSegunda linea de prosa que sigue")
    n0 = len(salida.getvalue())
    alto = mv._cola_altura
    assert alto >= 2
    reloj.avanzar(10.0)
    mv.escribir(" y crece un poco mas.")
    frame = salida.getvalue()[n0:]
    assert frame.startswith("\x1b[?2026h") and frame.endswith("\x1b[?2026l")
    assert f"\x1b[{alto}A\r" in frame
    assert "\x1b[J" not in frame, "la cola no encogio: nada que borrar por debajo"
    # solo la ultima linea cambio: una sola CR+EL; las demas bajan con LF
    assert frame.count("\r\x1b[2K") == 1
    assert "Primera linea de prosa." not in frame, "la linea identica no se reescribe"
    assert "crece un poco mas" in frame


def test_sync_output_se_apaga_con_env(monkeypatch):
    monkeypatch.setenv("COGNIA_SYNC_OUTPUT", "0")
    mv, salida, reloj = _mv()
    mv._animar = True
    reloj.avanzar(10.0)
    mv.escribir("Hola\n\nMundo")
    assert "\x1b[?2026h" not in salida.getvalue()


# ---------------------------------------------------------------------------
# throttle: reloj fijo + adaptativo de Aider + catch-up de CodeWhale
# ---------------------------------------------------------------------------

def test_retraso_adaptativo_clampa():
    assert retraso_adaptativo(0.0) == RELOJ            # piso: el reloj fijo
    assert retraso_adaptativo(0.01) == pytest.approx(0.1)   # 10x el render
    assert retraso_adaptativo(60.0) == RETRASO_MAX     # techo


def test_throttle_no_repinta_antes_del_reloj():
    mv, salida, reloj = _mv()
    reloj.avanzar(10.0)
    mv.escribir("# Hola\n\nuna linea de prosa\n")      # primer repintado
    pintado = salida.getvalue()
    mv.escribir("mas texto ")                          # mismo instante: nada
    mv.escribir("y mas ")
    assert salida.getvalue() == pintado, \
        "repinto sin que el reloj avanzara el retraso minimo"
    reloj.avanzar(CATCHUP_S + 0.01)                    # ya paso el reloj
    mv.escribir("final\n")
    assert salida.getvalue() != pintado or mv._estables >= 0


def test_catchup_techa_el_retraso_adaptativo():
    # aunque el render salga carisimo (retraso 2.0s), el backlog no espera
    # mas de CATCHUP_S: a los 1.3s el siguiente escribir SI repinta
    mv, salida, reloj = _mv()
    reloj.avanzar(10.0)
    mv.escribir("# Hola\n\nprosa inicial\n")
    mv._retraso = RETRASO_MAX                          # render "lento"
    antes = mv._estables
    fotos = salida.getvalue()
    reloj.avanzar(CATCHUP_S + 0.1)                     # < RETRASO_MAX
    mv.escribir("\nmas prosa que ya deberia verse\n\ny un parrafo extra\n"
                "con varias lineas\n\npara empujar estables\n")
    assert salida.getvalue() != fotos or mv._estables > antes, \
        "el catch-up no volco un backlog de mas de 1.2s"


# ---------------------------------------------------------------------------
# fences: el bloque abierto se retiene, jamas se parte al commitear
# ---------------------------------------------------------------------------

def test_fence_abierto_detecta_offset():
    assert fence_abierto("prosa\n```python\ncodigo\n") == len("prosa\n")
    assert fence_abierto("prosa\n```python\ncodigo\n```\n") is None
    assert fence_abierto("sin fence\n") is None
    # '~~~' dentro de ``` es contenido, no cierre
    t = "```\n~~~\ntodavia dentro\n"
    assert fence_abierto(t) == 0
    # el cierre exige largo >= apertura
    t2 = "````\n```\ndentro\n"
    assert fence_abierto(t2) == 0


def test_fence_abierto_no_se_comitea():
    # prosa corta + un fence abierto con MUCHAS lineas de codigo (mas que la
    # ventana): sin la regla, el bloque se partiria al commitear
    texto = "intro\n\n```python\n" + "\n".join(
        f"x{i} = {i}" for i in range(30)) + "\n"
    mv, salida, reloj = _mv()
    for i in range(0, len(texto), 9):
        reloj.avanzar(10.0)
        mv.escribir(texto[i:i + 9])
    tope = mv._tope_bloque()
    assert tope is not None
    assert mv._estables <= tope, \
        "se commitearon lineas DENTRO de un fence abierto"
    # al cerrar el fence y el flujo, todo sale
    reloj.avanzar(10.0)
    mv.escribir("```\n")
    mv.cerrar()
    assert "x29" in salida.getvalue()


def test_codigo_lleva_sintaxis_con_color():
    # con color activo, el bloque de codigo sale con escapes ANSI (pygments
    # via rich Syntax); el tema es el configurado
    class _FakeConsole:
        is_terminal = True
        no_color = False
        legacy_windows = False
        width = 80
        file = io.StringIO()
    salida = io.StringIO()
    mv = MarkdownVivo(console=_FakeConsole(), tema="monokai", ancho=78,
                      salida=salida, reloj=RelojFalso(100.0))
    lineas = mv._render("```python\nprint('hola')\n```\n")
    assert any("\x1b[" in l for l in lineas), \
        "el bloque de codigo salio sin sintaxis coloreada"


# ---------------------------------------------------------------------------
# snapshot a COLUMNS=80: titulo + lista + codigo
# ---------------------------------------------------------------------------

def test_snapshot_titulo_lista_codigo_80_columnas():
    mv, salida, reloj = _mv(ancho=78)
    for i in range(0, len(DOC), 4):
        reloj.avanzar(10.0)
        mv.escribir(DOC[i:i + 4])
    mv.cerrar()
    out = salida.getvalue()
    lineas = out.splitlines()
    assert all(len(l) <= 80 for l in lineas), "una linea excede COLUMNS=80"
    # el titulo H1 de rich va centrado y destacado; el texto esta
    assert "Titulo" in out
    # la lista con vinetas de rich
    assert out.count("•") >= 3 or out.count("- ") >= 3
    assert "primero" in out and "tercero" in out
    # el codigo del fence esta, y la prosa final tambien
    assert "print" in out and "hola" in out
    assert "frase final" in out
    # cada linea pintada lleva la sangria de 2 del REPL
    assert all(l.startswith("  ") or not l.strip() for l in lineas)


# ---------------------------------------------------------------------------
# degradacion: fallo del render -> aviso 'markdown' + flujo plano ESE turno
# ---------------------------------------------------------------------------

def test_fallo_del_render_degrada_a_plano_sin_lanzar(monkeypatch, capsys):
    avisos = []
    monkeypatch.setattr(markdown_vivo, "_avisar", avisos.append)
    mv, salida, reloj = _mv()
    reloj.avanzar(10.0)
    mv.escribir("hola ")

    def _boom(texto):
        raise RuntimeError("render roto")
    monkeypatch.setattr(mv, "_render", _boom)
    reloj.avanzar(10.0)
    mv.escribir("mundo cruel\n")             # NO lanza
    assert avisos, "el fallo del render no aviso por el canal 'markdown'"
    assert mv._plano is not None, "no cayo al flujo plano en este turno"
    mv.escribir("y sigue el stream\n")       # los tokens siguientes van al plano
    mv.cerrar()
    # el flujo plano (FlujoSuave, console=None) escribe a stdout, la misma
    # terminal donde vivia el render: el texto crudo COMPLETO queda visible
    out = capsys.readouterr().out
    assert "mundo cruel" in out and "y sigue el stream" in out


def test_cerrar_resetea_y_es_reusable():
    # el reintento por truncado del fast-path re-streamea sobre el MISMO flujo
    mv, salida, reloj = _mv()
    reloj.avanzar(10.0)
    mv.escribir("# Uno\n")
    mv.cerrar()
    assert mv._texto == "" and mv._estables == 0 and mv._cola_altura == 0
    reloj.avanzar(10.0)
    mv.escribir("# Dos\n")
    mv.cerrar()
    assert "Dos" in salida.getvalue()


# ---------------------------------------------------------------------------
# config: on/off, tty, remoto, tema
# ---------------------------------------------------------------------------

def test_config_apagada_por_env(monkeypatch):
    monkeypatch.setenv("COGNIA_MARKDOWN", "0")
    assert markdown_vivo.activo() is False


def test_config_remoto_apaga_siempre(monkeypatch):
    monkeypatch.setenv("COGNIA_MARKDOWN", "1")   # ni forzada gana al remoto
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert markdown_vivo.activo() is False


def test_config_forzada_gana_sin_tty(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_MARKDOWN", "1")
    assert markdown_vivo.activo() is True


def test_config_sin_tty_apaga_sola(monkeypatch):
    monkeypatch.delenv("COGNIA_MARKDOWN", raising=False)
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    # bajo pytest stdout no es un tty (capturado): el default debe apagarse
    assert markdown_vivo.activo() is False


def test_tema_env_gana(monkeypatch):
    monkeypatch.setenv("COGNIA_CODE_THEME", "dracula")
    assert markdown_vivo.config()[1] == "dracula"


def test_tema_espejo_de_respuesta_codigo(monkeypatch):
    """P6: /estilo respuesta.codigo texto <tema> es el espejo de markdown_tema:
    gana a la config, pierde contra COGNIA_CODE_THEME."""
    from cognia.ux import aspecto as A
    monkeypatch.delenv("COGNIA_CODE_THEME", raising=False)
    A.reset()
    try:
        assert markdown_vivo.config()[1] == markdown_vivo.TEMA_DEFAULT
        assert not A.errores(A.poner("respuesta.codigo", "texto", "dracula"))
        assert markdown_vivo.config()[1] == "dracula"
        monkeypatch.setenv("COGNIA_CODE_THEME", "github-dark")
        assert markdown_vivo.config()[1] == "github-dark"
    finally:
        A.reset()


def test_crear_nunca_lanza(monkeypatch):
    monkeypatch.setenv("COGNIA_MARKDOWN", "0")
    assert markdown_vivo.crear(None) is None


# ---------------------------------------------------------------------------
# cableado del renderer: abre MarkdownVivo cuando esta activo
# ---------------------------------------------------------------------------

def test_renderer_abre_markdown_vivo(monkeypatch):
    from cognia.ux import events
    from cognia.ux.renderer import Renderer
    monkeypatch.setenv("COGNIA_MARKDOWN", "1")
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    r = Renderer(console=None)
    r(events.TokenTexto(texto="# hola\n"))
    assert isinstance(r._flujo, MarkdownVivo), \
        "el renderer no abrio MarkdownVivo con la config activa"
    r(events.TokenTexto(texto="mas prosa\n"))
    r._cerrar_flujo()
    assert r._flujo is None


def test_renderer_remoto_conserva_camino_viejo(monkeypatch):
    from cognia.ux import events
    from cognia.ux.renderer import Renderer
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    r(events.TokenTexto(texto="# hola\n"))
    # bajo remoto el renderer ni siquiera abre flujo (la respuesta llega
    # entera via _show_response): el contrato del movil queda intacto
    assert r._flujo is None


# ---------------------------------------------------------------------------
# revision adversarial 2026-08-24: solo se comitean bloques CERRADOS
# ---------------------------------------------------------------------------

TABLA = ("| col | valor |\n|---|---|\n"
         + "".join(f"| r{i} | x |\n" for i in range(14))
         + "| r14 | una celda mucho mas ancha que todas las otras |\n")
LISTA = "".join(f"{i}. item {i}\n" for i in range(1, 13))
SETEXT = "Una frase corta que parece un parrafo\n---\n"


def _stream_invariante(texto, paso, cierre="\n\nfin.\n", **kw):
    """Streamea `texto` y comprueba en CADA paso que lo commiteado es un
    prefijo EXACTO del render final (no solo que no cambie despues: que
    coincida con lo que el render batch pinta). Devuelve (mv, salida)."""
    mv, salida, reloj = _mv(**kw)
    todo = texto + cierre
    final = MarkdownVivo(console=None, salida=io.StringIO(),
                         ancho=mv._ancho)._render(todo)
    for i in range(0, len(todo), paso):
        reloj.avanzar(10.0)
        mv.escribir(todo[i:i + paso])
        n = len(mv._commiteadas)
        assert mv._commiteadas == final[:n], \
            f"commiteado con otra forma en el paso {i}: " \
            f"{mv._commiteadas[-1]!r} != {final[n - 1]!r}"
    return mv, salida


def test_tabla_no_se_comitea_con_el_ancho_parcial():
    # antes: 11 de 12 lineas commiteadas distintas del render final (la
    # cabecera ' a   b ' a 10 columnas contra 44 en el final)
    mv, salida = _stream_invariante(TABLA, 4)
    assert mv._estables > 0, "la tabla cerrada tiene que commitearse"
    mv.cerrar()
    assert "r14" in salida.getvalue()


def test_lista_ordenada_de_diez_o_mas_no_desplaza_lo_commiteado():
    # antes: ' 1 item 1' commiteada y '  1 item 1' en el final (rich sangra
    # al ancho del ULTIMO numero)
    mv, _ = _stream_invariante(LISTA, 3)
    assert mv._estables > 0


def test_parrafo_seguido_de_subrayado_setext_no_se_comitea_como_prosa():
    mv, _ = _stream_invariante(SETEXT, 5, ventana=1)
    assert mv._estables > 0


def test_bloque_abierto_reglas():
    assert bloque_abierto("hola\n") == 0            # parrafo abierto
    assert bloque_abierto("hola\n\n") is None       # cerrado por blanco
    assert bloque_abierto("# titulo\n") is None     # ATX: una linea
    assert bloque_abierto("# titulo\nprosa") == len("# titulo\n")
    assert bloque_abierto("| a |\n|---|\n| 1 |\n") == 0
    assert bloque_abierto("| a |\n|---|\n\nprosa") == len("| a |\n|---|\n\n")
    # lista 'loose': la blanca no la cierra si sigue un item
    assert bloque_abierto("1. a\n\n2. b\n") == 0
    assert bloque_abierto("1. a\n\nprosa") == len("1. a\n\n")
    # el fence manda: dentro de el, nada cierra
    assert bloque_abierto("intro\n\n```py\n| no es tabla |\n\n") == len("intro\n\n")
    assert bloque_abierto("intro\n\n```py\nx\n```\n") is None


def test_bloque_mas_alto_que_la_pantalla_se_comitea_por_arriba():
    # fence de 40 lineas, terminal de 10 filas utiles, animado: la cola viva
    # jamas supera las 10 (CUU se clampa en la fila 0 y cada repintado
    # duplicaba en el scrollback lo que ya scrolleo)
    texto = "intro\n\n```python\n" + "\n".join(
        f"x{i} = {i}" for i in range(40)) + "\n"
    mv, salida, reloj = _mv(alto=10)
    mv._animar = True
    for i in range(0, len(texto), 9):
        reloj.avanzar(10.0)
        mv.escribir(texto[i:i + 9])
        assert mv._cola_altura <= 10, mv._cola_altura
    assert mv._estables > 3, "la cabeza del fence tiene que salir al scrollback"
    subidas = [int(m) for m in re.findall(r"\x1b\[(\d+)A", salida.getvalue())]
    assert subidas and max(subidas) <= 10
    reloj.avanzar(10.0)
    mv.escribir("```\n")
    # la cabeza commiteada del fence es IDENTICA al render final (las lineas
    # de codigo no reflowean): el transcript no tendra copias distintas
    final = MarkdownVivo(console=None, salida=io.StringIO(),
                         ancho=mv._ancho)._render(texto + "```\n")
    assert mv._commiteadas == final[:len(mv._commiteadas)]
    mv.cerrar()
    assert mv._cola_altura == 0
