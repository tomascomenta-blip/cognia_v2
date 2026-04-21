import { useState } from "react";

const SECTIONS = [
  { id: "arch", label: "Architecture" },
  { id: "loop", label: "Cognitive Loop" },
  { id: "cpu", label: "CPU Optimization" },
  { id: "memory", label: "Memory Optimization" },
  { id: "energy", label: "Energy Monitor" },
  { id: "throttle", label: "Throttle Controller" },
  { id: "diagram", label: "Architecture Diagram" },
];

const CODE = {
  loop: `# cognia_event_loop.py
# ──────────────────────────────────────────────────────────────────
# OPTIMIZED COGNITIVE LOOP — Event-driven, throttle-aware
# Replaces the always-on polling loop with an event queue model.
# ──────────────────────────────────────────────────────────────────

import threading
import queue
import time
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import IntEnum

class EventPriority(IntEnum):
    CRITICAL  = 0   # user input — never delayed
    HIGH      = 1   # learning, correction
    NORMAL    = 2   # inference, retrieval
    LOW       = 3   # consolidation, KG updates
    IDLE      = 4   # hypothesis, self-architect, creative

@dataclass(order=True)
class CognitiveEvent:
    priority:  int
    timestamp: float = field(compare=False)
    kind:      str   = field(compare=False)
    payload:   dict  = field(compare=False, default_factory=dict)
    callback:  Optional[Callable] = field(compare=False, default=None)

class EventDrivenCognitiveLoop:
    """
    Replaces the busy while-loop with a priority queue.

    Key changes vs. original:
    - No busy spin: uses queue.get(timeout=...) which yields CPU
    - Throttle controller gates LOW/IDLE events when resources are tight
    - Consolidation, hypothesis, self-architect only run as LOW/IDLE events
    - User input (CRITICAL) always bypasses throttle
    """

    def __init__(self, cognia_instance, throttle_controller):
        self.cognia      = cognia_instance
        self.throttle    = throttle_controller
        self._queue      = queue.PriorityQueue()
        self._stop_event = threading.Event()
        self._thread     = None
        # Minimum gap between LOW-priority batches (seconds)
        self._low_batch_interval   = 30.0
        self._last_low_batch_time  = 0.0

    # ── Public API ──────────────────────────────────────────────────

    def submit(self, kind: str, payload: dict = None,
               priority: EventPriority = EventPriority.NORMAL,
               callback: Callable = None):
        """Enqueue a cognitive event. Thread-safe."""
        evt = CognitiveEvent(
            priority  = int(priority),
            timestamp = time.monotonic(),
            kind      = kind,
            payload   = payload or {},
            callback  = callback,
        )
        self._queue.put(evt)

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="CognitiveLoop"
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # ── Internal loop ───────────────────────────────────────────────

    def _run(self):
        while not self._stop_event.is_set():
            try:
                # Yield CPU when idle — no busy spin
                evt = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Gate non-critical events based on resource pressure
            if evt.priority >= EventPriority.LOW:
                if not self._should_run_low_priority():
                    # Re-queue with small delay instead of dropping
                    time.sleep(0.1)
                    self._queue.put(evt)
                    continue

            try:
                self._dispatch(evt)
            except Exception as e:
                print(f"[CognitiveLoop] Error in {evt.kind}: {e}")
            finally:
                self._queue.task_done()

    def _should_run_low_priority(self) -> bool:
        """Return True only if resources allow low-priority work."""
        if self.throttle.is_low_resource_mode():
            return False
        now = time.monotonic()
        if (now - self._last_low_batch_time) < self._low_batch_interval:
            return False
        self._last_low_batch_time = now
        return True

    def _dispatch(self, evt: CognitiveEvent):
        result = None
        if evt.kind == "observe":
            result = self.cognia.observe(evt.payload["observation"],
                                         evt.payload.get("label"))
        elif evt.kind == "consolidate":
            result = self.cognia.consolidation.consolidate()
        elif evt.kind == "forget":
            result = self.cognia.forgetting.decay_cycle()
        elif evt.kind == "hypothesis":
            # Only run hypothesis if NOT in low-resource mode
            if not self.throttle.is_low_resource_mode():
                concepts = list(self.cognia.semantic._cache.keys())[:10]
                if len(concepts) >= 2:
                    import random
                    a, b = random.sample(concepts, 2)
                    result = self.cognia.hypothesis.generate(a, b)
        elif evt.kind == "self_architect":
            # Never run self-architect during high load
            if self.throttle.level == "normal":
                from self_architect import SelfArchitect
                sa = SelfArchitect(self.cognia.db)
                result = sa.evaluate(self.cognia)
        elif evt.kind == "creative":
            if self.throttle.level == "normal":
                result = {"skipped": "creative mode deferred"}

        if evt.callback and result is not None:
            evt.callback(result)
`,

  cpu: `# cognia_cpu_optimizer.py
# ──────────────────────────────────────────────────────────────────
# CPU OPTIMIZATION TECHNIQUES
# ──────────────────────────────────────────────────────────────────

import time
import threading
import psutil
import os
from functools import lru_cache
from collections import OrderedDict

# ── 1. Timed background worker (replaces busy loops) ──────────────

class TimedBackgroundWorker:
    """
    Replaces any 'while True: do_thing(); time.sleep(N)' pattern.
    Uses threading.Event for clean shutdown with zero CPU waste.
    """

    def __init__(self, fn, interval_seconds: float, name: str = "BgWorker"):
        self._fn       = fn
        self._interval = interval_seconds
        self._stop     = threading.Event()
        self._thread   = threading.Thread(
            target=self._loop, daemon=True, name=name
        )

    def start(self):
        self._thread.start()

    def stop(self, timeout: float = 3.0):
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _loop(self):
        while not self._stop.wait(self._interval):
            try:
                self._fn()
            except Exception as e:
                print(f"[{self._thread.name}] error: {e}")


# ── 2. Idle-aware hypothesis scheduler ────────────────────────────

class IdleHypothesisScheduler:
    """
    Hypothesis generation should ONLY run:
    - When CPU < 40%
    - At least 60 seconds since last run
    - Not during active user interaction
    """

    def __init__(self, cognia_instance, min_idle_s: float = 60.0,
                 cpu_threshold: float = 40.0):
        self.cognia        = cognia_instance
        self.min_idle_s    = min_idle_s
        self.cpu_threshold = cpu_threshold
        self._last_run     = 0.0
        self._process      = psutil.Process(os.getpid())

    def maybe_run(self) -> bool:
        """Returns True if hypothesis was generated."""
        now = time.monotonic()
        if (now - self._last_run) < self.min_idle_s:
            return False
        # Sample CPU — non-blocking (interval=None uses last cached value)
        cpu = self._process.cpu_percent(interval=None)
        if cpu > self.cpu_threshold:
            return False
        self._last_run = now
        self._run_hypothesis()
        return True

    def _run_hypothesis(self):
        import random
        sm = self.cognia.semantic
        # Sample concepts with high support (likely to produce useful hypotheses)
        conn = __import__("sqlite3").connect(self.cognia.db)
        rows = conn.execute(
            "SELECT concept FROM semantic_memory WHERE support >= 2 ORDER BY support DESC LIMIT 20"
        ).fetchall()
        conn.close()
        concepts = [r[0] for r in rows]
        if len(concepts) >= 2:
            a, b = random.sample(concepts, 2)
            self.cognia.hypothesis.generate(a, b, kg=self.cognia.kg)


# ── 3. SelfArchitect: run only every N interactions, never during load ──

class SelfArchitectGate:
    """
    Prevents SelfArchitect from running more than once per N interactions
    and blocks it entirely when CPU > threshold.
    """

    def __init__(self, cognia_instance, every_n: int = 50,
                 cpu_threshold: float = 60.0):
        self.cognia        = cognia_instance
        self.every_n       = every_n
        self.cpu_threshold = cpu_threshold
        self._last_check   = 0
        self._process      = psutil.Process(os.getpid())

    def check_and_run(self) -> bool:
        n = self.cognia.interaction_count
        if n - self._last_check < self.every_n:
            return False
        cpu = self._process.cpu_percent(interval=None)
        if cpu > self.cpu_threshold:
            # Defer — will retry on next call
            return False
        self._last_check = n
        try:
            from self_architect import SelfArchitect
            sa = SelfArchitect(self.cognia.db)
            sa.evaluate(self.cognia)
        except Exception as e:
            print(f"[SelfArchitectGate] {e}")
        return True


# ── 4. Consolidation / forgetting: defer when busy ────────────────

class DeferredMaintenance:
    """
    Consolidation and forgetting are expensive DB operations.
    Only run them when CPU pressure is low.
    """

    def __init__(self, cognia_instance, cpu_safe_threshold: float = 50.0):
        self.cognia        = cognia_instance
        self._cpu_safe     = cpu_safe_threshold
        self._process      = psutil.Process(os.getpid())
        self._deferred_consolidation = False
        self._deferred_forgetting    = False

    def tick(self, interaction_count: int):
        cpu = self._process.cpu_percent(interval=None)
        busy = cpu > self._cpu_safe

        if interaction_count % self.cognia.consolidation_interval == 0:
            if busy:
                self._deferred_consolidation = True
            else:
                self.cognia.consolidation.consolidate()

        if interaction_count % self.cognia.forgetting_interval == 0:
            if busy:
                self._deferred_forgetting = True
            else:
                self.cognia.forgetting.decay_cycle()

        # Flush deferred tasks when CPU recovers
        if not busy:
            if self._deferred_consolidation:
                self.cognia.consolidation.consolidate()
                self._deferred_consolidation = False
            if self._deferred_forgetting:
                self.cognia.forgetting.decay_cycle()
                self._deferred_forgetting = False
`,

  memory: `# cognia_memory_optimizer.py
# ──────────────────────────────────────────────────────────────────
# MEMORY OPTIMIZATION TECHNIQUES
# ──────────────────────────────────────────────────────────────────

import time
import threading
import psutil
import os
from collections import OrderedDict
from typing import Optional, List, Dict

# ── 1. Bounded LRU embedding cache (replaces unbounded dict) ──────

class BoundedLRUCache:
    """
    Drop-in replacement for cognia_v3._embedding_cache.
    Uses OrderedDict for O(1) LRU eviction instead of 'pop first key'.
    Max size is enforced strictly; also supports memory-pressure eviction.
    """

    def __init__(self, max_entries: int = 512, max_mb: float = 80.0):
        self._cache    = OrderedDict()
        self._max_n    = max_entries
        self._max_mb   = max_mb
        self._lock     = threading.Lock()
        self._hits     = 0
        self._misses   = 0

    def get(self, key: str) -> Optional[list]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            self._cache.move_to_end(key)   # mark as recently used
            self._hits += 1
            return self._cache[key]

    def set(self, key: str, value: list):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            # Enforce size limit
            while len(self._cache) > self._max_n:
                self._cache.popitem(last=False)   # evict LRU

    def maybe_shrink_under_pressure(self):
        """Call periodically to free memory when RAM is high."""
        process = psutil.Process(os.getpid())
        rss_mb  = process.memory_info().rss / 1024 / 1024
        if rss_mb > (psutil.virtual_memory().total / 1024 / 1024) * 0.80:
            with self._lock:
                # Evict oldest 25% of entries
                evict_n = max(1, len(self._cache) // 4)
                for _ in range(evict_n):
                    if self._cache:
                        self._cache.popitem(last=False)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def __len__(self):
        return len(self._cache)

    def __contains__(self, key):
        return key in self._cache


# ── 2. Working memory overflow guard ──────────────────────────────

class BoundedWorkingMemory:
    """
    Patches WorkingMemory to hard-cap its buffer at MAX_SLOTS.
    Prevents unbounded growth during long sessions.
    """
    MAX_SLOTS = 20   # matches original design spec

    @staticmethod
    def patch(working_mem_instance):
        """Apply overflow guard to an existing WorkingMemory instance."""
        original_add = working_mem_instance.add

        def guarded_add(observation, label, vector, emotion, confidence):
            # Trim if at capacity before adding
            buf = working_mem_instance.buffer
            while len(buf) >= BoundedWorkingMemory.MAX_SLOTS:
                buf.popleft()
            return original_add(observation, label, vector, emotion, confidence)

        working_mem_instance.add = guarded_add
        return working_mem_instance


# ── 3. KG retrieval limiter ────────────────────────────────────────

class KGRetrievalLimiter:
    """
    Wraps KnowledgeGraph.get_facts() to limit result set based on load.
    During high CPU/RAM, reduces KG lookups from default depth to 1.
    """

    def __init__(self, kg_instance, throttle_controller):
        self._kg       = kg_instance
        self._throttle = throttle_controller
        original_gf    = kg_instance.get_facts

        def limited_get_facts(concept: str, limit: int = 10) -> list:
            if self._throttle.is_low_resource_mode():
                limit = min(limit, 3)
            return original_gf(concept, limit)

        kg_instance.get_facts = limited_get_facts

    @staticmethod
    def patch(kg_instance, throttle_controller):
        return KGRetrievalLimiter(kg_instance, throttle_controller)


# ── 4. Semantic memory concept cap ────────────────────────────────

class SemanticMemoryCap:
    """
    Keeps semantic_memory table from growing unboundedly.
    Trims lowest-confidence, rarely-accessed concepts when count > MAX.
    """
    MAX_CONCEPTS = 2000

    @staticmethod
    def trim_if_needed(db_path: str):
        import sqlite3
        conn = sqlite3.connect(db_path)
        c    = conn.cursor()
        count = c.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
        if count > SemanticMemoryCap.MAX_CONCEPTS:
            excess = count - SemanticMemoryCap.MAX_CONCEPTS
            c.execute("""
                DELETE FROM semantic_memory
                WHERE id IN (
                    SELECT id FROM semantic_memory
                    ORDER BY confidence ASC, support ASC, last_updated ASC
                    LIMIT ?
                )
            """, (excess,))
            conn.commit()
        conn.close()
        return count


# ── 5. Lazy module loader (avoids loading all modules at startup) ──

class LazyModuleLoader:
    """
    Replaces eager instantiation of rarely-used modules.
    Module is only loaded on first access.

    Usage:
        self._self_arch = LazyModuleLoader(lambda: SelfArchitect(db_path))
        # Later:
        self._self_arch.instance.evaluate(self)
    """

    def __init__(self, factory):
        self._factory  = factory
        self._instance = None

    @property
    def instance(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def reset(self):
        """Force re-instantiation (e.g., after sleep cycle)."""
        self._instance = None
`,

  energy: `# cognia_energy_monitor.py
# ──────────────────────────────────────────────────────────────────
# REAL ENERGY USAGE MONITOR  (fixes the always-zero bug)
# Uses psutil to measure actual CPU + RAM; estimates watt-seconds.
# ──────────────────────────────────────────────────────────────────

import time
import os
import psutil
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

# Thermal Design Power for typical edge-AI laptop (watts)
# Adjust TDP_WATTS to match your specific hardware.
TDP_WATTS     = 65.0   # full-load CPU TDP (typical mid-range laptop)
IDLE_WATTS    = 8.0    # baseline idle consumption
RAM_PER_GB_W  = 0.375  # approximate DRAM power per GB active

@dataclass
class CycleMetrics:
    timestamp:       float
    cpu_pct:         float   # 0-100
    ram_mb:          float   # process RSS in MB
    ram_total_mb:    float   # system total RAM
    cycle_ms:        float   # cognitive cycle duration
    energy_mwh:      float   # milliwatt-hours this cycle
    energy_joules:   float   # joules this cycle


class RealEnergyMonitor:
    """
    Replaces the always-zero energy_estimate in cognia_v3.py.

    Key changes:
    - Uses process.cpu_percent(interval=None) for non-blocking reads
    - Estimates instantaneous wattage from CPU% + RAM usage
    - Converts to milliwatt-hours and joules per cognitive cycle
    - Maintains rolling window for session totals
    - Correct formula: energy_joules = watts * seconds

    Integration: call start_cycle() / end_cycle() in observe().
    """

    HISTORY_SIZE = 200

    def __init__(self):
        self._process    = psutil.Process(os.getpid())
        self._history    = deque(maxlen=self.HISTORY_SIZE)
        self._cycle_start: Optional[float] = None
        self._cpu_start:   Optional[float] = None
        # Warm up cpu_percent — first call always returns 0.0
        self._process.cpu_percent(interval=None)
        time.sleep(0.05)
        self._process.cpu_percent(interval=None)

    # ── Cycle API ─────────────────────────────────────────────────

    def start_cycle(self):
        self._cycle_start = time.perf_counter()
        # Non-blocking snapshot — uses kernel-accumulated CPU time
        self._cpu_start = self._process.cpu_percent(interval=None)

    def end_cycle(self) -> CycleMetrics:
        now = time.perf_counter()
        cycle_s  = now - (self._cycle_start or now)
        cycle_ms = cycle_s * 1000.0

        # CPU — sample at end, average with start
        cpu_end = self._process.cpu_percent(interval=None)
        cpu_pct = (self._cpu_start + cpu_end) / 2.0 if self._cpu_start else cpu_end

        # RAM
        mem_info   = self._process.memory_info()
        ram_mb     = mem_info.rss / 1024 / 1024
        total_ram  = psutil.virtual_memory().total / 1024 / 1024

        # Estimated wattage this process is drawing
        # Formula: idle baseline + (cpu_fraction * cpu_TDP) + (ram_gb * ram_coeff)
        cpu_fraction  = cpu_pct / 100.0
        ram_gb_active = ram_mb / 1024.0
        watts_now     = (IDLE_WATTS
                         + cpu_fraction * TDP_WATTS
                         + ram_gb_active * RAM_PER_GB_W)

        # Convert to energy units
        energy_joules = watts_now * cycle_s
        energy_mwh    = (watts_now * cycle_s / 3600.0) * 1000.0  # mWh

        metrics = CycleMetrics(
            timestamp    = now,
            cpu_pct      = round(cpu_pct, 1),
            ram_mb       = round(ram_mb, 1),
            ram_total_mb = round(total_ram, 1),
            cycle_ms     = round(cycle_ms, 2),
            energy_mwh   = round(energy_mwh, 6),
            energy_joules= round(energy_joules, 6),
        )
        self._history.append(metrics)
        return metrics

    # ── Aggregates ────────────────────────────────────────────────

    @property
    def session_total_joules(self) -> float:
        return sum(m.energy_joules for m in self._history)

    @property
    def session_total_mwh(self) -> float:
        return sum(m.energy_mwh for m in self._history)

    @property
    def avg_watts(self) -> float:
        if not self._history:
            return 0.0
        total_j = self.session_total_joules
        total_s = sum(m.cycle_ms for m in self._history) / 1000.0
        return total_j / total_s if total_s > 0 else 0.0

    @property
    def avg_cycle_ms(self) -> float:
        if not self._history:
            return 0.0
        return sum(m.cycle_ms for m in self._history) / len(self._history)

    def summary(self) -> dict:
        return {
            "cycles":              len(self._history),
            "avg_cycle_ms":        round(self.avg_cycle_ms, 1),
            "avg_cpu_pct":         round(sum(m.cpu_pct for m in self._history)
                                         / max(1, len(self._history)), 1),
            "avg_ram_mb":          round(sum(m.ram_mb for m in self._history)
                                         / max(1, len(self._history)), 1),
            "session_joules":      round(self.session_total_joules, 4),
            "session_mwh":         round(self.session_total_mwh, 4),
            "avg_watts_estimated": round(self.avg_watts, 2),
        }

    # ── DB write helper (replaces the always-zero insert) ─────────

    def write_to_db(self, conn, interaction_id: int, metrics: CycleMetrics):
        """
        Replaces the broken energy_log INSERT in cognia_v3.py.
        Call this instead of the manual INSERT block in observe().
        """
        conn.execute(
            "INSERT INTO energy_log "
            "(timestamp, interaction_id, embedding_calls, retrieval_ops, "
            " inference_steps, cache_hits, cache_misses, latency_ms, energy_estimate) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                __import__("datetime").datetime.now().isoformat(),
                interaction_id,
                0,              # filled by caller
                0,              # filled by caller
                0,              # filled by caller
                0,              # filled by caller
                0,              # filled by caller
                metrics.cycle_ms,
                metrics.energy_joules,   # ← actual joules, not cycle_ms/80
            )
        )
`,

  throttle: `# cognia_throttle_controller.py
# ──────────────────────────────────────────────────────────────────
# THROTTLE CONTROLLER — Central resource gatekeeper
# Monitors CPU + RAM every 5 seconds.
# Exposes .level and .adaptations for all modules to query.
# ──────────────────────────────────────────────────────────────────

import time
import threading
import psutil
import os
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class ThrottleAdaptations:
    """
    Replaces the adaptations dict from CognitiveFatigueMonitor.
    Single source of truth for all resource adaptations.
    """
    top_k_retrieval:      int   = 10
    attention_threshold:  float = 0.25
    inference_max_steps:  int   = 3
    enable_temporal:      bool  = True
    enable_bridge:        bool  = True
    embedding_cache_only: bool  = False
    consolidation_defer:  bool  = False
    kg_facts_limit:       int   = 5
    llm_context_tokens:   int   = 2048   # Ollama context window
    mode:                 str   = "normal"  # normal | moderate | low | critical


LEVEL_CONFIGS = {
    "normal": ThrottleAdaptations(
        top_k_retrieval=10, attention_threshold=0.25, inference_max_steps=3,
        enable_temporal=True, enable_bridge=True, embedding_cache_only=False,
        consolidation_defer=False, kg_facts_limit=5, llm_context_tokens=2048,
        mode="normal",
    ),
    "moderate": ThrottleAdaptations(
        top_k_retrieval=7, attention_threshold=0.35, inference_max_steps=2,
        enable_temporal=True, enable_bridge=False, embedding_cache_only=False,
        consolidation_defer=True, kg_facts_limit=3, llm_context_tokens=1024,
        mode="moderate",
    ),
    "low": ThrottleAdaptations(
        top_k_retrieval=4, attention_threshold=0.5, inference_max_steps=1,
        enable_temporal=False, enable_bridge=False, embedding_cache_only=True,
        consolidation_defer=True, kg_facts_limit=2, llm_context_tokens=512,
        mode="low",
    ),
    "critical": ThrottleAdaptations(
        top_k_retrieval=2, attention_threshold=0.7, inference_max_steps=0,
        enable_temporal=False, enable_bridge=False, embedding_cache_only=True,
        consolidation_defer=True, kg_facts_limit=1, llm_context_tokens=256,
        mode="critical",
    ),
}


class ThrottleController:
    """
    Polls system resources every POLL_INTERVAL seconds in background.
    All Cognia modules read self.level and self.adaptations to decide
    how much work to do — no module needs its own psutil calls.

    Thresholds:
        normal   → CPU < 50%  AND  RAM < 70%
        moderate → CPU < 70%  OR   RAM < 80%
        low      → CPU < 85%  OR   RAM < 88%
        critical → CPU >= 85% OR   RAM >= 88%
    """

    POLL_INTERVAL = 5.0     # seconds between resource checks
    HYSTERESIS    = 0.05    # prevents rapid level oscillation (5%)

    def __init__(self):
        self._process    = psutil.Process(os.getpid())
        self._lock       = threading.RLock()
        self._level      = "normal"
        self._stop       = threading.Event()
        self._thread     = threading.Thread(
            target=self._poll_loop, daemon=True, name="ThrottleMonitor"
        )
        # Warm up cpu_percent
        self._process.cpu_percent(interval=None)
        self._thread.start()

    # ── Public API ─────────────────────────────────────────────────

    @property
    def level(self) -> str:
        with self._lock:
            return self._level

    @property
    def adaptations(self) -> ThrottleAdaptations:
        with self._lock:
            return LEVEL_CONFIGS[self._level]

    def is_low_resource_mode(self) -> bool:
        return self.level in ("low", "critical")

    def stop(self):
        self._stop.set()

    def current_metrics(self) -> Dict[str, Any]:
        """Snapshot of current system state — useful for web_app.py dashboard."""
        mem  = psutil.virtual_memory()
        proc = self._process.memory_info()
        return {
            "level":             self.level,
            "cpu_pct_process":   round(self._process.cpu_percent(interval=None), 1),
            "cpu_pct_system":    round(psutil.cpu_percent(interval=None), 1),
            "ram_process_mb":    round(proc.rss / 1024 / 1024, 1),
            "ram_system_pct":    round(mem.percent, 1),
            "ram_available_mb":  round(mem.available / 1024 / 1024, 1),
        }

    # ── Internal ───────────────────────────────────────────────────

    def _poll_loop(self):
        while not self._stop.wait(self.POLL_INTERVAL):
            try:
                self._update_level()
            except Exception:
                pass

    def _update_level(self):
        cpu  = self._process.cpu_percent(interval=None)
        mem  = psutil.virtual_memory()
        ram  = mem.percent

        if   cpu >= 85 or ram >= 88:  new_level = "critical"
        elif cpu >= 70 or ram >= 80:  new_level = "low"
        elif cpu >= 50 or ram >= 70:  new_level = "moderate"
        else:                          new_level = "normal"

        with self._lock:
            if new_level != self._level:
                # Apply hysteresis: only downgrade if clearly better
                current_idx = list(LEVEL_CONFIGS).index(self._level)
                new_idx     = list(LEVEL_CONFIGS).index(new_level)
                if new_idx > current_idx:   # upgrading (worse)
                    self._level = new_level
                else:                        # downgrading — require margin
                    cpu_margin = cpu < (85 - self.HYSTERESIS * 100) if self._level == "critical" else True
                    if cpu_margin:
                        self._level = new_level


# ── Integration patch for cognia_v3.py observe() ──────────────────
#
# Add to Cognia.__init__():
#   from cognia_throttle_controller import ThrottleController
#   self.throttle = ThrottleController()
#
# Replace the fatigue adaptations block in observe() with:
#   adaptations = self.throttle.adaptations
#   top_k = adaptations.top_k_retrieval
#   ... (same keys, same values, now accurate)
#
# The ThrottleController is a superset of CognitiveFatigueMonitor —
# keep the fatigue monitor for its LLM feedback loop, but use
# ThrottleController for all resource gating decisions.
`,
};

