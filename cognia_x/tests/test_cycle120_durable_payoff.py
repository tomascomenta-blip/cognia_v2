r"""
CYCLE 120 / H-V4-8z — regresión: el selector durable solo (sin ancla) mejora calibración+yield pero no el downstream;
calibración y capacidad son ejes separados. El lazo usa torch (lento) -> se protege la LÓGICA del veredicto; el run real se
verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle120_durable_payoff.py -q
"""
from cognia_x.experiments.exp104_durable_payoff import run as X


def _seed(real_n, real_d, yld_n, yld_d, corr_n, corr_d):
    return {"hist": {"naive": {"real": [0.3] + real_n, "yield": yld_n, "corr": corr_n},
                     "durable": {"real": [0.3] + real_d, "yield": yld_d, "corr": corr_d}},
            "base": {"real_acc": 0.3}}


def test_verdict_refutada_no_downstream_payoff():
    # durable mejora corr+yield pero no el downstream -> refutada
    per = [_seed([0.05, 0.04], [0.04, 0.03], [7, 7], [10, 10], [0.3, 0.13], [0.3, 0.53]),
           _seed([0.06, 0.05], [0.05, 0.03], [7, 6], [10, 9], [0.3, 0.14], [0.3, 0.52])]
    sm = X.build_summary(per)
    assert sm["corr_final_durable"] > sm["corr_final_naive"]   # calibración mejor
    assert sm["yield_durable"] > sm["yield_naive"]             # yield mejor
    assert not sm["sustains_better"]                           # pero downstream no
    assert sm["status"] == "refutada"


def test_verdict_apoyada_if_downstream_sustained():
    # caso hipotético: durable sostiene el downstream -> apoyada
    per = [_seed([0.10, 0.12], [0.20, 0.30], [7, 7], [10, 10], [0.3, 0.13], [0.3, 0.53]),
           _seed([0.11, 0.13], [0.22, 0.32], [7, 6], [10, 9], [0.3, 0.14], [0.3, 0.52])]
    sm = X.build_summary(per)
    assert sm["sustains_better"]
    assert sm["status"] == "apoyada"
