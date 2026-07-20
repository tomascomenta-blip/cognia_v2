"""
tests/test_datagen_kernel.py
Tests for cognia_v3/training/kaggle/datagen_kernel.py — sin Kaggle, sin GPU,
sin modelo. Cubre las funciones puras: plantillas/armado de prompts, parser
del bloque python, gates estaticos, harness subprocess y registro JSONL.
"""

from __future__ import annotations

import random
import re


# ---------------------------------------------------------------------------
# Plantillas y armado de prompts
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_fills_every_slot_token(self):
        """Ningun {slot} declarado queda sin reemplazar en ninguna plantilla."""
        from cognia_v3.training.kaggle.datagen_kernel import TEMPLATES, fill_slots
        rng = random.Random(7)
        for band, temps in TEMPLATES.items():
            for t in temps:
                filled = fill_slots(t["prompt"], t.get("slots", {}), rng)
                for key in t.get("slots", {}):
                    assert "{" + key + "}" not in filled, (band, t["name"], key)

    def test_every_brace_token_is_a_declared_slot(self):
        """No hay tokens {x} huerfanos (typo de slot) en las plantillas."""
        from cognia_v3.training.kaggle.datagen_kernel import TEMPLATES
        slot_re = re.compile(r"\{([a-z_]+)\}")
        for band, temps in TEMPLATES.items():
            for t in temps:
                tokens = set(slot_re.findall(t["prompt"]))
                assert tokens <= set(t.get("slots", {})), (band, t["name"], tokens)

    def test_returns_band_entry_kind_prompt(self):
        from cognia_v3.training.kaggle.datagen_kernel import build_prompt
        rng = random.Random(3)
        for band in ("long", "spec"):
            p = build_prompt(band, rng)
            assert p["band"] == band
            assert p["entry"] and p["kind"] in ("class", "function")
            assert p["entry"] in p["prompt"]

    def test_deterministic_with_same_seed(self):
        from cognia_v3.training.kaggle.datagen_kernel import build_prompt
        a = build_prompt("long", random.Random(42))
        b = build_prompt("long", random.Random(42))
        assert a == b

    def test_no_leakage_from_tasks_hard(self):
        """ANTI-LEAKAGE: ningun entry point ni tema del set duro (tasks_hard.jsonl)
        aparece en las plantillas. El set duro es el instrumento de medicion."""
        from cognia_v3.training.kaggle.datagen_kernel import TEMPLATES
        forbidden = ["LRUCache", "Polynomial", "Matrix", "format_table",
                     "compare_versions", "validate_username", "summarize_logs",
                     "parse_json", "run_turtle", "num_distinct", "find_order",
                     "min_rooms", "count_queens", "num_decodings",
                     "split_bill", "least-recently-used", "semantic version"]
        blob = " ".join(t["prompt"] + " " + t["entry"]
                        for temps in TEMPLATES.values() for t in temps)
        for word in forbidden:
            assert word not in blob, f"leakage del set duro: {word}"


class TestPickBand:
    def test_starts_with_long(self):
        from cognia_v3.training.kaggle.datagen_kernel import pick_band
        assert pick_band(0, 0) == "long"

    def test_converges_to_60_40(self):
        """Aceptando siempre, la mezcla converge a 60% long / 40% spec."""
        from cognia_v3.training.kaggle.datagen_kernel import pick_band
        n_long = n_spec = 0
        for _ in range(100):
            if pick_band(n_long, n_spec) == "long":
                n_long += 1
            else:
                n_spec += 1
        assert n_long == 60 and n_spec == 40


# ---------------------------------------------------------------------------
# extract_python_block — parser de la respuesta del modelo
# ---------------------------------------------------------------------------