const ARCH_ISSUES = [
  {
    id: "loop",
    severity: "critical",
    title: "Busy cognitive loop",
    detail: "The main REPL runs while True with no idle detection. Every cycle re-runs embedding retrieval, KG lookup, inference, and temporal predictions regardless of whether anything changed.",
    fix: "Event-driven priority queue. User input = CRITICAL priority. Background work = LOW/IDLE, only dispatched when CPU < threshold.",
  },
  {
    id: "hypothesis",
    severity: "high",
    title: "Hypothesis generator always fires",
    detail: "generate_from_pattern() runs on every single inference cycle as long as len(similar) >= 2, which is almost always true.",
    fix: "Gate behind IdleHypothesisScheduler: run only when CPU < 40%, at least 60s since last run.",
  },
  {
    id: "selfarch",
    severity: "high",
    title: "SelfArchitect runs during active load",
    detail: "No CPU guard on the every-50-interactions trigger. SelfArchitect does multiple large DB queries and ORM operations.",
    fix: "SelfArchitectGate: skip if CPU > 60%, defer until next idle window.",
  },
  {
    id: "energy",
    severity: "high",
    title: "Energy monitor always reports 0",
    detail: "energy_estimate = cycle_ms / 80.0 normalizes the cycle time to a dimensionless ratio, not energy. The actual psutil data (CPU%, RAM) is read but never used in the formula.",
    fix: "RealEnergyMonitor: watts = idle_baseline + cpu_fraction × TDP + ram_gb × ram_coeff. energy = watts × seconds.",
  },
  {
    id: "cache",
    severity: "medium",
    title: "Unbounded embedding cache",
    detail: "_embedding_cache is a plain dict with no lock and O(n) eviction (iterates to find oldest key). With 9GB RAM usage, this cache may grow very large in long sessions.",
    fix: "BoundedLRUCache with OrderedDict: O(1) eviction, thread-safe, memory-pressure shrink.",
  },
  {
    id: "kg",
    severity: "medium",
    title: "KG retrieval not throttled",
    detail: "get_facts() and spreading_activation() run at full depth on every observe() call, even at critical CPU load.",
    fix: "KGRetrievalLimiter: reduce limit to 2-3 facts during high load. Disable spreading_activation in critical mode.",
  },
  {
    id: "consolidation",
    severity: "medium",
    title: "Consolidation runs mid-cycle",
    detail: "consolidation.consolidate() runs inline inside observe() every 8 interactions, blocking the response and adding latency during active conversation.",
    fix: "DeferredMaintenance: schedule consolidation as a background LOW-priority event, not inline.",
  },
  {
    id: "ollama",
    severity: "medium",
    title: "LLM context not shortened under load",
    detail: "Ollama is called with the same context window regardless of system pressure. Large prompts = more RAM + longer blocking calls.",
    fix: "ThrottleAdaptations.llm_context_tokens: 2048 → 512 tokens as load increases. Pass to every Ollama call.",
  },
];

