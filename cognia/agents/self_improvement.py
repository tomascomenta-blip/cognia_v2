"""
cognia/agents/self_improvement.py — Phase 26

SafeImprover: mejora autónoma de parámetros sin modificar código.

Constraints:
  - 0 LLM calls
  - parameter-only changes (module attribute patching, never file writes)
  - experiments aislados en DB temporal (nunca toca cognia_agents.db real)
  - cambio adoptado solo si mejora composite score > MIN_DELTA
  - máximo MAX_EXPERIMENTS_PER_RUN experimentos por llamada a run()

4 métricas SQL (agent_tasks + agent_subtasks):
  1. completion_rate      — DONE / total terminal (higher better)
  2. failed_rate          — FAILED / total terminal (lower better)
  3. avg_attempts         — AVG(attempts) terminal tasks (lower better)
  4. subtask_pass_rate    — subtask done / total subtasks (higher better)

Parámetros tunables (5):
  verifier_score_threshold      mirrors verifier.SCORE_THRESHOLD
  verifier_min_text_length      mirrors verifier.MIN_TEXT_LENGTH
  verifier_kg_sim_threshold     mirrors verifier.KG_SIM_THRESHOLD
  planner_episodic_threshold    mirrors planner.EPISODIC_PLAN_THRESHOLD
  research_episodic_threshold   mirrors research_worker._EPISODIC_HIT_THRESHOLD
"""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple


# ── Constantes ────────────────────────────────────────────────────────────────

MIN_DELTA             = 0.02   # mejora mínima para adoptar cambio
MAX_EXPERIMENTS_PER_RUN = 3
_SYNTHETIC_TASKS = [
    "analiza el archivo cognia/agents/planner.py",
    "analiza el archivo cognia/agents/verifier.py",
    "analiza el archivo cognia/agents/task_queue.py",
    "analiza el archivo cognia/agents/supervisor.py",
    "analiza el archivo cognia/agents/daemon.py",
]

# ── Params ────────────────────────────────────────────────────────────────────

@dataclass
class TunableParams:
    verifier_score_threshold:    float = 0.60
    verifier_min_text_length:    int   = 20
    verifier_kg_sim_threshold:   float = 0.30
    planner_episodic_threshold:  float = 0.85
    research_episodic_threshold: float = 0.75

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "TunableParams":
        return TunableParams(**{k: v for k, v in d.items() if k in TunableParams.__dataclass_fields__})


# (param_name, min_val, max_val, is_int)
_BOUNDS: dict[str, Tuple] = {
    "verifier_score_threshold":    (0.3,  0.9,  False),
    "verifier_min_text_length":    (5,    100,  True),
    "verifier_kg_sim_threshold":   (0.10, 0.70, False),
    "planner_episodic_threshold":  (0.60, 0.99, False),
    "research_episodic_threshold": (0.50, 0.95, False),
}


def _mutate(params: TunableParams, rng: random.Random) -> Tuple[TunableParams, str]:
    """Muta un parámetro aleatorio ±10%, clipado a bounds. Retorna (nueva_copia, nombre_param)."""
    param_name = rng.choice(list(_BOUNDS.keys()))
    lo, hi, is_int = _BOUNDS[param_name]
    current = getattr(params, param_name)
    delta = current * 0.10 * rng.choice([-1, 1])
    new_val = current + delta
    new_val = max(lo, min(hi, new_val))
    if is_int:
        new_val = int(round(new_val))
    d = params.to_dict()
    d[param_name] = new_val
    return TunableParams.from_dict(d), param_name


# ── Benchmark ─────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkMetrics:
    completion_rate:   float = 0.0   # DONE / total terminal
    failed_rate:       float = 0.0   # FAILED / total terminal
    avg_attempts:      float = 1.0   # AVG(attempts) terminal tasks
    subtask_pass_rate: float = 0.0   # subtask done / total subtasks


def _composite(m: BenchmarkMetrics) -> float:
    attempt_score = 1.0 / max(1.0, m.avg_attempts) if m.avg_attempts > 0 else 1.0
    return (
        0.40 * m.completion_rate
        + 0.30 * m.subtask_pass_rate
        + 0.20 * (1.0 - m.failed_rate)
        + 0.10 * attempt_score
    )


