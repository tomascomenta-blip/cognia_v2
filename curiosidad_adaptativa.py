"""
curiosidad_adaptativa.py — Scheduler de curiosidad inteligente para Cognia v3
==============================================================================
Reemplaza el loop de intervalo fijo de CuriosidadPasiva por un scheduler que
solo investiga cuando:
  1. El sistema tiene suficiente novedad acumulada (nuevos episodios)
  2. CPU < 30% y RAM < 70%
  3. No hay conversación activa (≥ 120 s de inactividad)
  4. Como fallback: máximo 4 horas sin investigar, pase lo que pase

RETROCOMPATIBILIDAD TOTAL con web_app.py:
  - Misma API: .iniciar(), .detener(), .forzar_ciclo(), .estado()
  - Mismo registro de rutas: register_routes_curiosidad(app, curiosidad)
  - El objeto puede pasarse donde antes iba un CuriosidadPasiva

MIGRACIÓN EN web_app.py:
  # ANTES:
  #   from curiosidad_pasiva import CuriosidadPasiva, register_routes_curiosidad
  #   curiosidad = CuriosidadPasiva(get_cognia)

  # DESPUÉS:
  from curiosidad_adaptativa import AdaptiveCuriosity, register_routes_curiosidad
  curiosidad = AdaptiveCuriosity(get_cognia)

  curiosidad.iniciar()   # idéntico al anterior
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Configuración (respeta las mismas variables de entorno que curiosidad_pasiva.py)
MAX_POR_DIA = int(os.environ.get("COGNIA_CURIOSIDAD_MAX_DIA", 10))

try:
    import psutil
    _PROC    = psutil.Process(os.getpid())
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    _PROC    = None


# ══════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class AdaptiveCuriosity:
    """
    Scheduler de curiosidad pasiva adaptativo.

    Diferencias clave vs CuriosidadPasiva:
      - NO usa un intervalo fijo. Revisa condiciones cada 30 s y decide.
      - NO itera 1800 veces con time.sleep(1). Usa threading.Event.wait().
      - Tiene en cuenta CPU, RAM, inactividad y novedad antes de investigar.
      - Notifica la actividad del usuario para no interrumpir conversaciones.
    """

    # ── Umbrales configurables ────────────────────────────────────────
    NOVEDAD_UMBRAL     = 5       # nuevos episodios para disparar curiosidad
    CPU_MAX            = 30.0    # % CPU máximo para investigar
    RAM_MAX            = 70.0    # % RAM del sistema máximo
    IDLE_MIN_S         = 120.0   # segundos mínimos de inactividad
    FALLBACK_INTERVAL  = 14400   # segundos (4h) máximo sin investigar
    CHECK_INTERVAL     = 30.0    # segundos entre revisiones de condiciones
    LOG_MAX            = 50      # entradas máximas en el historial

    def __init__(
        self,
        ai_getter,
        db_path: str = "cognia_memory.db",
        # Parámetro 'intervalo' ignorado — se mantiene por compatibilidad
        intervalo: int = 1800,
    ):
        self.ai_getter  = ai_getter
        self.db_path    = db_path

        self._activo    = False
        self._hilo: Optional[threading.Thread] = None
        self._stop      = threading.Event()

        self._lock      = threading.Lock()
        self._log: list = []
        self._ultimo_ciclo: Optional[dict] = None

        self._last_cycle_time   = 0.0          # monotonic
        self._last_user_msg     = time.monotonic()
        self._last_episodio_id  = 0

    # ── API pública (idéntica a CuriosidadPasiva) ─────────────────────

    def iniciar(self):
        """Inicia el hilo adaptativo."""
        if self._activo:
            return
        self._activo = True
        self._stop.clear()
        self._hilo = threading.Thread(
            target=self._run,
            name="AdaptiveCuriosity",
            daemon=True,
        )
        self._hilo.start()
        print(
            f"[AdaptiveCuriosity] Iniciada. "
            f"CPU_MAX={self.CPU_MAX}%, RAM_MAX={self.RAM_MAX}%, "
            f"IDLE_MIN={self.IDLE_MIN_S}s, máx/día={MAX_POR_DIA}"
        )

    def detener(self):
        """Detiene el hilo."""
        self._activo = False
        self._stop.set()
        if self._hilo:
            self._hilo.join(timeout=10)
        print("[AdaptiveCuriosity] Detenida.")

    def forzar_ciclo(self) -> dict:
        """Ejecuta un ciclo inmediatamente (testing / UI)."""
        try:
            ai = self.ai_getter()
            resultado = self._ejecutar_ciclo(ai)
            self._registrar(resultado)
            return resultado
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    def estado(self) -> dict:
        """Estado actual — compatible con el frontend existente."""
        inv_hoy = self._contar_investigaciones_hoy()
        with self._lock:
            ultimo = self._ultimo_ciclo
            historial = list(self._log[-5:])
        return {
            "activo":               self._activo,
            "intervalo_segundos":   int(self.FALLBACK_INTERVAL),   # compat
            "max_por_dia":          MAX_POR_DIA,
            "investigaciones_hoy":  inv_hoy,
            "ultimo_ciclo":         ultimo,
            "historial_reciente":   historial,
            "modo":                 "adaptativo",
            "umbrales": {
                "cpu_max":      self.CPU_MAX,
                "ram_max":      self.RAM_MAX,
                "idle_min_s":   self.IDLE_MIN_S,
                "novedad_umbral": self.NOVEDAD_UMBRAL,
            },
        }

    def notify_user_activity(self):
        """
        Llamar desde observe() para registrar actividad reciente.
        Evita que curiosidad interrumpa una conversación activa.
        """
        self._last_user_msg = time.monotonic()

    # ── Loop interno ──────────────────────────────────────────────────

    def _run(self):
        # Esperar arranque completo de Cognia
        self._stop.wait(timeout=90)
        if self._stop.is_set():
            return

        while not self._stop.wait(timeout=self.CHECK_INTERVAL):
            try:
                if self._should_investigate():
                    ai = self.ai_getter()
                    resultado = self._ejecutar_ciclo(ai)
                    self._registrar(resultado)

                    if resultado.get("investigado"):
                        print(
                            f"[AdaptiveCuriosity] ✨ '{resultado['titulo_wiki']}' "
                            f"(concepto: {resultado['concepto']}, "
                            f"+{resultado['hechos_guardados']} hechos)",
                            flush=True,
                        )
                    elif resultado.get("razon_skip"):
                        print(
                            f"[AdaptiveCuriosity] ⏭ {resultado['razon_skip']}",
                            flush=True,
                        )
            except Exception as e:
                print(f"[AdaptiveCuriosity] ❌ Error: {e}", flush=True)

    # ── Decisión de cuándo investigar ─────────────────────────────────

    def _should_investigate(self) -> bool:
        now = time.monotonic()

        # Fallback: máximo FALLBACK_INTERVAL sin investigar
        if (now - self._last_cycle_time) >= self.FALLBACK_INTERVAL:
            return True

        # No interrumpir conversación activa
        idle_s = now - self._last_user_msg
        if idle_s < self.IDLE_MIN_S:
            return False

        # Verificar recursos
        cpu = self._cpu_percent()
        ram = self._ram_percent()
        if cpu > self.CPU_MAX:
            return False
        if ram > self.RAM_MAX:
            return False

        # Verificar novedad acumulada
        novedad = self._contar_novedad()
        return novedad >= self.NOVEDAD_UMBRAL

    def _contar_novedad(self) -> int:
        """Episodios nuevos desde el último ciclo."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = str
            row = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE id > ? AND forgotten=0",
                (self._last_episodio_id,),
            ).fetchone()
            conn.close()
            return row[0] if row else 0
        except Exception:
            return 0

    def _contar_investigaciones_hoy(self) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = str
            hoy = datetime.now().strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory "
                "WHERE context_tags LIKE '%wikipedia%' AND timestamp LIKE ?",
                (f"{hoy}%",),
            ).fetchone()
            conn.close()
            return row[0] if row else 0
        except Exception:
            return 0

    # ── Ciclo de investigación (reutiliza lógica de curiosidad_pasiva) ─

    def _ejecutar_ciclo(self, ai) -> dict:
        """
        Delega al ciclo_curiosidad original para no duplicar lógica de
        Wikipedia / DuckDuckGo / guardar_en_cognia.
        """
        from curiosidad_pasiva import ciclo_curiosidad

        inv_hoy = self._contar_investigaciones_hoy()
        if inv_hoy >= MAX_POR_DIA:
            return {
                "timestamp": datetime.now().isoformat(),
                "investigado": False,
                "razon_skip": f"Cuota diaria alcanzada ({inv_hoy}/{MAX_POR_DIA})",
            }

        resultado = ciclo_curiosidad(ai, self.db_path)

        # Actualizar marcadores para el próximo ciclo
        self._last_cycle_time = time.monotonic()
        try:
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = str
            row = conn.execute("SELECT MAX(id) FROM episodic_memory").fetchone()
            self._last_episodio_id = row[0] or 0
            conn.close()
        except Exception:
            pass

        return resultado

    # ── Registro ──────────────────────────────────────────────────────

    def _registrar(self, resultado: dict):
        with self._lock:
            self._ultimo_ciclo = resultado
            self._log.append(resultado)
            if len(self._log) > self.LOG_MAX:
                self._log.pop(0)

    # ── Helpers de recursos ───────────────────────────────────────────

    def _cpu_percent(self) -> float:
        if HAS_PSUTIL and _PROC:
            try:
                return _PROC.cpu_percent(interval=None)
            except Exception:
                pass
        return 0.0

    def _ram_percent(self) -> float:
        if HAS_PSUTIL:
            try:
                return psutil.virtual_memory().percent
            except Exception:
                pass
        return 0.0


# ══════════════════════════════════════════════════════════════════════
# REGISTRO DE RUTAS FLASK (idéntico a curiosidad_pasiva.py)
# ══════════════════════════════════════════════════════════════════════

def register_routes_curiosidad(app, curiosidad: AdaptiveCuriosity):
    """
    Registra endpoints compatibles con los del módulo original.
    Reemplaza register_routes_curiosidad de curiosidad_pasiva.py.
    """
    from flask import jsonify

    @app.route("/api/curiosidad/estado")
    def api_curiosidad_estado():
        return jsonify(curiosidad.estado())

    @app.route("/api/curiosidad/forzar", methods=["POST"])
    def api_curiosidad_forzar():
        resultado = curiosidad.forzar_ciclo()
        return jsonify(resultado)

    @app.route("/api/curiosidad/historial")
    def api_curiosidad_historial():
        with curiosidad._lock:
            return jsonify(list(curiosidad._log[-20:]))

    print(
        "[OK] AdaptiveCuriosity endpoints: "
        "/api/curiosidad/estado, /api/curiosidad/forzar, /api/curiosidad/historial"
    )
