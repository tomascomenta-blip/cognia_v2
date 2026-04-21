"""
cognia_deferred.py — Tareas de mantenimiento diferidas para Cognia v3
======================================================================
Saca del hot-path de observe() dos operaciones costosas:

  1. DeferredMaintenance    — consolidation y forgetting en hilo de fondo
  2. IdleHypothesisScheduler — generate_from_pattern solo cuando CPU < 40%
                               y han pasado ≥ 60 s desde la última hipótesis

INTEGRACIÓN EN cognia_v3.py → Cognia.__init__():

    from cognia_deferred import DeferredMaintenance, IdleHypothesisScheduler

    self._maintenance   = DeferredMaintenance(self, throttle_controller=self.fatigue)
    self._hyp_scheduler = IdleHypothesisScheduler(
        self,
        min_idle_s=60.0,
        cpu_threshold=40.0,
    )

EN observe() — reemplazar los bloques al final:

    # ANTES (bloquea hilo principal):
    #   if self.interaction_count % self.consolidation_interval == 0 and not defer_consolidation:
    #       n = self.consolidation.consolidate()
    #   if self.interaction_count % self.forgetting_interval == 0:
    #       stats = self.forgetting.decay_cycle()

    # DESPUÉS (no bloquea):
    self._maintenance.tick(self.interaction_count)

    # ANTES (en modo inferencia):
    #   if len(similar) >= 2:
    #       pattern_hypothesis = self.hypothesis.generate_from_pattern(similar)

    # DESPUÉS:
    pattern_hypothesis = self._hyp_scheduler.maybe_run(similar)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional, List

try:
    import psutil
    _PROC = psutil.Process(os.getpid())
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    _PROC = None


# ══════════════════════════════════════════════════════════════════════
# 1. DEFERRED MAINTENANCE
# ══════════════════════════════════════════════════════════════════════

class DeferredMaintenance:
    """
    Ejecuta consolidation.consolidate() y forgetting.decay_cycle() en un hilo
    de fondo, nunca bloqueando el hilo que espera respuesta el usuario.

    Política de ejecución:
      - Consolidation: solo si el throttle no está en nivel "critical" o "low"
      - Forgetting:    solo si CPU < 50%
      - Si las condiciones no se cumplen, el evento queda pendiente y se reintenta
        en la siguiente iteración del worker (cada 5 s).
    """

    WORKER_POLL_S  = 5.0   # cada cuántos segundos el worker revisa eventos
    CPU_MAX_FORGET = 50.0  # % CPU máximo para ejecutar forgetting

    def __init__(self, cognia_instance, throttle_controller=None):
        self._ai  = cognia_instance
        self._tc  = throttle_controller

        self._pending_consolidation = threading.Event()
        self._pending_forgetting    = threading.Event()

        self._worker = threading.Thread(
            target=self._run, daemon=True, name="MaintenanceWorker"
        )
        self._worker.start()

    # ── API pública ────────────────────────────────────────────────────

    def tick(self, interaction_count: int) -> None:
        """
        Llamar desde observe() en lugar de las llamadas directas.
        No bloquea — solo activa eventos.
        """
        cons_interval = getattr(self._ai, "consolidation_interval", 8)
        forg_interval = getattr(self._ai, "forgetting_interval",    20)

        if interaction_count % cons_interval == 0:
            self._pending_consolidation.set()

        if interaction_count % forg_interval == 0:
            self._pending_forgetting.set()

    # ── Worker ─────────────────────────────────────────────────────────

    def _run(self):
        while True:
            time.sleep(self.WORKER_POLL_S)

            # ── Consolidation ──────────────────────────────────────────
            if self._pending_consolidation.is_set():
                if not self._is_overloaded():
                    try:
                        n = self._ai.consolidation.consolidate()
                        if n and n > 0:
                            print(f"[Maintenance] ✅ Consolidation: {n} conceptos", flush=True)
                    except Exception as e:
                        print(f"[Maintenance] ⚠️  Consolidation error: {e}", flush=True)
                    finally:
                        self._pending_consolidation.clear()
                # Si está sobrecargado, el evento queda activo y se reintenta

            # ── Forgetting ─────────────────────────────────────────────
            if self._pending_forgetting.is_set():
                cpu = self._cpu_percent()
                if cpu < self.CPU_MAX_FORGET:
                    try:
                        stats = self._ai.forgetting.decay_cycle()
                        if stats:
                            print(f"[Maintenance] ✅ Forgetting: {stats}", flush=True)
                    except Exception as e:
                        print(f"[Maintenance] ⚠️  Forgetting error: {e}", flush=True)
                    finally:
                        self._pending_forgetting.clear()

    # ── Helpers ────────────────────────────────────────────────────────

    def _is_overloaded(self) -> bool:
        """True si el throttle está en modo crítico o bajo."""
        if self._tc is None:
            return False
        try:
            level = getattr(self._tc, "level", None) or getattr(self._tc, "_level", None)
            return level in ("critical", "low")
        except Exception:
            return False

    def _cpu_percent(self) -> float:
        if HAS_PSUTIL and _PROC:
            try:
                return _PROC.cpu_percent(interval=None)
            except Exception:
                pass
        return 0.0


# ══════════════════════════════════════════════════════════════════════
# 2. IDLE HYPOTHESIS SCHEDULER
# ══════════════════════════════════════════════════════════════════════

class IdleHypothesisScheduler:
    """
    Reemplaza la llamada directa a hypothesis.generate_from_pattern() dentro
    de observe() que se disparaba en prácticamente cada ciclo.

    Nueva política:
      - Solo genera hipótesis si han pasado ≥ min_idle_s desde la última
      - Solo genera hipótesis si CPU < cpu_threshold
      - Retorna None inmediatamente si las condiciones no se cumplen
        (observe() sigue sin bloquear)
    """

    def __init__(
        self,
        cognia_instance,
        min_idle_s: float   = 60.0,
        cpu_threshold: float = 40.0,
    ):
        self._ai             = cognia_instance
        self._min_idle_s     = min_idle_s
        self._cpu_threshold  = cpu_threshold
        self._last_run_time  = 0.0   # epoch seconds

    # ── API pública ────────────────────────────────────────────────────

    def maybe_run(self, similar: list) -> Optional[dict]:
        """
        Devuelve la hipótesis generada o None.
        Nunca bloquea más de lo que tarda generate_from_pattern() cuando se
        decide ejecutar.

        Reemplaza directamente:
            if len(similar) >= 2:
                pattern_hypothesis = self.hypothesis.generate_from_pattern(similar)
        por:
            pattern_hypothesis = self._hyp_scheduler.maybe_run(similar)
        """
        if len(similar) < 2:
            return None

        now = time.monotonic()
        elapsed = now - self._last_run_time

        if elapsed < self._min_idle_s:
            return None   # demasiado reciente — saltar sin coste

        cpu = self._cpu_percent()
        if cpu >= self._cpu_threshold:
            return None   # sistema ocupado — saltar

        # Condiciones OK: ejecutar
        try:
            result = self._ai.hypothesis.generate_from_pattern(similar)
            self._last_run_time = now
            return result
        except Exception as e:
            print(f"[HypothesisScheduler] Error: {e}", flush=True)
            return None

    # ── Helper ─────────────────────────────────────────────────────────

    def _cpu_percent(self) -> float:
        if HAS_PSUTIL and _PROC:
            try:
                return _PROC.cpu_percent(interval=None)
            except Exception:
                pass
        return 0.0