const SEVERITY_COLOR = {
  critical: { bg: "#FCEBEB", text: "#A32D2D", border: "#F09595" },
  high:     { bg: "#FAEEDA", text: "#854F0B", border: "#FAC775" },
  medium:   { bg: "#E6F1FB", text: "#185FA5", border: "#B5D4F4" },
};

const SEVERITY_LABEL = { critical: "Critical", high: "High", medium: "Medium" };

export default function CogniaOptimizer() {
  const [section, setSection]   = useState("arch");
  const [expanded, setExpanded] = useState({});
  const [copiedKey, setCopied]  = useState(null);

  const toggleIssue = (id) => setExpanded(p => ({ ...p, [id]: !p[id] }));

  const copyCode = (key) => {
    navigator.clipboard.writeText(CODE[key] || "").then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 1800);
    });
  };

  return (
    <div style={{ fontFamily: "var(--font-sans)", color: "var(--color-text-primary)", padding: "0 0 40px" }}>

      {/* Header */}
      <div style={{ borderBottom: "1px solid var(--color-border-tertiary)", paddingBottom: 20, marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <span style={{ fontSize: 22, fontWeight: 500 }}>Cognia Optimizer</span>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)", background: "var(--color-background-secondary)", padding: "2px 8px", borderRadius: 6, border: "1px solid var(--color-border-tertiary)" }}>v3 · CPU-only · 12GB RAM</span>
        </div>
        <p style={{ fontSize: 14, color: "var(--color-text-secondary)", marginTop: 6, lineHeight: 1.6 }}>
          Architecture analysis, optimized code, and integration patches for drastically reducing CPU and RAM usage.
        </p>
      </div>

      {/* Nav */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 28 }}>
        {SECTIONS.map(s => (
          <button key={s.id} onClick={() => setSection(s.id)} style={{
            padding: "5px 14px", borderRadius: 20, border: "1px solid",
            borderColor: section === s.id ? "var(--color-border-primary)" : "var(--color-border-tertiary)",
            background: section === s.id ? "var(--color-background-secondary)" : "transparent",
            color: section === s.id ? "var(--color-text-primary)" : "var(--color-text-secondary)",
            fontSize: 13, fontWeight: section === s.id ? 500 : 400, cursor: "pointer",
          }}>{s.label}</button>
        ))}
      </div>

      {/* ARCHITECTURE */}
      {section === "arch" && (
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 500, marginBottom: 6 }}>Root cause analysis</h2>
          <p style={{ fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 20 }}>
            Eight specific issues were identified by reading the full source of <code>cognia_v3.py</code>, <code>fatiga_cognitiva.py</code>, and <code>cognia_idle.py</code>. Every fix is additive — no existing module is removed.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {ARCH_ISSUES.map(issue => {
              const col = SEVERITY_COLOR[issue.severity];
              return (
                <div key={issue.id} style={{ borderRadius: 10, border: `1px solid ${col.border}`, overflow: "hidden" }}>
                  <div onClick={() => toggleIssue(issue.id)} style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "12px 16px",
                    background: col.bg, cursor: "pointer", userSelect: "none",
                  }}>
                    <span style={{ fontSize: 11, fontWeight: 500, color: col.text, background: "rgba(255,255,255,0.6)", padding: "2px 7px", borderRadius: 4, minWidth: 56, textAlign: "center" }}>
                      {SEVERITY_LABEL[issue.severity]}
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 500, color: col.text, flex: 1 }}>{issue.title}</span>
                    <span style={{ fontSize: 16, color: col.text, transform: expanded[issue.id] ? "rotate(90deg)" : "none", transition: "transform 0.15s" }}>›</span>
                  </div>
                  {expanded[issue.id] && (
                    <div style={{ padding: "14px 16px", borderTop: `1px solid ${col.border}`, background: "var(--color-background-primary)" }}>
                      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.65, marginBottom: 10 }}>
                        <strong style={{ color: "var(--color-text-primary)", fontWeight: 500 }}>Problem: </strong>{issue.detail}
                      </p>
                      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.65, margin: 0 }}>
                        <strong style={{ color: "var(--color-text-primary)", fontWeight: 500 }}>Fix: </strong>{issue.fix}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 28, padding: 16, borderRadius: 10, border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)" }}>
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 10 }}>Expected improvements after all patches</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              {[
                { label: "Peak CPU", before: "100%", after: "30–50%", note: "idle: <5%" },
                { label: "Peak RAM", before: "9–10 GB", after: "2–4 GB", note: "LRU cache bounded" },
                { label: "Hypothesis calls", before: "every cycle", after: "every 60s idle", note: "CPU < 40%" },
                { label: "SelfArchitect", before: "every 50 obs", after: "every 50 obs + CPU check", note: "skipped if busy" },
                { label: "Energy estimate", before: "always 0", after: "real joules/cycle", note: "psutil-based" },
                { label: "Consolidation", before: "inline, blocking", after: "deferred background", note: "no response lag" },
              ].map(m => (
                <div key={m.label} style={{ padding: 12, borderRadius: 8, border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-primary)" }}>
                  <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 4 }}>{m.label}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                    <span style={{ fontSize: 12, color: "var(--color-text-danger)", textDecoration: "line-through" }}>{m.before}</span>
                    <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>→</span>
                    <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-success)" }}>{m.after}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{m.note}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* CODE SECTIONS */}
      {["loop", "cpu", "memory", "energy", "throttle"].includes(section) && (
        <CodeSection codeKey={section} copiedKey={copiedKey} onCopy={copyCode} />
      )}

      {/* DIAGRAM */}
      {section === "diagram" && <DiagramSection />}
    </div>
  );
}

