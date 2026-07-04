"""
Tests for low-memory background research (cognia/agent/background_research.py).

Pins the tool-idea queue, the RAM guard, the wanted-tool signal, and the full
background_tick path that synthesizes a queued idea into a verified tool.
"""

import types

import pytest

from cognia.agent import background_research as BR
from cognia.agent import tool_synthesis as TS


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "ideas.db")


@pytest.fixture(autouse=True)
def _isolate_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(TS, "GENERATED_DIR", tmp_path / "gen")
    monkeypatch.setattr(TS, "MANIFEST_PATH", tmp_path / "gen" / "_manifest.json")


def _orch(code):
    return types.SimpleNamespace(infer=lambda p: types.SimpleNamespace(text=code))


def test_queue_and_pending(db):
    assert BR.queue_tool_idea("mayus", "pasa a mayusculas", "hola", "HOLA", db_path=db)
    pend = BR.pending_tool_ideas(db_path=db)
    assert len(pend) == 1 and pend[0]["name"] == "mayus"


def test_queue_dedupes_by_name(db):
    assert BR.queue_tool_idea("mayus", "x", "hola", "HOLA", db_path=db)
    assert not BR.queue_tool_idea("mayus", "y", "z", "Z", db_path=db)
    assert len(BR.pending_tool_ideas(db_path=db)) == 1


def test_tick_idle_when_no_ideas(db):
    assert BR.background_tick(db_path=db)["action"] == "idle"


def test_tick_skips_on_low_memory(db, monkeypatch):
    BR.queue_tool_idea("mayus", "mayusculas", "hola", "HOLA", db_path=db)
    monkeypatch.setattr(BR, "free_memory_mb", lambda: 100.0)
    res = BR.background_tick(orch=_orch("def run(a):\n return a.upper()\n"),
                             min_free_mb=700.0, db_path=db)
    assert res["action"] == "skipped" and "memoria" in res["reason"]


def test_tick_synthesizes_and_marks_done(db, monkeypatch):
    monkeypatch.setattr(BR, "free_memory_mb", lambda: 99999.0)
    BR.queue_tool_idea("mayus", "pasa el texto a mayusculas", "hola", "HOLA", db_path=db)
    res = BR.background_tick(
        orch=_orch("def run(args):\n    return args.upper()\n"),
        min_free_mb=10.0, db_path=db,
    )
    assert res["action"] == "synthesized" and res["ok"], res
    # Idea consumed -> no longer pending.
    assert BR.pending_tool_ideas(db_path=db) == []
    # Tool is real and loadable.
    reg = {}
    TS.load_generated_tools(registry=reg)
    assert reg["mayus"]["fn"]("hola", {}) == "RESULTADO mayus: HOLA"


def test_tick_marks_failed_on_bad_code(db, monkeypatch):
    monkeypatch.setattr(BR, "free_memory_mb", lambda: 99999.0)
    BR.queue_tool_idea("rota", "x", "hola", "HOLA", db_path=db)
    res = BR.background_tick(
        orch=_orch("def run(args):\n    return 'siempre lo mismo'\n"),
        min_free_mb=10.0, db_path=db,
    )
    assert res["action"] == "synthesized" and not res["ok"]
    assert BR.pending_tool_ideas(db_path=db) == []  # marked failed, not pending


def test_record_wanted_tool_counts_hits(db):
    BR.record_wanted_tool("buscar_en_pdf", "leer pdf", db_path=db)
    BR.record_wanted_tool("buscar_en_pdf", "otra", db_path=db)
    conn = BR.db_connect_pooled(db)
    try:
        hits = conn.execute(
            "SELECT hits FROM wanted_tools WHERE name = ?", ("buscar_en_pdf",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert hits == 2


def test_capability_note_reflects_synthesized_tools():
    assert TS.synthesized_capabilities_note() == ""  # none yet (isolated dir)
    TS.synthesize_and_register(
        TS.ToolSpec("mayus", "mayusculas", "pasa a mayusculas", "hola", "HOLA"),
        code="def run(args):\n    return args.upper()\n",
    )
    note = TS.synthesized_capabilities_note()
    assert "mayus" in note


# ── puente wanted_tools -> tool_ideas (TAREA 1, cierra el lazo) ─────────

_PROPOSAL_TEXT = (
    "PROPOSITO: cuenta cuantas palabras tiene un texto\n"
    "TEST_INPUT: hola mundo cognia\n"
    "ESPERA: 3\n"
)


def test_wanted_below_hit_threshold_not_proposed(db):
    BR.record_wanted_tool("raro", "algo raro", db_path=db)  # hits=1
    res = BR.propose_tool_idea_from_wanted(_orch("no deberia llamarse"), db_path=db)
    assert res["action"] == "idle"
    assert BR.pending_tool_ideas(db_path=db) == []


def test_wanted_tool_bridges_to_tool_idea_and_no_dup(db):
    BR.record_wanted_tool("contar_palabras", "contar cuantas palabras tiene un texto",
                          db_path=db)
    BR.record_wanted_tool("contar_palabras", "otra vez", db_path=db)  # hits=2
    res = BR.propose_tool_idea_from_wanted(_orch(_PROPOSAL_TEXT), db_path=db)
    assert res["action"] == "proposed" and res["name"] == "contar_palabras"
    ideas = BR.pending_tool_ideas(db_path=db)
    assert len(ideas) == 1 and ideas[0]["name"] == "contar_palabras"
    assert ideas[0]["purpose"] == "cuenta cuantas palabras tiene un texto"

    # segunda invocacion: la wanted_tool ya se marco procesada -> no se
    # vuelve a proponer (ni se llama al modelo, ni se duplica la idea).
    def _boom(p):
        raise AssertionError("no debe llamarse: ya se proceso")
    res2 = BR.propose_tool_idea_from_wanted(types.SimpleNamespace(infer=_boom), db_path=db)
    assert res2["action"] == "idle"
    assert len(BR.pending_tool_ideas(db_path=db)) == 1


def test_wanted_tool_skipped_if_idea_already_queued(db):
    BR.record_wanted_tool("mayus", "pasa a mayusculas", db_path=db)
    BR.record_wanted_tool("mayus", "de nuevo", db_path=db)
    BR.queue_tool_idea("mayus", "ya encolada", "x", "X", db_path=db)
    res = BR.propose_tool_idea_from_wanted(_orch("no deberia llamarse"), db_path=db)
    assert res["action"] == "idle"
    assert len(BR.pending_tool_ideas(db_path=db)) == 1  # no duplica


def test_tick_proposes_from_wanted_when_no_pending_ideas(db, monkeypatch):
    monkeypatch.setattr(BR, "free_memory_mb", lambda: 99999.0)
    BR.record_wanted_tool("sumar_lista", "suma los numeros de una lista separada por comas",
                          db_path=db)
    BR.record_wanted_tool("sumar_lista", "de nuevo", db_path=db)
    proposal = ("PROPOSITO: suma numeros separados por coma\n"
                "TEST_INPUT: 1,2,3\nESPERA: 6\n")
    res = BR.background_tick(orch=_orch(proposal), min_free_mb=10.0, db_path=db)
    assert res["action"] == "proposed" and res["name"] == "sumar_lista"
    assert len(BR.pending_tool_ideas(db_path=db)) == 1