class Benchmark:
    """Lee métricas desde un SQLite de agentes. Read-only."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def measure(self, task_ids: Optional[List[str]] = None) -> BenchmarkMetrics:
        """
        Calcula las 4 métricas.
        Si task_ids es None mide todas las tareas terminales del DB.
        """
        if not Path(self._db_path).exists():
            return BenchmarkMetrics()
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self._db_path)  # pool: WAL+timeout ya aplicados
            m = self._compute(conn, task_ids)
            conn.close()
            return m
        except Exception:
            return BenchmarkMetrics()

    def _compute(self, conn: sqlite3.Connection, task_ids: Optional[List[str]]) -> BenchmarkMetrics:
        if task_ids:
            placeholders = ",".join("?" * len(task_ids))
            where = f"WHERE task_id IN ({placeholders}) AND status IN ('DONE','FAILED','ABORTED')"
            rows = conn.execute(
                f"SELECT status, attempts FROM agent_tasks {where}", task_ids
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, attempts FROM agent_tasks WHERE status IN ('DONE','FAILED','ABORTED')"
            ).fetchall()

        if not rows:
            return BenchmarkMetrics()

        total    = len(rows)
        done     = sum(1 for r in rows if r[0] == "DONE")
        failed   = sum(1 for r in rows if r[0] == "FAILED")
        attempts = [r[1] for r in rows]
        avg_att  = sum(attempts) / len(attempts)

        # subtask pass rate (scoped to task_ids if provided)
        if task_ids:
            placeholders = ",".join("?" * len(task_ids))
            st_rows = conn.execute(
                f"SELECT status FROM agent_subtasks WHERE task_id IN ({placeholders})",
                task_ids,
            ).fetchall()
        else:
            st_rows = conn.execute("SELECT status FROM agent_subtasks").fetchall()

        total_st = len(st_rows)
        done_st  = sum(1 for r in st_rows if r[0] == "done")
        st_pass  = done_st / total_st if total_st > 0 else 0.0

        return BenchmarkMetrics(
            completion_rate   = done / total,
            failed_rate       = failed / total,
            avg_attempts      = avg_att,
            subtask_pass_rate = st_pass,
        )


# ── Patching context manager ──────────────────────────────────────────────────

@contextmanager
def _patch_params(params: TunableParams) -> Iterator[None]:
    """
    Aplica TunableParams como atributos de módulo temporalmente.
    Siempre restaura los valores originales al salir.
    """
    import cognia.agents.verifier as _ver
    import cognia.agents.planner as _plan
    import cognia.agents.workers.research_worker as _rw

    orig = {
        "_ver.SCORE_THRESHOLD":             _ver.SCORE_THRESHOLD,
        "_ver.MIN_TEXT_LENGTH":             _ver.MIN_TEXT_LENGTH,
        "_ver.KG_SIM_THRESHOLD":            _ver.KG_SIM_THRESHOLD,
        "_plan.EPISODIC_PLAN_THRESHOLD":    _plan.EPISODIC_PLAN_THRESHOLD,
        "_rw._EPISODIC_HIT_THRESHOLD":      _rw._EPISODIC_HIT_THRESHOLD,
    }
    try:
        _ver.SCORE_THRESHOLD          = params.verifier_score_threshold
        _ver.MIN_TEXT_LENGTH          = params.verifier_min_text_length
        _ver.KG_SIM_THRESHOLD         = params.verifier_kg_sim_threshold
        _plan.EPISODIC_PLAN_THRESHOLD = params.planner_episodic_threshold
        _rw._EPISODIC_HIT_THRESHOLD   = params.research_episodic_threshold
        yield
    finally:
        _ver.SCORE_THRESHOLD          = orig["_ver.SCORE_THRESHOLD"]
        _ver.MIN_TEXT_LENGTH          = orig["_ver.MIN_TEXT_LENGTH"]
        _ver.KG_SIM_THRESHOLD         = orig["_ver.KG_SIM_THRESHOLD"]
        _plan.EPISODIC_PLAN_THRESHOLD = orig["_plan.EPISODIC_PLAN_THRESHOLD"]
        _rw._EPISODIC_HIT_THRESHOLD   = orig["_rw._EPISODIC_HIT_THRESHOLD"]


# ── SandboxedExperiment ───────────────────────────────────────────────────────

class SandboxedExperiment:
    """
    Corre N tareas sintéticas con los params dados en una DB temporal aislada.
    Retorna BenchmarkMetrics sin modificar el DB real ni archivos de código.
    """

    def __init__(self, params: TunableParams, n_tasks: int = 5) -> None:
        self._params  = params
        self._n_tasks = min(n_tasks, len(_SYNTHETIC_TASKS))

    def run(self) -> BenchmarkMetrics:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            return self._run_in(tmp_db)
        finally:
            try:
                Path(tmp_db).unlink(missing_ok=True)
            except OSError:
                pass

    def _run_in(self, db_path: str) -> BenchmarkMetrics:
        from cognia.agents.supervisor import CogniaAgentRuntime

        with _patch_params(self._params):
            runtime  = CogniaAgentRuntime(db_path=db_path)
            task_ids = []
            for desc in _SYNTHETIC_TASKS[:self._n_tasks]:
                tid = runtime.submit(desc)
                task_ids.append(tid)

            for _ in task_ids:
                runtime.tick()

            return Benchmark(db_path).measure(task_ids)


# ── SafeImprover ──────────────────────────────────────────────────────────────

class SafeImprover:
    """
    Orquesta ciclos de auto-mejora de parámetros.

    Uso típico (desde daemon idle):
        improver = SafeImprover(agents_db_path="cognia_agents.db")
        result   = improver.run()   # retorna ExperimentResult

    Persiste los mejores params en <agents_db_path>.params.json.
    """

    def __init__(
        self,
        agents_db_path: str = "cognia_agents.db",
        n_tasks: int = 5,
        seed: Optional[int] = None,
    ) -> None:
        self._db_path    = agents_db_path
        self._params_path = Path(agents_db_path).with_suffix(".params.json")
        self._n_tasks    = n_tasks
        self._rng        = random.Random(seed)

    # ── API pública ──────────────────────────────────────────────────────────

    def run(self) -> "ImprovementResult":
        """
        Ejecuta hasta MAX_EXPERIMENTS_PER_RUN experimentos.
        Adopta el mejor resultado si supera MIN_DELTA.
        Retorna ImprovementResult con detalle.
        """
        current_params  = self._load_params()
        baseline        = Benchmark(self._db_path).measure()
        baseline_score  = _composite(baseline)

        best_params     = current_params
        best_score      = baseline_score
        best_param_name = None
        experiments     = []

        for _ in range(MAX_EXPERIMENTS_PER_RUN):
            candidate, mutated_param = _mutate(best_params, self._rng)
            metrics = SandboxedExperiment(candidate, n_tasks=self._n_tasks).run()
            score   = _composite(metrics)
            experiments.append((mutated_param, score))

            if score > best_score:
                best_score      = score
                best_params     = candidate
                best_param_name = mutated_param

        adopted = best_score - baseline_score >= MIN_DELTA
        if adopted:
            self._save_params(best_params)
            _apply_params(best_params)

        return ImprovementResult(
            adopted        = adopted,
            baseline_score = baseline_score,
            best_score     = best_score,
            delta          = best_score - baseline_score,
            mutated_param  = best_param_name,
            params         = best_params,
            experiments    = experiments,
        )

    def current_params(self) -> TunableParams:
        return self._load_params()

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _load_params(self) -> TunableParams:
        if self._params_path.exists():
            try:
                with open(self._params_path, "r", encoding="utf-8") as f:
                    return TunableParams.from_dict(json.load(f))
            except Exception:
                pass
        return TunableParams()

    def _save_params(self, params: TunableParams) -> None:
        try:
            with open(self._params_path, "w", encoding="utf-8") as f:
                json.dump(params.to_dict(), f, indent=2)
        except Exception:
            pass


def _apply_params(params: TunableParams) -> None:
    """
    Aplica los parámetros adoptados al runtime actual (in-process).
    Llamada una sola vez por el SafeImprover tras adoptar.
    """
    try:
        import cognia.agents.verifier as _ver
        import cognia.agents.planner as _plan
        import cognia.agents.workers.research_worker as _rw
        _ver.SCORE_THRESHOLD          = params.verifier_score_threshold
        _ver.MIN_TEXT_LENGTH          = params.verifier_min_text_length
        _ver.KG_SIM_THRESHOLD         = params.verifier_kg_sim_threshold
        _plan.EPISODIC_PLAN_THRESHOLD = params.planner_episodic_threshold
        _rw._EPISODIC_HIT_THRESHOLD   = params.research_episodic_threshold
    except Exception:
        pass


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ImprovementResult:
    adopted:        bool
    baseline_score: float
    best_score:     float
    delta:          float
    mutated_param:  Optional[str]
    params:         TunableParams
    experiments:    List[Tuple[str, float]] = field(default_factory=list)

    def summary(self) -> str:
        status = "ADOPTED" if self.adopted else "NO_CHANGE"
        param  = self.mutated_param or "none"
        return (
            f"[self_improvement] {status} | "
            f"delta={self.delta:+.4f} | "
            f"param={param} | "
            f"score={self.baseline_score:.4f}->{self.best_score:.4f}"
        )
