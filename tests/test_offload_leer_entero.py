# -*- coding: utf-8 -*-
"""
tests/test_offload_leer_entero.py
=================================
Regresion del juicio visual 2026-08-24 (prioridad media): la cabecera del
offload afirmaba 'NO se perdio nada: esta guardada' cuando leer_archivo YA
habia recortado el fichero de 3000 lineas a 431 (24 KB) ANTES de espillear;
el modelo concluyo que las 3000 lineas eran 'a red herring'.

Ahora: con el offload ACTIVO y sin limit explicito, leer_archivo entrega el
fichero ENTERO (el offload es el mecanismo de recorte: guarda todo, muestra
cabeza+cola y deja recuperar); con limit explicito, la cabecera dice que
tramo se guardo y como seguir. Sin offload, el recorte de siempre.

Sin mocks: run_tool REAL sobre un fichero real de 3000 lineas.
"""
from __future__ import annotations

import re

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T


@pytest.fixture()
def taller(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "offload"))
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "2000")
    f = tmp_path / "grande.log"
    f.write_text("\n".join(f"2026-08-24T10:00:00 ERROR [cache] evento {i} detalle={i * 7}"
                           for i in range(3000)) + "\n", encoding="utf-8")
    return f


def _ctx():
    return {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}


def test_con_offload_el_fichero_va_entero_y_la_cabecera_dice_3000(taller, monkeypatch):
    monkeypatch.setenv("COGNIA_OFFLOAD", "1")
    ctx = _ctx()
    out = T.run_tool("leer_archivo", str(taller), ctx)
    cabeza = out.split("\n", 1)[0]
    assert cabeza.startswith("[SALIDA GRANDE de leer_archivo: 3000 lineas"), cabeza
    assert "NO se perdio nada" in cabeza
    assert "[TRUNCADO" not in out
    assert ctx["_ultimo_ok"] is True
    # y el spill tiene las 3000 lineas de verdad
    from cognia.harness import offloading as off
    handle = re.search(r"res:[0-9a-f]+", out).group(0)
    ultima = off.recuperar(handle, desde=3000, hasta=3000)
    assert "evento 2999" in ultima, ultima


def test_sin_offload_el_recorte_de_siempre(taller, monkeypatch):
    monkeypatch.setenv("COGNIA_OFFLOAD", "0")
    out = T.run_tool("leer_archivo", str(taller), _ctx())
    assert "[TRUNCADO: mostrando lineas 1-" in out and " de 3000" in out
    assert "[SALIDA GRANDE" not in out


def test_con_limit_explicito_la_cabecera_dice_que_tramo_se_guardo(taller, monkeypatch):
    monkeypatch.setenv("COGNIA_OFFLOAD", "1")
    out = T.run_tool("leer_archivo", f"{taller} limit=100", _ctx())
    cabeza = out.split("\n", 1)[0]
    assert cabeza.startswith("[SALIDA GRANDE de leer_archivo:"), cabeza
    assert "NO se perdio nada" not in cabeza, cabeza
    assert "tramo 1-100" in cabeza and "3000 lineas" in cabeza, cabeza
    assert "offset=101" in cabeza, cabeza
