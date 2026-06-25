r"""
CYCLE 79 / H-V4-6a — regresión: el empowerment es un proxy PARCIAL del valor (marginal-de-controlabilidad).

Protege: (a) empowerment recupera el óptimo cuando control=valor (rho=1) y degrada al desalinearse (rho=0 < rho=1);
(b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle79_empowerment_limits.py -q
"""
from cognia_x.experiments.exp063_empowerment_limits import run as X


def test_empowerment_recovers_when_aligned_and_degrades_when_orthogonal():
    by_rho = X.run(n=40, k=8, n_seeds=16)
    # con control=valor recupera (casi) el optimo
    assert by_rho[1.0]["empowerment"] >= 0.85
    # al desalinearse degrada (rho=0 < rho=1)
    assert by_rho[0.0]["empowerment"] < by_rho[1.0]["empowerment"] - 0.10
    # pero no cae a random (la controlabilidad es parte del valor)
    assert by_rho[0.0]["empowerment"] > by_rho[0.0]["random"]


def _by(hi, mid, lo, neg, rnd):
    return {1.0: {"empowerment": hi, "random": rnd}, 0.7: {"empowerment": mid, "random": rnd},
            0.3: {"empowerment": mid, "random": rnd}, 0.0: {"empowerment": lo, "random": rnd},
            -0.5: {"empowerment": neg, "random": rnd}}


def test_verdict_mixta_partial_proxy():
    by_rho = _by(1.000, 0.85, 0.724, 0.565, 0.431)   # no colapsa a random en rho=0 -> MIXTA
    sm = X.build_summary(by_rho, n=40, k=8)
    assert sm["status"] == "mixta"


def test_verdict_apoyada_collapses_to_random():
    by_rho = _by(0.95, 0.75, 0.50, 0.45, 0.43)        # rho=0 colapsa ~ random (<=random+0.10), swing>0.25
    sm = X.build_summary(by_rho, n=40, k=8)
    assert sm["status"] == "apoyada"


def test_verdict_refutada_universal():
    by_rho = _by(0.97, 0.95, 0.93, 0.90, 0.43)        # ~oracle para todo rho -> universal
    sm = X.build_summary(by_rho, n=40, k=8)
    assert sm["status"] == "refutada"
