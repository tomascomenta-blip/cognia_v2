r"""
CYCLE 103 / H-V4-8h — regresión: ablación 2×2 (decay × surprise-explore) bajo drift+action-gated. El OLVIDO (decay) es la
pieza dominante; la exploración es sustituto redundante dado decay (composición parcial -> mixta). Califica 98-99.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle103_adaptive_composition.py -q
"""
from cognia_x.experiments.exp087_adaptive_composition import run as X


def test_decay_dominates_real_run():
    cell = X.run_cell(n=50, T=32, D=8, warmup=4, k_obs=2, k_eval=10, decay=0.8, eps_high=0.5, noise=0.05, n_seeds=12)
    sm = X.build_summary(cell)
    # full_adaptive supera al naive, pero la exploración añade poco sobre decay (sustituibilidad) -> mixta
    assert sm["full_vs_naive"] > 0.05
    assert sm["decay_needed"]                          # ablar decay (explore_only) degrada -> decay necesario
    assert not sm["explore_needed"]                    # ablar explore (decay_only) NO degrada -> explore redundante dado decay
    assert sm["status"] == "mixta"


def _cell(naive, decay_only, explore_only, full, oracle):
    return {"naive": naive, "decay_only": decay_only, "explore_only": explore_only,
            "full_adaptive": full, "oracle": oracle}


def test_verdict_mixta_decay_dominates():
    sm = X.build_summary(_cell(0.379, 0.542, 0.394, 0.542, 1.0))
    assert sm["status"] == "mixta"
    assert sm["decay_needed"] and not sm["explore_needed"]


def test_verdict_apoyada_both_compose():
    # ambas piezas aportan: full > decay_only y > explore_only por > umbral -> apoyada
    sm = X.build_summary(_cell(0.40, 0.50, 0.48, 0.58, 1.0))
    assert sm["explore_needed"] and sm["decay_needed"] and sm["full_best"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_help():
    # full ≈ naive -> ninguna pieza ayuda
    sm = X.build_summary(_cell(0.52, 0.53, 0.52, 0.54, 1.0))
    assert sm["full_vs_naive"] <= 0.05
    assert sm["status"] == "refutada"
