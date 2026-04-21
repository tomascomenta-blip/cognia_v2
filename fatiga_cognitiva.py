"""
fatiga_cognitiva.py — Monitor de Fatiga Cognitiva para COGNIA v3
=================================================================
Implementa la variable COGNITIVE_FATIGUE definida en el documento
de arquitectura del sistema. Esta era la brecha más grande entre
el diseño y el código.

CONCEPTO:
  Cada ciclo de razonamiento tiene un costo computacional real.
  Este módulo mide ese costo en tiempo real y calcula un score
  de fatiga 0-100, donde:
    0-30  → sistema descansado, rendimiento óptimo
    31-60 → carga moderada, estrategias de eficiencia activas
    61-80 → carga alta, simplificación agresiva de razonamiento
    81-100 → fatiga crítica, reducción de operaciones al mínimo

MÉTRICAS MEDIDAS:
  • tiempo por ciclo de razonamiento (ms)
  • uso de CPU (psutil, 0-100%)
  • uso de memoria RSS (MB)
  • número de operaciones en la ventana actual
  • tasa de cache hits de embeddings
  • operaciones costosas (embeddings nuevos calculados)

ESTRATEGIAS DE REDUCCIÓN DE FATIGA:
  Cuando fatiga > 60, el módulo recomienda a Cognia:
    - aumentar attention_threshold (descartar más memorias)
    - reducir top_k de retrieval (buscar menos memorias)
    - aumentar uso del cache de embeddings
    - posponer consolidaciones y bridges del KG
  
  Cuando fatiga > 80 (crítica):
    - reducir inference max_steps a 1
    - desactivar temporal predictions
    - usar solo cache para embeddings (sin calcular nuevos)
    - proponer optimización arquitectural al SelfArchitect

INSPIRACIÓN BIOLÓGICA:
  Similar a la fatiga neuronal real:
    - pensar más consume más energía
    - la fatiga se acumula gradualmente
    - el descanso (bajo uso) reduce la fatiga
    - las tareas complejas fatigan más rápido

CONSUMO PROPIO: < 2ms por ciclo (solo aritmética + psutil)
"""

import time
import os
import math
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List

# psutil es opcional — si no está, estimamos desde /proc o valores fijos
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️  psutil no encontrado. Instala con: pip install psutil")
    print("   La fatiga cognitiva usará estimaciones alternativas.")


# ══════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════

# Tiempo de referencia "normal" por ciclo de razonamiento (ms)
# Calibrado para un laptop de gama media con embeddings cacheados
NORMAL_CYCLE_MS   = 80.0   # < 80ms = bajo costo
HIGH_CYCLE_MS     = 300.0  # > 300ms = ciclo costoso
CRITICAL_CYCLE_MS = 800.0  # > 800ms = ciclo muy costoso (embedding nuevo pesado)

# CPU reference (%)
NORMAL_CPU   = 20.0
HIGH_CPU     = 60.0
CRITICAL_CPU = 85.0

# Memoria RSS reference (MB)
NORMAL_MEM_MB   = 400.0
HIGH_MEM_MB     = 700.0
CRITICAL_MEM_MB = 1000.0

# Ventana deslizante de ciclos para promediar
WINDOW_SIZE = 20

# Pesos de las métricas en el score de fatiga
W_TIME   = 0.40   # tiempo por ciclo — métrica más directa
W_CPU    = 0.30   # CPU actual
W_MEM    = 0.15   # uso de memoria
W_OPS    = 0.15   # operaciones en ventana (presión de trabajo)

# Umbrales de fatiga para activar estrategias
THRESHOLD_MODERATE = 30
THRESHOLD_HIGH      = 60
THRESHOLD_CRITICAL  = 80


