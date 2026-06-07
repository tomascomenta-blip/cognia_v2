"""
cognia/reasoning/action_simulator.py
=====================================
Chimera World-Model "simulate before act" component (sections 6 + 8.2).

PURPOSE: predict the EFFECT and RISK of a candidate tool action BEFORE it is
executed, so the Cognitive Loop's ACT route can GATE risky/irreversible actions
(flag for confirmation / sandbox) instead of auto-executing them.

It is fully deterministic and offline: no LLM, no network. Risk is computed from
- tool.requires_network (network is an external, often irreversible side-effect),
- destructive verbs/patterns found in the tool name + stringified kwargs,
- code-execution tools whose payload writes/deletes/imports os/subprocess,
- whether the tool is read-only (reversible) vs side-effecting (irreversible),
- the World-Model knowledge graph (known consequences of touched entities),
- and an UNCERTAINTY term that rises when the tool is unknown or the KG is empty.

It REUSES existing components and adds no heavy abstractions:
  - cognia.agents.tool_registry.get_tool_registry  (real tool metadata)
  - cognia.reasoning.world_model.WorldModelModule   (KG consequence lookup)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# -- Risk band thresholds -----------------------------------------------------
# WHY three bands: a single yes/no gate is too blunt. PROCEED auto-executes
# trivially-safe reads; SANDBOX still runs but flags caution for medium risk;
# CONFIRM blocks auto-execution for anything that is destructive/irreversible.
RISK_LOW = 0.0     # floor; purely informational
RISK_MED = 0.35    # >= this -> SANDBOX (run but flagged); below -> PROCEED
RISK_HIGH = 0.70   # >= this -> CONFIRM (do NOT auto-execute)


# -- Destructive verbs / patterns ---------------------------------------------
# WHY these tokens: each names an operation that mutates or destroys external
# state (filesystem, processes, DB). Their presence in a tool name or in the
# stringified kwargs is strong evidence the action is irreversible.
_DESTRUCTIVE_PATTERNS = [
    "delete", "rm ", "remove", "drop", "format", "overwrite",
    "truncate", "kill", "shutdown", "write", "unlink", "del ",
    "erase", "wipe", "destroy", "purge",
]

# WHY these tools: tools that, by construction, can cause side-effects beyond a
# pure read. Code execution can do anything; network/research tools reach out.
_SIDE_EFFECT_TOOLS = {
    "execute_python", "research", "search_wikipedia", "research_llm",
    "file_writer", "shell", "exec",
}

# WHY read-only set: these are known-safe lookups/validations/calculations with
# no external mutation -> reversible and low base risk.
_READ_ONLY_TOOLS = {
    "validate_python", "query_episodic", "file_explorer", "calc",
    "search", "lookup", "validate",
}

# WHY these substrings inside execute_python code: importing os/subprocess or
# opening files for write means the "harmless" code path can mutate the host.
_CODE_DANGER_TOKENS = [
    "import os", "import subprocess", "import shutil", "import sys",
    "open(", "os.", "subprocess", "shutil", "remove(", "rmtree",
    "unlink", "system(", "popen", "__import__", "eval(", "exec(",
]


def _ascii(text: object) -> str:
    """Force ASCII so Windows CP1252 stdout never raises on non-ASCII chars."""
    return str(text).encode("ascii", "replace").decode("ascii")


def _tokens(text: str) -> List[str]:
    """Lowercase word tokens used as candidate KG entity keys."""
    return [t for t in re.split(r"[^a-zA-Z0-9_]+", str(text).lower()) if len(t) > 2]


@dataclass
class Prediction:
    action:          str
    predicted_effect: str
    risk:            float          # 0..1
    uncertainty:     float          # 0..1
    reversible:      bool
    recommendation:  str            # PROCEED | SANDBOX | CONFIRM
    reasons:         List[str] = field(default_factory=list)


class ActionSimulator:
    """
    Deterministic, offline world-model simulator. Tolerates a missing/empty DB
    and missing tools: it NEVER raises from predict_*/simulate.
    """

    def __init__(self, db_path: Optional[str] = None):
        # Tool registry -- real tool metadata (name, requires_network, ...).
        self._registry = None
        try:
            from cognia.agents.tool_registry import get_tool_registry
            self._registry = get_tool_registry()
        except Exception:
            self._registry = None

        # World-Model KG -- consequence lookup. Tolerate missing DB: any query
        # that hits a non-existent table is caught and treated as empty KG.
        self._wm = None
        try:
            from cognia.reasoning.world_model import WorldModelModule
            self._wm = WorldModelModule(db_path) if db_path else WorldModelModule()
        except Exception:
            self._wm = None

    # -- helpers ----------------------------------------------------------

    def _tool_names(self) -> List[str]:
        if self._registry is None:
            return []
        try:
            return list(self._registry.names())
        except Exception:
            return []

    def _kg_consequences(self, text: str) -> List[str]:
        """Consult the KG for known relations of entity tokens in `text`.

        Returns human-readable consequence strings. Tolerates empty/missing KG.
        """
        if self._wm is None:
            return []
        out: List[str] = []
        seen = set()
        for tok in _tokens(text):
            if tok in seen:
                continue
            seen.add(tok)
            try:
                rels = self._wm.get_relations(tok)
            except Exception:
                # WHY swallow: missing table / locked DB must not crash a
                # simulation -- an empty KG simply raises uncertainty.
                rels = []
            for r in rels[:2]:
                out.append(
                    "KG: %s --%s--> %s (s=%.2f)"
                    % (tok, r.get("relation", "?"),
                       r.get("entity", "?"), float(r.get("strength", 0.0)))
                )
            if len(out) >= 4:
                break
        return out

    @staticmethod
    def _destructive_hits(text: str) -> List[str]:
        low = " " + str(text).lower() + " "
        return [p.strip() for p in _DESTRUCTIVE_PATTERNS if p in low]

    @staticmethod
    def _recommend(risk: float, reversible: bool, network: bool) -> str:
        # WHY: irreversible + network is the worst combo (external, permanent
        # effect) -> force CONFIRM even if the numeric risk sits in the band.
        if risk >= RISK_HIGH or (not reversible and network):
            return "CONFIRM"
        if risk >= RISK_MED:
            return "SANDBOX"
        return "PROCEED"

    # -- core: predict a concrete tool call -------------------------------

    def predict_tool(self, tool_name: str, kwargs: Optional[dict] = None) -> Prediction:
        kwargs = kwargs or {}
        reasons: List[str] = []
        risk = 0.0
        uncertainty = 0.1

        tool = None
        if self._registry is not None:
            try:
                tool = self._registry.get(tool_name)
            except Exception:
                tool = None

        kw_str = " ".join("%s=%s" % (k, v) for k, v in kwargs.items())
        probe = (tool_name or "") + " " + kw_str

        # 1. Unknown tool -> we cannot reason about its effect -> high uncertainty.
        if tool is None:
            uncertainty += 0.4
            risk += 0.15
            reasons.append("unknown tool '%s' (not registered)" % tool_name)

        # 2. Network risk -- requires_network is the network-risk flag.
        network = bool(getattr(tool, "requires_network", False)) if tool else False
        if network:
            risk += 0.35
            reasons.append("tool requires network (external side-effect)")

        # 3. Destructive verbs/patterns in tool name OR stringified kwargs.
        hits = self._destructive_hits(probe)
        if hits:
            risk += min(0.5, 0.25 * len(set(hits)))
            reasons.append("destructive pattern(s): " + ", ".join(sorted(set(hits))))

        # 4. Code-execution payload analysis (execute_python / exec tools).
        is_exec = tool_name in ("execute_python", "exec", "shell")
        if is_exec:
            code = str(kwargs.get("code", "") or kwargs.get("cmd", ""))
            dangers = [t for t in _CODE_DANGER_TOKENS if t in code.lower()]
            if dangers:
                risk += min(0.5, 0.2 * len(set(dangers)))
                reasons.append(
                    "code-exec payload touches: " + ", ".join(sorted(set(dangers)))
                )
            else:
                # Pure arithmetic/print -> still execution but benign payload.
                reasons.append("code-exec payload looks side-effect free")

        # 5. Reversibility: read-only/validate/calc are reversible; write/delete
        #    /exec-with-side-effects are not.
        # WHY exec is judged by PAYLOAD, not by membership: execute_python is a
        # potential side-effect tool, but print(2+2) mutates nothing -- only a
        # payload touching os/subprocess/files is actually irreversible.
        exec_payload_dangerous = is_exec and any(
            t in str(kwargs).lower() for t in _CODE_DANGER_TOKENS
        )
        side_effecting = (
            (tool_name in _SIDE_EFFECT_TOOLS and not is_exec)
            or bool(hits)
            or exec_payload_dangerous
        )
        read_only = tool_name in _READ_ONLY_TOOLS or any(
            tool_name.startswith(p) for p in ("validate", "search", "query", "lookup")
        )
        if is_exec:
            # Exec is reversible iff its payload is benign (no danger tokens).
            reversible = not exec_payload_dangerous and not hits
        else:
            reversible = read_only and not side_effecting
        if not reversible:
            risk += 0.1
            reasons.append("action is NOT reversible")
        else:
            reasons.append("action is reversible (read-only/no side-effect)")

        # 6. KG consequence lookup (tolerate empty KG).
        kg = self._kg_consequences(probe)
        if kg:
            reasons.extend(kg)
            risk += 0.05  # known consequences exist -> nudge caution up.
        else:
            uncertainty += 0.2
            reasons.append("KG: no known consequences (empty/unknown entities)")

        risk = max(0.0, min(1.0, risk))
        uncertainty = max(0.0, min(1.0, uncertainty))

        effect = self._describe_effect(tool, tool_name, kwargs, network, reversible)
        rec = self._recommend(risk, reversible, network)

        return Prediction(
            action="tool:%s %s" % (tool_name, _clean_kwargs(kwargs)),
            predicted_effect=effect,
            risk=round(risk, 3),
            uncertainty=round(uncertainty, 3),
            reversible=reversible,
            recommendation=rec,
            reasons=[_ascii(r) for r in reasons],
        )

    @staticmethod
    def _describe_effect(tool, tool_name, kwargs, network, reversible) -> str:
        desc = getattr(tool, "description", "") if tool else ""
        base = desc or ("invoke tool '%s'" % tool_name)
        net = "reaches the network" if network else "stays local"
        rev = "reversible" if reversible else "IRREVERSIBLE"
        return _ascii("%s; %s; %s" % (_one_line(base), net, rev))

    # -- plan-level simulation -------------------------------------------

    def predict_plan(self, subtasks: list) -> dict:
        """Simulate each step of a plan and aggregate risk over the horizon.

        Each SubTask is mapped to its `tool_required` (real planner field).
        """
        steps: List[Prediction] = []
        for st in subtasks or []:
            tool_name = (
                getattr(st, "tool_required", None)
                or getattr(st, "tool", None)
                or getattr(st, "action", None)
                or str(st)
            )
            # WHY no kwargs at plan time: the planner does not bind concrete
            # args yet; we simulate the tool's intrinsic risk. We still feed the
            # step description so destructive verbs in the description count.
            desc = getattr(st, "description", "") or ""
            p = self.predict_tool(tool_name, {"_desc": desc})
            steps.append(p)

        risks = [p.risk for p in steps] or [0.0]
        max_risk = max(risks)
        mean_risk = sum(risks) / len(risks)
        any_confirm = any(p.recommendation == "CONFIRM" for p in steps)
        any_sandbox = any(p.recommendation == "SANDBOX" for p in steps)

        # WHY plan-level CONFIRM if any step is CONFIRM: a single irreversible
        # step taints the whole plan -- the user must approve before it runs.
        if any_confirm:
            recommendation = "CONFIRM"
        elif any_sandbox or max_risk >= RISK_MED:
            recommendation = "SANDBOX"
        else:
            recommendation = "PROCEED"

        return {
            "max_risk": round(max_risk, 3),
            "mean_risk": round(mean_risk, 3),
            "horizon": len(steps),
            "any_confirm": any_confirm,
            "steps": steps,
            "recommendation": recommendation,
        }

    # -- free-text heuristic ---------------------------------------------

    def simulate(self, free_text_action: str) -> Prediction:
        """Heuristic risk for a free-text action description (no tool binding)."""
        text = free_text_action or ""
        reasons: List[str] = []
        risk = 0.0
        uncertainty = 0.3  # free text has no structured tool metadata.

        hits = self._destructive_hits(text)
        if hits:
            risk += min(0.7, 0.3 * len(set(hits)))
            reasons.append("destructive verb(s): " + ", ".join(sorted(set(hits))))

        low = text.lower()
        # WHY broad/system targets escalate: "all files", "C:/", "disk",
        # "system32" turn a destructive verb into a catastrophic one.
        scope_tokens = ["all ", "everything", "c:/", "c:\\", "disk", "/",
                        "system32", "root", "database", "production"]
        scope = [s.strip() for s in scope_tokens if s in low]
        if scope and hits:
            risk += 0.25
            reasons.append("broad/system scope: " + ", ".join(sorted(set(scope))))

        network_words = ["http", "download", "upload", "fetch", "curl",
                         "wget", "api", "request", "send"]
        if any(w in low for w in network_words):
            risk += 0.2
            reasons.append("free-text implies network access")

        kg = self._kg_consequences(text)
        if kg:
            reasons.extend(kg)
            risk += 0.05
        else:
            uncertainty += 0.1
            reasons.append("KG: no known consequences for this description")

        # Reversible only if NO destructive verb and NO broad scope.
        reversible = not hits and not scope
        if not reversible:
            reasons.append("action is NOT reversible")
        else:
            reasons.append("no destructive verb detected -> treated reversible")

        risk = max(0.0, min(1.0, risk))
        uncertainty = max(0.0, min(1.0, uncertainty))
        network = any(w in low for w in network_words)
        rec = self._recommend(risk, reversible, network)

        return Prediction(
            action="text:" + _one_line(text, 80),
            predicted_effect=_ascii(
                "free-text action; %s" % ("IRREVERSIBLE" if not reversible
                                          else "reversible")
            ),
            risk=round(risk, 3),
            uncertainty=round(uncertainty, 3),
            reversible=reversible,
            recommendation=rec,
            reasons=[_ascii(r) for r in reasons],
        )


def _clean_kwargs(kwargs: dict) -> str:
    return _one_line(", ".join("%s=%s" % (k, v) for k, v in (kwargs or {}).items()), 80)


def _one_line(text: object, max_len: int = 120) -> str:
    t = re.sub(r"\s+", " ", str(text)).strip()
    t = t.encode("ascii", "replace").decode("ascii")
    return t[: max_len - 3] + "..." if len(t) > max_len else t


def format_prediction(p: Prediction) -> str:
    """ASCII-only multi-line rendering of a Prediction."""
    lines = [
        "-" * 60,
        "ACTION:        " + _ascii(p.action),
        "EFFECT:        " + _ascii(p.predicted_effect),
        "RISK:          %.2f   UNCERTAINTY: %.2f" % (p.risk, p.uncertainty),
        "REVERSIBLE:    %s" % p.reversible,
        "RECOMMENDATION: %s" % p.recommendation,
        "REASONS:",
    ]
    for r in p.reasons:
        lines.append("  - " + _ascii(r))
    lines.append("-" * 60)
    return _ascii("\n".join(lines))


def main(argv: Optional[List[str]] = None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    sim = ActionSimulator()

    if not argv:
        # Demo: a safe tool, a network/risky tool, and a destructive free-text.
        print("=== DEMO: simulate-before-act ===")
        names = sim._tool_names()
        safe = "validate_python" if "validate_python" in names else (
            names[0] if names else "validate_python")
        risky = ("search_wikipedia" if "search_wikipedia" in names
                 else ("research" if "research" in names else "research_llm"))

        print("\n[1] SAFE tool (%s):" % safe)
        print(format_prediction(sim.predict_tool(safe, {"code": "x = 1\n"})))

        print("\n[2] RISKY/NETWORK tool (%s):" % risky)
        print(format_prediction(sim.predict_tool(risky, {"query": "python"})))

        print("\n[3] DESTRUCTIVE free-text action:")
        print(format_prediction(sim.simulate("delete all files in C:/")))
        return 0

    arg = argv[0]
    # "tool:key=val,key=val" or bare tool name -> predict_tool.
    name = arg
    kwargs: dict = {}
    if ":" in arg and not arg.lower().startswith(("http", "c:")):
        name, _, rest = arg.partition(":")
        for pair in rest.split(","):
            if "=" in pair:
                k, _, v = pair.partition("=")
                kwargs[k.strip()] = v.strip()

    if name in sim._tool_names():
        print(format_prediction(sim.predict_tool(name, kwargs)))
    else:
        print(format_prediction(sim.simulate(arg)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
