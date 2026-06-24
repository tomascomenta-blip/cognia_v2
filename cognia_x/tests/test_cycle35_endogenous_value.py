r"""
CYCLE 35 / H-V4-1 — regresión del experimento de valor endógeno vs predicción pasiva (exp022).

Falla SIN la implementación correcta (mundo causal confundido + posterior bayesiano + agentes) y pasa
CON ella. Asserts del MECANISMO y del HALLAZGO científico (config rápida para la suite):
- test_world_confounded: en el stream observacional el clúster vale TODO lo mismo (confusión perfecta);
  bajo intervención las features varían independientes (rompe la confusión).
- test_infogain_identifies_cause: el agente ACTIVO por info-gain concentra el posterior en la causa.
- test_passive_cannot_identify: el agente PASIVO NO identifica la causa (muro informacional) ni con
  presupuesto alto -> post_on_cause se queda en el rango del clúster (~1/cluster), no ->1.
- test_intervention_wall: bajo intervención, B-A > 0.20 y A es PLANO en presupuesto (no mejora con K).
- test_iid_gap_invisible: i.i.d. el gap A-B es chico (el hueco solo aparece bajo intervención).
- test_reproducible: misma semilla -> mismos números (sin hash() de strings, sin Date/Random).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle35_endogenous_value.py -q
"""
import numpy as np

from cognia_x.experiments.exp022_endogenous_value import run as E


def test_world_confounded():
    rng = np.random.default_rng(0)
    c, cluster_idx = E.make_world(rng, D=12, cluster=4)
    assert c in set(int(i) for i in cluster_idx)
    Xobs = E.sample_observational(rng, 2000, 12, cluster_idx)
    # en el stream observacional, TODAS las features del clúster son idénticas (todas valen z)
    col0 = Xobs[:, cluster_idx[0]]
    for j in cluster_idx[1:]:
        assert np.array_equal(Xobs[:, j], col0)
    # bajo intervención NO: las features del clúster se desacoplan
    Xint = E.sample_intervention(rng, 2000, 12)
    disagreements = np.mean(Xint[:, cluster_idx[0]] != Xint[:, cluster_idx[1]])
    assert 0.4 < disagreements < 0.6   # ~independientes


def test_infogain_identifies_cause():
    rng = np.random.default_rng(1)
    c, cluster_idx = E.make_world(rng, D=12, cluster=4)
    post = E.run_agent(rng, "infogain", K=64, D=12, c=c, cluster_idx=cluster_idx,
                       p_obs=0.10, cand_pool=128)
    assert post[c] > 0.90   # el valor endógeno aísla la causa


def test_passive_cannot_identify():
    rng = np.random.default_rng(2)
    c, cluster_idx = E.make_world(rng, D=12, cluster=4)
    post = E.run_agent(rng, "passive", K=64, D=12, c=c, cluster_idx=cluster_idx,
                       p_obs=0.10, cand_pool=128)
    # el pasivo no puede separar la causa de las espurias del clúster: el posterior se reparte
    assert post[c] < 0.60                 # NO concentra en la causa
    cluster_mass = float(sum(post[int(j)] for j in cluster_idx))
    assert cluster_mass > 0.80            # pero sí sabe que la causa está en el clúster (no en distractores)


def test_intervention_wall_and_iid_gap():
    # config rápida para la suite (no los 24 seeds del run completo)
    per_seed, summary = E.run(budgets=[2, 16, 64], n_seeds=6, D=12, cluster=4,
                              p_obs=0.10, n_test=800, cand_pool=96)
    bb = summary["by_budget"]
    A2, A64 = bb["2"]["A_pasivo"]["interv_mean"], bb["64"]["A_pasivo"]["interv_mean"]
    B64 = bb["64"]["B_infogain"]["interv_mean"]
    # muro: A no mejora apreciablemente con presupuesto (plano en K)
    assert abs(A64 - A2) < 0.10
    # intervención >> pasivo
    assert (B64 - A64) > 0.20
    # gap invisible i.i.d.
    iid_gap = abs(bb["64"]["A_pasivo"]["iid_mean"] - bb["64"]["B_infogain"]["iid_mean"])
    assert iid_gap < 0.10
    # NO refutada (B supera a A; A no alcanza a B)
    assert summary["verdict"] in ("apoyada", "mixta")


def test_reproducible():
    a = E.run(budgets=[2, 16], n_seeds=4, D=12, cluster=4, p_obs=0.10, n_test=500, cand_pool=64)[1]
    b = E.run(budgets=[2, 16], n_seeds=4, D=12, cluster=4, p_obs=0.10, n_test=500, cand_pool=64)[1]
    assert a["verdict"] == b["verdict"]
    assert a["by_budget"]["16"]["B_infogain"]["interv_mean"] == b["by_budget"]["16"]["B_infogain"]["interv_mean"]
    assert a["by_budget"]["2"]["A_pasivo"]["interv_mean"] == b["by_budget"]["2"]["A_pasivo"]["interv_mean"]
