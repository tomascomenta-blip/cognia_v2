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
