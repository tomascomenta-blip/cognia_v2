"""
conftest.py — raiz del proyecto cognia_v2
==========================================
Configura sys.path para pytest con --import-mode=importlib.

Solo ROOT (cognia_v2/) se agrega. Agregar ROOT/cognia crea una colision de
nombres: Python encontraria cognia.py como modulo standalone "cognia" antes
que el paquete cognia/ — rompiendo los imports relativos en cognia/cognia.py.
"""

import sys
import importlib
from pathlib import Path

ROOT = Path(__file__).parent.parent  # cognia_v2/

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

# Pre-importar transformers COMPLETO (si esta instalado) antes de colectar los
# tests: si un test importa coordinator.app primero, su GlobalRouter dispara la
# carga de sentence-transformers DURANTE ese import y 'transformers' queda
# "partially initialized" en sys.modules (ciclo st<->transformers), rompiendo el
# import posterior de peft en test_expert_forge ("cannot import AutoModel").
# Importarlo entero y primero inmuniza el proceso (mismo espiritu que el
# workaround de rich de abajo). Costo: ~2-4s solo en maquinas con peft/torch.
try:
    import transformers as _tf_preload
    _ = _tf_preload.AutoModel          # fuerza la resolucion del lazy-module
except Exception:
    pass


def pytest_runtest_setup(item):
    """Re-import rich if contaminated by swig-based modules (e.g. llama-cpp-python)."""
    if "rich" in sys.modules:
        try:
            from rich.console import RenderableType  # noqa: F401
        except ImportError:
            # swig/llama-cpp contaminated the module cache — purge and reload rich
            mods_to_del = [k for k in sys.modules if k.startswith("rich")]
            for m in mods_to_del:
                del sys.modules[m]
            importlib.import_module("rich")


# ── Determinismo del azar ──────────────────────────────────────────────
# Ocho ficheros de test generan datos con `random`/`np.random` sin fijar
# semilla, asi que su veredicto dependia de la tirada. Medido el 2026-07-20:
# `test_orthogonal_to_existing_rows` paso 5 de 5 veces aislado y fallo en una
# corrida de la suite completa — su tolerancia de ortogonalidad (0.2) se supera
# de vez en cuando por azar.
#
# Un test que falla aleatoriamente es peor que no tenerlo: ensena a ignorar el
# rojo, y entonces el rojo de verdad tampoco se mira. Sembrar antes de cada
# test no debilita nada — comprueban exactamente lo mismo — pero hace el
# veredicto reproducible, que es la condicion para que la suite sirva de
# compuerta.
#
# Va aqui y no en cada fichero para tener UN solo punto que revertir si algun
# dia estorba.
import random as _random

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _semilla_reproducible():
    _random.seed(20260720)
    try:
        import numpy as _np
        _np.random.seed(20260720)
    except ImportError:
        pass


# ── El rastro de feromona NUNCA se escribe desde tests ─────────────────
# Medido el 2026-07-20: los tests que llaman _es_idea_web (test_deteccion_
# idea_web, test_program_creator_web) hacian que la colonia registrara sus
# discrepancias en el cognia/microexpertos/feromona.json REAL — cada corrida
# de la suite anadia observaciones duplicadas ("simple Markov chain text
# generator" x5) que ademas cuentan para el umbral de 20 confirmaciones.
# Redirigir SIEMPRE a tmp_path: los tests que quieren un rastro concreto
# (test_colonia.rastro_temporal) lo vuelven a apuntar ellos mismos encima.
@_pytest.fixture(autouse=True)
def _feromona_aislada(tmp_path, monkeypatch):
    try:
        from cognia.colonia import feromona as _fer
        monkeypatch.setattr(_fer, "RUTA_RASTRO",
                            tmp_path / "feromona_test.json")
    except ImportError:
        pass
