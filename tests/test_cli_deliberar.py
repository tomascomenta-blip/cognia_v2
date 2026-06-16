"""
tests/test_cli_deliberar.py — comando /deliberar (FASE 2b).
El handler vive inline en el dispatch del REPL. Regresion rapida del wiring: el comando
debe estar registrado en la ayuda. El comportamiento (plan/critica/verify) lo cubre
tests/test_cognitive_loop.py (loop) + verificacion CLI real (ver MANAGER_LOG). No se testea
_run_deliberate con DB temporal porque crear una DB fria dispara el seeder del KG (fetches
de red, ~5 min); contra la DB tibia el deliberate es ~0.2s.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_deliberar_registered_in_help():
    import cognia.cli as cli
    assert "/deliberar" in cli._CMD_DESCRIPTIONS
    assert "/deliberar" in cli._CMD_DETAILS
