"""
conftest.py — raiz del proyecto cognia_v2
==========================================
Configura sys.path para pytest con --import-mode=importlib.

Solo ROOT (cognia_v2/) se agrega. Agregar ROOT/cognia crea una colision de
nombres: Python encontraria cognia.py como modulo standalone "cognia" antes
que el paquete cognia/ — rompiendo los imports relativos en cognia/cognia.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent  # cognia_v2/

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass
