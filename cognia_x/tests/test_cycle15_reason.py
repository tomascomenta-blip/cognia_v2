"""
CYCLE 15 — regresión de la competencia GRADUADA (romper el techo perfecto). Asegura que, con dificultad:
  (i)   el ORACLE graduado (mejor cadena por instancia, por el verificador real) cae < 1.0 -> hay techo
        alcanzable real y headroom (retira el caveat "techo sintético perfecto"),
  (ii)  el router VERIFIER aprendido le GANA a la mejor cadena fija graduada,
  (iii) el router VERIFIER NO supera al oráculo (sanity: no se puede pasar el techo).
Determinista por semillas fijas (gen_graded + patinazo por (cadena,instancia)).
"""
from cognia_x.reason.problems import gen_graded, is_correct, TYPES
from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.router import Router


def _acc_fixed_graded(chain, problems):
    return sum(1 for p in problems if is_correct(p, graded_chain(chain, p)[0])) / len(problems)


def _acc_oracle_graded(problems):
    ok = sum(1 for p in problems if any(is_correct(p, graded_chain(c, p)[0]) for c in CHAINS))
    return ok / len(problems)


def _eval_router_graded(router, problems):
    router.explore = False
    return sum(1 for p in problems if is_correct(p, graded_chain(router.select(p["type"]), p)[0])) / len(problems)


def test_graded_oracle_below_one():
    test = gen_graded(2000, seed=42_000)
    oracle = _acc_oracle_graded(test)
    assert oracle < 1.0, f"el oráculo graduado deberia ser <1.0 (techo roto), dio {oracle:.3f}"
    assert oracle > 0.5, f"oráculo sospechosamente bajo {oracle:.3f} (setup roto)"


def test_router_beats_best_fixed_under_grading():
    train = gen_graded(4000, seed=42)
    test = gen_graded(2000, seed=42_000)   # semilla disjunta -> held-out
    rv = Router(list(CHAINS), mode="verifier", eps=0.15, seed=42, graded=True)
    for p in train:
        rv.train_one(p)
    acc_rv = _eval_router_graded(rv, test)
    best_fixed = max(_acc_fixed_graded(c, test) for c in CHAINS)
    assert acc_rv > best_fixed, f"router graduado {acc_rv:.3f} no supera a la mejor cadena fija {best_fixed:.3f}"


def test_router_cannot_beat_oracle():
    train = gen_graded(4000, seed=7)
    test = gen_graded(2000, seed=17_000)
    rv = Router(list(CHAINS), mode="verifier", eps=0.15, seed=7, graded=True)
    for p in train:
        rv.train_one(p)
    acc_rv = _eval_router_graded(rv, test)
    oracle = _acc_oracle_graded(test)
    assert acc_rv <= oracle, f"router {acc_rv:.3f} superó al oráculo {oracle:.3f} (imposible: techo)"
