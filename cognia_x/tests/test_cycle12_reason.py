"""
CYCLE 12 — regresion del loop meta-razonador.
Asegura que: (i) cada tipo tiene una cadena que lo resuelve bien, (ii) el router entrenado con el
verificador iguala o supera a la mejor cadena fija en held-out, (iii) el router-confianza (circular)
rinde PEOR que el router-verificador (secuestro del fanfarrón).
"""
from cognia_x.reason.problems import gen_problems, is_correct, TYPES
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router


def _acc_fixed(chain, problems):
    return sum(1 for p in problems if is_correct(p, CHAINS[chain](p)[0])) / len(problems)


def _eval_router(router, problems):
    router.explore = False
    return sum(1 for p in problems if is_correct(p, CHAINS[router.select(p["type"])](p)[0])) / len(problems)


def test_each_type_has_a_correct_chain():
    probs = gen_problems(400, seed=1)
    by_type = {t: [p for p in probs if p["type"] == t] for t in TYPES}
    for t, plist in by_type.items():
        assert plist, f"no se generaron problemas de tipo {t}"
        # debe existir al menos una cadena que resuelva TODOS los de ese tipo
        assert any(all(is_correct(p, CHAINS[c](p)[0]) for p in plist) for c in CHAINS), \
            f"ningun cadena resuelve perfecto el tipo {t}"


def test_verifier_router_beats_best_fixed():
    train = gen_problems(2000, seed=2)
    test = gen_problems(1000, seed=12_000)   # semilla disjunta -> held-out
    rv = Router(list(CHAINS), mode="verifier", eps=0.15, seed=2)
    for p in train:
        rv.train_one(p)
    acc_rv = _eval_router(rv, test)
    best_fixed = max(_acc_fixed(c, test) for c in CHAINS)
    assert acc_rv >= best_fixed, f"router verifier {acc_rv} < mejor fija {best_fixed}"


def test_confidence_router_worse_than_verifier():
    train = gen_problems(2000, seed=3)
    test = gen_problems(1000, seed=13_000)
    rv = Router(list(CHAINS), mode="verifier", eps=0.15, seed=3)
    rc = Router(list(CHAINS), mode="confidence", eps=0.15, seed=3)
    for p in train:
        rv.train_one(p); rc.train_one(p)
    acc_rv = _eval_router(rv, test)
    acc_rc = _eval_router(rc, test)
    assert acc_rc < acc_rv, f"confianza {acc_rc} no es peor que verificador {acc_rv}"
