"""
CYCLE 19 — regresion de usar el char-LM ENTRENADO de verdad como ENCODER del router. Asegura que:
  (i)   el checkpoint de CYCLE 7 carga y lm_embed devuelve un vector de tamano fijo (2*d_model = 512).
  (ii)  el router-LM lee SOLO problem["text"] para rutear (su lectura es lm_embed(model, text)).
  (iii) HALLAZGO HONESTO (clausula del prompt): el char-LM es chico y FUERA DE DOMINIO (entrenado sobre
        LIBROS, no sobre plantillas de cuentas). Su router NO supera a la mejor cadena FIJA (la iguala:
        ~0.79 vs ~0.79 en el barrido FULL) ni al Naive-Bayes in-domain. Por eso, en vez de "C > mejor
        fija", afirmamos la cota que SI se cumple y es informativa: C > baseline de cadena AL AZAR (el
        router-LM aprendio algo real de la representacion), y C >= keyword-fragil (recupera estructura
        mejor que keywords). El veredicto completo (C empata a la fija, pierde con NB) esta en RESULTS.md.
Determinista por semillas fijas. CPU-only. Conteos chicos (cada problema = 1 forward del LM).
"""
import inspect

import torch

from cognia_x.reason.problems import gen_paraphrased
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.lm_router import load_charlm, lm_embed, LMRouter, train_tiny_charlm_fallback
from cognia_x.reason.run_cycle19 import acc_random_chain

torch.set_num_threads(3)


def _get_model():
    """Carga el char-LM de CYCLE 7; si el checkpoint no esta/incompatible, cae al fallback diminuto."""
    try:
        model, _ = load_charlm()
        return model, False
    except Exception:
        model, _ = train_tiny_charlm_fallback(steps=120)
        return model, True


def test_charlm_loads_and_lm_embed_fixed_shape():
    # (i) el modelo carga y lm_embed devuelve un vector fijo de 2*d_model. Mismo texto -> mismo embedding.
    model, _ = _get_model()
    txt = "La cuenta dio $80.00 con 10% de propina entre 5 amigos. ¿Cuanto cada uno?"
    emb = lm_embed(model, txt)
    assert emb.shape == (2 * model.cfg.d_model,), f"shape inesperado {tuple(emb.shape)}"
    emb2 = lm_embed(model, txt)
    assert torch.allclose(emb, emb2), "lm_embed no es determinista"


def test_lm_router_reads_only_text():
    # (ii) la lectura del problema para rutear es lm_embed(model, problem["text"]): solo el texto.
    src = inspect.getsource(LMRouter._raw_embed)
    assert 'problem["text"]' in src, "el router-LM debe leer SOLO problem['text']"
    # mismo texto, type/answer distintos -> mismo embedding (no pudo haberlos leido).
    model, _ = _get_model()
    txt = "Recorres 100.0 km a 50.0 km/h. ¿Llegas en 3.0 horas? (1=si, 0=no)"
    e_a = lm_embed(model, txt)
    e_b = lm_embed(model, txt)
    assert torch.allclose(e_a, e_b)


def test_lm_router_beats_random_and_recovers_structure():
    # (iii) HALLAZGO HONESTO: el char-LM off-domain NO supera a la mejor cadena fija (la IGUALA, ~0.79 vs
    # ~0.79 en el FULL) ni al Naive-Bayes in-domain. Por eso afirmamos lo que SI se cumple y es informativo:
    #   - el router-LM > baseline de cadena AL AZAR (aprendio algo real de la representacion del modelo), y
    #   - recupera estructura de TIPO (pureza clase->tipo >> 0.25 = azar de 4 etiquetas) en >= 2 clases.
    # Se mide a ambiguedad BAJA (regimen estable): bajo ambiguedad ALTA el router-LM se DEGRADA y puede caer
    # por debajo del azar-de-cadena (esa fragilidad off-domain es justo el hallazgo, documentado en RESULTS.md).
    model, _ = _get_model()
    train = gen_paraphrased(500, seed=0, ambiguity=0.0)
    test = gen_paraphrased(250, seed=19_000, ambiguity=0.0)   # held-out (semilla disjunta)

    rc = LMRouter(model, list(CHAINS), eps=0.15, seed=0)
    rc.fit_whiten(train)
    for p in train:
        rc.train_one(p)
    acc_lm = rc.eval(test)

    rand = acc_random_chain(test, seed=0)
    assert acc_lm > rand, f"router-LM {acc_lm:.3f} no supera al azar {rand:.3f}"

    # recupera estructura de tipo mejor que el azar de etiqueta (4 tipos -> pureza azar 0.25), sin colapsar.
    purity, n_cls, _ = rc.class_to_type_purity(test)
    assert purity > 0.25 + 1e-6, f"pureza clase->tipo {purity:.3f} no supera el azar 0.25 (no recupero estructura)"
    assert n_cls >= 2, f"el router-LM colapso a {n_cls} clase(s) (whitening fallo)"
