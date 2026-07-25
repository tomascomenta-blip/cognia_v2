"""
Las tools de imagen son OPT-IN DURO (COGNIA_IMG_TOOLS=1).

Regresion medida 2026-07-25: registradas default-ON, el camino feliz del agente
cayo de 4.25/5 a 2.5/5 (A/B n=4+4) — el prompt de tools crece y el modelo chico
elige peor. Es la misma regla que ya protegia a las tools de pantalla ("techo
de nº de tools"). El registro ocurre AL IMPORTAR tools.py, asi que se verifica
en subprocesos limpios.
"""

import os
import subprocess
import sys

_CODE = ("from cognia.agent.tools import TOOLS; "
         "print('imagen_generar' in TOOLS)")


def _corre(env_extra):
    env = {**os.environ, **env_extra}
    env.pop("COGNIA_IMG_TOOLS", None)
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", _CODE], capture_output=True,
                       text=True, env=env, timeout=120)
    return r.stdout.strip().splitlines()[-1]


def test_off_por_defecto():
    assert _corre({}) == "False"


def test_on_con_flag():
    assert _corre({"COGNIA_IMG_TOOLS": "1"}) == "True"
