r"""
CYCLE 70 / H-V4-5 — regresión: escribir≡olvidar dirigido por valor.

Protege: (a) select/hit_rate -- value_directed captura más masa que random y anti_value menos; (b) las 3 ramas
del veredicto (APOYADA / REFUTADA / MIXTA). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle70_value_memory.py -q
"""
import numpy as np

from cognia_x.experiments.exp055_value_memory import run as X


def test_value_directed_captures_more_than_random():
    p = np.array([0.40, 0.30, 0.15, 0.10, 0.05])     # valores ordenados desc
    vd = X.hit_rate(p, X.select(np.random.default_rng(0), p, 2, "value_directed"))
    anti = X.hit_rate(p, X.select(np.random.default_rng(0), p, 2, "anti_value"))
    assert abs(vd - 0.70) < 1e-9     # top-2 = 0.40+0.30
    assert abs(anti - 0.15) < 1e-9   # bottom-2 = 0.10+0.05


def _res(vd, rnd, abl, anti):
    return {"value_directed": vd, "random": rnd, "ablation": abl, "anti_value": anti}


def test_verdict_apoyada():
    sm = X.build_summary(_res(0.507, 0.184, 0.200, 0.086), n=50, m=10)
    assert sm["status"] == "apoyada" and sm["vd_beats_random"] and sm["ablation_collapses"]


def test_verdict_refutada():
    sm = X.build_summary(_res(0.22, 0.20, 0.20, 0.18), n=50, m=10)   # value_directed no supera
    assert sm["status"] == "refutada"


def test_verdict_mixta():
    sm = X.build_summary(_res(0.50, 0.20, 0.40, 0.10), n=50, m=10)   # ablation NO colapsa a random
    assert sm["status"] == "mixta"
