# -*- coding: utf-8 -*-
"""
tests/test_cli_estado_unico.py
==============================
Regresion del juicio visual 2026-08-24: los ocho '/x estado' no compartian
formato -- 'ACTIVOS', 'ACTIVO', 'viva', 'activo', 'modo auto', 'modo
resumen' segun el modulo; spinner, markdown y la 2a mitad de /bucle a
columna 0 mientras los demas sangraban 2; /config-resuelta y /expandir con
reglas ASCII ('-- Seccion --', '--- ... ---'); todo en el mismo gris.

Ahora los ocho pasan por ux/estilo.estado_subsistema: titulo en 'mod',
estado 'on'/'off' (o el modo) coloreado, filas 'clave  valor' alineadas con
sangria de 2 y sangria COLGANTE al envolver, avisos con ⚠.

Snapshot REAL: se corre cada _slash_x('estado') con la Console del CLI a 80
columnas y se comprueba la reja sobre el texto pintado.
"""
from __future__ import annotations

import io
import re

import pytest

from cognia.ux import estilo, paleta

rich_console = pytest.importorskip("rich.console")


# -- el helper ------------------------------------------------------------------

def test_estado_subsistema_pinta_la_reja():
    lineas = estilo.estado_subsistema(
        "offload de salidas grandes", True,
        [("umbral", "12000 bytes inline"),
         ("dir spills", "C:/muy/larga " + "x " * 45),
         ("ultimo error", "ninguno")],
        fuente="config offload", avisos=["config invalida: umbral < 200"])
    assert lineas[0].startswith("[mod]offload de salidas grandes[/mod]  [ok_cl]on[/ok_cl]")
    assert "(config offload)" in lineas[0]
    # filas alineadas: la clave se rellena al ancho de la mas larga
    assert lineas[1].startswith("  [info_dim]umbral      [/info_dim]  ")
    assert lineas[3].startswith("  [info_dim]ultimo error[/info_dim]  ")
    # el valor largo envuelve con sangria COLGANTE bajo la columna del valor
    assert "\n" in lineas[2]
    for cont in lineas[2].split("\n")[1:]:
        assert cont.startswith(" " * (2 + len("ultimo error") + 2)), repr(cont)
    assert lineas[-1] == "  [warn_cl]⚠ config invalida: umbral < 200[/warn_cl]"
    # estados: bool -> on/off; palabra de modo -> ok salvo apagado
    assert "[warn_cl]off[/warn_cl]" in estilo.estado_subsistema("x", False)[0]
    assert "[ok_cl]resumen[/ok_cl]" in estilo.estado_subsistema("x", "resumen")[0]
    assert "[warn_cl]apagado[/warn_cl]" in estilo.estado_subsistema("x", "apagado")[0]
    # los valores se escapan (un '[x]' no es markup)... salvo markup propio
    fila = estilo.estado_subsistema("x", True, [("k", "[link] no es markup")])[1]
    assert "\\[link]" in fila
    crudo = estilo.estado_subsistema("x", True, [("k", "[link=file:///a]a[/link]", "listado", True)])[1]
    assert "[link=file:///a]a[/link]" in crudo


# -- los ocho comandos, pintados de verdad ---------------------------------------

def _consola(ancho=80):
    from rich.theme import Theme
    buf = io.StringIO()
    con = rich_console.Console(file=buf, width=ancho, force_terminal=False,
                               legacy_windows=False, highlight=False,
                               theme=Theme(paleta.tema_cli("oscuro")))
    return con, buf


COMANDOS = [
    ("_slash_enlaces", "enlaces de rutas"),
    ("_slash_pegado", "colapso de pastes largos"),
    ("_slash_offload", "offload de salidas grandes"),
    ("_slash_compactar", "compactacion del contexto"),
    ("_slash_bucle", "recordatorio de repeticion"),
    ("_slash_notificar", "notificaciones de escritorio"),
    ("_slash_spinner", "linea de estado viva"),
    ("_slash_markdown", "markdown en streaming"),
]

RE_ESTADO = re.compile(r"^\S.*  (on|off|resumen|truncado|viva|clasica|auto|osc|bell|toast|\d+s|sin limite)\b")


@pytest.mark.parametrize("fn, titulo", COMANDOS)
def test_los_ocho_estados_comparten_la_reja(fn, titulo, monkeypatch):
    import cognia.cli as cli
    con, buf = _consola(80)
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    monkeypatch.setenv("COGNIA_ADVANCED", "1")   # que el modo sencillo no filtre
    getattr(cli, fn)("estado")
    salida = buf.getvalue()
    lineas = [l for l in salida.split("\n") if l.strip()]
    assert lineas, salida
    assert lineas[0].startswith(titulo), lineas[0]
    # la cabecera lleva la PALABRA de estado normalizada (on/off o el modo)
    assert RE_ESTADO.match(lineas[0]), lineas[0]
    # todas las filas sangran 2 (nada a columna 0 salvo la cabecera de un
    # subsistema) y ninguna linea supera el ancho
    for l in lineas[1:]:
        assert l.startswith("  ") or RE_ESTADO.match(l), (fn, l)
        assert len(l) <= 80, (fn, len(l), l)
    # cero reglas ASCII y cero palabras de estado a mano
    assert "--" not in salida
    assert not re.search(r"\bACTIVOS?\b", salida), salida


def test_config_resuelta_usa_la_regla_de_la_casa(monkeypatch):
    import cognia.cli as cli
    con, buf = _consola(100)
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    cli._slash_config_resuelta("")
    salida = buf.getvalue()
    assert "Configuracion RESUELTA" in salida
    assert "-- " not in salida and " --" not in salida, salida
    assert "─ " in salida
