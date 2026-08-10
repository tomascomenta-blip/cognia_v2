"""Helper canonico del python GPU (venv312gpu).

POR QUE existe: varios subsistemas (summoner, voz, musica, tresd, y en fase 2
el pulidor) lanzan subprocesos con el python QUE TIENE torch/CUDA, y cada uno
resolvia la ruta por su cuenta. Este modulo es el punto unico. El flag es el
EXISTENTE COGNIA_GPU_PYTHON (ya usado en program_creator/pulidor.py:211);
COGNIA_GPU_PY no existe ni se crea (plan integrado, conflicto C4).
"""

import os
from pathlib import Path

# <repo>/cognia/gpu_env.py -> parent.parent es la raiz del repo.
_RAIZ = Path(__file__).resolve().parent.parent
_DEFAULT = _RAIZ / "venv312gpu" / "Scripts" / "python.exe"


def gpu_python() -> str:
    """Ruta (str) al python GPU: COGNIA_GPU_PYTHON o el default del repo.

    POR QUE no valida existencia aqui: el llamador decide si abortar o
    degradar (gpu_python_disponible() es el que responde ESO). Devolver
    siempre una ruta concreta hace que el error posterior sea legible
    ("no existe X") en vez de un None que se propaga en silencio."""
    env = os.environ.get("COGNIA_GPU_PYTHON", "").strip()
    if env:
        return env
    return str(_DEFAULT)


def gpu_python_disponible() -> tuple:
    """(ok, motivo). ok = el python GPU apunta a un archivo real.

    POR QUE el motivo trae la ruta y la salida: cuando falta, el usuario
    tiene que saber QUE ruta se busco y COMO arreglarlo, no solo un False."""
    ruta = gpu_python()
    if Path(ruta).is_file():
        return True, "ok"
    return False, (
        f"python GPU no encontrado en {ruta} "
        f"(crear venv312gpu con torch/CUDA o apuntar COGNIA_GPU_PYTHON "
        f"a un python que lo tenga)")
