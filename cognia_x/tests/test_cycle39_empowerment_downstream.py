r"""
CYCLE 39 / H-V4-1d — regresión: el empowerment como VALOR mejora una tarea (exp025).

Protege el hallazgo: bajo capacidad LIMITADA, asignar por empowerment logra la tarea; por predictibilidad
falla (peor que el azar); a capacidad plena todas empatan.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle39_empowerment_downstream.py -q
"""
from cognia_x.experiments.exp025_empowerment_downstream import run as E


def _fast():
    return E.run(K=4, eta=0.05, n_ctrl=4, n_clock=4, n_rand=4, samples=2500, caps=[4, 12], seeds=6)


def test_empowerment_beats_predictability_at_limited_capacity():
    _, s = _fast()
    d = s["by_cap"]["4"]
    assert d["empowerment"]["score_mean"] > 0.9           # logra la tarea
    assert d["empowerment"]["score_mean"] - d["predictibilidad"]["score_mean"] > 0.3
    assert s["verdict"] == "apoyada"


def test_predictability_is_anti_useful():
    _, s = _fast()
    d = s["by_cap"]["4"]
    # elegir lo predecible (el reloj) es PEOR que el azar para una tarea de control
    assert d["predictibilidad"]["score_mean"] <= d["azar"]["score_mean"] + 1e-9


def test_no_advantage_at_full_capacity():
    _, s = _fast()
    d = s["by_cap"]["12"]
    # con capacidad plena (k=D) la estrategia no importa: todas resuelven
    assert d["empowerment"]["score_mean"] > 0.99
    assert d["predictibilidad"]["score_mean"] > 0.99


def test_reproducible():
    a = E.run(K=4, eta=0.05, n_ctrl=4, n_clock=4, n_rand=4, samples=2000, caps=[4], seeds=4)[1]
    b = E.run(K=4, eta=0.05, n_ctrl=4, n_clock=4, n_rand=4, samples=2000, caps=[4], seeds=4)[1]
    assert a["by_cap"]["4"]["empowerment"]["score_mean"] == b["by_cap"]["4"]["empowerment"]["score_mean"]
    assert a["verdict"] == b["verdict"]
