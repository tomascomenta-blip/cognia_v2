# -*- coding: utf-8 -*-
"""El arnes cableado DENTRO de run_tool, no al lado.

Estos tests fallan si alguien desconecta el interceptor de cognia/agent/tools.py:
comprueban el comportamiento a traves de `run_tool`, que es como lo ve el agente
de verdad, no llamando al interceptor por su cuenta.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cognia.agent.tools import run_tool
from cognia.harness import checkpoints, interceptor, modo_plan


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    """Cada test con su HOME, su sesion de checkpoints y su modo limpio."""
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    checkpoints._SESION = None
    modo_plan.reiniciar()
    for var in ("COGNIA_AUTO_TESTS", "COGNIA_OFFLOAD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_HOOKS", "0")
    yield
    modo_plan.reiniciar()
    checkpoints._SESION = None


def _ctx(tmp_path):
    return {"working_memory": {}, "agent_state": {}, "workspace": str(tmp_path)}


# ── ruta destino ───────────────────────────────────────────────────────
def test_ruta_destino_lee_el_primer_campo_del_protocolo():
    assert interceptor.ruta_destino("escribir_archivo", "a/b.py | print(1)") == "a/b.py"
    assert interceptor.ruta_destino("editar_archivo", 'x.py | SEARCH') == "x.py"
    assert interceptor.ruta_destino("borrar_archivo", "viejo.txt") == "viejo.txt"
    # Una tool que no escribe no tiene destino aunque sus args parezcan una ruta.
    assert interceptor.ruta_destino("leer_archivo", "a/b.py") == ""


# ── modo plan ──────────────────────────────────────────────────────────
def test_modo_plan_veta_la_escritura_y_devuelve_motivo_util(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    modo_plan.activar("plan")
    salida = run_tool("escribir_archivo", "nuevo.txt | hola", _ctx(tmp_path))
    assert not (tmp_path / "nuevo.txt").exists(), "el modo plan dejo escribir"
    assert "PLAN" in salida.upper()


def test_modo_plan_deja_pasar_la_lectura(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "leeme.txt").write_text("contenido visible", encoding="utf-8")
    modo_plan.activar("plan")
    salida = run_tool("leer_archivo", "leeme.txt", _ctx(tmp_path))
    assert "contenido visible" in salida


# ── checkpoints ────────────────────────────────────────────────────────
def test_escribir_deja_checkpoint_y_deshacer_restaura(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    objetivo = tmp_path / "conf.txt"
    objetivo.write_text("version buena", encoding="utf-8")

    run_tool("escribir_archivo", "conf.txt | version rota", _ctx(tmp_path))
    assert objetivo.read_text(encoding="utf-8").strip() == "version rota"

    entradas = checkpoints.listar()
    assert entradas, "run_tool no registro ningun checkpoint"
    checkpoints.deshacer()
    assert objetivo.read_text(encoding="utf-8") == "version buena"


def test_deshacer_borra_el_fichero_que_no_existia_antes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_tool("escribir_archivo", "recien.txt | soy nuevo", _ctx(tmp_path))
    assert (tmp_path / "recien.txt").exists()
    checkpoints.deshacer()
    assert not (tmp_path / "recien.txt").exists(), (
        "deshacer sobre un fichero que no existia antes tiene que borrarlo")


# ── verificacion tras editar ───────────────────────────────────────────
def test_python_roto_avisa_en_el_mismo_turno(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    salida = run_tool("escribir_archivo", "roto.py | def f(:\n    pass", _ctx(tmp_path))
    assert "ERROR" in salida.upper(), "una sintaxis rota paso sin aviso"
    assert "linea" in salida.lower() or "line" in salida.lower()


def test_python_sano_no_ensucia_el_resultado(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    salida = run_tool("escribir_archivo", "sano.py | def f():\n    return 1", _ctx(tmp_path))
    assert "verificacion" not in salida.lower(), (
        "el fichero estaba bien: el agente no necesita un veredicto por cada escritura")


def test_texto_plano_no_se_verifica(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    salida = run_tool("escribir_archivo", "notas.txt | def f(: esto no es python", _ctx(tmp_path))
    assert "ERROR" not in salida.upper()


# ── el arnes no puede tumbar el agente ─────────────────────────────────
def test_un_arnes_roto_deja_pasar_la_llamada(tmp_path, monkeypatch):
    """Si el interceptor explota, la herramienta se ejecuta igual."""
    monkeypatch.chdir(tmp_path)

    def _explota(*a, **k):
        raise RuntimeError("arnes roto a proposito")

    monkeypatch.setattr(interceptor, "antes", _explota)
    monkeypatch.setattr(interceptor, "despues", _explota)
    salida = run_tool("escribir_archivo", "pese_a_todo.txt | sigo vivo", _ctx(tmp_path))
    assert (tmp_path / "pese_a_todo.txt").read_text(encoding="utf-8").strip() == "sigo vivo"
    assert "ERROR" not in salida.upper()
