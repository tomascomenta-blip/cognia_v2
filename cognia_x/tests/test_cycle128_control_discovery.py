r"""
CYCLE 128 / H-V4-10b — regresión: el control DESCUBRE la relevancia actuando. Estimando |b̂| por modo (cuánto responde cada
dimensión a la acción), el agente descubre qué es controlable SIN que se le diga; con data suficiente iguala al oracle y
vence a la predicción que colapsa; con poca data el distractor ruidoso confunde (R-INTERVENCIÓN medida). Cierra el caveat 127.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle128_control_discovery.py -q
"""
from cognia_x.experiments.exp112_control_discovery import run as X


def test_relevance_discoverable_by_acting_real_run():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["discovery_matches_oracle"], sm
    assert sm["discovery_picks_right"], sm["disc_pick_hi"]


def test_discovery_matches_oracle_beats_prediction_with_enough_data():
    grid = X.run(n_seeds=120)
    hiT = str(X.T_SWEEP[-1]); hs2 = str(X.S2_SWEEP[-1])
    disc = grid[hiT]["control_discovery"][hs2]["perf"]
    orac = grid[hiT]["control_oracle"][hs2]["perf"]
    pred = grid[hiT]["prediccion"][hs2]["perf"]
    assert abs(disc - orac) < 0.15, (disc, orac)        # discovery ≈ oracle (descubre la partición)
    assert disc > pred + 0.3, (disc, pred)              # ...y vence a la predicción que colapsa
    assert grid[hiT]["control_discovery"][hs2]["pick1"] > 0.9   # elige el modo controlable correcto


def test_discovery_needs_enough_interventional_data():
    # con POCA data, el distractor ruidoso confunde la estimación de controlabilidad (R-INTERVENCIÓN medida)
    grid = X.run(n_seeds=120)
    loT, hiT = str(X.T_SWEEP[0]), str(X.T_SWEEP[-1]); hs2 = str(X.S2_SWEEP[-1])
    disc_lo = grid[loT]["control_discovery"][hs2]["perf"]
    disc_hi = grid[hiT]["control_discovery"][hs2]["perf"]
    pick_lo = grid[loT]["control_discovery"][hs2]["pick1"]
    assert disc_hi - disc_lo > 0.2, (disc_hi, disc_lo)   # más data interventiva ayuda a descubrir
    assert pick_lo < grid[hiT]["control_discovery"][hs2]["pick1"]   # poca data -> peor acierto del modo correcto


def _grid_T(pred, orac, disc, disc_pick):
    ks = [str(s) for s in X.S2_SWEEP]
    return {"prediccion": {k: {"perf": pred[i], "pick1": 1.0} for i, k in enumerate(ks)},
            "control_oracle": {k: {"perf": orac[i], "pick1": 1.0} for i, k in enumerate(ks)},
            "control_discovery": {k: {"perf": disc[i], "pick1": disc_pick[i]} for i, k in enumerate(ks)}}


def test_verdict_refutada_if_discovery_collapses():
    # si discovery colapsa como la predicción (no recupera el modo controlable) -> refutada
    coll = [0.99, 0.99, 0.0, 0.0]; rob = [0.99, 0.99, 0.99, 0.99]; pk = [1.0, 1.0, 0.5, 0.3]
    grid = {str(X.T_SWEEP[0]): _grid_T(coll, rob, coll, pk), str(X.T_SWEEP[-1]): _grid_T(coll, rob, coll, pk)}
    sm = X.build_summary(grid)
    assert not sm["discovery_matches_oracle"]
    assert sm["status"] == "refutada", sm["verdict"]
