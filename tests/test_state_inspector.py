"""
Tests for cognia.debug.state_inspector.StateInspector.
"""
import pytest
from cognia.debug.state_inspector import StateInspector


class MockWithGetStats:
    def get_stats(self):
        return {"requests": 42, "errors": 0}


class MockWithGetSummary:
    def get_summary(self):
        return {"summary": "ok"}


class MockNoInspectionMethod:
    pass


class MockGetStatsFails:
    def get_stats(self):
        raise RuntimeError("db unavailable")


def test_get_system_info_keys():
    si = StateInspector()
    info = si.get_system_info()
    assert "python_version" in info
    assert "platform" in info
    assert "pid" in info
    assert isinstance(info["pid"], int)
    assert isinstance(info["python_version"], str)


def test_get_singleton_states_empty():
    si = StateInspector()
    result = si.get_singleton_states({})
    assert result == {}


def test_get_singleton_states_none_obj():
    si = StateInspector()
    result = si.get_singleton_states({"none_obj": None})
    assert result == {"none_obj": {"available": False}}


def test_get_singleton_states_calls_get_stats():
    si = StateInspector()
    mock = MockWithGetStats()
    result = si.get_singleton_states({"obj": mock})
    assert result["obj"]["available"] is True
    assert result["obj"]["type"] == "MockWithGetStats"
    assert result["obj"]["state"] == {"requests": 42, "errors": 0}


def test_get_singleton_states_calls_get_summary_when_no_get_stats():
    si = StateInspector()
    mock = MockWithGetSummary()
    result = si.get_singleton_states({"obj": mock})
    assert result["obj"]["available"] is True
    assert result["obj"]["state"] == {"summary": "ok"}


def test_get_singleton_states_no_inspection_method():
    si = StateInspector()
    mock = MockNoInspectionMethod()
    result = si.get_singleton_states({"obj": mock})
    assert result["obj"] == {"available": True, "type": "MockNoInspectionMethod"}


def test_get_singleton_states_error_captured():
    si = StateInspector()
    mock = MockGetStatsFails()
    result = si.get_singleton_states({"obj": mock})
    assert result["obj"]["available"] is True
    assert "error" in result["obj"]
    assert "db unavailable" in result["obj"]["error"]


def test_full_snapshot_structure():
    si = StateInspector()
    snap = si.full_snapshot({})
    assert "ts" in snap
    assert "system" in snap
    assert "singletons" in snap
    assert isinstance(snap["ts"], float)
    assert snap["singletons"] == {}


def test_full_snapshot_with_context():
    si = StateInspector()
    ctx = {"m": MockWithGetStats(), "n": None}
    snap = si.full_snapshot(ctx)
    assert snap["singletons"]["m"]["available"] is True
    assert snap["singletons"]["n"]["available"] is False
