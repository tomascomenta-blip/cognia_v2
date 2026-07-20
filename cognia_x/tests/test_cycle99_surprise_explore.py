r"""
CYCLE 99 / H-V4-7l — regresión: la exploración SURPRISE-GATED domina al ε-fijo y es no-regret (cierra el sub-arco 97-99).
Protege: (a) corrida real (surprise ahorra vs explore en estacionario y rescata en drift; es la mejor en promedio);
(b) ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle99_surprise_explore.py -q
"""
from cognia_x.experiments.exp083_surprise_explore import run as X


def test_surprise_dominates_fixed_explore_real_run():
    grid = X.run(n=50, T=32, D=8, warmup=4, k_obs=2, k_eval=10, decay=0.8, eps_fixed=0.5, eps_high=0.5, n_seeds=12)
    sm = X.build_summary(grid)
    assert sm["dominates_explore"], (sm["stat_savings"], sm["drift_vs_explore"])
    assert sm["beats_explore_avg"], sm["surprise_avg"]
    assert sm["no_regret"]
    assert sm["status"] == "apoyada"


def _cell(greedy, explore, surprise, random_, oracle):
    return {"greedy": greedy, "explore": explore, "surprise_explore": surprise, "random": random_, "oracle": oracle}


def _grid(st, dr):
    return {"stationary": _cell(*st), "drift": _cell(*dr)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(st=(0.900, 0.559, 0.859, 0.27, 1.0), dr=(0.532, 0.437, 0.550, 0.27, 1.0)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_domination():
    # surprise no ahorra vs explore en estacionario (≈ explore) -> no domina el esquema fijo
    sm = X.build_summary(_grid(st=(0.90, 0.86, 0.86, 0.27, 1.0), dr=(0.53, 0.55, 0.55, 0.27, 1.0)))
    assert not sm["dominates_explore"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_small_avg_margin():
    # surprise ahorra vs explore (domina el esquema, +0.07) y ≈ explore en drift (-0.02), PERO su promedio no supera al
    # ε-fijo por >0.05 -> mixta
    sm = X.build_summary(_grid(st=(0.62, 0.55, 0.62, 0.27, 1.0), dr=(0.56, 0.60, 0.58, 0.27, 1.0)))
    assert sm["dominates_explore"] and not sm["beats_explore_avg"]
    assert sm["status"] == "mixta"