class TestExtractPythonBlock:
    def test_fenced_block_with_prose_around(self):
        from cognia_v3.training.kaggle.datagen_kernel import extract_python_block
        text = "Sure!\n```python\ndef f():\n    return 1\n```\nHope it helps."
        assert extract_python_block(text) == "def f():\n    return 1"

    def test_open_fence_without_close(self):
        """Corte por max tokens: fence abierto, sin cierre."""
        from cognia_v3.training.kaggle.datagen_kernel import extract_python_block
        text = "```python\ndef f():\n    return 1"
        assert extract_python_block(text) == "def f():\n    return 1"

    def test_no_fence_but_valid_code(self):
        from cognia_v3.training.kaggle.datagen_kernel import extract_python_block
        assert extract_python_block("def f():\n    return 1") == "def f():\n    return 1"

    def test_no_fence_prose_returns_none(self):
        """Respuesta sin fence que no parsea como Python -> rechazada."""
        from cognia_v3.training.kaggle.datagen_kernel import extract_python_block
        assert extract_python_block("Here is how I would solve it: first...") is None

    def test_empty_returns_none(self):
        from cognia_v3.training.kaggle.datagen_kernel import extract_python_block
        assert extract_python_block("") is None
        assert extract_python_block("```python\n```") is None


# ---------------------------------------------------------------------------
# validate_solution / validate_asserts — gates estaticos
# ---------------------------------------------------------------------------

GOOD_CLASS = "\n".join(
    ["class Ring:",
     "    def __init__(self, capacity):",
     "        if capacity <= 0:",
     "            raise ValueError('capacity')",
     "        self.capacity = capacity",
     "        self.items = []",
     "    def push(self, x):",
     "        if len(self.items) == self.capacity:",
     "            self.items.pop(0)",
     "        self.items.append(x)",
     "    def pop(self):",
     "        if not self.items:",
     "            raise IndexError('empty')",
     "        return self.items.pop(0)",
     "    def to_list(self):",
     "        return list(self.items)",
     "    def __len__(self):",
     "        return len(self.items)",
     "    def is_full(self):",
     "        return len(self.items) == self.capacity",
     "    def clear(self):",
     "        self.items = []"])