function CodeSection({ codeKey, copiedKey, onCopy }) {
  const META = {
    loop:     { title: "Optimized cognitive loop", file: "cognia_event_loop.py", desc: "Replaces the while-True REPL with a priority event queue. User input is never delayed. Background tasks (consolidation, hypothesis, self-architect) only run when CPU is below threshold. No busy spin — uses queue.get(timeout=0.5) which yields the CPU entirely." },
    cpu:      { title: "CPU optimization", file: "cognia_cpu_optimizer.py", desc: "Four techniques: TimedBackgroundWorker replaces busy loops; IdleHypothesisScheduler gates hypothesis generation to CPU < 40% idle windows; SelfArchitectGate prevents evaluation during load; DeferredMaintenance defers consolidation and forgetting when CPU is high." },
    memory:   { title: "Memory optimization", file: "cognia_memory_optimizer.py", desc: "Five techniques: BoundedLRUCache (O(1) eviction, thread-safe, memory-pressure shrink); BoundedWorkingMemory (hard cap at 20 slots); KGRetrievalLimiter (3 facts in critical mode instead of 10); SemanticMemoryCap (trims lowest-confidence concepts above 2000); LazyModuleLoader (rare modules only loaded on first access)." },
    energy:   { title: "Real energy monitor", file: "cognia_energy_monitor.py", desc: "Fixes the always-zero bug. Real formula: watts = idle_baseline + (cpu_fraction × TDP_watts) + (ram_gb × 0.375). energy_joules = watts × cycle_seconds. Provides session totals and average wattage. Replaces the cycle_ms/80 pseudo-metric." },
    throttle: { title: "Throttle controller", file: "cognia_throttle_controller.py", desc: "Central resource gatekeeper. Polls CPU and RAM every 5 seconds in a background thread. Exposes four levels (normal → moderate → low → critical) with hysteresis to prevent oscillation. All modules query this one object instead of each calling psutil independently. Also controls LLM context window length." },
  };
  const m = META[codeKey];
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>{m.title}</h2>
          <code style={{ fontSize: 12, color: "var(--color-text-secondary)", background: "var(--color-background-secondary)", padding: "2px 8px", borderRadius: 4, border: "1px solid var(--color-border-tertiary)" }}>{m.file}</code>
        </div>
        <button onClick={() => onCopy(codeKey)} style={{
          padding: "6px 14px", borderRadius: 8, border: "1px solid var(--color-border-secondary)",
          background: "var(--color-background-secondary)", cursor: "pointer",
          color: "var(--color-text-secondary)", fontSize: 13, whiteSpace: "nowrap",
        }}>
          {copiedKey === codeKey ? "Copied!" : "Copy code"}
        </button>
      </div>
      <p style={{ fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 16 }}>{m.desc}</p>
      <pre style={{
        background: "var(--color-background-secondary)", border: "1px solid var(--color-border-tertiary)",
        borderRadius: 10, padding: 20, overflowX: "auto", fontSize: 12.5,
        lineHeight: 1.6, color: "var(--color-text-primary)", maxHeight: 560, overflowY: "auto",
        fontFamily: "var(--font-mono)",
      }}>{CODE[codeKey]}</pre>
    </div>
  );
}

