# -*- coding: utf-8 -*-
"""
tests/test_ux_footer_y_tema.py
==============================
Regresion del juicio visual 2026-08-24 (prioridad media, un solo producto):

- dos footers de turno: el chat imprimia '30.4s' pelado (sin glifo, sin
  tokens, sin ctx) y el agente '✓ 12.8s · 573 tokens · 3 pasos'. Ahora los
  dos salen de ux/estilo.footer_turno.
- el markdown final usaba los defaults de rich (titulos magenta subrayado,
  codigo inline cyan sobre negro, numeros cyan): colores ajenos a la rampa.
  Ahora los estilos 'markdown.*' viven en paleta.TOKENS_CLI y las tres
  Consoles (CLI, renderer, markdown_vivo) pintan con el tema.
- la mini-barra de contexto llenaba lo USADO junto a un '% libre': ahora
  cuenta en la misma direccion (lleno = libre).

Cada test falla sin su fix.
"""
from __future__ import annotations

import io
import re

import pytest

from cognia.ux import estilo, paleta


def _consola(theme=None, width=120, color=False):
    from rich.console import Console
    buf = io.StringIO()
    kw = dict(file=buf, highlight=False, width=width, legacy_windows=False)
    if color:
        kw.update(force_terminal=True, color_system="truecolor")
    else:
        kw.update(force_terminal=False)
    if theme is not None:
        kw["theme"] = theme
    return Console(**kw), buf


# -- footer unico -------------------------------------------------------------

def test_footer_turno_construye_las_partes_en_orden():
    trozos = estilo.footer_turno(True, 30.44, tokens=412, pasos=3, ctx_libre_pct=94)
    assert estilo.texto_footer(trozos) == "  ✓ 30.4s · 412 tokens · 3 pasos · ctx 94% libre"
    assert trozos[1] == ("✓", "ok_cl")
    fallo = estilo.footer_turno(False, 37.7, tokens=1213, pasos=5,
                                motivo="parado: 3 tools seguidas fallaron")
    assert estilo.texto_footer(fallo) == (
        "  ✗ 37.7s · 1213 tokens · 5 pasos · parado: 3 tools seguidas fallaron")
    assert fallo[1] == ("✗", "err_cl") and fallo[-1][1] == "warn_cl"
    # sin datos no se inventan: ni tokens ni ctx ni pasos
    assert estilo.texto_footer(estilo.footer_turno(True, 7.2)) == "  ✓ 7.2s"
    assert estilo.texto_footer(estilo.footer_turno(True, 2.0, pasos=1)) == "  ✓ 2.0s · 1 paso"
    # ocupacion ESTIMADA (chat, chars/4): la misma '~' que la barra
    assert estilo.texto_footer(estilo.footer_turno(
        True, 18.1, ctx_libre_pct=97, ctx_estimado=True)) == "  ✓ 18.1s · ctx ~97% libre"


def test_footer_del_chat_habla_el_idioma_del_agente(monkeypatch):
    import cognia.cli as cli
    from rich.theme import Theme
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    con, buf = _consola(Theme(paleta.tema_cli("oscuro")))
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    monkeypatch.setattr(cli, "_datos_barra_estado",
                        lambda: {"ctx_usado": 3_900, "ctx_total": 65_536,
                                 "ctx_estimado": True})
    cli._show_footer(30.44, "respuesta", tokens=412)
    linea = buf.getvalue().strip()
    assert linea.startswith("✓ 30.4s · 412 tokens · ctx ~"), linea
    assert linea.endswith("% libre"), linea


def test_footer_del_chat_remoto_sigue_plano(monkeypatch):
    import cognia.cli as cli
    from cognia.remoto.sesiones import _RE_FOOTER_RENDERER
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    con, buf = _consola()
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    cli._show_footer(30.44, "respuesta", tokens=412)
    linea = buf.getvalue().strip()
    assert _RE_FOOTER_RENDERER.match(linea), linea


# -- markdown con el tema -------------------------------------------------------

def test_los_estilos_markdown_viven_en_la_paleta_para_las_tres_variantes():
    for variante in paleta.ORDEN_VARIANTES:
        tema = paleta.tema_cli(variante)
        for clave in ("markdown.h1", "markdown.h2", "markdown.code",
                      "markdown.item.number", "markdown.item.bullet"):
            assert clave in tema, (variante, clave)
        # codigo inline: sin fondo negro
        assert "on black" not in tema["markdown.code"], tema["markdown.code"]


def test_el_markdown_pintado_no_usa_magenta_ni_cyan_sobre_negro():
    from rich.markdown import Markdown
    from rich.theme import Theme
    con, buf = _consola(Theme(paleta.tema_cli("oscuro")), color=True)
    con.print(Markdown("## Ventajas\n\n1. Busca `idx_clientes` rapido\n2. Ordena"))
    crudo = buf.getvalue()
    assert "\x1b[4;35m" not in crudo, crudo          # titulo magenta subrayado
    assert "\x1b[1;36;40m" not in crudo, crudo       # codigo cyan sobre negro
    assert "\x1b[40m" not in crudo and ";40m" not in crudo, crudo   # ningun fondo negro
    assert "Ventajas" in crudo and "idx_clientes" in crudo
    # el numero de lista va en el ACENTO del tema (cyan en oscuro), o sea el
    # mismo color que el verbo de una tool: no un color ajeno a la paleta
    from rich.style import Style
    acento = Style.parse(paleta.tema_cli("oscuro")["markdown.item.number"])
    assert acento.color is not None
    assert acento.color.get_ansi_codes()[0] in crudo, crudo


def test_markdown_vivo_renderiza_con_el_tema_del_cli(monkeypatch):
    from cognia.ux import markdown_vivo
    monkeypatch.delenv("COGNIA_THEME", raising=False)
    assert markdown_vivo.tema_del_cli() is not None
    con, _ = _consola(color=True)
    md = markdown_vivo.MarkdownVivo(console=con, salida=io.StringIO(), ancho=80)
    assert md._color is True
    lineas = md._render("## Titulo\n\n`codigo`\n")
    crudo = "\n".join(lineas)
    assert "\x1b[4;35m" not in crudo and "\x1b[1;36;40m" not in crudo, crudo
    assert "Titulo" in crudo and "codigo" in crudo


# -- la mini-barra cuenta hacia el mismo lado que el texto -----------------------

def test_la_mini_barra_se_vacia_al_gastar_contexto():
    from cognia.harness import barra_estado as B
    g = B.glifos(unicode_ok=True) if hasattr(B, "glifos") else {"lleno": "█", "vacio": "░"}
    # 40% libre -> 3 celdas llenas de 8, al lado de '(40% libre)'
    assert B._bloques(60, g) == "█" * 3 + "░" * 5
    assert B._bloques(0, g) == "█" * 8
    linea = B.barra_estado({"modelo": "m", "ctx_usado": 39_000, "ctx_total": 65_536},
                           120, unicode_ok=True)
    assert "% libre" in linea
    m = re.search(r"\((\d+)% libre\)\s+([█░]{8})", linea)
    assert m, linea
    libre = int(m.group(1))
    assert m.group(2).count("█") == round(libre * 8 / 100), linea