class TestValidateSolution:
    def test_good_long_class_passes(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        ok, reason = validate_solution(GOOD_CLASS, "long", "Ring", "class")
        assert ok, reason

    def test_unparseable_code_rejected(self):
        """Codigo que no parsea -> par rechazado en el gate estatico."""
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        ok, reason = validate_solution("def f(:\n    pass", "spec", "f", "function")
        assert not ok and reason.startswith("syntax")

    def test_missing_entry_rejected(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        ok, reason = validate_solution("def other():\n    return 1\n" * 3,
                                       "spec", "wrap", "function")
        assert not ok and reason.startswith("missing_entry")

    def test_long_too_short_rejected(self):
        """LONG exige tamano de clase real, no un stub de 3 lineas."""
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        stub = "class Ring:\n    def push(self, x):\n        pass"
        ok, reason = validate_solution(stub, "long", "Ring", "class")
        assert not ok and reason.startswith("too_short")

    def test_forbidden_import_rejected(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        bad = "import os\n" + GOOD_CLASS
        ok, reason = validate_solution(bad, "long", "Ring", "class")
        assert not ok and reason == "import:os"

    def test_forbidden_call_rejected(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        bad = GOOD_CLASS + "\n\ndata = eval(repr([1]))"
        ok, reason = validate_solution(bad, "long", "Ring", "class")
        assert not ok and reason == "call:eval"

    def test_kind_mismatch_rejected(self):
        """El modelo escribio una funcion donde se pedia una clase."""
        from cognia_v3.training.kaggle.datagen_kernel import validate_solution
        fn = "def Ring(capacity):\n    return []\n"
        ok, reason = validate_solution(fn, "long", "Ring", "class")
        assert not ok and reason.startswith("missing_entry")


class TestValidateAsserts:
    def test_good_asserts_pass(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_asserts
        block = ("r = Ring(2)\nr.push(1)\nr.push(2)\n"
                 "assert r.to_list() == [1, 2]\nassert len(r) == 2\n"
                 "assert r.is_full()")
        ok, reason = validate_asserts(block, "Ring")
        assert ok, reason

    def test_too_few_asserts_rejected(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_asserts
        ok, reason = validate_asserts("assert Ring(1) is not None", "Ring")
        assert not ok and reason.startswith("few_asserts")

    def test_redefining_entry_rejected(self):
        """Asserts que definen la clase pisarian la solucion: gate anulado."""
        from cognia_v3.training.kaggle.datagen_kernel import validate_asserts
        block = ("class Ring:\n    pass\n"
                 "assert True\nassert True\nassert True")
        ok, reason = validate_asserts(block, "Ring")
        assert not ok and reason == "redefines_entry"

    def test_no_entry_reference_rejected(self):
        from cognia_v3.training.kaggle.datagen_kernel import validate_asserts
        block = "assert 1 == 1\nassert 2 == 2\nassert 3 == 3"
        ok, reason = validate_asserts(block, "Ring")
        assert not ok and reason == "no_entry_ref"


# ---------------------------------------------------------------------------
# run_harness — ejecucion real en subprocess (gate dinamico)
# ---------------------------------------------------------------------------

class TestRunHarness:
    def test_passing_pair_accepted(self):
        from cognia_v3.training.kaggle.datagen_kernel import run_harness
        sol = "def double(x):\n    return 2 * x"
        ok, detail = run_harness(
            sol, "assert double(2) == 4\nassert double(0) == 0\nassert double(-1) == -2")
        assert ok, detail

    def test_failing_assert_rejects_pair(self):
        """Un assert que falla -> el par NO entra al dataset."""
        from cognia_v3.training.kaggle.datagen_kernel import run_harness
        sol = "def double(x):\n    return 2 * x + 1"  # solucion buggy
        ok, detail = run_harness(
            sol, "assert double(2) == 4\nassert double(0) == 0\nassert double(1) == 2")
        assert not ok
        assert "AssertionError" in detail or detail  # detalle del stderr

    def test_infinite_loop_times_out(self):
        from cognia_v3.training.kaggle.datagen_kernel import run_harness
        ok, detail = run_harness("def f():\n    return 1\nwhile True:\n    pass",
                                 "assert f() == 1", timeout_s=2)
        assert not ok and detail == "timeout"

    def test_exception_in_solution_rejects_pair(self):
        from cognia_v3.training.kaggle.datagen_kernel import run_harness
        ok, _ = run_harness("raise RuntimeError('boom')", "assert True")
        assert not ok


# ---------------------------------------------------------------------------
# make_record — registro JSONL final
# ---------------------------------------------------------------------------

class TestMakeRecord:
    def test_schema_and_fence(self):
        """Mismo schema que cognia_dataset.jsonl: prompt/completion/source. La
        completion es SOLO el bloque ```python (lo que extract_code espera)."""
        from cognia_v3.training.kaggle.datagen_kernel import make_record
        rec = make_record("Write f.", "def f():\n    return 1", "long")
        assert set(rec) == {"prompt", "completion", "source"}
        assert rec["completion"] == "```python\ndef f():\n    return 1\n```"

    def test_source_by_band(self):
        from cognia_v3.training.kaggle.datagen_kernel import make_record
        assert make_record("p", "c = 1", "long")["source"] == "syn_long"
        assert make_record("p", "c = 1", "spec")["source"] == "syn_spec"

    def test_roundtrip_through_extract_code(self):
        """La completion generada se extrae limpia con el mismo parser del kernel
        (y con la misma forma que usa el benchmark en eval)."""
        from cognia_v3.training.kaggle.datagen_kernel import (extract_python_block,
                                                              make_record)
        code = "def f():\n    return 1"
        rec = make_record("Write f.", code, "spec")
        assert extract_python_block(rec["completion"]) == code


# ---------------------------------------------------------------------------
# build_asserts_request — prompt del generador de asserts
# ---------------------------------------------------------------------------

class TestBuildAssertsRequest:
    def test_contains_task_and_entry(self):
        from cognia_v3.training.kaggle.datagen_kernel import build_asserts_request
        req = build_asserts_request("Implement `Ring` ...", "Ring")
        assert "[TASK]" in req and "Implement `Ring` ..." in req
        assert "Do NOT define or redefine `Ring`" in req
