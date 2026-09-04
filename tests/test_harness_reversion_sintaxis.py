# -*- coding: utf-8 -*-
"""Contrato de `cognia/harness/reversion_sintaxis.py` (lint diferencial de
SWE-agent, 2026-09-04): un editar_archivo que rompe un .py que parseaba se
revierte y se explica; si el fichero YA estaba roto no se toca; si es un
fichero nuevo no se toca; escribir_archivo/apendar_archivo quedan fuera; el
kill-switch apaga; y el cableado real por `interceptor.antes/despues`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cognia.harness import reversion_sintaxis as rs


@pytest.fixture(autouse=True)
def encendido(monkeypatch, tmp_path):
    monkeypatch.delenv(rs.ENV_ACTIVO, raising=False)
    monkeypatch.setenv("COGNIA_OFFLOAD", "0")
    monkeypatch.setenv("COGNIA_CHECKPOINTS_DIR", str(tmp_path / "ckpt"))


def _ctx(ruta: Path, previo):
    return {"_harness_previo": {"ruta": str(ruta), "contenido": previo, "tool": "editar_archivo"},
            "cwd": str(ruta.parent)}


def test_revierte_una_edicion_que_rompe_la_sintaxis(tmp_path):
    f = tmp_path / "a.py"
    previo = "def f():\n    return 1\n"
    f.write_text(previo, encoding="utf-8")
    ctx = _ctx(f, previo)
    f.write_text("def f(:\n    return 1\n", encoding="utf-8")       # lo que dejó el edit
    out = rs.aplicar("editar_archivo", str(f), ctx, "RESULTADO editar_archivo: ok")
    assert f.read_text(encoding="utf-8") == previo
    assert "REVIRTIÓ" in out and "No repitas" in out and "linea 1" in out
    assert ctx["_harness_revertido"] == str(f.resolve())


def test_no_toca_si_el_resultado_parsea(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    ctx = _ctx(f, "x = 0\n")
    out = rs.aplicar("editar_archivo", str(f), ctx, "RESULTADO editar_archivo: ok")
    assert out == "RESULTADO editar_archivo: ok"
    assert f.read_text(encoding="utf-8") == "x = 1\n"


def test_no_toca_si_ya_estaba_roto(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def g(:\n", encoding="utf-8")
    ctx = _ctx(f, "def f(:\n")
    out = rs.aplicar("editar_archivo", str(f), ctx, "RESULTADO editar_archivo: ok")
    assert "REVIRTIÓ" not in out
    assert f.read_text(encoding="utf-8") == "def g(:\n"


def test_no_toca_ficheros_nuevos_ni_otras_tools(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def f(:\n", encoding="utf-8")
    ctx = {"_harness_previo": {"ruta": str(f), "contenido": None, "tool": "escribir_archivo"}}
    assert "REVIRTIÓ" not in rs.aplicar("editar_archivo", str(f), ctx, "x")
    ctx = _ctx(f, "x = 1\n")
    assert "REVIRTIÓ" not in rs.aplicar("escribir_archivo", str(f), ctx, "x")
    assert "REVIRTIÓ" not in rs.aplicar("apendar_archivo", str(f), ctx, "x")
    assert f.read_text(encoding="utf-8") == "def f(:\n"


def test_solo_extensiones_con_verificador(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("(((", encoding="utf-8")
    assert "REVIRTIÓ" not in rs.aplicar("editar_archivo", str(f), _ctx(f, "ok"), "x")


def test_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv(rs.ENV_ACTIVO, "0")
    f = tmp_path / "a.py"
    f.write_text("def f(:\n", encoding="utf-8")
    assert "REVIRTIÓ" not in rs.aplicar("editar_archivo", str(f), _ctx(f, "x = 1\n"), "x")
    assert f.read_text(encoding="utf-8") == "def f(:\n"


def test_json_tambien(tmp_path):
    f = tmp_path / "c.json"
    previo = '{"a": 1}\n'
    f.write_text(previo, encoding="utf-8")
    f.write_text('{"a": 1,}\n', encoding="utf-8")
    out = rs.aplicar("editar_archivo", str(f), _ctx(f, previo), "ok")
    assert "REVIRTIÓ" in out and f.read_text(encoding="utf-8") == previo


# ── Cableado real: interceptor.antes guarda el previo, despues revierte ──────

def test_cableado_interceptor_antes_y_despues(tmp_path, monkeypatch):
    from cognia.harness import interceptor
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "m.py"
    previo = "def f():\n    return 1\n"
    f.write_bytes(previo.encode("utf-8"))       # bytes exactos: write_text pondria \r\n en Windows
    ctx = {"cwd": str(tmp_path)}
    args = f"{f} | <<<<<<< SEARCH\nreturn 1\n=======\nreturn (\n>>>>>>> REPLACE"
    veto = interceptor.antes("editar_archivo", args, ctx)
    assert veto is None
    assert ctx["_harness_previo"]["contenido"] == previo
    f.write_bytes(b"def f():\n    return (\n")          # el edit roto
    out = interceptor.despues("editar_archivo", args, ctx, "RESULTADO editar_archivo: 1 reemplazo", True)
    assert "REVIRTIÓ" in out
    assert f.read_bytes() == previo.encode("utf-8")
