r"""
CYCLE 63 / H-V4-1f — regresión: olvido en no-estacionariedad RECURRENTE.

Protege: (a) make_recurrent_world da causas distintas del clúster; (b) run_agent_recurrent es reproducible y
devuelve un post por fase; (c) las 3 ramas del veredicto (APOYADA committed se atasca + adaptive sigue / REFUTADA
no supera / MIXTA no sostenido). Rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle63_recurrent_nonstationary.py -q
"""
import numpy as np

from cognia_x.experiments.exp049_recurrent_nonstationary import run as X


def test_make_recurrent_world():
    causes, cluster_idx = X.make_recurrent_world(np.random.default_rng(0), D=20, cluster=5, n_phases=4)
    assert len(causes) == 4
    assert all(c in set(int(i) for i in cluster_idx) for c in causes)   # todas en el clúster


def test_run_agent_recurrent_reproducible():
    causes, _ = X.make_recurrent_world(np.random.default_rng(1), D=20, cluster=5, n_phases=3)
    a = X.run_agent_recurrent(np.random.default_rng(0), causes, 12, 20, 0.15, "adaptive", 0.6, 64)
    b = X.run_agent_recurrent(np.random.default_rng(0), causes, 12, 20, 0.15, "adaptive", 0.6, 64)
    assert len(a) == 3 and a == b                                       # un post por fase, reproducible


def _arm(per_phase):
    return {"post_per_phase": per_phase, "phase0": per_phase[0],
            "post_change_mean": round(sum(per_phase[1:]) / len(per_phase[1:]), 4)}


def _by_arm(com, fix, ada):
    return {"committed": _arm(com), "fixed": _arm(fix), "adaptive": _arm(ada)}


def test_verdict_apoyada():
    ba = _by_arm(com=[0.84, 0.41, 0.48, 0.24, 0.13], fix=[0.65, 0.70, 0.46, 0.58, 0.33],
                 ada=[0.69, 0.50, 0.53, 0.53, 0.40])
    sm = X.build_summary(ba, n_phases=5, n_seeds=16)
    assert sm["status"] == "apoyada"
    assert sm["committed_degrades"] and sm["beats_committed"]
    assert sm["fixed_best"]      # hallazgo honesto: el olvido constante es el mejor en recurrente


def test_verdict_refutada():
    ba = _by_arm(com=[0.84, 0.80, 0.78, 0.77, 0.77], fix=[0.65, 0.70, 0.66, 0.68, 0.63],
                 ada=[0.69, 0.72, 0.70, 0.71, 0.70])
    sm = X.build_summary(ba, n_phases=5, n_seeds=16)
    assert sm["status"] == "refutada"      # committed re-adapta solo; adaptive no lo supera


def test_verdict_mixta():
    ba = _by_arm(com=[0.84, 0.30, 0.28, 0.22, 0.18], fix=[0.65, 0.40, 0.42, 0.41, 0.40],
                 ada=[0.69, 0.40, 0.42, 0.41, 0.40])
    sm = X.build_summary(ba, n_phases=5, n_seeds=16)
    assert sm["status"] == "mixta"         # supera al committed pero post-cambio < 0.45 (no sostenido)
