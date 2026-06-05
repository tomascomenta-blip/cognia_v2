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
