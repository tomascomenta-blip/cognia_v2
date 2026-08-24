# -*- coding: utf-8 -*-
"""
tests/test_renderer_preview_e_intencion.py
==========================================
Regresion del juicio visual 2026-08-24 (prioridad media, bloque de tools):

- el preview de escritura salia DOS veces (verde a columna 0 durante la tool
  via ctx['show_diff'] + banda diff bajo el bloque) y las previas de codigo
  perdian la indentacion ('print(n * n)' al nivel de 'for': strip()).
- la linea de intencion se cortaba en seco a 160 chars ('Could it be t'),
  sin glifo y envolviendo a columna 0.

Cada test falla sin su fix.
"""
from __future__ import annotations

import io

import pytest

from cognia.ux import events
from cognia.ux.renderer import Renderer


def _consola(width=60):
    from rich.console import Console
    from rich.theme import Theme
    buf = io.StringIO()
    tema = Theme({"ok_cl": "green", "err_cl": "red", "footer": "dim",
                  "warn_cl": "yellow", "info_dim": "dim", "respuesta": "default",
                  "intencion": "italic", "escrito": "green", "borrado": "red",
                  "tool_verbo": "cyan", "tool_obj": "bold", "spinner": "green",
                  "pensar": "green"})
    return Console(file=buf, theme=tema, highlight=False, width=width,
                   force_terminal=False), buf


# -- indentacion del preview ---------------------------------------------------

def test_preview_de_escritura_conserva_la_indentacion(monkeypatch, capsys):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_RENDER_COLAPSO", "0")   # camino viejo + preview
    r = Renderer(console=None)                          # fallback plano: print()
    r(events.ToolFin(tool="escribir_archivo",
                     args="cuadrados.py|for n in range(1, 11):\n    print(n * n)\n",
                     ok=True, resumen="RESULTADO escribir_archivo cuadrados.py: OK (39 chars)"))
    salida = capsys.readouterr().out
    assert "+ for n in range(1, 11):" in salida
    assert "+     print(n * n)" in salida, salida


def test_preview_de_edicion_conserva_la_indentacion(monkeypatch, capsys):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_RENDER_COLAPSO", "0")
    r = Renderer(console=None)
    payload = ("x.py|<<<<<<< SEARCH\n    a = 1\n=======\n    a = 2\n"
               "    b = 3\n>>>>>>> REPLACE")
    r(events.ToolFin(tool="editar_archivo", args=payload, ok=True,
                     resumen="RESULTADO editar_archivo x.py: OK"))
    salida = capsys.readouterr().out
    assert "-     a = 1" in salida, salida
    assert "+     a = 2" in salida and "+     b = 3" in salida, salida


def test_preview_con_banda_rich_conserva_la_indentacion(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_RENDER_COLAPSO", "0")
    con, buf = _consola(width=100)
    r = Renderer(console=con)
    r(events.ToolFin(tool="escribir_archivo",
                     args="cuadrados.py|for n in range(1, 11):\n    print(n * n)\n",
                     ok=True, resumen="RESULTADO escribir_archivo cuadrados.py: OK (39 chars)"))
    salida = buf.getvalue()
    assert "    print(n * n)" in salida, salida


# -- el preview sale UNA vez ------------------------------------------------------

def test_show_diff_del_ctx_se_apaga_cuando_el_renderer_pinta_el_preview(monkeypatch):
    import cognia.cli as cli
    from cognia.ux import renderer as ux_r
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setattr(ux_r, "_renderer", object())     # renderer activo
    assert cli._show_diff_para_ctx(lambda *a: None) is None
    monkeypatch.setattr(ux_r, "_renderer", None)         # sin renderer
    assert callable(cli._show_diff_para_ctx(lambda *a: None))
    monkeypatch.setattr(ux_r, "_renderer", object())
    monkeypatch.setenv("COGNIA_REMOTO", "1")             # remoto: hace falta
    assert callable(cli._show_diff_para_ctx(lambda *a: None))


# -- la intencion ----------------------------------------------------------------

def test_recortar_en_palabra_cierra_con_elipsis():
    from cognia.agent.loop import recortar_en_palabra
    largo = ("The file is 431 lines the log claim looks like a red herring "
             "the actual file on disk is 431 lines 24183 bytes and it has been "
             "offloaded to res:fd573 could it be that the tool truncated")
    corto = recortar_en_palabra(largo, 160)
    assert len(corto) <= 160
    assert corto.endswith("…")
    assert not corto[:-1].endswith(" ")
    # se corta en una palabra entera, no a mitad ('Could it be t')
    assert corto[:-1].split(" ")[-1] in largo.split(" ")
    assert recortar_en_palabra("corta", 160) == "corta"
    assert recortar_en_palabra("", 160) == ""


def test_intencion_con_glifo_y_sangria_colgante():
    con, buf = _consola(width=60)
    r = Renderer(console=con)
    r(events.PasoIntencion(paso=1, intencion=(
        "The user wants me to create a script called cuadrados.py in the "
        "current folder and run it with python to show the squares")))
    lineas = buf.getvalue().rstrip("\n").split("\n")
    assert lineas[0].startswith("  ∴ The user wants"), lineas
    assert len(lineas) >= 2, lineas
    # la continuacion cuelga bajo el texto, no vuelve a la columna 0
    for l in lineas[1:]:
        assert l.startswith("    "), lineas
    assert all(len(l) <= 60 for l in lineas), lineas
