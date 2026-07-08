# -*- coding: utf-8 -*-
"""Regresión: eval_g4_cli.resolve_suites parsea válidas y rechaza inválidas."""
import pytest

from cognia_v3.eval.eval_g4_cli import resolve_suites


def test_default_g4_clasico():
    assert resolve_suites("g1,g2a") == {"g1": "g1_general.jsonl",
                                        "g2a": "g2_accion.jsonl"}


def test_todas_las_suites():
    r = resolve_suites("g1,g2a,g3,g5")
    assert list(r) == ["g1", "g2a", "g3", "g5"]
    assert r["g3"] == "g3_identidad.jsonl"
    assert r["g5"] == "g5_espanol.jsonl"


def test_invalida_lanza_valueerror():
    with pytest.raises(ValueError, match="g9"):
        resolve_suites("g1,g9")
