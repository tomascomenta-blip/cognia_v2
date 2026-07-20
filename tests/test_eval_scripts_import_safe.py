# -*- coding: utf-8 -*-
"""Regresion: los modulos-script de cognia_v3/eval son seguros de importar.

Deuda tecnica cazada 2026-07-16 (import-walk de auditoria): tres modulos que
VIAJAN EN EL WHEEL ejecutaban su flujo completo a nivel de modulo, sin guard
__main__:
- bon_live_batch.py: al importarse instanciaba Cognia(), corria el agente
  live (spawneando llama-server) y BORRABA factorial.py/fib.py/... del cwd
  del usuario. El import-walk lo disparo de verdad (~10 min de corrida).
- kaggle_eagle3_bench.py: git clone + wget + pip install + build CMake al
  importarse (es un kernel para Kaggle, no un modulo importable).
- medir_fidelidad.py: path absoluto del repo del dev hardcodeado + analisis
  completo al importarse -> FileNotFoundError garantizado fuera de esa maquina.
"""
import importlib
import os
import sys

import pytest

_SCRIPTS = [
    "cognia_v3.eval.bon_live_batch",
    "cognia_v3.eval.kaggle_eagle3_bench",
    "cognia_v3.eval.medir_fidelidad",
]


@pytest.mark.parametrize("modname", _SCRIPTS)
def test_import_es_inerte_y_define_main(modname):
    cwd_antes = os.getcwd()
    archivos_antes = set(os.listdir(cwd_antes))
    sys.modules.pop(modname, None)
    try:
        mod = importlib.import_module(modname)
    finally:
        os.chdir(cwd_antes)
    assert callable(getattr(mod, "main", None)), (
        f"{modname} debe exponer main() (flujo bajo guard __main__)")
    assert os.getcwd() == cwd_antes
    assert set(os.listdir(cwd_antes)) == archivos_antes, (
        f"importar {modname} creo/borro archivos en el cwd")
