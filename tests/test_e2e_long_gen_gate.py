"""
tests/test_e2e_long_gen_gate.py
Tests de _gate_verdict() de scripts/e2e_long_gen.py — el CHECK del gate E2E
de generacion larga. Sin server: la funcion es pura.

Regresion del 2026-06-11: el gate fallo por 4 tokens (4996/5000) porque el
modelo cerro natural (eos); un fin natural a <5% del target debe ser PASS.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_e2e_module():
    """Importa scripts/e2e_long_gen.py por path (scripts/ no es paquete)."""
    path = REPO_ROOT / "scripts" / "e2e_long_gen.py"
    spec = importlib.util.spec_from_file_location("e2e_long_gen", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["e2e_long_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestGateVerdict:
    def test_eos_within_5pct_of_target_passes(self):
        """Caso real del 2026-06-11: 4996/5000 con eos -> PASS."""
        mod = _load_e2e_module()
        assert mod._gate_verdict(4996, 5000, "eos") is True

    def test_limit_far_from_target_fails(self):
        """Corte por n_predict lejos del target -> FAIL (no es fin natural)."""
        mod = _load_e2e_module()
        assert mod._gate_verdict(4000, 5000, "limit") is False

    def test_target_reached_passes_any_reason(self):
        mod = _load_e2e_module()
        assert mod._gate_verdict(5000, 5000, "limit") is True
        assert mod._gate_verdict(5120, 5000, "eos") is True

    def test_limit_within_5pct_still_fails(self):
        """4996/5000 pero por 'limit' -> FAIL: la tolerancia es solo para eos."""
        mod = _load_e2e_module()
        assert mod._gate_verdict(4996, 5000, "limit") is False

    def test_eos_below_95pct_fails(self):
        """eos demasiado temprano (4000/5000 = 80%) -> FAIL."""
        mod = _load_e2e_module()
        assert mod._gate_verdict(4000, 5000, "eos") is False

    def test_eos_exactly_95pct_passes(self):
        mod = _load_e2e_module()
        assert mod._gate_verdict(4750, 5000, "eos") is True

    def test_none_stop_reason_fails_below_target(self):
        mod = _load_e2e_module()
        assert mod._gate_verdict(4996, 5000, None) is False
