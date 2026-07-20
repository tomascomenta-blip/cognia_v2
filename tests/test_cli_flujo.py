"""tests/test_cli_flujo.py — FASE 5: el comando /flujo esta registrado en el REPL."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_flujo_registered_in_help():
    import cognia.cli as cli
    assert "/flujo" in cli._CMD_DESCRIPTIONS
    assert "/flujo" in cli._CMD_DETAILS
