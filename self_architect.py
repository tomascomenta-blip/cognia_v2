"""
self_architect.py — Meta-Learning Self-Optimization Engine for COGNIA v4
=========================================================================
Redesign of the SelfArchitect module for guided evolutionary improvement.

WHAT'S NEW IN v4 vs v3:
  ① MetaLearningTracker  — learns which changes actually improve the system
  ② FatigueAdvisor       — uses fatigue score to gate expensive diagnostics
  ③ EnergyProfiler       — tracks and scores energy cost per reasoning cycle
  ④ ModuleProposer       — proposes entirely new modules (not just param tweaks)
  ⑤ StrategySelector     — picks the best proposal strategy based on history
  ⑥ TrendAnalyzer        — detects degradation trends before they become crises
  ⑦ Richer metrics       — reasoning_latency, cache_efficiency, attention_waste
  ⑧ Proposal scoring     — proposals are ranked by predicted ROI, not just severity

DESIGN INVARIANT (unchanged from v3):
  The AI PROPOSES, the human DECIDES, the system RECORDS.
  No change is ever applied without approved=True set by a human.

ARCHITECTURE:
  ArchitectureEvaluator  — collects metrics (SQL only, no embeddings, < 40ms)
  DiagnosticEngine       — detects structural problems with thresholds
  TrendAnalyzer          — detects metric trends across evaluations
  FatigueAdvisor         — maps fatigue level → allowed diagnostic depth
  EnergyProfiler         — tracks energy per reasoning cycle
  MetaLearningTracker    — learns from change outcomes over time
  ChangeProposer         — generates param + module + new-module proposals
  ModuleProposer         — proposes new cognitive modules when gaps are found
  StrategySelector       — ranks proposals by predicted success probability
  ChangeApplicator       — safely applies approved changes
  ArchitectureLog        — immutable history of all changes and outcomes
  SelfArchitect          — orchestrates the full cycle and exposes API

ENERGY PHILOSOPHY:
  Cognitive computation is treated like biological fatigue.
  Expensive operations are skipped under high fatigue.
  Every proposed change includes an energy_impact score.
  The architecture_score now penalizes high energy per cycle.
"""

import sqlite3
import json
import math
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple


# ══════════════════════════════════════════════════════════════════════
# CONSTANTS AND CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

ARCH_DB_PATH = "cognia_memory.db"

EVAL_INTERVAL     = 50    # interactions between evaluations
MAX_CHANGES_PER_DAY = 3   # emergency brake on daily change count
MAX_MODULE_PROPOSALS_PER_EVAL = 2  # cap new-module proposals per run

# Diagnostic thresholds (same as v3, extended)
THRESHOLDS = {
    "error_rate_critical":      0.55,
    "error_rate_high":          0.35,
    "memory_bloat_ratio":       0.70,
    "contradiction_density":    0.15,
    "kg_isolation":             0.40,
    "attention_waste":          0.60,
    "concept_drift_threshold":  0.25,
    "low_hypothesis_rate":      0.05,
    "cache_hit_floor":          0.30,
    # v4 additions
    "high_reasoning_latency_ms": 800,   # avg latency > 800ms = problem
    "low_cache_efficiency":      0.25,  # cache hit ratio < 25%
    "energy_per_cycle_high":     1.5,   # normalized energy units
    "inference_depth_waste":     0.50,  # >50% cycles hit max inference steps
    "working_memory_pressure":   0.85,  # WM usage > 85% of capacity
}

SEVERITY = {"critical": 3, "high": 2, "medium": 1, "low": 0}

# Fatigue levels (mapped from fatigue_score 0.0–1.0)
FATIGUE_LEVELS = {
    "low":      (0.00, 0.30),  # full diagnostics allowed
    "moderate": (0.30, 0.60),  # skip expensive diagnostics
    "high":     (0.60, 0.80),  # minimal diagnostics only
    "critical": (0.80, 1.00),  # only critical checks + propose architecture change
}


