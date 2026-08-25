"""`python -m cognia.remoto [--host IP] [--port N] [--limpiar [--dry-run]]`.
Los flags los define servidor.construir_parser (tambien lee COGNIA_REMOTO_HOST
y COGNIA_REMOTO_PORT del entorno)."""

import sys

from .servidor import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
