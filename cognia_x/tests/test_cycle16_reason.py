"""
CYCLE 16 — regresión de rutear desde el TEXTO (sin la muleta del tipo). Asegura que:
  (i)   features() depende SOLO del texto: su firma toma `text`, y dos problemas con el MISMO texto-relevante
        rutean a la misma firma sin importar type/answer (el router no puede mirar type/answer).
  (ii)  el router de TEXTO (infiere la clase del enunciado) le GANA a la mejor cadena fija en held-out.
  (iii) el router de TEXTO alcanza >= 0.9× del router de TIPO (CYCLE 12, le DAN la etiqueta): infirió bien.
Determinista por semillas fijas.
"""
import inspect

from cognia_x.reason.problems import gen_problems, is_correct, TYPES
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router
from cognia_x.reason.text_router import TextRouter, features, signature


def _acc_fixed(chain, problems):
    return sum(1 for p in problems if is_correct(p, CHAINS[chain](p)[0])) / len(problems)


def _eval_type_router(router, problems):
    router.explore = False
    acc = sum(1 for p in problems if is_correct(p, CHAINS[router.select(p["type"])](p)[0])) / len(problems)
    router.explore = True
    return acc


def test_features_only_depend_on_text():
    # la firma de features() es features(text): un solo argumento de texto (no type/answer)
    params = list(inspect.signature(features).parameters)
    assert params == ["text"], f"features() debe tomar solo 'text', toma {params}"
    # mismo texto-relevante -> misma firma, sin importar type/answer (no puede haberlos leído)
    txt = "5 amigos comen, la cuenta es $80.00 y dejan 10% de propina. ¿Cuánto paga cada uno?"
    p_a = {"type": "split_bill", "text": txt, "answer": 17.6, "params": {}}
    p_b = {"type": "OTRO_TIPO_FALSO", "text": txt, "answer": -999.0, "params": {}}
    assert signature(p_a["text"]) == signature(p_b["text"])


def test_text_router_beats_best_fixed():
    train = gen_problems(4000, seed=3)
    test = gen_problems(2000, seed=33_000)   # semilla disjunta -> held-out
    tr = TextRouter(list(CHAINS), eps=0.15, seed=3)
    for p in train:
        tr.train_one(p)
    acc_text = tr.eval(test)
    best_fixed = max(_acc_fixed(c, test) for c in CHAINS)
    assert acc_text > best_fixed, f"router de texto {acc_text:.3f} no supera la mejor cadena fija {best_fixed:.3f}"


def test_text_router_close_to_type_router():
    train = gen_problems(4000, seed=5)
    test = gen_problems(2000, seed=55_000)
    # router de TIPO (le DAN la etiqueta) = referencia superior
    rt = Router(list(CHAINS), mode="verifier", eps=0.15, seed=5)
    for p in train:
        rt.train_one(p)
    acc_type = _eval_type_router(rt, test)
    # router de TEXTO (infiere del enunciado)
    tr = TextRouter(list(CHAINS), eps=0.15, seed=5)
    for p in train:
        tr.train_one(p)
    acc_text = tr.eval(test)
    assert acc_text >= 0.9 * acc_type, f"router de texto {acc_text:.3f} < 0.9× del router de tipo {acc_type:.3f}"
