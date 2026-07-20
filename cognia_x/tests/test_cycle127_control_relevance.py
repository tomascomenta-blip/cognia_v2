r"""
CYCLE 127 / H-V4-10a — regresión: el CONTROL es la fuente de la RELEVANCIA (abre la rama control/acción). Bajo capacidad
limitada + un distractor irrelevante de alta varianza, el objetivo PREDICCIÓN colapsa el control (modela el distractor
ruidoso) mientras el objetivo CONTROL se mantiene (modela lo accionable; good-regulator).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle127_control_relevance.py -q
"""
from cognia_x.experiments.exp111_control_relevance import run as X


def test_control_is_source_of_relevance_real_run():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["crossover"], sm
    assert sm["pred_collapses"], sm["pred_collapse"]      # la predicción colapsa el control con distractor fuerte
    assert sm["ctrl_holds"], sm["gap_hi"]                 # el control se mantiene


def test_prediction_collapses_only_when_distractor_dominates():
    # a distractor DÉBIL ambos controlan bien; el colapso de la predicción es ESPECÍFICO del distractor fuerte
    grid = X.run(n_seeds=120)
    lo, hi = str(X.S2_SWEEP[0]), str(X.S2_SWEEP[-1])
    assert grid["prediccion"][lo] > 0.8        # distractor débil: predicción modela x1 -> controla bien
    assert grid["prediccion"][hi] < 0.2        # distractor fuerte: predicción modela el distractor -> colapsa
    assert grid["control"][hi] > 0.8           # control se mantiene pase lo que pase con el distractor


def test_control_robust_across_distractor_sweep():
    # el control mantiene perf alta en TODO el barrido (no depende de la varianza del distractor irrelevante)
    grid = X.run(n_seeds=120)
    for s2 in X.S2_SWEEP:
        assert grid["control"][str(s2)] > 0.8, (s2, grid["control"][str(s2)])


def _grid(pred, ctrl):
    ks = [str(s) for s in X.S2_SWEEP]
    return {"prediccion": dict(zip(ks, pred)), "control": dict(zip(ks, ctrl))}


def test_verdict_refutada_if_prediction_does_not_collapse():
    # si la predicción NO colapsa con distractor fuerte -> predecir basta para hallar lo relevante -> refutada
    sm = X.build_summary(_grid(pred=[0.95, 0.94, 0.93, 0.92], ctrl=[0.95, 0.95, 0.95, 0.95]))
    assert not sm["pred_collapses"]
    assert sm["status"] == "refutada", sm["verdict"]
