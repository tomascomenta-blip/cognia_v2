"""
test_goal_contract.py
=====================
Real pytest coverage for the verifiable goal contract. No mocks: every check
runs against tmp_path files or a real subprocess under sys.executable.
"""

from __future__ import annotations

import sys

from cognia.agents.goal_contract import (
    Criterion,
    GoalContract,
    format_status,
)


def test_file_exists_true_and_false(tmp_path):
    present = tmp_path / "here.txt"
    present.write_text("data", encoding="utf-8")
    missing = tmp_path / "nope.txt"

    contract = GoalContract.from_spec(
        "files",
        [
            {"kind": "file_exists", "path": str(present), "description": "present"},
            {"kind": "file_exists", "path": str(missing), "description": "missing"},
        ],
    )
    status = contract.check()
    by_desc = {r.criterion.description: r.satisfied for r in status.results}
    assert by_desc["present"] is True
    assert by_desc["missing"] is False
    assert status.satisfied_count == 1
    assert status.total == 2
    assert status.complete is False


def test_text_in_file_present_and_absent(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha HYDRA omega", encoding="utf-8")

    contract = GoalContract.from_spec(
        "text",
        [
            {"kind": "text_in_file", "path": str(f), "substring": "HYDRA", "description": "has"},
            {"kind": "text_in_file", "path": str(f), "substring": "DRAGON", "description": "nothas"},
        ],
    )
    status = contract.check()
    by_desc = {r.criterion.description: r.satisfied for r in status.results}
    assert by_desc["has"] is True
    assert by_desc["nothas"] is False


def test_command_succeeds_true_and_false():
    py = sys.executable
    contract = GoalContract.from_spec(
        "commands",
        [
            {"kind": "command_succeeds", "command": py + " -c \"pass\"", "description": "ok"},
            {"kind": "command_succeeds", "command": py + " -c \"raise SystemExit(1)\"", "description": "fail"},
        ],
    )
    status = contract.check()
    by_desc = {r.criterion.description: r.satisfied for r in status.results}
    assert by_desc["ok"] is True
    assert by_desc["fail"] is False


def test_text_present_evidence():
    contract = GoalContract.from_spec(
        "evidence",
        [
            {"kind": "text_present", "substring": "done", "evidence_key": "out", "description": "has"},
            {"kind": "text_present", "substring": "missing", "evidence_key": "out", "description": "nothas"},
        ],
    )
    status = contract.check(evidence={"out": "task is done now"})
    by_desc = {r.criterion.description: r.satisfied for r in status.results}
    assert by_desc["has"] is True
    assert by_desc["nothas"] is False


def test_check_aggregates_and_never_raises_on_bad_criterion(tmp_path):
    present = tmp_path / "ok.txt"
    present.write_text("x", encoding="utf-8")

    # A weird/illegal path plus an unknown kind must not raise -- they degrade
    # to unsatisfied with a detail string.
    weird_path = str(tmp_path / "\0bad" / "??:|*") if sys.platform != "win32" else "??:|*<>weird"
    contract = GoalContract.from_spec(
        "robust",
        [
            {"kind": "file_exists", "path": str(present), "description": "good"},
            {"kind": "file_exists", "path": weird_path, "description": "weird"},
            {"kind": "no_such_kind", "description": "unknown"},
        ],
    )
    status = contract.check()  # must not raise
    by_desc = {r.criterion.description: r.satisfied for r in status.results}
    assert by_desc["good"] is True
    assert by_desc["weird"] is False
    assert by_desc["unknown"] is False
    assert status.satisfied_count == 1
    assert status.total == 3
    assert status.complete is False


def test_drift_off_topic_lower_than_on_topic():
    contract = GoalContract("refactor the model shards loader code", [], session_id="drift-test")
    # AnchorTracker arms drift only after REMIND_AFTER_TURNS turns; advance past it.
    for _ in range(6):
        contract.record_turn()

    on_topic = contract.check(current_query="refactor model shards loader logic")
    off_topic = contract.check(current_query="write a poem about the ocean")

    assert on_topic.drift is not None
    assert off_topic.drift is not None
    assert 0.0 <= on_topic.drift <= 1.0
    assert 0.0 <= off_topic.drift <= 1.0
    # Off-topic query overlaps less with the anchor -> strictly lower score.
    assert off_topic.drift < on_topic.drift


# --- additional coverage -----------------------------------------------------

def test_complete_true_when_all_criteria_satisfied(tmp_path):
    # THE positive case: a contract is only "complete" when EVERY criterion is
    # independently verified. This is the anti progress-hallucination guarantee
    # and must be exercised in the all-pass direction, not just the failing one.
    f = tmp_path / "built.txt"
    f.write_text("HYDRA band router is built", encoding="utf-8")

    contract = GoalContract.from_spec(
        "ship it",
        [
            {"kind": "file_exists", "path": str(f), "description": "artifact exists"},
            {"kind": "text_in_file", "path": str(f), "substring": "HYDRA",
             "description": "artifact mentions HYDRA"},
            {"kind": "text_present", "substring": "ok", "evidence_key": "log",
             "description": "evidence shows ok"},
        ],
    )
    status = contract.check(evidence={"log": "all checks ok"})
    assert status.satisfied_count == 3
    assert status.total == 3
    assert status.complete is True


def test_empty_criteria_is_not_complete():
    # total == 0 must NOT count as complete (the `total > 0` guard): an empty
    # contract has proven nothing.
    status = GoalContract("do something", []).check()
    assert status.total == 0
    assert status.satisfied_count == 0
    assert status.complete is False


def test_text_present_defaults_to_evidence_text_key():
    # With no evidence_key, the check reads evidence["text"].
    contract = GoalContract.from_spec(
        "default key",
        [{"kind": "text_present", "substring": "done", "description": "has"}],
    )
    status = contract.check(evidence={"text": "the task is done"})
    assert status.results[0].satisfied is True


def test_text_present_with_no_evidence_is_unsatisfied():
    # No evidence supplied at all -> unsatisfied, never raises.
    contract = GoalContract.from_spec(
        "no evidence",
        [{"kind": "text_present", "substring": "done", "evidence_key": "out",
          "description": "has"}],
    )
    status = contract.check(evidence=None)
    assert status.results[0].satisfied is False
    assert status.complete is False


def test_reanchor_hint_returns_string():
    # reanchor_hint must always return a string (possibly empty), never raise.
    contract = GoalContract("refactor the model shards loader", [],
                            session_id="hint-test")
    hint = contract.reanchor_hint("write a poem about the ocean")
    assert isinstance(hint, str)


def test_format_status_renders_expected_lines(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("x", encoding="utf-8")
    contract = GoalContract.from_spec(
        "render me",
        [{"kind": "file_exists", "path": str(f), "description": "exists"}],
    )
    rendered = format_status(contract.check())
    assert "GOAL: render me" in rendered
    assert "SATISFIED: 1/1" in rendered
    assert "COMPLETE: yes" in rendered
    rendered.encode("ascii")  # ASCII-safe for Windows stdout
