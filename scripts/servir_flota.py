"""
servir_flota.py — levanta el COMBO de modelos correcto para cada tarea.

La logica vive en cognia/flota.py (WP6 2026-08-09): scripts/ no viaja en el
wheel y el comando instalado `cognia flota <arrancar|estado|parar>` necesita
los combos dentro del paquete. Este script queda como el punto de entrada
historico del repo y DELEGA — dos copias de los combos fue exactamente como
el :8088 sirvio un modelo retirado sin que nadie lo viera.

    python scripts/servir_flota.py pensar          # gpt-oss-20b :8080
    python scripts/servir_flota.py construir       # coder-14b(+draft) + VL-3B
    python scripts/servir_flota.py construir-ui    # UIGEN-X-8B + VL-3B
    python scripts/servir_flota.py pensar-en-lazo  # OpenReasoning-14B + VL-3B
    python scripts/servir_flota.py juzgar          # VL-7B :8081 (solo)
    python scripts/servir_flota.py solo [patron]   # UN solo modelo en :8080
    python scripts/servir_flota.py parar           # detiene los llama-server
    python scripts/servir_flota.py estado          # que GGUF sirve cada puerto

Ver cognia/flota.py para los combos y la regla de VRAM.
"""

from __future__ import annotations

import sys
from pathlib import Path

# El repo no esta instalado necesariamente: scripts/ es sys.path[0] al correr
# este archivo, asi que la raiz (donde vive cognia/) se agrega a mano.
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from cognia.flota import main   # noqa: E402  (la logica unica, sin duplicar)

if __name__ == "__main__":
    sys.exit(main())
