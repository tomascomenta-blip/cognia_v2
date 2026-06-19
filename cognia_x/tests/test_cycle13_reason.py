"""
CYCLE 13 — regresion de la robustez en el regimen REALISTA. Asegura que:
  (i)   el tipo NUEVO (discount_better) tiene una cadena que lo resuelve perfecto,
  (ii)  bajo oraculo RUIDOSO, robust-aggregate (vota K) >= blind-single (confia ciego) en held-out,
  (iii) la ask-rate del router sube en el tipo NUEVO (OOD) vs un tipo familiar (sabe que no sabe).
"""
from random import Random

from cognia_x.reason.problems import gen_problems, is_correct, TYPES, OOD_TYPE
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router


def _eval(router, problems):
    router.explore = False
    return sum(1 for p in problems if is_correct(p, CHAINS[router.deploy_chain(p["type"])](p)[0])) / len(problems)


def test_new_type_has_a_correct_chain():
    probs = gen_problems(400, seed=1, types=[OOD_TYPE])
    assert probs and all(p["type"] == OOD_TYPE for p in probs)
    # debe existir al menos una cadena que resuelva TODOS los del tipo nuevo
    assert any(all(is_correct(p, CHAINS[c](p)[0]) for p in probs) for c in CHAINS), \
        "ninguna cadena resuelve perfecto el tipo nuevo discount_better"


def _train_noisy(mode, train, test, p_noise, k, seed):
    r = Router(list(CHAINS), mode="verifier", eps=0.15, seed=seed)
    rng = Random(seed + 7)
    for p in train:
        r.solve_noisy(p, mode=mode, p_noise=p_noise, k=k, rng=rng)
    return _eval(r, test)


def test_robust_aggregate_at_least_as_good_as_blind_under_noise():
    train = gen_problems(2000, seed=2)
    test = gen_problems(1000, seed=12_000)   # held-out, semilla disjunta
    p_noise, k, seeds = 0.3, 5, 8
    # promedio sobre semillas: 'confiar ciego' es estocastico -> comparar el comportamiento ESPERADO
    blind = sum(_train_noisy("blind", train, test, p_noise, k, 2 + i * 101) for i in range(seeds)) / seeds
    aggr = sum(_train_noisy("aggregate", train, test, p_noise, k, 2 + i * 101) for i in range(seeds)) / seeds
    assert aggr >= blind, f"robust-aggregate {aggr:.3f} no supera a blind-single {blind:.3f} bajo ruido"


def test_ood_ask_rate_higher_than_familiar():
    train = gen_problems(2000, seed=4)
    fam = gen_problems(600, seed=14_000)                       # tipos familiares (held-out)
    ood = gen_problems(600, seed=24_000, types=[OOD_TYPE])     # tipo NUEVO (nunca entrenado)
    r = Router(list(CHAINS), mode="verifier", eps=0.15, seed=4)
    for p in train:
        r.train_one(p)        # ya competente en los familiares (mucha evidencia)
    rng = Random(99)
    stream = list(fam) + list(ood)
    rng.shuffle(stream)
    budget = 400
    asks = {t: [0, 0] for t in (list(TYPES) + [OOD_TYPE])}
    for p in stream:
        _, _, asked, budget = r.solve_ood(p, ask_budget=budget, min_obs=8, p_noise=0.0, k=5, rng=rng)
        asks[p["type"]][1] += 1
        if asked:
            asks[p["type"]][0] += 1
    rate = {t: (a / n if n else 0.0) for t, (a, n) in asks.items()}
    fam_rate = max(rate[t] for t in TYPES)
    assert rate[OOD_TYPE] > fam_rate, \
        f"ask-rate OOD {rate[OOD_TYPE]:.3f} no supera a familiar {fam_rate:.3f}"