def db_connect(path: str = ARCH_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.text_factory = str
    return conn


# ══════════════════════════════════════════════════════════════════════
# DATABASE TABLES — safe migration
# ══════════════════════════════════════════════════════════════════════

def init_architecture_tables(path: str = ARCH_DB_PATH):
    """Creates all required tables. Safe to call multiple times."""
    conn = db_connect(path)
    c = conn.cursor()

    # Immutable evaluation history
    c.execute("""
    CREATE TABLE IF NOT EXISTS architecture_evaluations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        interaction_at  INTEGER NOT NULL,
        metrics         TEXT NOT NULL,
        diagnoses       TEXT NOT NULL,
        score           REAL NOT NULL,
        fatigue_level   TEXT DEFAULT 'low',
        triggered_by    TEXT DEFAULT 'auto'
    )""")

    # Change proposals (pending | approved | rejected | applied | rolled_back)
    c.execute("""
    CREATE TABLE IF NOT EXISTS architecture_proposals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        evaluation_id   INTEGER,
        diagnosis_key   TEXT NOT NULL,
        proposal_type   TEXT DEFAULT 'param_update',
        title           TEXT NOT NULL,
        problem         TEXT NOT NULL,
        modification    TEXT NOT NULL,
        why_better      TEXT NOT NULL,
        risks           TEXT NOT NULL,
        impact          TEXT NOT NULL,
        energy_impact   TEXT DEFAULT 'low',
        predicted_roi   REAL DEFAULT 0.5,
        reversible      INTEGER DEFAULT 1,
        status          TEXT DEFAULT 'pending',
        human_comment   TEXT,
        decided_at      TEXT,
        param_key       TEXT,
        param_new       TEXT,
        params_before   TEXT,
        params_after    TEXT
    )""")

    # Applied change log (source of truth for rollback)
    c.execute("""
    CREATE TABLE IF NOT EXISTS architecture_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        proposal_id     INTEGER NOT NULL,
        change_type     TEXT NOT NULL,
        change_key      TEXT NOT NULL,
        value_before    TEXT,
        value_after     TEXT,
        impact_observed TEXT,
        reverted        INTEGER DEFAULT 0,
        reverted_at     TEXT
    )""")

    # Current architecture parameters (key-value)
    c.execute("""
    CREATE TABLE IF NOT EXISTS architecture_params (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        dtype       TEXT DEFAULT 'float',
        description TEXT,
        protected   INTEGER DEFAULT 0,
        updated_at  TEXT
    )""")

    # ── v4 NEW: meta-learning outcomes ────────────────────────────────
    # Tracks the before/after score delta for each applied change
    # so StrategySelector can predict ROI for future similar proposals.
    c.execute("""
    CREATE TABLE IF NOT EXISTS meta_learning_outcomes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        proposal_id     INTEGER NOT NULL,
        diagnosis_key   TEXT NOT NULL,
        param_key       TEXT,
        change_type     TEXT NOT NULL,
        score_before    REAL,
        score_after     REAL,
        score_delta     REAL,
        eval_before_id  INTEGER,
        eval_after_id   INTEGER,
        outcome         TEXT DEFAULT 'pending'  -- pending|positive|neutral|negative
    )""")

    # ── v4 NEW: energy tracking per interaction ────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS energy_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        interaction_id  INTEGER,
        embedding_calls INTEGER DEFAULT 0,
        retrieval_ops   INTEGER DEFAULT 0,
        inference_steps INTEGER DEFAULT 0,
        cache_hits      INTEGER DEFAULT 0,
        cache_misses    INTEGER DEFAULT 0,
        latency_ms      REAL DEFAULT 0,
        energy_estimate REAL DEFAULT 0   -- normalized units
    )""")

    # Safe column migrations for existing tables
    _safe_add_columns(c, "architecture_proposals", [
        ("proposal_type",  "TEXT DEFAULT 'param_update'"),
        ("energy_impact",  "TEXT DEFAULT 'low'"),
        ("predicted_roi",  "REAL DEFAULT 0.5"),
        ("generated_code", "TEXT"),
        ("test_result",    "TEXT"),
        ("test_passed",    "INTEGER DEFAULT NULL"),
    ])
    c.execute("""
        CREATE TABLE IF NOT EXISTS energy_micro_adjustments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL,
            param_key     TEXT NOT NULL,
            value_before  REAL NOT NULL,
            value_after   REAL NOT NULL,
            trigger       TEXT,
            energy_before REAL,
            energy_after  REAL,
            latency_before REAL,
            latency_after  REAL,
            outcome       TEXT DEFAULT 'pending'
        )
    """)
    _safe_add_columns(c, "architecture_evaluations", [
        ("fatigue_level", "TEXT DEFAULT 'low'"),
    ])

    conn.commit()
    conn.close()
    _seed_default_params(path)


def _safe_add_columns(cursor, table: str, columns: list):
    for col_def in columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            pass  # column already exists


def _seed_default_params(path: str):
    """Inserts default architectural parameters if they don't exist."""
    defaults = [
        ("attention_threshold",       "0.25",  "float", "Min score for an episode to pass attention filter", 0),
        ("attention_w_semantic",      "0.40",  "float", "Semantic weight in AttentionSystem", 0),
        ("attention_w_emotion",       "0.25",  "float", "Emotional weight in AttentionSystem", 0),
        ("attention_w_recency",       "0.20",  "float", "Recency weight in AttentionSystem", 0),
        ("attention_w_frequency",     "0.15",  "float", "Frequency weight in AttentionSystem", 0),
        ("forgetting_decay_rate",     "0.015", "float", "Importance decay rate per cycle", 0),
        ("forgetting_threshold",      "0.30",  "float", "Min importance before marking as forgotten", 0),
        ("consolidation_interval",    "8",     "int",   "Interactions between memory consolidations", 0),
        ("forgetting_interval",       "15",    "int",   "Interactions between forgetting cycles", 0),
        ("working_memory_capacity",   "12",    "int",   "Working memory slots", 0),
        ("embedding_cache_size",      "512",   "int",   "LRU embedding cache size", 0),
        ("kg_bridge_min_length",      "4",     "int",   "Min word length for KG triple extraction", 0),
        ("inference_max_steps",       "3",     "int",   "Max inference chain depth", 0),
        ("temporal_window_size",      "5",     "int",   "Temporal context window (concepts)", 0),
        ("hypothesis_confidence",     "0.3",   "float", "Initial confidence for new hypotheses", 0),
        ("eval_interval",             "50",    "int",   "Interactions between self-evaluations", 0),
        # v4 additions
        ("fatigue_threshold_suspend", "0.75",  "float", "Fatigue level to suspend expensive modules", 0),
        ("energy_budget_per_cycle",   "1.0",   "float", "Target max energy units per reasoning cycle", 0),
        ("meta_learning_window",      "10",    "int",   "Number of past changes used for ROI prediction", 0),
        # Protected params
        ("db_path",    ARCH_DB_PATH, "str", "SQLite database path", 1),
        ("vector_dim", "384",        "int", "Embedding dimensions (fixed to model)", 1),
        ("llm_model",  "llama3.2",   "str", "Ollama LLM model (requires restart)", 1),
    ]

    conn = db_connect(path)
    c = conn.cursor()
    for key, value, dtype, desc, protected in defaults:
        c.execute("""
            INSERT OR IGNORE INTO architecture_params
            (key, value, dtype, description, protected, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, value, dtype, desc, protected, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════
# 1. ARCHITECTURE EVALUATOR — reads metrics without heavy models
# ══════════════════════════════════════════════════════════════════════

class ArchitectureEvaluator:
    """
    Collects performance metrics from SQLite.
    No embeddings, no Ollama — pure SQL arithmetic.
    Typical runtime: 10–40ms on a laptop.

    v4 additions:
      - reasoning_latency_avg: from energy_log
      - cache_efficiency: cache_hits / (cache_hits + cache_misses)
      - energy_per_cycle: avg energy_estimate from energy_log
      - inference_depth_waste: fraction of cycles that hit max steps
      - working_memory_pressure: avg WM utilization
    """

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def collect_metrics(self, fatigue_level: str = "low") -> dict:
        """
        Returns a dict with all relevant system metrics.
        Under high fatigue, skips expensive multi-join queries.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        m = {}

        # ── Episodic memory ────────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0")
        m["active_memories"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=1")
        m["forgotten_memories"] = c.fetchone()[0]
        total_ep = m["active_memories"] + m["forgotten_memories"]
        m["total_memories"] = total_ep
        m["memory_bloat_ratio"] = m["forgotten_memories"] / max(1, total_ep)

        c.execute("SELECT AVG(confidence) FROM episodic_memory WHERE forgotten=0")
        m["avg_confidence"] = round(c.fetchone()[0] or 0.0, 4)
        c.execute("SELECT AVG(importance) FROM episodic_memory WHERE forgotten=0")
        m["avg_importance"] = round(c.fetchone()[0] or 0.0, 4)
        c.execute("SELECT COUNT(*) FROM episodic_memory WHERE label IS NULL AND forgotten=0")
        m["unlabeled_ratio"] = c.fetchone()[0] / max(1, m["active_memories"])

        # ── Semantic memory ────────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM semantic_memory")
        m["concept_count"] = c.fetchone()[0]
        c.execute("SELECT AVG(confidence) FROM semantic_memory")
        m["avg_concept_confidence"] = round(c.fetchone()[0] or 0.0, 4)
        c.execute("SELECT AVG(support) FROM semantic_memory")
        m["avg_concept_support"] = round(c.fetchone()[0] or 0.0, 2)

        # ── Knowledge Graph ────────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM knowledge_graph")
        m["kg_edges"] = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT subject) FROM knowledge_graph")
        m["kg_nodes"] = c.fetchone()[0]
        m["kg_isolation"] = max(0.0, 1.0 - m["kg_nodes"] / max(1, m["concept_count"])) \
                            if m["concept_count"] > 0 else 1.0
        m["kg_density"] = m["kg_edges"] / max(1, m["kg_nodes"])

        # ── Errors and feedback ────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM decision_log WHERE timestamp >= datetime('now','-24 hours')")
        m["decisions_24h"] = c.fetchone()[0]
        c.execute("SELECT SUM(was_error), COUNT(*) FROM decision_log WHERE timestamp >= datetime('now','-7 days')")
        row = c.fetchone(); errors_7d = row[0] or 0; total_7d = row[1] or 1
        m["error_rate_7d"] = round(errors_7d / max(1, total_7d), 4)

        c.execute("""
            SELECT SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN feedback=-1 THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM chat_history WHERE role='assistant'
              AND timestamp >= datetime('now','-48 hours')
        """)
        row = c.fetchone()
        m["feedback_positive"]        = row[0] or 0
        m["feedback_negative"]        = row[1] or 0
        m["feedback_ratio"]           = round(m["feedback_positive"] / max(1, row[2] or 1), 4)
        m["feedback_negative_ratio"]  = round(m["feedback_negative"] / max(1, row[2] or 1), 4)

        # ── Contradictions ─────────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0")
        m["contradictions_pending"] = c.fetchone()[0]
        m["contradiction_density"]  = m["contradictions_pending"] / max(1, m["active_memories"])

        # ── Hypotheses ─────────────────────────────────────────────────
        c.execute("SELECT COUNT(*), AVG(confidence) FROM hypotheses")
        row = c.fetchone()
        m["hypothesis_count"]           = row[0] or 0
        m["avg_hypothesis_confidence"]  = round(row[1] or 0.0, 4)
        m["hypothesis_rate"]            = m["hypothesis_count"] / max(1, m["active_memories"])

        # ── Temporal sequences ─────────────────────────────────────────
        c.execute("SELECT COUNT(*), AVG(count) FROM temporal_sequences")
        row = c.fetchone()
        m["sequence_count"] = row[0] or 0
        m["avg_seq_count"]  = round(row[1] or 0.0, 2)

        # ── Chat ───────────────────────────────────────────────────────
        c.execute("SELECT COUNT(*) FROM chat_history WHERE role='user'")
        m["total_user_interactions"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM chat_history WHERE role='user' AND timestamp >= datetime('now','-24 hours')")
        m["interactions_24h"] = c.fetchone()[0]

        # ── Sleep/consolidation ────────────────────────────────────────
        c.execute("SELECT COUNT(*), AVG(episodes_in), AVG(concepts_out) FROM sleep_log WHERE timestamp >= datetime('now','-7 days')")
        row = c.fetchone()
        m["sleep_cycles_7d"]    = row[0] or 0
        m["avg_eps_per_sleep"]  = round(row[1] or 0.0, 1)
        m["avg_conc_per_sleep"] = round(row[2] or 0.0, 1)

        # ── v4: Energy & latency (skip under high fatigue to save CPU) ─
        if fatigue_level in ("low", "moderate"):
            self._collect_energy_metrics(c, m)
        else:
            # Lightweight fallbacks
            m["reasoning_latency_avg"] = 0.0
            m["cache_efficiency"]      = 0.5
            m["energy_per_cycle"]      = 0.0
            m["inference_depth_waste"] = 0.0

        # ── Architecture score (0–100) ─────────────────────────────────
        s_error    = max(0, 100 - m["error_rate_7d"] * 200)
        s_kg       = min(100, m["kg_density"] * 20)
        s_conf     = m["avg_confidence"] * 100
        s_bloat    = max(0, 100 - m["memory_bloat_ratio"] * 150)
        s_contra   = max(0, 100 - m["contradiction_density"] * 500)
        s_hypo     = min(100, m["hypothesis_rate"] * 1000)
        s_cache    = m.get("cache_efficiency", 0.5) * 100   # v4
        s_energy   = max(0, 100 - m.get("energy_per_cycle", 0) * 40)  # v4

        m["architecture_score"] = round(
            s_error  * 0.25 +
            s_kg     * 0.15 +
            s_conf   * 0.15 +
            s_bloat  * 0.12 +
            s_contra * 0.10 +
            s_hypo   * 0.05 +
            s_cache  * 0.10 +  # v4
            s_energy * 0.08,   # v4
            2
        )

        conn.close()

        # ── Paso 4: métricas del LanguageEngine ───────────────────────
        self._collect_engine_metrics(m)

        # ── Paso 4: métricas del CollapseGuard ────────────────────────
        self._collect_collapse_metrics(m)

        m["collected_at"] = datetime.now().isoformat()
        return m

    def _collect_energy_metrics(self, cursor, m: dict):
        """Reads energy and latency stats from energy_log (last 24h)."""
        try:
            cursor.execute("""
                SELECT AVG(latency_ms), AVG(energy_estimate),
                       SUM(cache_hits), SUM(cache_misses),
                       AVG(CASE WHEN inference_steps >= 3 THEN 1.0 ELSE 0.0 END)
                FROM energy_log
                WHERE timestamp >= datetime('now','-24 hours')
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                hits   = row[2] or 0
                misses = row[3] or 0
                m["reasoning_latency_avg"] = round(row[0] or 0.0, 1)
                m["energy_per_cycle"]      = round(row[1] or 0.0, 3)
                m["cache_efficiency"]      = round(hits / max(1, hits + misses), 4)
                m["inference_depth_waste"] = round(row[4] or 0.0, 4)
            else:
                m["reasoning_latency_avg"] = 0.0
                m["cache_efficiency"]      = 0.5
                m["energy_per_cycle"]      = 0.0
                m["inference_depth_waste"] = 0.0
        except Exception:
            # energy_log may not exist yet
            m["reasoning_latency_avg"] = 0.0
            m["cache_efficiency"]      = 0.5
            m["energy_per_cycle"]      = 0.0
            m["inference_depth_waste"] = 0.0


    def _collect_engine_metrics(self, m: dict):
        """
        Paso 4: obtiene metricas del LanguageEngine y las inyecta en m.
        Si el engine no esta disponible, rellena con defaults neutros.
        """
        try:
            from language_engine import get_language_engine
            engine = get_language_engine()
            zones  = engine.report_weak_zones()
            m.update(zones)

            # Ajustar architecture_score con penalizacion por fallback rate
            fallback = zones.get("engine_fallback_rate", 0.0)
            if fallback > 0.0 and "architecture_score" in m:
                penalty = fallback * 15   # hasta -15 pts si todo cae al fallback
                m["architecture_score"] = round(
                    max(0.0, m["architecture_score"] - penalty), 2
                )
        except Exception:
            # Engine no disponible o sin requests todavia — defaults neutros
            m.setdefault("engine_fallback_rate",   0.0)
            m.setdefault("engine_cache_hit_rate",  0.0)
            m.setdefault("engine_llm_avoided_pct", 0.0)
            m.setdefault("engine_symbolic_rate",   0.0)
            m.setdefault("engine_total_requests",  0)

    def _collect_collapse_metrics(self, m: dict):
        """
        Paso 4: obtiene el reporte del ModelCollapseGuard y lo inyecta en m.
        Convierte risk_level a un score numerico para el DiagnosticEngine.
        """
        try:
            from model_collapse_guard import ModelCollapseGuard
            guard  = ModelCollapseGuard(self.db)
            report = guard.get_collapse_report()

            risk_map = {"low": 0.0, "medium": 0.5, "high": 1.0}
            m["collapse_risk_score"]   = risk_map.get(report["risk_level"], 0.0)
            m["collapse_semantic_sim"] = report.get("semantic_score", 0.0)
            dominant = report.get("dominant_labels", [])
            m["collapse_dominant_pct"] = dominant[0]["pct"] if dominant else 0.0
            m["collapse_events_24h"]   = len(report.get("events_24h", []))
        except Exception:
            m.setdefault("collapse_risk_score",   0.0)
            m.setdefault("collapse_semantic_sim", 0.0)
            m.setdefault("collapse_dominant_pct", 0.0)
            m.setdefault("collapse_events_24h",   0)


# ══════════════════════════════════════════════════════════════════════
# 2. TREND ANALYZER — detects degradation trends before crisis
# ══════════════════════════════════════════════════════════════════════

class TrendAnalyzer:
    """
    v4 NEW: Analyzes metric trends across recent evaluations.

    Detects:
    - Monotonically declining architecture_score
    - Steadily increasing error_rate_7d
    - Growing memory bloat over time
    - Cache efficiency declining

    Returns trend diagnoses with severity based on slope.
    """

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def analyze_trends(self, n_evals: int = 5) -> List[dict]:
        """Reads last N evaluations and returns trend-based diagnoses."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT metrics FROM architecture_evaluations
            ORDER BY timestamp DESC LIMIT ?
        """, (n_evals,))
        rows = c.fetchall()
        conn.close()

        if len(rows) < 3:
            return []  # Not enough history to detect trends

        # Parse metrics in chronological order
        history = []
        for row in reversed(rows):
            try:
                history.append(json.loads(row[0]))
            except Exception:
                pass

        if len(history) < 3:
            return []

        trends = []

        # ── Score trend ────────────────────────────────────────────────
        scores = [h.get("architecture_score", 50) for h in history]
        slope  = self._linear_slope(scores)
        if slope < -3.0:
            sev = "critical" if slope < -6.0 else "high"
            trends.append({
                "key":         "score_declining_trend",
                "severity":    sev,
                "severity_n":  SEVERITY[sev],
                "title":       "Architecture score declining across evaluations",
                "description": f"Score trend: {slope:+.2f} pts/eval over last {len(scores)} evaluations. "
                               f"From {scores[0]:.1f} to {scores[-1]:.1f}.",
                "metric":      f"score_slope = {slope:.2f}",
                "category":    "trend",
            })

        # ── Error rate trend ───────────────────────────────────────────
        errors = [h.get("error_rate_7d", 0) for h in history]
        err_slope = self._linear_slope(errors)
        if err_slope > 0.05:
            trends.append({
                "key":         "error_rate_rising_trend",
                "severity":    "high",
                "severity_n":  SEVERITY["high"],
                "title":       "Error rate rising over time",
                "description": f"7-day error rate increasing by {err_slope:+.3f}/eval. "
                               f"Current: {errors[-1]:.1%}. Projected to reach critical in "
                               f"{max(1, int((0.55 - errors[-1]) / err_slope))} evaluations.",
                "metric":      f"error_rate_slope = {err_slope:.4f}",
                "category":    "trend",
            })

        # ── Cache efficiency trend ─────────────────────────────────────
        caches = [h.get("cache_efficiency", 0.5) for h in history]
        cache_slope = self._linear_slope(caches)
        if cache_slope < -0.04 and history[-1].get("cache_efficiency", 0.5) < 0.5:
            trends.append({
                "key":         "cache_declining_trend",
                "severity":    "medium",
                "severity_n":  SEVERITY["medium"],
                "title":       "Cache efficiency declining",
                "description": f"Cache hit rate falling at {cache_slope:+.3f}/eval. "
                               f"Currently at {caches[-1]:.0%}. Embedding recomputation cost rising.",
                "metric":      f"cache_slope = {cache_slope:.4f}",
                "category":    "trend",
            })

        return trends

    @staticmethod
    def _linear_slope(values: list) -> float:
        """Simple linear regression slope over index → value pairs."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den > 0 else 0.0


# ══════════════════════════════════════════════════════════════════════
# 3. FATIGUE ADVISOR — gates diagnostic depth by fatigue level
# ══════════════════════════════════════════════════════════════════════

class FatigueAdvisor:
    """
    v4 NEW: Maps the system's current fatigue score to diagnostic strategy.

    Fatigue score comes from Cognia's FatigueMonitor.
    If not available, defaults to 'low' (full diagnostics).

    Behaviors:
      low      → Full diagnostics + trend analysis + module proposals
      moderate → Skip energy metrics + trend analysis; param proposals only
      high     → Minimal check; only critical threshold violations
      critical → Only one check: propose an ArchitecturalRelief module
    """

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def get_fatigue_level(self, cognia_instance=None) -> Tuple[str, float]:
        """Returns (level_name, fatigue_score)."""
        if cognia_instance is not None:
            try:
                score = float(cognia_instance.fatigue.score)
                for level, (lo, hi) in FATIGUE_LEVELS.items():
                    if lo <= score < hi:
                        return level, score
                return "critical", score
            except (AttributeError, TypeError, ValueError):
                pass

        # Fallback: estimate from DB activity in last hour
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE timestamp >= datetime('now','-1 hour')
        """)
        recent_interactions = c.fetchone()[0]
        conn.close()

        # More than 30 interactions/hour = moderate load estimate
        if recent_interactions > 60:
            return "high", 0.65
        elif recent_interactions > 30:
            return "moderate", 0.45
        return "low", 0.15

    def should_run_diagnostics(self, fatigue_level: str) -> dict:
        """Returns a dict of flags controlling diagnostic scope."""
        return {
            "full_diagnostics":     fatigue_level == "low",
            "param_proposals":      fatigue_level in ("low", "moderate"),
            "module_proposals":     fatigue_level == "low",
            "trend_analysis":       fatigue_level == "low",
            "energy_metrics":       fatigue_level in ("low", "moderate"),
            "run_at_all":           fatigue_level != "critical",
            "emergency_only":       fatigue_level == "critical",
        }


# ══════════════════════════════════════════════════════════════════════
# 4. DIAGNOSTIC ENGINE — detects structural problems
# ══════════════════════════════════════════════════════════════════════

class DiagnosticEngine:
    """
    Analyzes metrics and returns sorted list of diagnoses.

    v4 adds:
      D10: High reasoning latency
      D11: Low cache efficiency
      D12: High energy per cycle
      D13: Inference depth waste (hitting max steps too often)
      D14: Working memory pressure
      D15: Critical fatigue (architectural relief needed)
    """

    def __init__(self, thresholds: dict = None):
        self.thresholds = thresholds or THRESHOLDS

    def diagnose(self, metrics: dict, scope: dict = None) -> List[dict]:
        """
        Evaluates metrics and returns diagnoses ordered by severity.
        scope: dict from FatigueAdvisor.should_run_diagnostics()
        """
        if scope is None:
            scope = {"full_diagnostics": True, "emergency_only": False}

        diagnoses = []
        t = self.thresholds

        # ── Always-run checks ──────────────────────────────────────────
        er = metrics.get("error_rate_7d", 0)
        if er >= t["error_rate_critical"]:
            diagnoses.append(self._d("high_error_rate", "critical", "Critical error rate",
                f"{er:.0%} of decisions in last 7 days were wrong. Learning is failing.",
                f"error_rate_7d = {er:.3f}", t["error_rate_critical"], "learning"))
        elif er >= t["error_rate_high"]:
            diagnoses.append(self._d("elevated_error_rate", "high", "Elevated error rate",
                f"Error rate {er:.0%} — may indicate conflicting concepts or stale semantic memory.",
                f"error_rate_7d = {er:.3f}", t["error_rate_high"], "learning"))

        if scope.get("emergency_only"):
            diagnoses.sort(key=lambda x: x["severity_n"], reverse=True)
            return diagnoses

        # ── Standard checks ───────────────────────────────────────────
        br = metrics.get("memory_bloat_ratio", 0)
        if br >= t["memory_bloat_ratio"]:
            diagnoses.append(self._d("memory_bloat", "high", "Episodic memory bloated",
                f"{br:.0%} of episodes are forgotten but still occupy disk. Decay rate may be too slow.",
                f"memory_bloat_ratio = {br:.3f}", t["memory_bloat_ratio"], "memory"))

        cd = metrics.get("contradiction_density", 0)
        if cd >= t["contradiction_density"]:
            n = metrics.get("contradictions_pending", 0)
            diagnoses.append(self._d("contradiction_overload", "high",
                "Contradiction accumulation",
                f"{n} unresolved contradictions ({cd:.0%} of active memory). "
                "Auto-resolution may be disabled or insufficient.",
                f"contradiction_density = {cd:.3f}", t["contradiction_density"], "reasoning"))

        ki = metrics.get("kg_isolation", 0)
        if ki >= t["kg_isolation"] and metrics.get("concept_count", 0) > 10:
            diagnoses.append(self._d("kg_isolation", "medium", "Knowledge Graph poorly connected",
                f"{ki:.0%} of concepts have no edges. Inference and spreading activation are limited.",
                f"kg_isolation = {ki:.3f}", t["kg_isolation"], "knowledge_graph"))

        hr = metrics.get("hypothesis_rate", 0)
        if hr < t["low_hypothesis_rate"] and metrics.get("active_memories", 0) > 20:
            diagnoses.append(self._d("low_creativity", "medium", "Low hypothesis generation",
                f"Only {metrics.get('hypothesis_count',0)} hypotheses ({hr:.1%} of memory). "
                "The system is not exploring concept connections.",
                f"hypothesis_rate = {hr:.4f}", t["low_hypothesis_rate"], "creativity"))

        ac = metrics.get("avg_confidence", 0)
        if ac < 0.40 and metrics.get("active_memories", 0) > 15:
            diagnoses.append(self._d("low_avg_confidence", "medium", "Low average episode confidence",
                f"Mean confidence {ac:.0%} — high uncertainty across most memories.",
                f"avg_confidence = {ac:.3f}", 0.40, "memory"))

        ul = metrics.get("unlabeled_ratio", 0)
        if ul > 0.60 and metrics.get("active_memories", 0) > 20:
            diagnoses.append(self._d("unlabeled_noise", "low", "High unlabeled episode ratio",
                f"{ul:.0%} of active episodes lack semantic labels. Concept learning may be impaired.",
                f"unlabeled_ratio = {ul:.3f}", 0.60, "learning"))

        fnr = metrics.get("feedback_negative_ratio", 0)
        total_fb = metrics.get("feedback_positive", 0) + metrics.get("feedback_negative", 0)
        if fnr > 0.40 and total_fb >= 5:
            diagnoses.append(self._d("high_negative_feedback", "high",
                "Excessive negative user feedback",
                f"{fnr:.0%} of rated responses received negative feedback (n={total_fb}). "
                "Retrieved context may not be relevant.",
                f"feedback_negative_ratio = {fnr:.3f}", 0.40, "quality"))

        sc = metrics.get("sleep_cycles_7d", 0)
        if sc == 0 and metrics.get("active_memories", 0) > 30:
            diagnoses.append(self._d("no_sleep_cycles", "low", "No consolidation cycles recently",
                "No sleep cycles in 7 days — episodic memory has not been consolidated into concepts.",
                f"sleep_cycles_7d = {sc}", 1, "memory"))

        # ── v4: Energy & performance checks ──────────────────────────
        if scope.get("energy_metrics", True):
            latency = metrics.get("reasoning_latency_avg", 0)
            if latency > t["high_reasoning_latency_ms"] and latency > 0:
                diagnoses.append(self._d("high_reasoning_latency", "high",
                    "High average reasoning latency",
                    f"Average response latency {latency:.0f}ms exceeds target {t['high_reasoning_latency_ms']}ms. "
                    "Retrieval depth or embedding recomputation may be excessive.",
                    f"reasoning_latency_avg = {latency:.1f}ms", t["high_reasoning_latency_ms"], "performance"))

            cache_eff = metrics.get("cache_efficiency", 0.5)
            if cache_eff < t["low_cache_efficiency"] and metrics.get("total_memories", 0) > 10:
                diagnoses.append(self._d("low_cache_efficiency", "medium",
                    "Low embedding cache efficiency",
                    f"Cache hit rate {cache_eff:.0%} — embeddings are being recomputed unnecessarily. "
                    "Cache size may be too small or invalidation too aggressive.",
                    f"cache_efficiency = {cache_eff:.3f}", t["low_cache_efficiency"], "performance"))

            energy = metrics.get("energy_per_cycle", 0)
            if energy > t["energy_per_cycle_high"] and energy > 0:
                diagnoses.append(self._d("high_energy_per_cycle", "medium",
                    "Energy per reasoning cycle too high",
                    f"Energy estimate {energy:.2f} units/cycle exceeds target {t['energy_per_cycle_high']}. "
                    "Reasoning chain may contain redundant steps.",
                    f"energy_per_cycle = {energy:.3f}", t["energy_per_cycle_high"], "energy"))

            idw = metrics.get("inference_depth_waste", 0)
            if idw > t["inference_depth_waste"]:
                diagnoses.append(self._d("inference_depth_waste", "medium",
                    "Inference chain hitting depth limit too often",
                    f"{idw:.0%} of reasoning cycles reach the max inference step limit. "
                    "Either the limit is too low or reasoning loops are occurring.",
                    f"inference_depth_waste = {idw:.3f}", t["inference_depth_waste"], "reasoning"))

        # ── Paso 4: Engine diagnostics ───────────────────────────────
        fallback = metrics.get("engine_fallback_rate", 0.0)
        if fallback > 0.20 and metrics.get("engine_total_requests", 0) >= 10:
            diagnoses.append(self._d(
                "engine_high_fallback", "high",
                "Language Engine falling back too often",
                f"{fallback:.0%} of responses reached Stage 5 fallback "
                f"(target < 20%). UMBRAL_CONFIANZA may be too high or "
                f"symbolic knowledge is insufficient for current query types.",
                f"engine_fallback_rate = {fallback:.3f}", 0.20, "engine",
            ))

        eng_cache = metrics.get("engine_cache_hit_rate", 0.5)
        if eng_cache < 0.15 and metrics.get("engine_total_requests", 0) >= 20:
            diagnoses.append(self._d(
                "engine_low_cache", "medium",
                "Language Engine semantic cache underperforming",
                f"Engine cache hit rate {eng_cache:.0%} (target > 15%). "
                f"Cache TTL may be too short or CACHE_SIMILARITY threshold "
                f"too strict, causing unnecessary LLM calls.",
                f"engine_cache_hit_rate = {eng_cache:.3f}", 0.15, "engine",
            ))

        collapse = metrics.get("collapse_risk_score", 0.0)
        if collapse >= 0.5:
            dom_pct = metrics.get("collapse_dominant_pct", 0.0)
            severity_level = "high" if collapse >= 1.0 else "medium"
            diagnoses.append(self._d(
                "learning_collapse_risk", severity_level,
                "Model collapse risk detected",
                f"CollapseGuard reports {'high' if collapse >= 1.0 else 'medium'} risk. "
                f"Dominant label represents {dom_pct:.0%} of recent corrections. "
                f"Diversity of training labels needs attention.",
                f"collapse_risk_score = {collapse:.1f}", 0.5, "learning",
            ))

        diagnoses.sort(key=lambda x: x["severity_n"], reverse=True)
        return diagnoses

    @staticmethod
    def _d(key, severity, title, description, metric, threshold, category) -> dict:
        return {
            "key":         key,
            "severity":    severity,
            "severity_n":  SEVERITY[severity],
            "title":       title,
            "description": description,
            "metric":      metric,
            "threshold":   threshold,
            "category":    category,
        }


# ══════════════════════════════════════════════════════════════════════
# 5. META-LEARNING TRACKER — learns which changes actually help
# ══════════════════════════════════════════════════════════════════════

class MetaLearningTracker:
    """
    v4 NEW: Tracks the outcome of every applied change.

    After a change is applied, the tracker:
    1. Records the architecture_score before the change
    2. On the next evaluation (N interactions later), records score after
    3. Computes score_delta and classifies outcome:
       - positive:  delta > +2
       - neutral:   -2 <= delta <= +2
       - negative:  delta < -2

    StrategySelector uses this data to predict ROI for future proposals.
    """

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def record_change(self, proposal_id: int, diagnosis_key: str,
                      param_key: Optional[str], change_type: str,
                      score_before: float, eval_before_id: int):
        """Called immediately after a change is applied."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO meta_learning_outcomes
            (timestamp, proposal_id, diagnosis_key, param_key, change_type,
             score_before, eval_before_id, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (datetime.now().isoformat(), proposal_id, diagnosis_key,
              param_key, change_type, score_before, eval_before_id))
        conn.commit()
        conn.close()

    def update_outcomes(self, current_score: float, current_eval_id: int):
        """
        Called at each evaluation. Updates 'pending' outcomes where
        at least one evaluation has passed since the change.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, score_before FROM meta_learning_outcomes
            WHERE outcome = 'pending' AND eval_before_id < ?
        """, (current_eval_id,))
        pending = c.fetchall()

        for row_id, score_before in pending:
            delta   = current_score - score_before
            outcome = "positive" if delta > 2.0 else ("negative" if delta < -2.0 else "neutral")
            c.execute("""
                UPDATE meta_learning_outcomes
                SET score_after=?, score_delta=?, outcome=?, eval_after_id=?
                WHERE id=?
            """, (current_score, delta, outcome, current_eval_id, row_id))

        conn.commit()
        conn.close()

    def get_success_rate(self, diagnosis_key: str, window: int = 10) -> float:
        """
        Returns the fraction of changes for this diagnosis_key that had
        a positive outcome, over the last `window` outcomes.
        Returns 0.5 if no data (assume neutral prior).
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT outcome FROM meta_learning_outcomes
            WHERE diagnosis_key = ? AND outcome != 'pending'
            ORDER BY timestamp DESC LIMIT ?
        """, (diagnosis_key, window))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return 0.5  # neutral prior

        positive = sum(1 for r in rows if r[0] == "positive")
        return round(positive / len(rows), 3)

    def get_meta_summary(self) -> dict:
        """Summary of all meta-learning data."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT diagnosis_key,
                   COUNT(*) as total,
                   SUM(CASE WHEN outcome='positive' THEN 1 ELSE 0 END) as pos,
                   AVG(score_delta) as avg_delta
            FROM meta_learning_outcomes
            WHERE outcome != 'pending'
            GROUP BY diagnosis_key
            ORDER BY avg_delta DESC
        """)
        rows = c.fetchall()
        conn.close()

        return {
            row[0]: {
                "total_outcomes": row[1],
                "positive_count": row[2],
                "success_rate":   round(row[2] / max(1, row[1]), 3),
                "avg_score_delta": round(row[3] or 0.0, 2),
            }
            for row in rows
        }


