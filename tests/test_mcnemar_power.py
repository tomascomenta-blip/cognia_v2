"""Regresión de los umbrales de McNemar exacto usados por los gates de COGNIA 3B."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognia_v3.eval.mcnemar_power import mcnemar_exact_p, min_wins_significant


def test_p_value_balanceado_es_uno():
    assert mcnemar_exact_p(5, 5) == 1.0
    assert mcnemar_exact_p(0, 0) == 1.0


def test_umbral_10_discordantes():
    # 9-vs-1 es significativo; 8-vs-2 no (los umbrales citados en TEORIA_COGNIA3B).
    assert mcnemar_exact_p(9, 1) < 0.05
    assert mcnemar_exact_p(8, 2) >= 0.05
    assert min_wins_significant(10) == 9


def test_umbral_20_discordantes():
    assert mcnemar_exact_p(15, 5) < 0.05
    assert mcnemar_exact_p(14, 6) >= 0.05
    assert min_wins_significant(20) == 15


def test_p_value_simetrico_y_acotado():
    assert mcnemar_exact_p(3, 7) == mcnemar_exact_p(7, 3)
    assert 0.0 < mcnemar_exact_p(12, 4) <= 1.0


def test_p_exacto_contra_cuenta_manual():
    # n01=9, n10=1: p = 2 * (C(10,0)+C(10,1)) / 2^10 = 22/1024
    assert math.isclose(mcnemar_exact_p(9, 1), 22 / 1024)
