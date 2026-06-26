r"""
CYCLE 94 / H-V4-7j — regresión: la guardia dedup+replay (CYCLE 50) rescata el downstream de la asignación
confidence-greedy en el lazo cerrado real sin perder el yield (receta completa). El lazo usa el HybridLM (torch) y es
lento -> aquí se protege la LÓGICA del veredicto (build_summary) y los helpers de la guardia; el run real se verifica al
correr el experimento/ciclo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle94_closed_loop_guard.py -q
"""
from cognia_x.experiments.exp078_closed_loop_guard import run as X
from cognia_x.experiments.exp018_real_verifier import expression_task as E


def test_guard_helpers():
    # dedup colapsa repetidos (prompt, expr); replay genera verdad canónica (a+b == target con operador)
    pairs = [(b"12=", b"3*4"), (b"12=", b"3*4"), (b"10=", b"5+5")]
    assert len(X._dedup(pairs)) == 2
    import numpy as np
    rep = X._replay_examples(np.random.default_rng(0), list(range(2, 50)), 4)
    assert len(rep) == 4
    for p, e in rep:                       # cada replay es una solución REAL verificable
        assert E.is_real_solution(p, bytes(e) + b"\n")


def _seed(yc, yg, yn, yva, rc, rg, rn, rva, corr=0.5, B=20, M=100):
    return {"hist": {"conf_alloc": {"yield": yc, "real": [0.5] + rc},
                     "conf_alloc_guard": {"yield": yg, "real": [0.5] + rg},
                     "random_alloc": {"yield": yn, "real": [0.5] + rn},
                     "verify_all": {"yield": yva, "real": [0.5] + rva}},
            "conf_strong_corr": corr, "B": B, "M": M, "base": {"real_acc": 0.5}}


def test_verdict_apoyada_guard_rescues():
    # guard rescata (real guard > conf) y vuelve viable (>= random) manteniendo el yield
    per = [_seed([55, 56], [56, 57], [20, 18], [90, 88], [0.28, 0.27], [0.55, 0.56], [0.40, 0.41], [0.58, 0.59]),
           _seed([50, 52], [51, 53], [16, 17], [85, 86], [0.29, 0.30], [0.54, 0.55], [0.42, 0.43], [0.56, 0.57])]
    sm = X.build_summary(per)
    assert sm["rescues"] and sm["viable"] and sm["keeps_yield"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_guard_no_rescue():
    # guard ≈ conf -> no rescata
    per = [_seed([55, 56], [55, 56], [20, 18], [90, 88], [0.28, 0.27], [0.29, 0.28], [0.40, 0.41], [0.58, 0.59]),
           _seed([50, 52], [50, 52], [16, 17], [85, 86], [0.29, 0.30], [0.30, 0.29], [0.42, 0.43], [0.56, 0.57])]
    sm = X.build_summary(per)
    assert not sm["rescues"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial():
    # guard rescata sobre conf pero NO alcanza a random (no viable)
    per = [_seed([55, 56], [56, 57], [40, 42], [90, 88], [0.28, 0.27], [0.40, 0.41], [0.55, 0.56], [0.58, 0.59]),
           _seed([50, 52], [51, 53], [38, 39], [85, 86], [0.29, 0.30], [0.41, 0.40], [0.54, 0.55], [0.56, 0.57])]
    sm = X.build_summary(per)
    assert sm["rescues"] and not sm["viable"]
    assert sm["status"] == "mixta"