# ══════════════════════════════════════════════════════════════════════
# 6. STRATEGY SELECTOR — ranks proposals by predicted ROI
# ══════════════════════════════════════════════════════════════════════

class StrategySelector:
    """
    v4 NEW: Uses MetaLearningTracker data to score and rank proposals.

    ROI score = base_severity_weight * historical_success_rate * reversibility_bonus

    High ROI → present first to user for approval.
    Low ROI  → still presented, but ranked lower.
    """

    def __init__(self, meta_tracker: MetaLearningTracker):
        self.meta = meta_tracker

    def score_proposal(self, proposal: dict) -> float:
        """Returns a 0.0–1.0 ROI score for a proposal."""
        diagnosis_key = proposal.get("diagnosis_key", "")
        severity_n    = proposal.get("diagnosis", {}).get("severity_n", 1)
        reversible    = proposal.get("reversible", True)

        severity_weight    = (severity_n + 1) / 4.0       # 0.25–1.0
        historical_success = self.meta.get_success_rate(diagnosis_key)
        reversibility_bonus = 1.0 if reversible else 0.7

        roi = severity_weight * historical_success * reversibility_bonus
        return round(min(1.0, roi), 3)

    def rank_proposals(self, proposals: list) -> list:
        """Returns proposals sorted by predicted ROI, highest first."""
        for p in proposals:
            p["predicted_roi"] = self.score_proposal(p)
        return sorted(proposals, key=lambda x: x["predicted_roi"], reverse=True)


# ══════════════════════════════════════════════════════════════════════
# 7. MODULE PROPOSER — proposes entirely new cognitive modules
# ══════════════════════════════════════════════════════════════════════