# ══════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class CognitiveFatigueMonitor:
    """
    Monitor en tiempo real de la fatiga computacional de Cognia.
    
    Uso típico:
        monitor = CognitiveFatigueMonitor()
        
        # Antes de un ciclo costoso:
        monitor.start_cycle()
        ... lógica de razonamiento ...
        fatigue = monitor.end_cycle(ops_count=5, cache_hits=3, cache_misses=1)
        
        # Consultar estado actual:
        state = monitor.get_state()
        adaptations = monitor.get_adaptations()
    """
    
    def __init__(self):
        # Historial deslizante de tiempos de ciclo (ms)
        self._cycle_times: deque = deque(maxlen=WINDOW_SIZE)
        # Historial de CPU snapshots
        self._cpu_samples: deque = deque(maxlen=WINDOW_SIZE)
        # Historial de memoria (MB)
        self._mem_samples: deque = deque(maxlen=WINDOW_SIZE)
        # Conteo de operaciones costosas (embeddings nuevos)
        self._expensive_ops: deque = deque(maxlen=WINDOW_SIZE)
        # Cache hit rate
        self._cache_hits:   deque = deque(maxlen=WINDOW_SIZE)
        self._cache_misses: deque = deque(maxlen=WINDOW_SIZE)
        
        # Score actual 0-100
        self._fatigue_score: float = 0.0
        self._prev_fatigue:  float = 0.0
        
        # Timestamp de inicio del ciclo actual
        self._cycle_start: Optional[float] = None
        
        # Contador total de ciclos
        self._total_cycles: int = 0
        
        # Proceso actual (para psutil)
        self._process = psutil.Process(os.getpid()) if HAS_PSUTIL else None
        # Primera llamada a cpu_percent devuelve 0.0 siempre — llamar aqui para calibrar
        if self._process:
            try:
                self._process.cpu_percent(interval=None)
            except Exception:
                pass

        # Historial de scores para trend analysis
        self._score_history: deque = deque(maxlen=50)
        
        # Tiempo de inicio del sistema
        self._start_time = time.time()
        
        # Estado de las estrategias activas actualmente
        self._active_strategies: List[str] = []
        
        # Acumuladores de energía por sesión
        self._total_expensive_ops  = 0
        self._total_cheap_ops      = 0
        
        # Última vez que se propuso optimización arquitectural
        self._last_arch_proposal: Optional[float] = None
        
        print("✅ CognitiveFatigueMonitor activo — midiendo fatiga en tiempo real")

    # ── API principal ──────────────────────────────────────────────────

    def start_cycle(self):
        """Marcar el inicio de un ciclo de razonamiento."""
        self._cycle_start = time.perf_counter()

    def end_cycle(self,
                  ops_count:    int = 1,
                  cache_hits:   int = 0,
                  cache_misses: int = 0,
                  expensive:    int = 0) -> float:
        """
        Marcar el fin de un ciclo y actualizar el score de fatiga.
        
        Args:
            ops_count:    número de operaciones lógicas en este ciclo
            cache_hits:   embeddings servidos desde cache
            cache_misses: embeddings calculados nuevos (costosos)
            expensive:    operaciones extra costosas (ej: LLM call)
        
        Returns:
            float: score de fatiga actual (0-100)
        """
        now = time.perf_counter()
        
        # Tiempo del ciclo
        if self._cycle_start is not None:
            cycle_ms = (now - self._cycle_start) * 1000.0
        else:
            cycle_ms = NORMAL_CYCLE_MS  # estimación si no se llamó start_cycle
        
        self._cycle_times.append(cycle_ms)
        self._cache_hits.append(cache_hits)
        self._cache_misses.append(cache_misses)
        self._expensive_ops.append(expensive + cache_misses)  # misses = ops costosas
        self._total_cycles += 1
        self._total_expensive_ops += expensive + cache_misses
        self._total_cheap_ops += cache_hits + ops_count
        
        # Snapshot de CPU y memoria
        cpu, mem_mb = self._sample_resources()
        self._cpu_samples.append(cpu)
        self._mem_samples.append(mem_mb)
        
        # Recalcular score
        self._prev_fatigue = self._fatigue_score
        self._fatigue_score = self._compute_fatigue()
        self._score_history.append({
            "ts": datetime.now().isoformat(),
            "score": round(self._fatigue_score, 1),
            "cycle_ms": round(cycle_ms, 1),
            "cpu": round(cpu, 1),
            "mem_mb": round(mem_mb, 1),
        })
        
        # Actualizar estrategias activas
        self._update_strategies()
        
        self._cycle_start = None
        return self._fatigue_score

    def record_embedding_computed(self):
        """Registrar que se calculó un embedding nuevo (operación costosa)."""
        # Se llama desde text_to_vector cuando hay cache miss
        # No inicia un ciclo nuevo, solo incrementa el contador de ops costosas
        if self._expensive_ops:
            self._expensive_ops[-1] = self._expensive_ops[-1] + 1
        self._total_expensive_ops += 1

    def record_embedding_cached(self):
        """Registrar que se usó un embedding cacheado (operación barata)."""
        if self._cache_hits:
            self._cache_hits[-1] = self._cache_hits[-1] + 1
        self._total_cheap_ops += 1

    # ── Consultas de estado ────────────────────────────────────────────

    @property
    def score(self) -> float:
        """Score de fatiga actual (0-100)."""
        return round(self._fatigue_score, 1)

    @property
    def level(self) -> str:
        """Nivel de fatiga en texto."""
        s = self._fatigue_score
        if s >= THRESHOLD_CRITICAL:  return "critica"   # sin tilde → CSS fatigue-critica
        if s >= THRESHOLD_HIGH:      return "alta"
        if s >= THRESHOLD_MODERATE:  return "moderada"
        return "baja"

    @property
    def trend(self) -> str:
        """Tendencia: subiendo / bajando / estable."""
        if len(self._score_history) < 5:
            return "estable"
        recent = [h["score"] for h in list(self._score_history)[-5:]]
        delta = recent[-1] - recent[0]
        if delta > 5:  return "subiendo"
        if delta < -5: return "bajando"
        return "estable"

    def get_state(self) -> dict:
        """Estado completo del monitor para logging/UI."""
        cpu, mem_mb = self._sample_resources()
        
        avg_cycle = (sum(self._cycle_times) / len(self._cycle_times)
                     if self._cycle_times else 0.0)
        
        total_cache = sum(self._cache_hits) + sum(self._cache_misses)
        cache_rate  = (sum(self._cache_hits) / max(1, total_cache))
        
        uptime_min = (time.time() - self._start_time) / 60.0
        
        # Gasto energético estimado (W) — modelo lineal para edge AI (objetivo 5-20W)
        _w_base  = 2.0
        _w_cpu   = cpu * 0.15
        _w_mem   = mem_mb * 0.003
        _w_cycle = max(0.0, (avg_cycle - NORMAL_CYCLE_MS) / NORMAL_CYCLE_MS) * 1.5
        energy_watts = round(_w_base + _w_cpu + _w_mem + _w_cycle, 2)

        return {
            "fatigue_score":      round(self._fatigue_score, 1),
            "fatigue_level":      self.level,
            "fatigue_trend":      self.trend,
            "avg_cycle_ms":       round(avg_cycle, 1),
            "current_cpu_pct":    round(cpu, 1),
            "current_mem_mb":     round(mem_mb, 1),
            "cache_hit_rate":     round(cache_rate, 3),
            "total_cycles":       self._total_cycles,
            "total_expensive_ops":self._total_expensive_ops,
            "total_cheap_ops":    self._total_cheap_ops,
            "active_strategies":  self._active_strategies.copy(),
            "uptime_minutes":     round(uptime_min, 1),
            "score_history":      list(self._score_history)[-10:],
            "energy_watts":       energy_watts,
        }

    def get_adaptations(self) -> dict:
        """
        Retorna las adaptaciones que Cognia debe aplicar según el nivel de fatiga.
        Este dict se usa directamente en el ciclo observe() de Cognia.
        """
        s = self._fatigue_score
        
        if s < THRESHOLD_MODERATE:
            # Sistema descansado — operación normal
            return {
                "top_k_retrieval":      10,
                "attention_threshold":   0.25,
                "inference_max_steps":   3,
                "enable_temporal":       True,
                "enable_bridge":         True,
                "embedding_cache_only":  False,
                "consolidation_defer":   False,
                "mode":                  "normal",
            }
        
        elif s < THRESHOLD_HIGH:
            # Fatiga moderada — pequeñas optimizaciones
            return {
                "top_k_retrieval":      7,
                "attention_threshold":   0.30,
                "inference_max_steps":   2,
                "enable_temporal":       True,
                "enable_bridge":         True,
                "embedding_cache_only":  False,
                "consolidation_defer":   False,
                "mode":                  "moderada",
            }
        
        elif s < THRESHOLD_CRITICAL:
            # Fatiga alta — simplificación agresiva
            return {
                "top_k_retrieval":      5,
                "attention_threshold":   0.38,
                "inference_max_steps":   1,
                "enable_temporal":       False,    # posponer predicciones temporales
                "enable_bridge":         False,    # posponer bridge KG→episodic
                "embedding_cache_only":  False,
                "consolidation_defer":   True,     # posponer consolidación
                "mode":                  "alta",
            }
        
        else:
            # Fatiga crítica — modo mínimo
            return {
                "top_k_retrieval":      3,
                "attention_threshold":   0.50,
                "inference_max_steps":   0,        # sin inferencia simbólica
                "enable_temporal":       False,
                "enable_bridge":         False,
                "embedding_cache_only":  True,     # solo cache, sin calcular nuevos
                "consolidation_defer":   True,
                "mode":                  "critica",
            }

    def should_propose_optimization(self) -> bool:
        """
        True si la fatiga ha sido crítica por suficiente tiempo
        para justificar una propuesta arquitectural al SelfArchitect.
        """
        if self._fatigue_score < THRESHOLD_CRITICAL:
            return False
        # No proponer más de una vez por hora
        if self._last_arch_proposal:
            elapsed = time.time() - self._last_arch_proposal
            if elapsed < 3600:
                return False
        # Solo si la tendencia es "subiendo" o lleva muchos ciclos críticos
        if self.trend == "subiendo" and self._total_cycles > 20:
            self._last_arch_proposal = time.time()
            return True
        return False

    def format_status(self) -> str:
        """Texto legible para la UI de chat."""
        s = self._fatigue_score
        icons = {
            "baja":     "🟢",
            "moderada": "🟡",
            "alta":     "🟠",
            "critica":  "🔴",
        }
        icon = icons.get(self.level, "⚪")
        state = self.get_state()
        
        lines = [
            f"⚡ FATIGA COGNITIVA: {icon} {s:.1f}/100 ({self.level}) [{self.trend}]",
            f"   CPU actual:        {state['current_cpu_pct']:.1f}%",
            f"   Memoria RSS:       {state['current_mem_mb']:.0f} MB",
            f"   Tiempo/ciclo avg:  {state['avg_cycle_ms']:.0f} ms",
            f"   Cache hit rate:    {state['cache_hit_rate']:.0%}",
            f"   Ciclos totales:    {state['total_cycles']}",
            f"   Ops costosas:      {state['total_expensive_ops']} "
            f"(bajas: {state['total_cheap_ops']})",
        ]
        if self._active_strategies:
            lines.append(f"   Estrategias activas: {', '.join(self._active_strategies)}")
        return "\n".join(lines)

    # ── Internos ───────────────────────────────────────────────────────

    def _sample_resources(self) -> tuple:
        """Retorna (cpu_pct, mem_mb) del proceso actual."""
        if HAS_PSUTIL and self._process:
            try:
                cpu = float(self._process.cpu_percent(interval=None))
                mem = float(self._process.memory_info().rss) / (1024.0 * 1024.0)
                if not (0.0 <= cpu <= 100.0):
                    cpu = 30.0
                if not (10.0 <= mem <= 8192.0):
                    mem = 300.0
                return cpu, mem
            except Exception:
                pass
        # Fallback: estimar desde /proc/self/status (Linux)
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        mem_kb = int(line.split()[1])
                        return 30.0, mem_kb / 1024.0
        except Exception:
            pass
        return 30.0, 300.0  # valores por defecto razonables

    def _compute_fatigue(self) -> float:
        """
        Calcula el score de fatiga 0-100 a partir de las métricas acumuladas.
        Usa una media ponderada de los 4 componentes.
        """
        # 1. Componente de tiempo (basado en los últimos ciclos)
        if self._cycle_times:
            avg_ms = sum(self._cycle_times) / len(self._cycle_times)
        else:
            avg_ms = NORMAL_CYCLE_MS
        
        time_component = self._normalize(avg_ms, NORMAL_CYCLE_MS, HIGH_CYCLE_MS, CRITICAL_CYCLE_MS)
        
        # 2. Componente de CPU
        if self._cpu_samples:
            avg_cpu = sum(self._cpu_samples) / len(self._cpu_samples)
        else:
            avg_cpu = NORMAL_CPU
        
        cpu_component = self._normalize(avg_cpu, NORMAL_CPU, HIGH_CPU, CRITICAL_CPU)
        
        # 3. Componente de memoria
        if self._mem_samples:
            avg_mem = sum(self._mem_samples) / len(self._mem_samples)
        else:
            avg_mem = NORMAL_MEM_MB
        
        mem_component = self._normalize(avg_mem, NORMAL_MEM_MB, HIGH_MEM_MB, CRITICAL_MEM_MB)
        
        # 4. Componente de operaciones costosas en ventana
        if self._expensive_ops:
            total_ops_window = sum(self._expensive_ops)
            # Normalizar: 0 ops = 0, 20+ ops en ventana = 100
            ops_component = min(1.0, total_ops_window / 20.0)
        else:
            ops_component = 0.0
        
        # Score ponderado
        raw = (W_TIME * time_component +
               W_CPU  * cpu_component  +
               W_MEM  * mem_component  +
               W_OPS  * ops_component)
        
        score = raw * 100.0
        
        # Suavizado exponencial: el score no sube/baja bruscamente
        # alpha = 0.3 → cambios graduales (biológicamente realista)
        alpha = 0.3
        smoothed = alpha * score + (1 - alpha) * self._prev_fatigue
        
        return max(0.0, min(100.0, smoothed))

    @staticmethod
    def _normalize(value: float, low: float, mid: float, high: float) -> float:
        """
        Normaliza un valor en el rango [0, 1].
        - value <= low  → 0.0 (sin fatiga)
        - value == mid  → 0.5 (fatiga media)
        - value >= high → 1.0 (fatiga máxima)
        """
        if value <= low:
            return 0.0
        if value >= high:
            return 1.0
        if value <= mid:
            # Interpolación lineal entre low y mid → [0, 0.5]
            return 0.5 * (value - low) / (mid - low)
        else:
            # Interpolación lineal entre mid y high → [0.5, 1.0]
            return 0.5 + 0.5 * (value - mid) / (high - mid)

    def _update_strategies(self):
        """Actualizar lista de estrategias activas según nivel de fatiga."""
        s = self._fatigue_score
        strategies = []
        
        if s >= THRESHOLD_MODERATE:
            strategies.append("top_k_reducido")
            strategies.append("umbral_atención_alto")
        
        if s >= THRESHOLD_HIGH:
            strategies.append("inferencia_simplificada")
            strategies.append("temporal_pospuesto")
            strategies.append("bridge_pospuesto")
            strategies.append("consolidación_diferida")
        
        if s >= THRESHOLD_CRITICAL:
            strategies.append("solo_cache_embeddings")
            strategies.append("modo_mínimo")
        
        self._active_strategies = strategies


