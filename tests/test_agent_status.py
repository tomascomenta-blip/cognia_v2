"""Regresion de cognia/agent/agent_status.py (visibilidad del subsistema agente)."""
from cognia.agent.agent_status import (
    agent_status_snapshot, format_agent_status, _manifest_tiers,
    _bon_telemetry_tail,
)


def test_snapshot_tiene_todas_las_claves():
    snap = agent_status_snapshot()
    for k in ("daemon", "generated_tools", "tool_usage_top", "bon_recent",
              "pending_ideas", "wanted_pending"):
        assert k in snap


def test_format_no_levanta_con_snapshot_vacio():
    snap = {"daemon": {"last": None}, "generated_tools": {},
            "pending_ideas": [], "wanted_pending": [], "tool_usage_top": [],
            "bon_recent": []}
    out = format_agent_status(snap)
    assert "Estado del subsistema agente" in out
    assert "sin log" in out


def test_format_lista_tools_y_wishlist():
    snap = {
        "daemon": {"last": "2026-07-04T10:00:00"},
        "generated_tools": {"total": 2, "staged": 1, "verified": 1, "retired": 0,
                            "names": ["foo(verified v1.1.0)", "bar(staged v1.0.0)"]},
        "pending_ideas": [{"name": "baz", "purpose": "hace algo util"}],
        "wanted_pending": [{"name": "qux", "hits": 3}],
        "tool_usage_top": [{"tool": "leer_archivo", "calls": 10, "ok": 9, "fail": 1}],
        "bon_recent": [{"difficulty": 0.2, "n_generated": 3, "rank_mode": "tests",
                        "score": 2, "total": 2, "secs": 12.3}],
    }
    out = format_agent_status(snap)
    assert "foo(verified v1.1.0)" in out
    assert "qux (hits 3)" in out
    assert "leer_archivo: 10 llamadas" in out
    assert "dif=0.2" in out


def test_manifest_tiers_best_effort_no_levanta():
    # aunque el manifest no exista o este raro, devuelve la forma estandar
    t = _manifest_tiers()
    assert set(("staged", "verified", "retired", "total", "names")) <= set(t)


def test_bon_telemetry_tail_best_effort():
    # sin archivo -> lista vacia, nunca excepcion
    assert isinstance(_bon_telemetry_tail(), list)
