# -*- coding: utf-8 -*-
"""Tests de harness/enlaces: rutas de fichero clicables (OSC 8) en el
transcript. Cubre lo que pide la entrega:
 - target file:/// saneado (controles y espacios percent-encodeados,
   jamas un byte crudo < 0x20 dentro del OSC 8)
 - solo rutas ABSOLUTAS que existen (relativas y fantasmas: jamas)
 - el texto visible queda BYTE-IDENTICO (Text.plain == entrada) y el
   fallback sin tty es el texto plano tal cual
 - la emision REAL por rich trae el par OSC 8 (\x1b]8;;target ... \x1b]8;;)
"""
from __future__ import annotations

import io

import pytest

from cognia.harness import enlaces


@pytest.fixture(autouse=True)
def _sin_env(monkeypatch):
    monkeypatch.delenv("COGNIA_ENLACES", raising=False)
    yield


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_activo_default_on_y_env_gana(monkeypatch):
    assert enlaces.activo({}) is True
    assert enlaces.activo({"enlaces": "off"}) is False
    monkeypatch.setenv("COGNIA_ENLACES", "0")
    assert enlaces.activo({"enlaces": "on"}) is False
    monkeypatch.setenv("COGNIA_ENLACES", "1")
    assert enlaces.activo({"enlaces": "off"}) is True


# ---------------------------------------------------------------------------
# Target saneado
# ---------------------------------------------------------------------------

def test_target_absoluto_percent_encodeado(tmp_path):
    f = tmp_path / "con espacio.txt"
    f.write_text("x", encoding="utf-8")
    target = enlaces.target_de(str(f))
    assert target.startswith("file:///")
    assert " " not in target
    assert "%20" in target


def test_target_controles_percent_encodeados():
    # La ruta no necesita existir para sanear: target_de es pura. Un BEL o un
    # ESC crudos dentro del target ROMPEN la secuencia OSC 8 entera.
    target = enlaces.target_de("C:\\tmp\\raro\x07\x1b.txt")
    assert target != ""
    assert all(ord(c) >= 0x21 for c in target)
    assert "%07" in target and "%1B" in target.upper()


def test_target_relativo_o_vacio_se_rechaza():
    assert enlaces.target_de("cognia/cli.py") == ""
    assert enlaces.target_de("") == ""
    assert enlaces.target_de(None) == ""


# ---------------------------------------------------------------------------
# Deteccion de spans
# ---------------------------------------------------------------------------

def test_enlaces_en_solo_rutas_absolutas_existentes(tmp_path):
    f = tmp_path / "salida.txt"
    f.write_text("x", encoding="utf-8")
    linea = f"resultado -> fichero: {f} (48 B) y ./relativa.txt no"
    spans = enlaces.enlaces_en(linea)
    assert len(spans) == 1
    ini, fin, target = spans[0]
    assert linea[ini:fin] == str(f)
    assert target == enlaces.target_de(str(f))


def test_enlaces_en_ignora_fantasmas_y_comandos():
    assert enlaces.enlaces_en("C:\\no\\existe\\jamas_9x8.txt") == []
    assert enlaces.enlaces_en("usa /expandir o /pegado lista") == []
    assert enlaces.enlaces_en("") == []


def test_enlaces_en_recorta_puntuacion_final(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    spans = enlaces.enlaces_en(f"(ver {f}).")
    assert len(spans) == 1
    ini, fin, _ = spans[0]
    assert f"(ver {f})."[ini:fin] == str(f)


# ---------------------------------------------------------------------------
# Texto visible byte-identico + emision OSC 8 real
# ---------------------------------------------------------------------------

def test_texto_rich_plain_byte_identico(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    linea = f"  \u23bf guardado en {f} (1 B)"
    rico = enlaces.texto_rich(linea, "info_dim")
    assert rico is not None
    assert rico.plain == linea          # el target JAMAS en el texto visible


def test_texto_rich_sin_rutas_devuelve_none():
    assert enlaces.texto_rich("sin rutas por aca") is None


def test_emision_real_lleva_el_par_osc8(tmp_path):
    from rich.console import Console
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    linea = f"fichero: {f}"
    rico = enlaces.texto_rich(linea)
    buf = io.StringIO()
    # legacy_windows=False: rich SOLO emite OSC 8 en terminal moderna (en
    # Windows Terminal real la deteccion ya da False; un buffer de test no).
    consola = Console(file=buf, force_terminal=True, legacy_windows=False,
                      width=400)
    consola.print(rico, highlight=False)
    salida = buf.getvalue()
    # el par OSC 8: apertura con target y cierre vacio
    assert "\x1b]8;" in salida
    assert enlaces.target_de(str(f)) in salida
    assert salida.count("\x1b]8;") >= 2


def test_fallback_sin_tty_byte_identico(tmp_path):
    """Sin terminal el integrador imprime el PLANO: mismo texto, cero escapes.
    Se verifica con una Console NO terminal: rich no emite OSC 8 ni ANSI."""
    from rich.console import Console
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    linea = f"fichero: {f}"
    buf = io.StringIO()
    consola = Console(file=buf, force_terminal=False, width=400)
    consola.print(linea, markup=False, highlight=False)
    assert buf.getvalue() == linea + "\n"


def test_marcar_markup_envuelve_y_conserva_visible(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    linea = f"ultimo spill -> {f}"
    marcado = enlaces.marcar_markup(linea)
    target = enlaces.target_de(str(f))
    assert marcado == f"ultimo spill -> [link={target}]{f}[/link]"
    # sin rutas: intacto
    assert enlaces.marcar_markup("nada por aca") == "nada por aca"


def test_enlace_visible_off_apaga_el_osc8_y_la_env_gana(monkeypatch):
    """P6 (2026-08-24): /estilo enlace visible off apaga los enlaces; la env
    COGNIA_ENLACES sigue mandando por encima del registro."""
    from cognia.ux import aspecto as A
    monkeypatch.delenv("COGNIA_ENLACES", raising=False)
    A.reset()
    try:
        assert enlaces.activo({}) is True
        assert not A.errores(A.poner("enlace", "visible", "off"))
        assert enlaces.activo({}) is False
        assert enlaces.activo({"enlaces": "on"}) is False
        monkeypatch.setenv("COGNIA_ENLACES", "1")
        assert enlaces.activo({}) is True
    finally:
        A.reset()