class ModuleProposer:
    """
    v4 NEW: Proposes new cognitive modules when capability gaps are detected.

    Each module proposal includes:
    - purpose and expected benefit
    - computational cost and energy impact
    - pseudocode description
    - integration points with existing modules
    - triggering diagnosis key

    These proposals always have proposal_type = 'new_module' and
    are always marked reversible=False (they require implementation).
    They go through the same approval flow as parameter changes.
    """

    MODULE_CATALOG = {
        # Triggered by: high_error_rate + no meta-learning history
        "high_error_rate": {
            "module_name":   "MetaLearningController",
            "title":         "New module: MetaLearningController",
            "problem":       "Error rate is high and no meta-learning feedback loop exists to "
                             "detect which types of errors recur.",
            "modification":  "Add a MetaLearningController that tracks error patterns, groups "
                             "them by topic/context, and adjusts retrieval strategy for those contexts.",
            "why_better":    "A dedicated controller can detect that errors in topic X are "
                             "systematic and pre-fetch more context for X-related queries, "
                             "reducing recurrence without increasing global retrieval cost.",
            "risks":         "Topic classification requires embedding comparisons. If topics are "
                             "misclassified, the wrong retrieval strategy is applied.",
            "impact":        "+5-10% embedding cost during retrieval for tracked error topics.",
            "energy_impact": "medium",
            "pseudocode": """
class MetaLearningController:
    def __init__(self, db):
        self.error_patterns = {}  # topic → error_count

    def on_error(self, query_embedding, decision_id):
        topic = self._classify_topic(query_embedding)
        self.error_patterns[topic] = self.error_patterns.get(topic, 0) + 1

    def suggest_retrieval_depth(self, query_embedding) -> int:
        topic = self._classify_topic(query_embedding)
        errors = self.error_patterns.get(topic, 0)
        # More errors in this topic → retrieve more episodes
        return min(10, 3 + errors // 2)

    def _classify_topic(self, embedding) -> str:
        # Nearest concept in semantic_memory
        ...
            """,
            "integration_points": [
                "decision_log.on_error() → MetaLearningController.on_error()",
                "EpisodicRetriever.retrieve() → ask controller for depth",
                "AttentionSystem weights → override per-topic if error_count > threshold",
            ],
        },

        # Triggered by: low_cache_efficiency or high_energy_per_cycle
        "low_cache_efficiency": {
            "module_name":   "MemoryCompressionEngine",
            "title":         "New module: MemoryCompressionEngine",
            "problem":       "Low cache hit rate causes repeated embedding recomputation, "
                             "wasting energy on already-seen content.",
            "modification":  "Add a MemoryCompressionEngine that maintains a tiered cache: "
                             "hot (last 50 embeddings, in-memory), warm (LRU-512, in-memory), "
                             "cold (disk-backed). Also compresses rarely-accessed embeddings "
                             "using PCA to reduce vector size.",
            "why_better":    "Tiered cache matches access patterns better than a flat LRU. "
                             "PCA compression reduces memory footprint for cold entries by ~50%.",
            "risks":         "PCA compression is lossy — similarity scores for cold entries "
                             "will be slightly less accurate. Compression adds a one-time CPU cost.",
            "impact":        "RAM -20-40% for embedding cache. CPU -15-30% for repeated retrieval.",
            "energy_impact": "high_benefit",
            "pseudocode": """
class MemoryCompressionEngine:
    def __init__(self, hot_size=50, warm_size=512):
        self.hot  = {}   # {text_hash: embedding}  — LRU dict
        self.warm = {}   # {text_hash: embedding}  — LRU dict
        self.cold = {}   # {text_hash: compressed} — disk-backed

    def get(self, text_hash) -> Optional[np.ndarray]:
        if text_hash in self.hot:  return self.hot[text_hash]
        if text_hash in self.warm: self._promote(text_hash); return self.warm[text_hash]
        if text_hash in self.cold: return self._decompress(self.cold[text_hash])
        return None

    def put(self, text_hash, embedding):
        self._add_to_hot(text_hash, embedding)
        self._evict_if_needed()

    def compress_cold(self):
        # Move warm entries not accessed in 24h to cold with PCA
        ...
            """,
            "integration_points": [
                "EmbeddingEngine.embed() → check MemoryCompressionEngine.get() first",
                "EmbeddingEngine.embed() → call put() after computing",
                "Nightly maintenance → call compress_cold()",
            ],
        },

        # Triggered by: low_creativity or low_hypothesis_rate
        "low_creativity": {
            "module_name":   "CuriosityDriver",
            "title":         "New module: CuriosityDriver",
            "problem":       "Hypothesis generation rate is critically low — the system "
                             "is not exploring conceptual connections proactively.",
            "modification":  "Add a CuriosityDriver that periodically samples pairs of "
                             "semantically distant but structurally connected concepts and "
                             "proposes bridge hypotheses for the system to evaluate.",
            "why_better":    "Rather than waiting for user queries to trigger hypotheses, "
                             "the driver actively explores the knowledge graph for "
                             "underexplored regions, increasing hypothesis diversity.",
            "risks":         "May generate low-quality hypotheses if concepts are connected "
                             "by noise edges. Adds background computation.",
            "impact":        "+5% CPU in consolidation cycles. No RAM impact.",
            "energy_impact": "low",
            "pseudocode": """
class CuriosityDriver:
    def __init__(self, kg, hypotheses, interval=10):
        self.kg          = kg
        self.hypotheses  = hypotheses
        self.interval    = interval  # interactions between curiosity cycles

    def run_cycle(self):
        # Find concept pairs: connected in KG but semantically distant
        candidates = self._find_bridge_candidates(top_k=5)
        for concept_a, concept_b, path in candidates:
            hypothesis = self._generate_bridge_hypothesis(concept_a, concept_b, path)
            if hypothesis.confidence > MIN_CONFIDENCE:
                self.hypotheses.add(hypothesis)

    def _find_bridge_candidates(self, top_k):
        # BFS on KG, score by (path_length / semantic_similarity)
        # High score = structurally close but semantically distant = interesting
        ...
            """,
            "integration_points": [
                "Cognia.tick() → CuriosityDriver.maybe_run(interaction_count)",
                "HypothesisEngine → CuriosityDriver feeds hypotheses in",
                "KnowledgeGraph → CuriosityDriver reads edges",
            ],
        },

        # Triggered by: high_energy_per_cycle
        "high_energy_per_cycle": {
            "module_name":   "EnergyOptimizer",
            "title":         "New module: EnergyOptimizer",
            "problem":       "Energy per reasoning cycle is above target. "
                             "Reasoning steps may be redundant or overly deep.",
            "modification":  "Add an EnergyOptimizer that profiles each reasoning cycle, "
                             "identifies the costliest steps, and proposes pruning strategies "
                             "such as early exit, step caching, or lightweight fallback paths.",
            "why_better":    "By tracking which reasoning steps are most costly and least "
                             "impactful, the optimizer can selectively skip low-value steps "
                             "while preserving output quality.",
            "risks":         "Pruning reasoning steps may reduce answer quality for edge cases. "
                             "Profiling adds a small overhead per cycle.",
            "impact":        "Target: -20-40% energy per cycle. CPU overhead: +2% for profiling.",
            "energy_impact": "high_benefit",
            "pseudocode": """
class EnergyOptimizer:
    def __init__(self, energy_log, budget=1.0):
        self.energy_log = energy_log
        self.budget     = budget
        self.step_costs = {}  # step_name → avg_cost

    def profile_cycle(self, steps: List[ReasoningStep]):
        for step in steps:
            cost = step.end_time - step.start_time
            self.step_costs[step.name] = (
                0.9 * self.step_costs.get(step.name, cost) + 0.1 * cost
            )

    def should_run_step(self, step_name, current_budget_used) -> bool:
        expected_cost = self.step_costs.get(step_name, 0.1)
        return current_budget_used + expected_cost <= self.budget

    def suggest_simplifications(self) -> List[str]:
        # Return steps with high cost and low correlation to answer quality
        ...
            """,
            "integration_points": [
                "ReasoningEngine.run_cycle() → EnergyOptimizer.profile_cycle()",
                "ReasoningEngine.run_step() → check should_run_step() first",
                "SelfArchitect → reads EnergyOptimizer.suggest_simplifications()",
            ],
        },

        # Triggered by: kg_isolation
        "kg_isolation": {
            "module_name":   "PatternDetector",
            "title":         "New module: PatternDetector",
            "problem":       "Knowledge Graph has low connectivity — many concepts are islands "
                             "with no edges, making inference and spreading activation ineffective.",
            "modification":  "Add a PatternDetector that runs during consolidation cycles and "
                             "detects co-occurrence patterns across episodes to infer new KG edges.",
            "why_better":    "Instead of relying only on explicitly stated relationships, "
                             "the detector finds implicit patterns (e.g., concept A often "
                             "appears with concept B in similar contexts) and proposes edges.",
            "risks":         "Co-occurrence patterns may be spurious. Edges need a minimum "
                             "support count before being added to avoid noise.",
            "impact":        "+10% CPU during consolidation. KG edge count increases 20-50%.",
            "energy_impact": "medium",
            "pseudocode": """
class PatternDetector:
    def __init__(self, db, min_support=3, min_confidence=0.4):
        self.db             = db
        self.min_support    = min_support
        self.min_confidence = min_confidence

    def detect_co_occurrences(self):
        # Load recent episodes, extract concept sets per episode
        # Find pairs (A, B) appearing together in >= min_support episodes
        # If confidence(A→B) >= min_confidence, propose edge A→co-occurs-with→B
        episodes = self._load_recent_episodes(window=100)
        concept_sets = [self._extract_concepts(e) for e in episodes]
        candidates = self._frequent_pairs(concept_sets)
        new_edges = [(a, b, "co-occurs-with", support)
                     for a, b, support in candidates if support >= self.min_support]
        return new_edges

    def run(self):
        new_edges = self.detect_co_occurrences()
        self._add_edges_to_kg(new_edges)
            """,
            "integration_points": [
                "SleepCycle.run() → PatternDetector.run()",
                "KnowledgeGraph → PatternDetector reads and writes edges",
                "SemanticMemory → PatternDetector reads concept labels",
            ],
        },
    }

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def _already_pending(self, module_name: str) -> bool:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM architecture_proposals
            WHERE proposal_type='new_module'
              AND title LIKE ?
              AND status='pending'
        """, (f"%{module_name}%",))
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def propose_modules(self, diagnoses: List[dict], eval_id: int) -> List[dict]:
        """
        Generates new-module proposals for diagnoses that lack a param fix.
        """
        proposals = []
        count = 0
        for diag in diagnoses:
            if count >= MAX_MODULE_PROPOSALS_PER_EVAL:
                break
            key = diag["key"]
            template = self.MODULE_CATALOG.get(key)
            if not template:
                continue
            if self._already_pending(template["module_name"]):
                continue

            proposal = {
                "evaluation_id": eval_id,
                "diagnosis_key": key,
                "diagnosis":     diag,
                "proposal_type": "new_module",
                "title":         template["title"],
                "problem":       template["problem"],
                "modification":  template["modification"],
                "why_better":    template["why_better"],
                "risks":         template["risks"],
                "impact":        template["impact"],
                "energy_impact": template["energy_impact"],
                "reversible":    False,
                "change_type":   "new_module",
                "param_key":     None,
                "param_current": None,
                "param_new":     None,
                "pseudocode":    template["pseudocode"],
                "integration_points": template["integration_points"],
            }
            proposals.append(proposal)
            count += 1
        return proposals


# ══════════════════════════════════════════════════════════════════════
# 8. CHANGE PROPOSER — parameter and module modification proposals
# ══════════════════════════════════════════════════════════════════════

class ChangeProposer:
    """
    Generates concrete parameter change proposals.
    Same catalog structure as v3, extended with v4 diagnostic keys.
    """

    PROPOSALS = {
        "high_error_rate": [
            {
                "title":       "Reduce consolidation interval",
                "modification":"Lower consolidation_interval from {current} to {new}",
                "why_better":  "More frequent consolidations reinforce correct concepts faster.",
                "risks":       "+15% CPU during consolidations. May entrench incorrect data faster.",
                "impact":      "CPU +15% during consolidation windows.",
                "reversible":  True,
                "param_key":   "consolidation_interval",
                "param_fn":    lambda v: max(4, int(v * 0.6)),
            },
            {
                "title":       "Increase semantic attention weight",
                "modification":"Raise attention_w_semantic from {current} to {new}",
                "why_better":  "Prioritize semantic similarity over recency to find more relevant memories.",
                "risks":       "May ignore emotionally important but semantically distant memories.",
                "impact":      "No memory or CPU impact (same formula).",
                "reversible":  True,
                "param_key":   "attention_w_semantic",
                "param_fn":    lambda v: min(0.65, v + 0.10),
            },
        ],
        "elevated_error_rate": [
            {
                "title":       "Lower attention threshold",
                "modification":"Lower attention_threshold from {current} to {new}",
                "why_better":  "Retrieve more episodes per query, increasing chance of finding correct context.",
                "risks":       "May saturate LLM context with irrelevant memories. +5-10% retrieval CPU.",
                "impact":      "CPU +5-10% per retrieval. No RAM impact.",
                "reversible":  True,
                "param_key":   "attention_threshold",
                "param_fn":    lambda v: max(0.10, v - 0.05),
            },
        ],
        "memory_bloat": [
            {
                "title":       "Increase forgetting decay rate",
                "modification":"Raise forgetting_decay_rate from {current} to {new}",
                "why_better":  "Faster decay eliminates irrelevant episodes sooner, shrinking memory.",
                "risks":       "May forget important low-frequency episodes.",
                "impact":      "DB size -15-40% long term. Faster retrieval.",
                "reversible":  True,
                "param_key":   "forgetting_decay_rate",
                "param_fn":    lambda v: min(0.05, v * 1.4),
            },
            {
                "title":       "Physically purge forgotten low-importance episodes",
                "modification":"DELETE FROM episodic_memory WHERE forgotten=1 AND importance < 0.1",
                "why_better":  "Frees disk space and speeds all SQL queries.",
                "risks":       "Irreversible — deleted episodes cannot be recovered.",
                "impact":      "DB size reduction. Retrieval -20-50%.",
                "reversible":  False,
                "change_type": "sql_cleanup",
                "param_key":   None,
            },
        ],
        "contradiction_overload": [
            {
                "title":       "Raise forgetting threshold to resolve conflicts faster",
                "modification":"Raise forgetting_threshold from {current} to {new}",
                "why_better":  "Episodes in contradiction have reduced importance; a higher threshold "
                               "causes them to be forgotten sooner, resolving conflicts by attrition.",
                "risks":       "May forget the correct episode if its importance was underestimated.",
                "impact":      "No CPU impact. Active memory -5-15%.",
                "reversible":  True,
                "param_key":   "forgetting_threshold",
                "param_fn":    lambda v: min(0.55, v + 0.08),
            },
        ],
        "kg_isolation": [
            {
                "title":       "Reduce min word length for KG triple extraction",
                "modification":"Lower kg_bridge_min_length from {current} to {new}",
                "why_better":  "Shorter words increase the number of triples extracted per episode.",
                "risks":       "Short words are more ambiguous. May add noise to the KG.",
                "impact":      "KG edge count increases. Spreading activation slightly slower.",
                "reversible":  True,
                "param_key":   "kg_bridge_min_length",
                "param_fn":    lambda v: max(3, v - 1),
            },
        ],
        "low_creativity": [
            {
                "title":       "Lower minimum hypothesis confidence",
                "modification":"Lower hypothesis_confidence from {current} to {new}",
                "why_better":  "A lower threshold enables exploration of weaker concept connections.",
                "risks":       "May generate low-quality hypotheses with little empirical basis.",
                "impact":      "No CPU or RAM impact. Hypothesis table grows faster.",
                "reversible":  True,
                "param_key":   "hypothesis_confidence",
                "param_fn":    lambda v: max(0.15, v - 0.08),
            },
        ],
        "low_avg_confidence": [
            {
                "title":       "Increase spaced-repetition frequency",
                "modification":"Lower forgetting_interval from {current} to {new}",
                "why_better":  "More frequent reviews improve confidence through spaced repetition.",
                "risks":       "More CPU during review cycles. May reinforce incorrect beliefs.",
                "impact":      "CPU +10% during review cycles.",
                "reversible":  True,
                "param_key":   "forgetting_interval",
                "param_fn":    lambda v: max(8, int(v * 0.75)),
            },
        ],
        "high_negative_feedback": [
            {
                "title":       "Retrieve more context per query",
                "modification":"Lower attention_threshold from {current} to {new}",
                "why_better":  "More context gives the LLM more relevant information to generate better responses.",
                "risks":       "Larger context increases token cost and LLM response time by 10-20%.",
                "impact":      "LLM response time +10-20%. No RAM impact.",
                "reversible":  True,
                "param_key":   "attention_threshold",
                "param_fn":    lambda v: max(0.10, v - 0.05),
            },
        ],
        "no_sleep_cycles": [
            {
                "title":       "Reduce consolidation interval to force more sleep cycles",
                "modification":"Lower consolidation_interval from {current} to {new}",
                "why_better":  "More consolidations group episodic memory into semantic concepts more frequently.",
                "risks":       "Consolidations during active use can cause noticeable latency.",
                "impact":      "CPU +10-20% during consolidations.",
                "reversible":  True,
                "param_key":   "consolidation_interval",
                "param_fn":    lambda v: max(5, int(v * 0.7)),
            },
        ],
        "unlabeled_noise": [
            {
                "title":       "Recommendation: increase active labeling",
                "modification":"No automatic change. Action: use 'learn' command more actively to label episodes.",
                "why_better":  "Manual labeling creates accurate semantic anchors the system cannot safely auto-generate.",
                "risks":       "Automatic labeling without supervision would corrupt semantic memory.",
                "impact":      "No automated change. Human action required.",
                "reversible":  True,
                "change_type": "recommendation_only",
                "param_key":   None,
            },
        ],
        "attention_waste": [
            {
                "title":       "Raise attention threshold to filter before retrieval",
                "modification":"Raise attention_threshold from {current} to {new}",
                "why_better":  "Fewer episodes pass attention → fewer embedding comparisons → less wasted CPU.",
                "risks":       "May miss relevant memories with moderate similarity scores.",
                "impact":      "CPU -10-20% on retrieval. No RAM impact.",
                "reversible":  True,
                "param_key":   "attention_threshold",
                "param_fn":    lambda v: min(0.55, v + 0.07),
            },
        ],
        # v4 new keys
        "high_reasoning_latency": [
            {
                "title":       "Reduce max inference steps to cut latency",
                "modification":"Lower inference_max_steps from {current} to {new}",
                "why_better":  "Fewer inference steps directly reduce worst-case latency per cycle.",
                "risks":       "May miss multi-hop reasoning conclusions. Monitor error_rate after change.",
                "impact":      "Latency -10-25%. CPU proportionally reduced.",
                "reversible":  True,
                "param_key":   "inference_max_steps",
                "param_fn":    lambda v: max(2, int(v - 1)),
            },
        ],
        "low_cache_efficiency": [
            {
                "title":       "Double embedding cache size",
                "modification":"Raise embedding_cache_size from {current} to {new}",
                "why_better":  "A larger cache retains more embeddings in memory, reducing recomputation.",
                "risks":       "Higher RAM usage. On laptops with < 8GB RAM, monitor memory pressure.",
                "impact":      "RAM +50-100MB. CPU -15-25% on retrieval.",
                "reversible":  True,
                "param_key":   "embedding_cache_size",
                "param_fn":    lambda v: min(2048, int(v * 2)),
            },
        ],
        "high_energy_per_cycle": [
            {
                "title":       "Lower energy budget target to force optimizations",
                "modification":"Lower energy_budget_per_cycle from {current} to {new}",
                "why_better":  "A tighter budget causes the reasoning engine to skip low-value steps.",
                "risks":       "If budget is too low, important reasoning steps may be skipped.",
                "impact":      "CPU -10-20% per cycle. Slight answer quality reduction possible.",
                "reversible":  True,
                "param_key":   "energy_budget_per_cycle",
                "param_fn":    lambda v: max(0.5, v * 0.85),
            },
        ],
        "inference_depth_waste": [
            {
                "title":       "Increase max inference steps to prevent premature truncation",
                "modification":"Raise inference_max_steps from {current} to {new}",
                "why_better":  "If >50% of cycles hit the limit, the limit is too low. "
                               "Increasing it allows reasoning chains to complete naturally.",
                "risks":       "Higher inference depth increases latency. May cause timeout on complex queries.",
                "impact":      "Latency +10-20%. CPU proportionally higher.",
                "reversible":  True,
                "param_key":   "inference_max_steps",
                "param_fn":    lambda v: min(6, int(v + 1)),
            },
        ],
        # Trend-based keys
        "score_declining_trend": [
            {
                "title":       "Trigger immediate manual evaluation",
                "modification":"Recommendation: run '/api/architect/evaluar' and review all pending proposals.",
                "why_better":  "Architectural score has been declining across multiple evaluations. "
                               "A manual review may reveal compounding issues.",
                "risks":       "None — recommendation only.",
                "impact":      "None.",
                "reversible":  True,
                "change_type": "recommendation_only",
                "param_key":   None,
            },
        ],
        "error_rate_rising_trend": [
            {
                "title":       "Increase semantic weight preemptively",
                "modification":"Raise attention_w_semantic from {current} to {new}",
                "why_better":  "Getting ahead of rising error rates by improving retrieval relevance.",
                "risks":       "Same as semantic weight increase — may reduce emotional context.",
                "impact":      "No CPU or RAM impact.",
                "reversible":  True,
                "param_key":   "attention_w_semantic",
                "param_fn":    lambda v: min(0.60, v + 0.07),
            },
        ],
        "cache_declining_trend": [
            {
                "title":       "Preemptively increase cache size before efficiency hits critical",
                "modification":"Raise embedding_cache_size from {current} to {new}",
                "why_better":  "Cache efficiency is trending down — increasing size before it becomes critical.",
                "risks":       "RAM usage increase.",
                "impact":      "RAM +50MB. CPU -5-10% on retrieval.",
                "reversible":  True,
                "param_key":   "embedding_cache_size",
                "param_fn":    lambda v: min(1024, int(v * 1.5)),
            },
        ],
    }

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def _get_param(self, key: str) -> Optional[str]:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT value FROM architecture_params WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def _is_protected(self, key: str) -> bool:
        if not key:
            return False
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT protected FROM architecture_params WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return bool(row and row[0])

    def _already_pending(self, diagnosis_key: str) -> bool:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM architecture_proposals
            WHERE diagnosis_key=? AND status='pending'
              AND proposal_type != 'new_module'
        """, (diagnosis_key,))
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def generate_proposals(self, diagnoses: List[dict], evaluation_id: int) -> List[dict]:
        proposals = []
        for diag in diagnoses:
            key = diag["key"]
            if self._already_pending(key):
                continue
            templates = self.PROPOSALS.get(key, [])
            if not templates:
                continue

            template   = templates[0]
            param_key  = template.get("param_key")
            current_val, new_val = None, None

            if param_key and not self._is_protected(param_key):
                current_str = self._get_param(param_key)
                if current_str is not None:
                    try:
                        current_val = float(current_str)
                        param_fn = template.get("param_fn")
                        if param_fn:
                            new_val = param_fn(current_val)
                            if abs(new_val - current_val) < 0.001:
                                continue
                    except (ValueError, TypeError):
                        current_val = current_str

            mod_text = template["modification"]
            if current_val is not None and new_val is not None:
                mod_text = mod_text.format(
                    current=f"{current_val:.3f}" if isinstance(current_val, float) else current_val,
                    new=f"{new_val:.3f}"     if isinstance(new_val, float)    else new_val,
                )

            proposal = {
                "evaluation_id":  evaluation_id,
                "diagnosis_key":  key,
                "diagnosis":      diag,
                "proposal_type":  template.get("change_type", "param_update"),
                "title":          template["title"],
                "problem":        diag["description"],
                "modification":   mod_text,
                "why_better":     template["why_better"],
                "risks":          template["risks"],
                "impact":         template["impact"],
                "energy_impact":  template.get("energy_impact", "low"),
                "reversible":     template.get("reversible", True),
                "change_type":    template.get("change_type", "param_update"),
                "param_key":      param_key,
                "param_current":  current_val,
                "param_new":      new_val,
            }
            proposals.append(proposal)
        return proposals

    def save_proposal(self, proposal: dict) -> int:
        param_new_str = str(proposal["param_new"]) if proposal.get("param_new") is not None else None
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO architecture_proposals
            (timestamp, evaluation_id, diagnosis_key, proposal_type, title, problem,
             modification, why_better, risks, impact, energy_impact,
             predicted_roi, reversible, status, param_key, param_new)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (
            datetime.now().isoformat(),
            proposal.get("evaluation_id"),
            proposal["diagnosis_key"],
            proposal.get("proposal_type", "param_update"),
            proposal["title"],
            proposal["problem"],
            proposal["modification"],
            proposal["why_better"],
            proposal["risks"],
            proposal["impact"],
            proposal.get("energy_impact", "low"),
            proposal.get("predicted_roi", 0.5),
            1 if proposal.get("reversible", True) else 0,
            proposal.get("param_key"),
            param_new_str,
        ))
        proposal_id = c.lastrowid
        conn.commit()
        conn.close()
        return proposal_id


