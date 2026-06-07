"""
cognia/learning/continuous_learning.py
=======================================
Chimera "continuous learning at three speeds" CONTROLLER (whitepaper section 10).

This module does NOT reimplement learning mechanics. It ORCHESTRATES the three
already-existing learning speeds behind a single object, mapping each Chimera
"speed" onto the real Cognia subsystem that performs it:

  FAST  (per-observation, zero-gradient): episodic/KB write-gate.
        -> cognia.memory.hierarchical.HierarchicalMemory.write
        Real, every call. No weights touched; an observation is gated into
        episodic memory by surprise + importance.

  MEDIUM (per-session, adapter lifecycle / distillation trigger): LoRA ELC.
        -> inspects real episode counts + real adapter files and EMITS A
        TRIGGER. HONEST SCOPE: the medium tier does NOT train weights. Real
        ELC/LoRA training needs the loaded base model, which is unavailable
        offline. So medium tier manages adapter lifecycle (presence/size) and
        emits a real distillation TRIGGER signal; the actual training is
        DELEGATED to the existing sleep cycle / node ELC trainer. We never
        fabricate a trained adapter here.

  SLOW  (per-cycle, consolidation + differential decay): the EWC/rehearsal
        analogue.
        -> ConsolidationModule.consolidate (episodic -> semantic),
           LongTermConsolidator.consolidate (episodic -> KG facts),
           ForgettingModule.decay_cycle (differential decay).
        Real, every call.

ASCII-only output. Tolerates a missing/unreadable DB (never crashes).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ── Distillation-trigger tunables (medium tier) ────────────────────────────
# WHY: the medium tier must decide WHEN a LoRA distillation is worth running,
# without actually running it (training is delegated — see module docstring).
# The decision is a function of REAL stored-episode counts.
#
# DISTILL_TRIGGER_MIN_EPISODES: a distillation pass only earns its cost once
# enough fresh experience has accumulated. 20 episodes is a small but non-trivial
# batch — below it, a LoRA pass would overfit a handful of points and is skipped.
DISTILL_TRIGGER_MIN_EPISODES = 20

# DISTILL_TRIGGER_MIN_IMPORTANCE: episodes at or above this importance (on the
# episodic 0..3 scale) count as "high-importance" — the durable decisions /
# preferences a distillation should actually internalise. Reported alongside the
# raw count so a human (or the sleep cycle) can weigh trigger quality.
DISTILL_TRIGGER_MIN_IMPORTANCE = 1.5

# WHY (delegation, restated where it matters): real ELC/LoRA training is NOT
# performed by this controller. It is delegated to the sleep cycle / node ELC
# trainer, which has the loaded base model. We only compute the trigger.
_DELEGATION_NOTE = (
    "real LoRA training delegated to sleep cycle / node ELC trainer; "
    "this controller only emits the trigger"
)

# WHY: wide window (~10 years) used to count "all" stored episodes via the real
# episodic.get_in_window API, which is the only count that also exposes per-row
# importance (episodic.count() gives a total but not importance breakdown).
_WIDE_WINDOW_HOURS = 10 * 365 * 24
_WINDOW_LIMIT = 100000


@dataclass
class LearnResult:
    speed: str            # "fast" | "medium" | "slow"
    action: str
    detail: dict = field(default_factory=dict)


class ContinuousLearning:
    """Three-speed continuous-learning controller (orchestrator, not trainer)."""

    def __init__(self, db_path: Optional[str] = None, user_id: str = "default",
                 adapter_dir: str = "model_shards/adapters"):
        self.user_id = user_id
        self.adapter_dir = adapter_dir

        # WHY: resolve the live DB path lazily and defensively. A missing or
        # unreadable DB must NEVER crash construction — every subsystem below is
        # built behind _safe and degrades to None / empty on failure.
        if db_path is None:
            try:
                from ..config import DB_PATH
                db_path = DB_PATH
            except Exception:
                db_path = None
        self.db_path = db_path

        self.memory = self._safe(self._build_memory)
        self.adapters = self._safe(lambda: self._build_adapter_store(adapter_dir))
        self.forgetting = self._safe(self._build_forgetting)
        self.consolidator = self._safe(self._build_consolidator)
        self.long_term = self._safe(self._build_long_term)
        self.episodic = self._safe(self._build_episodic)

    # ── lazy builders (each tolerated by _safe) ────────────────────────────
    def _build_memory(self):
        from ..memory.hierarchical import HierarchicalMemory
        return HierarchicalMemory(db_path=self.db_path)

    @staticmethod
    def _build_adapter_store(adapter_dir: str):
        from ..memory.adapter_store import AdapterStore
        return AdapterStore(base_dir=adapter_dir)

    def _build_forgetting(self):
        from ..memory.forgetting import ForgettingModule
        return ForgettingModule(self.db_path) if self.db_path else None

    def _build_consolidator(self):
        from ..memory.forgetting import ConsolidationModule
        from ..memory.semantic import SemanticMemory
        if not self.db_path:
            return None
        return ConsolidationModule(self.db_path, SemanticMemory(self.db_path))

    def _build_long_term(self):
        from ..memory.long_term_consolidator import LongTermConsolidator
        return LongTermConsolidator(self.db_path) if self.db_path else None

    def _build_episodic(self):
        from ..memory.episodic import EpisodicMemory
        return EpisodicMemory(self.db_path) if self.db_path else None

    @staticmethod
    def _safe(builder):
        try:
            return builder()
        except Exception:
            return None

    # ── FAST: per-observation episodic/KB write-gate (zero gradient) ───────
    def learn_fast(self, observation: str, importance: Optional[float] = None,
                   pin: bool = False) -> LearnResult:
        """Gate one observation into episodic memory. Real, no weights touched."""
        if self.memory is None:
            return LearnResult("fast", "no_memory_backend",
                               {"observation": _ascii(str(observation)[:60]),
                                "note": "HierarchicalMemory unavailable"})
        try:
            r = self.memory.write(observation, importance=importance, pin=pin)
            return LearnResult(
                "fast",
                "stored" if r.stored_episodic else "gated_out",
                {
                    "observation": _ascii(str(observation)[:60]),
                    "stored_episodic": bool(r.stored_episodic),
                    "surprise": float(r.surprise),
                    "importance": float(r.importance),
                    "gate_score": float(r.gate_score),
                    "reason": _ascii(str(r.reason)),
                },
            )
        except Exception as exc:
            return LearnResult("fast", "write_error",
                               {"observation": _ascii(str(observation)[:60]),
                                "error": _ascii(str(exc)[:80])})

    # ── distillation trigger: real episode counts + real adapter files ─────
    def distillation_status(self) -> dict:
        """Compute the medium-tier trigger from REAL state. Never raises."""
        episode_count = 0
        high_importance_count = 0

        # Total stored (non-forgotten) episodes via the real count() API.
        if self.episodic is not None:
            try:
                episode_count = int(self.episodic.count())
            except Exception:
                episode_count = 0

            # High-importance breakdown: get_in_window exposes per-row
            # importance; a very wide window centred on "now" returns all rows.
            try:
                rows = self.episodic.get_in_window(
                    datetime.now().isoformat(),
                    window_hours=_WIDE_WINDOW_HOURS,
                    limit=_WINDOW_LIMIT,
                )
                high_importance_count = sum(
                    1 for r in rows
                    if isinstance(r, dict)
                    and float(r.get("importance", 0.0)) >= DISTILL_TRIGGER_MIN_IMPORTANCE
                )
            except Exception:
                high_importance_count = 0

        should_distill = episode_count >= DISTILL_TRIGGER_MIN_EPISODES

        # Adapter presence: a real file-backed lookup (AdapterStore.get loads
        # the .npz from disk if present, else returns None).
        adapter_present = False
        if self.adapters is not None:
            try:
                adapter_present = self.adapters.get(self.user_id) is not None
            except Exception:
                adapter_present = False

        return {
            "episode_count": episode_count,
            "high_importance_count": high_importance_count,
            "should_distill": bool(should_distill),
            "adapter_present": bool(adapter_present),
            "note": _DELEGATION_NOTE,
        }

    # ── MEDIUM: adapter lifecycle + distillation trigger (NO training) ─────
    def learn_medium(self) -> LearnResult:
        """Emit a real distillation trigger; never trains weights here."""
        status = self.distillation_status()

        # Trigger only when enough episodes accumulated AND no adapter already
        # captures them (presence => a recent distillation already ran).
        if status["should_distill"] and not status["adapter_present"]:
            action = "distill_triggered"
            detail_note = (
                "LoRA distillation SHOULD run: %d episodes >= %d threshold and "
                "no adapter present for user. %s."
                % (status["episode_count"], DISTILL_TRIGGER_MIN_EPISODES,
                   _DELEGATION_NOTE)
            )
        else:
            action = "no_distill_needed"
            if status["adapter_present"]:
                detail_note = ("adapter already present for user '%s'; no new "
                               "distillation triggered" % self.user_id)
            else:
                detail_note = (
                    "only %d episodes (< %d threshold); accumulating before a "
                    "distillation is worthwhile"
                    % (status["episode_count"], DISTILL_TRIGGER_MIN_EPISODES)
                )

        return LearnResult("medium", action,
                           {"status": status, "explanation": _ascii(detail_note),
                            "trains_weights": False})

    # ── SLOW: consolidation (episodic->semantic, ->KG) + differential decay ─
    def consolidate_slow(self) -> LearnResult:
        """Run the real consolidation + decay subsystems. Never raises."""
        detail = {
            "concepts_consolidated": 0,
            "longterm_facts": 0,
            "decay": {"total_checked": 0, "forgotten": 0, "compressed": 0},
        }

        if self.consolidator is not None:
            try:
                detail["concepts_consolidated"] = int(
                    self.consolidator.consolidate(min_support=2))
            except Exception as exc:
                detail["consolidate_error"] = _ascii(str(exc)[:80])

        if self.long_term is not None:
            try:
                detail["longterm_facts"] = int(
                    self.long_term.consolidate(self.user_id, min_occurrences=3))
            except Exception as exc:
                detail["longterm_error"] = _ascii(str(exc)[:80])

        if self.forgetting is not None:
            try:
                d = self.forgetting.decay_cycle()
                if isinstance(d, dict):
                    detail["decay"] = {
                        "total_checked": int(d.get("total_checked", 0)),
                        "forgotten": int(d.get("forgotten", 0)),
                        "compressed": int(d.get("compressed", 0)),
                    }
            except Exception as exc:
                detail["decay_error"] = _ascii(str(exc)[:80])

        return LearnResult("slow", "consolidated_and_decayed", detail)

    # ── one full 3-speed pass ──────────────────────────────────────────────
    def cycle(self, observations: List[str]) -> dict:
        """Run fast on each observation, then medium (trigger), then slow."""
        observations = observations or []
        fast_results = [self.learn_fast(o) for o in observations]
        medium_result = self.learn_medium()
        slow_result = self.consolidate_slow()
        return {
            "user_id": self.user_id,
            "fast": fast_results,
            "medium": medium_result,
            "slow": slow_result,
        }


# ── reporting ──────────────────────────────────────────────────────────────
def format_report(summary: dict) -> str:
    """ASCII multi-line report of the three speeds and their real outcomes."""
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("Chimera continuous learning -- 3-speed pass (user=%s)"
                 % _ascii(str(summary.get("user_id", "default"))))
    lines.append("=" * 64)

    # FAST
    lines.append("")
    lines.append("[FAST] per-observation episodic write-gate (no gradients)")
    fast = summary.get("fast", []) or []
    if not fast:
        lines.append("  (no observations)")
    for r in fast:
        d = r.detail
        lines.append("  - %-9s %s" % (r.action, d.get("observation", "")))
        if "surprise" in d:
            lines.append("      stored=%s surprise=%.3f importance=%.3f gate=%.3f"
                         % (d.get("stored_episodic"), d.get("surprise", 0.0),
                            d.get("importance", 0.0), d.get("gate_score", 0.0)))

    # MEDIUM
    lines.append("")
    lines.append("[MEDIUM] adapter lifecycle + distillation TRIGGER (no training)")
    med = summary.get("medium")
    if med is not None:
        st = med.detail.get("status", {})
        lines.append("  action: %s" % med.action)
        lines.append("  episodes=%d (high-importance=%d) should_distill=%s adapter_present=%s"
                     % (st.get("episode_count", 0), st.get("high_importance_count", 0),
                        st.get("should_distill", False), st.get("adapter_present", False)))
        lines.append("  %s" % med.detail.get("explanation", ""))
        lines.append("  trains_weights=%s" % med.detail.get("trains_weights", False))

    # SLOW
    lines.append("")
    lines.append("[SLOW] consolidation (episodic->semantic, ->KG) + differential decay")
    slow = summary.get("slow")
    if slow is not None:
        d = slow.detail
        dc = d.get("decay", {})
        lines.append("  action: %s" % slow.action)
        lines.append("  concepts_consolidated=%d longterm_facts=%d"
                     % (d.get("concepts_consolidated", 0), d.get("longterm_facts", 0)))
        lines.append("  decay: checked=%d forgotten=%d compressed=%d"
                     % (dc.get("total_checked", 0), dc.get("forgotten", 0),
                        dc.get("compressed", 0)))

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(_ascii(x) for x in lines)


def _ascii(s: str) -> str:
    # WHY: Windows CP1252 console; strip non-ASCII so prints never crash.
    return str(s).encode("ascii", "replace").decode("ascii")


# ── CLI / demo ───────────────────────────────────────────────────────────
_DEMO_OBSERVATIONS = [
    "Decidi que siempre usare numpy puro en los nodos de Cognia.",
    "El objetivo clave de este sprint es el controlador de aprendizaje continuo.",
    "Recorda preferir embeddings hash de 256 dimensiones en todo el pipeline.",
    "Probe el cafe de la esquina hoy.",
    "Nunca subir la clave de API de produccion al repositorio.",
]


def _demo(db_path: Optional[str] = None, user_id: str = "default") -> None:
    cl = ContinuousLearning(db_path=db_path, user_id=user_id)
    summary = cl.cycle(_DEMO_OBSERVATIONS)
    print(format_report(summary))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cognia.learning.continuous_learning",
        description="Chimera 3-speed continuous-learning controller (orchestrator).",
    )
    parser.add_argument("--db", default=None, help="DB path (default: live cognia DB)")
    parser.add_argument("--user", default="default", help="user_id")
    parser.add_argument("--status", action="store_true",
                        help="print distillation_status only and exit")
    args = parser.parse_args()

    if args.status:
        cl = ContinuousLearning(db_path=args.db, user_id=args.user)
        st = cl.distillation_status()
        print("distillation_status:")
        print("  episode_count          = %d" % st["episode_count"])
        print("  high_importance_count  = %d" % st["high_importance_count"])
        print("  should_distill         = %s" % st["should_distill"])
        print("  adapter_present        = %s" % st["adapter_present"])
        print("  note                   = %s" % _ascii(st["note"]))
        return

    _demo(db_path=args.db, user_id=args.user)


if __name__ == "__main__":
    main()
