r"""
CYCLE 89 / H-V4-7g — regresión: la política R-VALOR del gap #2 sobrevive el salto a un VERIFICADOR CHEQUEABLE REAL
(sandbox exp018, valor discreto). Protege: (a) en la corrida real, strong no-regret + weak recover + greedy sin trampa
+ aprendizaje vivo -> APOYADA; (b) el sandbox real decide el valor (no un g sintético); (c) las ramas del veredicto
(apoyada / refutada por valor discreto que rompe el aprendizaje / mixta). Rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle89_real_verifier_value.py -q
"""
from cognia_x.experiments.exp073_real_verifier_value import run as X
from cognia_x.experiments.exp018_real_verifier import expression_task as E


def test_real_sandbox_decides_value():
    # el valor lo decide el verificador REAL (ejecuta), no una fórmula: '3*4'->12 ok; echo '12' sin op -> strong no
    assert E.is_real_solution(b"12=", b"3*4\n")
    assert not E.is_real_solution(b"12=", b"12\n")        # echo: weak sí, strong no
    assert E.verify(b"12=", b"12\n", strong=False)
    assert not E.verify(b"12=", b"5+8\n", strong=False)   # valor 13 != 12


def test_policy_survives_real_verifier_real_run():
    grid = X.run(n=50, k_budget=10, k_eval=10, T=30, E_rounds=12, eps=0.3, sc=0.5, n_seeds=12)
    sm = X.build_summary(grid)
    # strong: el producto es Bayes-óptimo (E[v]=c·r) y el aprendido lo iguala (no-regret)
    assert sm["no_regret_ok"], sm["noregret_strong"]
    # weak: el producto mis-rankea los echoes y el aprendido recupera (relevancia-dominancia)
    assert sm["recover_ok"], sm["recover_weak"]
    # el feedback discreto no rompe el aprendizaje y greedy no se atrapa
    assert sm["learning_alive"]
    assert sm["no_trap"], (sm["greedy_trap_strong"], sm["greedy_trap_weak"])
    assert sm["status"] == "apoyada"


def _cell(prod, greedy, explore, rnd, oracle, chance):
    return {"product": prod, "learned_greedy": greedy, "learned_explore": explore,
            "learned_random": rnd, "oracle": oracle, "chance": chance}


def _grid(strong, weak):
    return {"strong": _cell(*strong), "weak": _cell(*weak)}


def test_verdict_apoyada():
    # strong no-regret (Δ -0.011), weak recover (+0.106), no trap, alive
    sm = X.build_summary(_grid(strong=(0.615, 0.604, 0.605, 0.604, 1.0, 0.26),
                               weak=(0.779, 0.885, 0.889, 0.887, 1.0, 0.50)))
    assert sm["status"] == "apoyada"
    assert sm["no_regret_ok"] and sm["recover_ok"] and sm["no_trap"] and sm["learning_alive"]


def test_verdict_refutada_discrete_breaks_learning():
    # el valor discreto rompe el aprendizaje: learned ≈ chance -> no learning_alive -> refutada
    sm = X.build_summary(_grid(strong=(0.30, 0.28, 0.28, 0.28, 1.0, 0.26),
                               weak=(0.52, 0.53, 0.53, 0.53, 1.0, 0.50)))
    assert not sm["learning_alive"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial():
    # no-regret en strong pero la recuperación weak NO cruza +0.03 -> mixta
    sm = X.build_summary(_grid(strong=(0.615, 0.604, 0.605, 0.604, 1.0, 0.26),
                               weak=(0.80, 0.81, 0.81, 0.82, 1.0, 0.50)))
    assert not sm["recover_ok"]
    assert sm["status"] == "mixta"
