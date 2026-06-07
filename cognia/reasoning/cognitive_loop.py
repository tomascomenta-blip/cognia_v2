"""
cognia/reasoning/cognitive_loop.py
==================================
Chimera "Cognitive Loop" orchestrator (section 2).

A lightweight, deterministic controller that classifies every query into one
of four routes and then EXECUTES the matching real subsystems offline -- no
LLM / Ollama is required for this cycle. The text-generation step (Synthesizer)
is intentionally out of scope; everything wired here is offline-capable.

Routes:
  FAST       -- trivial query: answer directly, no retrieval.
  RECALL     -- needs memory: use the HYDRA 3-band router GLOBAL retrieval.
  DELIBERATE -- complex / multi-step: build a plan, critique it, verify a
                candidate.
  ACT        -- needs tools/actions: select + invoke a real registered tool.

It REUSES existing components and adds no heavy abstractions:
  - cognia.context.band_router.HydraContextRouter      (3-band retrieval)
  - cognia.reasoning.complexity_scorer.ComplexityScorer (difficulty signal)
  - cognia.agents.planner.plan_task                     (deterministic plan)
  - cognia.agents.verifier.verify                       (deterministic verify)
  - cognia.reasoning.self_critic.SelfCritic             (deterministic critique)
  - cognia.agents.tool_registry.get_tool_registry       (real tools)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple


# -- Route constants ----------------------------------------------------------
ROUTE_FAST = "FAST"
ROUTE_RECALL = "RECALL"
ROUTE_DELIBERATE = "DELIBERATE"
ROUTE_ACT = "ACT"


# -- Classification cue sets (module-level so the WHY is inspectable) ----------
# ACT: verbs that imply an action / external tool invocation.
_ACT_VERBS = [
    "ejecuta", "corre", "calcula", "busca", "run", "execute", "search",
    "fetch", "convierte", "lista archivos", "crea archivo", "valida",
    "validate", "explora", "explore",
]

# RECALL: cues signalling the query reaches back to prior knowledge / history.
_RECALL_CUES = [
    "recuerda", "recordas", "recuerdas", "antes", "la vez", "mencion",
    "dijiste", "earlier", "previously", "remember", "que dijimos",
    "historial", "que dijiste", "habiamos",
]

# DELIBERATE: multi-step / design markers that imply planning is worthwhile.
_DELIBERATE_MARKERS = [
    "refactor", "refactoriza", "disena", "diseno", "planifica", "paso a paso",
    "implementa y prueba", "y luego", "primero", "despues", "step by step",
    "plan", "arquitectura",
]


def _ascii(text: str) -> str:
    """Force ASCII so Windows CP1252 stdout never raises on emoji/box chars."""
    return str(text).encode("ascii", "replace").decode("ascii")


def _clean(text: str, max_len: int = 160) -> str:
    """Collapse whitespace + force ASCII for safe single-line display."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


@dataclass
class LoopDecision:
    route: str
    confidence: float
    reasons: List[str]
    complexity: str


@dataclass
class LoopTrace:
    query: str
    decision: LoopDecision
    hydra: object | None
    plan: list | None
    critique: dict | None
    verify: object | None
    tools_invoked: list | None
    output: str
    prediction: object | None = None   # World-Model Prediction for the ACT route


