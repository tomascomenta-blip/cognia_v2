"""
cognia_v3 — paquete de la arquitectura cognitiva v3 (core, memory, interfaces,
training, eval). Los módulos legacy de la raíz migran aquí (ver AUDIT.md).

Shim de compatibilidad (temporal, Task 0.2→0.3): este paquete tiene precedencia
de import sobre el módulo homónimo `cognia_v3.py` de la raíz, así que sin esto
`from cognia_v3 import Cognia` rompería en investigador.py / cognia_idle.py /
aprendizaje_profundo.py. Se elimina cuando cognia_v3.py se mueva al paquete.
"""
import importlib.util as _ilu
import os as _os

__version__ = "3.0.0"

_LEGACY_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "cognia_v3.py")
_legacy_mod = None


def _load_legacy():
    global _legacy_mod
    if _legacy_mod is None:
        spec = _ilu.spec_from_file_location("_cognia_v3_legacy", _LEGACY_PATH)
        _legacy_mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(_legacy_mod)
    return _legacy_mod


def __getattr__(name):
    # PEP 562: carga lazy del módulo legacy solo si alguien pide un símbolo suyo
    if not _os.path.exists(_LEGACY_PATH):
        raise AttributeError(f"module 'cognia_v3' has no attribute {name!r}")
    return getattr(_load_legacy(), name)
