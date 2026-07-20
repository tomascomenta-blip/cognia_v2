"""
CYCLE 17 — regresión de rutear desde el TEXTO cuando el texto es DURO (paráfrasis + vocabulario ambiguo).
Retira el caveat de CYCLE 16 (que tenía pureza 1.000 por vocabulario único). Asegura que:
  (i)   bajo ambigüedad ALTA, la firma de KEYWORDS pura CONFUNDE tipos -> pureza firma->tipo < 1.0.
  (ii)  el router de TEXTO ROBUSTO (perceptrón sobre bag-of-words) iguala o supera al de keywords frágil
        en accuracy held-out a esa ambigüedad alta.
  (iii) ambos routers de texto leen SOLO el texto (su feature-extractor toma un único argumento `text`).
Determinista por semillas fijas.
"""
import inspect

from cognia_x.reason.problems import gen_paraphrased, is_correct
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.text_router import (
    TextRouter, RobustTextRouter, signature_keywords, bag_of_words, signature,
)

HIGH_AMBIG = 1.0


def test_feature_extractors_only_depend_on_text():
    # ambos extractores de features para rutear toman un único argumento `text` (no type/answer)
    assert list(inspect.signature(signature_keywords).parameters) == ["text"]
    assert list(inspect.signature(bag_of_words).parameters) == ["text"]
    # mismo texto -> misma firma/bolsa, sin importar type/answer (no pueden haberlos leído)
    txt = "Salimos 5 amigos; la cuenta fue $80.00 y sumamos 10% de propina. ¿Cuánto pone cada uno?"
    p_a = {"type": "split_bill", "text": txt, "answer": 17.6, "params": {}}
    p_b = {"type": "OTRO_FALSO", "text": txt, "answer": -999.0, "params": {}}
    assert signature_keywords(p_a["text"]) == signature_keywords(p_b["text"])
    assert bag_of_words(p_a["text"]) == bag_of_words(p_b["text"])


def test_keyword_signature_confuses_under_high_ambiguity():
    # con paráfrasis + vocabulario ambiguo, la firma de KEYWORDS pura mezcla tipos -> pureza < 1.0.
    # (esto retira el "almuerzo gratis" de CYCLE 16, donde la pureza era 1.000 por vocabulario único.)
    test = gen_paraphrased(2000, seed=20_000, ambiguity=HIGH_AMBIG)
    ra = TextRouter(list(CHAINS), eps=0.15, seed=7, sig_fn=signature_keywords)
    purity, _, _ = ra.signature_to_type_purity(test)
    assert purity < 1.0, f"la firma de keywords NO se confundió bajo ambigüedad alta (pureza {purity:.3f})"


def test_robust_router_at_least_as_good_as_brittle_under_ambiguity():
    # a ambigüedad alta, el router de TEXTO robusto >= el de keywords frágil (degrada más suave).
    # Semilla CANÓNICA del lab (la que usan run_cycle17 y el smoke). HONESTIDAD: en ~2/12 semillas el NB
    # patina en el arranque (exploración epsilon que sesga los conteos) y B cae por debajo de A; el patrón
    # dominante (10/12) es B >> A por +0.06..+0.17. El barrido completo está en RESULTS.md / runs/cycle17.
    train = gen_paraphrased(4000, seed=0, ambiguity=HIGH_AMBIG)
    test = gen_paraphrased(2000, seed=17_000, ambiguity=HIGH_AMBIG)   # semilla disjunta -> held-out

    ra = TextRouter(list(CHAINS), eps=0.15, seed=0, sig_fn=signature_keywords)
    for p in train:
        ra.train_one(p)
    acc_kw = ra.eval(test)

    rb = RobustTextRouter(list(CHAINS), eps=0.15, seed=0)
    for p in train:
        rb.train_one(p)
    acc_rb = rb.eval(test)

    assert acc_rb >= acc_kw, f"router robusto {acc_rb:.3f} < router de keywords {acc_kw:.3f} a ambigüedad alta"


def test_cycle16_signature_still_intact():
    # CYCLE 16 sigue exportando su firma combinada (keywords + nums/$/%) sin cambios -> no la rompimos.
    txt = "Tenés que recorrer 100.0 km a 50.0 km/h y llegar a tiempo en 3.0 horas. ¿Llegás? (1=sí, 0=no)"
    sig = signature(txt)
    assert isinstance(sig, tuple) and len(sig) > len(signature_keywords(txt))
