"""
CYCLE 14 — regresion del COMPOSER (encadenar cadenas en un programa multi-paso). Asegura que:
  (i)   al menos un tipo compuesto se resuelve perfecto por ALGÚN programa de 2 cadenas pero por NINGUNA
        cadena de un solo paso al 1.0 (la composición es NECESARIA),
  (ii)  el composer aprendido (verificador real) supera a la mejor cadena fija de un paso en held-out,
  (iii) el composer-confianza (circular) rinde PEOR que el composer-verificador (secuestro del fanfarrón).
"""
from cognia_x.reason.problems import gen_composed, is_correct, COMPOSED_TYPES
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.composer import Composer, run_program, enumerate_programs


def _acc_fixed_single(chain, problems):
    return sum(1 for p in problems if is_correct(p, CHAINS[chain](p)[0])) / len(problems)


def _eval_composer(comp, problems):
    comp.explore = False
    return sum(1 for p in problems if is_correct(p, run_program(p, comp.deploy(p["type"]))[0])) / len(problems)


def test_composed_needs_two_chains_no_single_solves():
    probs = gen_composed(600, seed=1)
    progs2 = [pr for pr in enumerate_programs(2) if len(pr) == 2]
    singles = list(CHAINS)
    solved_by_two = False
    for t in COMPOSED_TYPES:
        pl = [p for p in probs if p["type"] == t]
        assert pl, f"no se generaron problemas compuestos de tipo {t}"
        # NINGUNA cadena de un paso lo resuelve perfecto
        assert not any(all(is_correct(p, CHAINS[c](p)[0]) for p in pl) for c in singles), \
            f"una cadena de UN paso resuelve perfecto {t} (la composición no sería necesaria)"
        # pero SÍ existe un programa de 2 cadenas que lo resuelve perfecto
        if any(all(is_correct(p, run_program(p, pr)[0]) for p in pl) for pr in progs2):
            solved_by_two = True
    assert solved_by_two, "ningún tipo compuesto es resoluble por un programa de 2 cadenas"


def test_composer_beats_best_single_chain_held_out():
    train = gen_composed(2000, seed=2)
    test = gen_composed(1000, seed=12_000)   # semilla disjunta -> held-out
    cv = Composer(max_len=2, mode="verifier", eps=0.15, seed=2)
    for p in train:
        cv.train_one(p)
    acc_comp = _eval_composer(cv, test)
    best_single = max(_acc_fixed_single(c, test) for c in CHAINS)
    assert acc_comp > best_single, f"composer {acc_comp:.3f} no supera a la mejor cadena fija {best_single:.3f}"


def test_confidence_composer_worse_than_verifier():
    train = gen_composed(2000, seed=3)
    test = gen_composed(1000, seed=13_000)
    cv = Composer(max_len=2, mode="verifier", eps=0.15, seed=3)
    cc = Composer(max_len=2, mode="confidence", eps=0.15, seed=3)
    for p in train:
        cv.train_one(p); cc.train_one(p)
    acc_cv = _eval_composer(cv, test)
    acc_cc = _eval_composer(cc, test)
    assert acc_cc < acc_cv, f"confianza {acc_cc:.3f} no es peor que verificador {acc_cv:.3f}"