# ══════════════════════════════════════════════════════════════════════
# 9. CHANGE APPLICATOR — safely applies approved changes
# ══════════════════════════════════════════════════════════════════════

class ChangeApplicator:
    """
    Applies approved changes safely.

    CENTRAL INVARIANT: no method here is called without approved=True
    having been set explicitly by a human in architecture_proposals.

    v4 additions:
    - Calls MetaLearningTracker.record_change() after every apply
    - Returns energy_impact metadata
    """

    def __init__(self, db_path: str = ARCH_DB_PATH, meta_tracker: MetaLearningTracker = None):
        self.db   = db_path
        self.meta = meta_tracker

    def _count_changes_today(self) -> int:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM architecture_log WHERE timestamp >= date('now') AND reverted=0")
        n = c.fetchone()[0]
        conn.close()
        return n

    def _snapshot_params(self) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT key, value FROM architecture_params")
        snap = dict(c.fetchall())
        conn.close()
        return snap

    def _get_current_score(self) -> Tuple[float, int]:
        """Returns (score, eval_id) of the most recent evaluation."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT id, score FROM architecture_evaluations ORDER BY timestamp DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        return (row[1], row[0]) if row else (50.0, 0)

    def apply(self, proposal_id: int, cognia_instance=None) -> dict:
        """Applies an approved change. Returns result dict."""
        if self._count_changes_today() >= MAX_CHANGES_PER_DAY:
            return {"ok": False, "error": f"Daily change limit of {MAX_CHANGES_PER_DAY} reached."}

        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, diagnosis_key, title, modification, reversible, status,
                   param_key, param_new, proposal_type
            FROM architecture_proposals WHERE id=?
        """, (proposal_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"ok": False, "error": f"Proposal #{proposal_id} not found."}

        (prop_id, diag_key, title, modification, reversible,
         status, stored_param_key, stored_param_new, proposal_type) = row

        if status != "approved":
            return {"ok": False, "error": f"Proposal #{proposal_id} is not approved (status: {status})."}

        params_before = self._snapshot_params()
        score_before, eval_before_id = self._get_current_score()

        templates = ChangeProposer.PROPOSALS.get(diag_key, [])
        template  = templates[0] if templates else {}
        param_key   = stored_param_key or template.get("param_key")
        change_type = template.get("change_type", "param_update") if template else (proposal_type or "param_update")
        result_detail = ""
        value_before = "N/A"
        value_after  = "N/A"

        if change_type == "param_update" and param_key:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT value, protected FROM architecture_params WHERE key=?", (param_key,))
            prow = c.fetchone()
            conn.close()

            if not prow:
                return {"ok": False, "error": f"Parameter '{param_key}' not found."}
            if prow[1]:
                return {"ok": False, "error": f"Parameter '{param_key}' is protected."}

            current_val = float(prow[0])

            if stored_param_new is not None:
                try:
                    new_val = float(stored_param_new)
                except (ValueError, TypeError):
                    new_val = current_val
            else:
                param_fn = template.get("param_fn") if template else None
                if not param_fn:
                    return {"ok": False, "error": f"No transform function for {param_key}."}
                new_val = param_fn(current_val)

            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("UPDATE architecture_params SET value=?, updated_at=? WHERE key=?",
                      (str(new_val), datetime.now().isoformat(), param_key))
            conn.commit()
            conn.close()

            self._apply_to_instance(cognia_instance, param_key, new_val)
            result_detail = f"{param_key}: {current_val:.4f} → {new_val:.4f}"
            value_before  = str(current_val)
            value_after   = str(new_val)

        elif change_type == "sql_cleanup":
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("DELETE FROM episodic_memory WHERE forgotten=1 AND importance < 0.1")
            deleted = c.rowcount
            conn.commit()
            conn.close()
            result_detail = f"Deleted {deleted} forgotten low-importance episodes."
            value_before  = "N/A"
            value_after   = f"-{deleted} episodes"

        elif change_type == "recommendation_only":
            result_detail = "Recommendation noted. No automated change applied."

        elif change_type == "new_module":
            result_detail = (
                f"New module '{title}' approved. Implementation required by developer. "
                "Proposal logged in architecture_history."
            )

        else:
            result_detail = f"Unknown change type: {change_type}"

        # ── Record in architecture_log ─────────────────────────────────
        params_after = self._snapshot_params()
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO architecture_log
            (timestamp, proposal_id, change_type, change_key, value_before, value_after)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), proposal_id, change_type,
              param_key or diag_key, value_before, value_after))
        log_id = c.lastrowid

        c.execute("""
            UPDATE architecture_proposals
            SET status='applied', params_before=?, params_after=?, decided_at=?
            WHERE id=?
        """, (json.dumps(params_before), json.dumps(params_after),
              datetime.now().isoformat(), proposal_id))
        conn.commit()
        conn.close()

        # ── Record in meta-learning ────────────────────────────────────
        if self.meta:
            self.meta.record_change(
                proposal_id, diag_key, param_key, change_type,
                score_before, eval_before_id
            )

        return {"ok": True, "detail": result_detail, "title": title, "log_id": log_id}

    def _apply_to_instance(self, cognia, param_key: str, new_val: float):
        """Applies parameter change to the live Cognia instance."""
        if cognia is None:
            return
        try:
            mapping = {
                "attention_threshold":    lambda: setattr(cognia.attention, "threshold", new_val),
                "consolidation_interval": lambda: setattr(cognia, "consolidation_interval", int(new_val)),
                "forgetting_interval":    lambda: setattr(cognia, "forgetting_interval", int(new_val)),
                "forgetting_decay_rate":  lambda: setattr(cognia.forgetting, "decay_rate", new_val),
                "forgetting_threshold":   lambda: setattr(cognia.forgetting, "forget_threshold", new_val),
                "working_memory_capacity":lambda: setattr(cognia.working_mem, "CAPACITY", int(new_val)),
                "hypothesis_confidence":  lambda: setattr(cognia.hypothesis, "default_confidence", new_val)
                    if hasattr(cognia, "hypothesis") else None,
                "kg_bridge_min_length":   lambda: setattr(cognia.bridge, "min_word_length", int(new_val))
                    if hasattr(cognia, "bridge") else None,
                "embedding_cache_size":   lambda: setattr(cognia.embeddings, "cache_size", int(new_val))
                    if hasattr(cognia, "embeddings") else None,
                "inference_max_steps":    lambda: setattr(cognia.reasoner, "max_steps", int(new_val))
                    if hasattr(cognia, "reasoner") else None,
                "energy_budget_per_cycle":lambda: setattr(cognia.energy_optimizer, "budget", new_val)
                    if hasattr(cognia, "energy_optimizer") else None,
            }
            if param_key == "attention_w_semantic":
                cognia.attention.w_semantic = new_val
                total = (cognia.attention.w_semantic + cognia.attention.w_emotion +
                         cognia.attention.w_recency  + cognia.attention.w_frequency)
                for attr in ("w_semantic", "w_emotion", "w_recency", "w_frequency"):
                    setattr(cognia.attention, attr, getattr(cognia.attention, attr) / total)
            elif param_key in mapping:
                mapping[param_key]()
        except AttributeError:
            pass  # Change persists in DB even if live instance lacks the attribute

    def rollback(self, log_id: int, cognia_instance=None) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT change_key, value_before, reverted, change_type FROM architecture_log WHERE id=?",
                  (log_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"ok": False, "error": f"Log #{log_id} not found."}
        if row[2]:
            return {"ok": False, "error": f"Change #{log_id} already rolled back."}

        param_key, value_before, _, change_type = row

        if change_type == "sql_cleanup":
            return {"ok": False, "error": "SQL cleanup changes are irreversible (data already deleted)."}
        if change_type == "new_module":
            return {"ok": False, "error": "Module proposals cannot be auto-rolled back (no code was changed)."}

        if change_type == "param_update" and param_key and value_before:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("UPDATE architecture_params SET value=?, updated_at=? WHERE key=?",
                      (value_before, datetime.now().isoformat(), param_key))
            c.execute("UPDATE architecture_log SET reverted=1, reverted_at=? WHERE id=?",
                      (datetime.now().isoformat(), log_id))
            conn.commit()
            conn.close()
            try:
                self._apply_to_instance(cognia_instance, param_key, float(value_before))
            except Exception:
                pass
            return {"ok": True, "detail": f"Rolled back: {param_key} → {value_before}"}

        return {"ok": False, "error": "Change type not automatically reversible."}


