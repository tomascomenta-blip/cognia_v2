"""
cognia/experts/meta_maker.py
============================
Puerta al meta-modelo creador de expertos (modalidad 3 del alta).

REGLA DURA: cognia/ se empaqueta a PyPI y no puede importar torch — por eso
la inferencia corre por SUBPROCESS contra expert_forge/cli_infer.py, que solo
existe en la maquina de entrenamiento. Si no esta (instalacion PyPI normal),
make_expert_spec devuelve None y el caller degrada a plantillas.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CLAVES = ("id", "nombre", "dedicacion", "model_key", "backend")


def make_expert_spec(peticion: str, timeout_s: int = 180) -> dict | None:
    """Peticion libre -> spec de experto via el meta-modelo local, o None."""
    if not (_REPO_ROOT / "expert_forge" / "cli_infer.py").is_file():
        return None
    try:
        out = subprocess.run(
            [sys.executable, "-m", "expert_forge.cli_infer", "--peticion", peticion],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(_REPO_ROOT), encoding="utf-8", errors="replace",
        )
        line = (out.stdout or "").strip().splitlines()
        line = line[-1] if line else ""
        if not line or line.startswith("ERROR"):
            return None
        spec = json.loads(line)
        if all(k in spec for k in _CLAVES):
            return spec
    except Exception:
        pass
    return None