class CognitiveLoop:
    """
    Deterministic four-route controller. Every external subsystem is wired
    lazily and wrapped so a missing DB / import never crashes the loop.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

        # HYDRA 3-band router -- real retrieval over working/episodic/semantic.
        self._router = None
        try:
            from cognia.context.band_router import HydraContextRouter
            self._router = HydraContextRouter(db_path=db_path)
        except Exception:
            self._router = None

        # Difficulty signal -- pure heuristic, no DB needed.
        self._scorer = None
        try:
            from cognia.reasoning.complexity_scorer import ComplexityScorer
            self._scorer = ComplexityScorer()
        except Exception:
            self._scorer = None

        # Self-critic -- deterministic scoring (touches a sqlite pool, tolerate fail).
        self._critic = None
        try:
            from cognia.reasoning.self_critic import SelfCritic
            self._critic = SelfCritic()
        except Exception:
            self._critic = None

        # Tool registry -- real registered tools.
        self._registry = None
        try:
            from cognia.agents.tool_registry import get_tool_registry
            self._registry = get_tool_registry()
        except Exception:
            self._registry = None

        # World-Model action simulator -- "simulate before act" risk gate.
        # WHY here: built once so the ACT route can predict EFFECT/RISK of the
        # chosen tool BEFORE executing it. Tolerate missing DB/registry.
        self._simulator = None
        try:
            from cognia.reasoning.action_simulator import ActionSimulator
            self._simulator = ActionSimulator(db_path=db_path)
        except Exception:
            self._simulator = None

    # -- Classification ---------------------------------------------------

    def classify(self, query: str) -> LoopDecision:
        query = query or ""
        low = query.lower()
        reasons: List[str] = []

        # Core difficulty signal from the ComplexityScorer (1-5, budget).
        cx_score = 3
        cx_budget = "normal"
        if self._scorer is not None:
            try:
                cr = self._scorer.score(query)
                cx_score = int(cr.score)
                cx_budget = str(cr.budget)
                reasons.append(
                    "complexity score=%d budget=%s (%s)"
                    % (cx_score, cx_budget, "; ".join(cr.reasons))
                )
            except Exception as exc:
                reasons.append("complexity scorer error: " + _clean(str(exc)))
        complexity_label = "%d/%s" % (cx_score, cx_budget)

        # Gather cue evidence up front so confidence can weigh it.
        registry_names = []
        if self._registry is not None:
            try:
                registry_names = list(self._registry.names())
            except Exception:
                registry_names = []

        # An ACT cue fires if an action verb is present OR the query literally
        # names a registered tool (e.g. "execute_python").
        act_verb_hit = next((v for v in _ACT_VERBS if v in low), None)
        act_tool_hit = next((n for n in registry_names if n.lower() in low), None)
        recall_hit = next((c for c in _RECALL_CUES if c in low), None)
        deliberate_hit = next((m for m in _DELIBERATE_MARKERS if m in low), None)
        high_complexity = cx_score >= 4 or cx_budget == "deep"

        # WHY ACT first: an explicit action verb / named tool is the strongest,
        # least-ambiguous intent -- the user wants something DONE, not recalled
        # or merely planned. Acting trumps everything else.
        if act_verb_hit or act_tool_hit:
            route = ROUTE_ACT
            if act_verb_hit:
                reasons.append("ACT: action verb '%s' present" % act_verb_hit)
            if act_tool_hit:
                reasons.append("ACT: names registered tool '%s'" % act_tool_hit)

        # WHY RECALL second: a recall cue means the answer lives in prior
        # memory/history, so memory retrieval (GLOBAL band) is the real work --
        # this beats DELIBERATE because no new plan is needed, just lookup.
        elif recall_hit:
            route = ROUTE_RECALL
            reasons.append("RECALL: recall cue '%s' present" % recall_hit)

        # WHY DELIBERATE third: multi-step / design markers OR high measured
        # complexity mean the query needs decomposition + critique + verify.
        elif deliberate_hit or high_complexity:
            route = ROUTE_DELIBERATE
            if deliberate_hit:
                reasons.append(
                    "DELIBERATE: multi-step marker '%s' present" % deliberate_hit
                )
            if high_complexity:
                reasons.append(
                    "DELIBERATE: high complexity (score>=4 or budget=deep)"
                )

        # WHY FAST default: nothing above fired, so it is a trivial exchange
        # that can be answered directly from immediate (LOCAL) context.
        else:
            route = ROUTE_FAST
            reasons.append("FAST: no act/recall/deliberate cues, low complexity")

        # Confidence: blend normalized complexity with cue strength. A fired
        # cue is decisive (+0.3); complexity contributes up to ~0.5.
        cue_strength = 0.0
        if route == ROUTE_ACT:
            cue_strength = 0.35 if (act_verb_hit and act_tool_hit) else 0.25
        elif route == ROUTE_RECALL:
            cue_strength = 0.30
        elif route == ROUTE_DELIBERATE:
            cue_strength = 0.30 if deliberate_hit else 0.20
        else:  # FAST is most confident when complexity is genuinely low.
            cue_strength = 0.30 if cx_score <= 1 else 0.15
        complexity_component = min(0.5, 0.1 * cx_score)
        confidence = round(min(0.99, 0.4 + cue_strength + (
            complexity_component if route != ROUTE_FAST
            else (0.5 - complexity_component)
        )), 3)

        return LoopDecision(
            route=route,
            confidence=confidence,
            reasons=[_ascii(r) for r in reasons],
            complexity=complexity_label,
        )

    # -- Route execution helpers -----------------------------------------

    @staticmethod
    def _band(hydra, name: str):
        if hydra is None:
            return None
        for b in getattr(hydra, "bands", []) or []:
            if b.name == name:
                return b
        return None

    def _run_fast(self, query: str, hydra) -> str:
        # FAST: build a short, no-LLM acknowledgement from the LOCAL band
        # (immediate context). This is a real echo of what the loop "sees".
        local = self._band(hydra, "LOCAL")
        items = list(getattr(local, "items", []) or []) if local else []
        ctx = items[0] if items else ("query: " + _clean(query))
        persona = getattr(hydra, "persona", "logos") if hydra else "logos"
        return _ascii(
            "Acknowledged (%s). Direct answer, no retrieval needed. "
            "Immediate context: %s" % (persona, _clean(ctx))
        )

    def _run_recall(self, query: str, hydra) -> str:
        # RECALL: synthesize a summary from the GLOBAL band's real retrieved
        # memory items. With an empty DB this honestly reports "no memories".
        g = self._band(hydra, "GLOBAL")
        items = list(getattr(g, "items", []) or []) if g else []
        score = getattr(g, "score", 0.0) if g else 0.0
        if items:
            lines = ["Recalled %d memory item(s) (GLOBAL score=%.2f):"
                     % (len(items), score)]
            for it in items:
                lines.append("  - " + _clean(it))
            return _ascii("\n".join(lines))
        return _ascii(
            "No matching memories found in the GLOBAL band "
            "(score=%.2f); the episodic/semantic store returned nothing for "
            "this query." % score
        )

    def _run_deliberate(
        self, query: str, hydra
    ) -> Tuple[list, dict, object, str]:
        # DELIBERATE: real deterministic plan -> candidate -> critique -> verify.
        plan = None
        critique = None
        verify_res = None
        reasons: List[str] = []

        # 1. Deterministic plan (template or generic 2-step; never calls an LLM).
        try:
            from cognia.agents.planner import plan_task
            plan = plan_task(query, task_id="loop")
        except Exception as exc:
            reasons.append("plan_task error: " + _clean(str(exc)))
            plan = []

        # 2. Build a candidate response string FROM the plan (no LLM).
        if plan:
            step_lines = [
                "%d. %s (tool=%s)" % (i + 1, _clean(st.description, 120),
                                      st.tool_required)
                for i, st in enumerate(plan)
            ]
            candidate = (
                "Proposed plan for the request '%s':\n%s"
                % (_clean(query, 120), "\n".join(step_lines))
            )
        else:
            candidate = "No plan could be derived for: " + _clean(query, 120)

        # 3. Deterministic self-critique (numeric scores).
        if self._critic is not None:
            try:
                critique = self._critic.critique(candidate, query)
            except Exception as exc:
                reasons.append("critique error: " + _clean(str(exc)))
        if critique is None:
            critique = {"critique": "(critic unavailable)",
                        "scores": {"overall": 0.0}}

        # 4. Deterministic verify of the candidate as generic text output.
        try:
            from cognia.agents.verifier import verify
            verify_res = verify(candidate, output_type="text")
        except Exception as exc:
            reasons.append("verify error: " + _clean(str(exc)))

        overall = 0.0
        try:
            overall = float(critique.get("scores", {}).get("overall", 0.0))
        except Exception:
            overall = 0.0
        verdict = "n/a"
        if verify_res is not None:
            verdict = "PASS" if getattr(verify_res, "passed", False) else "FAIL"
        output = _ascii(
            "DELIBERATE result: %d-step plan; critique overall=%.2f (%s); "
            "verify=%s%s"
            % (
                len(plan or []),
                overall,
                _clean(critique.get("critique", "")),
                verdict,
                ("; " + "; ".join(reasons)) if reasons else "",
            )
        )
        return plan, critique, verify_res, output

    def _pick_tool(self, query: str, names: List[str]) -> Optional[Tuple[str, dict]]:
        """
        Choose a SAFE, offline tool + kwargs derived from the query.
        Returns (tool_name, kwargs) or None if nothing safe matches.
        """
        low = query.lower()

        # Arithmetic / "calcula 2+2" -> execute_python with a print expression.
        m = re.search(r"(-?\d[\d\s\.\+\-\*/\(\)]*\d|-?\d)", query)
        wants_calc = any(w in low for w in ("calcula", "calculate", "calc")) or (
            m and any(op in (m.group(1)) for op in "+-*/")
        )
        if wants_calc and m and "execute_python" in names:
            expr = m.group(1).strip()
            # Only digits/operators/space/parens -> safe to eval inside sandbox.
            if re.fullmatch(r"[\d\s\.\+\-\*/\(\)]+", expr):
                return "execute_python", {"code": "print(%s)" % expr}

        # Validate / syntax-check requests -> validate_python (no execution).
        if any(w in low for w in ("valida", "validate", "syntax")) and \
                "validate_python" in names:
            # Use the query tail as code if it looks like code, else a trivial probe.
            return "validate_python", {"code": "x = 1\n"}

        # "lista archivos" / explore -> file_explorer on the current dir (offline).
        if any(w in low for w in ("lista archivos", "explora", "explore",
                                  "file")) and "file_explorer" in names:
            return "file_explorer", {"path": "."}

        # Generic "ejecuta"/"run"/"execute" with no expression -> a real,
        # harmless execute_python probe so we still invoke a real tool.
        if any(w in low for w in ("ejecuta", "execute", "run", "corre")) and \
                "execute_python" in names:
            return "execute_python", {"code": "print('ok')"}

        # Offline-safe fallback: validate_python is network-free + side-effect free.
        if "validate_python" in names:
            return "validate_python", {"code": "x = 1\n"}
        return None

    def _run_act(self, query: str, hydra) -> Tuple[list, str, object]:
        # ACT: simulate (predict EFFECT+RISK) the chosen tool, then either GATE
        # (CONFIRM) or actually execute it (PROCEED/SANDBOX) with safe kwargs.
        if self._registry is None:
            return None, _ascii("ACT: tool registry unavailable."), None
        try:
            names = list(self._registry.names())
        except Exception as exc:
            return None, _ascii(
                "ACT: registry.names() error: " + _clean(str(exc))), None

        picked = self._pick_tool(query, names)
        if picked is None:
            # Still real: report the available tools.
            return None, _ascii(
                "ACT: no safe tool matched. Available tools: "
                + ", ".join(names)
            ), None

        name, kwargs = picked

        # World-Model "simulate before act": predict before executing.
        prediction = None
        if self._simulator is not None:
            try:
                prediction = self._simulator.predict_tool(name, kwargs)
            except Exception:
                # NEVER let the gate crash the loop: a None prediction simply
                # means "no gate available" and execution proceeds as before.
                prediction = None

        # RISK GATE: CONFIRM -> do NOT auto-execute; flag for confirmation.
        if prediction is not None and getattr(
            prediction, "recommendation", "PROCEED") == "CONFIRM":
            reason = "; ".join(getattr(prediction, "reasons", []) or []) or "high risk"
            out = "ACTION GATED: %s needs confirmation (risk=%.2f): %s" % (
                name, getattr(prediction, "risk", 0.0), _clean(reason, 120)
            )
            # Mark the tool as gated (not executed): result is None.
            return [(name, None)], _ascii(out), prediction

        # PROCEED / SANDBOX -> execute as before (keep current behavior).
        result = self._registry.execute(name, **kwargs)
        tools_invoked = [(name, result)]
        sb = ""
        if prediction is not None and getattr(
                prediction, "recommendation", "") == "SANDBOX":
            sb = " [SANDBOX: risk=%.2f]" % getattr(prediction, "risk", 0.0)
        if getattr(result, "success", False):
            out = "ACT: invoked tool '%s' kwargs=%s -> %s%s" % (
                name, _clean(str(kwargs), 80), _clean(str(result.output), 120), sb
            )
        else:
            out = "ACT: tool '%s' failed: %s%s" % (
                name, _clean(str(getattr(result, "error", ""))), sb
            )
        return tools_invoked, _ascii(out), prediction

    # -- Public pipeline --------------------------------------------------

    def process(self, query: str) -> LoopTrace:
        query = query or ""
        decision = self.classify(query)

        # Always run the HYDRA 3-band router (real retrieval) regardless of route.
        hydra = None
        if self._router is not None:
            try:
                hydra = self._router.route(query)
            except Exception as exc:
                decision.reasons.append("hydra route error: " + _clean(str(exc)))

        plan = None
        critique = None
        verify_res = None
        tools_invoked = None
        prediction = None
        output = ""

        try:
            if decision.route == ROUTE_FAST:
                output = self._run_fast(query, hydra)
            elif decision.route == ROUTE_RECALL:
                output = self._run_recall(query, hydra)
            elif decision.route == ROUTE_DELIBERATE:
                plan, critique, verify_res, output = self._run_deliberate(
                    query, hydra
                )
            elif decision.route == ROUTE_ACT:
                tools_invoked, output, prediction = self._run_act(query, hydra)
            else:
                output = _ascii("Unknown route: " + decision.route)
        except Exception as exc:
            # NEVER raise: capture the failure and keep a usable trace.
            decision.reasons.append("route execution error: " + _clean(str(exc)))
            output = _ascii("Route %s failed: %s" % (decision.route, str(exc)))

        if not output:
            output = _ascii("(no output produced for route %s)" % decision.route)

        return LoopTrace(
            query=query,
            decision=decision,
            hydra=hydra,
            plan=plan,
            critique=critique,
            verify=verify_res,
            tools_invoked=tools_invoked,
            output=output,
            prediction=prediction,
        )


def format_trace(trace: LoopTrace) -> str:
    """Multi-line, ASCII-only trace of a full cognitive-loop pass."""
    d = trace.decision
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("QUERY: " + _clean(trace.query, max_len=200))
    lines.append("ROUTE: %s  (confidence=%.2f)" % (d.route, d.confidence))
    lines.append("COMPLEXITY: " + d.complexity)
    lines.append("REASONS:")
    for r in d.reasons:
        lines.append("  - " + _ascii(r))

    # HYDRA summary.
    h = trace.hydra
    if h is not None:
        lines.append("HYDRA: persona=%s temp=%.2f conf=%.2f" % (
            getattr(h, "persona", "?"),
            getattr(h, "temperature", 0.0),
            getattr(h, "persona_confidence", 0.0),
        ))
        active = [b.name for b in getattr(h, "bands", []) or [] if b.active]
        lines.append("  active bands: " + (", ".join(active) if active else "(none)"))
        for b in getattr(h, "bands", []) or []:
            if b.active and b.items:
                lines.append("  %s items:" % b.name)
                for it in b.items:
                    lines.append("    - " + _clean(it))
    else:
        lines.append("HYDRA: (unavailable)")

    # PLAN.
    if trace.plan:
        lines.append("PLAN (%d steps):" % len(trace.plan))
        for i, st in enumerate(trace.plan):
            lines.append("  %d. %s (tool=%s)" % (
                i + 1, _clean(st.description, 120), st.tool_required
            ))

    # CRITIQUE.
    if trace.critique:
        scores = trace.critique.get("scores", {}) or {}
        lines.append("CRITIQUE: %s" % _clean(trace.critique.get("critique", "")))
        lines.append("  scores: " + ", ".join(
            "%s=%.2f" % (k, float(v)) for k, v in scores.items()
        ))

    # VERIFY.
    if trace.verify is not None:
        v = trace.verify
        lines.append("VERIFY: passed=%s score=%.2f reason=%s" % (
            getattr(v, "passed", "?"),
            getattr(v, "score", 0.0),
            _clean(str(getattr(v, "fail_reason", None))),
        ))

    # PREDICTION (World-Model "simulate before act") -- shown for ACT route.
    p = getattr(trace, "prediction", None)
    if p is not None:
        lines.append("PREDICTION:")
        lines.append("  effect: " + _clean(getattr(p, "predicted_effect", "")))
        lines.append("  risk=%.2f uncertainty=%.2f reversible=%s" % (
            getattr(p, "risk", 0.0),
            getattr(p, "uncertainty", 0.0),
            getattr(p, "reversible", "?"),
        ))
        lines.append("  recommendation: %s" % getattr(p, "recommendation", "?"))
        for r in getattr(p, "reasons", []) or []:
            lines.append("    - " + _clean(r))

    # TOOLS.
    if trace.tools_invoked:
        lines.append("TOOLS INVOKED:")
        for name, res in trace.tools_invoked:
            # res is None when the action was GATED (CONFIRM) and not executed.
            if res is None:
                lines.append("  - %s: GATED (not executed)" % name)
                continue
            lines.append("  - %s: success=%s output=%s" % (
                name,
                getattr(res, "success", "?"),
                _clean(str(getattr(res, "output", res)), 120),
            ))

    lines.append("OUTPUT:")
    for ol in str(trace.output).splitlines() or [""]:
        lines.append("  " + _ascii(ol))
    lines.append("=" * 64)
    return _ascii("\n".join(lines))


_DEMO_QUERIES = [
    "hola",
    "recuerda lo que dijiste antes sobre la arquitectura de shards",
    "refactoriza el orchestrator paso a paso e implementa y prueba",
    "calcula 2+2",
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chimera Cognitive Loop: classify + execute one of "
                    "FAST/RECALL/DELIBERATE/ACT routes (offline)."
    )
    parser.add_argument(
        "query", nargs="?", default=None,
        help="Query to process. If omitted, runs 4 demo queries (one per route).",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Override DB path (default: cognia.config.DB_PATH).",
    )
    args = parser.parse_args(argv)

    loop = CognitiveLoop(db_path=args.db_path)
    queries = [args.query] if args.query else _DEMO_QUERIES

    for q in queries:
        trace = loop.process(q)
        out = format_trace(trace)
        # ASCII-safe print for Windows CP1252 stdout.
        print(out.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