# ══════════════════════════════════════════════════════════════════════
# 10. ARCHITECTURE LOG — queries and human-readable reports
# ══════════════════════════════════════════════════════════════════════

class ArchitectureLog:
    """Queries over the history of changes and evaluations."""

    def __init__(self, db_path: str = ARCH_DB_PATH):
        self.db = db_path

    def get_pending_proposals(self) -> List[dict]:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, diagnosis_key, proposal_type, title, problem,
                   modification, why_better, risks, impact, energy_impact,
                   predicted_roi, reversible
            FROM architecture_proposals
            WHERE status='pending'
            ORDER BY predicted_roi DESC, timestamp DESC
        """)
        rows = [
            {
                "id":             r[0],
                "timestamp":      r[1],
                "diagnosis_key":  r[2],
                "proposal_type":  r[3],
                "title":          r[4],
                "problem":        r[5],
                "modification":   r[6],
                "why_better":     r[7],
                "risks":          r[8],
                "impact":         r[9],
                "energy_impact":  r[10],
                "predicted_roi":  r[11],
                "reversible":     bool(r[12]),
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows

    def get_applied_changes(self, limit: int = 20) -> List[dict]:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT l.id, l.timestamp, l.change_type, l.change_key,
                   l.value_before, l.value_after, l.impact_observed,
                   l.reverted, p.title
            FROM architecture_log l
            JOIN architecture_proposals p ON l.proposal_id = p.id
            ORDER BY l.timestamp DESC LIMIT ?
        """, (limit,))
        rows = [
            {
                "log_id":          r[0],
                "timestamp":       r[1],
                "change_type":     r[2],
                "param_key":       r[3],
                "value_before":    r[4],
                "value_after":     r[5],
                "impact_observed": r[6],
                "reverted":        bool(r[7]),
                "title":           r[8],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows

    def get_last_evaluation(self) -> Optional[dict]:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, metrics, diagnoses, score, fatigue_level
            FROM architecture_evaluations ORDER BY timestamp DESC LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id":           row[0],
            "timestamp":    row[1],
            "metrics":      json.loads(row[2]),
            "diagnoses":    json.loads(row[3]),
            "score":        row[4],
            "fatigue_level":row[5],
        }

    def get_score_history(self, n: int = 10) -> List[dict]:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, score, interaction_at, fatigue_level
            FROM architecture_evaluations ORDER BY timestamp DESC LIMIT ?
        """, (n,))
        rows = [
            {"timestamp": r[0], "score": r[1], "interaction": r[2], "fatigue": r[3]}
            for r in c.fetchall()
        ]
        conn.close()
        return list(reversed(rows))

    def format_proposal_for_human(self, proposal: dict) -> str:
        """Formats a proposal for human review."""
        rev   = "✅ Yes" if proposal.get("reversible", True) else "❌ NO (irreversible action)"
        sev   = proposal.get("diagnosis", {}).get("severity", "unknown").upper()
        ptype = proposal.get("proposal_type", "param_update")
        roi   = proposal.get("predicted_roi", 0.5)
        etype = proposal.get("energy_impact", "low")

        type_labels = {
            "param_update":       "⚙️  Parameter change",
            "new_module":         "🧩 New module proposal",
            "sql_cleanup":        "🗑️  Database cleanup",
            "recommendation_only":"💡 Recommendation only",
        }

        lines = [
            "",
            f"╔══════════════════════════════════════════════════════════╗",
            f"║     PROPOSED_ARCHITECTURE_CHANGE #{proposal.get('id','?')}  [{type_labels.get(ptype,ptype)}]",
            f"╠══════════════════════════════════════════════════════════╣",
            f"║  Severity: {sev:<20}  Predicted ROI: {roi:.0%}         ║",
            f"╚══════════════════════════════════════════════════════════╝",
            "",
            "1. PROBLEM DETECTED",
            f"   {proposal['problem']}",
            "",
            "2. PROPOSED MODIFICATION",
            f"   {proposal['modification']}",
            "",
            "3. WHY THIS IMPROVES THE SYSTEM",
            f"   {proposal['why_better']}",
            "",
            "4. POTENTIAL RISKS",
            f"   {proposal['risks']}",
            "",
            "5. PERFORMANCE & ENERGY IMPACT",
            f"   {proposal['impact']}",
            f"   Energy impact: {etype}",
            "",
            "6. IS IT REVERSIBLE?",
            f"   {rev}",
            "",
            "──────────────────────────────────────────────────────────",
            "Do you approve this architectural change?",
            f"  → UI:  use Approve / Reject buttons",
            f"  → CLI: type 'approve {proposal.get('id','?')}' or 'reject {proposal.get('id','?')}'",
            "",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 11. SELF ARCHITECT — main orchestrator
# ══════════════════════════════════════════════════════════════════════

class SelfArchitect:
    """
    Orchestrates the full self-evaluation and improvement cycle.

    v4 cycle:
      1. Get fatigue level → determine diagnostic scope
      2. Collect metrics (respecting fatigue scope)
      3. Run diagnostics (filtered by scope)
      4. Run trend analysis (if fatigue allows)
      5. Merge diagnoses, sorted by severity
      6. Generate param proposals (ChangeProposer)
      7. Generate module proposals (ModuleProposer)
      8. Rank all proposals by ROI (StrategySelector)
      9. Persist evaluation + proposals
      10. Update meta-learning outcomes
      11. Present ranked proposals to human for approval
    """

    def __init__(self, db_path: str = ARCH_DB_PATH, cognia_instance=None):
        self.db     = db_path
        self.cognia      = cognia_instance
        self.energy_loop = EnergyOptimizationLoop(db_path)

        init_architecture_tables(db_path)

        self.evaluator  = ArchitectureEvaluator(db_path)
        self.diagnostic = DiagnosticEngine()
        self.trends     = TrendAnalyzer(db_path)
        self.fatigue    = FatigueAdvisor(db_path)
        self.meta       = MetaLearningTracker(db_path)
        self.proposer   = ChangeProposer(db_path)
        self.modules    = ModuleProposer(db_path)
        self.selector   = StrategySelector(self.meta)
        self.applicator = ChangeApplicator(db_path, self.meta)
        self.log        = ArchitectureLog(db_path)

        self._last_eval_interaction = 0
        self._eval_interval         = EVAL_INTERVAL

    def tick(self, interaction_count: int) -> Optional[dict]:
        """
        Call on every Cognia interaction.
        Returns None most of the time. Returns evaluation dict when triggered.
        """
        if interaction_count - self._last_eval_interaction < self._eval_interval:
            return None
        self._last_eval_interaction = interaction_count
        return self.run_evaluation(triggered_by="auto")

    def run_evaluation(self, triggered_by: str = "manual") -> dict:
        """Executes the full SELF_ARCHITECTURE_EVALUATION cycle."""

        # ── 1. Fatigue level ──────────────────────────────────────────
        fatigue_level, fatigue_score = self.fatigue.get_fatigue_level(self.cognia)
        scope = self.fatigue.should_run_diagnostics(fatigue_level)

        if not scope["run_at_all"]:
            return {
                "evaluation_id":       None,
                "score":               None,
                "skipped":             True,
                "reason":              f"Critical fatigue ({fatigue_score:.2f}) — evaluation deferred.",
                "fatigue_level":       fatigue_level,
            }

        # ── 2. Collect metrics ────────────────────────────────────────
        metrics = self.evaluator.collect_metrics(fatigue_level=fatigue_level)

        # ── 3. Diagnose ───────────────────────────────────────────────
        diagnoses = self.diagnostic.diagnose(metrics, scope=scope)

        # ── 4. Trend analysis ─────────────────────────────────────────
        trend_diagnoses = []
        if scope["trend_analysis"]:
            trend_diagnoses = self.trends.analyze_trends()

        all_diagnoses = diagnoses + trend_diagnoses
        all_diagnoses.sort(key=lambda x: x["severity_n"], reverse=True)

        # ── 5. Persist evaluation ─────────────────────────────────────
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO architecture_evaluations
            (timestamp, interaction_at, metrics, diagnoses, score, fatigue_level, triggered_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            metrics.get("total_user_interactions", 0),
            json.dumps(metrics),
            json.dumps(all_diagnoses),
            metrics["architecture_score"],
            fatigue_level,
            triggered_by,
        ))
        eval_id = c.lastrowid
        conn.commit()
        conn.close()

        # ── 6. Update meta-learning outcomes ─────────────────────────
        self.meta.update_outcomes(metrics["architecture_score"], eval_id)

        # ── 7. Generate proposals ─────────────────────────────────────
        proposals = []

        if scope["param_proposals"]:
            actionable = [d for d in all_diagnoses if d["severity_n"] >= SEVERITY["medium"]]
            raw = self.proposer.generate_proposals(actionable, eval_id)
            for prop in raw:
                prop["id"] = self.proposer.save_proposal(prop)
                proposals.append(prop)

        if scope["module_proposals"]:
            # Propose modules only for high/critical diagnoses without a param fix
            module_candidates = [
                d for d in all_diagnoses
                if d["severity_n"] >= SEVERITY["high"]
                and d["key"] in ModuleProposer.MODULE_CATALOG
            ]
            module_props = self.modules.propose_modules(module_candidates, eval_id)
            for prop in module_props:
                prop["id"] = self.proposer.save_proposal(prop)
                proposals.append(prop)

        # ── 8. Rank by ROI ────────────────────────────────────────────
        proposals = self.selector.rank_proposals(proposals)

        # Update predicted_roi in DB now that we have StrategySelector scores
        conn = db_connect(self.db)
        c = conn.cursor()
        for prop in proposals:
            if prop.get("id") and prop.get("predicted_roi") is not None:
                c.execute(
                    "UPDATE architecture_proposals SET predicted_roi=? WHERE id=?",
                    (prop["predicted_roi"], prop["id"])
                )
        conn.commit()
        conn.close()

        return {
            "evaluation_id":       eval_id,
            "score":               metrics["architecture_score"],
            "fatigue_level":       fatigue_level,
            "metrics":             metrics,
            "diagnoses":           all_diagnoses,
            "trend_diagnoses":     trend_diagnoses,
            "proposals_generated": len(proposals),
            "proposals":           proposals,
            "has_critical":        any(d["severity"] == "critical" for d in all_diagnoses),
        }

    def approve_proposal(self, proposal_id: int, comment: str = "",
                         cognia_instance=None) -> dict:
        """Approves and immediately applies a proposal. REQUIRES HUMAN ACTION."""
        cognia = cognia_instance or self.cognia

        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            UPDATE architecture_proposals
            SET status='approved', human_comment=?, decided_at=?
            WHERE id=? AND status='pending'
        """, (comment, datetime.now().isoformat(), proposal_id))
        updated = c.rowcount
        conn.commit()
        conn.close()

        if not updated:
            return {"ok": False, "error": f"Proposal #{proposal_id} not found or not pending."}

        return self.applicator.apply(proposal_id, cognia)

    def reject_proposal(self, proposal_id: int, comment: str = "") -> dict:
        """Rejects a proposal. No change is applied."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            UPDATE architecture_proposals
            SET status='rejected', human_comment=?, decided_at=?
            WHERE id=? AND status='pending'
        """, (comment or "Rejected by human", datetime.now().isoformat(), proposal_id))
        updated = c.rowcount
        conn.commit()
        conn.close()

        if updated:
            return {"ok": True, "detail": f"Proposal #{proposal_id} rejected and archived."}
        return {"ok": False, "error": f"Proposal #{proposal_id} not found."}

    def rollback_change(self, log_id: int, cognia_instance=None) -> dict:
        return self.applicator.rollback(log_id, cognia_instance or self.cognia)

    def get_meta_insights(self) -> str:
        """Returns a human-readable summary of meta-learning findings."""
        summary = self.meta.get_meta_summary()
        if not summary:
            return "No meta-learning data yet. Apply and observe some changes first."

        lines = ["\n🧠 META-LEARNING INSIGHTS\n"]
        lines.append("What the system has learned about architectural changes:\n")

        for key, data in sorted(summary.items(), key=lambda x: -x[1]["avg_score_delta"]):
            icon = "✅" if data["avg_score_delta"] > 1 else ("⚠️" if data["avg_score_delta"] > -1 else "❌")
            lines.append(
                f"  {icon} {key}:\n"
                f"       Success rate: {data['success_rate']:.0%}  |  "
                f"Avg score Δ: {data['avg_score_delta']:+.1f}  |  "
                f"Observations: {data['total_outcomes']}"
            )
        return "\n".join(lines)

    def status_report(self) -> str:
        """Human-readable summary of the self-evolution system state."""
        pending   = self.log.get_pending_proposals()
        applied   = self.log.get_applied_changes(5)
        last_eval = self.log.get_last_evaluation()
        history   = self.log.get_score_history(5)
        fatigue_level, _ = self.fatigue.get_fatigue_level(self.cognia)

        lines = ["\n🏗️  SELF_ARCHITECT v4 — System Status\n"]

        fatigue_icons = {"low": "🟢", "moderate": "🟡", "high": "🟠", "critical": "🔴"}
        lines.append(f"{fatigue_icons.get(fatigue_level,'⚪')} Fatigue level: {fatigue_level.upper()}")

        if last_eval:
            score = last_eval["score"]
            icon  = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
            lines.append(f"{icon} Architecture score: {score:.1f}/100")
            lines.append(f"   Last evaluation: {last_eval['timestamp'][:16]}  "
                         f"[fatigue at eval: {last_eval.get('fatigue_level','?')}]")

            if history and len(history) >= 2:
                trend = history[-1]["score"] - history[0]["score"]
                arrow = "📈" if trend > 2 else "📉" if trend < -2 else "➡️"
                lines.append(f"   Trend ({len(history)} evals): {arrow} {trend:+.1f}")

            diags = last_eval.get("diagnoses", [])
            if diags:
                lines.append(f"\n⚠️  Active diagnoses ({len(diags)}):")
                for d in diags[:5]:
                    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}.get(d["severity"], "•")
                    cat = d.get("category", "")
                    lines.append(f"   {sev_icon} [{d['severity'].upper()}] {d['title']}  ({cat})")
        else:
            lines.append("   No evaluations yet.")

        if pending:
            lines.append(f"\n📋 Pending proposals ({len(pending)}) — sorted by predicted ROI:")
            for p in pending:
                rev  = "↩️ reversible" if p["reversible"] else "⚠️ irreversible"
                roi  = p.get("predicted_roi", 0.5)
                ptype = p.get("proposal_type", "param_update")
                lines.append(f"   #{p['id']} [{roi:.0%} ROI] [{ptype}] — {p['title']} ({rev})")
            lines.append(f"\n   → Use '/api/architect/propuestas' to see full details")
        else:
            lines.append("\n✅ No pending proposals.")

        if applied:
            lines.append(f"\n📜 Recent changes:")
            for ch in applied[:3]:
                rev_tag = " [ROLLED BACK]" if ch["reverted"] else ""
                lines.append(f"   • {ch['timestamp'][:10]} — {ch['title']}{rev_tag}")
                if ch["value_before"] != "N/A":
                    lines.append(f"     {ch['param_key']}: {ch['value_before']} → {ch['value_after']}")

        return "\n".join(lines)


    # ── Punto 3: Module Generator ─────────────────────────────────────

    def generate_module_code(self, proposal_id: int) -> dict:
        """Genera código Python para una propuesta new_module vía Ollama."""
        import urllib.request as _ur, json as _js
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("""SELECT id,title,problem,modification,why_better,
                         risks,impact,proposal_type,params_before
                         FROM architecture_proposals WHERE id=?""", (proposal_id,))
            row = c.fetchone()
        except Exception as e:
            conn.close(); return {"error": str(e)}
        if not row:
            conn.close(); return {"error": f"Propuesta {proposal_id} no encontrada"}
        _,title,problem,modification,why_better,risks,impact,ptype,pseudocode = row
        conn.close()
        if ptype != "new_module":
            return {"error": f"Propuesta {proposal_id} no es new_module (es {ptype!r})"}
        mname = title.replace("New module: ","").replace(" ","").strip() or f"Module{proposal_id}"
        prompt = (f"Genera código Python para el módulo cognitivo '{mname}'.\n"
                  f"PROBLEMA: {problem}\nDESCRIPCIÓN: {modification}\n"
                  f"PSEUDOCÓDIGO:\n{pseudocode or '(ninguno)'}\n\n"
                  f"REQUISITOS: clase {mname}(db_path), método status_report()->str, sqlite3.\n"
                  f"Responde SOLO con código Python puro. Sin markdown.")
        code, err = None, None
        try:
            url = os.environ.get("OLLAMA_URL","http://localhost:11434")
            modelo = os.environ.get("COGNIA_MODEL","llama3.2")
            with _ur.urlopen(_ur.Request(f"{url}/api/tags"), timeout=10) as r:
                avail = [m["name"].split(":")[0] for m in _js.loads(r.read()).get("models",[])]
            if modelo.split(":")[0] not in avail:
                raise RuntimeError(f"Modelo {modelo!r} no disponible. Disponibles: {avail}")
            payload = _js.dumps({"model":modelo,"prompt":prompt,"stream":True,
                "system":"Responde SOLO con código Python puro.",
                "options":{"temperature":0.3,"num_predict":1200}}).encode()
            req = _ur.Request(f"{url}/api/generate",data=payload,
                              headers={"Content-Type":"application/json"})
            toks=[]
            with _ur.urlopen(req,timeout=120) as r:
                for line in r:
                    if not line.strip(): continue
                    try: chunk=_js.loads(line.decode())
                    except: continue
                    if chunk.get("response"): toks.append(chunk["response"])
                    if chunk.get("done"): break
            raw = "".join(toks).strip()
            if raw.startswith("```"):
                parts=raw.split("\n")
                raw="\n".join(parts[1:-1] if parts[-1].strip()=="```" else parts[1:])
            code = raw
        except Exception as e:
            err = str(e)
            code = (f'''"""\n{mname} — esqueleto (Ollama no disponible: {e})\n"""\n'''
                    f"import sqlite3\n\nclass {mname}:\n"
                    f"    def __init__(self, db_path='cognia_memory.db'): self.db=db_path\n"
                    f"    def run(self): return {{'status':'not_implemented'}}\n"
                    f"    def status_report(self): return '{mname}: esqueleto.'\n")
        status = "code_generated" if not err else "code_skeleton"
        conn2 = db_connect(self.db)
        try:
            conn2.execute("UPDATE architecture_proposals SET generated_code=?,status=? WHERE id=?",
                          (code, status, proposal_id))
            conn2.commit()
        except Exception as e:
            conn2.close(); return {"error": f"Error guardando: {e}"}
        conn2.close()
        return {"proposal_id":proposal_id,"module_name":mname,"status":status,
                "ollama_used":err is None,"generation_error":err,
                "code_preview":code[:300]+"..." if len(code)>300 else code}

    def test_proposal(self, proposal_id: int) -> dict:
        """Ejecuta el código generado en sandbox aislado (nunca toca DB real)."""
        import json as _js
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("SELECT title,generated_code FROM architecture_proposals WHERE id=?",
                      (proposal_id,))
            row = c.fetchone()
        except Exception as e:
            conn.close(); return {"error": str(e)}
        conn.close()
        if not row: return {"error": f"Propuesta {proposal_id} no encontrada"}
        title, code = row
        if not code:
            return {"error":"Sin código. Llama primero generate_module_code().","proposal_id":proposal_id}
        try:
            from sandbox_tester import SandboxTester
        except ImportError as e:
            return {"error": f"sandbox_tester.py no disponible: {e}"}
        mname = title.replace("New module: ","").replace(" ","").strip() or f"module_{proposal_id}"
        report = SandboxTester(self.db).test_module_from_code(code, mname, proposal_id)
        passed = report.get("passed", False)
        new_status = "test_passed" if passed else "test_failed"
        summary = {"passed":passed,"timestamp":report.get("timestamp"),
                   "summary":report.get("summary","")[:500],
                   "criteria":{k:{"passed":v["passed"],"value":v.get("value")}
                               for k,v in report.get("details",{}).get("criteria",{}).items()}}
        conn2 = db_connect(self.db)
        try:
            conn2.execute("UPDATE architecture_proposals SET test_result=?,test_passed=?,status=? WHERE id=?",
                          (_js.dumps(summary),1 if passed else 0,new_status,proposal_id))
            conn2.commit()
        except Exception as e:
            conn2.close(); return {"error": f"Error guardando: {e}"}
        conn2.close()
        return {"proposal_id":proposal_id,"module_name":mname,"passed":passed,"status":new_status,
                "summary":report.get("summary",""),
                "next_step":(f"✅ Test pasado. Aprueba: POST /api/architect/aprobar/{proposal_id}"
                             if passed else f"❌ Test fallido. Regenera: POST /api/architect/generar_codigo/{proposal_id}")}


