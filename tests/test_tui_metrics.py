"""
test_tui_metrics.py -- Verificacion headless del widget de metricas de sistema.

Comprueba que SystemMetrics lee valores REALES de psutil (rangos validos), que el
helper de color respeta los umbrales (ok/warn/err), y que el empty-state de GPU es
honesto (None cuando no hay GPU/pynvml, nunca un numero inventado).

pytest-asyncio en modo auto (pytest.ini): los tests async se detectan solos.
"""

from __future__ import annotations

import pytest

from cognia.tui.app import CogniaTUI
from cognia.tui.widgets.metrics import SystemMetrics, threshold_color


@pytest.mark.asyncio
async def test_metrics_widget_reads_real_values():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        metrics = app.query_one(SystemMetrics)
        # Forzar una lectura real (no esperar al timer de 1s).
        metrics.refresh_metrics()
        await pilot.pause()
        snap = metrics.snapshot()
        for key in ("cpu", "ram", "disk"):
            assert isinstance(snap[key], float)
            assert 0.0 <= snap[key] <= 100.0


def test_metrics_color_thresholds():
    # <60 -> ok, 60-85 -> warn, >85 -> err.
    assert threshold_color(45) == "ok"
    assert threshold_color(70) == "warn"
    assert threshold_color(95) == "err"


@pytest.mark.asyncio
async def test_metrics_no_fake_gpu():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        metrics = app.query_one(SystemMetrics)
        metrics.refresh_metrics()
        await pilot.pause()
        gpu = metrics.snapshot()["gpu"]
        # Sin GPU/pynvml: None o "--", nunca un numero inventado.
        assert gpu is None or gpu == "--"
