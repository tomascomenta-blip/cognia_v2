# Antes de nada: stdout UTF-8. Si no, cualquier print con emoji mata el
# proceso en Windows cuando la salida esta redirigida (ver cognia/consola.py).
from .consola import forzar_utf8

forzar_utf8()

from .cognia import Cognia


def _detectar_version() -> str:
    # Instalado por pip: la metadata del wheel es la verdad. En un checkout
    # del repo (venv312 sin cognia-ai instalado) la metadata no existe, asi
    # que se lee pyproject.toml; "dev" solo si tampoco hay repo alrededor.
    try:
        from importlib.metadata import version
        return version("cognia-ai")
    except Exception:
        pass
    try:
        import os
        import re
        pp = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "pyproject.toml")
        with open(pp, "r", encoding="utf-8") as fh:
            m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "dev"


__version__ = _detectar_version()
