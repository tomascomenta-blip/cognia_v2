"""
goal_contract.py
================
Chimera "verifiable goal contract" + anti-goal-drift component
(whitepaper section 8.3, points 2 and 6).

A goal is expressed as CHECKABLE success criteria and progress is evaluated
with REAL checks (filesystem, command exit code, text presence) -- NOT
self-reports. This is the anti progress-hallucination guarantee: a goal is
only "complete" when every criterion is independently verifiable.

Drift detection is delegated to the existing AnchorTracker (Conversation
Anchor Tracker, Phase 61); we do not reimplement it.

Runnable as:  python -m cognia.agents.goal_contract
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

# WHY: tolerate the module being importable even if the anchor tracker (or its
# transitive deps) is unavailable; drift becomes a no-op instead of a crash.
try:
    from cognia.context.anchor_tracker import AnchorTracker
except Exception:  # pragma: no cover - defensive import guard
    AnchorTracker = None  # type: ignore


_COMMAND_TIMEOUT_SECONDS = 30


@dataclass
class Criterion:
    kind: str          # one of: file_exists, text_in_file, command_succeeds, text_present
    spec: dict         # parameters for the check (path / substring / command / evidence_key)
    description: str    # human-readable WHY this criterion proves progress


@dataclass
class CriterionResult:
    criterion: Criterion
    satisfied: bool
    detail: str        # evidence string or error text (never raised, always captured)


@dataclass
class ContractStatus:
    goal: str
    satisfied_count: int
    total: int
    complete: bool
    results: list
    drift: Optional[float] = None


# --- individual real checks -------------------------------------------------
# WHY: each check returns (satisfied, detail) and NEVER raises. A broken check
# must downgrade the criterion to unsatisfied with an explanatory detail so the
# contract can never hallucinate completion from an exception.

def _check_file_exists(spec: dict) -> tuple:
    path = spec.get("path", "")
    try:
        ok = os.path.exists(path)
        return ok, ("exists: " + path) if ok else ("missing: " + path)
    except Exception as exc:  # pragma: no cover - defensive
        return False, "error: " + repr(exc)


def _check_text_in_file(spec: dict) -> tuple:
    path = spec.get("path", "")
    substring = spec.get("substring", "")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            contents = handle.read()
    except Exception as exc:
        return False, "error reading " + path + ": " + repr(exc)
    if substring in contents:
        return True, "found '" + substring + "' in " + path
    return False, "absent '" + substring + "' in " + path


def _check_command_succeeds(spec: dict) -> tuple:
    # WHY: evidence must be RUNNABLE, not claimed. A zero exit code from a real
    # subprocess is the strongest non-self-report signal of progress.
    command = spec.get("command", "")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout after " + str(_COMMAND_TIMEOUT_SECONDS) + "s: " + str(command)
    except Exception as exc:
        return False, "error: " + repr(exc)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    snippet = tail[-1] if tail else ""
    if proc.returncode == 0:
        return True, "rc=0 " + snippet
    return False, "rc=" + str(proc.returncode) + " " + snippet


def _check_text_present(spec: dict, evidence: Optional[dict]) -> tuple:
    # WHY: when evidence is supplied directly (e.g. captured agent output), we
    # still verify a substring is literally present rather than trusting a flag.
    substring = spec.get("substring", "")
    key = spec.get("evidence_key", "")
    blob = ""
    if evidence is not None:
        blob = str(evidence.get(key, "")) if key else ""
        if not key:
            blob = str(evidence.get("text", ""))
    if substring and substring in blob:
        return True, "found '" + substring + "' in evidence['" + (key or "text") + "']"
    return False, "absent '" + substring + "' in evidence['" + (key or "text") + "']"


_CHECKS = {
    "file_exists": lambda spec, evidence: _check_file_exists(spec),
    "text_in_file": lambda spec, evidence: _check_text_in_file(spec),
    "command_succeeds": lambda spec, evidence: _check_command_succeeds(spec),
    "text_present": lambda spec, evidence: _check_text_present(spec, evidence),
}


class GoalContract:
    """A goal bound to verifiable criteria, with anchor-based drift detection."""

    def __init__(self, goal: str, criteria: list, session_id: str = "default") -> None:
        self.goal = goal
        self.criteria = list(criteria)
        self.session_id = session_id
        # WHY: tolerate missing AnchorTracker dep -> drift simply unavailable.
        self._tracker = None
        if AnchorTracker is not None:
            try:
                self._tracker = AnchorTracker()
                self._tracker.set_anchor(session_id, goal)
            except Exception:
                self._tracker = None

    @classmethod
    def from_spec(cls, goal: str, specs: list, session_id: str = "default") -> "GoalContract":
        criteria = []
        for raw in specs:
            kind = raw.get("kind", "")
            description = raw.get("description", kind)
            # Build the spec dict from the flat convenience keys.
            spec = {
                k: v for k, v in raw.items()
                if k not in ("kind", "description")
            }
            criteria.append(Criterion(kind=kind, spec=spec, description=description))
        return cls(goal, criteria, session_id=session_id)

    def check(self, evidence: Optional[dict] = None, current_query: Optional[str] = None) -> ContractStatus:
        results = []
        satisfied_count = 0
        for criterion in self.criteria:
            checker = _CHECKS.get(criterion.kind)
            if checker is None:
                results.append(CriterionResult(criterion, False, "unknown kind: " + str(criterion.kind)))
                continue
            try:
                ok, detail = checker(criterion.spec, evidence)
            except Exception as exc:  # WHY: never let one bad criterion abort the whole contract.
                ok, detail = False, "error: " + repr(exc)
            if ok:
                satisfied_count += 1
            results.append(CriterionResult(criterion, bool(ok), detail))

        total = len(self.criteria)
        complete = satisfied_count == total and total > 0

        drift = None
        if current_query is not None and self._tracker is not None:
            try:
                drift = float(self._tracker.check_drift(self.session_id, current_query))
            except Exception:
                drift = None

        return ContractStatus(
            goal=self.goal,
            satisfied_count=satisfied_count,
            total=total,
            complete=complete,
            results=results,
            drift=drift,
        )

    def record_turn(self) -> None:
        # WHY: AnchorTracker only arms drift checks after REMIND_AFTER_TURNS turns;
        # expose the counter so callers can advance the session honestly.
        if self._tracker is not None:
            try:
                self._tracker.record_turn(self.session_id)
            except Exception:
                pass

    def reanchor_hint(self, current_query: str) -> str:
        # WHY: re-anchoring against drift -- delegate to the existing tracker.
        if self._tracker is None:
            return ""
        try:
            return self._tracker.get_anchor_hint(self.session_id, current_query)
        except Exception:
            return ""


# --- derivación mecánica de criterios desde la tarea -------------------------
# WHY: para que el loop /hacer pueda armar un contrato SIN pedirle criterios al
# usuario ni gastar una llamada LLM. Conservador a propósito: solo criterios
# NECESARIOS obvios (archivo mencionado -> file_exists; pedido de tests con una
# ruta de test -> command_succeeds pytest). Puede devolver [] — mejor ningún
# contrato que uno inventado que bloquee 'responder' con falsos negativos.

import re as _re

# WHY el prefijo de unidad opcional y el ~: las tareas reales traen rutas
# absolutas de Windows (C:\..., TOMANQ~1) ademas de relativas.
_TASK_FILE_RX = _re.compile(
    r"((?:[A-Za-z]:[/\\])?[\w.~/\\-]+\.(?:py|md|txt|json|html|css|js|yaml|yml|csv))\b")
_TASK_TEST_RX = _re.compile(r"\b(test|tests|pytest|prueba|pruebas)\b",
                            _re.IGNORECASE)
_MAX_DERIVED = 3


def derive_criteria_from_task(task: str, py_exe: Optional[str] = None) -> list:
    """Specs (para GoalContract.from_spec) derivadas de la letra de la tarea.

    - ruta con pinta de test (test_*.py o bajo tests/) + mención de tests
      -> command_succeeds: pytest sobre esa ruta (oráculo ejecutable real);
    - cualquier otra ruta mencionada -> file_exists (necesario, no suficiente);
    - tope _MAX_DERIVED criterios, dedupe por ruta.
    """
    specs = []
    seen = set()
    # WHY quitar las rutas antes de buscar intencion de tests: la palabra
    # 'tests' DENTRO de una ruta (tests/test_foo.py) no es un pedido de
    # correrlos ("lee tests/test_foo.py y explicalo" no debe armar pytest).
    stripped = _TASK_FILE_RX.sub(" ", task or "")
    wants_tests = bool(_TASK_TEST_RX.search(stripped))
    py = py_exe or sys.executable
    for m in _TASK_FILE_RX.finditer(task or ""):
        path = m.group(1)
        if path in seen or len(specs) >= _MAX_DERIVED:
            continue
        seen.add(path)
        name = os.path.basename(path)
        is_testfile = name.startswith("test_") or "tests" in path.replace("\\", "/").split("/")
        if wants_tests and is_testfile and path.endswith(".py"):
            specs.append({
                "kind": "command_succeeds",
                "command": '"' + py + '" -m pytest ' + path + " -q --no-header",
                "description": "los tests mencionados pasan: " + path,
            })
        else:
            specs.append({
                "kind": "file_exists", "path": path,
                "description": "la tarea menciona " + path + " -> debe existir",
            })
    return specs


def format_status(status: ContractStatus) -> str:
    lines = []
    lines.append("GOAL: " + status.goal)
    for res in status.results:
        mark = "[OK]" if res.satisfied else "[--]"
        lines.append("  " + mark + " " + res.criterion.description + " -- " + res.detail)
    lines.append("SATISFIED: " + str(status.satisfied_count) + "/" + str(status.total))
    lines.append("COMPLETE: " + ("yes" if status.complete else "no"))
    if status.drift is not None:
        lines.append("DRIFT: " + ("%.3f" % status.drift))
    return "\n".join(lines)


def _demo() -> None:
    # --- Real verifiable contract against THIS repo's Chimera work ---------
    py = sys.executable  # WHY: run the import check under the SAME interpreter.
    contract = GoalContract.from_spec(
        "Build the Chimera HYDRA capstone with band routing",
        [
            {"kind": "file_exists", "path": "cognia/chimera.py",
             "description": "Chimera capstone module exists"},
            {"kind": "file_exists", "path": "cognia/context/band_router.py",
             "description": "Band router module exists"},
            {"kind": "text_in_file", "path": "README.md", "substring": "HYDRA",
             "description": "README documents HYDRA"},
            {"kind": "command_succeeds",
             "command": py + " -c \"import cognia.chimera\"",
             "description": "cognia.chimera imports cleanly"},
        ],
        session_id="chimera-demo",
    )
    status = contract.check()
    print("=== Verifiable goal contract (real repo) ===")
    print(format_status(status))

    # --- Drift demonstration ----------------------------------------------
    print()
    print("=== Anti-goal-drift demo ===")
    drift_contract = GoalContract("refactor shards", [], session_id="drift-demo")
    # WHY: AnchorTracker arms drift only after REMIND_AFTER_TURNS turns.
    for _ in range(6):
        drift_contract.record_turn()
    on_topic = drift_contract.check(current_query="refactor the model shards loader")
    off_topic = drift_contract.check(current_query="write a poem about the ocean")
    print("on-topic  query 'refactor the model shards loader' -> drift="
          + ("%.3f" % on_topic.drift if on_topic.drift is not None else "n/a"))
    print("off-topic query 'write a poem about the ocean'     -> drift="
          + ("%.3f" % off_topic.drift if off_topic.drift is not None else "n/a"))
    hint = drift_contract.reanchor_hint("write a poem about the ocean")
    print("reanchor_hint: " + (hint if hint else "(no hint)"))


if __name__ == "__main__":
    _demo()
