"""
test_tui_training.py -- Verificacion headless del dashboard de entrenamiento.

Corre la app con Pilot (run_test, sin terminal) y comprueba: que sin archivo de
progreso el dashboard muestra su empty-state (idle, no pantalla vacia); que con un
progreso 'running' inyectado aparecen el nombre de la corrida, epoch X/Y,
tokens/s, loss y un VRAM honesto ('--' cuando es None); que TrainingMonitor lee un
JSON real y degrada a 'idle' si el archivo falta; y que en 'running' hay dos
ProgressBar (epoch y step).

pytest-asyncio en modo auto (pytest.ini): los tests async se detectan solos.
"""

from __future__ import annotations

import json

import pytest
from textual.widgets import ProgressBar

from cognia.tui.app import CogniaTUI
from cognia.tui.training_monitor import TrainingMonitor
from cognia.tui.widgets.training import TrainingDashboard

_RUNNING = {
    "status": "running",
    "epoch": 2,
    "total_epochs": 5,
    "step": 1200,
    "total_steps": 5000,
    "tokens_per_s": 8.3,
    "loss": 1.42,
    "lr": 3e-4,
    "batch_size": 8,
    "eta_s": 600,
    "vram_pct": None,
    "run_name": "g2",
}


@pytest.mark.asyncio
async def test_empty_state_when_idle(tmp_path):
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        dash = app.query_one(TrainingDashboard)
        # Apuntar a una ruta inexistente para garantizar 'idle' deterministico.
        dash.monitor = TrainingMonitor(tmp_path / "missing.json")
        dash._poll()
        await pilot.pause()
        assert dash.progress["status"] == "idle"
        assert "Sin entrenamiento activo" in dash.dashboard_text()


@pytest.mark.asyncio
async def test_renders_metrics_when_running():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        dash = app.query_one(TrainingDashboard)
        dash.set_progress(dict(_RUNNING))
        await pilot.pause()
        text = dash.dashboard_text()
        assert dash.progress["status"] == "running"
        assert "g2" in text          # nombre de la corrida
        assert "2/5" in text         # epoch X/Y
        assert "8.3" in text         # tokens/s
        assert "1.42" in text        # loss
        # VRAM honesto: None -> '--', nunca un numero inventado.
        assert dash.progress["vram_pct"] is None
        assert "--" in text


def test_monitor_reads_json(tmp_path):
    prog = {
        "status": "running",
        "run_name": "r1",
        "epoch": 3,
        "total_epochs": 10,
        "loss": 0.97,
    }
    path = tmp_path / "training_progress.json"
    path.write_text(json.dumps(prog), encoding="utf-8")
    out = TrainingMonitor(path).read()
    assert out["status"] == "running"
    assert out["run_name"] == "r1"
    assert out["epoch"] == 3
    assert out["total_epochs"] == 10
    assert out["loss"] == 0.97
    # Ruta inexistente -> 'idle' (sin levantar).
    assert TrainingMonitor(tmp_path / "nope.json").read()["status"] == "idle"
    # JSON corrupto -> 'idle' (sin levantar).
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert TrainingMonitor(bad).read()["status"] == "idle"


@pytest.mark.asyncio
async def test_progress_bars_present():
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        dash = app.query_one(TrainingDashboard)
        dash.set_progress(dict(_RUNNING))
        await pilot.pause()
        bars = dash.query(ProgressBar)
        assert len(bars) == 2
        ids = {bar.id for bar in bars}
        assert ids == {"train-epoch-bar", "train-step-bar"}