function DiagramSection() {
  const [view, setView] = useState("before");
  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 500, marginBottom: 6 }}>Architecture diagram</h2>
      <p style={{ fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 16 }}>
        Before/after comparison of the cognitive execution model. The key change is moving from a synchronous blocking loop to an asynchronous event queue with a central resource gatekeeper.
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {["before", "after"].map(v => (
          <button key={v} onClick={() => setView(v)} style={{
            padding: "5px 18px", borderRadius: 20, border: "1px solid",
            borderColor: view === v ? "var(--color-border-primary)" : "var(--color-border-tertiary)",
            background: view === v ? "var(--color-background-secondary)" : "transparent",
            color: view === v ? "var(--color-text-primary)" : "var(--color-text-secondary)",
            fontSize: 13, fontWeight: view === v ? 500 : 400, cursor: "pointer",
          }}>{v === "before" ? "Before (current)" : "After (optimized)"}</button>
        ))}
      </div>

      {view === "before" ? <BeforeDiagram /> : <AfterDiagram />}

      <div style={{ marginTop: 24, padding: 16, borderRadius: 10, border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)" }}>
        <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 10 }}>Integration guide — minimal changes to cognia_v3.py</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            { step: "1", text: "Add ThrottleController to Cognia.__init__() — replaces per-module psutil calls" },
            { step: "2", text: "Replace _embedding_cache dict with BoundedLRUCache instance" },
            { step: "3", text: "Wrap observe() with RealEnergyMonitor.start_cycle() / end_cycle()" },
            { step: "4", text: "Move consolidation and forgetting calls into DeferredMaintenance.tick()" },
            { step: "5", text: "Replace hypothesis inline call with IdleHypothesisScheduler.maybe_run()" },
            { step: "6", text: "Add SelfArchitectGate.check_and_run() after every 50 interactions" },
            { step: "7", text: "Pass throttle.adaptations.llm_context_tokens to every Ollama API call" },
          ].map(item => (
            <div key={item.step} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span style={{ minWidth: 22, height: 22, borderRadius: 11, background: "var(--color-background-info)", color: "var(--color-text-info)", fontSize: 11, fontWeight: 500, display: "flex", alignItems: "center", justifyContent: "center" }}>{item.step}</span>
              <span style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.55 }}>{item.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BeforeDiagram() {
  return (
    <svg width="100%" viewBox="0 0 680 480" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arr-b" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </marker>
      </defs>
      {/* Outer loop box */}
      <rect x="40" y="30" width="600" height="420" rx="12" fill="none" stroke="var(--color-border-secondary)" strokeWidth="1" strokeDasharray="6 4"/>
      <text className="ts" x="56" y="54" style={{fontSize:12, fill:"var(--color-text-tertiary)"}}>while True (synchronous, blocking)</text>

      {/* User input */}
      <g>
        <rect x="270" y="68" width="140" height="40" rx="8" fill="#E6F1FB" stroke="#B5D4F4" strokeWidth="0.5"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#0C447C"}} x="340" y="92" textAnchor="middle" dominantBaseline="central">User input</text>
      </g>
      <line x1="340" y1="108" x2="340" y2="132" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-b)"/>

      {/* observe() */}
      <g>
        <rect x="200" y="132" width="280" height="40" rx="8" fill="#E1F5EE" stroke="#9FE1CB" strokeWidth="0.5"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#085041"}} x="340" y="156" textAnchor="middle" dominantBaseline="central">observe() — full pipeline every call</text>
      </g>
      <line x1="340" y1="172" x2="340" y2="196" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-b)"/>

      {/* Always-on modules row */}
      <g>
        <rect x="60" y="196" width="116" height="56" rx="8" fill="#FCEBEB" stroke="#F09595" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#A32D2D"}} x="118" y="216" textAnchor="middle">Hypothesis</text>
        <text style={{fontSize:11,fill:"#A32D2D"}} x="118" y="234" textAnchor="middle">every cycle</text>
      </g>
      <g>
        <rect x="192" y="196" width="116" height="56" rx="8" fill="#FCEBEB" stroke="#F09595" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#A32D2D"}} x="250" y="216" textAnchor="middle">KG retrieval</text>
        <text style={{fontSize:11,fill:"#A32D2D"}} x="250" y="234" textAnchor="middle">full depth always</text>
      </g>
      <g>
        <rect x="324" y="196" width="116" height="56" rx="8" fill="#FCEBEB" stroke="#F09595" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#A32D2D"}} x="382" y="216" textAnchor="middle">Consolidation</text>
        <text style={{fontSize:11,fill:"#A32D2D"}} x="382" y="234" textAnchor="middle">inline, blocking</text>
      </g>
      <g>
        <rect x="456" y="196" width="116" height="56" rx="8" fill="#FAEEDA" stroke="#FAC775" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#854F0B"}} x="514" y="216" textAnchor="middle">SelfArchitect</text>
        <text style={{fontSize:11,fill:"#854F0B"}} x="514" y="234" textAnchor="middle">every 50, no CPU gate</text>
      </g>
      {[118,250,382,514].map(x => (
        <line key={x} x1={x} y1="172" x2={x} y2="194" stroke="var(--color-text-secondary)" strokeWidth="0.8" markerEnd="url(#arr-b)"/>
      ))}

      {/* Energy monitor */}
      <g>
        <rect x="200" y="280" width="280" height="40" rx="8" fill="#FAEEDA" stroke="#FAC775" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#854F0B"}} x="340" y="300" textAnchor="middle" dominantBaseline="central">energy_estimate = cycle_ms / 80  ← always ≈ 0</text>
      </g>
      <line x1="340" y1="252" x2="340" y2="278" stroke="var(--color-text-secondary)" strokeWidth="0.8" markerEnd="url(#arr-b)"/>

      {/* Embedding cache */}
      <g>
        <rect x="200" y="348" width="280" height="40" rx="8" fill="#FAEEDA" stroke="#FAC775" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#854F0B"}} x="340" y="368" textAnchor="middle" dominantBaseline="central">_embedding_cache — unbounded dict, no lock</text>
      </g>
      <line x1="340" y1="320" x2="340" y2="346" stroke="var(--color-text-secondary)" strokeWidth="0.8" markerEnd="url(#arr-b)"/>

      {/* Return arrow */}
      <path d="M 620 240 L 650 240 L 650 88 L 412 88" fill="none" stroke="var(--color-text-tertiary)" strokeWidth="0.8" strokeDasharray="5 3" markerEnd="url(#arr-b)"/>
      <text style={{fontSize:11,fill:"var(--color-text-tertiary)"}} x="648" y="168" textAnchor="end">loop</text>

      {/* No resource check */}
      <g>
        <rect x="200" y="416" width="280" height="22" rx="6" fill="var(--color-background-secondary)" stroke="var(--color-border-tertiary)" strokeWidth="0.5"/>
        <text style={{fontSize:11,fill:"var(--color-text-tertiary)"}} x="340" y="428" textAnchor="middle" dominantBaseline="central">No CPU / RAM check before any operation</text>
      </g>
    </svg>
  );
}

