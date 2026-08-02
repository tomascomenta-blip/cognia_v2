"""
tests/test_scale_manager.py
============================
Tests del contrato de ScaleManager tras degradarlo a PURO REPORTE (2026-08-01).

select_model()/get_timeout() fueron borrados: eran alias de
get_config().model/.timeout_s sin llamadores en produccion, con nombres de
modelo de la era Ollama (llama3.2/mixtral) que no existen en la flota actual.
El contrato vivo es status() (lo consumen cli.py /escalar y
app/routes/status.py) y get_config()/detect_level().
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.scale_manager import ScaleManager, LEVEL_CONFIGS


@pytest.fixture
def sm(tmp_path):
    # db_path inexistente: _count_memories devuelve 0 y no toca DBs reales
    return ScaleManager(db_path=str(tmp_path / "no_existe.db"))


class TestStatusContract:
    def test_status_has_all_report_fields(self, sm):
        st = sm.status()
        for key in ("level", "name", "model", "timeout_s", "ram_gb",
                    "memories", "peers", "hit_counts"):
            assert key in st, f"status() perdio la clave '{key}'"

    def test_status_matches_get_config(self, sm):
        st = sm.status()
        cfg = sm.get_config()
        assert st["model"] == cfg.model
        assert st["timeout_s"] == cfg.timeout_s
        assert st["level"] == cfg.level

    def test_level_within_catalog(self, sm):
        assert 1 <= sm.level <= len(LEVEL_CONFIGS)


class TestReportOnly:
    def test_selector_api_removed(self, sm):
        """Regresion 2026-08-01: el modulo es solo-reporte; los alias de
        seleccion de modelo no deben volver sin un llamador real (el router
        vive en node/fleet.py + enrutador, no aqui)."""
        assert not hasattr(sm, "select_model")
        assert not hasattr(sm, "get_timeout")

    def test_compute_level_thresholds(self, sm):
        assert sm._compute_level(2.0, 50, 0) == 1
        assert sm._compute_level(8.0, 500, 0) == 2
        assert sm._compute_level(16.0, 20000, 0) == 3
