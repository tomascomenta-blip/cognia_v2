r"""
CYCLE 38 / H-V4-1c — regresión del empowerment (exp024).

Falla SIN la implementación correcta y pasa CON ella. Protege la INVERSIÓN clave:
- el EMPOWERMENT aísla el factor CONTROLABLE (y da ~0 al reloj y al azar),
- la PREDICCIÓN pasiva hace lo contrario (se queda con el reloj, pierde el controlable).
También protege que Blahut-Arimoto da capacidades sanas y que es CPU-barato y reproducible.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle38_empowerment.py -q
"""
import numpy as np

from cognia_x.experiments.exp024_empowerment import run as E


def test_blahut_arimoto_known_capacities():
    # canal identidad KxK -> capacidad = log2(K)
    K = 4
    ident = np.eye(K)
    assert abs(E.blahut_arimoto(ident) - np.log2(K)) < 1e-3
    # canal que ignora la entrada (todas las filas iguales) -> capacidad 0
    flat = np.ones((K, K)) / K
    assert E.blahut_arimoto(flat) < 1e-3


def test_empowerment_isolates_controllable():
    _, s = E.run(K=4, eta=0.05, n_factors=2, samples=8000, seeds=4)
    bk = s["by_kind"]
    # empowerment: alto en controlable, ~0 en reloj y azar
    assert bk["ctrl"]["emp_mean"] > 1.2
    assert bk["clock"]["emp_mean"] < 0.2
    assert bk["rand"]["emp_mean"] < 0.2


def test_passive_prediction_locks_clock_inversion():
    _, s = E.run(K=4, eta=0.05, n_factors=2, samples=8000, seeds=4)
    bk = s["by_kind"]
    # predicción pasiva: alta en reloj, ~0 en controlable (la INVERSIÓN)
    assert bk["clock"]["pred_mean"] > 1.2
    assert bk["ctrl"]["pred_mean"] < 0.2
    assert s["verdict"] == "apoyada"


def test_cheap_and_reproducible():
    a = E.run(K=4, eta=0.05, n_factors=1, samples=4000, seeds=3)[1]
    b = E.run(K=4, eta=0.05, n_factors=1, samples=4000, seeds=3)[1]
    assert a["by_kind"]["ctrl"]["emp_mean"] == b["by_kind"]["ctrl"]["emp_mean"]
    assert a["verdict"] == b["verdict"]
