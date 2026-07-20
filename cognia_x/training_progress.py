r"""
training_progress.py -- Puente entreno -> dashboard de la TUI.

Que: ProgressWriter escribe en vivo el archivo de progreso que la TUI ya sabe
leer (cognia/tui/training_monitor.py:TrainingMonitor). Esquema FIJO (el que el
TUI normaliza): status, run_name, epoch, total_epochs, step, total_steps,
tokens_per_s, loss, lr, batch_size, eta_s, vram_pct, started_at, updated_at.

Por que: el harness de entreno (cognia_x/train/fast_harness.py) ya calcula step,
loss, lr y el batch en cada paso; este modulo los serializa cada N pasos a un
JSON que el dashboard polea sin bloquear. Escritura ATOMICA (a .tmp + os.replace)
para que el lector nunca vea un JSON a medias. Best-effort: ningun fallo de IO
puede tumbar el entrenamiento -> todo va envuelto en try/except.

Honestidad: lo que no se mide se escribe None (no se inventa). En CPU sin GPU,
vram_pct queda None; tokens_per_s se deriva del ritmo REAL medido si el harness
pasa los tokens por paso, si no queda None.

Ruta por defecto: <repo>/cognia_x/training_progress.json -- la MISMA que
TrainingMonitor usa por defecto, para que enchufar sea cero-config.

Convencion: codigo ASCII; los textos pueden ir en UTF-8.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Mismo archivo que TrainingMonitor lee por defecto. Este modulo vive en
# cognia_x/, asi que parent == <repo>/cognia_x.
DEFAULT_PROGRESS_PATH = Path(__file__).resolve().parent / "training_progress.json"

_FINAL_STATUS = ("done", "error")

# Estado del lazy-init de pynvml (solo si corre en GPU y pynvml esta instalado).
_NVML: Dict[str, Any] = {"init": False, "ok": False, "handle": None, "mod": None}


def _read_vram_pct() -> Optional[float]:
    """%% de VRAM usada via pynvml, o None si no hay GPU / pynvml (honesto).

    Inicializa pynvml UNA vez (lazy) y cachea el handle; cada lectura es barata.
    Cualquier fallo -> None (nunca levanta)."""
    try:
        if not _NVML["init"]:
            _NVML["init"] = True
            try:
                import pynvml  # type: ignore

                pynvml.nvmlInit()
                _NVML["mod"] = pynvml
                _NVML["handle"] = pynvml.nvmlDeviceGetHandleByIndex(0)
                _NVML["ok"] = True
            except Exception:  # noqa: BLE001 - sin GPU/pynvml: degrada a None
                _NVML["ok"] = False
        if not _NVML["ok"]:
            return None
        mem = _NVML["mod"].nvmlDeviceGetMemoryInfo(_NVML["handle"])
        if not mem.total:
            return None
        return round(100.0 * mem.used / mem.total, 1)
    except Exception:  # noqa: BLE001
        return None


class ProgressWriter:
    """Escribe el progreso de una corrida al JSON que lee la TUI.

    Uso desde un loop de entreno:
        w = ProgressWriter(run_name="g2", total_epochs=1, total_steps=5000)
        w.start()
        for step in ...:
            ...
            w.update(step, epoch, loss=..., lr=..., batch_size=...)
        w.finish("done")

    `write_every`: cada cuantos pasos persiste (ademas de cada cambio de epoch y
    del paso final). Todo es best-effort: si el disco falla, el entrenamiento NO
    se entera."""

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        run_name: str = "",
        total_epochs: int = 0,
        total_steps: int = 0,
        write_every: int = 10,
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PROGRESS_PATH
        self.run_name = run_name
        self.total_epochs = int(total_epochs or 0)
        self.total_steps = int(total_steps or 0)
        self.write_every = max(1, int(write_every))
        self.started_at: Optional[float] = None
        # Ancla de ritmo: (tiempo, paso) del ultimo write -> sps reciente para ETA.
        self._prev_t: float = 0.0
        self._prev_step: int = 0
        self._last_epoch: Optional[int] = None
        # Ultimo payload escrito -> finish() reusa los valores reales finales.
        self._last_payload: Optional[Dict[str, Any]] = None

    # -- API publica -------------------------------------------------------

    def start(self) -> None:
        """Marca la corrida como 'running' y fija started_at + totales."""
        try:
            now = time.time()
            self.started_at = now
            self._prev_t = now
            self._prev_step = 0
            self._last_epoch = None
            payload = self._payload("running", step=0, epoch=0, updated_at=now)
            self._last_payload = payload
            self._write_atomic(payload)
        except Exception:  # noqa: BLE001 - nunca romper el entreno por un write
            pass

    def update(
        self,
        step: int,
        epoch: int = 0,
        loss: Optional[float] = None,
        lr: Optional[float] = None,
        batch_size: Optional[int] = None,
        tokens_per_s: Optional[float] = None,
        tokens_per_step: Optional[int] = None,
    ) -> None:
        """Persiste el progreso cada `write_every` pasos (o si cambio epoch / es
        el paso final). Calcula eta_s con el ritmo REAL entre writes; si no se
        pasa tokens_per_s pero si tokens_per_step, deriva tokens_per_s = tps*sps
        (tokens/s MEDIDO). Best-effort: nunca levanta."""
        try:
            epoch_changed = self._last_epoch is not None and epoch != self._last_epoch
            is_final = bool(self.total_steps) and step >= self.total_steps
            due = (step % self.write_every == 0) or epoch_changed or is_final
            self._last_epoch = epoch
            if not due:
                return

            now = time.time()
            dt = now - self._prev_t
            dstep = step - self._prev_step
            sps = (dstep / dt) if (dt > 0 and dstep > 0) else None

            eta_s: Optional[float] = None
            if sps and self.total_steps:
                eta_s = max(0, self.total_steps - step) / sps

            tps = tokens_per_s
            if tps is None and tokens_per_step is not None and sps is not None:
                tps = float(tokens_per_step) * sps

            self._prev_t = now
            self._prev_step = step

            payload = self._payload(
                "running",
                step=step,
                epoch=epoch,
                loss=loss,
                lr=lr,
                batch_size=batch_size,
                tokens_per_s=tps,
                eta_s=eta_s,
                updated_at=now,
            )
            self._last_payload = payload
            self._write_atomic(payload)
        except Exception:  # noqa: BLE001
            pass

    def finish(self, status: str = "done") -> None:
        """Escribe el estado final ('done' o 'error') reusando las ultimas
        metricas reales. eta_s=0 al completar. Best-effort."""
        try:
            now = time.time()
            status = status if status in _FINAL_STATUS else "done"
            base = dict(self._last_payload) if self._last_payload else self._payload("running")
            base["status"] = status
            base["updated_at"] = now
            base["vram_pct"] = _read_vram_pct()
            if status == "done":
                base["eta_s"] = 0
            self._last_payload = base
            self._write_atomic(base)
        except Exception:  # noqa: BLE001
            pass

    # -- internos ----------------------------------------------------------

    def _payload(
        self,
        status: str,
        step: int = 0,
        epoch: int = 0,
        loss: Optional[float] = None,
        lr: Optional[float] = None,
        batch_size: Optional[int] = None,
        tokens_per_s: Optional[float] = None,
        eta_s: Optional[float] = None,
        updated_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Arma el dict con el esquema EXACTO que TrainingMonitor normaliza."""
        return {
            "status": status,
            "run_name": self.run_name,
            "epoch": int(epoch),
            "total_epochs": self.total_epochs,
            "step": int(step),
            "total_steps": self.total_steps,
            "tokens_per_s": None if tokens_per_s is None else float(tokens_per_s),
            "loss": None if loss is None else float(loss),
            "lr": None if lr is None else float(lr),
            "batch_size": None if batch_size is None else int(batch_size),
            "eta_s": None if eta_s is None else float(eta_s),
            "vram_pct": _read_vram_pct(),
            "started_at": self.started_at,
            "updated_at": updated_at,
        }

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """Escribe `data` a path.tmp y os.replace -> el lector ve JSON completo
        o el anterior, jamas uno a medias."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)  # atomico en el mismo filesystem