# ══════════════════════════════════════════════════════════════════════
# 11b. ENERGY OPTIMIZATION LOOP — Punto 4: loop de feedback cerrado
# ══════════════════════════════════════════════════════════════════════

class EnergyOptimizationLoop:
    """
    Punto 4: cierra el loop energético.
    ANTES (roto):  mide → registra → propone → humano aprueba
    AHORA (cerrado): detect → adjust → measure → evaluate → auto-rollback
    Solo parámetros en SAFE_PARAMS se ajustan sin aprobación humana.
    """
    SAFE_PARAMS = {
        "inference_max_steps":    (1,    3,    1,    "pasos de inferencia"),
        "attention_threshold":    (0.20, 0.55, 0.05, "umbral de atención"),
        "embedding_cache_size":   (256,  1024, 128,  "cache de embeddings"),
        "consolidation_interval": (4,    20,   2,    "intervalo de consolidación"),
    }
    HIGH_ENERGY   = 1.5
    HIGH_LATENCY  = 400.0
    MIN_CYCLES    = 5
    EVAL_WINDOW   = 10

    def __init__(self, db_path: str):
        self.db = db_path

    def _energy_stats(self, n=20) -> dict:
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("""SELECT AVG(energy_estimate),AVG(latency_ms),
                               AVG(inference_steps),AVG(cache_misses),COUNT(*)
                        FROM energy_log ORDER BY timestamp DESC LIMIT ?""", (n,))
            r = c.fetchone()
            if r and r[4] and r[4] >= self.MIN_CYCLES:
                return {"avg_e":round(r[0] or 0,3),"avg_l":round(r[1] or 0,1),
                        "avg_inf":round(r[2] or 0,2),"avg_miss":round(r[3] or 0,2),
                        "n":int(r[4]),"ok":True}
        except Exception: pass
        finally: conn.close()
        return {"ok":False,"n":0}

    def _read_param(self, key):
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("SELECT value FROM architecture_params WHERE key=?",(key,))
            r = c.fetchone(); return float(r[0]) if r else None
        except: return None
        finally: conn.close()

    def _write_param(self, key, val) -> bool:
        conn = db_connect(self.db)
        try:
            conn.execute("UPDATE architecture_params SET value=?,updated_at=? WHERE key=?",
                         (str(val),datetime.now().isoformat(),key))
            conn.commit(); return True
        except: return False
        finally: conn.close()

    def detect(self) -> dict:
        """Detecta si hay condición de alta energía y qué parámetro ajustar."""
        s = self._energy_stats()
        if not s.get("ok"):
            return {"needs_action":False,"reason":f"Datos insuficientes ({s.get('n',0)}/{self.MIN_CYCLES} ciclos)"}
        # Diagnóstico 1: demasiados pasos de inferencia
        if s["avg_e"] > self.HIGH_ENERGY and s["avg_inf"] >= 2.5:
            cur = self._read_param("inference_max_steps")
            if cur and cur > 1:
                return {"needs_action":True,"trigger":"high_energy_inference",
                        "param_key":"inference_max_steps","current":cur,"proposed":max(1.0,cur-1),
                        "reason":f"energy={s['avg_e']:.2f}>{self.HIGH_ENERGY}, inf_steps={s['avg_inf']:.1f}","stats":s}
        # Diagnóstico 2: latencia alta → subir umbral de atención
        if s["avg_l"] > self.HIGH_LATENCY:
            cur = self._read_param("attention_threshold")
            if cur:
                p = self.SAFE_PARAMS["attention_threshold"]
                nv = round(min(p[1], cur+p[2]), 3)
                if nv != cur:
                    return {"needs_action":True,"trigger":"high_latency",
                            "param_key":"attention_threshold","current":cur,"proposed":nv,
                            "reason":f"latency={s['avg_l']:.0f}ms>{self.HIGH_LATENCY}ms","stats":s}
        # Diagnóstico 3: cache misses → ampliar cache
        if s["avg_miss"] > 2.0:
            cur = self._read_param("embedding_cache_size")
            if cur:
                p = self.SAFE_PARAMS["embedding_cache_size"]
                nv = min(p[1], cur+p[2])
                if nv != cur:
                    return {"needs_action":True,"trigger":"high_cache_misses",
                            "param_key":"embedding_cache_size","current":cur,"proposed":nv,
                            "reason":f"cache_miss={s['avg_miss']:.1f}>2","stats":s}
        return {"needs_action":False,"reason":"Sistema dentro de rangos normales","stats":s}

    def adjust(self, action: dict) -> dict:
        """Aplica micro-ajuste automático dentro de SAFE_PARAMS."""
        key,cur,prop,trig = (action["param_key"],action["current"],
                             action["proposed"],action.get("trigger","auto"))
        if key not in self.SAFE_PARAMS:
            return {"ok":False,"error":f"{key!r} requiere aprobación humana"}
        p = self.SAFE_PARAMS[key]
        if not (p[0] <= prop <= p[1]):
            return {"ok":False,"error":f"Valor {prop} fuera de rango [{p[0]},{p[1]}]"}
        sb = self._energy_stats(10)
        if not self._write_param(key, prop):
            return {"ok":False,"error":f"No se pudo escribir {key}={prop}"}
        conn = db_connect(self.db)
        try:
            conn.execute("""INSERT INTO energy_micro_adjustments
                (timestamp,param_key,value_before,value_after,trigger,
                 energy_before,latency_before,outcome)
                VALUES (?,?,?,?,?,?,?,'pending')""",
                (datetime.now().isoformat(),key,cur,prop,trig,
                 sb.get("avg_e"),sb.get("avg_l")))
            conn.commit()
            adj_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as e:
            conn.close(); return {"ok":False,"error":str(e)}
        conn.close()
        return {"ok":True,"adj_id":adj_id,"param_key":key,"from":cur,"to":prop,
                "message":f"✅ Auto-ajuste: {key} {cur}→{prop} ({p[3]})"}

    def evaluate(self, adj_id: int) -> dict:
        """Compara antes/después y hace rollback si empeoró."""
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("""SELECT param_key,value_before,value_after,
                                energy_before,latency_before,outcome
                         FROM energy_micro_adjustments WHERE id=?""", (adj_id,))
            row = c.fetchone()
        except Exception as e:
            conn.close(); return {"error":str(e)}
        conn.close()
        if not row: return {"error":f"Ajuste {adj_id} no encontrado"}
        key,vb,va,eb,lb,outcome = row
        if outcome != "pending":
            return {"adj_id":adj_id,"outcome":outcome,"note":"Ya evaluado"}
        sa = self._energy_stats(self.EVAL_WINDOW)
        if not sa.get("ok"):
            return {"adj_id":adj_id,"outcome":"pending",
                    "note":f"Esperando ciclos ({sa.get('n',0)}/{self.EVAL_WINDOW})"}
        ea,la = sa["avg_e"],sa["avg_l"]
        ed = (ea-(eb or ea))/max(0.001,eb or 0.001)
        ld = (la-(lb or la))/max(0.001,lb or 0.001)
        if ed < -0.05 or ld < -0.05:   outcome = "improved"
        elif ed > 0.10 or ld > 0.10:   outcome = "worse"
        else:                           outcome = "no_change"
        conn2 = db_connect(self.db)
        conn2.execute("UPDATE energy_micro_adjustments SET energy_after=?,latency_after=?,outcome=? WHERE id=?",
                      (round(ea,3),round(la,1),outcome,adj_id))
        conn2.commit(); conn2.close()
        result = {"adj_id":adj_id,"param":key,"outcome":outcome,
                  "energy":{"before":eb,"after":ea,"delta_pct":round(ed*100,1)},
                  "latency":{"before":lb,"after":la,"delta_pct":round(ld*100,1)}}
        if outcome == "worse":
            self._write_param(key, vb)
            result["rollback"] = True
            result["message"] = f"⚠️ Revertido: {key} {va}→{vb} (empeoró {ld*100:+.1f}% lat, {ed*100:+.1f}% energy)"
        elif outcome == "improved":
            result["message"] = f"✅ Mejora: {key}={va} ({ed*100:+.1f}% energy, {ld*100:+.1f}% lat)"
        else:
            result["message"] = f"➡️ Sin cambio significativo con {key}={va}"
        return result

    def run_loop(self) -> dict:
        """Ciclo completo: evalúa pendientes, luego detecta+ajusta si necesario."""
        results = {"timestamp":datetime.now().isoformat(),"actions":[]}
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("SELECT id FROM energy_micro_adjustments WHERE outcome='pending' ORDER BY timestamp ASC LIMIT 5")
            pending = [r[0] for r in c.fetchall()]
        except: pending=[]
        finally: conn.close()
        for aid in pending:
            ev = self.evaluate(aid)
            results["actions"].append({"type":"evaluate",**ev})
        det = self.detect()
        results["detection"] = det
        if det.get("needs_action"):
            adj = self.adjust(det)
            results["actions"].append({"type":"adjust",**adj})
            results["adjusted"] = adj.get("ok",False)
        else:
            results["adjusted"] = False
        results["summary"] = (f"Loop: {len(pending)} evaluaciones, "
                               f"{'1 ajuste' if results['adjusted'] else 'sin ajuste'}")
        return results

    def get_history(self, n=20) -> list:
        conn = db_connect(self.db); c = conn.cursor()
        try:
            c.execute("""SELECT id,timestamp,param_key,value_before,value_after,
                                trigger,energy_before,energy_after,
                                latency_before,latency_after,outcome
                         FROM energy_micro_adjustments ORDER BY timestamp DESC LIMIT ?""",(n,))
            return [{"id":r[0],"timestamp":r[1],"param_key":r[2],"value_before":r[3],
                     "value_after":r[4],"trigger":r[5],"energy_before":r[6],
                     "energy_after":r[7],"latency_before":r[8],"latency_after":r[9],
                     "outcome":r[10]} for r in c.fetchall()]
        except: return []
        finally: conn.close()


