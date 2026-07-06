"""
cognia/runtime_mode.py
======================
Interruptor duro local-only para la version COMERCIAL de Cognia.

Por default Cognia corre 100% local (solo el modelo 3B via llama.cpp): el swarm /
orquestacion online solo se activa si hay una URL de coordinador en el entorno. La
version comercial ademas expone un flag DURO, `COGNIA_DISABLE_SWARM=1`, que fuerza
el modo local aunque una env var de coordinador este seteada por error o herencia
-> garantiza "corre unicamente con el 3B", sin fugas a la red.

Concreto: dos funciones puras sobre os.environ, sin estado ni deps.
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}


def swarm_disabled() -> bool:
    """True si el usuario forzo el modo local-only (COGNIA_DISABLE_SWARM)."""
    return os.environ.get("COGNIA_DISABLE_SWARM", "").strip().lower() in _TRUE


def coordinator_url() -> str:
    """URL del coordinador del swarm, o "" si el swarm esta deshabilitado (por el
    flag duro) o no configurado. Todos los sitios que decidan local-vs-online
    deben pasar por aca en vez de leer las env vars directo."""
    if swarm_disabled():
        return ""
    return (os.environ.get("COGNIA_COORDINATOR_URL", "")
            or os.environ.get("COORDINATOR_URL", "")).strip()