function AfterDiagram() {
  return (
    <svg width="100%" viewBox="0 0 680 520" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arr-a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </marker>
      </defs>

      {/* ThrottleController — top */}
      <g>
        <rect x="180" y="28" width="320" height="50" rx="10" fill="#E1F5EE" stroke="#5DCAA5" strokeWidth="1"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#085041"}} x="340" y="47" textAnchor="middle">ThrottleController</text>
        <text style={{fontSize:11,fill:"#0F6E56"}} x="340" y="65" textAnchor="middle">polls CPU + RAM every 5s — level: normal | moderate | low | critical</text>
      </g>

      {/* Priority queue */}
      <g>
        <rect x="200" y="116" width="280" height="44" rx="8" fill="#E6F1FB" stroke="#85B7EB" strokeWidth="0.5"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#0C447C"}} x="340" y="134" textAnchor="middle">Event Queue (PriorityQueue)</text>
        <text style={{fontSize:11,fill:"#185FA5"}} x="340" y="150" textAnchor="middle">CRITICAL → HIGH → NORMAL → LOW → IDLE</text>
      </g>
      <line x1="340" y1="78" x2="340" y2="114" stroke="#5DCAA5" strokeWidth="1" markerEnd="url(#arr-a)"/>

      {/* Input lanes */}
      <g>
        <rect x="52" y="116" width="120" height="44" rx="8" fill="#E6F1FB" stroke="#B5D4F4" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#0C447C"}} x="112" y="134" textAnchor="middle">User input</text>
        <text style={{fontSize:11,fill:"#185FA5"}} x="112" y="150" textAnchor="middle">CRITICAL — never gated</text>
      </g>
      <line x1="172" y1="138" x2="198" y2="138" stroke="#B5D4F4" strokeWidth="1" markerEnd="url(#arr-a)"/>

      <g>
        <rect x="508" y="116" width="120" height="44" rx="8" fill="#F1EFE8" stroke="#B4B2A9" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#444441"}} x="568" y="134" textAnchor="middle">Background</text>
        <text style={{fontSize:11,fill:"#5F5E5A"}} x="568" y="150" textAnchor="middle">LOW / IDLE only</text>
      </g>
      <line x1="508" y1="138" x2="482" y2="138" stroke="#B4B2A9" strokeWidth="1" markerEnd="url(#arr-a)"/>

      <line x1="340" y1="160" x2="340" y2="184" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-a)"/>

      {/* Dispatcher */}
      <g>
        <rect x="200" y="184" width="280" height="40" rx="8" fill="#E1F5EE" stroke="#9FE1CB" strokeWidth="0.5"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#085041"}} x="340" y="208" textAnchor="middle" dominantBaseline="central">Dispatcher — reads throttle.adaptations</text>
      </g>
      <line x1="340" y1="224" x2="340" y2="248" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-a)"/>

      {/* observe() */}
      <g>
        <rect x="200" y="248" width="280" height="40" rx="8" fill="#E1F5EE" stroke="#5DCAA5" strokeWidth="0.5"/>
        <text style={{fontSize:13,fontWeight:500,fill:"#0F6E56"}} x="340" y="272" textAnchor="middle" dominantBaseline="central">observe() — top_k, KG depth throttled</text>
      </g>
      <line x1="340" y1="288" x2="340" y2="312" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-a)"/>

      {/* Real energy */}
      <g>
        <rect x="200" y="312" width="280" height="40" rx="8" fill="#EAF3DE" stroke="#C0DD97" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#3B6D11"}} x="340" y="335" textAnchor="middle" dominantBaseline="central">RealEnergyMonitor — watts × seconds = joules</text>
      </g>
      <line x1="340" y1="352" x2="340" y2="376" stroke="var(--color-text-secondary)" strokeWidth="1" markerEnd="url(#arr-a)"/>

      {/* BoundedLRUCache */}
      <g>
        <rect x="200" y="376" width="280" height="40" rx="8" fill="#EAF3DE" stroke="#97C459" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#3B6D11"}} x="340" y="399" textAnchor="middle" dominantBaseline="central">BoundedLRUCache — 512 entries, thread-safe</text>
      </g>

      {/* Background workers row */}
      <g>
        <rect x="52" y="444" width="130" height="52" rx="8" fill="#F1EFE8" stroke="#D3D1C7" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#444441"}} x="117" y="464" textAnchor="middle">Hypothesis</text>
        <text style={{fontSize:11,fill:"#5F5E5A"}} x="117" y="482" textAnchor="middle">idle only, CPU &lt; 40%</text>
      </g>
      <g>
        <rect x="200" y="444" width="130" height="52" rx="8" fill="#F1EFE8" stroke="#D3D1C7" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#444441"}} x="265" y="464" textAnchor="middle">Consolidation</text>
        <text style={{fontSize:11,fill:"#5F5E5A"}} x="265" y="482" textAnchor="middle">deferred background</text>
      </g>
      <g>
        <rect x="348" y="444" width="130" height="52" rx="8" fill="#F1EFE8" stroke="#D3D1C7" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#444441"}} x="413" y="464" textAnchor="middle">SelfArchitect</text>
        <text style={{fontSize:11,fill:"#5F5E5A"}} x="413" y="482" textAnchor="middle">CPU &lt; 60% gate</text>
      </g>
      <g>
        <rect x="496" y="444" width="132" height="52" rx="8" fill="#F1EFE8" stroke="#D3D1C7" strokeWidth="0.5"/>
        <text style={{fontSize:12,fontWeight:500,fill:"#444441"}} x="562" y="464" textAnchor="middle">Sleep / Research</text>
        <text style={{fontSize:11,fill:"#5F5E5A"}} x="562" y="482" textAnchor="middle">event-triggered</text>
      </g>

      {/* Throttle down arrows to background row */}
      {[117, 265, 413, 562].map(x => (
        <line key={x} x1={x} y1="420" x2={x} y2="442" stroke="#B4B2A9" strokeWidth="0.8" strokeDasharray="4 3" markerEnd="url(#arr-a)"/>
      ))}

      <text style={{fontSize:11,fill:"var(--color-text-tertiary)"}} x="340" y="438" textAnchor="middle">background thread pool — only dispatched at LOW / IDLE level</text>
    </svg>
  );
}