# ══════════════════════════════════════════════════════════════════════
# 12. FLASK INTEGRATION — API endpoints
# ══════════════════════════════════════════════════════════════════════

def register_routes_architect(app, get_cognia_fn):
    """Registers self-architect endpoints in the Flask app."""
    from flask import request, jsonify

    _architect = None

    def get_architect():
        nonlocal _architect
        if _architect is None:
            _architect = SelfArchitect(ARCH_DB_PATH, get_cognia_fn())
        return _architect

    @app.route("/api/architect/estado")
    def api_architect_estado():
        arch = get_architect()
        return jsonify({
            "last_evaluation":   arch.log.get_last_evaluation(),
            "pending_proposals": len(arch.log.get_pending_proposals()),
            "score_history":     arch.log.get_score_history(10),
            "status_text":       arch.status_report(),
            "meta_insights":     arch.get_meta_insights(),
        })

    @app.route("/api/architect/evaluar", methods=["POST"])
    def api_architect_evaluar():
        arch   = get_architect()
        result = arch.run_evaluation(triggered_by="manual")
        result["proposals_formatted"] = [
            arch.log.format_proposal_for_human(p)
            for p in result.get("proposals", [])
        ]
        return jsonify(result)

    @app.route("/api/architect/propuestas")
    def api_architect_propuestas():
        arch    = get_architect()
        pending = arch.log.get_pending_proposals()
        return jsonify({
            "pending":   pending,
            "formatted": [arch.log.format_proposal_for_human(p) for p in pending],
            "count":     len(pending),
        })

    @app.route("/api/architect/aprobar/<int:proposal_id>", methods=["POST"])
    def api_architect_aprobar(proposal_id):
        data    = request.get_json() or {}
        comment = data.get("comment", "")
        arch    = get_architect()
        result  = arch.approve_proposal(proposal_id, comment, get_cognia_fn())
        return jsonify(result)

    @app.route("/api/architect/rechazar/<int:proposal_id>", methods=["POST"])
    def api_architect_rechazar(proposal_id):
        data    = request.get_json() or {}
        comment = data.get("comment", "Rejected by human")
        arch    = get_architect()
        result  = arch.reject_proposal(proposal_id, comment)
        return jsonify(result)

    @app.route("/api/architect/revertir/<int:log_id>", methods=["POST"])
    def api_architect_revertir(log_id):
        arch   = get_architect()
        result = arch.rollback_change(log_id, get_cognia_fn())
        return jsonify(result)

    @app.route("/api/architect/historial")
    def api_architect_historial():
        arch = get_architect()
        n    = int(request.args.get("n", 20))
        return jsonify(arch.log.get_applied_changes(n))

    @app.route("/api/architect/params")
    def api_architect_params():
        conn = db_connect(ARCH_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key, value, dtype, description, protected, updated_at FROM architecture_params ORDER BY protected DESC, key")
        params = [
            {"key": r[0], "value": r[1], "dtype": r[2],
             "description": r[3], "protected": bool(r[4]), "updated_at": r[5]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify(params)

    @app.route("/api/architect/meta")
    def api_architect_meta():
        arch = get_architect()
        return jsonify({
            "summary":       arch.meta.get_meta_summary(),
            "narrative":     arch.get_meta_insights(),
        })

    @app.route("/api/architect/energia")
    def api_architect_energia():
        """Returns recent energy log entries."""
        conn = db_connect(ARCH_DB_PATH)
        c = conn.cursor()
        n = int(request.args.get("n", 50))
        try:
            c.execute("""
                SELECT timestamp, interaction_id, embedding_calls, retrieval_ops,
                       inference_steps, cache_hits, cache_misses, latency_ms, energy_estimate
                FROM energy_log ORDER BY timestamp DESC LIMIT ?
            """, (n,))
            rows = [
                {
                    "timestamp": r[0], "interaction_id": r[1],
                    "embedding_calls": r[2], "retrieval_ops": r[3],
                    "inference_steps": r[4], "cache_hits": r[5],
                    "cache_misses": r[6], "latency_ms": r[7], "energy_estimate": r[8]
                }
                for r in c.fetchall()
            ]
        except Exception:
            rows = []
        conn.close()
        return jsonify(rows)

    @app.route("/api/architect/generar_codigo/<int:proposal_id>", methods=["POST"])
    def api_generar_codigo(proposal_id):
        return jsonify(get_architect().generate_module_code(proposal_id))

    @app.route("/api/architect/test/<int:proposal_id>", methods=["POST"])
    def api_test_propuesta(proposal_id):
        return jsonify(get_architect().test_proposal(proposal_id))

    @app.route("/api/architect/propuesta/<int:proposal_id>")
    def api_propuesta_detalle(proposal_id):
        import json as _js
        conn = db_connect(ARCH_DB_PATH); c = conn.cursor()
        try:
            c.execute("""SELECT id,timestamp,title,problem,modification,why_better,
                         risks,impact,proposal_type,status,energy_impact,predicted_roi,
                         reversible,human_comment,generated_code,test_result,test_passed
                         FROM architecture_proposals WHERE id=?""",(proposal_id,))
            row = c.fetchone()
        except Exception as e:
            conn.close(); return jsonify({"error":str(e)}),500
        conn.close()
        if not row: return jsonify({"error":f"Propuesta {proposal_id} no encontrada"}),404
        tr=None
        if row[15]:
            try: tr=_js.loads(row[15])
            except: tr={"raw":row[15]}
        guides={"pending":f"POST /api/architect/generar_codigo/{proposal_id}",
            "code_generated":f"POST /api/architect/test/{proposal_id}",
            "code_skeleton":f"Completa el esqueleto y luego POST /api/architect/test/{proposal_id}",
            "test_passed":f"POST /api/architect/aprobar/{proposal_id}",
            "test_failed":f"POST /api/architect/generar_codigo/{proposal_id}"}
        return jsonify({"id":row[0],"timestamp":row[1],"title":row[2],"problem":row[3],
            "modification":row[4],"why_better":row[5],"risks":row[6],"impact":row[7],
            "proposal_type":row[8],"status":row[9],"energy_impact":row[10],
            "predicted_roi":row[11],"reversible":bool(row[12]),"human_comment":row[13],
            "generated_code":row[14],"test_result":tr,"test_passed":row[16],
            "next_step":guides.get(row[9] or "","")})

    @app.route("/api/energy/loop", methods=["POST"])
    def api_energy_loop():
        """Punto 4: ejecuta un ciclo del Energy Optimization Loop."""
        return jsonify(get_architect().energy_loop.run_loop())

    @app.route("/api/energy/historial")
    def api_energy_historial():
        n = int(request.args.get("n",20))
        return jsonify(get_architect().energy_loop.get_history(n))

    @app.route("/api/energy/estado")
    def api_energy_estado():
        """Detección sin actuar — útil para monitoreo."""
        return jsonify(get_architect().energy_loop.detect())

    print("[OK] SelfArchitect v5 — /api/architect/* + /api/energy/* activos")
    return get_architect
