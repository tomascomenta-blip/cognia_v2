"""
test_training_progress.py -- Puente entreno -> dashboard (training_progress.json).

Verifica el ProgressWriter (cognia_x/training_progress.py) y su enganche al harness
real (cognia_x/train/fast_harness.py):

  * Unit: escritura ATOMICA legible por TrainingMonitor; gating cada write_every;
    best-effort (nunca levanta ante un path invalido).
  * E2E REAL: corre un entrenamiento CORTO de verdad con el harness + progress
    activado y comprueba que el JSON final trae metricas REALES (loss>0, step==N).
  * TUI: TrainingMonitor lee el archivo generado y el TrainingDashboard sale de
    'idle' (set_progress con la lectura real).

pytest-asyncio en modo auto (pytest.ini).
"""
from __future__ import annotations

import pytest

from cognia.tui.training_monitor import TrainingMonitor
from cognia_x.training_progress import ProgressWriter


# -- unit: atomic write + lectura por el monitor --------------------------------

def test_atomic_write_and_read(tmp_path):
    path = tmp_path / "training_progress.json"
    w = ProgressWriter(path=path, run_name="t-atomic", total_epochs=1,
                       total_steps=20, write_every=5)
    mon = TrainingMonitor(path)

    w.start()
    p = mon.read()
    assert p["status"] == "running"
    assert p["run_name"] == "t-atomic"
    assert p["total_steps"] == 20
    assert p["total_epochs"] == 1

    w.update(step=5, epoch=1, loss=2.0, lr=1e-3, batch_size=8)
    p = mon.read()
    assert p["status"] == "running"
    assert p["step"] == 5
    assert p["loss"] == 2.0
    assert p["lr"] == 1e-3
    assert p["batch_size"] == 8

    w.update(step=20, epoch=1, loss=0.5, lr=1e-3, batch_size=8)
    w.finish()
    p = mon.read()
    assert p["status"] == "done"
    assert p["step"] == 20
    assert p["loss"] == 0.5      # finish reusa la ultima metrica real
    assert p["eta_s"] == 0


# -- unit: gating cada write_every ----------------------------------------------

def test_write_every(tmp_path):
    path = tmp_path / "training_progress.json"
    # total_steps=0 -> sin gatillo de 'paso final'; epoch constante -> sin gatillo
    # de epoch. Asi el unico gatillo es step % write_every.
    w = ProgressWriter(path=path, run_name="t-every", total_epochs=1,
                       total_steps=0, write_every=5)
    w.start()

    writes = []
    w._write_atomic = lambda data: writes.append(data["step"])  # espia post-start
    for s in range(1, 11):
        w.update(step=s, epoch=1, loss=1.0, lr=1e-3, batch_size=4)
    assert writes == [5, 10]


# -- unit: best-effort (nunca levanta) ------------------------------------------

def test_never_raises(tmp_path):
    bad = tmp_path / "iam_a_dir"      # path que es un DIRECTORIO -> os.replace falla
    bad.mkdir()
    w = ProgressWriter(path=bad, run_name="t-bad", total_epochs=1,
                       total_steps=10, write_every=1)
    # Ninguna de estas debe levantar pese a que el write falla internamente.
    w.start()
    w.update(step=1, epoch=1, loss=1.0, lr=1e-3, batch_size=2)
    w.finish("error")
    # El lector tampoco rompe: no hay JSON valido -> 'idle'.
    assert TrainingMonitor(bad).read()["status"] == "idle"


# -- E2E REAL: harness + progress escribe metricas reales -----------------------

def test_e2e_harness_writes_real_progress(tmp_path):
    import numpy as np

    from cognia_x.train.fast_harness import train
    from cognia_x.train.recall_task import make_recall_batch

    p = dict(batch=16, n_pairs=8, n_queries=6, n_keys=48, n_vals=16)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    cfg_model = dict(vocab_size=vocab, d_model=64, n_layers=4, n_heads=4,
                     window=L + 1, attn_every=2, max_seq_len=L + 1)
    rng = np.random.default_rng(0)

    def bf(step):
        return make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], "cpu")

    ppath = tmp_path / "training_progress.json"
    out = tmp_path / "_run"
    # Captura cada payload que el harness escribe -> demuestra step que avanza /
    # loss que baja con metricas REALES del modelo entrenando.
    seen = []
    orig = ProgressWriter._write_atomic

    def spy(self, data):
        seen.append(dict(data))
        return orig(self, data)

    ProgressWriter._write_atomic = spy
    try:
        train(cfg_model, dict(steps=30, lr=1e-3, ckpt_every=15, amp=False, seed=0,
                              run_name="e2e", progress_every=5),
              str(out), bf, device="cpu", log=lambda *a, **k: None, progress=str(ppath))
    finally:
        ProgressWriter._write_atomic = orig

    final = TrainingMonitor(ppath).read()
    assert final["status"] == "done"
    assert final["step"] == 30
    assert final["run_name"] == "e2e"
    assert final["loss"] is not None and final["loss"] > 0   # loss REAL del modelo
    assert final["batch_size"] == 16
    assert final["lr"] is not None

    running = [s for s in seen if s["status"] == "running" and s["step"] > 0]
    assert [s["step"] for s in running] == [5, 10, 15, 20, 25, 30]
    first_loss, last_loss = running[0]["loss"], running[-1]["loss"]
    assert last_loss < first_loss     # loss BAJA durante el entreno real


# -- TUI: el dashboard lee el archivo generado y sale de 'idle' -----------------

@pytest.mark.asyncio
async def test_tui_reads_generated_progress(tmp_path):
    from cognia.tui.app import CogniaTUI
    from cognia.tui.widgets.training import TrainingDashboard

    path = tmp_path / "training_progress.json"
    w = ProgressWriter(path=path, run_name="bridge", total_epochs=1,
                       total_steps=10, write_every=1)
    w.start()
    w.update(step=5, epoch=1, loss=1.23, lr=3e-4, batch_size=8)

    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        dash = app.query_one(TrainingDashboard)
        dash.monitor = TrainingMonitor(path)
        dash._poll()
        await pilot.pause()
        assert dash.progress["status"] != "idle"
        assert dash.progress["run_name"] == "bridge"
        assert dash.progress["loss"] == 1.23
        # set_progress con la lectura real -> sigue no-idle (item 3 del CP10).
        dash.set_progress(dash.monitor.read())
        await pilot.pause()
        assert dash.progress["status"] == "running"
        assert "bridge" in dash.dashboard_text()
