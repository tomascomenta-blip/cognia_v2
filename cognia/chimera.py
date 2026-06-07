"""
cognia/chimera.py
=================
Chimera CAPSTONE orchestrator (whitepaper section 11).

A single ChimeraSystem that runs the full Chimera inference loop over one query
by REUSING the subsystems already built this session -- it adds no new mechanics,
only wires them in the canonical RECALL -> LOOP -> WRITE order and renders the
10-stage end-to-end trace.

Wired subsystems (all real, deterministic, offline, no LLM):
  - cognia.context.band_router.HydraContextRouter  (3-band HYDRA context router)
  - cognia.reasoning.cognitive_loop.CognitiveLoop   (FAST/RECALL/DELIBERATE/ACT;
        internally drives the band router, planner, self-critic, verifier, the
        world-model action simulator, and the tool registry)
  - cognia.memory.hierarchical.HierarchicalMemory   (recall + surprise-gated write)

The world-model "simulate before act" predictor
(cognia.reasoning.action_simulator.ActionSimulator) is invoked INSIDE the
cognitive loop's ACT route; its prediction surfaces here as
loop_trace.prediction (stage [7]).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import List, Optional


def _ascii(text: str) -> str:
    """Force ASCII so Windows CP1252 stdout never raises on non-ASCII chars."""
    return str(text).encode("ascii", "replace").decode("ascii")


@dataclass
class ChimeraResult:
    query: str
    loop_trace: object          # cognia.reasoning.cognitive_loop.LoopTrace
    recalled: List[str]         # memory items recalled BEFORE the loop ran
    write_result: object        # cognia.memory.hierarchical.WriteResult


class ChimeraSystem:
    """
    End-to-end Chimera inference loop over a single query.

    Construction is defensive: each subsystem is built once and wrapped so a
    missing/empty DB never crashes the system. run() likewise never raises.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

        # Cognitive loop -- itself drives band router + planner + critic +
        # verifier + world-model simulator + tools. Built once.
        self._loop = None
        try:
            from cognia.reasoning.cognitive_loop import CognitiveLoop
            self._loop = CognitiveLoop(db_path=db_path)
        except Exception:
            self._loop = None

        # Hierarchical memory -- recall (pre-loop) + surprise-gated write (post-loop).
        self._memory = None
        try:
            from cognia.memory.hierarchical import HierarchicalMemory
            self._memory = HierarchicalMemory(db_path=db_path)
        except Exception:
            self._memory = None

        # Standalone HYDRA router -- the loop owns its own internally, but the
        # capstone holds one too so band routing is available even if the loop
        # failed to construct. Built once.
        self._router = None
        try:
            from cognia.context.band_router import HydraContextRouter
            self._router = HydraContextRouter(db_path=db_path)
        except Exception:
            self._router = None

    def run(self, query: str) -> ChimeraResult:
        """Run RECALL -> COGNITIVE LOOP -> WRITE over one query. Never raises."""
        query = query or ""

        # [1] RECALL: pull prior memory BEFORE reasoning, so the turn is grounded
        # in what is already stored (real episodic+semantic retrieval).
        recalled: List[str] = []
        if self._memory is not None:
            try:
                recalled = self._memory.recall(query, top_k=5)
            except Exception:
                recalled = []

        # [2] COGNITIVE LOOP: classify + execute one of FAST/RECALL/DELIBERATE/ACT.
        # This internally runs the band router, planner, critic, verifier, the
        # world-model simulator and any tools. Falls back to a standalone band
        # route if the loop is unavailable so the trace still carries HYDRA data.
        loop_trace = None
        if self._loop is not None:
            try:
                loop_trace = self._loop.process(query)
            except Exception:
                loop_trace = None
        if loop_trace is None:
            loop_trace = self._fallback_trace(query)

        # [3] WRITE: persist the interaction through the surprise/importance gate.
        # WHY store Q+A together: the durable episode should capture both the ask
        # and the loop's answer so future recall sees the full turn.
        write_result = None
        if self._memory is not None:
            try:
                observation = "Q: %s | A: %s" % (query, getattr(loop_trace, "output", ""))
                write_result = self._memory.write(observation, label="chimera_turn")
            except Exception:
                write_result = None
        if write_result is None:
            write_result = self._fallback_write()

        return ChimeraResult(
            query=query,
            loop_trace=loop_trace,
            recalled=recalled,
            write_result=write_result,
        )

    # -- Fallbacks (only used if a subsystem failed to construct) ----------

    def _fallback_trace(self, query: str):
        """Minimal LoopTrace-shaped object when the cognitive loop is unavailable."""
        from cognia.reasoning.cognitive_loop import LoopDecision, LoopTrace
        hydra = None
        if self._router is not None:
            try:
                hydra = self._router.route(query)
            except Exception:
                hydra = None
        decision = LoopDecision(
            route="FAST", confidence=0.0,
            reasons=["cognitive loop unavailable; standalone band route only"],
            complexity="3/normal",
        )
        return LoopTrace(
            query=query, decision=decision, hydra=hydra, plan=None,
            critique=None, verify=None, tools_invoked=None,
            output=_ascii("(cognitive loop unavailable for: %s)" % query),
            prediction=None,
        )

    @staticmethod
    def _fallback_write():
        """Minimal WriteResult-shaped object when memory is unavailable."""
        from cognia.memory.hierarchical import WriteResult
        return WriteResult(
            stored_episodic=False, in_working=False, surprise=1.0,
            importance=0.0, gate_score=0.0, ep_id=None,
            reason="memory backend unavailable",
        )

    # -- Reporting --------------------------------------------------------

    def format_report(self, result: ChimeraResult) -> str:
        """Single ASCII, 10-stage end-to-end trace (whitepaper section 11)."""
        t = result.loop_trace
        d = getattr(t, "decision", None)
        h = getattr(t, "hydra", None)
        lines: List[str] = []

        lines.append("=" * 64)
        lines.append("CHIMERA END-TO-END TRACE")
        lines.append("=" * 64)

        # INPUT
        lines.append("INPUT: " + _clean(result.query, 200))

        # [1] HYDRA BANDS
        lines.append("")
        lines.append("[1] HYDRA BANDS:")
        if h is not None:
            lines.append("  persona=%s (temp=%.2f, confidence=%.2f)" % (
                getattr(h, "persona", "?"),
                float(getattr(h, "temperature", 0.0)),
                float(getattr(h, "persona_confidence", 0.0)),
            ))
            bands = getattr(h, "bands", []) or []
            active = [b.name for b in bands if getattr(b, "active", False)]
            lines.append("  active bands: " + (", ".join(active) if active else "(none)"))
            for b in bands:
                lines.append("    %-6s active=%s score=%.2f" % (
                    b.name, getattr(b, "active", False), float(getattr(b, "score", 0.0))
                ))
            lines.append("  retrieved items:")
            any_item = False
            for b in bands:
                items = getattr(b, "items", []) or []
                if getattr(b, "active", False) and items:
                    any_item = True
                    for it in items:
                        lines.append("    [%s] %s" % (b.name, _clean(it)))
            if not any_item:
                lines.append("    (none)")
        else:
            lines.append("  (HYDRA unavailable)")

        # [2] COGNITIVE LOOP ROUTE
        lines.append("")
        lines.append("[2] COGNITIVE LOOP ROUTE:")
        if d is not None:
            lines.append("  route=%s confidence=%.2f complexity=%s" % (
                getattr(d, "route", "?"),
                float(getattr(d, "confidence", 0.0)),
                getattr(d, "complexity", "?"),
            ))
            lines.append("  reasons:")
            for r in getattr(d, "reasons", []) or []:
                lines.append("    - " + _clean(r))
        else:
            lines.append("  (decision unavailable)")

        # [3] MEMORY RECALLED (from the pre-loop recall step)
        lines.append("")
        lines.append("[3] MEMORY RECALLED:")
        if result.recalled:
            for it in result.recalled:
                lines.append("    - " + _clean(it))
        else:
            lines.append("    (no prior memories matched)")

        # [4] PLAN (DELIBERATE only)
        lines.append("")
        lines.append("[4] PLAN:")
        plan = getattr(t, "plan", None)
        if plan:
            for i, st in enumerate(plan):
                lines.append("    %d. %s (tool=%s)" % (
                    i + 1, _clean(getattr(st, "description", ""), 120),
                    getattr(st, "tool_required", "?"),
                ))
        else:
            lines.append("    (n/a)")

        # [5] CRITIQUE
        lines.append("")
        lines.append("[5] CRITIQUE:")
        critique = getattr(t, "critique", None)
        if critique:
            scores = critique.get("scores", {}) or {}
            overall = scores.get("overall", None)
            if overall is not None:
                lines.append("    score(overall)=%.2f : %s" % (
                    float(overall), _clean(critique.get("critique", ""))))
            else:
                lines.append("    " + _clean(critique.get("critique", "")))
            if scores:
                lines.append("    scores: " + ", ".join(
                    "%s=%.2f" % (k, float(v)) for k, v in scores.items()))
        else:
            lines.append("    (n/a)")

        # [6] VERIFY
        lines.append("")
        lines.append("[6] VERIFY:")
        verify = getattr(t, "verify", None)
        if verify is not None:
            verdict = "PASS" if getattr(verify, "passed", False) else "FAIL"
            lines.append("    verdict=%s score=%.2f reason=%s" % (
                verdict,
                float(getattr(verify, "score", 0.0)),
                _clean(str(getattr(verify, "fail_reason", None))),
            ))
        else:
            lines.append("    (n/a)")

        # [7] WORLD-MODEL PREDICTION (ACT only)
        lines.append("")
        lines.append("[7] WORLD-MODEL PREDICTION:")
        p = getattr(t, "prediction", None)
        if p is not None:
            lines.append("    effect: " + _clean(getattr(p, "predicted_effect", "")))
            lines.append("    risk=%.2f uncertainty=%.2f reversible=%s" % (
                float(getattr(p, "risk", 0.0)),
                float(getattr(p, "uncertainty", 0.0)),
                getattr(p, "reversible", "?"),
            ))
            lines.append("    recommendation: %s" % getattr(p, "recommendation", "?"))
            for r in getattr(p, "reasons", []) or []:
                lines.append("      - " + _clean(r))
        else:
            lines.append("    (n/a)")

        # [8] TOOLS INVOKED (ACT only)
        lines.append("")
        lines.append("[8] TOOLS INVOKED:")
        tools = getattr(t, "tools_invoked", None)
        if tools:
            for name, res in tools:
                if res is None:
                    lines.append("    - %s: GATED (not executed)" % name)
                else:
                    lines.append("    - %s: success=%s result=%s" % (
                        name,
                        getattr(res, "success", "?"),
                        _clean(str(getattr(res, "output", res)), 120),
                    ))
        else:
            lines.append("    (n/a)")

        # [9] OUTPUT
        lines.append("")
        lines.append("[9] OUTPUT:")
        for ol in str(getattr(t, "output", "")).splitlines() or [""]:
            lines.append("    " + _ascii(ol))

        # [10] MEMORY WRITTEN
        lines.append("")
        lines.append("[10] MEMORY WRITTEN:")
        w = result.write_result
        lines.append("    stored_episodic=%s surprise=%.3f importance=%.3f "
                     "gate_score=%.3f reason=%s" % (
                         getattr(w, "stored_episodic", False),
                         float(getattr(w, "surprise", 0.0)),
                         float(getattr(w, "importance", 0.0)),
                         float(getattr(w, "gate_score", 0.0)),
                         _clean(getattr(w, "reason", "")),
                     ))

        lines.append("=" * 64)
        return _ascii("\n".join(lines))


def _clean(text: str, max_len: int = 160) -> str:
    """Collapse whitespace + force ASCII for safe single-line display."""
    import re
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


# Demo queries -- one per cognitive-loop route (FAST/RECALL/DELIBERATE/ACT).
_DEMO_QUERIES = [
    "hola",                                                              # FAST
    "recuerda lo que dijiste antes sobre la arquitectura de shards",     # RECALL
    "refactoriza el orchestrator paso a paso e implementa y prueba",     # DELIBERATE
    "calcula 2+2",                                                       # ACT
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chimera CAPSTONE: full end-to-end inference loop "
                    "(HYDRA bands + cognitive loop + hierarchical memory), offline."
    )
    parser.add_argument(
        "query", nargs="?", default=None,
        help="Query to run. If omitted, runs 4 demo queries (one per route).",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Override DB path (default: cognia.config.DB_PATH).",
    )
    args = parser.parse_args(argv)

    system = ChimeraSystem(db_path=args.db_path)
    queries = [args.query] if args.query else _DEMO_QUERIES

    for i, q in enumerate(queries):
        if i:
            print("")
        result = system.run(q)
        report = system.format_report(result)
        # ASCII-safe print for Windows CP1252 stdout.
        print(report.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
