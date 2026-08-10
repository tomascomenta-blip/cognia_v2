# -*- coding: utf-8 -*-
"""Tests de scripts/banco_trazas.py — plantillas + pre-chequeo (CPU puro).

POR QUE: 2 de 3 bitacoras reales fallaron por el alias de Microsoft Store
(exit 9009), no por el modelo — generar 100 tareas sin el pre-chequeo habria
envenenado el dataset con fallos de infra. Y las plantillas deben variar con
la semilla o el dedupe por plantilla del dataset se come toda la corrida.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    ruta = REPO_ROOT / "scripts" / "banco_trazas.py"
    spec = importlib.util.spec_from_file_location("banco_trazas", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── Plantillas parametrizadas ──────────────────────────────────────────

def test_semillas_distintas_dan_tareas_distintas(mod):
    n = len(mod.PLANTILLAS)
    t1 = [t["tarea"] for t in mod.generar_tareas(n, semilla=1)]
    t2 = [t["tarea"] for t in mod.generar_tareas(n, semilla=2)]
    distintas = sum(1 for a, b in zip(t1, t2) if a != b)
    assert distintas >= n * 3 // 4, (
        f"solo {distintas}/{n} tareas cambian con la semilla: el dedupe "
        "del dataset se comeria las corridas")


def test_misma_semilla_reproduce_el_banco(mod):
    a = [t["tarea"] for t in mod.generar_tareas(10, semilla=7)]
    b = [t["tarea"] for t in mod.generar_tareas(10, semilla=7)]
    assert a == b


def test_desde_continua_la_serie(mod):
    todo = [t["tarea"] for t in mod.generar_tareas(10, semilla=7, desde=0)]
    cola = [t["tarea"] for t in mod.generar_tareas(5, semilla=7, desde=5)]
    assert todo[5:] == cola
    indices = [t["indice"] for t in mod.generar_tareas(3, semilla=7, desde=5)]
    assert indices == [5, 6, 7]


def test_hay_suficientes_plantillas(mod):
    assert len(mod.PLANTILLAS) >= 20


def test_verificar_es_real_sobre_el_filesystem(mod, tmp_path):
    # La postcondicion de 'escribir' pasa con el artefacto y falla sin el.
    tarea = next(t for t in mod.generar_tareas(len(mod.PLANTILLAS), semilla=3)
                 if t["nombre"] == "escribir")
    ws = tmp_path / "ws"
    ws.mkdir()
    assert tarea["verificar"](ws) is False
    frase = tarea["tarea"].split("texto exacto: ", 1)[1]
    arch = tarea["tarea"].split("llamado ", 1)[1].split(" ", 1)[0]
    (ws / arch).write_text(frase, encoding="utf-8")
    assert tarea["verificar"](ws) is True


def test_setup_prepara_el_workspace(mod, tmp_path):
    tarea = next(t for t in mod.generar_tareas(len(mod.PLANTILLAS), semilla=3)
                 if t["nombre"] == "apendar")
    ws = tmp_path / "ws2"
    ws.mkdir()
    tarea["setup"](ws)
    assert (ws / "bitacora.txt").is_file()
    assert tarea["verificar"](ws) is False  # aun sin la linea nueva


# ── Pre-chequeo del interprete ─────────────────────────────────────────

class _Res:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout = rc, out


def test_prechequeo_aborta_con_alias_de_store(mod):
    ok, motivo = mod.prechequeo_interprete(
        run_fn=lambda *a, **k: _Res(0, "42\n"),
        which_fn=lambda n: r"C:\Users\u\AppData\Local\Microsoft"
                           r"\WindowsApps\python.exe")
    assert ok is False
    assert "Microsoft Store" in motivo


def test_prechequeo_aborta_con_exit_9009(mod):
    ok, motivo = mod.prechequeo_interprete(
        run_fn=lambda *a, **k: _Res(9009, ""),
        which_fn=lambda n: r"C:\pythons\python.exe")
    assert ok is False
    assert "9009" in motivo


def test_prechequeo_aborta_si_no_imprime(mod):
    ok, _ = mod.prechequeo_interprete(
        run_fn=lambda *a, **k: _Res(0, ""),
        which_fn=lambda n: r"C:\pythons\python.exe")
    assert ok is False


def test_prechequeo_pasa_con_interprete_sano(mod):
    ok, motivo = mod.prechequeo_interprete(
        run_fn=lambda *a, **k: _Res(0, "42\n"),
        which_fn=lambda n: r"C:\pythons\python.exe")
    assert ok is True
    assert "python" in motivo.lower()


def test_prechequeo_tolera_excepcion_de_run(mod):
    def explota(*a, **k):
        raise FileNotFoundError("no python")
    ok, motivo = mod.prechequeo_interprete(
        run_fn=explota, which_fn=lambda n: "")
    assert ok is False and "no python" in motivo


def test_main_aborta_sin_generar_si_prechequeo_falla(mod, monkeypatch):
    # El abort ocurre ANTES de importar/arrancar nada pesado: exit 2.
    monkeypatch.setattr(mod, "prechequeo_interprete",
                        lambda: (False, "alias roto (simulado)"))
    assert mod.main(["--n", "1"]) == 2