# ══════════════════════════════════════════════════════════════════════
# SINGLETON — una instancia compartida por todo el sistema
# ══════════════════════════════════════════════════════════════════════

_global_monitor: Optional[CognitiveFatigueMonitor] = None

def get_fatigue_monitor() -> CognitiveFatigueMonitor:
    """Retorna el monitor global (singleton). Crea uno si no existe."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = CognitiveFatigueMonitor()
    return _global_monitor


# ══════════════════════════════════════════════════════════════════════
# DECORADOR DE CONVENIENCIA
# ══════════════════════════════════════════════════════════════════════

def track_cognitive_cost(func):
    """
    Decorador que mide el costo cognitivo de una función.
    Úsalo en métodos costosos de Cognia para alimentar el monitor.
    
    Ejemplo:
        @track_cognitive_cost
        def observe(self, observation):
            ...
    """
    def wrapper(*args, **kwargs):
        monitor = get_fatigue_monitor()
        monitor.start_cycle()
        try:
            result = func(*args, **kwargs)
            monitor.end_cycle(ops_count=1)
            return result
        except Exception:
            monitor.end_cycle(ops_count=1)
            raise
    wrapper.__name__ = func.__name__
    return wrapper


# ══════════════════════════════════════════════════════════════════════
# PRUEBA STANDALONE
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import random
    
    print("\n🧪 Test del CognitiveFatigueMonitor\n")
    m = CognitiveFatigueMonitor()
    
    print("Simulando 30 ciclos de razonamiento...\n")
    for i in range(30):
        m.start_cycle()
        # Simular trabajo de diferente intensidad
        cost = random.choice([
            0.02,  # ciclo barato (cache hit)
            0.08,  # ciclo normal
            0.30,  # ciclo costoso (embedding nuevo)
            0.80,  # ciclo muy costoso (embedding pesado)
        ])
        time.sleep(cost * 0.1)  # 10% del tiempo real para el test
        
        cache_hits   = random.randint(0, 5)
        cache_misses = random.randint(0, 2)
        expensive    = 1 if cost > 0.5 else 0
        
        fatigue = m.end_cycle(
            ops_count=random.randint(1, 8),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            expensive=expensive,
        )
        
        level_icons = {"baja": "🟢", "moderada": "🟡", "alta": "🟠", "crítica": "🔴"}
        icon = level_icons.get(m.level, "⚪")
        print(f"  Ciclo {i+1:02d}: {icon} fatiga={fatigue:5.1f} | "
              f"cycle_ms={cost*1000:.0f}ms | "
              f"cache={cache_hits}h/{cache_misses}m | "
              f"nivel={m.level}")
    
    print()
    print(m.format_status())
    print()
    
    adaptaciones = m.get_adaptations()
    print(f"Adaptaciones recomendadas: {adaptaciones}")
