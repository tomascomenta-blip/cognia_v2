r"""
CYCLE 98 / H-V4-7k — regresión: la exploración (R-INTERVENCIÓN) LIGA bajo drift + observación estrecha (revierte 87-88
condicionalmente). Protege: (a) corrida real (a k_obs estrecho el drift atrapa y explore rescata; a k_obs amplio y en
estacionario no atrapa); (b) ramas del veredicto. El barrido completo es algo lento -> el real-run usa pocas seeds.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle98_drift_exploration.py -q
"""
from cognia_x.experiments.exp082_drift_exploration import run as X


def test_conditional_reversal_real_run():
    grid = X.run(n=50, T=32, D=8, warmup=4, k_eval=10, decay=0.8, eps=0.4, n_seeds=12)
    sm = X.build_summary(grid)
    # a k_obs estrecho bajo drift: atrapa y explore rescata; a k_obs amplio y estacionario: no atrapa
    assert sm["drift_traps"], sm["drift_trap"]
    assert sm["explore_rescues"], sm["drift_rescue"]
    assert sm["wide_robust"], sm["wide_trap"]
    assert sm["stat_robust"], sm["stat_trap"]
    assert sm["status"] == "apoyada"


def _cell(greedy, explore, random_, oracle):
    return {"greedy": greedy, "explore": explore, "random": random_, "oracle": oracle}


def _grid(nd, wd, ns):
    # nd/wd = drift @ narrow/wide k_obs; ns = stationary @ narrow. Resto neutral.
    g = {}
    for reg in ("stationary", "drift"):
        for ko in X.K_OBS_LIST:
            g["{}_kobs{}".format(reg, ko)] = _cell(0.9, 0.9, 0.9, 1.0)
    g["drift_kobs{}".format(X.NARROW_KOBS)] = _cell(*nd)
    g["drift_kobs{}".format(X.WIDE_KOBS)] = _cell(*wd)
    g["stationary_kobs{}".format(X.NARROW_KOBS)] = _cell(*ns)
    return g


def test_verdict_apoyada():
    sm = X.build_summary(_grid(nd=(0.757, 0.811, 0.812, 1.0), wd=(0.850, 0.859, 0.863, 1.0), ns=(0.941, 0.946, 0.933, 1.0)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_trap_under_drift():
    # bajo drift el greedy no se atrapa ni a k_obs estrecho -> 87-88 generaliza
    sm = X.build_summary(_grid(nd=(0.84, 0.84, 0.85, 1.0), wd=(0.85, 0.86, 0.86, 1.0), ns=(0.94, 0.95, 0.93, 1.0)))
    assert not sm["drift_traps"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_trap_no_rescue():
    # atrapa pero la exploración NO rescata (k_obs extremo) -> mixta
    sm = X.build_summary(_grid(nd=(0.63, 0.625, 0.71, 1.0), wd=(0.85, 0.86, 0.86, 1.0), ns=(0.94, 0.95, 0.93, 1.0)))
    assert sm["drift_traps"] and not sm["explore_rescues"]
    assert sm["status"] == "mixta"
